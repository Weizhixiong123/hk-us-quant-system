from __future__ import annotations

import os
from dataclasses import dataclass

from quant.live.settings import load_live_settings

_VALID_TRD_ENV = {"SIMULATE", "REAL"}
_VALID_TIGER_ENV = {"sandbox", "live"}
_REAL_TRADING_CONFIRM = "I_UNDERSTAND_REAL_MONEY_RISK"
_TIGER_LIVE_TRADING_CONFIRM = "I_UNDERSTAND_TIGER_REAL_MONEY_RISK"


@dataclass(frozen=True)
class FutuAccountConfig:
    account_id: str
    name: str
    host: str
    port: int
    markets: tuple[str, ...]


@dataclass(frozen=True)
class FutuGatewayConfig:
    host: str
    port: int
    trd_env: str
    market: str
    markets: tuple[str, ...]
    paper: bool
    real_trading_confirmed: bool
    accounts: tuple[FutuAccountConfig, ...] = ()
    market_accounts: tuple[tuple[str, str], ...] = ()

    def account_for(self, market: str) -> FutuAccountConfig:
        normalized_market = market.upper()
        route = dict(self.market_accounts).get(normalized_market)
        if route:
            for account in self.accounts:
                if account.account_id == route:
                    return account
        return FutuAccountConfig(
            account_id="default",
            name="默认账户",
            host=self.host,
            port=self.port,
            markets=self.markets,
        )


@dataclass(frozen=True)
class TigerGatewayConfig:
    tiger_id: str
    account: str
    private_key: str
    private_key_path: str
    tiger_public_key_path: str
    environment: str
    language: str
    max_contracts: int
    use_preset_contracts: bool
    market: str
    markets: tuple[str, ...]
    paper: bool
    live_trading_confirmed: bool


def load_futu_config() -> FutuGatewayConfig:
    settings = load_live_settings().get("futu", {})
    trd_env = os.getenv("FUTU_TRD_ENV", str(settings.get("trd_env", "SIMULATE"))).upper()
    if trd_env not in _VALID_TRD_ENV:
        raise ValueError(f"FUTU_TRD_ENV must be one of {_VALID_TRD_ENV}, got {trd_env}")

    real_confirmed = _confirmation_from_env(
        "FUTU_REAL_TRADING_CONFIRM",
        _REAL_TRADING_CONFIRM,
        bool(settings.get("real_trading_confirmed", False)),
    )
    host = os.getenv("FUTU_HOST", str(settings.get("host", "127.0.0.1")))
    port = int(os.getenv("FUTU_PORT", str(settings.get("port", "11111"))))
    markets = _markets_from_env("FUTU_MARKETS", settings.get("markets", ["HK", "US"]))
    accounts = _futu_accounts_from_settings(settings.get("accounts"), host, port, markets)
    if len(accounts) == 1 and accounts[0].account_id == "default":
        accounts = (
            FutuAccountConfig(
                account_id="default",
                name=accounts[0].name,
                host=host,
                port=port,
                markets=accounts[0].markets,
            ),
        )
    market_accounts = _market_accounts_from_settings(
        settings.get("market_accounts"), accounts, markets
    )
    return FutuGatewayConfig(
        host=host,
        port=port,
        trd_env=trd_env,
        market=os.getenv("FUTU_MARKET", str(settings.get("market", "HK"))).upper(),
        markets=markets,
        paper=trd_env == "SIMULATE",
        real_trading_confirmed=real_confirmed,
        accounts=accounts,
        market_accounts=market_accounts,
    )


