"""TTS WS 原始帧转储：观察服务器实际发送的帧头/类型/标志，校准协议解析。"""
import asyncio
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

TTS_WSS = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"


async def main() -> None:
    async with async_session_factory() as db:
        from sqlalchemy import select

        row = await db.scalar(select(UserApiKey).where(UserApiKey.service_type == "tts"))
        appid = str((row.config or {}).get("appid", ""))
        token = decrypt_secret(row.key_encrypted)

    payload = {
        "app": {"appid": appid, "token": token, "cluster": "volcano_tts"},
        "user": {"uid": "probe"},
        "audio": {"voice_type": "en_female_anna", "encoding": "pcm", "rate": 24000},
        "request": {
            "reqid": uuid.uuid4().hex,
            "text": "Hello.",
            "text_type": "plain",
            "operation": "submit",
        },
    }
    headers = {
        "Authorization": f"Bearer;{token}",
        "X-Api-App-Key": appid,
        "X-Api-Resource-Id": "volc.megatts.default",
    }

    ws = await websockets.connect(TTS_WSS, additional_headers=headers, max_size=None)
    await ws.send(build_json_request(payload))
    print("请求已发送，开始接收帧（最多 20 帧 / 15 秒）：")
    audio_total = 0
    try:
        for i in range(20):
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            header = raw[:4].hex()
            mtype = raw[1] >> 4
            flags = raw[1] & 0x0F
            comp = raw[2] & 0x0F
            size = len(raw)
            kind = {1: "FULL_CLIENT_REQ", 9: "FULL_SERVER_RESP", 10: "AUDIO_SERVER", 15: "ERROR_RESP"}.get(mtype, "?")
            extra = ""
            if mtype in (9, 15):
                body = raw[4:]
                if len(body) >= 4:
                    declared = int.from_bytes(body[:4], "big")
                    if declared == len(body) - 4:
                        body = body[4:]
                if comp == 1 or (flags & 1):
                    import gzip

                    try:
                        body = gzip.decompress(body)
                    except OSError:
                        pass
                extra = body[:200].decode("utf-8", errors="replace")
            elif mtype == 10:
                audio_total += len(raw) - 8
            print(f"  #{i} type={kind}(0x{mtype:x}) flags=0b{flags:04b} comp={comp} size={size} {extra}")
            if mtype == 10 and flags == 0:
                print("  ^ 音频最后一包")
                break
    except asyncio.TimeoutError:
        print("  （等待超时，服务器未再发帧）")
    finally:
        await ws.close()
    print(f"累计音频负载约 {audio_total} 字节")


if __name__ == "__main__":
    asyncio.run(main())
