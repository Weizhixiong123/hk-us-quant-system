from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class IntradayCandidate:
    symbol: str
    market: str
    avg_turnover: float
    prev_amplitude_pct: float
    price: float
    halted: bool
    ex_dividend_soon: bool
    major_news: bool
    turnover_rate: float = 0.0  # %, 保留供数据源展示
    market_cap: float = 0.0  # 用于换手率计算


@dataclass(frozen=True)
class ScreenHit:
    symbol: str
    market: str
    passed: bool
    reasons: tuple[str, ...]


def screen_intraday(
    candidates: Sequence[IntradayCandidate],
    min_turnover: float = 5_000_000.0,
    min_amplitude_pct: float = 2.0,
    max_amplitude_pct: float = 8.0,
    min_price: float = 2.0,
    min_turnover_rate: float = 0.0,
) -> list[ScreenHit]:
    results: list[ScreenHit] = []
    for c in candidates:
        # 换手率 = 日均成交额 / 总市值 * 100 (%)，总市值为 0 时跳过此检查
        rate = c.turnover_rate
        if rate <= 0 and c.market_cap > 0:
            rate = c.avg_turnover / c.market_cap * 100
        checks = {
            f"日均成交额≥{min_turnover:.0f}": c.avg_turnover >= min_turnover,
            f"振幅∈[{min_amplitude_pct:.1f}%,{max_amplitude_pct:.1f}%]": min_amplitude_pct <= c.prev_amplitude_pct <= max_amplitude_pct,
            f"股价≥{min_price}": c.price >= min_price,
            f"换手率≥{min_turnover_rate:.1f}%": rate >= min_turnover_rate,
            "未停牌": not c.halted,
            "非即将除权除息": not c.ex_dividend_soon,
            "无重大公告": not c.major_news,
        }
        reasons = tuple(
            f"{label}{'通过' if ok else '未满足'}" for label, ok in checks.items()
        )
        results.append(
            ScreenHit(
                symbol=c.symbol,
                market=c.market,
                passed=all(checks.values()),
                reasons=reasons,
            )
        )
    return results
