"""Part C 评分系统测试：流利度规则引擎 / LLM 解析容错 / 融合规则 / 降级路径 / API。"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.services.scoring import fluency as fluency_svc
from app.services.scoring import llm_scorer
from app.services.scoring.engine import (
    eval_score_to_band,
    fuse_overall,
    fuse_pronunciation,
    low_confidence_flags,
)


# ---------------------------------------------------------------------------
# 流利度规则引擎
# ---------------------------------------------------------------------------


def _ev(t: int, kind: str) -> dict:
    return {"type": kind, "t": t}


def test_fluency_basic_metrics():
    """构造 20s 轮次：两段发言（0-8s / 11-20s），中间 3s 停顿；48 词含填充词。"""
    transcript = "I really like my hometown " + "um " * 2 + "because the food is great " + "you know " * 1 + "and people are friendly there."
    events = [
        _ev(0, "speech_start"), _ev(8000, "speech_end"),
        _ev(11000, "speech_start"), _ev(20000, "speech_end"),
    ]
    metrics, turns = fluency_svc.analyze_session(
        [{
            "seq": 1, "user_transcript": transcript, "speech_events": events,
            "started_at": None, "ended_at": None,
        }]
    )
    assert metrics.valid_turns == 1
    assert metrics.total_seconds == 20.0
    assert metrics.speech_seconds == 17.0
    assert metrics.long_pause_count == 1  # 段间 3s 静默
    assert metrics.filler_total == 3
    assert metrics.wpm > 0
    fillers = turns[0].fillers
    assert fillers["um"] == 2
    assert fillers["you know"] == 1


def test_fluency_long_pauses():
    """发言 2s + 停 2.5s + 发言 2s → 一次长停顿。"""
    events = [
        _ev(0, "speech_start"), _ev(2000, "speech_end"),
        _ev(4500, "speech_start"), _ev(6500, "speech_end"),
    ]
    metrics, _ = fluency_svc.analyze_session(
        [{"seq": 1, "user_transcript": "hello world again today",
          "speech_events": events, "started_at": None, "ended_at": None}]
    )
    assert metrics.long_pause_count == 1


def test_fluency_unclosed_speech_segment():
    """speech_end 丢失：以最后事件时间闭合，不抛错。"""
    events = [_ev(0, "speech_start"), _ev(5000, "noisy")]
    metrics, _ = fluency_svc.analyze_session(
        [{"seq": 1, "user_transcript": "some words here",
          "speech_events": events, "started_at": None, "ended_at": None}]
    )
    assert metrics.speech_seconds == 5.0
    assert metrics.noisy_turns == 1


def test_fluency_fallback_without_events():
    """无 VAD 事件：用起止时间估算并打 estimated 标记。"""
    start = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
    metrics, _ = fluency_svc.analyze_session(
        [{"seq": 1, "user_transcript": "a b c d e f",
          "speech_events": None, "started_at": start,
          "ended_at": start + timedelta(seconds=12)}]
    )
    assert metrics.estimated is True
    assert metrics.total_seconds == 12.0


def test_estimate_fluency_band_ranges():
    """语速正常无填充词 ≥6.0；重度填充词 + 多长停顿显著降低；空数据兜底 3.0。"""
    good = fluency_svc.aggregate([
        fluency_svc.TurnFluency(seq=1, words=120, speech_ms=60000, total_ms=64000)
    ])
    good_band = fluency_svc.estimate_fluency_band(good)
    assert 6.0 <= good_band <= 8.0

    bad = fluency_svc.aggregate([
        fluency_svc.TurnFluency(
            seq=1, words=40, speech_ms=60000, total_ms=120000,
            long_pauses=8, fillers={"um": 8},
        )
    ])
    assert fluency_svc.estimate_fluency_band(bad) < good_band

    empty = fluency_svc.aggregate([])
    assert fluency_svc.estimate_fluency_band(empty) == 3.0


# ---------------------------------------------------------------------------
# LLM 输出解析容错
# ---------------------------------------------------------------------------


def test_clamp_band():
    assert llm_scorer.clamp_band(6.3) == 6.5
    assert llm_scorer.clamp_band("7") == 7.0
    assert llm_scorer.clamp_band(12) == 9.0
    assert llm_scorer.clamp_band(None) == 3.0
    assert llm_scorer.clamp_band("abc") == 3.0


@pytest.mark.asyncio
async def test_score_dimensions_quick(monkeypatch):
    """快速打分：markdown 围栏容忍 + 超界钳制。"""
    raw = """前置说明
