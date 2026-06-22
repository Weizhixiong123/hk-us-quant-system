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


@dataclass(frozen=True)
class ScreenHit:
    symbol: str
    market: str
    passed: bool
    reasons: tuple[str, ...]


def screen_intraday(
    candidates: Sequence[IntradayCandidate],
    min_turnover: float = 5_000_000.0,
) -> list[ScreenHit]:
    results: list[ScreenHit] = []
    for c in candidates:
        checks = {
            f"日均成交额≥{min_turnover:.0f}": c.avg_turnover >= min_turnover,
            "振幅∈[2%,8%]": 2.0 <= c.prev_amplitude_pct <= 8.0,
            "股价≥2": c.price >= 2.0,
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
