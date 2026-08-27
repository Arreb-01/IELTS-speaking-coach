"""学习进度统计：口径内聚的纯函数集合（Part E）。

全部为无 IO 的纯函数，方便单测覆盖时区边界与小样本场景。
统一日期口径：Asia/Shanghai 本地日期（local_date），打卡判定以此为唯一标准。
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Shanghai")

# 预测 Band：近 5 次综合评分加权（最新权重最高）
PREDICT_WINDOW = 5
_PREDICT_WEIGHTS = (5, 4, 3, 2, 1)

# 自适应降频：同一维度连续 3 次 >= 7.0 视为已稳定，降低该维任务频率
STABLE_HIGH_THRESHOLD = 7.0
STABLE_HIGH_STREAK = 3

DIMENSIONS = ("fluency", "lexical", "grammar", "pronunciation")
DIM_ZH = {
    "fluency": "流利度",
    "lexical": "词汇多样性",
    "grammar": "语法准确性",
    "pronunciation": "发音",
}


def local_date(dt: datetime) -> date:
    """UTC aware datetime → 北京时区日期（打卡归属的唯一入口）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ).date()


def streak_days(practiced_dates: set[date], today: date) -> int:
    """连续打卡天数。

    口径：从今天往回数连续"有 completed 会话"的天数；
    今天还没练不打断 streak（从昨天起算），昨天断了才断。
    """
    start = today if today in practiced_dates else today - timedelta(days=1)
    count = 0
    cursor = start
    while cursor in practiced_dates:
        count += 1
        cursor -= timedelta(days=1)
    return count


def predicted_band(recent_overalls_desc: list[float]) -> tuple[float | None, str]:
    """预测 Band：近 5 次加权平均。返回 (band, 提示语)。

    recent_overalls_desc 按时间新→旧排列；不足 5 次返回 None + 数据不足提示。
    """
    n = len(recent_overalls_desc)
    if n == 0:
        return None, "完成第一次练习并出分后开始预测"
    if n < PREDICT_WINDOW:
        return None, f"已有 {n} 次评分，累计满 {PREDICT_WINDOW} 次后开始预测"
    window = recent_overalls_desc[:PREDICT_WINDOW]
    total_weight = sum(_PREDICT_WEIGHTS)
    value = sum(w * v for w, v in zip(_PREDICT_WEIGHTS, window)) / total_weight
    return round(value, 1), ""


def week_delta(this_week_last: float | None, last_week_last: float | None) -> float | None:
    """较上周变化：本周最后一份报告 - 上周最后一份报告；任一周缺失则隐藏。"""
    if this_week_last is None or last_week_last is None:
        return None
    return round(this_week_last - last_week_last, 1)


def avg_session_minutes(durations_seconds: list[float]) -> float | None:
    """单次练习平均分钟数（近 7 天会话时长均值，保留 1 位小数）。"""
    if not durations_seconds:
        return None
    return round(sum(durations_seconds) / len(durations_seconds) / 60, 1)


def dimension_averages(dim_series: dict[str, list[float]]) -> dict[str, float]:
    """各维度取均值（只统计有值的维度），用于雷达与弱项判定。"""
    avgs: dict[str, float] = {}
    for dim, values in dim_series.items():
        if values:
            avgs[dim] = round(sum(values) / len(values), 1)
    return avgs


def weakness_order(avgs: dict[str, float]) -> list[tuple[str, float]]:
    """按均值升序返回 [(维度, 均值)]——最弱在前。无数据返回空。"""
    return sorted(avgs.items(), key=lambda kv: kv[1])


def is_stable_high(last3_values: list[float]) -> bool:
    """连续 3 次同维 >= 7.0 → 该维进入"稳定高水平"，任务间隔排。"""
    if len(last3_values) < STABLE_HIGH_STREAK:
        return False
    return all(v >= STABLE_HIGH_THRESHOLD for v in last3_values[:STABLE_HIGH_STREAK])


def eta_text(
    target_band: float | None,
    predicted: float | None,
    weekly_gain: float | None,
) -> str | None:
    """预计达成时间文案。拒绝拍脑袋承诺：提升速度样本不足或过低时用兜底文案。

    weekly_gain：近 28 天周均提升（负值视为原地踏步）；None 表示样本不足。
    """
    if target_band is None or predicted is None:
        return None
    gap = round(target_band - predicted, 1)
    if gap <= 0:
        return "已达目标分数，继续保持！"
    if weekly_gain is not None and weekly_gain >= 0.05:
        weeks = max(1, round(gap / weekly_gain))
        return f"以当前进度约 {weeks} 周达成目标"
    return "保持当前练习频率稳步提升"


def weekly_gain_from_history(points_asc: list[tuple], now: datetime) -> float | None:
    """近 28 天周均提升：(窗口末值 - 窗口首值) / 4 周。

    points_asc 按 [(时间, overall_band)] 时间升序；时间项可为 date 或
    datetime（naive 按 UTC）；窗口内 <2 个点返回 None。
    """

    def _as_aware(value) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)

    cutoff = now - timedelta(days=28)
    normalized = [(_as_aware(dt), v) for dt, v in points_asc]
    window = [(dt, v) for dt, v in normalized if dt >= cutoff]
    if len(window) < 2:
        return None
    gain = window[-1][1] - window[0][1]
    return round(gain / 4, 2)
