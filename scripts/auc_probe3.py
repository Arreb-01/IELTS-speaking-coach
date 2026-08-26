"""MDD WS 协议探测：完整会话（JSON 配置帧 + 音频）看返回结构。"""

import asyncio
import base64
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import websockets
from sqlalchemy import select

from app.core.crypto import decrypt_secret
from app.db.base import async_session_factory
from app.db.models import UserApiKey

WS_URL = "wss://openspeech.bytedance.com/api/v1/mdd/ws"
REF = "I really enjoy listening to music, especially pop songs."


async def main():
    async with async_session_factory() as db:
        row = await db.scalar(select(UserApiKey).where(UserApiKey.service_type == "tts"))
        appid = str((row.config or {}).get("appid", ""))
        token = decrypt_secret(row.key_encrypted)
    wav = sorted(Path(__file__).parent.parent.glob("backend/storage/audio/*/*.wav"),
                 key=lambda p: p.stat().st_mtime, reverse=True)[0]
    pcm = wav.read_bytes()[44:44 + 32000 * 20]
    audio_b64 = base64.b64encode(pcm).decode()

    headers = {
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": "volc.mdd",
    }
    ws = await websockets.connect(WS_URL, additional_headers=headers, max_size=None)
    print("WS 已连接")

    reqid = uuid.uuid4().hex
    # 方案 A：一帧全量 JSON（base64 音频，sequence -1）
    payload = {
        "user": {"uid": "probe"},
        "audio": {"format": "pcm", "rate": 16000, "bits": 16, "channel": 1, "data": audio_b64},
        "request": {
            "reqid": reqid,
            "sequence": -1,
            "model_name": "bigmodel",
            "ref_text": REF,
            "service_type": 81,
        },
    }
    await ws.send(json.dumps(payload))
    print("已发送方案 A（全量 JSON）")
    try:
        for i in range(3):
            raw = await asyncio.wait_for(ws.recv(), timeout=20)
            if isinstance(raw, bytes):
                print(f"#{i} 二进制帧 {len(raw)}B: {raw[:120]!r}")
            else:
                print(f"#{i} 文本帧: {raw[:1200]}")
    except (asyncio.TimeoutError, websockets.ConnectionClosed) as e:
        print(f"接收结束: {type(e).__name__}")
    await ws.close()

    # 方案 B：SAUC 二进制协议帧格式（4 字节头 + payload）
    print("\n=== 方案 B：SAUC 二进制帧")
    from app.services.volcengine.protocol import build_json_request, build_audio_frame, parse_server_frame

    ws = await websockets.connect(WS_URL, additional_headers=headers, max_size=None)
    config = {
        "user": {"uid": "probe"},
        "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
        "request": {
            "reqid": reqid,
            "model_name": "bigmodel",
            "ref_text": REF,
            "service_type": 81,
        },
    }
    await ws.send(build_json_request(config))
    # 分 4 块送音频，最后一块 last=True
    chunk = len(pcm) // 4
    for i in range(4):
        part = pcm[i * chunk:(i + 1) * chunk if i < 3 else len(pcm)]
        await ws.send(build_audio_frame(part, last=(i == 3)))
    print("已发送配置 + 4 音频块")
    try:
        for i in range(6):
            raw = await asyncio.wait_for(ws.recv(), timeout=20)
            msg = parse_server_frame(raw) if isinstance(raw, bytes) else raw
            if isinstance(msg, str):
                print(f"#{i} 文本: {msg[:1200]}")
            elif msg.json is not None:
                print(f"#{i} JSON: {json.dumps(msg.json, ensure_ascii=False)[:1500]}")
            elif msg.payload:
                print(f"#{i} 二进制 {len(msg.payload)}B")
            else:
                print(f"#{i} 空帧")
    except (asyncio.TimeoutError, websockets.ConnectionClosed) as e:
        print(f"接收结束: {type(e).__name__}")
    await ws.close()


if __name__ == "__main__":
    asyncio.run(main())
