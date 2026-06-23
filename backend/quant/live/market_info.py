from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class SymbolMarketInfo:
    halted: bool
    ex_dividend_soon: bool


MarketInfoSource = Callable[[str], "SymbolMarketInfo | None"]


def _normalize(symbol: str) -> str:
    return symbol.strip().upper()


class MarketInfoProvider:
    def __init__(
        self,
        source: MarketInfoSource | None = None,
        news_blocklist: Iterable[str] = (),
    ) -> None:
        self.source = source
        self.news_blocklist = {_normalize(item) for item in news_blocklist}

    def lookup(self, symbol: str) -> tuple[bool, bool, bool]:
        """returns (halted, ex_dividend_soon, major_news)."""
        major_news = _normalize(symbol) in self.news_blocklist
        if self.source is None:
            return (False, False, major_news)
        try:
            info = self.source(symbol)
        except Exception:
            info = None
        if info is None:
            return (True, False, major_news)
        return (info.halted, info.ex_dividend_soon, major_news)
