from quant.live.settings import load_live_settings, public_live_settings, save_live_settings


def test_save_live_settings_redacts_private_key_in_public_view(tmp_path):
    path = tmp_path / "live-settings.json"

    settings = save_live_settings(
        {
            "runtime": {"broker": "tiger", "enabled": True, "dry_run": False},
            "tiger": {
                "tiger_id": "tid",
                "account": "acc",
                "private_key": "secret",
                "environment": "sandbox",
            },
        },
        path,
    )

    assert load_live_settings(path)["tiger"]["private_key"] == "secret"
    public = public_live_settings(settings)
    assert "private_key" not in public["tiger"]
    assert public["tiger"]["private_key_configured"] is True


def test_save_live_settings_accepts_live_without_confirmation(tmp_path):
    path = tmp_path / "live-settings.json"

    settings = save_live_settings({"tiger": {"environment": "live"}}, path)

    assert settings["tiger"]["environment"] == "live"


def test_clear_private_key(tmp_path):
    path = tmp_path / "live-settings.json"
    save_live_settings({"tiger": {"private_key": "secret"}}, path)

    settings = save_live_settings({"tiger": {"clear_private_key": True}}, path)

    assert settings["tiger"]["private_key"] == ""


def test_manual_intraday_universe_is_normalized_and_deduplicated(tmp_path):
    path = tmp_path / "live-settings.json"

    settings = save_live_settings(
        {
            "intraday_universe": {
                "selection_mode": "manual",
                "manual_symbols": [
                    {"symbol": "700", "name": "腾讯控股", "market": "HK", "shortable": True},
                    {"symbol": "0700.HK", "name": "重复项", "market": "HK"},
                    {"symbol": "aapl.us", "name": "Apple", "market": "US"},
                ],
            }
        },
        path,
    )

    assert settings["intraday_universe"] == {
        "selection_mode": "manual",
        "manual_symbols": [
            {"symbol": "0700.HK", "name": "腾讯控股", "market": "HK", "shortable": True},
            {"symbol": "AAPL", "name": "Apple", "market": "US", "shortable": False},
        ],
    }
