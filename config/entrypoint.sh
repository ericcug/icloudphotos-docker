#!/bin/bash
set -e

echo "[entrypoint] Starting iCloud Photo Downloader..."

# 确保配置目录存在
mkdir -p /config/cookies /tmp/icloudpd

# 设置文件权限
if [ -f /config/config.yaml ]; then
    chmod 600 /config/config.yaml 2>/dev/null || true
fi

# 启动 Python 主程序
exec python -m icloud_docker.main --config "${ICLOUD_CONFIG:-/config/config.yaml}"
