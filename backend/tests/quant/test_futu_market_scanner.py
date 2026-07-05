from __future__ import annotations

from quant.data.futu_market_scanner import _snapshot_candidate, _symbol_infos


def test_symbol_infos_convert_full_market_codes():
    us = _symbol_infos(
        [
            {"code": "US.AAPL", "name": "Apple", "delisting": False, "exchange_type": "US_NASDAQ"},
            {"code": "US.OTC", "name": "OTC", "delisting": False, "exchange_type": "US_PINK"},
        ],
        "US",
    )
    hk = _symbol_infos([{"code": "HK.00700", "name": "腾讯", "delisting": False}], "HK")

    assert us[0].symbol == "AAPL"
    assert len(us) == 1
    assert hk[0].symbol == "0700.HK"


def test_snapshot_candidate_uses_realtime_market_fields():
    candidate = _snapshot_candidate(
        {
            "code": "US.NVDA",
            "last_price": 125.0,
            "turnover": 80_000_000,
            "amplitude": 4.2,
            "turnover_rate": 1.5,
            "circular_market_val": 2_500_000_000,
            "total_market_val": 3_000_000_000,
            "suspension": False,
        }
    )

    assert candidate.symbol == "NVDA"
    assert candidate.avg_turnover == 80_000_000
    assert candidate.prev_amplitude_pct == 4.2
    assert candidate.turnover_rate == 1.5
    assert candidate.market_cap == 2_500_000_000
