# 部署说明

## 1. 本地开发

后端使用 FastAPI，前端使用 Vite + Vue。开发阶段推荐分别启动：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

前端开发服务器会把 `/api` 和 `/api/ws/stream` 代理到 `127.0.0.1:8000`。

## 2. 模拟盘接入准备

### 富途

1. 安装并登录 FutuOpenD。
2. 确认账号开通 OpenAPI。
3. 在富途 App 开通模拟交易。
4. 确认 FutuOpenD 可以返回 `SIMULATE` 账户。
5. 安装 vnpy 与 `vnpy_futu`，把 `backend/app/gateways/futu.py` 替换为真实 vnpy 网关调用。

### 老虎

1. 完成老虎开发者认证。
2. 获取 `tiger_id`、RSA 私钥和 Paper 模拟账户号。
3. 安装 vnpy 与 `vnpy_tiger`，把 `backend/app/gateways/tiger.py` 替换为真实 vnpy 网关调用。

## 3. 生产部署建议

- 后端：`uvicorn app.main:app --host 0.0.0.0 --port 8000`，外层用 Nginx 或 Caddy 反代。
- 前端：`npm run build` 后部署 `frontend/dist` 静态文件。
- 配置：券商凭证只放服务器环境变量或密钥管理服务，不提交到仓库。
- 数据：订单、成交、日志、策略参数和回测结果需要接 SQLite/MySQL/PostgreSQL 持久化。
- 进程：FutuOpenD、后端 API、策略引擎、数据记录器应由 supervisor/systemd/PM2 等守护。

## 4. 上线检查

- 确认策略一美股账户满足 PDT 要求：保证金账户且净值不低于 25,000 美元。
- 确认空头交易只对券商返回可做空/可借券标的开放。
- 模拟盘至少跑完一个完整交易日，核对开仓、止损、止盈、尾盘清仓和日志。
- 小资金实盘前，必须复核滑点、成交费用、最小交易单位和交易时段。

