"""Configuration loader: YAML parsing, validation, and environment variable override."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from config.schema import (
    VALID_DELETE_POLICIES,
    VALID_FILE_MATCH_POLICIES,
    VALID_FILE_PERMISSIONS,
    VALID_FOLDER_STRUCTURES,
    VALID_LOG_LEVELS,
    ENV_VAR_MAP,
    Config,
    NotificationConfig,
    PipelineConfig,
    PipelineStepConfig,
    TelegramConfig,
    WebhookConfig,
)

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Configuration validation error."""
    pass


def load_config(config_path: Path, password: Optional[str] = None) -> Config:
    """Load and validate configuration from YAML file.

    Merges environment variable overrides on top of YAML values.
    Password is NOT stored in the config file; it must be passed separately
    via environment variable ICLOUD_PASSWORD or parameter.

    Args:
        config_path: Path to config.yaml file.
        password: iCloud Apple ID password (from env or param).

    Returns:
        Validated Config instance.

    Raises:
        ConfigError: If required fields are missing or values are invalid.
        FileNotFoundError: If config file does not exist.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}

    # Apply environment variable overrides
    _apply_env_overrides(raw)

    # Build Config from raw dict
    config = _build_config(raw, password)

    # Validate
    _validate(config)

    logger.info("Configuration loaded successfully (apple_id=%s)", _mask(config.apple_id))
    return config


def _apply_env_overrides(raw: Dict[str, Any]) -> None:
    """Apply environment variable overrides to raw config dict."""
    for env_key, config_path in ENV_VAR_MAP.items():
        value = os.environ.get(env_key)
        if value is not None and config_path is not None:
            _set_nested(raw, config_path, value)
            logger.debug("Env override: %s=%s", env_key, _mask(value))


def _set_nested(d: Dict[str, Any], path: str, value: str) -> None:
    """Set a nested dict value by dot-separated path, converting types.

    Uses the schema defaults for type inference when the target key
    doesn't exist yet in the raw dict.
    """
    keys = path.split(".")
    for key in keys[:-1]:
        if key not in d:
            d[key] = {}
        d = d[key]

    # Determine target type from existing value or schema defaults
    existing = d.get(keys[-1])
    if existing is None:
        # Fall back to schema defaults for type inference
        existing = _SCHEMA_TYPE_HINTS.get(path)

    if isinstance(existing, bool):
        d[keys[-1]] = value.lower() in ("true", "1", "yes")
    elif isinstance(existing, int):
        try:
            d[keys[-1]] = int(value)
        except ValueError:
            d[keys[-1]] = value
    else:
        d[keys[-1]] = value


# Schema type hints for environment variable type inference when key is absent
_SCHEMA_TYPE_HINTS: Dict[str, Any] = {
    "apple_id": "",
    "download_path": "",
    "folder_structure": "",
    "download_interval": 86400,
    "download_delay": 0,
    "retry_interval": 120,
    "retry_count": 3,
    "file_permissions": "",
    "directory_permissions": "",
    "keep_unicode": True,
    "set_exif_datetime": True,
    "file_match_policy": "",
    "delete_policy": "",
    "trash_days": 30,
    "icloud_china": False,
    "auth_china": False,
    "log_level": "",
    "debug_logging": False,
    "notification_days": 7,
    "notification.telegram.enabled": False,
    "notification.telegram.bot_token": "",
    "notification.telegram.chat_id": "",
    "notification.telegram.polling_interval": 5,
    "notification.webhook.enabled": False,
    "notification.webhook.url": "",
    "notification.webhook.method": "",
}


def _build_config(raw: Dict[str, Any], password: Optional[str]) -> Config:
    """Build Config dataclass from raw dict."""
    # Notification
    notif_raw = raw.get("notification", {})
    tg_raw = notif_raw.get("telegram", {})
    wh_raw = notif_raw.get("webhook", {})

    notification = NotificationConfig(
        telegram=TelegramConfig(
            enabled=tg_raw.get("enabled", False),
            bot_token=tg_raw.get("bot_token", ""),
            chat_id=tg_raw.get("chat_id", ""),
            polling_interval=tg_raw.get("polling_interval", 5),
        ),
        webhook=WebhookConfig(
            enabled=wh_raw.get("enabled", False),
            url=wh_raw.get("url", ""),
            method=wh_raw.get("method", "POST"),
            headers=wh_raw.get("headers", {}),
        ),
        events=notif_raw.get("events", ["start", "complete", "error"]),
    )

    # Pipeline
    pipeline_raw = raw.get("pipeline", {})
    steps = []
    for step_raw in pipeline_raw.get("steps", []):
        steps.append(PipelineStepConfig(
            name=step_raw.get("name", ""),
            config=step_raw.get("config", {}),
            retry=step_raw.get("retry", 3),
            enabled=step_raw.get("enabled", True),
        ))
    pipeline = PipelineConfig(steps=steps)

    cookie_dir_val = raw.get("cookie_dir", None)
    if cookie_dir_val:
        cookie_dir = Path(cookie_dir_val)
    else:
        cookie_dir = Path("./data/cookies")

    return Config(
        apple_id=raw.get("apple_id", ""),
        download_path=Path(raw.get("download_path", "/data/photos")),
        folder_structure=raw.get("folder_structure", "YYYY/MM"),
        download_interval=int(raw.get("download_interval", 86400)),
        download_delay=int(raw.get("download_delay", 0)),
        retry_interval=int(raw.get("retry_interval", 120)),
        retry_count=int(raw.get("retry_count", 3)),
        file_permissions=str(raw.get("file_permissions", "644")),
        directory_permissions=str(raw.get("directory_permissions", "755")),
        keep_unicode=bool(raw.get("keep_unicode", True)),
        set_exif_datetime=bool(raw.get("set_exif_datetime", True)),
        file_match_policy=str(raw.get("file_match_policy", "name")),
        delete_policy=str(raw.get("delete_policy", "keep")),
        trash_days=int(raw.get("trash_days", 30)),
        icloud_china=bool(raw.get("icloud_china", False)),
        auth_china=bool(raw.get("auth_china", False)),
        log_level=str(raw.get("log_level", "info")),
        debug_logging=bool(raw.get("debug_logging", False)),
        cookie_dir=cookie_dir,
        notification=notification,
        pipeline=pipeline,
    )


def _validate(config: Config) -> None:
    """Validate configuration values."""
    errors = []

    if not config.apple_id or "@" not in config.apple_id:
        errors.append("apple_id is required and must contain '@'")

    if config.folder_structure not in VALID_FOLDER_STRUCTURES:
        errors.append(
            f"folder_structure '{config.folder_structure}' must be one of {VALID_FOLDER_STRUCTURES}"
        )

    if config.file_permissions not in VALID_FILE_PERMISSIONS:
        errors.append(
            f"file_permissions '{config.file_permissions}' must be one of {VALID_FILE_PERMISSIONS}"
        )

    if config.delete_policy not in VALID_DELETE_POLICIES:
        errors.append(
            f"delete_policy '{config.delete_policy}' must be one of {VALID_DELETE_POLICIES}"
        )

    if config.file_match_policy not in VALID_FILE_MATCH_POLICIES:
        errors.append(
            f"file_match_policy '{config.file_match_policy}' must be one of {VALID_FILE_MATCH_POLICIES}"
        )

    if config.log_level not in VALID_LOG_LEVELS:
        errors.append(f"log_level '{config.log_level}' must be one of {VALID_LOG_LEVELS}")

    if config.download_interval < 60:
        errors.append("download_interval must be >= 60 seconds")

    if errors:
        raise ConfigError("Configuration validation failed:\n  - " + "\n  - ".join(errors))


def _mask(value: str) -> str:
    """Mask sensitive string for logging."""
    if not value or len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]
