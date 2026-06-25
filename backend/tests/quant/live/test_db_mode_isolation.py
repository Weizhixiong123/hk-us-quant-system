from __future__ import annotations

from quant.live.store import live_db_path_for_mode


def test_dry_run_uses_dedicated_db():
    path = live_db_path_for_mode({"runtime": {"dry_run": True}})
    assert path.name == "live-dry_run.sqlite3"
    assert path.parent.name == "data"


def test_each_broker_mode_gets_distinct_db():
    futu_sim = live_db_path_for_mode(
        {"runtime": {"dry_run": False, "broker": "futu"}, "futu": {"trd_env": "SIMULATE"}}
    )
    futu_real = live_db_path_for_mode(
        {"runtime": {"dry_run": False, "broker": "futu"}, "futu": {"trd_env": "REAL"}}
    )
    tiger_sb = live_db_path_for_mode(
        {"runtime": {"dry_run": False, "broker": "tiger"}, "tiger": {"environment": "sandbox"}}
    )
    tiger_live = live_db_path_for_mode(
        {"runtime": {"dry_run": False, "broker": "tiger"}, "tiger": {"environment": "live"}}
    )

    names = {futu_sim.name, futu_real.name, tiger_sb.name, tiger_live.name}
    assert names == {
        "live-futu-simulate.sqlite3",
        "live-futu-real.sqlite3",
        "live-tiger-sandbox.sqlite3",
        "live-tiger-live.sqlite3",
    }


def test_appstate_db_path_follows_current_mode(monkeypatch, tmp_path):
    import json

    from app.services.state import AppState
    from quant.live.state import LiveGatewayState

    settings_file = tmp_path / "live-settings.json"
    settings_file.write_text(
        json.dumps(
            {"runtime": {"dry_run": False, "broker": "futu"}, "futu": {"trd_env": "REAL"}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_file))

    state = AppState(LiveGatewayState())  # db_path=None → 动态按当前模式
    assert state._current_db_path().name == "live-futu-real.sqlite3"


def test_build_runtime_uses_mode_specific_db(monkeypatch, tmp_path):
    import json

    from quant.live.runtime import build_live_runtime_from_env
    from quant.live.state import LiveGatewayState

    settings_file = tmp_path / "live-settings.json"
    settings_file.write_text(json.dumps({"runtime": {"dry_run": True}}), encoding="utf-8")
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_file))
    monkeypatch.delenv("LIVE_RUNTIME_DRY_RUN", raising=False)

    runtime = build_live_runtime_from_env(LiveGatewayState())
    assert runtime.db_path.name == "live-dry_run.sqlite3"
