from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable


def normalize_symbol(symbol: str, market: str) -> str:
    value = symbol.strip().upper().replace(" ", "")
    if market == "US":
        return value.removesuffix(".US")
    if market == "HK":
        value = value.removeprefix("HK.").removesuffix(".HK")
        if value.isdigit():
            value = (value.lstrip("0") or "0").zfill(4)
        return f"{value}.HK"
    raise ValueError(f"unknown market: {market}")


def _name_from_quotes(symbol: str, quotes: Iterable[dict[str, Any]]) -> str | None:
    match_key = symbol.replace(".", "-").replace("_", "-")
    for quote in quotes:
        quote_symbol = str(quote.get("symbol", "")).upper()
        quote_key = quote_symbol.replace(".", "-").replace("_", "-")
        if quote_key != match_key:
            continue
        name = str(quote.get("longname") or quote.get("shortname") or "").strip()
        return name or None
    return None


@lru_cache(maxsize=1024)
def lookup_symbol_name(symbol: str, market: str) -> tuple[str, str | None]:
    normalized = normalize_symbol(symbol, market)

    import yfinance as yf

    quotes = yf.Search(
        normalized,
        max_results=5,
        news_count=0,
        timeout=8,
        raise_errors=True,
    ).quotes
    return normalized, _name_from_quotes(normalized, quotes)
