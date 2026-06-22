from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from app.strategies.trend_portfolio import (
    FundamentalSnapshot,
    TrendSnapshot,
    screen_symbol,
)
from quant.data.resample import resample_ohlcv
from quant.indicators.macd import macd
from quant.indicators.trend import sma


def _last(seq, default=0.0):
    return float(seq[-1]) if len(seq) else default


def build_trend_snapshot(
    daily: pd.DataFrame,
    fundamentals: FundamentalSnapshot,
) -> TrendSnapshot:
    weekly = resample_ohlcv(daily, "W")
    monthly = resample_ohlcv(daily, "ME")

    m_close = monthly["close"].tolist()
    w_close = weekly["close"].tolist()
    w_high = weekly["high"].tolist()
    w_low = weekly["low"].tolist()

    m_macd = macd(m_close)
    price = _last(daily["close"].tolist())

    def safe_sma(values, period):
        return sma(values, period) or 0.0

    # 周线高低点抬高:用最近两段窗口的极值比较
    def rising(values):
        if len(values) < 8:
            return False
        recent = values[-4:]
        prior = values[-8:-4]
        return max(recent) > max(prior) and min(recent) > min(prior)

    return TrendSnapshot(
        price=price,
        ma20_month=safe_sma(m_close, 20),
        ma60_month=safe_sma(m_close, 60),
        macd_month_dif=m_macd[-1].dif if m_macd else 0.0,
        macd_month_dea=m_macd[-1].dea if m_macd else 0.0,
        ma5_week=safe_sma(w_close, 5),
        ma10_week=safe_sma(w_close, 10),
        ma20_week=safe_sma(w_close, 20),
        weekly_highs_rising=rising(w_high),
        weekly_lows_rising=rising(w_low),
        max_drawdown_3m_pct=_recent_drawdown_pct(daily, days=63),
        short_term_gain_pct=_recent_gain_pct(daily, days=20),
    )


def _recent_drawdown_pct(daily: pd.DataFrame, days: int) -> float:
    closes = daily["close"].tolist()[-days:]
    if not closes:
        return 0.0
    peak = closes[0]
    dd = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            dd = max(dd, (peak - c) / peak * 100)
    return round(dd, 4)


def _recent_gain_pct(daily: pd.DataFrame, days: int) -> float:
    closes = daily["close"].tolist()[-days:]
    if len(closes) < 2 or closes[0] == 0:
        return 0.0
    return round((closes[-1] - closes[0]) / closes[0] * 100, 4)


@dataclass(frozen=True)
class PortfolioHit:
    symbol: str
    market: str
    passed: bool
    score: float
    reasons: tuple[str, ...]


def screen_portfolio(
    rows: Sequence[tuple[str, str, pd.DataFrame, FundamentalSnapshot]],
) -> list[PortfolioHit]:
    hits: list[PortfolioHit] = []
    for symbol, market, daily, fundamentals in rows:
        snap = build_trend_snapshot(daily, fundamentals)
        result = screen_symbol(market, snap, fundamentals)
        hits.append(
            PortfolioHit(
                symbol=symbol,
                market=market,
                passed=result.passed,
                score=result.score,
                reasons=result.reasons,
            )
        )
    return hits
