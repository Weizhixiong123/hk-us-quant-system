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
5. 安装 vnpy 与 `vnpy_futu`，设置 `LIVE_RUNTIME_BROKER=futu`、`LIVE_RUNTIME_DRY_RUN=0` 后启动后端。

### 老虎

1. 完成老虎开发者认证。
2. 获取 `tiger_id`、RSA 私钥和 Paper 模拟账户号。
3. 安装 `vnpy_tiger`，当前 pip 源找不到时可用 `pip install git+https://github.com/weijiaxing/vnpy_tiger.git`。
4. 设置 `LIVE_RUNTIME_BROKER=tiger`、`LIVE_RUNTIME_DRY_RUN=0` 后启动后端。
5. sandbox 使用 `TIGER_ENVIRONMENT=sandbox`；live 还需要 `TIGER_LIVE_TRADING_CONFIRM=I_UNDERSTAND_TIGER_REAL_MONEY_RISK`。

## 3. Windows 本地单机部署包

在开发机上生成客户可运行的本地目录包：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\build-package.ps1
```

生成结果：

```text
release\hk-us-quant-client\
```

手动压缩该目录后即可发送给客户。客户解压后双击 `start.bat`，浏览器访问 `http://127.0.0.1:8000`。如果客户机器上的内置运行时不可用，可双击 `repair-runtime.bat` 重建依赖。

## 4. Ubuntu 服务器部署

仓库提供了 `deploy/linux` 下的 systemd、Nginx 和配置示例。以下路径与服务文件中的默认值一致。

### 4.1 安装应用

```bash
sudo useradd --system --create-home --home-dir /var/lib/hk-us-quant --shell /usr/sbin/nologin quant
sudo mkdir -p /opt/hk-us-quant-system /opt/futu-opend /etc/hk-us-quant /var/lib/hk-us-quant
sudo chown -R quant:quant /opt/hk-us-quant-system /opt/futu-opend /var/lib/hk-us-quant
```

把仓库放到 `/opt/hk-us-quant-system` 后安装并构建：

```bash
cd /opt/hk-us-quant-system/backend
sudo -u quant python3 -m venv .venv
sudo -u quant .venv/bin/python -m pip install -r requirements.txt
sudo -u quant .venv/bin/python -m pip install -r requirements-broker.txt

cd /opt/hk-us-quant-system/frontend
sudo -u quant npm ci
sudo -u quant npm run build
```

`requirements-broker.txt` 已固定项目验证过的官方 `vnpy_futu` GitHub 版本。

### 4.2 为每个富途登录账号准备 OpenD

每个登录账号使用独立目录和端口，例如：

```text
/opt/futu-opend/hk_main/FutuOpenD.xml  -> api_port 11111
/opt/futu-opend/us_main/FutuOpenD.xml  -> api_port 11112
```

每个目录都必须保留完整官方命令行包，包括 `FutuOpenD`、`FutuOpenD.xml` 和 `Appdata.dat`。首次登录先以前台方式运行，并完成手机/设备验证码：

```bash
sudo -u quant -H /opt/futu-opend/hk_main/FutuOpenD \
  -cfg_file=/opt/futu-opend/hk_main/FutuOpenD.xml -console=1
```

需要验证时，在 OpenD 控制台执行：

```text
req_phone_verify_code
input_phone_verify_code -code=收到的验证码
```

对每个账号分别完成一次。不要删除 `/var/lib/hk-us-quant/.com.futunn.FutuOpenD` 下的设备数据。

### 4.3 配置账户和市场路由

```bash
sudo cp deploy/linux/backend.env.example /etc/hk-us-quant/backend.env
sudo cp deploy/linux/live-settings.example.json /var/lib/hk-us-quant/live-settings.json
sudo chown quant:quant /var/lib/hk-us-quant/live-settings.json
sudo chmod 600 /etc/hk-us-quant/backend.env /var/lib/hk-us-quant/live-settings.json
```

`futu.accounts` 可以添加多个 OpenD；`futu.market_accounts` 决定港股、美股订单分别发往哪个账户。也可以启动 Web 后在“运行设置 → 富途账户与 OpenD”中新增、删除或切换执行账户。

同一市场当前只选择一个执行账户，系统不会在多个账户之间自动拆单或分配资金。

### 4.4 启动服务

```bash
sudo cp deploy/linux/futu-opend@.service /etc/systemd/system/
sudo cp deploy/linux/hk-us-quant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now futu-opend@hk_main futu-opend@us_main
sudo systemctl enable --now hk-us-quant
```

查看状态：

```bash
systemctl status futu-opend@hk_main futu-opend@us_main hk-us-quant
journalctl -u hk-us-quant -f
curl http://127.0.0.1:8000/api/health
```

安装 Nginx 反代：

```bash
sudo apt-get install -y nginx apache2-utils
sudo install -d -m 750 /etc/hk-us-quant/tls
sudo htpasswd -cB /etc/nginx/hk-us-quant.htpasswd quantadmin
sudo chown root:www-data /etc/nginx/hk-us-quant.htpasswd
sudo chmod 640 /etc/nginx/hk-us-quant.htpasswd
sudo cp deploy/linux/nginx-hk-us-quant.conf /etc/nginx/sites-available/hk-us-quant
sudo sed -i 's/YOUR_DOMAIN/quant.example.com/g' /etc/nginx/sites-available/hk-us-quant
sudo ln -s /etc/nginx/sites-available/hk-us-quant /etc/nginx/sites-enabled/hk-us-quant
sudo nginx -t
sudo systemctl reload nginx
```

执行前将 `quant.example.com` 替换为真实域名，并将该域名的证书安装为
`/etc/hk-us-quant/tls/fullchain.pem`、私钥安装为 `/etc/hk-us-quant/tls/privkey.pem`。
配置自带 HTTPS、HTTP 跳转 HTTPS 和单用户 Basic Auth。仅通过安全组和防火墙开放 Nginx 的
80/443；OpenD 的 `11111`、`11112` 和 Telnet 运维端口不得暴露到公网。

### 4.5 使用 Docker Compose 部署应用

如果希望容器化前端和后端，可以在仓库根目录直接执行：

```bash
cp deploy/docker/.env.example .env
docker compose build
docker compose up -d
docker compose ps
```

若使用 Docker Hub 私有镜像，在服务器 `.env` 中设置
`IMAGE_REPOSITORY=你的用户名/hk-us-quant-system`，完成 `sudo docker login` 后执行：

```bash
sudo docker compose pull quant-app
sudo docker compose up -d --no-build --pull never quant-app
```

本机发布脚本为 `deploy/docker/publish-image.ps1`；服务器带备份、健康检查和失败回滚的更新脚本为
`deploy/linux/update-docker-image.sh`。具体命令见 `deploy/docker/README.md`。

镜像采用多阶段构建：Node 阶段生成 Vue 的 `frontend/dist`，最终 Python 镜像由 FastAPI 同时提供页面、API 和 WebSocket。运行数据保存在命名卷 `hk-us-quant-data`。

Compose 使用 Linux `host` 网络，使容器可以通过 `127.0.0.1:11111`、`127.0.0.1:11112` 连接宿主机 OpenD，同时 OpenD 仍可只监听本机。该配置用于 Ubuntu/Linux 服务器，不以 Docker Desktop 作为生产运行环境。

FutuOpenD 不放进 Compose，仍使用前述 `futu-opend@.service` 管理。Compose 模式下，Uvicorn
只监听宿主机 `127.0.0.1:8000`。备份和无覆盖恢复命令见 `deploy/docker/README.md`，对应脚本为
`deploy/linux/backup-docker-volume.sh` 和 `deploy/linux/restore-docker-volume.sh`。

## 5. 上线检查

- 确认策略一美股账户满足 PDT 要求：保证金账户且净值不低于 25,000 美元。
- 确认空头交易只对券商返回可做空/可借券标的开放。
- 模拟盘至少跑完一个完整交易日，核对开仓、止损、止盈、尾盘清仓和日志。
- 小资金实盘前，必须复核滑点、成交费用、最小交易单位和交易时段。
