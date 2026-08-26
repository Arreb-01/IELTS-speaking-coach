"""MDD（口语评测）协议第二轮：补 app 鉴权字段，逐字段逼近。"""

import asyncio
import base64
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx
from sqlalchemy import select

from app.core.crypto import decrypt_secret
from app.db.base import async_session_factory
from app.db.models import UserApiKey

MDD_URL = "https://openspeech.bytedance.com/api/v1/mdd"
REF_TEXT = "I really enjoy listening to music, especially pop songs."


def load_wav_b64() -> str:
    root = Path(__file__).resolve().parent.parent / "backend" / "storage"
    wavs = sorted(root.glob("audio/*/*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    data = wavs[0].read_bytes()
    if len(data) > 44 + 32000 * 20:
        data = data[: 44 + 32000 * 20]
    print(f"素材: {wavs[0].name} ({len(data)} bytes)")
    return base64.b64encode(data).decode("ascii")


async def get_credentials() -> tuple[str, str]:
    async with async_session_factory() as db:
        row = await db.scalar(select(UserApiKey).where(UserApiKey.service_type == "tts"))
        if row is None:
            for st in ("asr", "evaluation"):
                row = await db.scalar(select(UserApiKey).where(UserApiKey.service_type == st))
                if row:
                    break
        appid = str((row.config or {}).get("appid", ""))
        return appid, decrypt_secret(row.key_encrypted)


async def try_body(client, appid, token, audio_b64, label, body):
    print(f"\n=== {label}")
    try:
        resp = await client.post(MDD_URL, json=body)
    except httpx.HTTPError as exc:
        print(f"    网络错误: {exc}")
        return None
    print(f"    HTTP {resp.status_code}")
    print("    " + resp.text[:800].replace("\n", "\n    "))
    try:
        return resp.json()
    except ValueError:
        return None


async def main():
    appid, token = await get_credentials()
    audio_b64 = load_wav_b64()

    async with httpx.AsyncClient(timeout=60) as client:
        # 形态 1：app 鉴权 + SAUC 风格 request
        await try_body(
            client, appid, token, audio_b64,
            "app + SAUC request（ref_text/model_name）",
            {
                "app": {"appid": appid, "token": token, "cluster": "volcano_mdd"},
                "user": {"uid": "probe"},
                "audio": {"format": "wav", "rate": 16000, "bits": 16, "channel": 1, "data": audio_b64},
                "request": {"model_name": "bigmodel", "ref_text": REF_TEXT},
            },
        )
        # 形态 2：app 鉴权 + text 字段
        await try_body(
            client, appid, token, audio_b64,
            "app + request.text",
            {
                "app": {"appid": appid, "token": token, "cluster": "volcano_mdd"},
                "user": {"uid": "probe"},
                "audio": {"format": "wav", "rate": 16000, "bits": 16, "channel": 1, "data": audio_b64},
                "request": {"model_name": "bigmodel", "text": REF_TEXT, "service_type": 81},
            },
        )
        # 形态 3：只放 app（不带 cluster）看校验顺序
        await try_body(
            client, appid, token, audio_b64,
            "app（无 cluster）",
            {
                "app": {"appid": appid, "token": token},
                "user": {"uid": "probe"},
                "audio": {"format": "wav", "rate": 16000, "bits": 16, "channel": 1, "data": audio_b64},
                "request": {"model_name": "bigmodel", "ref_text": REF_TEXT},
            },
        )


if __name__ == "__main__":
    asyncio.run(main())
