import pytest
from quant.live.config import load_futu_config, load_tiger_config

_CONFIRM = "I_UNDERSTAND_REAL_MONEY_RISK"
_TIGER_CONFIRM = "I_UNDERSTAND_TIGER_REAL_MONEY_RISK"


def test_defaults(monkeypatch):
    for var in (
        "FUTU_HOST",
        "FUTU_PORT",
        "FUTU_TRD_ENV",
        "FUTU_MARKET",
        "FUTU_REAL_TRADING_CONFIRM",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = load_futu_config()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 11111
    assert cfg.trd_env == "SIMULATE"
    assert cfg.paper is True
    assert cfg.real_trading_confirmed is False


def test_real_env_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    monkeypatch.delenv("FUTU_REAL_TRADING_CONFIRM", raising=False)
    with pytest.raises(ValueError, match="FUTU_REAL_TRADING_CONFIRM"):
        load_futu_config()


def test_real_env_override_with_confirmation(monkeypatch):
    monkeypatch.setenv("FUTU_HOST", "192.168.1.10")
    monkeypatch.setenv("FUTU_PORT", "22222")
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    monkeypatch.setenv("FUTU_REAL_TRADING_CONFIRM", _CONFIRM)
    cfg = load_futu_config()
    assert cfg.host == "192.168.1.10"
    assert cfg.port == 22222
    assert cfg.trd_env == "REAL"
    assert cfg.paper is False
    assert cfg.real_trading_confirmed is True


def test_invalid_trd_env_raises(monkeypatch):
    monkeypatch.setenv("FUTU_TRD_ENV", "DEMO")
    with pytest.raises(ValueError):
        load_futu_config()


def test_tiger_defaults(monkeypatch):
    for var in (
        "TIGER_ID",
        "TIGER_ACCOUNT",
        "TIGER_PRIVATE_KEY",
        "TIGER_PRIVATE_KEY_PATH",
        "TIGER_PUBLIC_KEY_PATH",
        "TIGER_ENVIRONMENT",
        "TIGER_LANGUAGE",
        "TIGER_MAX_CONTRACTS",
        "TIGER_USE_PRESET_CONTRACTS",
        "TIGER_MARKET",
        "TIGER_LIVE_TRADING_CONFIRM",
    ):
        monkeypatch.delenv(var, raising=False)

    cfg = load_tiger_config()

    assert cfg.environment == "sandbox"
    assert cfg.language == "zh_CN"
    assert cfg.max_contracts == 100
    assert cfg.market == "US"
    assert cfg.paper is True
    assert cfg.live_trading_confirmed is False


def test_tiger_live_env_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setenv("TIGER_ENVIRONMENT", "live")
    monkeypatch.delenv("TIGER_LIVE_TRADING_CONFIRM", raising=False)

    with pytest.raises(ValueError, match="TIGER_LIVE_TRADING_CONFIRM"):
        load_tiger_config()


def test_tiger_live_env_override_with_confirmation(monkeypatch):
    monkeypatch.setenv("TIGER_ID", "tid")
    monkeypatch.setenv("TIGER_ACCOUNT", "acc")
    monkeypatch.setenv("TIGER_PRIVATE_KEY", "line1\\nline2")
    monkeypatch.setenv("TIGER_ENVIRONMENT", "live")
    monkeypatch.setenv("TIGER_LANGUAGE", "en_US")
    monkeypatch.setenv("TIGER_MAX_CONTRACTS", "25")
    monkeypatch.setenv("TIGER_USE_PRESET_CONTRACTS", "true")
    monkeypatch.setenv("TIGER_MARKET", "HK")
    monkeypatch.setenv("TIGER_LIVE_TRADING_CONFIRM", _TIGER_CONFIRM)

    cfg = load_tiger_config()

    assert cfg.tiger_id == "tid"
    assert cfg.account == "acc"
    assert cfg.private_key == "line1\nline2"
    assert cfg.environment == "live"
    assert cfg.language == "en_US"
    assert cfg.max_contracts == 25
    assert cfg.use_preset_contracts is True
    assert cfg.market == "HK"
    assert cfg.paper is False
    assert cfg.live_trading_confirmed is True


def test_tiger_invalid_environment_raises(monkeypatch):
    monkeypatch.setenv("TIGER_ENVIRONMENT", "paper")
    with pytest.raises(ValueError):
        load_tiger_config()


def test_tiger_config_can_load_from_settings_file(monkeypatch, tmp_path):
    from quant.live.settings import save_live_settings

    path = tmp_path / "live-settings.json"
    save_live_settings(
        {
            "tiger": {
                "tiger_id": "tid",
                "account": "acc",
                "private_key_path": "key.pem",
                "environment": "sandbox",
                "market": "HK",
            }
        },
        path,
    )
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(path))
    for var in ("TIGER_ID", "TIGER_ACCOUNT", "TIGER_PRIVATE_KEY_PATH"):
        monkeypatch.delenv(var, raising=False)

    cfg = load_tiger_config()

    assert cfg.tiger_id == "tid"
    assert cfg.account == "acc"
    assert cfg.private_key_path == "key.pem"
    assert cfg.market == "HK"