```json
{"fluency": 6.4, "lexical": 99, "grammar": "5.5", "pronunciation": 2.0}
```
后置说明"""

    async def fake_ask(user, db, system, content, *, model, max_tokens, timeout):
        return llm_scorer._extract_json(raw)

    async def fake_model(db, user):
        return None

    monkeypatch.setattr(llm_scorer, "_ask_llm", fake_ask)
    monkeypatch.setattr(llm_scorer, "_user_model", fake_model)
    result, model = await llm_scorer.score_dimensions(
        user=None, db=None, user_content="x"
    )
    assert result is not None
    assert result["scores"]["fluency"] == 6.5
    assert result["scores"]["lexical"] == 9.0  # 99 → 钳制
    assert result["scores"]["grammar"] == 5.5
    assert result["scores"]["pronunciation"] == 3.0  # 低于下限 → 钳制
    assert model == llm_scorer.SCORE_MODEL_DEFAULT


@pytest.mark.asyncio
async def test_deep_analysis_bad_fields(monkeypatch):
    """深度分析：非法枚举值 + 空句 + 无效替换条目全部被容错修正/丢弃。"""
    raw = {
        "turns": [
            {"seq": "1", "sentences": [
                {"text": "I go school yesterday.", "issues": [
                    {"type": "tense", "severity": "huge", "explanation_zh": "时态错误",
                     "suggestion": "I went to school"}]},
                {"text": "", "issues": []},
            ]},
        ],
        "overall_comment_zh": "整体不错",
        "strengths": ["用了例子", ""],
        "improvements": ["减少停顿"],
        "expression_upgrades": [
            {"original": "very good", "upgraded": "remarkable", "note_zh": "更精准"},
            {"original": "", "upgraded": "x"},  # 无效条目被丢弃
        ],
    }

    async def fake_ask(user, db, system, content, *, model, max_tokens, timeout):
        return raw

    async def fake_model(db, user):
        return None

    monkeypatch.setattr(llm_scorer, "_ask_llm", fake_ask)
    monkeypatch.setattr(llm_scorer, "_user_model", fake_model)
    result, model = await llm_scorer.deep_analysis(user=None, db=None, user_content="x")
    assert result is not None
    turn = result["turns"][0]
    assert turn["seq"] == 1
    assert len(turn["sentences"]) == 1  # 空句被丢弃
    issue = turn["sentences"][0]["issues"][0]
    assert issue["type"] == "grammar"  # tense → 修正
    assert issue["severity"] == "moderate"  # huge → 修正
    feedback = result["feedback"]
    assert feedback["strengths"] == ["用了例子"]
    assert len(feedback["expression_upgrades"]) == 1
    assert model == llm_scorer.FEEDBACK_MODEL_DEFAULT


@pytest.mark.asyncio
async def test_deep_analysis_empty_returns_none(monkeypatch):
    async def fake_ask(user, db, system, content, *, model, max_tokens, timeout):
        return {"strengths": [], "improvements": [], "turns": []}

    async def fake_model(db, user):
        return None

    monkeypatch.setattr(llm_scorer, "_ask_llm", fake_ask)
    monkeypatch.setattr(llm_scorer, "_user_model", fake_model)
    result, _ = await llm_scorer.deep_analysis(user=None, db=None, user_content="x")
    assert result is None


# ---------------------------------------------------------------------------
# 融合规则
# ---------------------------------------------------------------------------


def test_eval_score_to_band():
    assert eval_score_to_band(90) == 8.0  # 8.1 → 半档 8.0
    assert eval_score_to_band(72) == 6.5
    assert eval_score_to_band(100) == 9.0
    assert eval_score_to_band(10) == 9.0  # 0-10 制按 10 分满分处理 → 9
    assert eval_score_to_band(1) == 3.0  # 下限


def test_fuse_pronunciation():
    band, notes = fuse_pronunciation(6.0, 7.0, eval_is_mock=False)
    assert band == 6.5  # 0.7*7 + 0.3*6 = 6.7 → 6.5
    assert notes == []
    band, notes = fuse_pronunciation(6.0, 7.0, eval_is_mock=True)
    assert notes == ["pronunciation_mock"]
    assert band == 6.0  # mock 时信 LLM
    band, notes = fuse_pronunciation(6.0, None, eval_is_mock=False)
    assert band == 6.0
    assert notes == ["pronunciation_missing"]


def test_fuse_overall_ielts_rounding():
    # 官方口径：四维均值取最近的 0.5 档（.25/.75 向上）
    assert fuse_overall(6.0, 6.0, 6.0, 5.5) == 6.0  # 5.875 → 6.0
    assert fuse_overall(7.0, 7.0, 7.0, 6.0) == 7.0  # 6.75 → 7.0
    assert fuse_overall(5.0, 5.0, 5.0, 5.0) == 5.0


def test_low_confidence_flags():
    flags = low_confidence_flags(
        total_words=20, noisy_turns=1, dimensions=[8.0, 5.0, 5.0, 5.0], extra=["llm_score_unavailable"]
    )
    assert "answer_too_short" in flags
    assert "audio_noisy" in flags
    assert "dimension_spread" in flags
    assert "llm_score_unavailable" in flags


# ---------------------------------------------------------------------------
# 评分流水线（Mock 模式端到端）
# ---------------------------------------------------------------------------


async def _seed_completed_session(db_engine):
    """直接落库：用户 + 已完成会话 + 一个有效轮次。返回 (user_id, session_id, turn_id, topic_name)。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import PracticeSession, PracticeTurn, Topic, User

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db:
        user = User(email=f"scorer-{uuid.uuid4().hex[:8]}@test.com", hashed_password="x")
        db.add(user)
        await db.flush()
        topic = Topic(name_en=f"Topic-{uuid.uuid4().hex[:6]}", name_zh="测试话题")
        db.add(topic)
        await db.flush()
        session = PracticeSession(
            user_id=user.id, part=1, topic_id=topic.id, status="completed",
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
        )
        db.add(session)
        await db.flush()
        turn = PracticeTurn(
            session_id=session.id, seq=1,
            question_text="Where do you live?",
            user_transcript=(
                "I live in a small city in the south of China. "
                "It is famous for its delicious food, and the people there are very friendly. "
                "um I have lived there for more than twenty years since I was born."
            ),
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc) + timedelta(seconds=18),
        )
        db.add(turn)
        await db.commit()
        return user.id, session.id, turn.id, topic.name_en


