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
