from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FundamentalSnapshot:
    positive_profit_quarters: int
    market_cap: float
    has_major_risk: bool


@dataclass(frozen=True)
class TrendSnapshot:
    price: float
    ma20_month: float
    ma60_month: float
    macd_month_dif: float
    macd_month_dea: float
    ma5_week: float
    ma10_week: float
    ma20_week: float
    weekly_highs_rising: bool
    weekly_lows_rising: bool
    max_drawdown_3m_pct: float
    short_term_gain_pct: float


@dataclass(frozen=True)
class PortfolioScreenResult:
    passed: bool
    score: float
    reasons: tuple[str, ...]


def screen_symbol(
    market: str,
    trend: TrendSnapshot,
    fundamentals: FundamentalSnapshot,
) -> PortfolioScreenResult:
    min_cap = 5_000_000_000 if market == "HK" else 2_000_000_000
    checks = {
        "月线站上 20/60 月线": trend.price > trend.ma20_month and trend.price > trend.ma60_month,
        "月线 MACD 零轴上方": trend.macd_month_dif > 0 and trend.macd_month_dea > 0,
        "周线均线多头排列": trend.ma5_week > trend.ma10_week > trend.ma20_week,
        "周线高低点抬高": trend.weekly_highs_rising and trend.weekly_lows_rising,
        "近 2 季盈利": fundamentals.positive_profit_quarters >= 2,
        "无重大基本面风险": not fundamentals.has_major_risk,
        "流通市值达标": fundamentals.market_cap >= min_cap,
        "近 3 月最大回撤可控": trend.max_drawdown_3m_pct <= 15,
        "短期涨幅未过热": trend.short_term_gain_pct <= 40,
    }
    passed_count = sum(1 for ok in checks.values() if ok)
    score = round(passed_count / len(checks), 3)
    reasons = tuple(
        f"{label}{'通过' if ok else '未满足'}" for label, ok in checks.items()
    )
    return PortfolioScreenResult(
        passed=passed_count == len(checks),
        score=score,
        reasons=reasons,
    )

