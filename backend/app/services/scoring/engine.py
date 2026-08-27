"""评分编排引擎：练习结束后生成完整评分报告。

两阶段流水线（真机实测 seed-2.1 生成约 12 tok/s，大 JSON 无法在 10s 内产出）：
- 阶段一（10s 预算，报告先完成）：
  - 并行 A：流利度规则引擎（纯本地）
  - 并行 B：火山口语评测（每有效轮次一次，音频 + 参考文本=该轮转写）
  - 并行 C：LLM 快速四维打分（输出仅 4 个数字，10s 超时）
  - 融合落库：发音 = 真实评测 0.7 + LLM 0.3；综合 = 四维均值按雅思规则取半档
- 阶段二（后台任务，前端轮询渐进呈现）：LLM 深度分析一次产出逐句分析 + 中文反馈
- 降级：LLM 打分失败 → 规则引擎出流利度、其余维度保守 5.0 并标注低置信度
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.base import async_session_factory
from app.db.models import PracticeSession, PracticeTurn, ScoreReport, Topic, TurnAnalysis, User
from app.services.scoring import fluency as fluency_svc
from app.services.scoring import llm_scorer, prompts
from app.services.volcengine import speech as speech_svc
from app.services.volcengine.evaluation import EvaluationError

logger = logging.getLogger(__name__)

# 深度分析输出约 1200-2000 token（pro 实测 ~18 tok/s 无思考），180s 覆盖
DEEP_ANALYSIS_TIMEOUT_SECONDS = 180.0


class ScoringError(Exception):
    """流水线业务性失败（如无有效作答），报告置 failed 并落可读错误。"""


# ---------------------------------------------------------------------------
# 融合规则
# ---------------------------------------------------------------------------

def _half_step(value: float) -> float:
    return round(int(value * 2 + 0.5) / 2, 1)


def eval_score_to_band(score: float) -> float:
    """评测原始分（0-100 或 0-10）→ 发音 band（3-9 半档）。"""
    band = score / 100 * 9 if score > 10 else score * 0.9
    return max(3.0, min(_half_step(band), 9.0))


def fuse_pronunciation(
    llm_band: float | None, eval_band: float | None, eval_is_mock: bool
) -> tuple[float | None, list[str]]:
    """发音维度融合：真实评测 0.7 + LLM 0.3；返回 (band, 低置信度标注)。"""
    notes: list[str] = []
    if eval_band is None:
        if llm_band is None:
            return None, ["pronunciation_missing"]
        return llm_band, ["pronunciation_missing"]
    if eval_is_mock:
        notes.append("pronunciation_mock")
        return llm_band or eval_band, notes
    if llm_band is None:
        return eval_band, notes
    return _half_step(eval_band * 0.7 + llm_band * 0.3), notes


def fuse_overall(
    fluency: float, lexical: float, grammar: float, pronunciation: float
) -> float:
    """综合 Band：四维均值按雅思规则取最近的 0.5 档。"""
    mean = (fluency + lexical + grammar + pronunciation) / 4
    return max(3.0, min(_half_step(mean), 9.0))


def low_confidence_flags(
    *,
    total_words: int,
    noisy_turns: int,
    dimensions: list[float],
    extra: list[str],
) -> list[str]:
    flags = list(extra)
    if total_words < 30:
        flags.append("answer_too_short")
    if noisy_turns > 0:
        flags.append("audio_noisy")
    if max(dimensions) - min(dimensions) > 2:
        flags.append("dimension_spread")
    return flags


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

async def ensure_report(session_id, user_id) -> tuple[ScoreReport, bool]:
    """获取或创建报告行。返回 (report, created)。"""
    async with async_session_factory() as db:
        report = await db.scalar(
            select(ScoreReport).where(ScoreReport.session_id == session_id)
        )
        if report is None:
            report = ScoreReport(session_id=session_id, user_id=user_id, status="pending")
            db.add(report)
            await db.commit()
            await db.refresh(report)
            return report, True
        return report, False


async def trigger_scoring(session_id, *, force: bool = False) -> ScoreReport | None:
    """触发评分（幂等）。processing 中不重复触发，force=True 用于手动重评。"""
    from app.db.base import async_session_factory as factory

    async with factory() as db:
        session = await db.get(PracticeSession, session_id)
        if session is None or session.status != "completed":
            return None
        report = await db.scalar(
            select(ScoreReport).where(ScoreReport.session_id == session_id)
        )
        if report is None:
            report = ScoreReport(session_id=session_id, user_id=session.user_id, status="pending")
            db.add(report)
            await db.commit()
            await db.refresh(report)
        elif report.status == "processing" and not force:
            return report
        else:
            report.status = "pending"
            report.error = None
            await db.commit()

    asyncio.create_task(run_scoring(session_id))
    # 返回触发后的报告快照（处理中）
    async with factory() as db:
        return await db.scalar(select(ScoreReport).where(ScoreReport.session_id == session_id))


async def run_scoring(session_id) -> None:
    """执行完整评分流水线并落库。后台任务上下文，自身管理 DB 会话。"""
    started = time.monotonic()
    async with async_session_factory() as db:
        report = await db.scalar(
            select(ScoreReport).where(ScoreReport.session_id == session_id)
        )
        session = await db.get(PracticeSession, session_id)
        if report is None or session is None:
            logger.error("评分任务找不到会话或报告：%s", session_id)
            return
        user = await db.get(User, session.user_id)
        topic = await db.get(Topic, session.topic_id) if session.topic_id else None
        turns = (
            await db.scalars(
                select(PracticeTurn)
                .where(PracticeTurn.session_id == session_id)
                .order_by(PracticeTurn.seq)
            )
        ).all()

        report.status = "processing"
        report.error = None
        await db.commit()

        try:
            pron_summary = await _run_pipeline(db, report, session, topic, turns, user)
            report.status = "completed"
            report.completed_at = datetime.now(timezone.utc)
        except ScoringError as exc:
            pron_summary = None
            report.status = "failed"
            report.error = str(exc)[:500]
        except Exception as exc:  # noqa: BLE001  后台任务兜底：任何失败落库可读错误
            pron_summary = None
            logger.exception("评分流水线失败：%s", session_id)
            report.status = "failed"
            report.error = str(exc)[:500]
        await db.commit()

        # 阶段二在状态提交为 completed 之后才启动（避免读到 processing 静默退出）
        if pron_summary is not None:
            asyncio.create_task(_deep_analysis_later(session_id, pron_summary))
        logger.info(
            "评分完成 %s：status=%s 耗时 %.1fs",
            session_id, report.status, time.monotonic() - started,
        )


async def _run_pipeline(db, report, session, topic, turns, user) -> None:
    valid_turns = [t for t in turns if (t.user_transcript or "").strip()]
    if not valid_turns:
        raise ScoringError("有效作答轮次不足（没有可评分的回答）")

    turn_dicts = [
        {
            "seq": t.seq,
            "question_text": t.question_text,
            "user_transcript": t.user_transcript,
            "is_followup": t.is_followup,
            "speech_events": t.speech_events,
            "started_at": t.started_at,
            "ended_at": t.ended_at,
        }
        for t in valid_turns
    ]

    # ---- 阶段一：并行 A/B/C（评测 + 快速打分）+ 融合 ----
    metrics, turn_fluency = fluency_svc.analyze_session(turn_dicts)
    metrics_dict = metrics.to_dict()
    valid_fluency = [t for t in turn_fluency if t.words > 0]

    eval_task = asyncio.create_task(_evaluate_turns(user, db, valid_turns))
    score_content = prompts.build_score_user_content(
        part=session.part,
        topic_name=topic.name_en if topic else "General",
        turns=turn_dicts,
        fluency_metrics=metrics_dict,
        pronunciation_summary="",
    )
    llm_task = asyncio.create_task(llm_scorer.score_dimensions(user, db, user_content=score_content))

    eval_results, eval_is_mock = await eval_task
    llm_result, score_model = await llm_task

    pron_summary = _pronunciation_summary(eval_results)

    # ---- 融合 ----
    notes: list[str] = []
    if llm_result is not None:
        llm_scores = llm_result["scores"]
    else:
        # 降级：规则引擎只可靠产出流利度；其余维度保守值并标注
        llm_scores = {
            "fluency": fluency_svc.estimate_fluency_band(metrics),
            "lexical": 5.0,
            "grammar": 5.0,
            "pronunciation": 5.0,
        }
        notes.append("llm_score_unavailable")

    avg_eval_band = None
    if eval_results:
        scored = [r["band"] for r in eval_results if r.get("band") is not None]
        if scored:
            avg_eval_band = sum(scored) / len(scored)
    pron_band, pron_notes = fuse_pronunciation(
        llm_scores["pronunciation"], avg_eval_band, eval_is_mock
    )
    notes.extend(pron_notes)

    fluency_band = llm_scores["fluency"]
    report.fluency = fluency_band
    report.lexical = llm_scores["lexical"]
    report.grammar = llm_scores["grammar"]
    report.pronunciation = pron_band
    report.overall_band = fuse_overall(
        fluency_band, llm_scores["lexical"], llm_scores["grammar"], pron_band or 5.0
    )
    report.fluency_metrics = metrics_dict
    report.low_confidence = low_confidence_flags(
        total_words=metrics.total_words,
        noisy_turns=metrics.noisy_turns,
        dimensions=[fluency_band, llm_scores["lexical"], llm_scores["grammar"], pron_band or 5.0],
        extra=notes,
    )
    report.model_versions = {
        "llm_score": score_model,
        "llm_deep": None,
        "evaluation": "mock" if eval_is_mock else "volc.mdd",
        "deep_pending": True,
    }

    # ---- 逐轮分析落库（先写评测/填充词；句子由阶段二补齐；重评时先清空）----
    await db.execute(delete(TurnAnalysis).where(TurnAnalysis.report_id == report.id))
    for turn, tf in zip(valid_turns, valid_fluency):
        eval_raw = next((e for e in eval_results if e["seq"] == turn.seq), None)
        db.add(
            TurnAnalysis(
                report_id=report.id,
                turn_id=turn.id,
                seq=turn.seq,
                sentences=None,
                pronunciation_detail=eval_raw["detail"] if eval_raw else None,
                filler_hits=[{"word": k, "count": v} for k, v in tf.fillers.items()] or None,
            )
        )
    await db.commit()
    return pron_summary


def _apply_feedback(report: ScoreReport, feedback: dict) -> None:
    report.overall_comment_zh = feedback["overall_comment_zh"]
    report.strengths = feedback["strengths"]
    report.improvements = feedback["improvements"]
    report.expression_upgrades = feedback["expression_upgrades"]


async def _deep_analysis_later(session_id, pron_summary: str) -> None:
    """阶段二补偿任务：长预算产出逐句分析 + 中文反馈，原地更新已完成报告。"""
    try:
        async with async_session_factory() as db:
            report = await db.scalar(
                select(ScoreReport).where(ScoreReport.session_id == session_id)
            )
            session = await db.get(PracticeSession, session_id)
            if report is None or session is None:
                return
            # 幂等守卫：状态未到 completed（上游失败）或已有深度结果时跳过
            versions = report.model_versions or {}
            if report.status != "completed" or (
                not versions.get("deep_pending") and report.overall_comment_zh
            ):
                return
            user = await db.get(User, session.user_id)
            topic = await db.get(Topic, session.topic_id) if session.topic_id else None
            turns = (
                await db.scalars(
                    select(PracticeTurn)
                    .where(PracticeTurn.session_id == session_id)
                    .order_by(PracticeTurn.seq)
                )
            ).all()
            turn_dicts = [
                {
                    "seq": t.seq, "question_text": t.question_text,
                    "user_transcript": t.user_transcript, "is_followup": t.is_followup,
                    "speech_events": t.speech_events,
                    "started_at": t.started_at, "ended_at": t.ended_at,
                }
                for t in turns if (t.user_transcript or "").strip()
            ]
            if not turn_dicts:
                return

            content = prompts.build_deep_analysis_user_content(
                part=session.part,
                topic_name=topic.name_en if topic else "General",
                turns=turn_dicts,
                scores={
                    "fluency": float(report.fluency or 5),
                    "lexical": float(report.lexical or 5),
                    "grammar": float(report.grammar or 5),
                    "pronunciation": float(report.pronunciation or 5),
                    "overall_band": float(report.overall_band or 5),
                },
                fluency_metrics=report.fluency_metrics or {},
                pronunciation_summary=pron_summary,
            )
            result, model = await asyncio.wait_for(
                llm_scorer.deep_analysis(user, db, user_content=content),
                timeout=DEEP_ANALYSIS_TIMEOUT_SECONDS,
            )
            if result is None:
                logger.warning("评分报告 %s 深度分析失败（保留已出分数）", session_id)
                return

            _apply_feedback(report, result["feedback"])
            sentences_by_seq = {t["seq"]: t["sentences"] for t in result["turns"]}
            analyses = (
                await db.scalars(
                    select(TurnAnalysis).where(TurnAnalysis.report_id == report.id)
                )
            ).all()
            for analysis in analyses:
                if analysis.seq in sentences_by_seq:
                    analysis.sentences = sentences_by_seq[analysis.seq]

            versions = dict(report.model_versions or {})
            versions["llm_deep"] = model
            versions["deep_pending"] = False
            report.model_versions = versions
            await db.commit()
            logger.info("评分报告 %s 深度分析补齐完成", session_id)
    except asyncio.TimeoutError:
        logger.warning("评分报告 %s 深度分析超时（%.0fs）", session_id, DEEP_ANALYSIS_TIMEOUT_SECONDS)
    except Exception:
        logger.exception("深度分析补齐失败：%s", session_id)


async def _evaluate_turns(user, db, turns) -> tuple[list[dict], bool]:
    """逐轮发音评测。返回 (结果列表, 是否全部为 mock/降级)。单轮失败跳过不阻断。"""
    settings = get_settings()

    async def one(turn) -> dict:
        wav = _read_turn_audio(turn.audio_path)
        if wav is None:
            return {"seq": turn.seq, "band": None, "detail": None, "error": "no_audio"}
        try:
            result = await speech_svc.evaluate_turn_speech(
                wav, turn.user_transcript or "", user, db, uid=str(user.id)
            )
        except EvaluationError as exc:
            logger.warning("轮次 %s 发音评测失败：%s", turn.seq, exc)
            return {"seq": turn.seq, "band": None, "detail": None, "error": str(exc)[:200]}
        band = eval_score_to_band(result.score) if result.score is not None else None
        detail = {
            "score": result.score,
            "fluency": result.fluency,
            "integrity": result.integrity,
            "words": [
                {"word": w.word, "score": w.score} for w in result.words[:80]
            ],
            "mock": bool(result.raw.get("mock")),
        }
        return {"seq": turn.seq, "band": band, "detail": detail, "error": None}

    results = await asyncio.gather(*(one(t) for t in turns))
    is_mock = bool(settings.volc_mock) or all(
        (r["detail"] or {}).get("mock") or r["error"] for r in results
    )
    return list(results), is_mock


def _read_turn_audio(rel_path: str | None) -> bytes | None:
    if not rel_path:
        return None
    path = Path(get_settings().storage_dir) / rel_path
    try:
        if path.is_file():
            return path.read_bytes()
    except OSError:
        logger.warning("读取轮次音频失败：%s", rel_path)
    return None


def _pronunciation_summary(eval_results: list[dict]) -> str:
    parts = []
    for r in eval_results:
        detail = r.get("detail") or {}
        if r.get("band") is not None:
            worst = sorted(
                (w for w in detail.get("words", []) if w.get("score") is not None),
                key=lambda w: w["score"],
            )[:3]
            parts.append(
                f"轮次{r['seq']}: 评测分 {detail.get('score'):.0f}/100（约 band {r['band']}）"
                + (f"；薄弱词 {', '.join(w['word'] for w in worst)}" if worst else "")
            )
        elif r.get("error"):
            parts.append(f"轮次{r['seq']}: 评测失败（{r['error'][:60]}）")
    return "; ".join(parts)


async def recover_stale_reports(max_age_minutes: int = 15) -> int:
    """把卡在 processing 超过时限的报告标记为 failed（进程重启/任务丢失的兜底）。

    应用启动时与周期任务调用。用户可在报告页点击「重新评分」重跑。"""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    async with async_session_factory() as db:
        rows = await db.scalars(
            select(ScoreReport).where(
                ScoreReport.status == "processing",
                ScoreReport.created_at < cutoff,
            )
        )
        stale = list(rows)
        for report in stale:
            report.status = "failed"
            report.error = "评分超时中断（服务重启或网络故障），请点击「重新评分」重试"
            await db.commit()
        if stale:
            logger.warning("回收 %d 份卡死的评分报告", len(stale))
        return len(stale)


async def _stale_report_sweeper() -> None:
    # 首轮延迟 5 秒：启动后先回收孤儿报告，之后每 5 分钟巡检
    await asyncio.sleep(5)
    while True:
        try:
            await recover_stale_reports()
        except Exception:
            logger.exception("卡死报告回收失败")
        await asyncio.sleep(300)


_sweeper_task: asyncio.Task | None = None


def start_stale_sweeper() -> None:
    global _sweeper_task
    if _sweeper_task is None or _sweeper_task.done():
        _sweeper_task = asyncio.create_task(_stale_report_sweeper())


def stop_stale_sweeper() -> None:
    global _sweeper_task
    if _sweeper_task is not None:
        _sweeper_task.cancel()
        _sweeper_task = None
