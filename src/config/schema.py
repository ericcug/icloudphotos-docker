"""Configuration schema definitions and validation for iCloud Docker.

Defines the Config dataclass with all supported configuration fields,
YAML schema structure, and environment variable override mappings.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class TelegramConfig:
    """Telegram Bot notification and control configuration."""

    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    polling_interval: int = 5


@dataclass
class WebhookConfig:
    """Webhook notification configuration."""

    enabled: bool = False
    url: str = ""
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class NotificationConfig:
    """Notification subsystem configuration."""

    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    events: List[str] = field(default_factory=lambda: [
        "start", "complete", "error", "auth_expired", "cookie_expiring",
        "low_space", "rate_limited"
    ])


@dataclass
class PipelineStepConfig:
    """Single post-processing pipeline step configuration."""

    name: str = ""
    config: Dict = field(default_factory=dict)
    retry: int = 3
    enabled: bool = True


@dataclass
class PipelineConfig:
    """Post-processing pipeline configuration."""

    steps: List[PipelineStepConfig] = field(default_factory=list)


@dataclass
class Config:
    """Master configuration for iCloud Photo Downloader.

    All fields correspond to config.yaml keys. Environment variables
    with prefix ICLOUD_ can override top-level string/int fields.
    """

    # Required
    apple_id: str = ""

    # Storage
    download_path: Path = Path("/data/photos")
    folder_structure: str = "YYYY/MM"

    # Sync
    download_interval: int = 86400
    download_delay: int = 0
    retry_interval: int = 120
    retry_count: int = 3
    file_permissions: str = "644"
    directory_permissions: str = "755"
    keep_unicode: bool = True
    set_exif_datetime: bool = True
    file_match_policy: str = "name"

    # Delete policy
    delete_policy: str = "keep"
    trash_days: int = 30

    # China region
    icloud_china: bool = False
    auth_china: bool = False

    # Cookie expiry notification (docker-icloudpd: notification_days)
    notification_days: int = 7

    # Subsystems
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)

    # Advanced
    log_level: str = "info"
    debug_logging: bool = False

    # Derived paths (not configurable via YAML)
    cookie_dir: Path = Path("./data/cookies")
    temp_dir: Path = Path("/tmp/icloudpd")


# Valid folder structure options
VALID_FOLDER_STRUCTURES = {"YYYY/MM", "YYYY/MM/DD", "YYYY-MM-DD", "album", "none"}

# Valid file permissions
VALID_FILE_PERMISSIONS = {"600", "640", "644", "660", "664", "666"}

# Valid delete policies
VALID_DELETE_POLICIES = {"keep", "delete", "trash"}

# Valid file match policies
VALID_FILE_MATCH_POLICIES = {"name", "size", "checksum"}

# Valid log levels
VALID_LOG_LEVELS = {"debug", "info", "warning", "error"}


# Environment variable mapping
ENV_VAR_MAP = {
    "ICLOUD_APPLE_ID": "apple_id",
    "ICLOUD_PASSWORD": None,  # handled separately, not stored in Config
    "ICLOUD_DOWNLOAD_PATH": "download_path",
    "ICLOUD_FOLDER_STRUCTURE": "folder_structure",
    "ICLOUD_DOWNLOAD_INTERVAL": "download_interval",
    "ICLOUD_INTERVAL": "download_interval",
    "ICLOUD_DOWNLOAD_DELAY": "download_delay",
    "ICLOUD_RETRY_INTERVAL": "retry_interval",
    "ICLOUD_RETRY_COUNT": "retry_count",
    "ICLOUD_FILE_PERMISSIONS": "file_permissions",
    "ICLOUD_DIRECTORY_PERMISSIONS": "directory_permissions",
    "ICLOUD_KEEP_UNICODE": "keep_unicode",
    "ICLOUD_SET_EXIF_DATETIME": "set_exif_datetime",
    "ICLOUD_FILE_MATCH_POLICY": "file_match_policy",
    "ICLOUD_DELETE_POLICY": "delete_policy",
    "ICLOUD_TRASH_DAYS": "trash_days",
    "ICLOUD_CHINA": "icloud_china",
    "ICLOUD_AUTH_CHINA": "auth_china",
    "ICLOUD_LOG_LEVEL": "log_level",
    "ICLOUD_DEBUG_LOGGING": "debug_logging",
    "ICLOUD_NOTIFICATION_DAYS": "notification_days",
    "ICLOUD_TELEGRAM_ENABLED": "notification.telegram.enabled",
    "ICLOUD_TELEGRAM_TOKEN": "notification.telegram.bot_token",
    "ICLOUD_TELEGRAM_CHAT_ID": "notification.telegram.chat_id",
    "ICLOUD_TELEGRAM_POLLING_INTERVAL": "notification.telegram.polling_interval",
    "ICLOUD_WEBHOOK_ENABLED": "notification.webhook.enabled",
    "ICLOUD_WEBHOOK_URL": "notification.webhook.url",
    "ICLOUD_WEBHOOK_METHOD": "notification.webhook.method",
}
