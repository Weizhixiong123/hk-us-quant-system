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

## 当前边界

- `app/api`: 前端调用的 REST/WS 接口
- `app/services`: 内存状态、模拟行情、回测任务、风控服务
- `app/strategies`: MACD 日内策略与中长线筛选的纯算法函数
- `app/gateways`: 富途/老虎适配边界，等待 vnpy 网关和客户凭证接入

## 核心接口

- `GET /api/dashboard`: 控制台全量快照
- `PATCH /api/strategies/{id}/toggle`: 策略独立开关
- `PUT /api/strategies/{id}/params`: 策略参数热更新入口
- `POST /api/backtests`: 回测任务入口
- `WS /api/ws/stream`: 控制台实时推送

