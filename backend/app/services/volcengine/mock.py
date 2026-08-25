"""Mock 语音适配器：VOLC_MOCK=1 时替代真实火山服务。

用于无凭据环境下的开发与自动化测试：
- MockAsrSession：按投放的音频量渐进输出预置文本，模拟 partial → final
- mock_tts_audio：返回一段极短的静音 MP3 块
"""

import asyncio

from app.services.volcengine.asr import AsrResult

MOCK_ANSWER_POOL = [
    "I really enjoy listening to music, especially pop songs, because they help me relax after a long day of study.",
    "Well, I usually play basketball with my friends on weekends, and I think it is a great way to keep fit and socialize.",
    "To be honest, I prefer watching movies at home rather than going to the cinema, since it is more comfortable and much cheaper.",
    "I would say my hometown is a small city in the south, famous for its delicious food and friendly people who always make visitors feel welcome.",
    "In my opinion, learning a foreign language opens many doors, for example it allows us to communicate with people from different cultures.",
]


class MockAsrSession:
    """接口对齐 VolcAsrSession：start / feed / finish / close。"""

    def __init__(self, *, on_partial=None, text: str | None = None) -> None:
        import random

        self._on_partial = on_partial
        self._text = text or random.choice(MOCK_ANSWER_POOL)
        self._fed_bytes = 0
        self._emitted_words = 0
        self.result = AsrResult()

    async def start(self) -> None:
        self.result = AsrResult()

    async def feed(self, pcm: bytes) -> None:
        self._fed_bytes += len(pcm)
        # 32000 字节/秒（16k*16bit 单声道）；每约 1.5 秒多"识别"出几个词
        expected_words = int(self._fed_bytes / 32000 / 1.5 * 4)
        while self._emitted_words < min(expected_words, len(self._text.split())):
            self._emitted_words += 1
            partial = " ".join(self._text.split()[: self._emitted_words])
            self.result.text = partial
            if self._on_partial is not None:
                await self._on_partial(partial)
            await asyncio.sleep(0.01)

    async def finish(self, timeout: float = 8.0) -> AsrResult:
        await asyncio.sleep(0.2)  # 模拟服务端汇总延迟
        self.result.text = self._text
        self.result.duration_ms = int(self._fed_bytes / 32000 * 1000)
        self.result.words = []
        return self.result

    async def close(self) -> None:
        pass


def mock_tts_audio() -> bytes:
    """约 200ms 的静音 PCM（24kHz 16bit 单声道），与真实 TTS 输出格式一致。"""
    return b"\x00\x00" * 4800


async def mock_synthesize_stream(text, on_audio=None, **_kwargs) -> bytes:
    # 按句模拟流式：每个分块之间稍作延迟，验证前端播放队列
    chunks = [mock_tts_audio() for _ in range(max(2, min(6, len(text) // 40 + 2)))]
    for chunk in chunks:
        if on_audio is not None:
            await on_audio(chunk)
        await asyncio.sleep(0.05)
    return b"".join(chunks)