@pytest.mark.asyncio
async def test_scoring_pipeline_degradation(db_engine, monkeypatch, tmp_path):
    """无 LLM Key + Mock 评测：降级路径产出完整报告（规则流利度 + 低置信度标注）。"""
    from app.core.config import get_settings
    from app.db.models import ScoreReport, TurnAnalysis
    from app.services.scoring import engine as scoring_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    monkeypatch.setattr(get_settings(), "volc_mock", True)
    monkeypatch.setattr(get_settings(), "volc_ark_default_api_key", None)
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(scoring_engine, "async_session_factory", factory)

    user_id, session_id, turn_id, _ = await _seed_completed_session(db_engine)

    await scoring_engine.ensure_report(session_id, user_id)
    await scoring_engine.run_scoring(session_id)

    async with factory() as db:
        from app.db.models import ScoreReport, TurnAnalysis

        report = await db.scalar(
            select(ScoreReport).where(ScoreReport.session_id == session_id)
        )
        assert report is not None
        assert report.status == "completed"
        assert report.overall_band is not None and 3.0 <= float(report.overall_band) <= 9.0
        assert 3.0 <= float(report.fluency) <= 9.0
        assert float(report.lexical) == 5.0  # LLM 不可用降级
        assert "llm_score_unavailable" in (report.low_confidence or [])
        assert report.model_versions["evaluation"] == "mock"
        analyses = (
            await db.scalars(
                select(TurnAnalysis).where(TurnAnalysis.report_id == report.id)
            )
        ).all()
        assert len(analyses) == 1
        assert analyses[0].turn_id == turn_id


@pytest.mark.asyncio
async def test_scoring_pipeline_no_valid_turns(db_engine, monkeypatch):
    from app.core.config import get_settings
    from app.db.models import PracticeSession, PracticeTurn, ScoreReport, User
    from app.services.scoring import engine as scoring_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    monkeypatch.setattr(get_settings(), "volc_mock", True)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(scoring_engine, "async_session_factory", factory)

    async with factory() as db:
        user = User(email=f"empty-{uuid.uuid4().hex[:8]}@test.com", hashed_password="x")
        db.add(user)
        await db.flush()
        session = PracticeSession(user_id=user.id, part=1, status="completed")
        db.add(session)
        await db.flush()
        db.add(PracticeTurn(session_id=session.id, seq=1, user_transcript=None))
        await db.commit()
        session_id = session.id
        user_id = user.id

    await scoring_engine.ensure_report(session_id, user_id)
    await scoring_engine.run_scoring(session_id)

    async with factory() as db:
        report = await db.scalar(select(ScoreReport).where(ScoreReport.session_id == session_id))
        assert report.status == "failed"
        assert "有效作答" in (report.error or "")


@pytest.mark.asyncio
async def test_rescore_idempotent(db_engine, monkeypatch):
    """重评复用同一报告行（session 唯一），不重复建行。"""
    from app.core.config import get_settings
    from app.db.models import ScoreReport
    from app.services.scoring import engine as scoring_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    monkeypatch.setattr(get_settings(), "volc_mock", True)
    monkeypatch.setattr(get_settings(), "volc_ark_default_api_key", None)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(scoring_engine, "async_session_factory", factory)

    user_id, session_id, _, _ = await _seed_completed_session(db_engine)
    await scoring_engine.ensure_report(session_id, user_id)
    await scoring_engine.run_scoring(session_id)
    await scoring_engine.ensure_report(session_id, user_id)
    await scoring_engine.run_scoring(session_id)

    async with factory() as db:
        rows = (await db.scalars(
            select(ScoreReport).where(ScoreReport.session_id == session_id)
        )).all()
        assert len(rows) == 1
        assert rows[0].status == "completed"
