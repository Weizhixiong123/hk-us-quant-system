from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from app.models.schemas import (
    AccountSummary,
    BacktestRequest,
    BacktestResult,
    Candle,
    DashboardSnapshot,
    Order,
    ParamValue,
    Position,
    RiskRuleStatus,
    Severity,
    Signal,
    StrategyConfig,
    Trade,
    TradeLog,
    WatchSymbol,
)
from quant.data.universe import all_symbols
from quant.indicators.scoring import ScoreInputs, score_for_symbol
from quant.live.params import LiveParams
from quant.live.settings import INTRADAY_PARAM_DEFAULTS, load_live_settings, save_live_settings
from quant.live.state import LiveGatewayState
from quant.live.store import LiveEvent, list_live_events, live_db_path_for_mode


_SERVER_TZ = timezone(timedelta(hours=8))


def _score_inputs_for_selection(
    event: LiveEvent,
    symbol: str,
    market: str,
    now: datetime,
) -> ScoreInputs:
    """从 selection event payload 提取 ScoreInputs。缺字段 → None → 0.5 fallback。"""
    payload = event.payload or {}
    comp = (payload.get("score_components") or {}).get(symbol) or {}
    age_hours: float | None = None
    if event.created_at is not None:
        delta = (now - event.created_at).total_seconds() / 3600.0
        age_hours = max(delta, 0.0)
    return ScoreInputs(
        symbol=symbol,
        market=market,
        consistency=comp.get("consistency"),
        daily_volume_ratio=comp.get("daily_volume_ratio"),
        intraday_volume_ratio=comp.get("intraday_volume_ratio"),
        prev_amplitude_pct=comp.get("prev_amplitude_pct"),
        price_vs_ma20_pct=comp.get("price_vs_ma20_pct"),
        price_vs_ma30_pct=comp.get("price_vs_ma30_pct"),
        short_term_gain_pct=comp.get("short_term_gain_pct"),
        avg_turnover=comp.get("avg_turnover"),
        selection_age_hours=age_hours,
    )


def _score_inputs_for_signal(event: LiveEvent, now: datetime) -> ScoreInputs:
    """signal event:consistency 默认 1.0(已触发信号 = 当时 3 周期 MACD 一致)。"""
    payload = event.payload or {}
    comp = payload.get("score_components") or {}
    age_hours: float | None = None
    if event.created_at is not None:
        delta = (now - event.created_at).total_seconds() / 3600.0
        age_hours = max(delta, 0.0)
    return ScoreInputs(
        symbol=event.symbol or "",
        market=_market_from_symbol(event.symbol or ""),
        consistency=comp.get("consistency", 1.0),
        daily_volume_ratio=comp.get("daily_volume_ratio"),
        intraday_volume_ratio=comp.get("intraday_volume_ratio"),
        prev_amplitude_pct=comp.get("prev_amplitude_pct"),
        price_vs_ma20_pct=comp.get("price_vs_ma20_pct"),
        price_vs_ma30_pct=comp.get("price_vs_ma30_pct"),
        short_term_gain_pct=comp.get("short_term_gain_pct"),
        avg_turnover=comp.get("avg_turnover"),
        selection_age_hours=age_hours,
    )


def _is_shortable(symbol: str) -> bool:
    """从 manual universe 配置里查 shortable 标记。symbol 不在 manual 里 → False。"""
    try:
        settings = load_live_settings()
    except Exception:
        return False
    universe = settings.get("intraday_universe", {}) or {}
    for item in universe.get("manual_symbols", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("symbol", "")).upper() == symbol.upper():
            return bool(item.get("shortable", False))
    return False


