# Quickstart: iCloud 照片下载器

## 环境准备

> **注意**: venv 仅用于本地开发环境。Docker 容器内直接 `pip install`。

```bash
# 1. 克隆仓库（含子模块）
git clone --recurse-submodules <repo-url> icloudphotos-docker
cd icloudphotos-docker

# 如果已克隆但未拉取子模块：
git submodule update --init --recursive

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 验证安装

```bash
source venv/bin/activate
python -c "from pyicloud_ipd.base import PyiCloudService; print('icloudpd 库加载成功')"
```

## 项目结构

```
libs/icloud_photos_downloader/   # Git 子模块 — ericcug/icloud_photos_downloader
src/icloud_docker/               # 主程序包
config/                          # Docker 配置
```

## 本地运行

```bash
export ICLOUD_PASSWORD="your-app-specific-password"
python -m icloud_docker.main --config config/config.yaml --once
```

## Docker 构建

```bash
docker build -t icloudphotos -f config/Dockerfile .
```
