# 港美股双策略量化系统

基于方案文档搭建的前后端分离项目骨架，覆盖策略一“日内 MACD 全自动交易”和策略二“大级别中长线选股持仓”的控制台、接口、策略算法边界、风控和券商网关适配层。

## 项目结构

```text
backend/
  app/
    api/          FastAPI REST + WebSocket
    gateways/     富途/老虎/vnpy 网关适配边界
    models/       前后端共享响应模型
    services/     模拟状态、风控、回测任务
    strategies/   MACD 日内与中长线筛选算法函数
  tests/          纯算法与风控测试
frontend/
  src/
    api/          前端接口类型与请求封装
    components/   策略卡、K线图、持仓表、事件流
    composables/  控制台状态与 WebSocket 订阅
docs/
  deployment.md
  credentials-checklist.md
```

## 本地启动

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`。接口文档在 `http://127.0.0.1:8000/docs`。

## 当前实现范围

- 两套策略独立开关、独立参数入口
- 控制台展示账户、风控、持仓、候选池、信号、订单、日志
- WebSocket 推送模拟行情与账户快照
- MACD 计算、交叉、柱体缩短、背离识别的纯函数
- 中长线选股筛选纯函数
- 日内交易风控函数，包括日亏损、持仓数量、止损禁开、做空、PDT
- 实盘运行时支持按 `LIVE_RUNTIME_BROKER` 切换富途/老虎 vn.py 网关

## 后续接入顺序

1. 接入历史数据源，替换 `AppState` 中的模拟行情与候选池。
2. 配置富途 FutuOpenD 与老虎 tigeropen 凭证，先用模拟盘/sandbox 跑满完整交易日。
3. 增加回测报告导出与参数优化任务队列。
