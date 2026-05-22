# iCloud Photos Downloader - Docker

A robust and feature-rich Docker container for automatically downloading and syncing your iCloud Photos and Videos to a local directory. This project wraps the core `icloud_photos_downloader` script into a convenient, scheduled Docker container.

## Features

- **Automated Background Sync:** Automatically runs on a configurable schedule to pull down new photos and videos.
- **Flexible Configuration:** Configure everything via a single `config.yaml` or entirely via **Environment Variables**.
- **Resilient:** Includes retry mechanisms, authentication handling, and notification integrations (Telegram, Webhooks).
- **Lightweight:** Built on a Python slim image.

## Getting Started

### Using Docker Compose

The easiest way to get started is with Docker Compose. Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  icloudpd:
    image: ghcr.io/ericcug/icloudphotos-docker:latest
    container_name: icloudpd
    restart: unless-stopped
    environment:
      # Required
      - ICLOUD_APPLE_ID=your.email@example.com
      - ICLOUD_PASSWORD=your_apple_id_password
      # Optional settings
      - ICLOUD_DOWNLOAD_INTERVAL=86400
      - TZ=Asia/Shanghai
    volumes:
      # Mount a volume for your downloaded photos
      - /path/to/your/photos:/data
      # Mount a volume for configuration and cookies to avoid re-authentication
      - /path/to/your/config:/config
```

Run it with:

```bash
docker-compose up -d
```

### Using Docker CLI

```bash
docker run -d \
  --name icloudpd \
  --restart unless-stopped \
  -e ICLOUD_APPLE_ID="your.email@example.com" \
  -e ICLOUD_PASSWORD="your_apple_id_password" \
  -v /path/to/your/photos:/data \
  -v /path/to/your/config:/config \
  ghcr.io/ericcug/icloudphotos-docker:latest
```

## Configuration

You can configure the application using either a `config.yaml` file mounted to `/config/config.yaml` or via **Environment Variables**. 

> **Important:** Environment variables will always take precedence over values defined in `config.yaml`.

### Available Configuration Options

| Environment Variable | config.yaml key | Description | Default |
| :--- | :--- | :--- | :--- |
| `ICLOUD_APPLE_ID` | `apple_id` | **Required.** Your iCloud Apple ID | |
| `ICLOUD_PASSWORD` | N/A | **Required.** Your iCloud Password (Only available via Env Var for security) | |
| `ICLOUD_DOWNLOAD_PATH` | `download_path` | The path where photos are saved inside the container | `/data` |
| `ICLOUD_FOLDER_STRUCTURE` | `folder_structure` | Structure of downloaded folders (`YYYY/MM`, `YYYY/MM/DD`, `YYYY-MM-DD`, `album`, `none`) | `YYYY/MM` |
| `ICLOUD_DOWNLOAD_INTERVAL` | `download_interval` | Sync interval in seconds | `86400` (24h) |
| `ICLOUD_DOWNLOAD_DELAY` | `download_delay` | Delay between downloading individual files in seconds | `0` |
| `ICLOUD_RETRY_INTERVAL` | `retry_interval` | Wait time before retrying a failed download in seconds | `120` |
| `ICLOUD_RETRY_COUNT` | `retry_count` | Number of retries per file | `3` |
| `ICLOUD_FILE_PERMISSIONS` | `file_permissions` | Permissions for downloaded files | `644` |
| `ICLOUD_DIRECTORY_PERMISSIONS` | `directory_permissions`| Permissions for created directories | `755` |
| `ICLOUD_KEEP_UNICODE` | `keep_unicode` | Keep unicode characters in filenames | `true` |
| `ICLOUD_SET_EXIF_DATETIME` | `set_exif_datetime` | Update file creation date from EXIF data | `true` |
| `ICLOUD_FILE_MATCH_POLICY` | `file_match_policy` | Policy to determine if file already exists (`name`, `size`, `checksum`) | `name` |
| `ICLOUD_DOWNLOAD_RESOLUTION` | `download_resolution` | Download format option (`unmodified`, `high_res`, `compatible`) | `unmodified` |
| `ICLOUD_DELETE_POLICY` | `delete_policy` | How to handle files deleted from iCloud (`keep`, `delete`, `trash`) | `keep` |
| `ICLOUD_TRASH_DAYS` | `trash_days` | Number of days to keep files in trash before deleting (if policy is `trash`) | `30` |
| `ICLOUD_DELETE_AFTER_DOWNLOAD` | `delete_after_download` | Safely move photo to "Recently Deleted" on iCloud after successful local download | `false` |
| `ICLOUD_MAX_DELETIONS_PER_RUN` | `max_deletions_per_run` | Maximum number of iCloud deletions per sync cycle (to avoid Apple API throttling) | `100` |
| `ICLOUD_CHINA` | `icloud_china` | Set to `true` if your iCloud account is in China | `false` |
| `ICLOUD_AUTH_CHINA` | `auth_china` | Set to `true` to use China auth servers | `false` |
| `ICLOUD_LOG_LEVEL` | `log_level` | Application log level (`debug`, `info`, `warning`, `error`) | `info` |
| `ICLOUD_NOTIFICATION_DAYS` | `notification_days` | Days before cookie expiry to notify | `7` |

### Notification Settings

| Environment Variable | config.yaml key | Description | Default |
| :--- | :--- | :--- | :--- |
| `ICLOUD_TELEGRAM_ENABLED` | `notification.telegram.enabled` | Enable Telegram notifications | `false` |
| `ICLOUD_TELEGRAM_TOKEN` | `notification.telegram.bot_token` | Telegram Bot Token | |
| `ICLOUD_TELEGRAM_CHAT_ID` | `notification.telegram.chat_id` | Telegram Chat ID to send messages to | |
| `ICLOUD_TELEGRAM_POLLING_INTERVAL`| `notification.telegram.polling_interval`| Telegram polling interval in seconds | `5` |
| `ICLOUD_WEBHOOK_ENABLED` | `notification.webhook.enabled` | Enable Webhook notifications | `false` |
| `ICLOUD_WEBHOOK_URL` | `notification.webhook.url` | Webhook URL | |
| `ICLOUD_WEBHOOK_METHOD` | `notification.webhook.method` | Webhook HTTP method (`POST`, `GET`, etc.) | `POST` |

## Authentication

When you first start the container, it will attempt to authenticate. If you have Two-Factor Authentication (2FA) enabled, the container will pause and prompt for a verification code.
Check the container logs, and pass the 2FA code if needed. The resulting authentication cookies are saved in `/config` (or wherever you mapped `/config/cookie_dir`), so subsequent runs will not require re-authentication until the session expires (usually several months).
