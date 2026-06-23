from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Literal, Mapping
from zoneinfo import ZoneInfo


Market = Literal["HK", "US"]

HK_TZ = ZoneInfo("Asia/Hong_Kong")
US_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class MarketSession:
    market: Market
    timezone: ZoneInfo
    open_time: time
    close_time: time
    breaks: tuple[tuple[time, time], ...] = ()


HolidayCalendar = Mapping[Market, Iterable[date]]


SESSIONS: dict[Market, MarketSession] = {
    "HK": MarketSession(
        market="HK",
        timezone=HK_TZ,
        open_time=time(9, 30),
        close_time=time(16, 0),
        breaks=((time(12, 0), time(13, 0)),),
    ),
    "US": MarketSession(
        market="US",
        timezone=US_TZ,
        open_time=time(9, 30),
        close_time=time(16, 0),
    ),
}


def market_time(at: datetime, market: Market) -> datetime:
    session = SESSIONS[market]
    if at.tzinfo is None:
        return at.replace(tzinfo=session.timezone)
    return at.astimezone(session.timezone)


def is_trading_day(
    day: date,
    market: Market,
    holidays: HolidayCalendar | None = None,
) -> bool:
    if day.weekday() >= 5:
        return False
    if holidays is None:
        return True
    return day not in set(holidays.get(market, ()))


def is_market_open(
    at: datetime,
    market: Market,
    holidays: HolidayCalendar | None = None,
) -> bool:
    local = market_time(at, market)
    session = SESSIONS[market]
    local_time = local.time()
    if not is_trading_day(local.date(), market, holidays):
        return False
    if local_time < session.open_time or local_time >= session.close_time:
        return False
    return not _in_break(local_time, session)


def is_intraday_entry_window(
    at: datetime,
    market: Market,
    holidays: HolidayCalendar | None = None,
) -> bool:
    local = market_time(at, market)
    session = SESSIONS[market]
    window_start = _combine(local.date(), session.open_time, session.timezone) + timedelta(minutes=30)
    window_end = _combine(local.date(), session.close_time, session.timezone) - timedelta(minutes=90)
    return window_start <= local < window_end and is_market_open(local, market, holidays)


def is_force_close_window(
    at: datetime,
    market: Market,
    holidays: HolidayCalendar | None = None,
) -> bool:
    local = market_time(at, market)
    session = SESSIONS[market]
    window_start = _combine(local.date(), session.close_time, session.timezone) - timedelta(minutes=10)
    window_end = _combine(local.date(), session.close_time, session.timezone)
    return window_start <= local < window_end and is_trading_day(local.date(), market, holidays)


def is_month_end_rebalance_day(
    day: date,
    market: Market,
    holidays: HolidayCalendar | None = None,
) -> bool:
    if not is_trading_day(day, market, holidays):
        return False
    next_day = day + timedelta(days=1)
    while next_day.month == day.month:
        if is_trading_day(next_day, market, holidays):
            return False
        next_day += timedelta(days=1)
    return True


def is_bar_close(at: datetime, interval_minutes: int, market: Market) -> bool:
    local = market_time(at, market)
    minutes = local.hour * 60 + local.minute
    return local.second == 0 and local.microsecond == 0 and minutes % interval_minutes == 0


def premarket_scan_time(day: date, market: Market) -> datetime:
    session = SESSIONS[market]
    return _combine(day, session.open_time, session.timezone) - timedelta(minutes=30)


def close_review_time(day: date, market: Market) -> datetime:
    session = SESSIONS[market]
    return _combine(day, session.close_time, session.timezone) + timedelta(minutes=5)


def force_close_time(day: date, market: Market) -> datetime:
    session = SESSIONS[market]
    return _combine(day, session.close_time, session.timezone) - timedelta(minutes=10)


def _in_break(value: time, session: MarketSession) -> bool:
    return any(start <= value < end for start, end in session.breaks)


def _combine(day: date, value: time, timezone: ZoneInfo) -> datetime:
    return datetime.combine(day, value, tzinfo=timezone)
