#!/usr/bin/env bash
# =============================================================================
# DealMind 一键部署脚本（Ubuntu 24.04 / 阿里云轻量应用服务器 2核2G）
#
# 前置：已把整个项目（含 data/ 与本机 build 好的 web/dist 与 .env）上传到
#       /opt/dealmind。然后在服务器上以 root 执行：
#
#       cd /opt/dealmind && bash deploy/setup.sh
#
# 脚本是幂等的：重复执行只会更新依赖与服务，不会重复建 swap / 重复装源。
# =============================================================================
set -euo pipefail

APP_DIR="/opt/dealmind"
cd "$APP_DIR"

echo "==> [1/7] 基础工具"
apt-get update -y
apt-get install -y python3-venv python3-pip curl debian-keyring debian-archive-keyring apt-transport-https

echo "==> [2/7] 创建 2G swap（2G 物理内存加载 embedding 模型时兜底，防 OOM）"
if [ ! -f /swapfile ]; then
	fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
	chmod 600 /swapfile
	mkswap /swapfile
	swapon /swapfile
	grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
	echo "    swap 已创建"
else
	echo "    /swapfile 已存在，跳过"
fi

echo "==> [3/7] Python 虚拟环境 + 依赖"
if [ ! -d "$APP_DIR/.venv" ]; then
	python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip
# torch / sentence-transformers 体积较大，首次安装会比较久（几分钟）
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> [4/7] 校验 .env 是否存在（缺少 OPENAI_API_KEY 后端会起不来）"
if [ ! -f "$APP_DIR/.env" ]; then
	echo "!!! 未找到 $APP_DIR/.env —— 请先上传 .env（至少包含 OPENAI_API_KEY）后重跑本脚本"
	exit 1
fi

echo "==> [5/7] 安装 Caddy"
if ! command -v caddy >/dev/null 2>&1; then
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
		| gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
		> /etc/apt/sources.list.d/caddy-stable.list
	apt-get update -y
	apt-get install -y caddy
else
	echo "    caddy 已安装，跳过"
fi

echo "==> [6/7] 部署 systemd 后端服务 + Caddy 配置"
cp "$APP_DIR/deploy/dealmind-api.service" /etc/systemd/system/dealmind-api.service
cp "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable dealmind-api
systemctl restart dealmind-api
systemctl restart caddy

echo "==> [7/7] 完成。状态："
sleep 2
systemctl --no-pager --lines=5 status dealmind-api || true
echo
echo "后端日志：  journalctl -u dealmind-api -f"
echo "Caddy 日志： journalctl -u caddy -f"
echo
echo "首次启动会下载 embedding 模型（bge-small-zh，约 100MB），稍等 1-2 分钟。"
echo "然后浏览器访问：http://<你的公网IP>/"
