"""腾讯云智聆口语评测（新版，WebSocket）真机探测。

用法（在 backend 目录）：
    .venv/Scripts/python scripts/tencent_soe_probe.py [轮次数量]

凭据从 .env 的 TENCENT_SECRET_ID / TENCENT_SECRET_KEY 读取；
账号 APPID（数字串）通过 CAM GetUserAppId 自动获取。
协议照官方 Python SDK github.com/TencentCloud/tencentcloud-speech-sdk-python 实现：
wss://soe.cloud.tencent.com/soe/api/{appid}?{参数按 key 排序}&signature={hmac-sha1}
"""

import asyncio
import base64
import hashlib
import hmac
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import websocket

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.config import get_settings
from app.db.base import async_session_factory
from app.db.models import PracticeTurn

MAX_REF_WORDS = 120


def get_account_appid(secret_id: str, secret_key: str) -> str:
    """CAM GetUserAppId：用密钥查本账号的数字 APPID。"""
    from tencentcloud.common import credential

    from tencentcloud.cam.v20190116.cam_client import CamClient
    from tencentcloud.cam.v20190116 import models as cam_models

    cred = credential.Credential(secret_id, secret_key)
    client = CamClient(cred, "ap-shanghai")
    return str(client.GetUserAppId(cam_models.GetUserAppIdRequest()).AppId)


def soe_evaluate_once(
    wav: bytes,
    ref_text: str,
    appid: str,
    secret_id: str,
    secret_key: str,
    *,
    eval_mode: int = 2,
    voice_format: int = 1,
    timeout: float = 20.0,
) -> dict:
    """录音评测模式（rec_mode=1）：握手成功后一次性传整段音频，等 final 结果。

    签名规则（官方文档 107497）：签名原文 = soe.cloud.tencent.com/soe/api/{appid}?
    {除 signature/appid 外按字典序排序的 k=v（值不做 urlencode）}，
    HMAC-SHA1(SecretKey) 后 base64；实际请求时所有 key/value 与 signature 需 urlencode。"""
    ts = str(int(time.time()))
    query = {
        "server_engine_type": "16k_en",
        "text_mode": 0,
        "rec_mode": 1,
        "ref_text": " ".join(ref_text.split()[:MAX_REF_WORDS]),
        "eval_mode": eval_mode,
        "score_coeff": 3.0,
        "sentence_info_enabled": 1,
        "secretid": secret_id,
        "voice_format": voice_format,
        "voice_id": str(uuid.uuid1()),
        "timestamp": ts,
        "nonce": ts,
        "expired": int(time.time()) + 3600,
    }
    sorted_items = sorted(query.items(), key=lambda kv: kv[0])
    signstr = (
        "soe.cloud.tencent.com/soe/api/"
        + appid
        + "?"
        + "&".join(f"{k}={v}" for k, v in sorted_items)
    )
    signature = base64.b64encode(
        hmac.new(secret_key.encode("utf-8"), signstr.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")

    url = (
        f"wss://soe.cloud.tencent.com/soe/api/{appid}?"
        + "&".join(f"{k}={quote(str(v), safe='')}" for k, v in sorted_items)
        + "&signature="
        + quote(signature, safe="")
    )

    ws = websocket.create_connection(url, timeout=timeout)
    try:
        # 握手阶段：先等服务端 code=0 的确认消息再传音频
        handshake = json.loads(ws.recv())
        if handshake.get("code") != 0:
            return {"ok": False, **handshake}
        ws.send_binary(wav)
        ws.send(json.dumps({"type": "end"}))
        while True:
            data = json.loads(ws.recv())
            if data.get("code") not in (0, None):
                return {"ok": False, **data}
            if data.get("final") == 1:
                return {"ok": True, "data": data}
    finally:
        ws.close()


def summarize(data: dict) -> str:
    result = data.get("result") or {}
    keys = {
        k: result.get(k)
        for k in (
            "pron_accuracy", "pron_fluency", "pron_completion", "suggested_score",
            "PronAccuracy", "PronFluency", "PronCompletion", "SuggestedScore",
            "voice_text_str",
        )
        if result.get(k) is not None
    }
    words = result.get("words") or result.get("word_list") or []
    sample = [
        {k: w.get(k) for k in ("word", "Word", "pron_accuracy", "PronAccuracy", "match_tag", "MatchTag") if w.get(k) is not None}
        for w in words[:5]
    ]
    top_keys = [k for k in data.keys() if k not in ("result",)]
    return f"top={top_keys} 分数={json.dumps(keys, ensure_ascii=False)}\n  词数={len(words)} 词级样例={json.dumps(sample, ensure_ascii=False)[:400]}"


async def main() -> None:
    settings = get_settings()
    if not settings.tencent_secret_id or not settings.tencent_secret_key:
        print("未配置 TENCENT_SECRET_ID / TENCENT_SECRET_KEY")
        return

    appid = await asyncio.to_thread(
        get_account_appid, settings.tencent_secret_id, settings.tencent_secret_key
    )
    print(f"账号 APPID: {appid}\n")

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    async with async_session_factory() as db:
        turns = (
            await db.scalars(
                select(PracticeTurn)
                .where(PracticeTurn.user_transcript.is_not(None))
                .where(PracticeTurn.audio_path.is_not(None))
                .order_by(PracticeTurn.id.desc())
                .limit(limit)
            )
        ).all()

    root = Path(settings.storage_dir)
    for t in turns:
        wav_path = root / t.audio_path
        if not wav_path.is_file():
            print(f"[turn {t.seq}] 录音文件缺失: {t.audio_path}")
            continue
        wav = wav_path.read_bytes()
        text = (t.user_transcript or "").strip()
        print(f"[turn seq={t.seq}] 音频 {len(wav)/32000:.1f}s | ref: {text[:100]}")
        try:
            r = await asyncio.to_thread(
                soe_evaluate_once, wav, text, appid,
                settings.tencent_secret_id, settings.tencent_secret_key,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ 异常: {type(exc).__name__}: {exc}\n")
            continue
        if r["ok"]:
            print(f"  ✅ 成功: {summarize(r['data'])}")
        else:
            print(f"  ❌ 失败 code={r.get('code')}: {str(r.get('message'))[:200]}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
