from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from quant.live.clock import (
    HK_TZ,
    US_TZ,
    is_force_close_window,
    is_intraday_entry_window,
    is_market_open,
    is_month_end_rebalance_day,
    market_time,
)


def test_hk_entry_window_respects_open_delay_lunch_and_late_cutoff():
    assert is_intraday_entry_window(datetime(2026, 6, 23, 10, 0, tzinfo=HK_TZ), "HK")
    assert not is_intraday_entry_window(datetime(2026, 6, 23, 9, 59, tzinfo=HK_TZ), "HK")
    assert not is_intraday_entry_window(datetime(2026, 6, 23, 12, 30, tzinfo=HK_TZ), "HK")
    assert not is_intraday_entry_window(datetime(2026, 6, 23, 14, 30, tzinfo=HK_TZ), "HK")


def test_us_market_time_uses_new_york_daylight_saving_time():
    shanghai = datetime(2026, 6, 23, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert market_time(shanghai, "US") == datetime(2026, 6, 23, 10, 0, tzinfo=US_TZ)
    assert is_market_open(shanghai, "US")
    assert is_intraday_entry_window(shanghai, "US")


def test_force_close_window_is_final_ten_minutes():
    assert is_force_close_window(datetime(2026, 6, 23, 15, 50, tzinfo=HK_TZ), "HK")
    assert is_force_close_window(datetime(2026, 6, 23, 15, 59, tzinfo=HK_TZ), "HK")
    assert not is_force_close_window(datetime(2026, 6, 23, 16, 0, tzinfo=HK_TZ), "HK")


def test_month_end_rebalance_day_skips_weekend_and_injected_holiday():
    assert is_month_end_rebalance_day(date(2026, 6, 30), "US")
    assert is_month_end_rebalance_day(date(2026, 2, 27), "US")
    assert not is_month_end_rebalance_day(date(2026, 6, 29), "US")

    holidays = {"US": {date(2026, 6, 30)}, "HK": set()}
    assert is_month_end_rebalance_day(date(2026, 6, 29), "US", holidays)
