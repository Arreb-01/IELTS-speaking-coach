"""腾讯云智聆口语评测适配器单测（纯解析逻辑，不触网）。"""

import io
import wave

import pytest

from app.services.tencent.soe import (
    TencentEvaluationError,
    _clip_wav_to_60s,
    _normalize_100,
    _parse_result,
)


def make_wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(rate * seconds))
    return buf.getvalue()


def test_normalize_100_fractional_and_score_scales():
    assert _normalize_100(0.938, scale_if_fractional=True) == 93.8
    assert _normalize_100(1, scale_if_fractional=True) == 100.0
    # 准确度本身就是百分制，不应被放大
    assert _normalize_100(92.1, scale_if_fractional=False) == 92.1
    assert _normalize_100("bad", scale_if_fractional=False) is None
    assert _normalize_100(None, scale_if_fractional=False) is None


def test_parse_result_maps_fields_and_words():
    result = {
        "SuggestedScore": 92.1019515991211,
        "PronAccuracy": 91.7,
        "PronFluency": 0.9380993247032166,
        "PronCompletion": 1,
        "Words": [
            {
                "Word": "well",
                "PronAccuracy": 95.76,
                "MemBeginTime": 110,
                "MemEndTime": 720,
            },
            {"PronAccuracy": None},  # 无词名，应丢弃
        ],
    }
    parsed = _parse_result(result)
    assert parsed.ok and parsed.score == pytest.approx(92.1, abs=0.01)
    assert parsed.fluency == 93.8
    assert parsed.integrity == 100.0
    assert [w.word for w in parsed.words] == ["well"]
    assert parsed.words[0].score == pytest.approx(95.8, abs=0.01)
    assert (parsed.words[0].start_ms, parsed.words[0].end_ms) == (110, 720)
    assert parsed.raw == {"tencent": True}


def test_parse_result_falls_back_to_accuracy_when_no_suggested():
    parsed = _parse_result({"SuggestedScore": 0, "PronAccuracy": 77.5})
    assert parsed.score == pytest.approx(77.5, abs=0.01)


def test_clip_wav_truncates_to_60s():
    long = make_wav(seconds=61.5)
    clipped = _clip_wav_to_60s(long)
    with wave.open(io.BytesIO(clipped), "rb") as w:
        assert w.getnframes() <= 16000 * 60
        assert w.getframerate() == 16000

    short = make_wav(seconds=4)
    assert _clip_wav_to_60s(short) == short
    # 非法输入原样返回，交给服务端报错
    assert _clip_wav_to_60s(b"not-a-wav") == b"not-a-wav"


def test_error_types():
    assert issubclass(TencentEvaluationError, Exception)
