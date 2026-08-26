"""流利度规则引擎：纯 Python 统计，零成本，作为评分流水线的并行分支 A。

输入为会话的全部轮次（转写 + 前端 VAD 事件 + 起止时间），输出聚合指标。
speech_events 事件格式（useRecorder.ts）：{type: speech_start|speech_end|
silence_prompted|noisy, t: 相对录音开始的毫秒}。
"""

import re
from dataclasses import dataclass, field

# 常见英文填充词（含口语惯用冗余表达）；\b 防止匹配单词片段。
# 注意：裸 "like" 不计入（动词用法太常见，纯文本无法区分，误报代价高于收益）
FILLER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("um", re.compile(r"\bum+\b", re.IGNORECASE)),
    ("uh", re.compile(r"\buh+\b", re.IGNORECASE)),
    ("er", re.compile(r"\ber+\b", re.IGNORECASE)),
    ("i mean", re.compile(r"\bi\s+mean\b", re.IGNORECASE)),
    ("you know", re.compile(r"\byou\s+know\b", re.IGNORECASE)),
    ("kind of", re.compile(r"\bkind\s?of\b", re.IGNORECASE)),
    ("sort of", re.compile(r"\bsort\s?of\b", re.IGNORECASE)),
    ("basically", re.compile(r"\bbasically\b", re.IGNORECASE)),
    ("actually", re.compile(r"\bactually\b", re.IGNORECASE)),
]

LONG_PAUSE_MS = 2000  # 雅思口径：>2s 停顿明显影响流利度


@dataclass
class TurnFluency:
    seq: int
    words: int = 0
    speech_ms: int = 0
    total_ms: int = 0
    long_pauses: int = 0
    pause_ms: int = 0
    fillers: dict[str, int] = field(default_factory=dict)
    noisy: bool = False
    # speech_events 缺失时置 True（指标由起止时间估算）
    estimated: bool = False


@dataclass
class FluencyMetrics:
    turns: int = 0
    valid_turns: int = 0
    total_words: int = 0
    speech_seconds: float = 0.0
    total_seconds: float = 0.0
    wpm: float = 0.0  # 有效语速：词/有效发言分钟
    long_pause_count: int = 0
    long_pause_ratio: float = 0.0  # 长停顿占发言时段比例
    filler_total: int = 0
    filler_per_100: float = 0.0  # 每百词填充词
    noisy_turns: int = 0
    estimated: bool = False

    def to_dict(self) -> dict:
        return {
            "turns": self.turns,
            "valid_turns": self.valid_turns,
            "total_words": self.total_words,
            "speech_seconds": round(self.speech_seconds, 1),
            "total_seconds": round(self.total_seconds, 1),
            "wpm": round(self.wpm, 1),
            "long_pause_count": self.long_pause_count,
            "long_pause_ratio": round(self.long_pause_ratio, 3),
            "filler_total": self.filler_total,
            "filler_per_100": round(self.filler_per_100, 1),
            "noisy_turns": self.noisy_turns,
            "estimated": self.estimated,
        }


def count_fillers(transcript: str) -> dict[str, int]:
    hits: dict[str, int] = {}
    for name, pattern in FILLER_PATTERNS:
        n = len(pattern.findall(transcript))
        if n:
            hits[name] = n
    return hits


def _speech_segments(events: list[dict]) -> list[tuple[int, int]]:
    """把 speech_start/speech_end 事件序列折叠成 (start_ms, end_ms) 区间。

    容错：未闭合的 speech_start 以最后一个事件时间闭合。"""
    segments: list[tuple[int, int]] = []
    open_at: int | None = None
    last_t = 0
    for ev in events:
        t = ev.get("t")
        if not isinstance(t, (int, float)):
            continue
        t = int(t)
        last_t = max(last_t, t)
        if ev.get("type") == "speech_start" and open_at is None:
            open_at = t
        elif ev.get("type") == "speech_end" and open_at is not None:
            segments.append((open_at, max(t, open_at)))
            open_at = None
    if open_at is not None:
        segments.append((open_at, last_t))
    return segments


def _pause_gaps(segments: list[tuple[int, int]], end_ms: int) -> list[tuple[int, int]]:
    """相邻发言区间之间的静默间隔 [(start, end)]。"""
    gaps: list[tuple[int, int]] = []
    prev_end = 0
    for start, end in segments:
        if start > prev_end:
            gaps.append((prev_end, start))
        prev_end = max(prev_end, end)
    if end_ms > prev_end:
        gaps.append((prev_end, end_ms))
    return gaps


