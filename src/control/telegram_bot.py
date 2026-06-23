"""Telegram Bot for remote control and MFA interaction.

Provides bidirectional Telegram communication:
- Receives commands: /pause, /resume, /sync, /status, /reauth
- Receives MFA verification codes → feeds to TelegramMFAProvider
- Sends status reports and notifications

Uses shared TelegramService for connection pooling. Long polling
uses Telegram's native timeout parameter so each poll blocks for
up to 30 seconds, eliminating unnecessary reconnections.
"""

import os

import logging
import threading
from typing import Optional

from notify.channels.telegram_service import TelegramService

logger = logging.getLogger(__name__)


class TelegramController:
    """Telegram Bot controller for remote sync management.

    Polls the Telegram API for incoming messages and dispatches
    commands to the sync engine. MFA codes are forwarded to the
    MFA provider via provide_code().

    Uses TelegramService for persistent HTTP connection pooling.

    Attributes:
        service: Shared TelegramService for API calls.
        chat_id: Authorized chat ID.
        engine: SyncEngine instance for command execution.
        mfa_provider: TelegramMFAProvider for MFA code delivery.
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
        service: Optional[TelegramService],
        chat_id: str,
        engine=None,
        mfa_provider=None,
        auth_manager=None,
    ):
        """Initialize Telegram controller.

        Args:
            service: Shared TelegramService instance.
            chat_id: Authorized chat ID.
            engine: SyncEngine for command execution.
            mfa_provider: TelegramMFAProvider for MFA codes.
            auth_manager: AuthManager for re-authentication.
        """
        self.service = service
        self.chat_id = chat_id
        self.engine = engine
        self.mfa_provider = mfa_provider
        self.auth_manager = auth_manager
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._last_update_id = 0
        self.enabled = bool(service and chat_id)

    def start(self) -> None:
        """Start the Telegram polling loop in a background thread."""
        if not self.enabled:
            logger.info("Telegram controller disabled (service or chat_id not set)")
            return

        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Telegram controller started (long polling)")

    def stop(self) -> None:
        """Stop the Telegram polling loop."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=35)  # wait for long poll to finish
        logger.info("Telegram controller stopped")

    def _poll_loop(self) -> None:
        """Main polling loop for Telegram updates.

        Each iteration does a long poll (30s timeout), so there is no
        need for an additional sleep between iterations. The connection
        is reused via TelegramService's httpx pool.
        """
        while self.running:
            try:
                self._check_updates()
            except Exception as e:
                logger.error("Telegram poll error: %s", e)

    def _check_updates(self) -> None:
        """Fetch and process pending Telegram updates."""
        updates = self.service.get_updates(
            offset=self._last_update_id + 1,
            timeout=30,
            limit=10,
        )

        for update in updates:
            update_id = update.get("update_id", 0)
            if update_id > self._last_update_id:
                self._last_update_id = update_id
            self._process_update(update)

    def _process_update(self, update: dict) -> None:
        """Process a single Telegram update.

        Args:
            update: Telegram update object (dict).
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
        """Handle /reauth command.

        Triggers a full re-authentication cycle:
        1. Deletes existing cookies
        2. Performs SRP login (triggers Apple MFA push)
        3. Waits for MFA code via Telegram
        4. Updates the sync engine's wrapper with the new service
        """
        if not self.auth_manager:
            self._send_reply("❌ Re-authentication not available (auth_manager not set).")
            return

        password = os.environ.get("ICLOUD_PASSWORD", "")
        if not password:
            self._send_reply("❌ ICLOUD_PASSWORD environment variable not set.")
            return

        self._send_reply(
            "🔐 Re-authentication started...\n"
            "Please send the 6-digit MFA code when prompted."
        )

        # Run reauth in a separate thread to avoid blocking the poll loop
        reauth_thread = threading.Thread(
            target=self._do_reauth, args=(password,), daemon=True
        )
        reauth_thread.start()

    def _do_reauth(self, password: str) -> None:
        """Perform re-authentication in background thread.

        Args:
            password: iCloud Apple ID password.
        """
        try:
            new_service = self.auth_manager.reauthenticate(password)
            # Update the sync engine's wrapper with the fresh service
            if self.engine:
                self.engine.wrapper.service = new_service
            self._send_reply("✅ Re-authentication successful. Cookies refreshed.")
            logger.info("Re-authentication completed via /reauth command")
        except Exception as e:
            logger.error("Re-authentication failed: %s", e)
            self._send_reply(f"❌ Re-authentication failed: {e}")

    def _send_reply(self, text: str) -> None:
        """Send a reply message to the authorized chat.

        Args:
            text: Message text (supports Markdown).
        """
        if self.service:
            self.service.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="Markdown",
            )
