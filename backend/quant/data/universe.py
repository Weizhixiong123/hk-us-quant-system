from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Market = Literal["HK", "US"]


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    name: str
    market: Market
    shortable: bool = False


_UNIVERSE: dict[str, list[SymbolInfo]] = {
    "US": [
        SymbolInfo("AAPL", "Apple", "US", shortable=True),
        SymbolInfo("MSFT", "Microsoft", "US", shortable=True),
        SymbolInfo("NVDA", "NVIDIA", "US"),
    ],
    "HK": [
        SymbolInfo("0700.HK", "腾讯控股", "HK", shortable=True),
        SymbolInfo("9988.HK", "阿里巴巴-W", "HK"),
        SymbolInfo("3690.HK", "美团-W", "HK"),
    ],
}


def get_universe(market: str) -> list[SymbolInfo]:
    if market not in _UNIVERSE:
        raise ValueError(f"unknown market: {market}")
    return list(_UNIVERSE[market])


def all_symbols() -> list[SymbolInfo]:
    return [item for items in _UNIVERSE.values() for item in items]