def analyze_turn(
    seq: int,
    transcript: str | None,
    speech_events: list | None,
    started_at,
    ended_at,
) -> TurnFluency:
    result = TurnFluency(seq=seq)
    transcript = transcript or ""
    result.words = len(transcript.split())
    result.fillers = count_fillers(transcript)

    events = [e for e in (speech_events or []) if isinstance(e, dict)]
    result.noisy = any(e.get("type") == "noisy" for e in events)

    if events:
        segments = _speech_segments(events)
        end_ms = max([e.get("t", 0) for e in events if isinstance(e.get("t"), (int, float))] or [0])
        result.total_ms = end_ms
        result.speech_ms = sum(end - start for start, end in segments)
        gaps = _pause_gaps(segments, end_ms)
        result.pause_ms = sum(end - start for start, end in gaps)
        result.long_pauses = sum(1 for start, end in gaps if end - start >= LONG_PAUSE_MS)
    else:
        # 兜底：无 VAD 事件（旧数据/事件丢失）时用起止时间估算
        result.estimated = True
        if started_at is not None and ended_at is not None:
            delta = (ended_at - started_at).total_seconds()
            result.total_ms = result.speech_ms = int(max(delta, 0) * 1000)
    return result


def aggregate(turn_results: list[TurnFluency]) -> FluencyMetrics:
    m = FluencyMetrics(turns=len(turn_results))
    valid = [t for t in turn_results if t.words > 0]
    m.valid_turns = len(valid)
    m.total_words = sum(t.words for t in valid)
    m.speech_seconds = sum(t.speech_ms for t in valid) / 1000
    m.total_seconds = sum(t.total_ms for t in valid) / 1000
    m.long_pause_count = sum(t.long_pauses for t in valid)
    m.noisy_turns = sum(1 for t in valid if t.noisy)
    m.estimated = all(t.estimated for t in valid) if valid else False

    filler_total = sum(sum(t.fillers.values()) for t in valid)
    m.filler_total = filler_total
    if m.speech_seconds > 0:
        m.wpm = m.total_words / (m.speech_seconds / 60)
    if m.total_seconds > 0:
        # 停顿时长（含长停顿）占发言总时段的比例
        pause_seconds = sum(t.pause_ms for t in valid) / 1000
        m.long_pause_ratio = min(pause_seconds / m.total_seconds if pause_seconds else 0.0, 1.0)
    if m.total_words > 0:
        m.filler_per_100 = filler_total / m.total_words * 100
    return m


def estimate_fluency_band(m: FluencyMetrics) -> float:
    """规则估算流利度 band（LLM 不可用时的降级路径，3.0-9.0 步长 0.5）。

    以语速 100-160 wpm 为 6.5 基准，按填充词密度与长停顿扣减。"""
    if m.valid_turns == 0 or m.total_words < 5:
        return 3.0

    band = 6.5
    # 语速区间评分（过慢 <85 / 过快 >170 都失分）
    if 100 <= m.wpm <= 160:
        band += 0.5
    elif 85 <= m.wpm < 100 or 160 < m.wpm <= 175:
        band -= 0.5
    elif m.wpm < 60 or m.wpm > 190:
        band -= 1.5
    else:
        band -= 1.0

    # 填充词密度：每百词
    if m.filler_per_100 >= 8:
        band -= 1.5
    elif m.filler_per_100 >= 5:
        band -= 1.0
    elif m.filler_per_100 >= 3:
        band -= 0.5

    # 长停顿：每 30 秒发言超过 1 次 2s+ 停顿开始扣分
    per_30s = m.long_pause_count / max(m.speech_seconds / 30, 0.5)
    if per_30s >= 3:
        band -= 1.5
    elif per_30s >= 2:
        band -= 1.0
    elif per_30s >= 1:
        band -= 0.5

    return _clamp_half(max(3.0, min(band, 9.0)))


def _clamp_half(value: float) -> float:
    return round(int(value * 2 + 0.5) / 2 if value >= 0 else value, 1)


def analyze_session(turns: list[dict]) -> tuple[FluencyMetrics, list[TurnFluency]]:
    """turns: [{seq, user_transcript, speech_events, started_at, ended_at}]"""
    results = [
        analyze_turn(
            t.get("seq", i + 1),
            t.get("user_transcript"),
            t.get("speech_events"),
            t.get("started_at"),
            t.get("ended_at"),
        )
        for i, t in enumerate(turns)
    ]
    return aggregate(results), results
