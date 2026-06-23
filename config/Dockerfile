FROM python:3.11-slim AS builder

# Build arguments: icloud_photos_downloader repository and branch
ARG ICLOUDPD_REPO=https://github.com/ericcug/icloud_photos_downloader.git
ARG ICLOUDPD_REF=master

# Install build tools + create virtual environment + install all dependencies (single layer merge)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

# Clone from Git and install icloud_photos_downloader + runtime dependencies (merged into one layer)
RUN git clone --depth 1 --branch "${ICLOUDPD_REF}" "${ICLOUDPD_REPO}" /tmp/icloudpd_src \
    && pip install --no-cache-dir --no-compile \
        /tmp/icloudpd_src \
        "python-telegram-bot>=20.0" \
        "PyYAML>=6.0" \
    && rm -rf /tmp/icloudpd_src \
    # Clean up files not needed at runtime
    && find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -name "*.pyc" -o -name "*.pyo" | xargs rm -f 2>/dev/null; \
       find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -type d -name "testing" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -type d -name "docs" -exec rm -rf {} + 2>/dev/null; \
       true

# --- Final runtime image (Alpine) ---
FROM python:3.11-alpine

# Install minimal runtime dependencies
RUN apk add --no-cache bash libffi

# Create non-root user
RUN addgroup -g 1000 icloud && \
    adduser -u 1000 -G icloud -D -s /bin/bash icloud

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
# Enable virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Create runtime directories
RUN mkdir -p /config /data /tmp/icloudpd && \
    chown -R icloud:icloud /config /data /tmp/icloudpd

# Copy source code
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
