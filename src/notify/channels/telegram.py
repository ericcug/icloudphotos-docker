"""Telegram notification channel for system events."""

import logging
from typing import Optional

from notify.bus import SystemEvent
from notify.channels.telegram_service import TelegramService

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends system event notifications via Telegram Bot.

    Uses a shared TelegramService instance for connection pooling
    and persistent HTTPS connections.

    Attributes:
        service: Shared TelegramService for sending messages.
        chat_id: Target chat ID.
    """

    # Event type to emoji mapping
    EVENT_EMOJI = {
        "start": "🚀",
        "complete": "✅",
        "error": "❌",
        "auth_expired": "⚠️",
        "low_space": "💾",
        "rate_limited": "🐌",
        "sync_paused": "⏸️",
        "sync_resumed": "▶️",
        "mfa_requested": "🔐",
    }

    def __init__(self, service: TelegramService, chat_id: str):
        """Initialize Telegram notifier.

        Args:
            service: Shared TelegramService instance.
            chat_id: Target Telegram chat ID.
        """
        self.service = service
        self.chat_id = chat_id
        self.enabled = bool(chat_id) and service.is_running

    def send(self, event: SystemEvent) -> bool:
        """Send an event notification via Telegram.

        Args:
            event: SystemEvent to send.

        Returns:
            True if sent successfully.
        """
        if not self.enabled and not self.service.is_running:
            return False

        emoji = self.EVENT_EMOJI.get(event.event_type, "ℹ️")
        severity = event.severity.upper()
        text = f"{emoji} *{severity}* — {event.message}"

        if event.details:
            details_str = "\n".join(f"  • {k}: {v}" for k, v in event.details.items())
            text += f"\n\n{details_str}"

        result = self.service.send_message(
            chat_id=self.chat_id,
            text=text,
            parse_mode="Markdown",
        )

        if result:
            logger.debug("Telegram notification sent: %s", event.event_type)
        else:
            logger.warning("Telegram notification failed: %s", event.event_type)

        return result
