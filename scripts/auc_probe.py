"""探测火山口语评测（service_type 81）协议形态。

公开文档抓不到，采用 TTS spike 同方法论：真实凭据 + 真实音频，
按候选 (URL, resource_id, body 形态) 逐一试探，读服务端错误信息逼近真协议。
"""

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
from app.db.models import PracticeTurn, UserApiKey

REF_TEXT = "I really enjoy listening to music, especially pop songs."


def load_wav_b64() -> str:
    """取最近一条有录音的轮次音频做探测素材。"""
    root = Path(__file__).resolve().parent.parent / "backend" / "storage"
    wavs = sorted(root.glob("audio/*/*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wavs:
        raise SystemExit("storage/audio 下没有 WAV，请先用真实凭据练一轮")
    wav = wavs[0]
    # 评测音频上限约 60s/2MB；超长就截前 20 秒（WAV header 44 字节 + 32000B/s）
    data = wav.read_bytes()
    if len(data) > 44 + 32000 * 20:
        data = data[: 44 + 32000 * 20]
    print(f"素材: {wav.name} ({len(data)} bytes)")
    return base64.b64encode(data).decode("ascii")


async def get_credentials() -> tuple[str, str]:
    async with async_session_factory() as db:
        row = await db.scalar(select(UserApiKey).where(UserApiKey.service_type == "tts"))
        if row is None:
            for st in ("asr", "evaluation"):
                row = await db.scalar(select(UserApiKey).where(UserApiKey.service_type == st))
                if row:
                    break
        if row is None:
            raise SystemExit("user_api_keys 里没有语音凭据")
        appid = str((row.config or {}).get("appid", ""))
        token = decrypt_secret(row.key_encrypted)
        return appid, token


def headers(appid: str, token: str, resource_id: str) -> dict:
    return {
        "X-Api-App-Key": appid,
        "X-Api-Access-Key": token,
        "X-Api-Resource-Id": resource_id,
        "Content-Type": "application/json",
    }


def body_sauc(audio_b64: str, service_type: int | None) -> dict:
    request: dict = {
        "model_name": "bigmodel",
        "ref_text": REF_TEXT,
        "enable_words": True,
        "work_mode": 1,
    }
    if service_type is not None:
        request["service_type"] = service_type
    return {
        "reqid": uuid.uuid4().hex,
        "user": {"uid": "probe"},
        "audio": {
            "format": "wav",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
            "data": audio_b64,
        },
        "request": request,
    }


def body_flat(audio_b64: str) -> dict:
    """平铺字段形态（reqid/text/audio 在顶层）。"""
    return {
        "reqid": uuid.uuid4().hex,
        "text": REF_TEXT,
        "service_type": 81,
        "audio": {"format": "wav", "rate": 16000, "bits": 16, "channel": 1, "data": audio_b64},
    }


async def probe(client, label, url, hdrs, body):
    print(f"\n=== {label}\n    POST {url}\n    resource={hdrs.get('X-Api-Resource-Id')}")
    try:
        resp = await client.post(url, headers=hdrs, json=body)
    except httpx.HTTPError as exc:
        print(f"    网络错误: {type(exc).__name__}: {exc}")
        return
    print(f"    HTTP {resp.status_code}")
    text = resp.text
    print("    " + text[:600].replace("\n", "\n    "))


async def main():
    appid, token = await get_credentials()
    print(f"appid={appid}")
    audio_b64 = load_wav_b64()

    async with httpx.AsyncClient(timeout=30) as client:
        # --- URL 家族 1：/api/v1/auc ---
        for resource in ("volc.auc_test", "volc.auc.n.en", "volc.mdd", "volc.bigasr.auc.duration"):
            await probe(
                client,
                f"v1/auc + SAUC 形态 (service_type 81) + {resource}",
                "https://openspeech.bytedance.com/api/v1/auc",
                headers(appid, token, resource),
                body_sauc(audio_b64, 81),
            )
        # 不带 resource id（鉴权走 query 的老形态）
        await probe(
            client,
            "v1/auc 平铺形态 无 resource id",
            "https://openspeech.bytedance.com/api/v1/auc",
            {"Content-Type": "application/json"},
            body_flat(audio_b64),
        )

        # --- URL 家族 2：/api/v1/mdd ---
        for path in ("/api/v1/mdd", "/api/v1/mdd/evaluate", "/api/v1/score"):
            await probe(
                client,
                f"{path} SAUC 形态",
                f"https://openspeech.bytedance.com{path}",
                headers(appid, token, "volc.mdd"),
                body_sauc(audio_b64, None),
            )

        # --- URL 家族 3：v3 大模型族 ---
        await probe(
            client,
            "v3/auc SAUC 形态",
            "https://openspeech.bytedance.com/api/v3/auc",
            headers(appid, token, "volc.auc.bigmodel"),
            body_sauc(audio_b64, 81),
        )
        await probe(
            client,
            "v3/auc/bigmodel SAUC 形态",
            "https://openspeech.bytedance.com/api/v3/auc/bigmodel",
            headers(appid, token, "volc.auc.bigmodel"),
            body_sauc(audio_b64, 81),
        )


if __name__ == "__main__":
    asyncio.run(main())
