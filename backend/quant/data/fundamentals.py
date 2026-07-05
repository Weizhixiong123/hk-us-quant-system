from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from app.strategies.trend_portfolio import FundamentalSnapshot


@dataclass(frozen=True)
class RawFundamentals:
    market_cap: float
    positive_profit_quarters: int


FundamentalsSource = Callable[[str, str], "RawFundamentals | None"]


def _normalize(symbol: str) -> str:
    return symbol.strip().upper()


def load_fundamentals(
    symbol: str,
    market: str,
    source: FundamentalsSource,
    risk_blocklist: Iterable[str] = (),
    cache: dict[str, FundamentalSnapshot] | None = None,
) -> FundamentalSnapshot:
    key = _normalize(symbol)
    if cache is not None and key in cache:
        return cache[key]

    has_major_risk = key in {_normalize(item) for item in risk_blocklist}
    try:
        raw = source(symbol, market)
    except Exception:
        raw = None

    if raw is None:
        snapshot = FundamentalSnapshot(
            positive_profit_quarters=0,
            market_cap=0.0,
            has_major_risk=has_major_risk,
        )
    else:
        snapshot = FundamentalSnapshot(
            positive_profit_quarters=int(raw.positive_profit_quarters),
            market_cap=float(raw.market_cap),
            has_major_risk=has_major_risk,
        )

    if cache is not None:
        cache[key] = snapshot
    return snapshot


def default_fundamentals_source(symbol: str, market: str) -> RawFundamentals | None:
    if market in {"US", "HK"}:
        return _yfinance_fundamentals(symbol)
    return None


def _yfinance_fundamentals(symbol: str) -> RawFundamentals | None:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info = getattr(ticker, "info", None) or {}
    market_cap = float(info.get("marketCap") or 0.0)
    if market_cap <= 0:
        return None
    positive = 0
    income = getattr(ticker, "quarterly_income_stmt", None)
    if income is not None and "Net Income" in getattr(income, "index", []):
        for value in list(income.loc["Net Income"])[:2]:
            if value is not None and float(value) > 0:
                positive += 1
    return RawFundamentals(market_cap=market_cap, positive_profit_quarters=positive)
