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


def _futu_code_for(normalized: str, market: str) -> str:
    """富途需要 HK.xxxxx (5 位零填充) / US.xxxx 格式。

    normalized 是后端归一化后的字符串:
    - HK: "7747.HK" / "02899.HK" → 富途需要 HK.07747 / HK.02899(5 位零填充)
    - US: "AAPL" / "BRK.B" → 富途需要 US.AAPL / US.BRK.B
    """
    if market == "US":
        return f"US.{normalized}"
    # HK: 从 normalized "xxxx.HK" 取出数字部分,padStart 到 5 位
    code = normalized.replace(".HK", "")
    if code.isdigit():
        code = code.zfill(5)
    return f"HK.{code}"


@lru_cache(maxsize=1024)
def _futu_lookup(symbol: str, market: str) -> str | None:
    """通过富途 OpenD (futu-api) 查询股票名, 失败时返回 None 回退 yfinance。"""
    try:
        from futu import OpenQuoteContext

        ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
        try:
            ret, data = ctx.get_market_snapshot([_futu_code_for(symbol, market)])
            if ret == 0 and not data.empty:
                name: str = data.iloc[0].get("name", "")
                # 富途返回的 name 在 utf-8 终端下是正常中文;
                # 若遇到含乱码或全为英文(富途非中文环境)也可接受
                return name.strip() or None
            return None
        finally:
            ctx.close()
    except Exception:
        return None


@lru_cache(maxsize=1024)
def _yf_lookup(normalized: str) -> str | None:
    """yfinance 兜底命名查询。"""
    import yfinance as yf

    try:
        quotes = yf.Search(
            normalized, max_results=5, news_count=0, timeout=8, raise_errors=True
        ).quotes
        return _name_from_quotes(normalized, quotes)
    except Exception:
        return None


@lru_cache(maxsize=1024)
def lookup_symbol_name(symbol: str, market: str) -> tuple[str, str | None]:
    normalized = normalize_symbol(symbol, market)

    # 1) 优先富途查询 (OpenD 需要在本地运行)
    name = _futu_lookup(symbol, market)
    if name:
        return normalized, name

    # 2) 兜底 yfinance
    name = _yf_lookup(normalized)
    return normalized, name
