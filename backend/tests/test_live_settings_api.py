from fastapi import HTTPException

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


def test_live_settings_api_rejects_live_without_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(tmp_path / "live-settings.json"))
    payload = LiveSettingsUpdate.model_validate(
        {"tiger": {"environment": "live", "live_trading_confirmed": False}}
    )

    try:
        update_live_settings(payload)
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected route to reject live without confirmation")


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
