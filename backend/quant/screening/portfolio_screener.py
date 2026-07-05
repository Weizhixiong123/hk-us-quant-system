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
from quant.indicators.macd import has_top_divergence, macd
from quant.indicators.trend import max_drawdown_pct, sma


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
    w_macd = macd(w_close)
    price = _last(daily["close"].tolist())

    def safe_sma(values, period):
        # 数据不足时返回 inf：使 "price > ma" 为 False，"ma5>ma10>ma20" 链式比较为 False，
        # 保守判不通过——无法确认条件成立时宁可拦截。
        result = sma(values, period)
        return result if result is not None else float("inf")

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
        max_drawdown_3m_pct=max_drawdown_pct(daily["close"].tolist()[-63:]),
        short_term_gain_pct=_recent_gain_pct(daily, days=20),
        weekly_macd_hist_positive=_macd_hist_positive(w_macd),
        weekly_macd_hist_healthy=_macd_hist_healthy(w_macd),
        weekly_macd_top_divergence=_top_divergence(w_high, w_macd),
        monthly_macd_top_divergence=_top_divergence(monthly["high"].tolist(), m_macd),
    )


def _macd_hist_positive(points) -> bool:
    return bool(points and (points[-1].hist > 0 or (points[-1].dif > 0 and points[-1].dea > 0)))


def _macd_hist_healthy(points, bars: int = 3, shrink_tolerance: float = 0.35) -> bool:
    if len(points) < bars:
        return False
    hist = [float(point.hist) for point in points[-bars:]]
    if points[-1].dif > 0 and points[-1].dea > 0:
        return True
    if any(value <= 0 for value in hist):
        return False
    # 红柱允许温和回落，但最后一根不能比窗口最高值萎缩太多。
    return hist[-1] >= max(hist) * 0.2


def _top_divergence(highs: list[float], points) -> bool:
    if len(highs) < 8 or len(points) < 8:
        return False
    hist = [float(point.hist) for point in points]
    return has_top_divergence(highs, hist, lookback=min(28, len(highs)))


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
