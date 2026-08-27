"""火山口语评测（英文，service_type 81）客户端。

2026-08 真机校准进展（探测脚本 scripts/auc_probe*.py）：
- 端点 POST https://openspeech.bytedance.com/api/v1/mdd（网关实测存在，逐字段校验：
  app 鉴权 → request.reqid → request.sequence → cluster 路由）
- 请求体形态：{app:{appid,token,cluster}, user:{uid},
  audio:{format,rate,bits,channel,data(base64)}, request:{reqid,sequence:-1,
  ref_text, service_type:81}}
- cluster 即 resource id（空值报 "cluster cannot be empty"，实测所有候选值均报
  "no available instances" —— 判定为应用未开通口语评测；开通后用控制台文档校准
  VOLC_MDD_CLUSTER 常量即可，其余协议已定型）
- 响应字段名未实测到成功样本，_extract_scores 按常见命名防御式解析
"""

import base64
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MDD_HTTP_URL = "https://openspeech.bytedance.com/api/v1/mdd"
SERVICE_TYPE_EN = 81
SEQUENCE_FINAL = -1
# 音频上限：截前 60 秒，避免超长请求（参考同类评测服务限制）
MAX_AUDIO_SECONDS = 60
PCM_BYTES_PER_SECOND = 32000  # 16kHz * 16bit * 单声道


class EvaluationError(Exception):
    pass


@dataclass
class EvaluationCredentials:
    appid: str
    access_token: str
    cluster: str


@dataclass
class WordScore:
    word: str
    score: float | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass
class EvaluationResult:
    """单轮评测结果。score 为 0-100 原始分；words 为词级明细（服务支持时）。

    raw 保留服务端原始返回，报告页与回归排查用。"""

    score: float | None = None
    fluency: float | None = None
    integrity: float | None = None
    words: list[WordScore] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.score is not None


def _wav_to_pcm(wav: bytes) -> bytes:
    """剥离 44 字节标准 WAV 头（StorageService 归档均为该格式）。"""
    return wav[44:] if len(wav) > 44 and wav[:4] == b"RIFF" else wav


def build_request(ref_text: str, pcm: bytes, uid: str) -> dict[str, Any]:
    payload = pcm[: PCM_BYTES_PER_SECOND * MAX_AUDIO_SECONDS]
    return {
        "app": None,  # 由调用方注入凭据（见 evaluate）
        "user": {"uid": uid},
        "audio": {
            "format": "pcm",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
            "data": base64.b64encode(payload).decode("ascii"),
        },
        "request": {
            "reqid": uuid.uuid4().hex,
            "sequence": SEQUENCE_FINAL,
            "ref_text": ref_text,
            "service_type": SERVICE_TYPE_EN,
        },
    }


# ---------------------------------------------------------------------------
# 响应解析：字段名未拿到成功样本，按常见命名防御式取值
# ---------------------------------------------------------------------------

_SCORE_ALIASES = ("pronunciation", "pron_accuracy", "accuracy", "score", "overall")
_FLUENCY_ALIASES = ("fluency", "pron_fluency")
_INTEGRITY_ALIASES = ("integrity", "completeness")


def _pick(data: dict[str, Any], aliases: tuple[str, ...]) -> float | None:
    for key in aliases:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _extract_scores(data: dict[str, Any]) -> EvaluationResult:
    result_root = data.get("result") if isinstance(data.get("result"), dict) else data
    words_raw = result_root.get("words") or result_root.get("word_list") or []

    words: list[WordScore] = []
    for item in words_raw:
        if not isinstance(item, dict):
            continue
        words.append(
            WordScore(
                word=str(item.get("word") or item.get("text") or ""),
                score=_pick(item, _SCORE_ALIASES),
                start_ms=item.get("start_time") if isinstance(item.get("start_time"), int) else None,
                end_ms=item.get("end_time") if isinstance(item.get("end_time"), int) else None,
            )
        )

    return EvaluationResult(
        score=_pick(result_root, _SCORE_ALIASES),
        fluency=_pick(result_root, _FLUENCY_ALIASES),
        integrity=_pick(result_root, _INTEGRITY_ALIASES),
        words=words,
        raw=data,
    )


def _describe_error(data: dict[str, Any]) -> str:
    message = str(data.get("message", ""))[:200]
    if "no available instances" in message or "no pickable item" in message:
        return "口语评测服务无可用实例（应用大概率未开通「口语评测」服务，请在语音控制台开通后重试）"
    return f"口语评测服务错误 code={data.get('code', '?')}：{message}"


async def evaluate_turn(
    wav: bytes,
    ref_text: str,
    credentials: EvaluationCredentials,
    *,
    uid: str = "ielts-user",
    timeout: float = 15.0,
) -> EvaluationResult:
    """单轮评测：归档 WAV + 参考文本（该轮 ASR 转写）→ 发音分与词级明细。"""
    body = build_request(ref_text, _wav_to_pcm(wav), uid)
    body["app"] = {
        "appid": credentials.appid,
        "token": credentials.access_token,
        "cluster": credentials.cluster,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:  # 国内云服务直连，不受系统代理干扰
            resp = await client.post(MDD_HTTP_URL, json=body)
    except httpx.TimeoutException:
        raise EvaluationError("口语评测请求超时")
    except httpx.HTTPError as exc:
        raise EvaluationError(f"口语评测请求失败：{type(exc).__name__}") from exc

    if resp.status_code != 200:
        try:
            data = resp.json()
        except ValueError:
            data = {"code": resp.status_code, "message": resp.text[:200]}
        raise EvaluationError(_describe_error(data))

    try:
        data = resp.json()
    except ValueError as exc:
        raise EvaluationError("口语评测返回非 JSON 响应") from exc

    code = data.get("code")
    if code not in (0, 1000, 20000000):
        raise EvaluationError(_describe_error(data))

    result = _extract_scores(data)
    if not result.ok:
        logger.warning("口语评测响应缺少分数字段：%s", str(data)[:300])
    return result


async def test_evaluation_connection(credentials: EvaluationCredentials) -> tuple[bool, str, int]:
    """最小化连通测试：用 1 秒静音 + 一句参考文本发起真实评测。"""
    start = time.monotonic()
    silence = b"\x00\x00" * 16000  # 0.5s 静音 PCM
    try:
        result = await evaluate_turn(
            silence, "Hello.", credentials, uid="connect-test", timeout=12
        )
    except EvaluationError as exc:
        return False, str(exc), int((time.monotonic() - start) * 1000)
    latency = int((time.monotonic() - start) * 1000)
    if not result.ok:
        return False, "服务可达但未返回评分（请检查服务开通状态与集群配置）", latency
    return True, "连接成功（已获得评测分数）", latency
