"""火山引擎语音服务 WebSocket 二进制协议（v1/v3 通用帧格式）。

帧结构：4 字节头 + 4 字节大端负载长度 + 负载

    byte0: protocol_version(4b) | header_size(4b)        -> 0x11
    byte1: message_type(4b)   | message_flags(4b)
    byte2: serialization(4b)  | message_compression(4b)
    byte3: reserved

消息类型：
    0b0001 full client request   0b0010 audio-only request
    0b1001 full server response  0b1010 audio-only server response
    0b1111 error response

标志位（byte1 低 4 位）：
    0b0001 gzip 压缩（请求侧）；服务器响应侧表示负载 gzip
    0b0010 last packet（音频流结束）
"""

import gzip
import json
import struct
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 0b0001
HEADER_SIZE = 0b0001

# 消息类型
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY = 0b0010
FULL_SERVER_RESPONSE = 0b1001
AUDIO_ONLY_SERVER = 0b1010
ERROR_RESPONSE = 0b1111

# 标志位
FLAG_NONE = 0b0000
FLAG_GZIP = 0b0001
FLAG_LAST_PACKET = 0b0010

# 序列化
SERIAL_JSON = 0b0001
SERIAL_RAW = 0b0000

# 压缩
COMPRESS_NONE = 0b0000
COMPRESS_GZIP = 0b0001


def build_header(
    message_type: int,
    flags: int = FLAG_NONE,
    serialization: int = SERIAL_RAW,
    compression: int = COMPRESS_NONE,
) -> bytes:
    header = bytearray(4)
    header[0] = (PROTOCOL_VERSION << 4) | HEADER_SIZE
    header[1] = (message_type << 4) | flags
    header[2] = (serialization << 4) | compression
    header[3] = 0
    return bytes(header)


def build_frame(
    message_type: int,
    payload: bytes,
    flags: int = FLAG_NONE,
    serialization: int = SERIAL_RAW,
    compression: int = COMPRESS_NONE,
) -> bytes:
    header = build_header(message_type, flags, serialization, compression)
    return header + struct.pack(">I", len(payload)) + payload


def build_json_request(payload: dict[str, Any], compress: bool = False) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    if compress:
        body = gzip.compress(body)
    return build_frame(
        FULL_CLIENT_REQUEST,
        body,
        flags=FLAG_GZIP if compress else FLAG_NONE,
        serialization=SERIAL_JSON,
        compression=COMPRESS_GZIP if compress else COMPRESS_NONE,
    )


def build_audio_frame(audio: bytes, last: bool = False) -> bytes:
    return build_frame(
        AUDIO_ONLY,
        audio,
        flags=FLAG_LAST_PACKET if last else FLAG_NONE,
        serialization=SERIAL_RAW,
        compression=COMPRESS_NONE,
    )


@dataclass
class ServerMessage:
    message_type: int          # FULL_SERVER_RESPONSE / AUDIO_ONLY_SERVER / ERROR_RESPONSE
    flags: int
    payload: bytes             # 已解压的负载
    json: dict[str, Any] | None = None   # JSON 消息已解析的内容
    is_last_audio: bool = False  # 音频流结束（TTS：flags 为 0 表示最后一包）

    @property
    def is_audio(self) -> bool:
        return self.message_type == AUDIO_ONLY_SERVER


def parse_server_frame(data: bytes) -> ServerMessage:
    """解析服务器帧。防御式解析：不同版本的负载长度字段处理略有差异。"""
    if len(data) < 4:
        raise ValueError("帧长度不足 4 字节")
    header_size = data[0] & 0x0F
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    compression = data[2] & 0x0F

    body = data[header_size * 4:]
    # 标准格式：4 字节大端长度前缀；个别版本不带，做一次自适应
    if len(body) >= 4:
        declared = struct.unpack(">I", body[:4])[0]
        if declared == len(body) - 4:
            body = body[4:]
        elif declared == 0 and len(body) == 4:
            body = b""

    if compression == COMPRESS_GZIP and body:
        body = gzip.decompress(body)

    msg = ServerMessage(message_type=message_type, flags=flags, payload=body)
    if message_type in (FULL_SERVER_RESPONSE, ERROR_RESPONSE):
        try:
            msg.json = json.loads(body) if body else {}
        except json.JSONDecodeError:
            msg.json = {"raw": body[:200].decode("utf-8", errors="replace")}
    return msg
