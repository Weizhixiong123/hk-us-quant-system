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
    Position,
    RiskRuleStatus,
    Signal,
    StrategyConfig,
    TradeLog,
    WatchSymbol,
)


class AppState:
    def __init__(self) -> None:
        self._lock = RLock()
        self._rng = random.Random(42)
        now = self._now()
        self.account = AccountSummary(
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
            return DashboardSnapshot(
                server_time=self._now(),
                account=self.account,
                risk=self.risk_status(),
                strategies=self.strategies,
                positions=self.positions,
                watchlist=self.watchlist,
                signals=self.signals,
                orders=self.orders,
                logs=self.logs,
                chart=self.chart,
            )

    def risk_status(self) -> list[RiskRuleStatus]:
        intraday_positions = sum(
            1 for position in self.positions if position.strategy_id == "intraday_macd"
        )
        return [
            RiskRuleStatus(
                code="daily_loss",
                name="单日最大亏损",
                status="pass" if self.account.day_pnl_pct > -3 else "blocked",
                detail=f"当前 {self.account.day_pnl_pct:.2f}%，阈值 -3.00%",
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
                detail="模拟环境剩余额度 3，实盘需接入账户权益校验。",
            ),
            RiskRuleStatus(
                code="shortable",
                name="做空校验",
                status="watch",
                detail="空头信号仅记录，等待券商可借券接口。",
            ),
        ]

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
            return strategy

    def run_backtest(self, request: BacktestRequest) -> BacktestResult:
        strategy = self._find_strategy(request.strategy_id)
        seed = sum(ord(char) for char in request.strategy_id + request.market)
        rng = random.Random(seed)
        if request.strategy_id == "intraday_macd":
            base_return, drawdown, sharpe, win_rate, trades = 8.6, 5.4, 1.18, 54.2, 312
            notes = [
                "使用模拟成交与固定滑点，暂不代表实盘收益。",
                "背离阈值与绿柱缩短根数仍需在参数优化阶段复核。",
            ]
        else:
            base_return, drawdown, sharpe, win_rate, trades = 18.4, 11.7, 1.42, 61.5, 42
            notes = [
                "月度调仓与分批建仓逻辑已纳入骨架。",
                "基本面数据源接入后需要替换当前筛选样例。",
            ]

        jitter = rng.uniform(-1.2, 1.2)
        self._append_log(
            source="backtest",
            severity="info",
            message=f"{strategy.name} {request.market} 回测任务已生成。",
        )
        return BacktestResult(
            id=f"BT-{uuid4().hex[:8].upper()}",
            strategy_id=request.strategy_id,
            market=request.market,
            start_date=request.start_date,
            end_date=request.end_date,
            total_return_pct=round(base_return + jitter, 2),
            max_drawdown_pct=round(drawdown + abs(jitter) / 2, 2),
            sharpe=round(sharpe + jitter / 10, 2),
            win_rate_pct=round(win_rate + jitter, 2),
            trades=trades + int(jitter * 7),
            notes=notes,
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


