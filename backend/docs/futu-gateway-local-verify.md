# 富途网关本地验证清单

前置条件:
- 已安装 vnpy + vnpy_futu（`pip install vnpy>=3.9.0 vnpy_futu>=1.0.0`）
- FutuOpenD 已登录；模拟盘需能返回 SIMULATE 账户，正式账户需确认交易权限和账户状态
- backend 项目根已加入 PYTHONPATH（或 `pip install -e .`）

环境变量（模拟盘示例）:

```bash
export FUTU_HOST=127.0.0.1
export FUTU_PORT=11111
export FUTU_TRD_ENV=SIMULATE
export FUTU_MARKET=HK
```

环境变量（正式账户示例）:

```bash
export FUTU_HOST=127.0.0.1
export FUTU_PORT=11111
export FUTU_TRD_ENV=REAL
export FUTU_MARKET=HK
export FUTU_REAL_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY_RISK
```

正式账户会产生真实资金风险；代码层要求 `FUTU_REAL_TRADING_CONFIRM` 精确匹配上面的值，避免误把模拟盘切成实盘。

## 逐项确认

- [ ] **连接**:`FutuLiveGateway(config, state).connect()` 不抛异常，连接后短时内收到 `EVENT_ACCOUNT`，`state.is_connected()` 为 `True`

- [ ] **账户推送**:`state.snapshot()["account"]` 非空，`balance` / `available` / `frozen` 数值合理

- [ ] **行情订阅**:`subscribe(["00700.HK"])` 或 `subscribe(["00700"])` 后收到 `EVENT_TICK`，`state.snapshot()["ticks"]` 中有 `00700` 条目且 `last_price > 0`

- [ ] **下单**:`send_order("00700.HK", "多", "开", <现价>, 100)` 返回非空 `vt_orderid`；随后收到 `EVENT_ORDER`，`state.snapshot()["orders"]` 中出现该订单

- [ ] **撤单**:对未成交订单调用 `cancel_order(<orderid>, "00700.HK")`，随后收到撤单/已撤状态的 `EVENT_ORDER`

- [ ] **成交回报**:触发一笔成交后收到 `EVENT_TRADE`，`state.snapshot()["trades"]` 出现成交，字段包含 `trade_id` / `order_id` / `price` / `volume` / `time`

- [ ] **持仓**:若账户有持仓，`EVENT_POSITION` 推送后 `state.snapshot()["positions"]` 正确；volume 归零时对应 key 自动移除

- [ ] **字段一致性**:确认 `translate.py` 中 `account_from_vnpy` / `position_from_vnpy` / `order_from_vnpy` / `trade_from_vnpy` / `tick_from_vnpy` 对真实 vnpy 对象字段取值不为空；如有差异在 `translate.py` 集中修正并补单测

- [ ] **Exchange 映射**:港股默认 `Exchange.SEHK` 有效；如需测试美股，确认 `vnpy_futu` 支持 `SMART` 或显式传入 `exchange="NASDAQ"` / `exchange="NYSE"`

- [ ] **断开**:`close()` 后 `state.is_connected()` 为 `False`，无残留线程报错

## 验证脚本片段

```python
import os
os.environ.setdefault("FUTU_HOST", "127.0.0.1")
os.environ.setdefault("FUTU_PORT", "11111")
os.environ.setdefault("FUTU_TRD_ENV", "SIMULATE")
os.environ.setdefault("FUTU_MARKET", "HK")

import time
from quant.live.config import load_futu_config
from quant.live.state import LiveGatewayState
from quant.live.gateway import FutuLiveGateway

config = load_futu_config()
state = LiveGatewayState()
gw = FutuLiveGateway(config, state)

gw.connect()
time.sleep(3)  # 等待账户推送
print("connected:", state.is_connected())
print("account:", state.snapshot()["account"])

gw.subscribe(["00700.HK"])
time.sleep(3)  # 等待 tick 推送
print("ticks:", state.snapshot()["ticks"])

# order_id = gw.send_order("00700.HK", "多", "开", 100.0, 100)
# time.sleep(2)
# print("orders:", state.snapshot()["orders"])
# gw.cancel_order(order_id, "00700.HK")
# time.sleep(2)
# print("orders after cancel:", state.snapshot()["orders"])
# print("trades:", state.snapshot()["trades"])

gw.close()
print("connected after close:", state.is_connected())
```

## 开放项（本地联调后按实际结果收口）

- `vnpy_futu` connect setting 键名（`"市场"` / `"host"` / `"port"` / `"trd_env"`）以实际 `FutuGateway.default_setting` 为准
- 美股交易所映射以 `vnpy_futu` 支持值为准；当前默认 `SMART`，可显式传 `NASDAQ` / `NYSE`
- 行情类型（实时 / 摆盘 / 逐笔）订阅参数：`SubscribeRequest` 可能有额外字段

