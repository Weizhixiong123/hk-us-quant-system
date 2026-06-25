# Task 2 Report: risk 熔断拦截 + runtime 接入真实 daily_loss/熔断

## Status
DONE — all tests green, committed.

## Commit
- SHA: f619f2c
- Subject: `feat(live): 接入真实当日亏损与熔断闩锁拦截开仓`

## TDD Evidence

### RED (before implementation)
Command: `.venv/bin/python -m pytest tests/quant/live/test_risk.py tests/quant/live/test_runtime.py -q`

Output:
```
FAILED tests/quant/live/test_risk.py::test_live_risk_blocks_open_when_account_halted
  TypeError: evaluate_live_order_risk() got an unexpected keyword argument 'account_halted'
FAILED tests/quant/live/test_risk.py::test_live_risk_halt_does_not_block_close
  TypeError: evaluate_live_order_risk() got an unexpected keyword argument 'account_halted'
FAILED tests/quant/live/test_runtime.py::test_run_once_trips_halt_on_daily_loss
  assert False is True  (is_halted() returned False — _observe_account not yet wired)
3 failed, 12 passed
```

### GREEN (after implementation)
Command: `.venv/bin/python -m pytest tests/quant/live/test_risk.py tests/quant/live/test_runtime.py -q`

Output:
```
15 passed in 1.17s
```

### Full suite
Command: `.venv/bin/python -m pytest -q`

Output:
```
134 passed in 1.85s
```

## Files Changed

### `backend/quant/live/risk.py`
- Added `account_halted: bool = False` parameter to `evaluate_live_order_risk`
- Inside `if purpose == "open"` block: added check `if account_halted: blocks.append("已触发当日熔断，停止开仓")`
- Does NOT block `purpose == "close"` (close path untouched)

### `backend/quant/live/runtime.py`
- Added `max_daily_loss_pct: float = 3.0` to `RuntimeConfig` dataclass
- Added `_observe_account(self, snapshot, at)` helper: reads `account.balance`, calls `observe_account_equity` then `trip_halt_if_breached`
- In `run_once`: inserted `self._observe_account(snapshot, at)` before `persist_gateway_snapshot`
- In `_run_intraday_entries`: replaced `daily_loss_pct=0.0` with `daily_loss_pct=self.runtime_state.daily_loss_pct(_account_equity(snapshot, self.config.default_equity))`
- In `_live_risk`: replaced `daily_loss_pct=0.0` with real value, added `account_halted=self.runtime_state.is_halted()`

### `backend/tests/quant/live/test_risk.py`
- Added `test_live_risk_blocks_open_when_account_halted`
- Added `test_live_risk_halt_does_not_block_close`

### `backend/tests/quant/live/test_runtime.py`
- Added `test_run_once_trips_halt_on_daily_loss`: sets baseline 1000, drops account to 950 (5% loss > 3% threshold), asserts `is_halted() is True`

## Self-Review

- [x] `account_halted=True` blocks open (reason contains "熔断")
- [x] `account_halted=True` does NOT block close (test_live_risk_halt_does_not_block_close passes)
- [x] `run_once` calls `_observe_account` each cycle
- [x] `_observe_account` calls both `observe_account_equity` and `trip_halt_if_breached`
- [x] Both hardcoded `daily_loss_pct=0.0` replaced with `self.runtime_state.daily_loss_pct(balance)` (in `_run_intraday_entries` and `_live_risk`)
- [x] `_live_risk` passes `account_halted=self.runtime_state.is_halted()`
- [x] run_once test trips halt when balance drops to 950 from 1000 baseline (5% loss > 3% threshold)
- [x] Pre-existing 3 runtime entry/exit tests green (daily_loss_pct=0.0 when no account baseline, behavior unchanged)
- [x] Full suite: 134 passed

## Concerns
None. Implementation matches brief exactly. Pre-existing tests unaffected because `daily_loss_pct(balance)` returns 0.0 when `day_start_equity` is None (no baseline set), preserving existing behavior.
