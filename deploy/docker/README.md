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

Compose 只在宿主机 `127.0.0.1:8000` 监听。生产环境必须通过下文的 Nginx HTTPS
入口访问，不能把 8000 暴露到公网。

## Docker Hub 私有镜像

Docker Hub Personal 免费版可以创建一个私有仓库。先在 Docker Hub 创建：

```text
你的用户名/hk-us-quant-system
```

不要把 Docker Hub 密码或访问令牌写进 `.env`。在本机 PowerShell 中登录，密码位置建议输入
Docker Hub Access Token：

```powershell
docker login --username 你的DockerHub用户名
```

在仓库根目录构建并推送版本化镜像。脚本默认同时更新 `latest`：

```powershell
.\deploy\docker\publish-image.ps1 `
  -Repository 你的DockerHub用户名/hk-us-quant-system
```

如需指定版本：

```powershell
.\deploy\docker\publish-image.ps1 `
  -Repository 你的DockerHub用户名/hk-us-quant-system `
  -Tag 2026.07.17-1
```

服务器只需登录一次。以 root 运行更新脚本时，也应由 root 保存 Docker 登录凭据：

```bash
sudo docker login --username 你的DockerHub用户名
```

把服务器 `.env` 中的镜像配置改成：

```env
IMAGE_REPOSITORY=你的DockerHub用户名/hk-us-quant-system
IMAGE_TAG=latest
INSTALL_BROKER_DEPS=1
TZ=Asia/Shanghai
DATA_VOLUME_NAME=hk-us-quant-data
```

首次从仓库启动：

```bash
sudo docker compose pull quant-app
sudo docker compose up -d --no-build --pull never quant-app
sudo docker compose ps
```

以后本机推送新镜像后，服务器执行：

```bash
cd /www/wwwroot/hk-us-quant-system
sudo bash deploy/linux/update-docker-image.sh
```

更新脚本会比较镜像ID；没有新镜像时直接退出。有新镜像时先备份数据卷，再启动新镜像并等待
健康检查；健康检查失败会自动恢复旧镜像。量化交易系统不建议在交易时段无人值守更新。若确实
需要定时检查，应选择所有策略停止的维护窗口。示例为每周日北京时间 18:00 检查一次：

```bash
sudo crontab -e
```

加入：

```cron
CRON_TZ=Asia/Shanghai
0 18 * * 0 cd /www/wwwroot/hk-us-quant-system && bash deploy/linux/update-docker-image.sh >> /var/log/hk-us-quant-update.log 2>&1
```

定时任务使用 root 的 Docker Hub 登录凭据。推送紧急版本后，也可以手工运行更新脚本，不必等待
下一个维护窗口。

## 单用户认证与 HTTPS

准备一个已解析到服务器的域名，以及该域名的 TLS 证书。把证书和私钥安装到：

```text
/etc/hk-us-quant/tls/fullchain.pem
/etc/hk-us-quant/tls/privkey.pem
```

证书可以由云厂商或 Let's Encrypt 签发。私钥权限应限制为 root 可读，Nginx 主进程可加载。

安装 Basic Auth 工具并创建唯一管理员账号：

```bash
sudo apt-get update
sudo apt-get install -y nginx apache2-utils
sudo install -d -m 750 /etc/hk-us-quant/tls
sudo htpasswd -cB /etc/nginx/hk-us-quant.htpasswd quantadmin
sudo chown root:www-data /etc/nginx/hk-us-quant.htpasswd
sudo chmod 640 /etc/nginx/hk-us-quant.htpasswd
```

复制 Nginx 配置前，把 `YOUR_DOMAIN` 换成真实域名：

```bash
sudo cp deploy/linux/nginx-hk-us-quant.conf /etc/nginx/sites-available/hk-us-quant
sudo sed -i 's/YOUR_DOMAIN/quant.example.com/g' /etc/nginx/sites-available/hk-us-quant
sudo ln -s /etc/nginx/sites-available/hk-us-quant /etc/nginx/sites-enabled/hk-us-quant
sudo nginx -t
sudo systemctl reload nginx
```

将示例中的 `quant.example.com` 替换为真实域名。浏览器访问 `https://真实域名`，输入刚创建
的 `quantadmin` 账号和密码。认证覆盖页面、API 和 WebSocket。

云安全组和宿主机防火墙只需对公网开放 80/443；22 应尽量只允许管理员固定 IP。
8000、11111、11112 和 OpenD 运维端口均不得开放。FutuOpenD 的 `ip` 配置必须保持
`127.0.0.1`。

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
sudo bash deploy/linux/update-docker-image.sh
docker compose down
```

配置、SQLite 数据和运行状态保存在 Docker 卷 `hk-us-quant-data`。卷名可通过 `.env` 中的
`DATA_VOLUME_NAME` 调整。`docker compose down` 不会删除该卷；不要使用
`docker compose down -v`，除非明确需要清空全部运行数据。

## 备份与恢复

创建一致性备份：

```bash
sudo bash deploy/linux/backup-docker-volume.sh
```

默认写入 `/var/backups/hk-us-quant/hk-us-quant-data-时间.tar.gz`。脚本只在应用原本运行时
短暂停止 `quant-app`，校验压缩包后自动恢复服务。也可以指定备份目录：

```bash
sudo bash deploy/linux/backup-docker-volume.sh /mnt/backup/hk-us-quant
```

恢复脚本不会覆盖现有卷，而是恢复到一个新卷：

```bash
sudo bash deploy/linux/restore-docker-volume.sh \
  /var/backups/hk-us-quant/hk-us-quant-data-时间.tar.gz \
  hk-us-quant-data-restored
```

恢复成功后修改 `.env`：

```env
DATA_VOLUME_NAME=hk-us-quant-data-restored
```

然后执行：

```bash
docker compose up -d
curl http://127.0.0.1:8000/api/health
```

确认恢复结果后再决定是否保留旧卷。建议每天定时备份，并把备份同步到另一块磁盘或对象存储。

如果只运行干跑、不连接真实券商，可以在 `.env` 中设置 `INSTALL_BROKER_DEPS=0`，以减小镜像体积。
