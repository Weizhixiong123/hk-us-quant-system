import pytest
from quant.live.config import FutuGatewayConfig, load_futu_config


def test_defaults(monkeypatch):
    for var in ("FUTU_HOST", "FUTU_PORT", "FUTU_TRD_ENV", "FUTU_MARKET"):
        monkeypatch.delenv(var, raising=False)
    cfg = load_futu_config()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 11111
    assert cfg.trd_env == "SIMULATE"
    assert cfg.paper is True


def test_env_override(monkeypatch):
    monkeypatch.setenv("FUTU_HOST", "192.168.1.10")
    monkeypatch.setenv("FUTU_PORT", "22222")
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    cfg = load_futu_config()
    assert cfg.host == "192.168.1.10"
    assert cfg.port == 22222
    assert cfg.trd_env == "REAL"
    assert cfg.paper is False


def test_invalid_trd_env_raises(monkeypatch):
    monkeypatch.setenv("FUTU_TRD_ENV", "DEMO")
    with pytest.raises(ValueError):
        load_futu_config()
