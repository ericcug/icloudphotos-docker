"""Telegram notification channel for system events."""

import logging
from typing import Optional

import requests

from notify.bus import SystemEvent

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends system event notifications via Telegram Bot.

    Attributes:
        bot_token: Telegram Bot API token.
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

    def __init__(self, bot_token: str, chat_id: str):
        """Initialize Telegram notifier.

        Args:
            bot_token: Telegram Bot API token.
            chat_id: Target Telegram chat ID.
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)

    def send(self, event: SystemEvent) -> bool:
        """Send an event notification via Telegram.

        Args:
            event: SystemEvent to send.

        Returns:
            True if sent successfully.
        """
        if not self.enabled:
            return False

        emoji = self.EVENT_EMOJI.get(event.event_type, "ℹ️")
        severity = event.severity.upper()
        text = f"{emoji} *{severity}* — {event.message}"

        if event.details:
            details_str = "\n".join(f"  • {k}: {v}" for k, v in event.details.items())
            text += f"\n\n{details_str}"

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }, timeout=10)

            if resp.status_code == 200:
                logger.debug("Telegram notification sent: %s", event.event_type)
                return True
            else:
                logger.warning("Telegram send failed (HTTP %d): %s",
                               resp.status_code, resp.text)
                return False

        except Exception as e:
            logger.warning("Telegram send error: %s", e)
            return False
