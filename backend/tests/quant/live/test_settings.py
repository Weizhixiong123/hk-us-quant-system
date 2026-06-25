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


def test_save_live_settings_rejects_live_without_confirmation(tmp_path):
    path = tmp_path / "live-settings.json"

    try:
        save_live_settings({"tiger": {"environment": "live"}}, path)
    except ValueError as exc:
        assert "live mode requires" in str(exc)
    else:
        raise AssertionError("expected live settings to require confirmation")


def test_clear_private_key(tmp_path):
    path = tmp_path / "live-settings.json"
    save_live_settings({"tiger": {"private_key": "secret"}}, path)

    settings = save_live_settings({"tiger": {"clear_private_key": True}}, path)

    assert settings["tiger"]["private_key"] == ""
