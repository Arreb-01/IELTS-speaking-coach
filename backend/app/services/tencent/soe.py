"""腾讯云智聆口语评测（新版）适配器。

2026-08 真机校准（scripts/tencent_soe_probe.py，账号已开通并持有 1 万次资源包）：
- 录音评测模式：wss://soe.cloud.tencent.com/soe/api/{appid}?<参数>&signature=...
- 签名原文 = soe.cloud.tencent.com/soe/api/{appid}?{除 signature 外按字典序
  排序的 k=v，值不做 urlencode，appid 不参与查询串}，HMAC-SHA1(SecretKey) → base64；
  实际请求中所有 key/value 与 signature 均需 urlencode
- 流程：握手（服务端先回 code=0）→ 一次性 send_binary 整段 WAV →
  发送 {"type":"end"} → 等 final=1
- 参数：rec_mode=1、eval_mode=2(段落,≤120词)、server_engine_type=16k_en、
  voice_format=1、score_coeff=3.0(成人苛刻度 1.0~4.0)
- 返回（final 消息）：result.SuggestedScore/PronAccuracy/PronFluency/
  PronCompletion/Words[{Word,PronAccuracy,MemBeginTime,MemEndTime,...}]
"""

import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import time
import uuid
import wave
from dataclasses import dataclass
from urllib.parse import quote

from app.services.volcengine.evaluation import EvaluationResult, WordScore

logger = logging.getLogger(__name__)

SOE_SIGN_PREFIX = "soe.cloud.tencent.com/soe/api/"
MAX_AUDIO_SECONDS = 60  # rec_mode=1 单段上限
MAX_REF_WORDS = 120  # 段落模式参考文本词数上限

# 账号 APPID 缓存：(secret_id, secret_key) → appid（CAM GetUserAppId 结果）
_appid_cache: dict[tuple[str, str], str] = {}
_appid_lock = asyncio.Lock()


class TencentEvaluationError(Exception):
    pass


@dataclass
class TencentSoeCredentials:
    secret_id: str
    secret_key: str


async def resolve_appid(credentials: TencentSoeCredentials) -> str:
    """查账号数字 APPID（签名与 URL 均需要）。优先 CAM 接口自动获取并缓存。"""
    from app.core.config import get_settings

    settings = get_settings()
    if settings.tencent_appid:
        return settings.tencent_appid

    cache_key = (credentials.secret_id, credentials.secret_key)
    async with _appid_lock:
        if cache_key in _appid_cache:
            return _appid_cache[cache_key]
        try:
            appid = await asyncio.to_thread(_fetch_appid, credentials)
        except Exception as exc:  # noqa: BLE001
            raise TencentEvaluationError(
                f"获取腾讯云账号 APPID 失败（请检查密钥或改在配置里直接填 TENCENT_APPID）：{exc}"
            ) from exc
        _appid_cache[cache_key] = appid
        return appid


def _fetch_appid(credentials: TencentSoeCredentials) -> str:
    from tencentcloud.cam.v20190116.cam_client import CamClient
    from tencentcloud.cam.v20190116 import models as cam_models
    from tencentcloud.common import credential

    client = CamClient(
        credential.Credential(credentials.secret_id, credentials.secret_key), "ap-shanghai"
    )
    return str(client.GetUserAppId(cam_models.GetUserAppIdRequest()).AppId)


