"""豆包语音合成 2.0 客户端（Seed-TTS v3 单向流式接口，2026-08 真机校准）。

接口要点（实测确定）：
- POST https://openspeech.bytedance.com/api/v3/tts/unidirectional
- 鉴权头：X-Api-App-Key(appid) + X-Api-Access-Key(token) + X-Api-Resource-Id: volc.seedtts.default
- 请求体：{user:{uid}, req_params:{text, speaker, audio_params:{format, sample_rate}}}
- 响应：NDJSON 流，每行 {code, message, data(base64 音频块)}，逐行解析拼接
- 音色为美式口音（zen_daya 女声 / michael_kevin 男声），英音选项映射到最接近音色
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TTS_V3_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
TTS_RESOURCE_ID = "volc.seedtts.default"
TTS_SUCCESS_CODE = 0
TTS_STREAM_END_CODE = 20000000  # NDJSON 流的结束事件

# 前端 accent 配置键 → 实际音色（账号音色库全部为美式口音；英音选项映射到女声）
DEFAULT_VOICE_MAP = {
    "en_female_anna": "en_female_zendaya_p1_uranus_bigtts",
    "en_female_ariana": "en_female_zendaya_p1_uranus_bigtts",
    "en_male_jackson": "en_male_michael_kevin_uranus_bigtts",
}

SPEED_RATIO_MAP = {"slow": 0.8, "normal": 1.0, "fast": 1.2}


class TtsCredentials:
    def __init__(self, appid: str, access_token: str, resource_id: str = TTS_RESOURCE_ID) -> None:
        self.appid = appid
        self.access_token = access_token
        self.resource_id = resource_id


class TtsError(Exception):
    pass


def resolve_voice_type(voice_key: str) -> str:
    settings = get_settings()
    voice_map = DEFAULT_VOICE_MAP
    override = getattr(settings, "volc_tts_voice_map", None)
    if override:
        try:
            voice_map = {**voice_map, **json.loads(override)}
        except json.JSONDecodeError:
            logger.warning("VOLC_TTS_VOICE_MAP 配置格式错误，忽略")
    return voice_map.get(voice_key, voice_key)


def resolve_speed_ratio(speed_key: str) -> float:
    return SPEED_RATIO_MAP.get(speed_key, 1.0)


def _auth_headers(credentials: TtsCredentials) -> dict[str, str]:
    return {
        "X-Api-App-Key": credentials.appid,
        "X-Api-Access-Key": credentials.access_token,
        "X-Api-Resource-Id": credentials.resource_id,
        "Content-Type": "application/json",
    }


def _build_payload(
    text: str, voice_type: str, speed_ratio: float, encoding: str = "mp3"
) -> dict[str, Any]:
    return {
        "user": {"uid": "ielts-user"},
        "req_params": {
            "text": text,
            "speaker": voice_type,
            "speech_rate": speed_ratio,
            "audio_params": {"format": encoding, "sample_rate": 24000},
        },
    }


async def synthesize_stream(
    text: str,
    credentials: TtsCredentials,
    *,
    voice_key: str = "en_female_anna",
    speed_key: str = "normal",
    encoding: str = "pcm",
    on_audio: Callable[[bytes], Awaitable[None]] | None = None,
    timeout: float = 20.0,
) -> bytes:
    """v3 单向流式合成：NDJSON 逐块解析，音频块经 on_audio 推送，返回完整音频。

    默认 PCM（24kHz/16bit/单声道）：前端播放器按原始数据直读，无需解压，
    任意分块边界都安全（MP3 分块解码不可靠）。"""
    voice_type = resolve_voice_type(voice_key)
    speed_ratio = resolve_speed_ratio(speed_key)
    payload = _build_payload(text, voice_type, speed_ratio, encoding)

    audio = bytearray()
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:  # 国内云服务直连，不受系统代理干扰
            async with client.stream(
                "POST", TTS_V3_URL, json=payload, headers=_auth_headers(credentials)
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise TtsError(_describe_error(resp.status_code, body))
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    code = chunk.get("code")
                    # 0=音频块；20000000=流正常结束；其余为错误
                    if code is not None and code not in (TTS_SUCCESS_CODE, TTS_STREAM_END_CODE):
                        raise TtsError(
                            f"TTS 服务错误 code={code}：{str(chunk.get('message', ''))[:150]}"
                        )
                    data_b64 = chunk.get("data")
                    if data_b64:
                        block = base64.b64decode(data_b64)
                        if block:
                            audio.extend(block)
                            if on_audio is not None:
                                result = on_audio(block)
                                if asyncio.iscoroutine(result):
                                    await result
    except httpx.HTTPError as exc:
        raise TtsError(f"TTS 请求失败：{type(exc).__name__}") from exc
    except asyncio.TimeoutError:
        raise TtsError("TTS 合成超时")

    if not audio:
        raise TtsError("TTS 未返回音频数据")
    return bytes(audio)


def _describe_error(status: int, body: str) -> str:
    try:
        data = json.loads(body)
        header = data.get("header") or data
        code = header.get("code", status)
        message = str(header.get("message", ""))[:150]
    except (json.JSONDecodeError, AttributeError):
        return f"TTS HTTP 返回 {status}"
    if code == 45000030 and "not granted" in message:
        return "TTS 服务未授权该资源（请检查语音合成 2.0 是否已开通）"
    return f"TTS 服务错误 code={code}：{message}"


async def synthesize_http(
    text: str,
    credentials: TtsCredentials,
    *,
    voice_key: str = "en_female_anna",
    speed_key: str = "normal",
    encoding: str = "mp3",
    timeout: float = 15.0,
) -> bytes:
    """非流式便捷封装：一次性返回完整音频（复用 v3 流式接口）。"""
    return await synthesize_stream(
        text, credentials,
        voice_key=voice_key, speed_key=speed_key, encoding=encoding, timeout=timeout,
    )


async def test_tts_connection(credentials: TtsCredentials) -> tuple[bool, str, int]:
    """最小化连通测试：合成一个单词，验证鉴权与音色可用。"""
    start = time.monotonic()
    try:
        audio = await synthesize_http(
            "Hello.", credentials, voice_key="en_female_anna", encoding="mp3", timeout=12
        )
    except TtsError as exc:
        return False, str(exc), int((time.monotonic() - start) * 1000)
    latency = int((time.monotonic() - start) * 1000)
    if len(audio) < 100:
        return False, "TTS 返回的音频异常（过短）", latency
    return True, "连接成功（已合成测试音频）", latency
