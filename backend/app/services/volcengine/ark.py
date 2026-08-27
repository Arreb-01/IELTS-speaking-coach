"""火山引擎方舟（豆包大模型）客户端。

Part A 仅实现连通性测试所需的最小调用；完整的评分/反馈调用在 Part B/C 扩展。
错误信息中绝不包含 API Key 明文。
"""

import time
from typing import Any

import httpx

from app.core.config import get_settings


class ArkError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


async def chat_completions(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float = 15.0,
    **payload_extra: Any,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.volc_ark_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, **payload_extra}
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:  # 国内云服务直连，不受系统代理干扰
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ArkError("请求火山引擎超时") from exc
    except httpx.HTTPError as exc:
        raise ArkError(f"网络错误：{type(exc).__name__}") from exc

    if resp.status_code >= 400:
        raise ArkError(_describe_http_error(resp), resp.status_code)
    return resp.json()


def _describe_http_error(resp: httpx.Response) -> str:
    # 只提取错误概要，避免把响应体整段透出（其中可能含请求回显内容）
    try:
        body = resp.json()
        message = str(body.get("error", {}).get("message", ""))[:200]
    except Exception:
        message = ""
    status = resp.status_code
    if status in (401, 403):
        return "API Key 无效或无访问权限"
    if status == 404:
        return "模型不存在或无访问权限（请检查模型 ID / 推理接入点）"
    if status == 429:
        return "请求过于频繁或额度不足"
    return f"火山引擎返回错误 {status}" + (f"：{message}" if message else "")


async def test_connection(
    api_key: str, model: str | None = None
) -> tuple[bool, str, int]:
    """最小化连通性测试，返回 (是否成功, 说明, 耗时毫秒)。"""
    settings = get_settings()
    model = model or settings.volc_ark_test_model
    start = time.monotonic()
    try:
        await chat_completions(
            api_key,
            model,
            [{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except ArkError as exc:
        return False, str(exc), int((time.monotonic() - start) * 1000)
    return True, "连接成功", int((time.monotonic() - start) * 1000)
