"""学习路径推荐引擎（Part E，确定性规则版）。

架构决策（docs/part-e-plan.md 三.2）：
- 弱项判定：近 5 次 completed 报告四维均值，最低为一号弱项；
  <5 次走固定新手计划；0 报告不生成任务（未测评用户见引导卡）。
- 推荐话题：未练过的 tag=new/must 优先，排除近 7 天已用话题；
  池枯竭回退 retained 巩固话题并注明文案。
- 自适应：每次生成都重新看近 5 次（窗口自然滑动）；某维连续 3 次 ≥7.0
  则该维隔日出现（降频），否则密集安排。
- LLM 中文建议语暂用本地模板固化在任务文案里（plan 决策中的可选增强，
  保持零额外延迟与零失败面）。

幂等策略：同日重跑删除 pending、保留 done/skipped；
per-user asyncio.Lock 防「报告回调 + 懒加载」并发竞态。
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, distinct, func, select

from app.db.base import async_session_factory
from app.db.models import DailyTask, PracticeSession, Question, ScoreReport, Topic, User
from app.services.progress import stats
from app.services.progress.stats import DIMENSIONS, local_date

logger = logging.getLogger(__name__)

# 每日任务数与建议时长（PRD 默认值）
TASKS_PER_DAY = 3
SUGGESTED_MINUTES = 20

# 单日硬上限：skip 替补超过该数量不再追加
DAY_TASK_HARD_CAP = TASKS_PER_DAY + 2

_user_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _lock_for(user_id: uuid.UUID) -> asyncio.Lock:
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


@dataclass
class TaskDraft:
    """一条任务的生成期形态（落库前）。"""

    task_type: str
    dimension: str | None
    topic_id: uuid.UUID | None
    part: int | None
    title_zh: str
    desc_zh: str
    payload: dict = field(default_factory=dict)


@dataclass
class PlanContext:
    """单用户路径生成的共享输入（一次构建，供多日复用）。"""

    has_placement: bool
    report_count: int
    dim_values: dict[str, list[float]] = field(default_factory=dict)
    avgs: dict[str, float] = field(default_factory=dict)
    ordered_weaknesses: list[tuple[str, float]] = field(default_factory=list)
    stable_dims: set[str] = field(default_factory=set)
    practiced_topic_ids: set[uuid.UUID] = field(default_factory=set)
    p1_topic_ids: set[uuid.UUID] = field(default_factory=set)
    p2_topic_ids: set[uuid.UUID] = field(default_factory=set)
    topics: dict[uuid.UUID, Topic] = field(default_factory=dict)
    used_topic_ids: set[uuid.UUID] = field(default_factory=set)

    @property
    def adaptive(self) -> bool:
        return self.report_count >= stats.PREDICT_WINDOW


# ---------------------------------------------------------------------------
# 上下文构建
# ---------------------------------------------------------------------------

async def load_context(
    db, user_id: uuid.UUID, *, exclude_dates: tuple[date, ...] = ()
) -> PlanContext:
    """加载规则引擎输入。exclude_dates 窗口内已有任务的 topic 计入去重（防同周撞车）。"""
    ctx = PlanContext(has_placement=True, report_count=0)

    user = await db.get(User, user_id)
    ctx.has_placement = bool(user and user.placement_at is not None)

    recent = (
        await db.execute(
            select(ScoreReport, PracticeSession)
            .join(PracticeSession, ScoreReport.session_id == PracticeSession.id)
            .where(ScoreReport.user_id == user_id, ScoreReport.status == "completed")
            .order_by(ScoreReport.created_at.desc())
            .limit(stats.PREDICT_WINDOW)
        )
    ).all()
    ctx.report_count = len(recent)
    for report, _session in recent:
        for dim in DIMENSIONS:
            value = getattr(report, dim)
            if value is not None:
                ctx.dim_values.setdefault(dim, []).append(float(value))

    practiced_rows = await db.scalars(
        select(PracticeSession.topic_id).where(
            PracticeSession.user_id == user_id,
            PracticeSession.status == "completed",
            PracticeSession.topic_id.is_not(None),
        )
    )
    ctx.practiced_topic_ids = {tid for tid in practiced_rows if tid is not None}

    all_topics = (await db.scalars(select(Topic))).all()
    ctx.topics = {t.id: t for t in all_topics}

    # 有 P1 题的话题集合 / 有 Cue Card（P2 题）的话题集合
    ctx.p1_topic_ids = set(
        await db.scalars(select(distinct(Question.topic_id)).where(Question.part == 1))
    )
    ctx.p2_topic_ids = set(
        await db.scalars(select(distinct(Question.topic_id)).where(Question.part == 2))
    )

    # 目标窗口已在任务中使用的话题：防同周/多日推荐重复
    if exclude_dates:
        used_rows = await db.scalars(
            select(DailyTask.topic_id).where(
                DailyTask.user_id == user_id,
                DailyTask.plan_date >= min(exclude_dates) - timedelta(days=6),
                DailyTask.plan_date <= max(exclude_dates),
                DailyTask.topic_id.is_not(None),
            )
        )
        ctx.used_topic_ids = {tid for tid in used_rows if tid is not None}
    return ctx


def finalize_stats(ctx: PlanContext) -> None:
    """上下文构建完成后计算派生统计（均值/弱项排序/稳定维）。"""
    ctx.avgs = stats.dimension_averages(ctx.dim_values)
    ctx.ordered_weaknesses = stats.weakness_order(ctx.avgs)
    ctx.stable_dims = {
        dim for dim, values in ctx.dim_values.items() if stats.is_stable_high(values[:3])
    }


# ---------------------------------------------------------------------------
# 话题挑选与任务构造
# ---------------------------------------------------------------------------

def pick_topic(
    ctx: PlanContext, *, need_p2: bool, prefer_unpracticed_new: bool = True
) -> Topic | None:
    """按优先级挑话题：未练 new/must → 其余未练 → retained 复习兜底。

    挑中的话题立刻记入 used_topic_ids，保证同批多日生成不重复。
    """

    def _take(cands: list[Topic]) -> Topic | None:
        for t in cands:
            if t.id not in ctx.used_topic_ids:
                ctx.used_topic_ids.add(t.id)
                return t
        return None

    pool_ids = ctx.p2_topic_ids if need_p2 else ctx.p1_topic_ids
    available = [
        t
        for tid, t in ctx.topics.items()
        if tid in pool_ids and tid not in ctx.practiced_topic_ids
    ]
    fresh_must = sorted(
        (t for t in available if t.tag == "must"), key=lambda t: t.created_at
    )
    fresh_new = sorted((t for t in available if t.tag == "new"), key=lambda t: t.created_at)
    picked = _take(fresh_must + fresh_new) if prefer_unpracticed_new else None
    if picked:
        return picked

    rest = sorted(available, key=lambda t: t.created_at)
    picked = _take(rest)
    if picked:
        return picked

    # 池枯竭：回退 retained 已练话题做巩固复习
    review = sorted(
        (
            t
            for tid, t in ctx.topics.items()
            if tid in pool_ids and (t.tag or "") == "retained"
        ),
        key=lambda t: t.created_at,
    )
    return _take(review)


def _topic_label(topic: Topic) -> str:
    return topic.name_zh or topic.name_en


def _draft_for_dimension(dim: str, topic: Topic | None) -> TaskDraft | None:
    if topic is None:
        return None
    if dim == "pronunciation":
        return TaskDraft(
            task_type="special",
            dimension=dim,
            topic_id=topic.id,
            part=None,
            title_zh=f"发音跟读：{_topic_label(topic)}",
            desc_zh="进入话题详情页跟读范文两遍，对照高分表达修正发音",
            payload={"action": "topic-detail"},
        )
    if dim == "fluency":
        return TaskDraft(
            task_type="topic",
            dimension=dim,
            topic_id=topic.id,
            part=2,
            title_zh=f"Part 2 独白：{_topic_label(topic)}",
            desc_zh="目标是连贯说完不停顿，少用「嗯啊」类填充词",
            payload={"action": "practice"},
        )
    zh = stats.DIM_ZH[dim]
    return TaskDraft(
        task_type="topic",
        dimension=dim,
        topic_id=topic.id,
        part=1,
        title_zh=f"Part 1 练习：{_topic_label(topic)}",
        desc_zh=f"针对{zh}短板：作答时留意句式多样性与用词升级",
        payload={"action": "practice"},
    )


def _review_draft(topic: Topic) -> TaskDraft:
    return TaskDraft(
        task_type="topic",
        dimension=None,
        topic_id=topic.id,
        part=1,
        title_zh=f"巩固复习：{_topic_label(topic)}",
        desc_zh="之前练过的话题温故知新，尝试用上词汇本里的高分表达",
        payload={"action": "practice"},
    )


def build_day_plan(ctx: PlanContext, day: date) -> list[TaskDraft]:
    """规则核心：产出某天的任务清单（挑选中会消耗 ctx.used_topic_ids 槽位）。"""
    drafts: list[TaskDraft] = []

    if not ctx.report_count:
        return drafts

    if not ctx.adaptive:
        # 新手固定计划：2 条必考话题 P1 + 1 条表达学习
        for _ in range(2):
            topic = pick_topic(ctx, need_p2=False, prefer_unpracticed_new=True)
            if topic is None:
                break
            drafts.append(_draft_for_dimension("lexical", topic))
        expression_topic = next(
            (t for t in sorted(ctx.topics.values(), key=lambda x: x.created_at) if t.tag == "must"),
            None,
        )
        if expression_topic is not None:
            drafts.append(
                TaskDraft(
                    task_type="corpus",
                    dimension=None,
                    topic_id=expression_topic.id,
                    part=None,
                    title_zh=f"高分表达学习：{_topic_label(expression_topic)}",
                    desc_zh="在话题详情页摘抄 3 个高分表达到词汇本并朗读记忆",
                    payload={"action": "topic-detail"},
                )
            )
        # 池不足时放宽补位（不限 P1/P2、含复习），保证每日至少 2 条
        while len(drafts) < 2:
            filler = pick_topic(ctx, need_p2=True, prefer_unpracticed_new=False)
            if filler is None:
                break
            drafts.append(_review_draft(filler))
        return drafts[:TASKS_PER_DAY]

    # 自适应模式：按弱项顺序各产一项；稳定高维隔日出现（降频）
    weak_first = [d for d, _ in ctx.ordered_weaknesses if d not in ctx.stable_dims]
    stable_rest = [d for d, _ in ctx.ordered_weaknesses if d in ctx.stable_dims]
    for dim in weak_first + stable_rest:
        if len(drafts) >= TASKS_PER_DAY:
            break
        if dim in ctx.stable_dims and day.toordinal() % 2 != 0:
            continue  # 连续 3 次 ≥7.0 的维度今天不排（隔日降频）
        need_p2 = dim == "fluency"
        topic = pick_topic(ctx, need_p2=need_p2)
        draft = _draft_for_dimension(dim, topic)
        if draft is not None:
            drafts.append(draft)

    # 名额不足（全稳定或池枯竭）：至少保证 2 条巩固型任务
    while len(drafts) < 2:
        filler = pick_topic(ctx, need_p2=False, prefer_unpracticed_new=False)
        if filler is None:
            break
        drafts.append(_review_draft(filler))
    return drafts[:TASKS_PER_DAY]


def _insert_tasks(db, user_id: uuid.UUID, day: date, drafts: list[TaskDraft]) -> None:
    for sort_idx, draft in enumerate(drafts):
        db.add(
            DailyTask(
                user_id=user_id,
                plan_date=day,
                task_type=draft.task_type,
                dimension=draft.dimension,
                topic_id=draft.topic_id,
                part=draft.part,
                title_zh=draft.title_zh,
                desc_zh=draft.desc_zh,
                payload=draft.payload,
                status="pending",
                sort=sort_idx,
            )
        )


# ---------------------------------------------------------------------------
# 入口 1：报告完成后的重排（评分管线末端触发）
# ---------------------------------------------------------------------------

async def regenerate_future_tasks(user_id: uuid.UUID, *, horizon_days: int = 7) -> int:
    """重排 [今日..今日+N) 的 pending 任务（保留 done/skipped）。返回新建条数。"""
    async with _lock_for(user_id):
        now_utc = datetime.now(timezone.utc)
        today = local_date(now_utc)
        span = [today + timedelta(days=i) for i in range(horizon_days)]

        async with async_session_factory() as db:
            user = await db.get(User, user_id)
            if user is None:
                return 0
            ctx = await load_context(db, user_id, exclude_dates=tuple(span))
            finalize_stats(ctx)

            created = 0
            for day in span:
                # 幂等：删该日 pending（done/skipped 不动）
                await db.execute(
                    delete(DailyTask).where(
                        DailyTask.user_id == user_id,
                        DailyTask.plan_date == day,
                        DailyTask.status == "pending",
                    )
                )
                drafts = build_day_plan(ctx, day)
                _insert_tasks(db, user_id, day, drafts)
                created += len(drafts)
            await db.commit()
            return created


async def on_report_completed(session_id: uuid.UUID) -> None:
    """评分管线最终提交成功后的钩子：
    ① 测评会话（topic 空 + 预选题集）→ 补写 users.placement_at；
    ② 触发未来任务重排。任何异常只记日志，不影响评分主流程。
    """
    try:
        user_id: uuid.UUID | None = None
        async with async_session_factory() as db:
            report = await db.scalar(
                select(ScoreReport).where(ScoreReport.session_id == session_id)
            )
            session = await db.get(PracticeSession, session_id)
            if report is None or session is None or report.status != "completed":
                return
            user_id = session.user_id
            is_placement = session.topic_id is None and bool(session.question_ids)
            if is_placement:
                user = await db.get(User, session.user_id)
                if user is not None and user.placement_at is None:
                    user.placement_at = datetime.now(timezone.utc)
                    await db.commit()
                    logger.info("用户 %s 完成能力测评", user_id)
        if user_id is not None:
            await regenerate_future_tasks(user_id)
    except Exception:
        logger.exception("报告完成后续处理失败：%s", session_id)


# ---------------------------------------------------------------------------
# 入口 2：懒加载补齐（GET /plan/week 发现空缺日时现场生成）
# ---------------------------------------------------------------------------

async def ensure_range(user_id: uuid.UUID, start_day: date, days: int = 7) -> None:
    """确保 [start_day, start_day+days) 中每天至少有一行任务记录（空缺日现场生成）。"""
    span = [start_day + timedelta(days=i) for i in range(days)]
    async with _lock_for(user_id):
        async with async_session_factory() as db:
            user = await db.get(User, user_id)
            if user is None:
                return
            existing_days = set(
                await db.scalars(
                    select(DailyTask.plan_date).where(
                        DailyTask.user_id == user_id,
                        DailyTask.plan_date.in_(span),
                    )
                )
            )
            missing = [d for d in span if d not in existing_days]
            if not missing:
                return
            ctx = await load_context(db, user_id, exclude_dates=tuple(span))
            finalize_stats(ctx)
            for day in missing:
                drafts = build_day_plan(ctx, day)
                _insert_tasks(db, user_id, day, drafts)
            await db.commit()


# ---------------------------------------------------------------------------
# 入口 3：跳过任务后的同型替补
# ---------------------------------------------------------------------------

async def replace_skipped_task(user_id: uuid.UUID, skipped: DailyTask) -> DailyTask | None:
    """被跳过的任务不计完成：立即生成一条同型替补占住名额。

    当日总行数已达硬上限时不追加；候选枯竭返回 None。
    """
    async with _lock_for(user_id):
        async with async_session_factory() as db:
            total = await db.scalar(
                select(func.count())
                .select_from(DailyTask)
                .where(DailyTask.user_id == user_id, DailyTask.plan_date == skipped.plan_date)
            )
            if (total or 0) >= DAY_TASK_HARD_CAP:
                return None

            ctx = await load_context(db, user_id, exclude_dates=(skipped.plan_date,))
            finalize_stats(ctx)
            need_p2 = (skipped.dimension == "fluency") or (
                skipped.task_type == "topic" and skipped.part == 2
            )
            draft: TaskDraft | None = None
            if skipped.dimension and skipped.dimension in DIMENSIONS:
                draft = _draft_for_dimension(skipped.dimension, pick_topic(ctx, need_p2=need_p2))
            elif skipped.task_type == "special":
                draft = _draft_for_dimension("pronunciation", pick_topic(ctx, need_p2=False))
            if draft is None:
                fallback_topic = pick_topic(ctx, need_p2=False, prefer_unpracticed_new=False)
                draft = _review_draft(fallback_topic) if fallback_topic else None
            if draft is None:
                return None

            max_sort = await db.scalar(
                select(func.max(DailyTask.sort)).where(
                    DailyTask.user_id == user_id, DailyTask.plan_date == skipped.plan_date
                )
            )
            task = DailyTask(
                user_id=user_id,
                plan_date=skipped.plan_date,
                task_type=draft.task_type,
                dimension=draft.dimension,
                topic_id=draft.topic_id,
                part=draft.part,
                title_zh=f"[替补] {draft.title_zh}",
                desc_zh=draft.desc_zh,
                payload=draft.payload,
                status="pending",
                sort=(max_sort or 0) + 1,
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            return task
