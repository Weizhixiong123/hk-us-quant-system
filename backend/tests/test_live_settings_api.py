from app.api.routes import live_settings, update_live_settings
from app.models.schemas import LiveSettingsUpdate


def test_live_settings_api_saves_and_redacts_private_key(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(tmp_path / "live-settings.json"))

    payload = LiveSettingsUpdate.model_validate(
        {
            "runtime": {"broker": "tiger", "enabled": True, "dry_run": False},
            "tiger": {
                "tiger_id": "tid",
                "account": "acc",
                "private_key": "secret",
                "environment": "sandbox",
            },
        }
    )

    response = update_live_settings(payload)

    assert response["runtime"]["broker"] == "tiger"
    assert response["tiger"]["private_key_configured"] is True
    assert "private_key" not in response["tiger"]
    assert live_settings()["tiger"]["private_key_configured"] is True


def test_live_settings_api_accepts_live_without_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(tmp_path / "live-settings.json"))
    payload = LiveSettingsUpdate.model_validate(
        {"tiger": {"environment": "live", "live_trading_confirmed": False}}
    )

    response = update_live_settings(payload)

    assert response["tiger"]["environment"] == "live"


def test_live_settings_api_round_trips_broker_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(tmp_path / "live-settings.json"))
    payload = LiveSettingsUpdate.model_validate(
        {
            "runtime": {"broker": "futu", "enabled": True, "dry_run": False},
            "futu": {
                "host": "192.168.1.20",
                "port": 22222,
                "trd_env": "REAL",
                "market": "HK",
                "markets": ["HK", "US"],
            },
            "tiger": {
                "tiger_id": "tid",
                "account": "account",
                "private_key_path": "C:/keys/tiger.pem",
                "tiger_public_key_path": "C:/keys/tiger.pub",
                "environment": "live",
                "language": "zh_CN",
                "max_contracts": 50,
                "market": "US",
                "markets": ["US"],
            },
        }
    )

    update_live_settings(payload)
    response = live_settings()

    assert response["futu"]["host"] == "192.168.1.20"
    assert response["futu"]["port"] == 22222
    assert response["futu"]["trd_env"] == "REAL"
    assert response["futu"]["markets"] == ["HK", "US"]
    assert response["tiger"]["tiger_id"] == "tid"
    assert response["tiger"]["account"] == "account"
    assert response["tiger"]["private_key_path"] == "C:/keys/tiger.pem"
    assert response["tiger"]["tiger_public_key_path"] == "C:/keys/tiger.pub"


def test_live_settings_api_round_trips_manual_intraday_universe(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(tmp_path / "live-settings.json"))
    payload = LiveSettingsUpdate.model_validate(
        {
            "intraday_universe": {
                "selection_mode": "manual",
                "manual_symbols": [
                    {"symbol": "tsla", "name": "Tesla", "market": "US", "shortable": True}
                ],
            }
        }
    )

    response = update_live_settings(payload)

    assert response["intraday_universe"]["selection_mode"] == "manual"
    assert response["intraday_universe"]["manual_symbols"][0]["symbol"] == "TSLA"


def test_runtime_reload_returns_running_state(monkeypatch, tmp_path):
    import os

    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("LIVE_RUNTIME_ENABLED", "1")
    monkeypatch.setenv("LIVE_RUNTIME_DRY_RUN", "1")
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(tmp_path / "live-settings.json"))
    os.makedirs(tmp_path / "data", exist_ok=True)

    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/api/runtime/reload")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["runtime_running"] is True
        assert body["runtime_dry_run"] is True
