"""Telegram Bot for remote control and MFA interaction.

Provides bidirectional Telegram communication:
- Receives commands: /pause, /resume, /sync, /status, /reauth
- Receives MFA verification codes → feeds to TelegramMFAProvider
- Sends status reports and notifications

Follows the docker-icloudpd pattern of single-Bot-for-all.
"""

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class TelegramController:
    """Telegram Bot controller for remote sync management.

    Polls the Telegram API for incoming messages and dispatches
    commands to the sync engine. MFA codes are forwarded to the
    MFA provider via provide_code().

    Attributes:
        bot_token: Telegram Bot API token.
        chat_id: Authorized chat ID.
        engine: SyncEngine instance for command execution.
        mfa_provider: TelegramMFAProvider for MFA code delivery.
        polling_interval: Seconds between update polls.
        running: Whether the polling loop is active.
    """

    # Command handlers
    COMMANDS = {
        "/pause": "pause_sync",
        "/resume": "resume_sync",
        "/sync": "sync_now",
        "/status": "get_status",
        "/reauth": "request_reauth",
    }

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        engine=None,
        mfa_provider=None,
        polling_interval: int = 5,
    ):
        """Initialize Telegram controller.

        Args:
            bot_token: Telegram Bot API token.
            chat_id: Authorized chat ID.
            engine: SyncEngine for command execution.
            mfa_provider: TelegramMFAProvider for MFA codes.
            polling_interval: Poll interval in seconds.
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.engine = engine
        self.mfa_provider = mfa_provider
        self.polling_interval = polling_interval
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._last_update_id = 0
        self.enabled = bool(bot_token and chat_id)

    def start(self) -> None:
        """Start the Telegram polling loop in a background thread."""
        if not self.enabled:
            logger.info("Telegram controller disabled (bot_token or chat_id not set)")
            return

        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Telegram controller started (polling every %ds)", self.polling_interval)

    def stop(self) -> None:
        """Stop the Telegram polling loop."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Telegram controller stopped")

    def _poll_loop(self) -> None:
        """Main polling loop for Telegram updates."""
        while self.running:
            try:
                self._check_updates()
            except Exception as e:
                logger.error("Telegram poll error: %s", e)
            time.sleep(self.polling_interval)

    def _check_updates(self) -> None:
        """Fetch and process pending Telegram updates."""
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params = {
            "offset": self._last_update_id + 1,
            "timeout": 30,
            "limit": 10,
        }

        try:
            resp = requests.get(url, params=params, timeout=35)
            data = resp.json()

            if not data.get("ok"):
                logger.warning("Telegram API error: %s", data.get("description"))
                return

            for update in data.get("result", []):
                self._last_update_id = update["update_id"]
                self._process_update(update)

        except requests.RequestException as e:
            logger.debug("Telegram network error: %s", e)

    def _process_update(self, update: dict) -> None:
        """Process a single Telegram update.

        Args:
            update: Telegram update object.
        """
        message = update.get("message", {})
        text = message.get("text", "").strip()
        msg_chat_id = str(message.get("chat", {}).get("id", ""))

        # Security: only respond to authorized chat_id (FR-023)
        if msg_chat_id != str(self.chat_id):
            logger.warning("Unauthorized message from chat %s", msg_chat_id)
            return

        if not text:
            return

        # Detect 6-digit MFA code → feed to MFA provider (like docker-icloudpd)
        # Supports both plain "123456" and "username 123456" formats
        parts = text.split()
        for part in parts:
            if len(part) == 6 and part.isdigit():
                if self.mfa_provider:
                    logger.info("MFA code detected in Telegram message → injecting")
                    self.mfa_provider.provide_code(part)
                    self._send_reply("✅ MFA code received. Authenticating...")
                    return

        # Detect single letter SMS device choice (a-z), but only when MFA is
        # actively waiting for input (to avoid false positives from normal messages)
        if len(parts) >= 1 and len(parts[-1]) == 1 and parts[-1].isalpha():
            choice = parts[-1].lower()
            if self.mfa_provider and not self.mfa_provider._code_event.is_set():
                logger.info("SMS device choice detected in Telegram message: '%s'", choice)
                self.mfa_provider.provide_code(choice)
                self._send_reply(f"📱 Sending SMS to device '{choice}'...")
                return

        # Check for commands
        cmd = text.lower().split()[0] if text else ""
        handler_name = self.COMMANDS.get(cmd)

        if handler_name:
            handler = getattr(self, handler_name, None)
            if handler:
                handler()

    def pause_sync(self) -> None:
        """Handle /pause command."""
        if self.engine:
            self.engine.pause()
            self._send_reply("⏸️ Sync paused at next checkpoint.")

    def resume_sync(self) -> None:
        """Handle /resume command."""
        if self.engine:
            self.engine.resume()
            self._send_reply("▶️ Sync resumed.")

    def sync_now(self) -> None:
        """Handle /sync command."""
        if self.engine:
            self.engine.sync_now()
            self._send_reply("🚀 Immediate sync triggered.")

    def get_status(self) -> None:
        """Handle /status command."""
        if self.engine:
            state = self.engine.state.value
            stats = self.engine.downloader.stats if hasattr(self.engine, 'downloader') else {}
            msg = (
                f"📊 *Sync Status*\n"
                f"State: `{state}`\n"
                f"Downloaded: {stats.get('downloaded', 0)}\n"
                f"Failed: {stats.get('failed', 0)}"
            )
            self._send_reply(msg)

    def request_reauth(self) -> None:
        """Handle /reauth command."""
        self._send_reply(
            "🔐 Re-authentication requested.\n"
            "Please send the 6-digit MFA code when prompted."
        )
        # The actual re-auth is triggered by cookie expiry detection

    def _send_reply(self, text: str) -> None:
        """Send a reply message to the authorized chat.

        Args:
            text: Message text (supports Markdown).
        """
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            requests.post(url, json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }, timeout=10)
        except Exception as e:
            logger.warning("Failed to send Telegram reply: %s", e)