def load_tiger_config() -> TigerGatewayConfig:
    settings = load_live_settings().get("tiger", {})
    environment = os.getenv(
        "TIGER_ENVIRONMENT",
        str(settings.get("environment", "sandbox")),
    ).lower()
    if environment not in _VALID_TIGER_ENV:
        raise ValueError(
            f"TIGER_ENVIRONMENT must be one of {_VALID_TIGER_ENV}, got {environment}"
        )

    live_confirmed = _confirmation_from_env(
        "TIGER_LIVE_TRADING_CONFIRM",
        _TIGER_LIVE_TRADING_CONFIRM,
        bool(settings.get("live_trading_confirmed", False)),
    )
    return TigerGatewayConfig(
        tiger_id=os.getenv("TIGER_ID", str(settings.get("tiger_id", ""))),
        account=os.getenv("TIGER_ACCOUNT", str(settings.get("account", ""))),
        private_key=os.getenv(
            "TIGER_PRIVATE_KEY",
            str(settings.get("private_key", "")),
        ).replace("\\n", "\n"),
        private_key_path=os.getenv(
            "TIGER_PRIVATE_KEY_PATH",
            str(settings.get("private_key_path", "")),
        ),
        tiger_public_key_path=os.getenv(
            "TIGER_PUBLIC_KEY_PATH",
            str(settings.get("tiger_public_key_path", "")),
        ),
        environment=environment,
        language=os.getenv("TIGER_LANGUAGE", str(settings.get("language", "zh_CN"))),
        max_contracts=int(
            os.getenv("TIGER_MAX_CONTRACTS", str(settings.get("max_contracts", "100")))
        ),
        use_preset_contracts=_env_bool(
            "TIGER_USE_PRESET_CONTRACTS",
            bool(settings.get("use_preset_contracts", False)),
        ),
        market=os.getenv("TIGER_MARKET", str(settings.get("market", "US"))).upper(),
        markets=_markets_from_env("TIGER_MARKETS", settings.get("markets", ["US"])),
        paper=environment == "sandbox",
        live_trading_confirmed=live_confirmed,
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _confirmation_from_env(name: str, expected: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value == expected


def _markets_from_env(name: str, default: object) -> tuple[str, ...]:
    value = os.getenv(name)
    raw_items = value.split(",") if value else default
    if not isinstance(raw_items, list | tuple):
        raw_items = [raw_items]

    markets: list[str] = []
    for item in raw_items:
        market = str(item).strip().upper()
        if market in {"HK", "US"} and market not in markets:
            markets.append(market)
    return tuple(markets or ["HK"])


def _futu_accounts_from_settings(
    value: object,
    default_host: str,
    default_port: int,
    default_markets: tuple[str, ...],
) -> tuple[FutuAccountConfig, ...]:
    raw_accounts = value if isinstance(value, list) else []
    accounts: list[FutuAccountConfig] = []
    for item in raw_accounts:
        if not isinstance(item, dict):
            continue
        account_id = str(item.get("id", "")).strip()
        if not account_id:
            continue
        markets = _markets_from_value(item.get("markets"), default_markets)
        accounts.append(
            FutuAccountConfig(
                account_id=account_id,
                name=str(item.get("name", account_id)).strip() or account_id,
                host=str(item.get("host", default_host)).strip() or default_host,
                port=int(item.get("port", default_port)),
                markets=markets,
            )
        )
    if accounts:
        return tuple(accounts)
    return (
        FutuAccountConfig(
            account_id="default",
            name="默认账户",
            host=default_host,
            port=default_port,
            markets=default_markets,
        ),
    )


def _market_accounts_from_settings(
    value: object,
    accounts: tuple[FutuAccountConfig, ...],
    markets: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    requested = value if isinstance(value, dict) else {}
    routes: list[tuple[str, str]] = []
    for market in markets:
        account_id = str(requested.get(market, "")).strip()
        matching = next(
            (
                account
                for account in accounts
                if account.account_id == account_id and market in account.markets
            ),
            None,
        )
        if matching is None:
            matching = next(
                (account for account in accounts if market in account.markets),
                None,
            )
        if matching is None:
            raise ValueError(f"no Futu account is configured for {market}")
        routes.append((market, matching.account_id))
    return tuple(routes)


def _markets_from_value(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_items = value if isinstance(value, list | tuple) else default
    markets: list[str] = []
    for item in raw_items:
        market = str(item).strip().upper()
        if market in {"HK", "US"} and market not in markets:
            markets.append(market)
    return tuple(markets or default)
