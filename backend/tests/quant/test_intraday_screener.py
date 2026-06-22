from quant.screening.intraday_screener import IntradayCandidate, screen_intraday


def _ok(**kw):
    base = dict(
        symbol="AAPL", market="US", avg_turnover=8_000_000,
        prev_amplitude_pct=4.0, price=180.0,
        halted=False, ex_dividend_soon=False, major_news=False,
    )
    base.update(kw)
    return IntradayCandidate(**base)


def test_qualified_candidate_passes():
    hits = screen_intraday([_ok()])
    assert hits[0].passed is True


def test_low_turnover_fails():
    hits = screen_intraday([_ok(avg_turnover=1_000_000)])
    assert hits[0].passed is False
    assert any("成交额" in r for r in hits[0].reasons)


def test_amplitude_out_of_range_fails():
    assert screen_intraday([_ok(prev_amplitude_pct=1.0)])[0].passed is False
    assert screen_intraday([_ok(prev_amplitude_pct=9.0)])[0].passed is False


def test_penny_and_excludes_fail():
    assert screen_intraday([_ok(price=1.5)])[0].passed is False
    assert screen_intraday([_ok(halted=True)])[0].passed is False
    assert screen_intraday([_ok(ex_dividend_soon=True)])[0].passed is False
    assert screen_intraday([_ok(major_news=True)])[0].passed is False
