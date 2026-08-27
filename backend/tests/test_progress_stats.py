"""统计口径纯函数单测：streak / predicted_band / 时区边界 / 降频规则。"""

from datetime import date, datetime, timedelta, timezone

from app.services.progress import stats

SH = stats.LOCAL_TZ


# ---------------------------------------------------------------------------
# local_date：北京时区归属
# ---------------------------------------------------------------------------

def test_local_date_utc_late_evening_belongs_to_next_beijing_day():
    # UTC 周一 23:30 = 北京周二 07:30，打卡应归属周二
    utc_dt = datetime(2026, 8, 3, 23, 30, tzinfo=timezone.utc)
    assert stats.local_date(utc_dt) == date(2026, 8, 4)


def test_local_date_naive_treated_as_utc():
    naive = datetime(2026, 8, 3, 16, 0)  # 北京 8-04 00:00 整
    assert stats.local_date(naive) == date(2026, 8, 4)


# ---------------------------------------------------------------------------
# streak_days
# ---------------------------------------------------------------------------

def test_streak_counts_backwards_from_today():
    today = date(2026, 8, 27)
    practiced = {today - timedelta(days=i) for i in range(5)}
    assert stats.streak_days(practiced, today) == 5


def test_streak_today_missing_does_not_break():
    # 今天还没练不打断 streak（从昨天起算）
    today = date(2026, 8, 27)
    practiced = {today - timedelta(days=i) for i in range(1, 4)}  # 昨天+前天+大前天
    assert stats.streak_days(practiced, today) == 3


def test_streak_broken_yesterday_is_zero():
    today = date(2026, 8, 27)
    practiced = {today - timedelta(days=2), today - timedelta(days=3)}
    assert stats.streak_days(practiced, today) == 0


def test_streak_empty():
    assert stats.streak_days(set(), date(2026, 8, 27)) == 0


# ---------------------------------------------------------------------------
# predicted_band
# ---------------------------------------------------------------------------

def test_predicted_band_weighted_average():
    # 近 5 次按新→旧 [7.0, 6.0, 6.5, 5.5, 5.0]，权重 [5,4,3,2,1]/15
    # (35 + 24 + 19.5 + 11 + 5) / 15 = 6.3
    band, hint = stats.predicted_band([7.0, 6.0, 6.5, 5.5, 5.0])
    assert band == 6.3
    assert hint == ""


def test_predicted_band_insufficient_samples():
    band, hint = stats.predicted_band([6.0, 6.5])
    assert band is None
    assert "2 次" in hint


def test_predicted_band_empty():
    band, hint = stats.predicted_band([])
    assert band is None
    assert "第一次" in hint


# ---------------------------------------------------------------------------
# 弱项排序与降频
# ---------------------------------------------------------------------------

def test_weakness_order_ascending():
    avgs = {"fluency": 6.0, "lexical": 5.5, "grammar": 7.0, "pronunciation": 6.5}
    ordered = stats.weakness_order(avgs)
    assert ordered[0] == ("lexical", 5.5)
    assert ordered[-1] == ("grammar", 7.0)


def test_is_stable_high_requires_three_consecutive():
    assert stats.is_stable_high([7.0, 7.5, 8.0]) is True
    assert stats.is_stable_high([7.0, 6.5, 8.0]) is False  # 中间低于阈值
    assert stats.is_stable_high([7.0, 7.5]) is False       # 样本不足
    assert stats.is_stable_high([5.0, 5.0, 5.0]) is False


def test_dimension_averages_skips_missing_dims():
    result = stats.dimension_averages({"fluency": [], "lexical": [5.0, 6.0]})
    assert result == {"lexical": 5.5}


# ---------------------------------------------------------------------------
# week_delta / eta / weekly_gain
# ---------------------------------------------------------------------------

def test_week_delta_hides_when_either_week_missing():
    assert stats.week_delta(None, 6.0) is None
    assert stats.week_delta(6.5, None) is None
    assert stats.week_delta(6.5, 6.0) == 0.5


def test_eta_text_no_overpromise_when_gain_too_low():
    text = stats.eta_text(target_band=7.0, predicted=5.5, weekly_gain=0.04)
    assert text == "保持当前练习频率稳步提升"
    assert stats.eta_text(7.0, 5.5, 0.05).startswith("以当前进度约")
    assert stats.eta_text(6.5, 6.5, 0.1) == "已达目标分数，继续保持！"
    assert stats.eta_text(None, 5.5, 0.1) is None


def test_weekly_gain_over_four_weeks():
    now = datetime.now(timezone.utc)
    points = [
        (now - timedelta(days=28), 5.0),
        (now - timedelta(days=14), 5.5),
        (now - timedelta(days=1), 6.0),
    ]
    assert stats.weekly_gain_from_history(points, now) == 0.25  # (6.0-5.0)/4


def test_weekly_gain_needs_two_points_in_window():
    now = datetime.now(timezone.utc)
    points = [(now - timedelta(days=40), 5.0), (now - timedelta(days=1), 6.0)]
    assert stats.weekly_gain_from_history(points, now) is None


# ---------------------------------------------------------------------------
# avg_session_minutes
# ---------------------------------------------------------------------------

def test_avg_session_minutes_rounding():
    assert stats.avg_session_minutes([300, 600]) == 7.5   # 900s / 2 = 7.5min
    assert stats.avg_session_minutes([]) is None
