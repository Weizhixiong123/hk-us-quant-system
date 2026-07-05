from __future__ import annotations

import math
from datetime import date
from typing import Iterable

from quant.data.universe import SymbolInfo
from quant.screening.intraday_screener import IntradayCandidate


class FutuMarketScanner:
    """富途全市场普通股列表与批量快照读取器。"""

    def __init__(self, host: str, port: int, markets: Iterable[str]) -> None:
        self.host = host
        self.port = port
        self.markets = tuple(str(item).upper() for item in markets)
        self._universe_cache: dict[str, tuple[date, list[SymbolInfo]]] = {}

    def symbols(self, market: str) -> list[SymbolInfo]:
        market = market.upper()
        cached = self._universe_cache.get(market)
        if cached and cached[0] == date.today():
            return list(cached[1])

        from futu import Market, OpenQuoteContext, RET_OK, SecurityType

        quote_ctx = OpenQuoteContext(host=self.host, port=self.port)
        try:
            ret, data = quote_ctx.get_stock_basicinfo(
                market=getattr(Market, market),
                stock_type=SecurityType.STOCK,
            )
            if ret != RET_OK:
                raise RuntimeError(f"富途证券列表读取失败: {data}")
            symbols = _symbol_infos(data.to_dict("records"), market)
        finally:
            quote_ctx.close()

        self._universe_cache[market] = (date.today(), symbols)
        return list(symbols)

    def all_symbols(self) -> list[SymbolInfo]:
        return [item for market in self.markets for item in self.symbols(market)]

    def intraday_candidates(self, market: str | None = None) -> list[IntradayCandidate]:
        symbols = self.symbols(market) if market else self.all_symbols()
        if not symbols:
            return []

        from futu import OpenQuoteContext, RET_OK

        quote_ctx = OpenQuoteContext(host=self.host, port=self.port)
        try:
            rows: list[dict[str, object]] = []
            for offset in range(0, len(symbols), 300):
                codes = [_to_futu_code(item) for item in symbols[offset : offset + 300]]
                rows.extend(_snapshot_rows(quote_ctx, codes, RET_OK))
        finally:
            quote_ctx.close()
        return [_snapshot_candidate(row) for row in rows if _valid_snapshot(row)]

    def trend_symbols(self, market: str) -> list[SymbolInfo]:
        """先用全市场快照完成市值硬筛，再下载成本较高的历史K线。"""
        min_cap = 5_000_000_000 if market.upper() == "HK" else 2_000_000_000
        eligible = {
            item.symbol
            for item in self.intraday_candidates(market)
            if item.market_cap >= min_cap
        }
        return [item for item in self.symbols(market) if item.symbol in eligible]


def _symbol_infos(rows: list[dict[str, object]], market: str) -> list[SymbolInfo]:
    result: list[SymbolInfo] = []
    for row in rows:
        code = str(row.get("code", "")).upper()
        if not code or _flag(row.get("delisting")):
            continue
        exchange = str(row.get("exchange_type", ""))
        if market == "US" and exchange not in {"US_NASDAQ", "US_NYSE", "US_AMEX"}:
            continue
        symbol = code.removeprefix("US.") if market == "US" else f"{_hk_symbol(code)}.HK"
        result.append(
            SymbolInfo(
                symbol=symbol,
                name=str(row.get("name", symbol)),
                market=market,  # type: ignore[arg-type]
                shortable=_flag(row.get("is_short_sell")),
            )
        )
    return result


def _to_futu_code(item: SymbolInfo) -> str:
    if item.market == "US":
        return f"US.{item.symbol.upper()}"
    return f"HK.{item.symbol.upper().removesuffix('.HK').zfill(5)}"


def _valid_snapshot(row: dict[str, object]) -> bool:
    return _number(row.get("last_price")) > 0 and bool(str(row.get("code", "")))


def _snapshot_candidate(row: dict[str, object]) -> IntradayCandidate:
    code = str(row.get("code", "")).upper()
    market = "US" if code.startswith("US.") else "HK"
    symbol = code.removeprefix("US.") if market == "US" else f"{_hk_symbol(code)}.HK"
    return IntradayCandidate(
        symbol=symbol,
        market=market,
        avg_turnover=_number(row.get("turnover")),
        prev_amplitude_pct=_number(row.get("amplitude")),
        price=_number(row.get("last_price")),
        halted=_flag(row.get("suspension")) or str(row.get("sec_status", "NORMAL")) != "NORMAL",
        ex_dividend_soon=False,
        major_news=False,
        turnover_rate=_number(row.get("turnover_rate")),
        market_cap=_number(row.get("circular_market_val")) or _number(row.get("total_market_val")),
    )


def _number(value: object) -> float:
    try:
        result = float(value or 0.0)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _flag(value: object) -> bool:
    return value is True or str(value).upper() == "TRUE"


def _snapshot_rows(quote_ctx: object, codes: list[str], ret_ok: int) -> list[dict[str, object]]:
    ret, data = quote_ctx.get_market_snapshot(codes)  # type: ignore[attr-defined]
    if ret == ret_ok:
        return data.to_dict("records")
    if len(codes) == 1:
        return []
    middle = len(codes) // 2
    return [
        *_snapshot_rows(quote_ctx, codes[:middle], ret_ok),
        *_snapshot_rows(quote_ctx, codes[middle:], ret_ok),
    ]


def _hk_symbol(code: str) -> str:
    digits = code.removeprefix("HK.")
    try:
        return str(int(digits)).zfill(4)
    except ValueError:
        return digits
