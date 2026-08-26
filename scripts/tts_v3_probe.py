"""探测大模型 TTS v3 单向流式端点的协议格式。"""
import asyncio
import gzip
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import websockets

from app.core.crypto import decrypt_secret
from app.db.base import async_session_factory
from app.db.models import UserApiKey
from app.services.volcengine.protocol import build_json_request

from sqlalchemy import select

V3_URL = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional"


def describe(raw: bytes) -> str:
    mtype = raw[1] >> 4
    flags = raw[1] & 0x0F
    comp = raw[2] & 0x0F
    kind = {1: "FULL_CLIENT_REQ", 9: "FULL_SERVER_RESP", 10: "AUDIO_SERVER", 15: "ERROR_RESP", 12: "ACK"}.get(mtype, f"0x{mtype:x}")
    body = raw[4:]
    if len(body) >= 4 and int.from_bytes(body[:4], "big") == len(body) - 4:
        body = body[4:]
    if comp == 1 or (flags & 1):
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    text = body[:250].decode("utf-8", errors="replace") if mtype in (9, 15, 12) else f"<{len(body)}B payload>"
    return f"type={kind} flags=0b{flags:04b} comp={comp} size={len(raw)} {text}"


async def try_schema(ws_headers, payload, label):
    ws = await websockets.connect(V3_URL, additional_headers=ws_headers, max_size=None)
    await ws.send(build_json_request(payload))
    print(f"--- {label}")
    try:
        for i in range(6):
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f"  #{i} {describe(raw)}")
            if (raw[1] >> 4) == 15:
                break
            if (raw[1] >> 4) == 10 and (raw[1] & 0x0F) == 0:
                print("  ^ 最后一包音频")
                break
    except asyncio.TimeoutError:
        print("  （10 秒无后续帧）")
    finally:
        await ws.close()


async def main():
    async with async_session_factory() as db:
        row = await db.scalar(select(UserApiKey).where(UserApiKey.service_type == "tts"))
        appid = str((row.config or {}).get("appid", ""))
        token = decrypt_secret(row.key_encrypted)

    headers = {
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": "volc.megatts.default",
    }
    uid = {"uid": "probe"}
    reqid = uuid.uuid4().hex

    # 方案 A：event/namespace 风格（v3 双向文档）
    await try_schema(
        headers,
        {
            "user": uid,
            "event": 1,
            "namespace": "BidirectionalTTS",
            "req_params": {
                "text": "Hello.",
                "speaker": "en_female_anna",
                "audio_params": {"format": "pcm", "sample_rate": 24000},
            },
            "reqid": reqid,
        },
        "A: event/namespace 风格",
    )

    # 方案 B：user/audio/request 风格（SAUC 同族）
    await try_schema(
        headers,
        {
            "user": uid,
            "audio": {
                "voice": "en_female_anna",
                "encoding": "pcm",
                "rate": 24000,
                "speed_ratio": 1.0,
            },
            "request": {"reqid": reqid, "text": "Hello.", "operation": "submit"},
        },
        "B: user/audio/request 风格",
    )


if __name__ == "__main__":
    asyncio.run(main())
