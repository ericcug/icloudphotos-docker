#!/bin/bash
set -e

echo "[entrypoint] Starting iCloud Photo Downloader..."

# Ensure config directories exist
mkdir -p /config/cookies /tmp/icloudpd

# Set file permissions
if [ -f /config/config.yaml ]; then
    chmod 600 /config/config.yaml 2>/dev/null || true
fi

# Start Python main program
exec python -m main --config "${ICLOUD_CONFIG:-/config/config.yaml}"
