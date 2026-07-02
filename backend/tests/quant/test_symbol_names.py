from quant.data.symbol_names import _name_from_quotes, normalize_symbol


def test_normalize_symbol_for_supported_markets():
    assert normalize_symbol(" asml.us ", "US") == "ASML"
    assert normalize_symbol("700", "HK") == "0700.HK"
    assert normalize_symbol("HK.09988", "HK") == "9988.HK"


def test_name_lookup_requires_an_exact_symbol_match():
    quotes = [
        {"symbol": "ASML.AS", "longname": "ASML Holding N.V."},
        {"symbol": "ASML", "longname": "ASML Holding N.V."},
    ]

    assert _name_from_quotes("ASML", quotes) == "ASML Holding N.V."
    assert _name_from_quotes("ASM", quotes) is None


def test_name_lookup_falls_back_to_short_name():
    quotes = [{"symbol": "0700.HK", "shortname": "TENCENT"}]

    assert _name_from_quotes("0700.HK", quotes) == "TENCENT"


def test_name_lookup_accepts_us_share_class_separators():
    quotes = [{"symbol": "BRK-B", "longname": "Berkshire Hathaway Inc."}]

    assert _name_from_quotes("BRK.B", quotes) == "Berkshire Hathaway Inc."
