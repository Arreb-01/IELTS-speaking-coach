"""豆包语音合成 2.0 客户端。

两条通道：
- WS 流式（ws_binary）：逐句合成时边收边推，用于考官语音播报（低延迟）
- HTTP 单次（/api/v1/tts）：一次性返回 base64 音频，用于连通性测试与固定话术预合成

音色映射：前端 accent 选项（en_female_anna 英音 / en_female_ariana 美音女 /
en_male_jackson 美音男）→ 火山 voice_type。默认值以语音控制台音色列表为准，
可用环境变量 VOLC_TTS_VOICE_MAP（JSON）覆盖。
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Awaitable, Callable

import httpx
import websockets

from app.core.config import get_settings
from app.services.volcengine.protocol import (
    AUDIO_ONLY_SERVER,
    FULL_SERVER_RESPONSE,
    build_json_request,
    parse_server_frame,
)

logger = logging.getLogger(__name__)

TTS_WSS_URL = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"
TTS_HTTP_URL = "https://openspeech.bytedance.com/api/v1/tts"
TTS_SUCCESS_CODE = 3000

# accent/voice 配置键 → 火山 voice_type（部署前在语音控制台核对具体音色 ID）
DEFAULT_VOICE_MAP = {
    "en_female_anna": "en_female_anna",
    "en_female_ariana": "en_female_ariana",
    "en_male_jackson": "en_male_jackson",
}

SPEED_RATIO_MAP = {"slow": 0.8, "normal": 1.0, "fast": 1.2}


class TtsCredentials:
    def __init__(self, appid: str, access_token: str, resource_id: str) -> None:
        self.appid = appid
        self.access_token = access_token
        self.resource_id = resource_id


class TtsError(Exception):
    pass


def resolve_voice_type(voice_key: str) -> str:
    settings = get_settings()
    voice_map = DEFAULT_VOICE_MAP
    # 允许通过环境变量覆盖映射（JSON 字符串）
    override = getattr(settings, "volc_tts_voice_map", None)
    if override:
        try:
            voice_map = {**voice_map, **json.loads(override)}
        except json.JSONDecodeError:
            logger.warning("VOLC_TTS_VOICE_MAP 配置格式错误，忽略")
    return voice_map.get(voice_key, voice_key)


def resolve_speed_ratio(speed_key: str) -> float:
    return SPEED_RATIO_MAP.get(speed_key, 1.0)


def _build_request_payload(
    credentials: TtsCredentials, text: str, voice_type: str, speed_ratio: float, encoding: str
) -> dict:
    return {
        "app": {
            "appid": credentials.appid,
            "token": credentials.access_token,
            "cluster": "volcano_tts",
        },
        "user": {"uid": "ielts-user"},
        "audio": {
            "voice_type": voice_type,
            "encoding": encoding,
            "speed_ratio": speed_ratio,
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
            "rate": 24000,
            "bits": 16,
        },
        "request": {
            "reqid": uuid.uuid4().hex,
            "text": text,
            "text_type": "plain",
            "operation": "submit",
            "with_frontend": 1,
            "frontend_type": "unit",
        },
    }


def _auth_headers(credentials: TtsCredentials) -> dict[str, str]:
    # 火山 TTS 鉴权头的官方格式是 "Bearer;{token}"（分号分隔）
    return {
        "Authorization": f"Bearer;{credentials.access_token}",
        "X-Api-App-Key": credentials.appid,
        "X-Api-Resource-Id": credentials.resource_id,
    }


async def synthesize_stream(
    text: str,
    credentials: TtsCredentials,
    *,
    voice_key: str = "en_female_anna",
    speed_key: str = "normal",
    encoding: str = "pcm",
    on_audio: Callable[[bytes], Awaitable[None]] | None = None,
    timeout: float = 15.0,
) -> bytes:
    """WS 流式合成：音频块边到边推（on_audio），返回完整音频。"""
    voice_type = resolve_voice_type(voice_key)
    speed_ratio = resolve_speed_ratio(speed_key)
    payload = _build_request_payload(credentials, text, voice_type, speed_ratio, encoding)

    try:
        ws = await asyncio.wait_for(
            websockets.connect(TTS_WSS_URL, additional_headers=_auth_headers(credentials), max_size=None),
            timeout=10,
        )
    except (websockets.WebSocketException, asyncio.TimeoutError, OSError) as exc:
        raise TtsError(f"TTS 连接失败：{type(exc).__name__}") from exc

    audio = bytearray()
    try:
        await ws.send(build_json_request(payload))
        async for raw in ws:
            msg = parse_server_frame(raw)
            if msg.message_type == FULL_SERVER_RESPONSE and msg.json:
                code = msg.json.get("code")
                if code != TTS_SUCCESS_CODE:
                    raise TtsError(f"TTS 服务返回错误 code={code}：{msg.json.get('message', '')}")
            elif msg.message_type == AUDIO_ONLY_SERVER:
                if msg.payload:
                    audio.extend(msg.payload)
                    if on_audio is not None:
                        await on_audio(bytes(msg.payload))
                # TTS v1：音频帧 flags==0 表示最后一包
                if msg.flags == 0 and audio:
                    break
    except asyncio.TimeoutError:
        raise TtsError("TTS 合成超时")
    finally:
        await ws.close()

    if not audio:
        raise TtsError("TTS 未返回音频数据")
    return bytes(audio)


async def synthesize_http(
    text: str,
    credentials: TtsCredentials,
    *,
    voice_key: str = "en_female_anna",
    speed_key: str = "normal",
    encoding: str = "pcm",
    timeout: float = 15.0,
) -> bytes:
    """HTTP 单次合成，返回音频二进制。用于连通测试与预合成。"""
    voice_type = resolve_voice_type(voice_key)
    speed_ratio = resolve_speed_ratio(speed_key)
    payload = _build_request_payload(credentials, text, voice_type, speed_ratio, encoding)
    headers = {"Content-Type": "application/json", **_auth_headers(credentials)}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(TTS_HTTP_URL, json=payload, headers=headers)
    if resp.status_code != 200:
        # 3001 = requested resource not granted（应用未开通该服务）
        try:
            error = resp.json()
            raise TtsError(
                f"TTS 服务错误 code={error.get('code')}：{str(error.get('message', ''))[:150]}"
            )
        except ValueError:
            raise TtsError(f"TTS HTTP 返回 {resp.status_code}")
    data = resp.json()
    if data.get("code") != TTS_SUCCESS_CODE:
        raise TtsError(f"TTS 服务错误 code={data.get('code')}：{data.get('message', '')}")
    audio_b64 = data.get("data")
    if not audio_b64:
        raise TtsError("TTS 未返回音频数据")
    return base64.b64decode(audio_b64)


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
