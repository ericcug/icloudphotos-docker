"""Shared Telegram Bot service with connection pooling.

Manages a single telegram.Bot instance with persistent HTTPS connection
pool via httpx (built into python-telegram-bot v20+). Runs an asyncio
event loop in a background thread for async-to-sync bridging, so that
synchronous callers (TelegramController, TelegramNotifier, MFAProvider)
can use the Bot without managing their own event loops.
"""

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

import telegram

logger = logging.getLogger(__name__)


class TelegramService:
    """Shared Telegram Bot service with connection pooling.

    Creates a single ``telegram.Bot`` instance and runs it inside a
    dedicated asyncio event loop on a background thread.  All public
    methods are **synchronous** wrappers that dispatch coroutines into
    that loop via ``asyncio.run_coroutine_threadsafe``.

    Attributes:
        bot_token: Telegram Bot API token.
        bot: The underlying ``telegram.Bot`` instance (created on start).
    """

    def __init__(self, bot_token: str) -> None:
        """Initialize TelegramService.

        Args:
            bot_token: Telegram Bot API token.
        """
        self.bot_token = bot_token
        self.bot: Optional[telegram.Bot] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = False

    # ---- Lifecycle ----

    def start(self) -> None:
        """Start the background asyncio event loop and initialize the Bot.

        Creates a new event loop in a daemon thread and initialises the
        ``telegram.Bot`` (which sets up the internal httpx connection
        pool for persistent HTTPS connections).
        """
        if self._started:
            return

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="telegram-service"
        )
        self._thread.start()

        # Initialize the Bot inside the event loop
        try:
            self._run_sync(self._init_bot())
            self._started = True
            logger.info("TelegramService started (connection pool active)")
        except Exception as e:
            logger.error("Failed to start TelegramService: %s", e)
            self.stop()
            raise

    def stop(self) -> None:
        """Gracefully shut down the Bot and event loop."""
        if not self._started and not self._loop:
            return

        try:
            if self.bot and self._loop and self._loop.is_running():
                self._run_sync(self.bot.shutdown())
        except Exception as e:
            logger.debug("Bot shutdown error (non-fatal): %s", e)

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        self._started = False
        self.bot = None
        logger.info("TelegramService stopped")

    @property
    def is_running(self) -> bool:
        """Check if the service is running."""
        return self._started and self._loop is not None and self._loop.is_running()

    # ---- Public API (synchronous) ----

    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> bool:
        """Send a text message to a Telegram chat.

        Args:
            chat_id: Target chat ID.
            text: Message text.
            parse_mode: Optional parse mode (Markdown, HTML).

        Returns:
            True if the message was sent successfully.
        """
        if not self.is_running:
            logger.warning("TelegramService not running, cannot send message")
            return False

        try:
            self._run_sync(
                self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                )
            )
            return True
        except Exception as e:
            logger.warning("Telegram send_message failed: %s", e)
            return False

    def get_updates(
        self,
        offset: int = 0,
        timeout: int = 30,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch pending updates from Telegram (long polling).

        Args:
            offset: Identifier of the first update to be returned.
            timeout: Long polling timeout in seconds.
            limit: Maximum number of updates to retrieve.

        Returns:
            List of update dicts (raw Telegram update objects).
        """
        if not self.is_running:
            return []

        try:
            updates = self._run_sync(
                self.bot.get_updates(
                    offset=offset,
                    timeout=timeout,
                    limit=limit,
                )
            )
            # Convert telegram.Update objects to dicts for backward compat
            return [u.to_dict() for u in updates]
        except Exception as e:
            logger.debug("Telegram get_updates error: %s", e)
            return []

    # ---- Internal ----

    async def _init_bot(self) -> None:
        """Initialize the Bot instance (sets up httpx connection pool)."""
        self.bot = telegram.Bot(token=self.bot_token)
        await self.bot.initialize()
        me = await self.bot.get_me()
        logger.info("Telegram Bot initialized: @%s", me.username)

    def _run_loop(self) -> None:
        """Run the asyncio event loop in the background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_sync(self, coro, timeout: float = 35.0) -> Any:
        """Bridge an async coroutine to synchronous execution.

        Submits the coroutine to the background event loop and blocks
        until it completes.

        Args:
            coro: Awaitable coroutine.
            timeout: Maximum seconds to wait for result.

        Returns:
            The coroutine's return value.

        Raises:
            TimeoutError: If the coroutine does not complete in time.
            Exception: Any exception raised by the coroutine.
        """
        if not self._loop or not self._loop.is_running():
            raise RuntimeError("TelegramService event loop is not running")

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)
