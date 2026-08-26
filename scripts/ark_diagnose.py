"""诊断：用用户保存在本机数据库里的 Ark Key，探测哪些模型 ID 真实可用。

用法（backend 目录下）：
    .venv/Scripts/python ../scripts/ark_diagnose.py
输出只包含各模型的调用状态，绝不打印 Key 本身。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.db.base import async_session_factory
from app.db.models import UserApiKey

CANDIDATE_MODELS = [
    # 豆包 1.5 系列（PRD 选型）
    "doubao-1.5-pro-32k-250115",
    "doubao-1.5-pro-32k-character-250115",
    "doubao-1.5-pro-32k",
    "doubao-1.5-lite-32k-250115",
    "doubao-1.5-thinking-pro-250428",
    # 豆包 1.6 / seed 系列（2025-2026 主力）
    "doubao-seed-1.6-250615",
    "doubao-seed-1.6-flash-250815",
    "doubao-seed-2.1-turbo",
    "doubao-seed-2.1-flash",
    "doubao-seed-2.1-pro",
    # 旧版命名兜底
    "doubao-pro-32k-241215",
    "doubao-pro-32k",
]


async def load_key() -> str:
    async with async_session_factory() as db:
        row = await db.scalar(
            select(UserApiKey).where(UserApiKey.service_type == "llm")
        )
        if row is None:
            raise SystemExit("数据库里没有保存 LLM Key，请先在网站 API 设置页保存")
        return decrypt_secret(row.key_encrypted)


async def probe(client: httpx.AsyncClient, api_key: str, model: str) -> tuple[str, int, str]:
    settings = get_settings()
    url = f"{settings.volc_ark_base_url.rstrip('/')}/chat/completions"
    try:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            },
        )
    except httpx.HTTPError as exc:
        return model, -1, f"网络错误 {type(exc).__name__}"
    if resp.status_code == 200:
        return model, 200, "OK ✅"
    try:
        message = str(resp.json().get("error", {}).get("message", ""))[:90]
    except Exception:
        message = ""
    return model, resp.status_code, message


async def main() -> None:
    api_key = await load_key()
    print(f"已从数据库加载 Key（****{api_key[-4:]}），开始探测 {len(CANDIDATE_MODELS)} 个候选模型…\n")
    async with httpx.AsyncClient(timeout=15) as client:
        results = []
        for model in CANDIDATE_MODELS:
            results.append(await probe(client, api_key, model))
            model_id, status, message = results[-1]
            print(f"  [{status}] {model_id}  {message}")

    ok = [r for r in results if r[1] == 200]
    print("\n===== 结论 =====")
    if ok:
        print("可用模型：")
        for model_id, _, _ in ok:
            print(f"  - {model_id}")
    else:
        print("以上候选全部不可用。请在火山方舟控制台「开通管理」页找到已开通模型的完整 ID 发给我。")


if __name__ == "__main__":
    asyncio.run(main())
