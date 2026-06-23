from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from quant.live.translate import GatewayTick


@dataclass(frozen=True)
class Bar:
    symbol: str
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BarAggregator:
    def __init__(self, max_bars: int = 500) -> None:
        self.max_bars = max_bars
        self._current: dict[str, Bar] = {}
        self._minute_bars: dict[str, list[Bar]] = {}
        self._seen_ticks: set[tuple[str, str, float, float]] = set()

    def ingest_ticks(self, ticks: Iterable[GatewayTick]) -> None:
        for tick in ticks:
            self.ingest_tick(tick)

    def ingest_tick(self, tick: GatewayTick) -> None:
        if tick.last_price <= 0:
            return
        tick_key = (tick.symbol, tick.time, tick.last_price, tick.volume)
        if tick_key in self._seen_ticks:
            return
        self._seen_ticks.add(tick_key)

        tick_time = _parse_time(tick.time)
        minute = tick_time.replace(second=0, microsecond=0)
        current = self._current.get(tick.symbol)
        if current is not None and current.start != minute:
            self._append_minute_bar(current)
            current = None

        if current is None:
            self._current[tick.symbol] = Bar(
                symbol=tick.symbol,
                start=minute,
                open=tick.last_price,
                high=tick.last_price,
                low=tick.last_price,
                close=tick.last_price,
                volume=tick.volume,
            )
            return

        self._current[tick.symbol] = Bar(
            symbol=tick.symbol,
            start=current.start,
            open=current.open,
            high=max(current.high, tick.last_price),
            low=min(current.low, tick.last_price),
            close=tick.last_price,
            volume=max(tick.volume, current.volume),
        )

    def minute_bars(self, symbol: str, limit: int = 100) -> list[Bar]:
        return self._minute_bars.get(symbol, [])[-limit:]

    def interval_bars(self, symbol: str, interval_minutes: int, limit: int = 100) -> list[Bar]:
        if interval_minutes <= 0:
            raise ValueError("interval_minutes must be positive")
        grouped: dict[datetime, list[Bar]] = {}
        for bar in self._minute_bars.get(symbol, []):
            start_minute = bar.start.minute - (bar.start.minute % interval_minutes)
            bucket = bar.start.replace(minute=start_minute, second=0, microsecond=0)
            grouped.setdefault(bucket, []).append(bar)

        result = [_merge_bars(bucket, bars) for bucket, bars in sorted(grouped.items())]
        return result[-limit:]

    def latest_price(self, symbol: str) -> float | None:
        current = self._current.get(symbol)
        if current is not None:
            return current.close
        bars = self._minute_bars.get(symbol, [])
        return bars[-1].close if bars else None

    def flush_open_bars(self) -> None:
        for symbol, bar in list(self._current.items()):
            self._append_minute_bar(bar)
            self._current.pop(symbol, None)

    def _append_minute_bar(self, bar: Bar) -> None:
        bars = self._minute_bars.setdefault(bar.symbol, [])
        bars.append(bar)
        if len(bars) > self.max_bars:
            del bars[: len(bars) - self.max_bars]


def _merge_bars(start: datetime, bars: list[Bar]) -> Bar:
    return Bar(
        symbol=bars[0].symbol,
        start=start,
        open=bars[0].open,
        high=max(bar.high for bar in bars),
        low=min(bar.low for bar in bars),
        close=bars[-1].close,
        volume=bars[-1].volume - bars[0].volume if bars[-1].volume >= bars[0].volume else bars[-1].volume,
    )


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
