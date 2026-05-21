FROM python:3.11-slim

# 构建参数：icloud_photos_downloader 仓库与分支
ARG ICLOUDPD_REPO=https://github.com/ericcug/icloud_photos_downloader.git
ARG ICLOUDPD_REF=master

# 安装构建期工具
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -g 1000 icloud && \
    useradd -u 1000 -g icloud -m -s /bin/bash icloud

# 从 Git 拉取并安装 icloud_photos_downloader
RUN git clone --depth 1 --branch "${ICLOUDPD_REF}" "${ICLOUDPD_REPO}" /tmp/icloudpd_src \
    && pip install --no-cache-dir /tmp/icloudpd_src \
    && rm -rf /tmp/icloudpd_src

# 安装运行时依赖
RUN pip install --no-cache-dir \
    requests==2.32.3 \
    "python-telegram-bot>=20.0" \
    "PyYAML>=6.0" \
    "pillow>=10.0"

# 清理构建期工具
RUN apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# 创建运行时目录
RUN mkdir -p /config /data /tmp/icloudpd && \
    chown -R icloud:icloud /config /data /tmp/icloudpd

# 复制源码
COPY src/ /app/src/
COPY config/entrypoint.sh /app/entrypoint.sh
COPY config/healthcheck.sh /app/healthcheck.sh
RUN chmod +x /app/entrypoint.sh /app/healthcheck.sh

WORKDIR /app
USER icloud

ENV PYTHONPATH=/app/src
ENV ICLOUD_CONFIG=/config/config.yaml
ENV ICLOUD_DOWNLOAD_PATH=/data

HEALTHCHECK --interval=300s --timeout=30s --start-period=60s --retries=3 \
    CMD /bin/bash /app/healthcheck.sh || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