class AppState:
    def __init__(
        self,
        live_state: LiveGatewayState | None = None,
        params: LiveParams | None = None,
        db_path=None,
        persist_strategy_params: bool = False,
    ) -> None:
        self.params = params or LiveParams()
        self._persist_strategy_params = persist_strategy_params
        if persist_strategy_params:
            self.params.update(
                "intraday_macd",
                load_live_settings().get("intraday_params", {}),
            )
        self._lock = RLock()
        self._rng = random.Random(42)
        self.live_state = live_state
        self.db_path = db_path
        now = self._now()
        self.account = AccountSummary(
            source="dry_run",
            total_equity=1_285_000,
            cash=515_500,
            buying_power=2_124_000,
            day_pnl=8_420,
            day_pnl_pct=0.66,
        )
        self.strategies = [
            StrategyConfig(
                id="intraday_macd",
                name="策略一 · 日内 MACD",
                description="15min 主信号 + 5min 确认，日内自动开平仓且尾盘清仓。",
                enabled=True,
                state="running",
                automation="full_auto",
                cadence="5min / 15min",
                markets=["HK", "US"],
                params={
                    **{
                        key: getattr(self.params.intraday, key)
                        for key in INTRADAY_PARAM_DEFAULTS
                    },
                    "stop_loss_pct": 1.5,
                    "take_profit_1_pct": 2.0,
                    "take_profit_2_pct": 3.5,
                },
                risk_controls=[
                    "单日最大亏损 3%",
                    "单标的止损后当日禁开",
                    "美股 PDT 拦截",
                    "做空名单校验",
                    "收盘前 10 分钟强制清仓",
                ],
                last_signal="AAPL 5min 金叉确认，等待 15min 背离完成",
                updated_at=now,
            ),
            StrategyConfig(
                id="trend_portfolio",
                name="策略二 · 中长线选股持仓",
                description="月线定牛熊、周线确认趋势、日线择时，月度调仓。",
                enabled=True,
                state="running",
                automation="semi_auto",
                cadence="daily / monthly",
                markets=["HK", "US"],
                params={
                    "single_position_cap_pct": 15.0,
                    "target_positions_min": 5,
                    "target_positions_max": 8,
                    "max_symbol_drawdown_pct": 18.0,
                    "first_entry_fraction_pct": 60.0,
                    "rebalance_months": 6,
                    "hot_gain_block_pct": 40.0,
                },
                risk_controls=[
                    "总持仓 5~8 只",
                    "单只最大仓位 15%",
                    "分两次建仓",
                    "满 6 个月强制复核",
                    "月线破位清仓",
                ],
                last_signal="NVDA 仍在候选池，等待日线回踩 20MA",
                updated_at=now,
            ),
        ]
        self.positions = [
            Position(
                symbol="0700.HK",
                name="腾讯控股",
                market="HK",
                strategy_id="trend_portfolio",
                side="long",
                quantity=800,
                avg_price=376.2,
                last_price=389.4,
                market_value=311_520,
                pnl=10_560,
                pnl_pct=3.51,
                holding_days=24,
            ),
            Position(
                symbol="AAPL",
                name="Apple",
                market="US",
                strategy_id="intraday_macd",
                side="long",
                quantity=400,
                avg_price=198.4,
                last_price=201.1,
                market_value=80_440,
                pnl=1_080,
                pnl_pct=1.36,
                holding_days=0,
            ),
            Position(
                symbol="9988.HK",
                name="阿里巴巴-W",
                market="HK",
                strategy_id="trend_portfolio",
                side="long",
                quantity=2_000,
                avg_price=82.1,
                last_price=84.6,
                market_value=169_200,
                pnl=5_000,
                pnl_pct=3.05,
                holding_days=18,
            ),
        ]
        self.watchlist = [
            WatchSymbol(
                symbol="AAPL",
                name="Apple",
                market="US",
                last_price=201.1,
                change_pct=0.84,
                turnover=6_850_000_000,
                score=0.82,
                tags=["15m 缩量", "5m 金叉"],
                updated_at=now,
            ),
            WatchSymbol(
                symbol="MSFT",
                name="Microsoft",
                market="US",
                last_price=478.6,
                change_pct=0.38,
                turnover=5_170_000_000,
                score=0.77,
                tags=["周线多头", "月线零轴上"],
                updated_at=now,
            ),
            WatchSymbol(
                symbol="0700.HK",
                name="腾讯控股",
                market="HK",
                last_price=389.4,
                change_pct=1.12,
                turnover=1_920_000_000,
                score=0.86,
                tags=["日线回踩", "候选持仓"],
                updated_at=now,
            ),
            WatchSymbol(
                symbol="3690.HK",
                name="美团-W",
                market="HK",
                last_price=128.7,
                change_pct=-0.44,
                turnover=1_120_000_000,
                score=0.64,
                tags=["波动观察", "未触发"],
                updated_at=now,
            ),
        ]
        self.signals = [
            Signal(
                id="SIG-1007",
                strategy_id="intraday_macd",
                symbol="AAPL",
                market="US",
                side="long",
                confidence=0.76,
                reason="5min MACD 金叉，15min 绿柱连续缩短 3 根。",
                created_at=now - timedelta(minutes=4),
                status="new",
            ),
            Signal(
                id="SIG-1006",
                strategy_id="trend_portfolio",
                symbol="MSFT",
                market="US",
                side="watch",
                confidence=0.81,
                reason="月线站上 20/60MA，周线均线多头排列。",
                created_at=now - timedelta(hours=1),
                status="acknowledged",
            ),
            Signal(
                id="SIG-1005",
                strategy_id="intraday_macd",
                symbol="3690.HK",
                market="HK",
                side="short",
                confidence=0.52,
                reason="顶背离未完成，做空校验待确认。",
                created_at=now - timedelta(hours=2),
                status="filtered",
            ),
        ]
        self.orders = [
            Order(
                id="ORD-8205",
                strategy_id="intraday_macd",
                symbol="AAPL",
                market="US",
                side="buy",
                quantity=400,
                price=198.4,
                status="filled",
                created_at=now - timedelta(hours=3),
            ),
            Order(
                id="ORD-8204",
                strategy_id="trend_portfolio",
                symbol="9988.HK",
                market="HK",
                side="buy",
                quantity=2_000,
                price=82.1,
                status="filled",
                created_at=now - timedelta(days=18),
            ),
        ]
        self.trades: list[Trade] = []
        self.logs = [
            TradeLog(
                id="LOG-4011",
                time=now - timedelta(minutes=2),
                source="risk",
                severity="info",
                message="PDT 检查通过，剩余日内交易额度 3。",
            ),
            TradeLog(
                id="LOG-4010",
                time=now - timedelta(minutes=4),
                source="intraday_macd",
                severity="info",
                message="AAPL 进入候选开仓队列，等待 15min 收线确认。",
            ),
            TradeLog(
                id="LOG-4009",
                time=now - timedelta(hours=1),
                source="trend_portfolio",
                severity="warning",
                message="MSFT 达到中长线候选标准，但短期涨幅接近阈值。",
            ),
        ]
        self.chart = self._build_chart()

    def dashboard(self) -> DashboardSnapshot:
        with self._lock:
            live_snapshot = self._live_snapshot()
            uses_live_state = self.live_state is not None
            positions = self._live_positions(live_snapshot)
            orders = self._live_orders(live_snapshot)
            trades = self._live_trades(live_snapshot)
            if not uses_live_state:
                # 只有显式创建纯演示 AppState 时才使用 seed 数据。
                positions = positions or self.positions
                orders = orders or self.orders
                trades = trades or self.trades
            watchlist = self._live_watchlist() if uses_live_state else self.watchlist
            signals = self._live_signals() if uses_live_state else self.signals
            return DashboardSnapshot(
                server_time=self._now(),
                account=self._dashboard_account(live_snapshot),
                risk=self.risk_status(live_snapshot),
                strategies=self.strategies,
                positions=positions,
                watchlist=watchlist,
                signals=signals,
                orders=orders,
                trades=trades,
                logs=self._live_logs(live_snapshot) + self.logs,
                chart=self.chart,
            )

    def risk_status(self, live_snapshot: dict | None = None) -> list[RiskRuleStatus]:
        live_snapshot = live_snapshot if live_snapshot is not None else self._live_snapshot()
        if self.live_state is not None:
            intraday_positions = sum(
                1
                for position in self._live_positions(live_snapshot)
                if position.strategy_id == "intraday_macd"
            )
        else:
            intraday_positions = sum(
                1 for position in self.positions if position.strategy_id == "intraday_macd"
            )
        account = self._dashboard_account(live_snapshot)
        intraday_params = self.params.intraday
        gateway_connected = bool(live_snapshot and live_snapshot.get("connected"))
        gateway_detail = str(live_snapshot.get("detail", "")) if live_snapshot else "未初始化实盘网关"
        return [
            RiskRuleStatus(
                code="broker_connection",
                name="富途连接",
                status="pass" if gateway_connected else "blocked",
                detail=gateway_detail or ("已连接" if gateway_connected else "未连接"),
            ),
            RiskRuleStatus(
                code="daily_loss",
                name="单日最大亏损",
                status=(
                    "pass"
                    if account.day_pnl_pct > -intraday_params.max_daily_loss_pct
                    else "blocked"
                ),
                detail=(
                    f"当前 {account.day_pnl_pct:.2f}%，"
                    f"阈值 -{intraday_params.max_daily_loss_pct:.2f}%"
                ),
            ),
            RiskRuleStatus(
                code="intraday_position_count",
                name="日内持仓数量",
                status=(
                    "watch"
                    if intraday_positions >= max(1, intraday_params.max_positions - 1)
                    else "pass"
                ),
                detail=f"{intraday_positions}/{intraday_params.max_positions}",
            ),
            RiskRuleStatus(
                code="pdt",
                name="美股 PDT",
                status="pass",
                detail="滚动 5 个交易日额度已内置，账户类型与权益以券商回报为准。",
            ),
            RiskRuleStatus(
                code="shortable",
                name="做空校验",
                status="watch",
                detail="空头信号仅记录，等待券商可借券接口。",
            ),
        ]

    def current_positions(self) -> list[Position]:
        live_positions = self._live_positions(self._live_snapshot())
        return live_positions if self.live_state is not None else self.positions

    def current_orders(self) -> list[Order]:
        live_orders = self._live_orders(self._live_snapshot())
        return live_orders if self.live_state is not None else self.orders

    def current_trades(self) -> list[Trade]:
        live_trades = self._live_trades(self._live_snapshot())
        return live_trades if self.live_state is not None else self.trades

    def current_logs(self) -> list[TradeLog]:
        live_snapshot = self._live_snapshot()
        return self._live_logs(live_snapshot) + self.logs

    def set_strategy_enabled(self, strategy_id: str, enabled: bool) -> StrategyConfig:
        with self._lock:
            strategy = self._find_strategy(strategy_id)
            strategy.enabled = enabled
            strategy.state = "running" if enabled else "paused"
            strategy.updated_at = self._now()
            self._append_log(
                source=strategy_id,
                severity="info",
                message=f"{strategy.name} 已{'开启' if enabled else '暂停'}。",
            )
            return strategy

    def update_strategy_params(
        self,
        strategy_id: str,
        params: dict[str, ParamValue],
    ) -> StrategyConfig:
        with self._lock:
            strategy = self._find_strategy(strategy_id)
            self.params.update(strategy_id, params)
            strategy.params.update(params)
            strategy.updated_at = self._now()
            if strategy_id == "intraday_macd" and self._persist_strategy_params:
                persisted = {
                    key: getattr(self.params.intraday, key)
                    for key in INTRADAY_PARAM_DEFAULTS
                }
                save_live_settings({"intraday_params": persisted})
                strategy.params.update(persisted)
            if strategy_id == "intraday_macd" and "max_daily_loss_pct" in params:
                self.account.max_daily_loss_pct = self.params.intraday.max_daily_loss_pct
            self._append_log(
                source=strategy_id,
                severity="info",
                message=f"{strategy.name} 参数已更新：{', '.join(params.keys())}",
            )
            return strategy

    def run_backtest(self, request: BacktestRequest) -> BacktestResult:
        strategy = self._find_strategy(request.strategy_id)
        try:
            from quant.backtest.service import run_backtest as run_quant_backtest

            result = run_quant_backtest(request)
        except ImportError as exc:
            result = self._failed_backtest_result(
                request,
                f"回测依赖未安装：{exc.name or exc}。请先执行 pip install -r requirements.txt。",
            )
        except Exception as exc:
            result = self._failed_backtest_result(request, f"回测失败：{exc}")

        result = self._store_backtest_result(result)
        self._append_log(
            source="backtest",
            severity="info",
            message=f"{strategy.name} {request.market} 回测任务已生成。",
        )
        return result

    def list_backtests(self, limit: int = 20) -> list[BacktestResult]:
        try:
            from quant.backtest.store import list_backtest_results

            return list_backtest_results(limit)
        except Exception as exc:
            self._append_log(
                source="backtest",
                severity="warning",
                message=f"回测历史读取失败：{exc}",
            )
            return []

    def _store_backtest_result(self, result: BacktestResult) -> BacktestResult:
        try:
            from quant.backtest.store import save_backtest_result

            return save_backtest_result(result)
        except Exception as exc:
            result.notes.append(f"回测结果保存失败：{exc}")
            return result

    def _failed_backtest_result(self, request: BacktestRequest, note: str) -> BacktestResult:
        return BacktestResult(
            id=f"BT-{uuid4().hex[:8].upper()}",
            strategy_id=request.strategy_id,
            market=request.market,
            start_date=request.start_date,
            end_date=request.end_date,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe=0.0,
            win_rate_pct=0.0,
            trades=0,
            equity_curve=[],
            notes=[note],
        )

    def tick(self) -> DashboardSnapshot:
        with self._lock:
            if self.live_state is not None:
                # 已配置运行态：返回真实快照，不做随机演示漂移。
                return self.dashboard()
            drift = self._rng.uniform(-0.25, 0.3)
            self.account.day_pnl = round(self.account.day_pnl + drift * 620, 2)
            self.account.day_pnl_pct = round(
                self.account.day_pnl / self.account.total_equity * 100,
                2,
            )
            for item in self.watchlist:
                move = self._rng.uniform(-0.18, 0.22)
                item.last_price = round(max(0.01, item.last_price * (1 + move / 100)), 2)
                item.change_pct = round(item.change_pct + move, 2)
            for position in self.positions:
                move = self._rng.uniform(-0.16, 0.2)
                position.last_price = round(position.last_price * (1 + move / 100), 2)
                position.market_value = round(position.quantity * position.last_price, 2)
                basis = position.quantity * position.avg_price
                position.pnl = round(position.market_value - basis, 2)
                position.pnl_pct = round(position.pnl / basis * 100, 2)
            last = self.chart[-1]
            close = round(max(1, last.close * (1 + drift / 400)), 2)
            # Parse last candle time and add 5 min — avoids collisions from same‑minute ticks.
            parts = last.time.split(":")
            h, m = int(parts[0]), int(parts[1])
            next_min = h * 60 + m + 5
            next_h, next_m = divmod(next_min, 60)
            next_time = f"{next_h % 24:02d}:{next_m % 60:02d}"
            self.chart = [
                *self.chart[1:],
                Candle(
                    time=next_time,
                    open=last.close,
                    high=round(max(last.close, close) * 1.003, 2),
                    low=round(min(last.close, close) * 0.997, 2),
                    close=close,
                    volume=int(last.volume * (1 + abs(drift) / 10)),
                ),
            ]
            return self.dashboard()

    def _find_strategy(self, strategy_id: str) -> StrategyConfig:
        for strategy in self.strategies:
            if strategy.id == strategy_id:
                return strategy
        raise KeyError(f"unknown strategy: {strategy_id}")

    def _append_log(self, source: str, severity: Severity, message: str) -> None:
        self.logs.insert(
            0,
            TradeLog(
                id=f"LOG-{uuid4().hex[:6].upper()}",
                time=self._now(),
                source=source,
                severity=severity,
                message=message,
            ),
        )
        self.logs = self.logs[:30]

    def _build_chart(self) -> list[Candle]:
        candles: list[Candle] = []
        base = 198.0
        # Align last candle to the current 5‑minute boundary so tick() never collides.
        now = self._now()
        aligned = now.replace(second=0, microsecond=0)
        aligned = aligned.replace(minute=(aligned.minute // 5) * 5)
        # 64 bars, each 5 min apart, ending at `aligned`.
        start = aligned - timedelta(minutes=5 * 63)
        for index in range(64):
            wave = math.sin(index / 5) * 1.8
            trend = index * 0.045
            open_price = base + wave + trend + self._rng.uniform(-0.25, 0.25)
            close = open_price + self._rng.uniform(-0.65, 0.72)
            high = max(open_price, close) + self._rng.uniform(0.12, 0.55)
            low = min(open_price, close) - self._rng.uniform(0.12, 0.5)
            candles.append(
                Candle(
                    time=(start + timedelta(minutes=5 * index)).strftime("%H:%M"),
                    open=round(open_price, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    close=round(close, 2),
                    volume=120_000 + int(abs(math.sin(index)) * 90_000),
                )
            )
        return candles

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _live_snapshot(self) -> dict | None:
        if self.live_state is None:
            return None
        return self.live_state.snapshot()

    def _live_account(self, snapshot: dict | None) -> AccountSummary | None:
        account = snapshot.get("account") if snapshot else None
        if account is None:
            return None
        if account.account_id == "DRY-RUN":
            initial = float(
                load_live_settings().get("runtime", {}).get("default_equity", 1_000_000.0)
            )
            day_pnl = round(account.balance - initial, 2)
            return AccountSummary(
                currency="干跑",
                source="dry_run",
                total_equity=round(account.balance, 2),
                cash=round(account.available, 2),
                buying_power=round(account.available, 2),
                day_pnl=day_pnl,
                day_pnl_pct=round(day_pnl / initial * 100, 2) if initial else 0.0,
                max_daily_loss_pct=self.account.max_daily_loss_pct,
            )
        day_pnl = round(float(account.day_pnl), 2)
        baseline = float(account.balance) - float(account.day_pnl)
        return AccountSummary(
            currency="HKD/USD",
            source="broker",
            total_equity=round(account.balance, 2),
            cash=round(account.available, 2),
            buying_power=round(account.available, 2),
            day_pnl=day_pnl,
            day_pnl_pct=round(day_pnl / baseline * 100, 2) if baseline else 0.0,
            max_daily_loss_pct=self.account.max_daily_loss_pct,
        )

    def _dashboard_account(self, snapshot: dict | None) -> AccountSummary:
        live_account = self._live_account(snapshot)
        if live_account is not None:
            return live_account

        runtime = load_live_settings().get("runtime", {})
        if bool(runtime.get("dry_run", True)):
            equity = round(float(runtime.get("default_equity", 1_000_000.0)), 2)
            return AccountSummary(
                currency="干跑",
                source="dry_run",
                total_equity=equity,
                cash=equity,
                buying_power=equity,
                day_pnl=0.0,
                day_pnl_pct=0.0,
                max_daily_loss_pct=self.account.max_daily_loss_pct,
            )

        return AccountSummary(
            currency="券商未返回",
            source="broker",
            total_equity=0.0,
            cash=0.0,
            buying_power=0.0,
            day_pnl=0.0,
            day_pnl_pct=0.0,
            max_daily_loss_pct=self.account.max_daily_loss_pct,
        )

    def _live_positions(self, snapshot: dict | None) -> list[Position]:
        if not snapshot:
            return []
        ticks = {tick.symbol: tick for tick in snapshot.get("ticks", [])}
        strategy_by_symbol = self._strategy_by_symbol()
        positions: list[Position] = []
        for item in snapshot.get("positions", []):
            quantity = int(item.volume)
            avg_price = float(item.price)
            tick = ticks.get(item.symbol)
            last_price = float(tick.last_price) if tick is not None and tick.last_price > 0 else avg_price
            market_value = round(quantity * last_price, 2)
            basis = quantity * avg_price
            pnl = round(float(item.pnl) if item.pnl else market_value - basis, 2)
            pnl_pct = round(pnl / basis * 100, 2) if basis > 0 else 0.0
            positions.append(
                Position(
                    symbol=item.symbol,
                    name=item.symbol,
                    market=_market_from_symbol(item.symbol),
                    strategy_id=strategy_by_symbol.get(_symbol_key(item.symbol), "live"),
                    side=_side_from_direction(item.direction),
                    quantity=quantity,
                    avg_price=avg_price,
                    last_price=last_price,
                    market_value=market_value,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    holding_days=0,
                )
            )
        return positions

    def _live_orders(self, snapshot: dict | None) -> list[Order]:
        if not snapshot:
            return []
        return [
            Order(
                id=item.order_id,
                strategy_id="live",
                symbol=item.symbol,
                market=_market_from_symbol(item.symbol),
                side=_order_side(item.direction, item.offset),
                quantity=int(item.volume),
                price=float(item.price),
                status=_order_status(item.status),
                created_at=self._now(),
            )
            for item in snapshot.get("orders", [])
        ]

    def _live_trades(self, snapshot: dict | None) -> list[Trade]:
        if not snapshot:
            return []
        trades: list[Trade] = []
        for item in snapshot.get("trades", []):
            traded_at = _parse_live_time(item.time, self._now())
            trades.append(
                Trade(
                    id=item.trade_id or f"{item.order_id}:{item.symbol}",
                    order_id=item.order_id,
                    symbol=item.symbol,
                    market=_market_from_symbol(item.symbol),
                    side=_order_side(item.direction, item.offset),
                    quantity=int(item.volume),
                    price=float(item.price),
                    traded_at=traded_at,
                )
            )
        return trades

    def _current_db_path(self):
        if self.db_path is not None:
            return self.db_path
        return live_db_path_for_mode(load_live_settings())

    def trade_history(self, limit: int = 200) -> list[Trade]:
        events = list_live_events(kind="trade", db_path=self._current_db_path(), limit=limit)
        trades: list[Trade] = []
        for event in events:
            payload = event.payload or {}
            symbol = str(payload.get("symbol", event.symbol or ""))
            if not symbol:
                continue
            order_id = str(payload.get("order_id", ""))
            trades.append(
                Trade(
                    id=str(payload.get("trade_id") or f"{order_id}:{symbol}"),
                    order_id=order_id,
                    symbol=symbol,
                    market=_market_from_symbol(symbol),
                    side=_order_side(
                        str(payload.get("direction", "")), str(payload.get("offset", ""))
                    ),
                    quantity=int(payload.get("volume", 0)),
                    price=float(payload.get("price", 0.0)),
                    traded_at=_parse_live_time(str(payload.get("time", "")), self._now()),
                )
            )
        return trades

    def _live_watchlist(self) -> list[WatchSymbol]:
        names = {_symbol_key(info.symbol): info.name for info in all_symbols()}
        selection_events = list_live_events(kind="selection", limit=100, db_path=self._current_db_path())
        current_intraday_mode = str(
            load_live_settings().get("intraday_universe", {}).get("selection_mode", "auto")
        )
        latest_selections = {}
        for event in selection_events:
            if event.strategy_id not in latest_selections:
                latest_selections[event.strategy_id] = event
        active_selections = [
            event
            for event in latest_selections.values()
            if event.strategy_id != "intraday_macd"
            or str((event.payload or {}).get("selection_mode", "auto")) == current_intraday_mode
        ]
        active_keys = {
            _symbol_key(str(symbol))
            for event in active_selections
            for symbol in (event.payload or {}).get("symbols", [])
        }
        for event in active_selections:
            event_names = (event.payload or {}).get("names", {})
            if isinstance(event_names, dict):
                names.update({_symbol_key(str(symbol)): str(name) for symbol, name in event_names.items()})
        rows: list[WatchSymbol] = []
        seen: set[str] = set()
        signal_events = list_live_events(kind="signal", limit=100, db_path=self._current_db_path())
        latest_signals = {}
        triggered_today: set[str] = set()
        today = self._now().astimezone(_SERVER_TZ).date()
        for event in signal_events:
            if event.strategy_id not in {"intraday_macd", "trend_portfolio"}:
                continue
            symbol = event.symbol or ""
            if not symbol:
                continue
            key = _symbol_key(symbol)
            if selection_events and key not in active_keys:
                continue
            latest_signals.setdefault(key, event)
            payload = event.payload or {}
            event_day = event.created_at.astimezone(_SERVER_TZ).date()
            if event_day == today and bool(payload.get("submitted", False)):
                triggered_today.add(key)

        for key, event in latest_signals.items():
            symbol = event.symbol or ""
            seen.add(key)
            payload = event.payload or {}
            bd = score_for_symbol(
                _score_inputs_for_signal(event, self._now()),
                half_life_hours=self.params.intraday.score_half_life_hours,
                shortable=_is_shortable(symbol),
                shortable_bonus_pts=self.params.intraday.shortable_bonus_pts,
            )
            rows.append(
                WatchSymbol(
                    symbol=symbol,
                    name=names.get(key, symbol),
                    market=_market_from_symbol(symbol),
                    last_price=0.0,
                    change_pct=0.0,
                    turnover=0.0,
                    score=bd.total,
                    tags=list(payload.get("reasons", [])),
                    updated_at=event.created_at,
                    triggered=key in triggered_today,
                    score_breakdown={
                        "consistency": round(bd.consistency, 4),
                        "volume_ratio": round(bd.volume_ratio, 4),
                        "atr_quality": round(bd.atr_quality, 4),
                        "trend_filter": round(bd.trend_filter, 4),
                        "liquidity_rank": round(bd.liquidity_rank, 4),
                        "weighted": round(bd.weighted, 4),
                    },
                    freshness=round(bd.freshness, 4),
                    shortable=bd.shortable_bonus > 0,
                )
            )
        for event in active_selections:
            payload = event.payload or {}
            for raw_symbol in payload.get("symbols", []):
                symbol = str(raw_symbol)
                key = _symbol_key(symbol)
                if not symbol or key in seen:
                    continue
                seen.add(key)
                market = _market_from_symbol(symbol)
                bd = score_for_symbol(
                    _score_inputs_for_selection(event, symbol, market, self._now()),
                    half_life_hours=self.params.intraday.score_half_life_hours,
                    shortable=_is_shortable(symbol),
                    shortable_bonus_pts=self.params.intraday.shortable_bonus_pts,
                )
                rows.append(
                    WatchSymbol(
                        symbol=symbol,
                        name=names.get(key, symbol),
                        market=market,
                        last_price=0.0,
                        change_pct=0.0,
                        turnover=0.0,
                        score=bd.total,
                        tags=_selection_tags(
                            event.strategy_id,
                            str(payload.get("selection_mode", "auto")),
                        ),
                        updated_at=event.created_at,
                        triggered=False,
                        score_breakdown={
                            "consistency": round(bd.consistency, 4),
                            "volume_ratio": round(bd.volume_ratio, 4),
                            "atr_quality": round(bd.atr_quality, 4),
                            "trend_filter": round(bd.trend_filter, 4),
                            "liquidity_rank": round(bd.liquidity_rank, 4),
                            "weighted": round(bd.weighted, 4),
                        },
                        freshness=round(bd.freshness, 4),
                        shortable=bd.shortable_bonus > 0,
                    )
                )
        return rows

    def _strategy_by_symbol(self) -> dict[str, str]:
        strategies: dict[str, str] = {}
        for event in list_live_events(kind="signal", limit=100, db_path=self._current_db_path()):
            payload = event.payload or {}
            if event.strategy_id not in {"intraday_macd", "trend_portfolio"}:
                continue
            if not event.symbol or not bool(payload.get("submitted", False)):
                continue
            strategies.setdefault(_symbol_key(event.symbol), event.strategy_id)
        return strategies

    def _live_signals(self) -> list[Signal]:
        events = list_live_events(kind="signal", db_path=self._current_db_path())
        signals: list[Signal] = []
        for event in events:
            symbol = event.symbol or ""
            if not symbol:
                continue
            payload = event.payload or {}
            submitted = bool(payload.get("submitted", False))
            reasons = list(payload.get("reasons", []))
            signals.append(
                Signal(
                    id=event.id,
                    strategy_id=event.strategy_id,
                    symbol=symbol,
                    market=_market_from_symbol(symbol),
                    side="long",
                    confidence=0.8 if submitted else 0.5,
                    reason=" / ".join(reasons) if reasons else "等待信号",
                    created_at=event.created_at,
                    status="executed" if submitted else "new",
                )
            )
        return signals

    def _live_logs(self, snapshot: dict | None) -> list[TradeLog]:
        if snapshot is None:
            return []
        connected = bool(snapshot.get("connected"))
        detail = str(snapshot.get("detail", "")) or ("富途已连接" if connected else "富途未连接")
        return [
            TradeLog(
                id="LIVE-GATEWAY",
                time=self._now(),
                source="gateway",
                severity="info" if connected else "warning",
                message=detail,
            )
        ]


def _market_from_symbol(symbol: str) -> str:
    value = symbol.upper()
    if value.endswith(".HK") or value.startswith("HK.") or value.isdigit():
        return "HK"
    return "US"


def _symbol_key(symbol: str) -> str:
    value = symbol.strip().upper()
    for prefix in ("HK.", "US."):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    for suffix in (".HK", ".US"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    if value.isdigit():
        return value.lstrip("0") or "0"
    return value


def _selection_tags(strategy_id: str, selection_mode: str = "auto") -> list[str]:
    if strategy_id == "trend_portfolio":
        return ["月末选股", "候选持仓"]
    if selection_mode == "manual":
        return ["手动选股", "等待 MACD 开仓信号"]
    return ["盘前筛选", "等待 15m 收线确认"]


def _side_from_direction(direction: str) -> str:
    value = direction.upper()
    return "short" if "空" in direction or "SHORT" in value else "long"


def _order_side(direction: str, offset: str) -> str:
    is_short_direction = _side_from_direction(direction) == "short"
    is_close = "平" in offset or "CLOSE" in offset.upper()
    if is_close and is_short_direction:
        return "sell"
    if is_close:
        return "cover"
    return "short" if is_short_direction else "buy"


def _order_status(status: str) -> str:
    value = status.upper()
    if "拒" in status or "REJECT" in value:
        return "rejected"
    if "撤" in status or "CANCEL" in value:
        return "cancelled"
    if "成交" in status or "FILLED" in value or "ALLTRADED" in value:
        return "filled"
    return "submitted"


def _parse_live_time(value: str, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed

