# Docker Compose 部署

该方案把 Vue 前端构建产物和 FastAPI 后端放在同一个 `quant-app` 镜像中。FutuOpenD 继续由宿主机 systemd 管理。

## 启动

在仓库根目录执行：

```bash
cp deploy/docker/.env.example .env
docker compose build
docker compose up -d
docker compose ps
```

浏览器访问 `http://服务器IP:8000`。

## 连接 FutuOpenD

Compose 使用 Linux `host` 网络，因此容器内的 `127.0.0.1:11111`、`127.0.0.1:11112` 就是宿主机上的 OpenD。OpenD 可以继续只监听本机，不需要向公网开放端口。

在 Web 设置页添加账户，例如：

- 港股账户：`127.0.0.1:11111`
- 美股账户：`127.0.0.1:11112`

## 常用命令

```bash
docker compose logs -f quant-app
docker compose restart quant-app
docker compose up -d --build
docker compose down
```

配置、SQLite 数据和运行状态保存在 Docker 卷 `hk-us-quant-data`。`docker compose down` 不会删除该卷；不要使用 `docker compose down -v`，除非明确需要清空全部运行数据。

如果只运行干跑、不连接真实券商，可以在 `.env` 中设置 `INSTALL_BROKER_DEPS=0`，以减小镜像体积。
