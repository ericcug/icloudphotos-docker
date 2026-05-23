FROM python:3.11-slim AS builder

# 构建参数：icloud_photos_downloader 仓库与分支
ARG ICLOUDPD_REPO=https://github.com/ericcug/icloud_photos_downloader.git
ARG ICLOUDPD_REF=master

# 安装构建期工具 + 创建虚拟环境 + 安装所有依赖（单层合并）
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

# 从 Git 拉取并安装 icloud_photos_downloader + 运行时依赖（合并为一层）
RUN git clone --depth 1 --branch "${ICLOUDPD_REF}" "${ICLOUDPD_REPO}" /tmp/icloudpd_src \
    && pip install --no-cache-dir --no-compile \
        /tmp/icloudpd_src \
        "python-telegram-bot>=20.0" \
        "PyYAML>=6.0" \
    && rm -rf /tmp/icloudpd_src \
    # 清理运行时不需要的文件
    && find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -name "*.pyc" -o -name "*.pyo" | xargs rm -f 2>/dev/null; \
       find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -type d -name "testing" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -type d -name "docs" -exec rm -rf {} + 2>/dev/null; \
       true

# --- 最终运行镜像（Alpine） ---
FROM python:3.11-alpine

# 安装最小运行时依赖
RUN apk add --no-cache bash libffi

# 创建非 root 用户
RUN addgroup -g 1000 icloud && \
    adduser -u 1000 -G icloud -D -s /bin/bash icloud

# 从 builder 阶段复制虚拟环境
COPY --from=builder /opt/venv /opt/venv
# 启用虚拟环境
ENV PATH="/opt/venv/bin:$PATH"

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
