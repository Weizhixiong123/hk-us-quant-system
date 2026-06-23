from __future__ import annotations

from quant.data.fundamentals import RawFundamentals, load_fundamentals


def test_load_fundamentals_uses_source_values():
    snap = load_fundamentals("AAPL", "US", lambda s, m: RawFundamentals(8e9, 3))
    assert snap.market_cap == 8e9
    assert snap.positive_profit_quarters == 3
    assert snap.has_major_risk is False


def test_blocklist_sets_major_risk():
    snap = load_fundamentals("evil", "US", lambda s, m: RawFundamentals(8e9, 3), risk_blocklist=["EVIL"])
    assert snap.has_major_risk is True


def test_missing_data_is_safe_side():
    snap = load_fundamentals("AAPL", "US", lambda s, m: None)
    assert snap.market_cap == 0.0
    assert snap.positive_profit_quarters == 0


def test_source_exception_is_safe_side():
    def boom(s, m):
        raise RuntimeError("network")

    snap = load_fundamentals("AAPL", "US", boom)
    assert snap.market_cap == 0.0


def test_cache_avoids_second_source_call():
    calls: list[str] = []

    def source(s, m):
        calls.append(s)
        return RawFundamentals(8e9, 3)

    cache: dict = {}
    load_fundamentals("AAPL", "US", source, cache=cache)
    load_fundamentals("AAPL", "US", source, cache=cache)
    assert len(calls) == 1