def _clip_wav_to_60s(wav: bytes) -> bytes:
    """rec_mode=1 单段上限 60s：用 wave 模块安全截断（非法输入原样返回）。"""
    try:
        with wave.open(io.BytesIO(wav), "rb") as w:
            rate = w.getframerate() or 16000
            limit_frames = rate * MAX_AUDIO_SECONDS
            if w.getnframes() <= limit_frames:
                return wav
            channels, sampwidth, _, _, comptype, _ = w.getparams()
            frames = w.readframes(limit_frames)
        out = io.BytesIO()
        with wave.open(out, "wb") as wo:
            wo.setnchannels(channels)
            wo.setsampwidth(sampwidth)
            wo.setframerate(rate)
            wo.setcomptype(comptype, "NONE")
            wo.writeframes(frames[: len(frames) // (channels * sampwidth) * (channels * sampwidth)])
        return out.getvalue()
    except Exception:  # noqa: BLE001 - wave 解析失败则交给服务端报错
        return wav


def _normalize_100(value, *, scale_if_fractional: bool) -> float | None:
    """腾讯返回流利度/完整度为 0~1 小数、准确度为 0~100 分值；统一到 0~100。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    v = float(value)
    if scale_if_fractional and 0 <= v <= 1:
        return round(v * 100, 1)
    return round(max(min(v, 100), 0), 1)


def _parse_result(result: dict) -> EvaluationResult:
    words = [
        WordScore(
            word=str(item.get("Word") or ""),
            score=_normalize_100(item.get("PronAccuracy"), scale_if_fractional=False),
            start_ms=item.get("MemBeginTime") if isinstance(item.get("MemBeginTime"), int) else None,
            end_ms=item.get("MemEndTime") if isinstance(item.get("MemEndTime"), int) else None,
        )
        for item in result.get("Words") or []
        if isinstance(item, dict) and item.get("Word")
    ]
    accuracy = _normalize_100(result.get("PronAccuracy"), scale_if_fractional=False)
    suggested = _normalize_100(result.get("SuggestedScore"), scale_if_fractional=False)
    # 无语音时腾讯返回全 0 分——视为"无有效评测"而不是 0 分，避免污染 band
    score = next((v for v in (suggested, accuracy) if v is not None and v > 0), None)
    return EvaluationResult(
        # 建议分综合各维度更贴近"该轮发音总评"；缺失时退回准确度
        score=score,
        fluency=_normalize_100(result.get("PronFluency"), scale_if_fractional=True),
        integrity=_normalize_100(result.get("PronCompletion"), scale_if_fractional=True),
        words=words,
        raw={"tencent": True},
    )


async def evaluate_turn(
    wav: bytes,
    ref_text: str,
    credentials: TencentSoeCredentials,
    *,
    timeout: float = 20.0,
) -> EvaluationResult:
    """单轮评测：归档 WAV + 参考文本（该轮 ASR 转写）→ 发音分与词级明细。"""
    import websocket

    appid = await resolve_appid(credentials)
    ref_text = " ".join((ref_text or "").split()[:MAX_REF_WORDS])
    if not ref_text:
        raise TencentEvaluationError("参考文本为空（该轮无 ASR 转写）")

    ts = str(int(time.time()))
    query = {
        "server_engine_type": "16k_en",
        "text_mode": 0,
        "rec_mode": 1,
        "ref_text": ref_text,
        "eval_mode": 2,
        "score_coeff": 3.0,
        "sentence_info_enabled": 1,
        "secretid": credentials.secret_id,
        "voice_format": 1,
        "voice_id": str(uuid.uuid1()),
        "timestamp": ts,
        "nonce": ts,
        "expired": int(time.time()) + 3600,
    }
    sorted_items = sorted(query.items(), key=lambda kv: kv[0])
    signstr = SOE_SIGN_PREFIX + appid + "?" + "&".join(f"{k}={v}" for k, v in sorted_items)
    signature = base64.b64encode(
        hmac.new(credentials.secret_key.encode("utf-8"), signstr.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")
    url = (
        f"wss://soe.cloud.tencent.com/soe/api/{appid}?"
        + "&".join(f"{k}={quote(str(v), safe='')}" for k, v in sorted_items)
        + "&signature="
        + quote(signature, safe="")
    )

    def _call() -> dict:
        ws = websocket.create_connection(url, timeout=timeout)
        try:
            handshake = _recv_json(ws)
            if handshake.get("code") != 0:
                raise TencentEvaluationError(f"{handshake.get('code')}: {handshake.get('message')}")
            ws.send_binary(_clip_wav_to_60s(wav))
            ws.send('{"type":"end"}')
            while True:
                data = json.loads(ws.recv())
                code = data.get("code")
                if code not in (0, None):
                    raise TencentEvaluationError(f"{code}: {data.get('message')}")
                if data.get("final") == 1:
                    return data
        finally:
            ws.close()

    try:
        data = await asyncio.to_thread(_call)
    except TencentEvaluationError:
        raise
    except TimeoutError:
        raise TencentEvaluationError("口语评测请求超时") from None
    except Exception as exc:  # noqa: BLE001
        raise TencentEvaluationError(f"口语评测连接失败：{type(exc).__name__}: {exc}") from exc

    result_root = data.get("result")
    if not isinstance(result_root, dict):
        raise TencentEvaluationError("评测返回缺少 result 字段")
    parsed = _parse_result(result_root)
    if not parsed.ok:
        logger.warning("腾讯云口语评测未返回有效分数：%s", str(data)[:300])
    return parsed


# websocket-client 的 recv 返回 str/bytes，这里统一转 dict
def _recv_json(ws) -> dict:
    frame = ws.recv()
    if isinstance(frame, bytes):
        frame = frame.decode("utf-8")
    return json.loads(frame)


async def test_evaluation_connection(credentials: TencentSoeCredentials) -> tuple[bool, str, int]:
    """连通测试：合成一段极短静音真实调用；能拿到合法响应即视为开通可用。"""
    start = time.monotonic()
    pcm_silence = b"\x00\x00" * 16000
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm_silence)
    try:
        await evaluate_turn(buf.getvalue(), "Hello.", credentials, timeout=15)
    except TencentEvaluationError as exc:
        message = str(exc)
        if any(k in message for k in ("4004", "FailedAccount", "60003", "未开通")):
            return False, "智聆口语评测服务不可用（可能未开通或资源包耗尽）", int((time.monotonic() - start) * 1000)
        if "json" in message or "object has no attribute" in message:
            return False, "智聆口语评测协议异常", int((time.monotonic() - start) * 1000)
        # 静音音频引擎无语音可评（无分数属预期），但握手与鉴权通过即算连通
        if "3001" in message or "声音检测失败" in message or "未检测到语音" in message:
            return True, "连接成功（静音样本无评分，属正常）", int((time.monotonic() - start) * 1000)
        return False, message[:200], int((time.monotonic() - start) * 1000)
    latency = int((time.monotonic() - start) * 1000)
    return True, "连接成功（已获得评测响应）", latency
