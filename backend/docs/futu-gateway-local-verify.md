# 富途网关本地验证清单

前置条件:
- 已安装 vnpy + vnpy_futu（`pip install vnpy>=3.9.0 vnpy_futu>=1.0.0`）
- FutuOpenD 已登录并开通模拟交易；`get_acc_list()` 能返回 SIMULATE 账户
- backend 项目根已加入 PYTHONPATH（或 `pip install -e .`）

环境变量（模拟盘示例）:

```bash
export FUTU_HOST=127.0.0.1
export FUTU_PORT=11111
export FUTU_TRD_ENV=SIMULATE
export FUTU_MARKET=HK
```

## 逐项确认

- [ ] **连接**:`FutuLiveGateway(config, state).connect()` 不抛异常，`state.is_connected()` 为 `True`

- [ ] **账户推送**:连接后短时内收到 `EVENT_ACCOUNT`，`state.snapshot()["account"]` 非空且 `balance` 数值合理

- [ ] **行情订阅**:`subscribe(["00700"])` 后收到 `EVENT_TICK`，`state.snapshot()["ticks"]` 中有 `00700` 条目且 `last_price > 0`

- [ ] **下单**:`send_order("00700", "多", "开", <现价>, 100)` 返回非空 `vt_orderid`；随后收到 `EVENT_ORDER`，`state.snapshot()["orders"]` 中出现该订单

- [ ] **持仓**:若账户有持仓，`EVENT_POSITION` 推送后 `state.snapshot()["positions"]` 正确；volume 归零时对应 key 自动移除

- [ ] **字段一致性**:确认 `translate.py` 中 `order_from_vnpy` / `tick_from_vnpy` 等对 vnpy 真实对象字段的 `getattr` 取值不为空（`balance`/`frozen`/`accountid`/`orderid`/`symbol`/`last_price`/`datetime` 等）；如有差异在 `translate.py` 集中修正并补单测

- [ ] **成交回报**:触发一笔成交后，`EVENT_TRADE` 数据对象含 `orderid` 字段，`_on_trade` 能正确调用 `order_from_vnpy`；若 `TradeData` 缺少 `orderid`，需在 `translate.py` 新增 `trade_from_vnpy` 并更新 `gateway._on_trade`

- [ ] **Exchange 映射**:港股 `Exchange.SEHK` 有效；如需测试美股，确认 `vnpy_futu` 支持的 Exchange 值（`NASDAQ`/`NYSE`/`SMART`），在 `subscribe`/`send_order` 按 symbol 前缀分支补全

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

gw.subscribe(["00700"])
time.sleep(3)  # 等待 tick 推送
print("ticks:", state.snapshot()["ticks"])

# gw.send_order("00700", "多", "开", 100.0, 100)
# time.sleep(2)
# print("orders:", state.snapshot()["orders"])

gw.close()
print("connected after close:", state.is_connected())
```

## 开放项（Plan C/D 细化时处理）

- 多市场 Exchange 映射：港股 SEHK / 美股 NASDAQ/NYSE/SMART，按 `config.market` 或 symbol 前缀路由
- `TradeData` 字段与 `OrderData` 差异：若 `EVENT_TRADE` 需独立转换，新增 `trade_from_vnpy` 函数
- `vnpy_futu` connect setting 键名（`"市场"` 等中文键）：以实际 `FutuGateway.default_setting` 为准
- 行情类型（实时 / 摆盘 / 逐笔）订阅参数：`SubscribeRequest` 可能有额外字段
