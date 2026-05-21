"""iCloud Docker — Docker-based iCloud Photo Downloader.

A modular Python application that downloads iCloud photos and videos
to local storage, with post-processing pipeline, Telegram notifications,
and remote control capabilities.
"""

import logging
import re
import sys
from typing import Optional


def setup_logging(level: str = "info", debug: bool = False) -> logging.Logger:
    """Configure structured logging for the application.

    Logs to stdout with timestamp, level, and module name.
    Includes a password filter to prevent credential leakage.

    Args:
        level: Log level string (debug, info, warning, error).
        debug: Enable debug logging (overrides level to DEBUG).

    Returns:
        Configured root logger instance.
    """
    log_level = logging.DEBUG if debug else getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # Add password filter to handler
    handler.addFilter(PasswordFilter())

    root_logger = logging.getLogger("icloud_docker")
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    return root_logger


class PasswordFilter(logging.Filter):
    """Logging filter that redacts sensitive fields from log records.

    Prevents iCloud passwords and Telegram tokens from appearing in logs.
    Detects patterns like 'password=value', 'token: value', 'key value' and
    replaces the sensitive value portion with [REDACTED].
    """

    SENSITIVE_FIELDS = {"password", "bot_token", "apple_id", "token", "secret", "key"}

    # Pattern matches: field_name followed by separator (=, :, space) then the value
    _REDACT_RE = re.compile(
        r'(?i)\b(' + '|'.join(re.escape(f) for f in SENSITIVE_FIELDS) + r')'
        r'([\s=:]+)'
        r'(\S+)',
    )

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log record, redacting sensitive values from message."""
        if hasattr(record, "msg") and isinstance(record.msg, str):
            record.msg = self._REDACT_RE.sub(r'\1\2[REDACTED]', record.msg)
        return True


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given module name.

    Args:
        name: Module name (typically __name__).

    Returns:
        Logger instance under the icloud_docker namespace.
    """
    return logging.getLogger(f"icloud_docker.{name}")
