#!/bin/bash
# Docker HEALTHCHECK script for iCloud Photo Downloader
# Follows the docker-icloudpd healthcheck pattern

set -e

COOKIE_DIR="${COOKIE_DIR:-/config/cookies}"
EXIT_CODE_FILE="/tmp/icloudpd/icloudpd_exit_code"

# Check if exit code file exists
if [ -f "$EXIT_CODE_FILE" ]; then
    exit_code=$(cat "$EXIT_CODE_FILE" 2>/dev/null || echo "0")
    if [ "${exit_code:-0}" -ne 0 ]; then
        echo "Sync error detected (exit code: $exit_code)"
        exit 1
    fi
fi

# Check if at least one cookie file exists
cookie_count=$(find "$COOKIE_DIR" -type f 2>/dev/null | wc -l)
if [ "$cookie_count" -eq 0 ]; then
    # No cookies yet - container may be waiting for first auth
    # Return healthy (don't restart container for initial setup)
    echo "Waiting for initial authentication..."
    exit 0
fi

# Check if sync process is running (Alpine-compatible, no pgrep needed)
if ! ps aux 2>/dev/null | grep -v grep | grep -q "python -m main"; then
    echo "Sync process not running"
    exit 1
fi

echo "iCloud Photo Downloader healthy"
exit 0
