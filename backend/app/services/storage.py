"""音频存储：每轮作答的 PCM 累积 → WAV 归档。

本地卷实现；部署到火山引擎时按 docs/deployment.md 挂载卷即可，
后续接 TOS 时新增适配器保持 save/load 接口不变。
"""

import io
import logging
import struct
import uuid
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1, bits: int = 16) -> bytes:
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        sample_rate,
        sample_rate * channels * bits // 8,
        channels * bits // 8,
        bits,
        b"data",
        data_size,
    )
    return header + pcm


class StorageService:
    """会话内累积单轮 PCM，结束时落盘。"""

    def __init__(self, session_id: uuid.UUID) -> None:
        self._session_id = session_id
        self._buffer = bytearray()

    def feed(self, pcm: bytes) -> None:
        self._buffer.extend(pcm)

    def reset(self) -> None:
        self._buffer.clear()

    @property
    def size(self) -> int:
        return len(self._buffer)

    def flush_to_wav(self, turn_id: uuid.UUID) -> str | None:
        """当前缓冲写成 WAV，返回相对路径；无数据返回 None。"""
        if not self._buffer:
            return None
        rel_dir = Path("audio") / str(self._session_id)
        rel_path = rel_dir / f"{turn_id}.wav"
        root = Path(get_settings().storage_dir)
        abs_path = root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(pcm_to_wav(bytes(self._buffer)))
        self._buffer.clear()
        return rel_path.as_posix()


def open_audio_file(rel_path: str) -> BinaryIO | None:
    """按相对路径读取归档音频（回放接口用）。"""
    abs_path = Path(get_settings().storage_dir) / rel_path
    if not abs_path.is_file() or ".." in Path(rel_path).parts:
        return None
    return open(abs_path, "rb")
