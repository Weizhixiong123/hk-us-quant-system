# 老虎网关本地验证清单

## 前置条件

- 已安装 `vnpy_tiger` 和老虎官方 `tigeropen` 依赖；当前 pip 源找不到时可用 `pip install git+https://github.com/weijiaxing/vnpy_tiger.git`
- `vnpy_tiger` 仓库声明依赖 `vnpy>=4.0.0`、`tigeropen>=2.0.0`
- 已获取 `TIGER_ID`、账户号和 RSA 私钥
- sandbox/live 账户已开通对应市场交易权限

## Sandbox

```bash
set LIVE_RUNTIME_ENABLED=1
set LIVE_RUNTIME_DRY_RUN=0
set LIVE_RUNTIME_BROKER=tiger
set TIGER_ENVIRONMENT=sandbox
set TIGER_ID=你的开发者ID
set TIGER_ACCOUNT=你的账户号
set TIGER_PRIVATE_KEY_PATH=你的私钥文件路径
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Live

```bash
set LIVE_RUNTIME_ENABLED=1
set LIVE_RUNTIME_DRY_RUN=0
set LIVE_RUNTIME_BROKER=tiger
set TIGER_ENVIRONMENT=live
set TIGER_ID=你的开发者ID
set TIGER_ACCOUNT=你的账户号
set TIGER_PRIVATE_KEY_PATH=你的私钥文件路径
set TIGER_LIVE_TRADING_CONFIRM=I_UNDERSTAND_TIGER_REAL_MONEY_RISK
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

live 会产生真实资金风险；代码层要求 `TIGER_LIVE_TRADING_CONFIRM` 精确匹配上面的值，避免误把 sandbox 切成实盘。

## 核对项

- [ ] `GET /api/health` 返回 `runtime_broker=tiger`、`runtime_dry_run=false`
- [ ] 网关连接后收到 `EVENT_ACCOUNT`，前端连接状态变为在线
- [ ] 候选池触发订阅后，`/api/dashboard` 能看到 tick 或 bar 推动的行情
- [ ] sandbox 小额限价单可以产生订单回报、成交回报和持仓更新
- [ ] 撤单路径可用，订单状态能写入 `/api/orders`
- [ ] 下单失败时连续失败计数增加，并能触发风控拦截
- [ ] live 前先完整跑完一个 sandbox 交易日，核对开仓、止盈、止损和清仓日志
