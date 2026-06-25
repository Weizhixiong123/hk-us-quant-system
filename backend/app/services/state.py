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
from quant.live.params import LiveParams
from quant.live.settings import load_live_settings
from quant.live.state import LiveGatewayState


class AppState:
    def __init__(self, live_state: LiveGatewayState | None = None, params: LiveParams | None = None) -> None:
        self.params = params or LiveParams()
        self._lock = RLock()
        self._rng = random.Random(42)
        self.live_state = live_state
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
                    "fast_ema": 12,
                    "slow_ema": 26,
                    "signal_ema": 9,
                    "stop_loss_pct": 1.5,
                    "take_profit_1_pct": 2.0,
                    "take_profit_2_pct": 3.5,
                    "position_fraction_pct": 10.0,
                    "max_positions": 3,
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
            return DashboardSnapshot(
                server_time=self._now(),
                account=self._dashboard_account(live_snapshot),
                risk=self.risk_status(live_snapshot),
                strategies=self.strategies,
                positions=self._live_positions(live_snapshot) or self.positions,
                watchlist=self.watchlist,
                signals=self.signals,
                orders=self._live_orders(live_snapshot) or self.orders,
                trades=self._live_trades(live_snapshot) or self.trades,
                logs=self._live_logs(live_snapshot) + self.logs,
                chart=self.chart,
            )

    def risk_status(self, live_snapshot: dict | None = None) -> list[RiskRuleStatus]:
        intraday_positions = sum(
            1 for position in self.positions if position.strategy_id == "intraday_macd"
        )
        live_snapshot = live_snapshot if live_snapshot is not None else self._live_snapshot()
        account = self._dashboard_account(live_snapshot)
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
                status="pass" if account.day_pnl_pct > -3 else "blocked",
                detail=f"当前 {account.day_pnl_pct:.2f}%，阈值 -3.00%",
            ),
            RiskRuleStatus(
                code="intraday_position_count",
                name="日内持仓数量",
                status="watch" if intraday_positions >= 2 else "pass",
                detail=f"{intraday_positions}/3",
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
        return live_positions or self.positions

    def current_orders(self) -> list[Order]:
        live_orders = self._live_orders(self._live_snapshot())
        return live_orders or self.orders

    def current_trades(self) -> list[Trade]:
        live_trades = self._live_trades(self._live_snapshot())
        return live_trades or self.trades

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
            strategy.params.update(params)
            strategy.updated_at = self._now()
            self._append_log(
                source=strategy_id,
                severity="info",
                message=f"{strategy.name} 参数已更新：{', '.join(params.keys())}",
            )
            self.params.update(strategy_id, params)
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
        return AccountSummary(
            currency="HKD/USD",
            source="broker",
            total_equity=round(account.balance, 2),
            cash=round(account.available, 2),
            buying_power=round(account.available, 2),
            day_pnl=0.0,
            day_pnl_pct=0.0,
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
                currency="DRY-RUN",
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
                    strategy_id="live",
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

