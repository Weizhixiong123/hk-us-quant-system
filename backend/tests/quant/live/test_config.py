import pytest
from quant.live.config import FutuGatewayConfig, load_futu_config

_CONFIRM = "I_UNDERSTAND_REAL_MONEY_RISK"


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
