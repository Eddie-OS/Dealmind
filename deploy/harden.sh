#!/usr/bin/env bash
# DealMind 服务器稳定性加固脚本
# 目标：在 2GB 内存机器上防止“加载 embedding 模型 / 多人会话”把整机内存打满导致卡死重启。
set -uo pipefail

echo "==================================================="
echo "== 1. 关闭并禁用 docker/containerd（HR_v2 残留，白占内存）"
echo "==================================================="
sudo systemctl disable --now docker.service docker.socket containerd.service 2>/dev/null || true
sudo systemctl is-active docker 2>/dev/null || echo "  docker 已停"

echo "==================================================="
echo "== 2. 确保 swap 持久化（重启后依然生效）"
echo "==================================================="
if ! swapon --show | grep -q .; then
  echo "  未检测到 swap，创建 2G /swapfile ..."
  sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
else
  echo "  swap 已启用"
fi
if ! grep -q '/swapfile' /etc/fstab 2>/dev/null; then
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  echo "  已写入 /etc/fstab（开机自动挂载 swap）"
fi

echo "==================================================="
echo "== 3. 调低 swappiness：内存吃紧时更早用 swap 缓冲峰值"
echo "==================================================="
sudo sysctl -w vm.swappiness=30 >/dev/null
grep -q 'vm.swappiness' /etc/sysctl.conf 2>/dev/null || echo 'vm.swappiness=30' | sudo tee -a /etc/sysctl.conf >/dev/null
echo "  vm.swappiness=30"

echo "==================================================="
echo "== 4. 给后端加内存护栏：超限只重启后端，绝不拖垮整机"
echo "==================================================="
sudo mkdir -p /etc/systemd/system/dealmind-api.service.d
sudo tee /etc/systemd/system/dealmind-api.service.d/limits.conf >/dev/null <<'EOF'
[Service]
MemoryAccounting=yes
# 后端最多 1.4G（足够放下 embedding 模型）；超过则内核在 cgroup 内结束后端进程，
# 由 Restart=always 自动拉起——只有后端短暂重启，整机不会卡死/重启。
MemoryMax=1400M
MemoryHigh=1200M
# 系统级内存告急时，优先回收后端而不是整机
OOMScoreAdjust=600
EOF
sudo systemctl daemon-reload
sudo systemctl restart dealmind-api

echo "==================================================="
echo "== 结果"
echo "==================================================="
sleep 3
free -h
echo "--- swap ---"; swapon --show
echo "--- dealmind-api ---"; systemctl is-active dealmind-api
echo "--- 生效的内存限制 ---"; systemctl show dealmind-api -p MemoryMax -p MemoryHigh -p OOMScoreAdjust
echo "DONE"
