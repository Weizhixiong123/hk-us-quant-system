from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Iterable, Protocol

import pandas as pd

from app.strategies.trend_portfolio import FundamentalSnapshot
from quant.data.fundamentals import FundamentalsSource, default_fundamentals_source, load_fundamentals
from quant.data.loaders import load_daily
from quant.data.universe import SymbolInfo, all_symbols
from quant.indicators.macd import has_bearish_cross, has_bullish_cross, macd
from quant.live.market_data import BarAggregator
from quant.live.market_info import MarketInfoProvider
from quant.live.trend import DailyTimingSnapshot
from quant.screening.intraday_screener import IntradayCandidate


DailyLoader = Callable[[str, str, str, str], pd.DataFrame]


@dataclass(frozen=True)
class TrendExitContext:
    monthly_below_ma60_months: int = 0
    weekly_ma5: float = 0.0
    weekly_ma10: float = 0.0
    monthly_macd_dif: float = 0.0
    monthly_macd_dea: float = 0.0
    top_divergence: bool = False
    symbol_drawdown_pct: float = 0.0


class LiveDataProvider(Protocol):
    def intraday_candidates(self) -> list[IntradayCandidate]:
        ...

    def portfolio_rows(self) -> list[tuple[str, str, pd.DataFrame, FundamentalSnapshot]]:
        ...

    def daily_timing(self, symbol: str, market: str) -> DailyTimingSnapshot | None:
        ...

    def trend_exit_context(self, symbol: str, market: str) -> TrendExitContext:
        ...


class DefaultLiveDataProvider:
    def __init__(
        self,
        market_data: BarAggregator,
        symbols: list[SymbolInfo] | None = None,
        intraday_symbols: list[SymbolInfo] | None = None,
        daily_loader: DailyLoader | None = None,
        today: date | None = None,
        fundamentals_source: FundamentalsSource | None = None,
        risk_blocklist: Iterable[str] = (),
        market_info: MarketInfoProvider | None = None,
    ) -> None:
        self.market_data = market_data
        self.symbols = symbols or all_symbols()
        self.intraday_symbols = list(intraday_symbols) if intraday_symbols is not None else self.symbols
        self.daily_loader = daily_loader or load_daily
        self.today = today
        self.fundamentals_source = fundamentals_source or default_fundamentals_source
        self.risk_blocklist = tuple(risk_blocklist)
        self.market_info = market_info or MarketInfoProvider()
        self._fundamentals_cache: dict[str, FundamentalSnapshot] = {}

    def intraday_candidates(self) -> list[IntradayCandidate]:
        candidates: list[IntradayCandidate] = []
        for item in self.intraday_symbols:
            daily = self._load_daily(item, lookback_days=140)
            if daily is None or len(daily) < 21:
                continue
            prev = daily.iloc[-2]
            recent = daily.tail(20)
            latest_price = self.market_data.latest_price(item.symbol) or float(daily.iloc[-1]["close"])
            prev_close = float(prev["close"])
            amplitude = (float(prev["high"]) - float(prev["low"])) / prev_close * 100 if prev_close > 0 else 0.0
            turnover = (recent["close"] * recent["volume"]).mean()
            halted, ex_dividend_soon, major_news = self.market_info.lookup(item.symbol)
            candidates.append(
                IntradayCandidate(
                    symbol=item.symbol,
                    market=item.market,
                    avg_turnover=float(turnover),
                    prev_amplitude_pct=round(amplitude, 4),
                    price=float(latest_price),
                    halted=halted,
                    ex_dividend_soon=ex_dividend_soon,
                    major_news=major_news,
                )
            )
        return candidates

    def portfolio_rows(self) -> list[tuple[str, str, pd.DataFrame, FundamentalSnapshot]]:
        rows: list[tuple[str, str, pd.DataFrame, FundamentalSnapshot]] = []
        for item in self.symbols:
            daily = self._load_daily(item, lookback_days=2200)
            if daily is None:
                continue
            fundamentals = load_fundamentals(
                item.symbol,
                item.market,
                self.fundamentals_source,
                self.risk_blocklist,
                self._fundamentals_cache,
            )
            rows.append((item.symbol, item.market, daily, fundamentals))
        return rows

    def daily_timing(self, symbol: str, market: str) -> DailyTimingSnapshot | None:
        daily = self._load_daily(SymbolInfo(symbol, symbol, market), lookback_days=90)
        if daily is None or len(daily) < 31:
            return None
        close = daily["close"]
        volume = daily["volume"]
        points = macd(close.tolist())
        return DailyTimingSnapshot(
            close=float(close.iloc[-1]),
            low=float(daily["low"].iloc[-1]),
            ma20=float(close.tail(20).mean()),
            ma30=float(close.tail(30).mean()),
            previous_close=float(close.iloc[-2]),
            volume=float(volume.iloc[-1]),
            avg_volume20=float(volume.tail(20).mean()),
            macd_bearish_break=has_bearish_cross(points) if points else False,
            macd_recover_cross=has_bullish_cross(points) if points else False,
            short_term_gain_pct=_recent_gain_pct(close, 20),
        )

    def trend_exit_context(self, symbol: str, market: str) -> TrendExitContext:
        daily = self._load_daily(SymbolInfo(symbol, symbol, market), lookback_days=2200)
        if daily is None or len(daily) < 63:
            return TrendExitContext()
        close = daily["close"]
        drawdown = _drawdown_pct(close.tail(63))
        points = macd(close.resample("ME").last().dropna().tolist())
        monthly_dif = points[-1].dif if points else 0.0
        monthly_dea = points[-1].dea if points else 0.0
        weekly_close = close.resample("W").last().dropna()
        ma5 = float(weekly_close.tail(5).mean()) if len(weekly_close) >= 5 else 0.0
        ma10 = float(weekly_close.tail(10).mean()) if len(weekly_close) >= 10 else 0.0
        return TrendExitContext(
            monthly_below_ma60_months=_monthly_below_ma60_months(close),
            weekly_ma5=ma5,
            weekly_ma10=ma10,
            monthly_macd_dif=monthly_dif,
            monthly_macd_dea=monthly_dea,
            symbol_drawdown_pct=drawdown,
        )

    def _load_daily(self, item: SymbolInfo, lookback_days: int) -> pd.DataFrame | None:
        end_day = self.today or date.today()
        start = (end_day - timedelta(days=lookback_days)).isoformat()
        end = (end_day + timedelta(days=1)).isoformat()
        try:
            return self.daily_loader(item.symbol, item.market, start, end)
        except Exception:
            return None


def _recent_gain_pct(close: pd.Series, days: int) -> float:
    values = close.tail(days)
    if len(values) < 2 or float(values.iloc[0]) == 0:
        return 0.0
    return round((float(values.iloc[-1]) - float(values.iloc[0])) / float(values.iloc[0]) * 100, 4)


def _drawdown_pct(close: pd.Series) -> float:
    if close.empty:
        return 0.0
    peak = close.cummax()
    drawdown = (peak - close) / peak * 100
    return round(float(drawdown.max()), 4)


def _monthly_below_ma60_months(close: pd.Series) -> int:
    monthly = close.resample("ME").last().dropna()
    if len(monthly) < 60:
        return 0
    ma60 = monthly.rolling(60).mean()
    count = 0
    for price, average in zip(reversed(monthly.tolist()), reversed(ma60.tolist())):
        if pd.isna(average) or price >= average:
            break
        count += 1
    return count
