"""豆包流式语音识别（SAUC 全双工）客户端。

每个作答轮次一个会话：start() 建连并下发配置 → feed() 持续送 PCM →
finish() 发结束帧并汇总最终转写。识别过程中的增量文本通过回调推送。

协议参考官方 sauc websocket demo（二进制帧格式见 protocol.py）。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import websockets

from app.services.volcengine.protocol import (
    build_audio_frame,
    build_json_request,
    parse_server_frame,
)

logger = logging.getLogger(__name__)

ASR_WSS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"

# 音频要求：PCM 16kHz 16bit 单声道（由前端 AudioWorklet 重采样保证）
AUDIO_FORMAT = {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1}


@dataclass
class AsrCredentials:
    appid: str
    access_token: str
    resource_id: str


@dataclass
class WordTimestamp:
    text: str
    start_time: int  # ms
    end_time: int


@dataclass
class AsrResult:
    text: str = ""
    duration_ms: int = 0
    utterances: list[dict[str, Any]] = field(default_factory=list)
    words: list[WordTimestamp] = field(default_factory=list)


class AsrError(Exception):
    pass


class VolcAsrSession:
    """单轮识别会话。"""

    def __init__(
        self,
        credentials: AsrCredentials,
        *,
        uid: str = "ielts-user",
        on_partial: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._credentials = credentials
        self._uid = uid
        self._on_partial = on_partial
        self._ws: websockets.ClientConnection | None = None
        self._reader: asyncio.Task | None = None
        self.result = AsrResult()
        self._final_waiter = asyncio.Event()
        self._closed = False

    async def start(self) -> None:
        headers = {
            "X-Api-App-Key": self._credentials.appid,
            "X-Api-Access-Key": self._credentials.access_token,
            "X-Api-Resource-Id": self._credentials.resource_id,
        }
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(ASR_WSS_URL, additional_headers=headers, max_size=None),
                timeout=10,
            )
        except (websockets.WebSocketException, asyncio.TimeoutError, OSError) as exc:
            raise AsrError(f"ASR 连接失败：{type(exc).__name__}") from exc

        request = {
            "user": {"uid": self._uid},
            "audio": AUDIO_FORMAT,
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True,
                # full：每次返回累计文本；split：返回增量
                "result_type": "full",
                "enable_words": True,
            },
        }
        await self._ws.send(build_json_request(request))
        self._reader = asyncio.create_task(self._read_loop())

    async def feed(self, pcm: bytes) -> None:
        if self._ws is not None and not self._closed:
            await self._ws.send(build_audio_frame(pcm))

    async def finish(self, timeout: float = 8.0) -> AsrResult:
        """发送结束帧，等待服务端剩余结果，汇总返回。"""
        if self._ws is not None and not self._closed:
            try:
                await self._ws.send(build_audio_frame(b"", last=True))
            except websockets.WebSocketException:
                pass
        try:
            await asyncio.wait_for(self._final_waiter.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("ASR finish 等待超时，使用已收到的增量结果")
        await self.close()
        return self.result

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
        if self._ws is not None:
            await self._ws.close()

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = parse_server_frame(raw)
                if msg.json is None:
                    continue
                self._handle_json(msg.json)
        except websockets.ConnectionClosed:
            pass
        except Exception:
            logger.exception("ASR 读取循环异常")
        finally:
            self._final_waiter.set()

    def _handle_json(self, data: dict[str, Any]) -> None:
        # 错误响应：{"error_code": ..., "error_msg": ...} 或 status 字段
        error_code = data.get("error_code") or data.get("code")
        if isinstance(error_code, int) and error_code not in (0, 200, 1000, 3000):
            logger.error("ASR 服务返回错误：%s", data)
            return

        result = data.get("result") or {}
        audio_info = data.get("audio_info") or {}

        if text := result.get("text"):
            if text != self.result.text:
                self.result.text = text
                if self._on_partial is not None:
                    # 回调中不允许抛异常中断读取循环
                    task = asyncio.ensure_future(self._on_partial(text))
                    task.add_done_callback(lambda t: t.exception())

        if utterances := result.get("utterances"):
            self.result.utterances = utterances

        if duration := audio_info.get("duration"):
            self.result.duration_ms = int(duration)

        if data.get("is_final"):
            self._final_waiter.set()


async def test_asr_connection(credentials: AsrCredentials) -> tuple[bool, str, int]:
    """最小化连通测试：建立 WS 连接并下发配置，验证鉴权与资源 ID。"""
    import time

    start = time.monotonic()
    session = VolcAsrSession(credentials)
    try:
        await session.start()
    except AsrError as exc:
        return False, f"{exc}（请检查 APPID / Access Token / Resource ID 是否匹配开通的模型版本）", int((time.monotonic() - start) * 1000)
    finally:
        await session.close()
    return True, "连接成功", int((time.monotonic() - start) * 1000)
