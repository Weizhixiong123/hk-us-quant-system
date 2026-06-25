# 后端服务

FastAPI 后端负责对前端暴露 REST 与 WebSocket，并把策略、风控、日志、回测和券商网关隔离成独立模块。

## 本地启动

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## 实盘运行时

默认启动后只提供 API，不自动连接券商。需要后台运行时串起券商、调度、策略和执行器时，设置：

```bash
set LIVE_RUNTIME_ENABLED=1
set LIVE_RUNTIME_DRY_RUN=1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`LIVE_RUNTIME_DRY_RUN=1` 会走本地 dry-run 网关，只写订单、成交、持仓和日志状态，不触达券商。联调富途模拟盘/实盘时改为：

```bash
set LIVE_RUNTIME_BROKER=futu
set LIVE_RUNTIME_DRY_RUN=0
set FUTU_TRD_ENV=SIMULATE
```

正式账户还必须额外设置 `FUTU_REAL_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY_RISK`，否则代码会拒绝启动 REAL 交易环境。

联调老虎 sandbox/live 时使用：

```bash
python -m pip install git+https://github.com/weijiaxing/vnpy_tiger.git
set LIVE_RUNTIME_BROKER=tiger
set LIVE_RUNTIME_DRY_RUN=0
set TIGER_ENVIRONMENT=sandbox
set TIGER_ID=你的开发者ID
set TIGER_ACCOUNT=你的账户号
set TIGER_PRIVATE_KEY_PATH=你的私钥文件路径
```

也可以用 `TIGER_PRIVATE_KEY` 直接传私钥内容。正式老虎账户还必须额外设置 `TIGER_LIVE_TRADING_CONFIRM=I_UNDERSTAND_TIGER_REAL_MONEY_RISK`，否则代码会拒绝启动 live 交易环境。

注意：`vnpy_tiger` 仓库声明依赖 `vnpy>=4.0.0`、`tigeropen>=2.0.0`；如果本机富途环境仍固定在旧版 vn.py，建议为老虎单独建虚拟环境验证。

## 当前边界

- `app/api`: 前端调用的 REST/WS 接口
- `app/services`: Web 状态层，优先展示 live runtime 共享状态
- `app/strategies`: MACD 日内策略与中长线筛选的纯算法函数
- `quant/live`: 富途/老虎网关、运行时引擎、行情聚合、调度、风控、执行器、持久化

## 核心接口

- `GET /api/dashboard`: 控制台全量快照
- `GET /api/health`: 服务与 live runtime 状态
- `PATCH /api/strategies/{id}/toggle`: 策略独立开关
- `PUT /api/strategies/{id}/params`: 策略参数热更新入口
- `POST /api/backtests`: 回测任务入口
- `WS /api/ws/stream`: 控制台实时推送
