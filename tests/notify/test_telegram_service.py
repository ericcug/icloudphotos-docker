"""Unit tests for TelegramService shared connection pool."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTelegramService:
    """Test TelegramService lifecycle and sync bridging."""

    def test_not_running_before_start(self):
        from notify.channels.telegram_service import TelegramService
        svc = TelegramService("fake-token")
        assert svc.is_running is False

    def test_send_message_when_not_running_returns_false(self):
        from notify.channels.telegram_service import TelegramService
        svc = TelegramService("fake-token")
        assert svc.send_message("chat", "text") is False

    def test_get_updates_when_not_running_returns_empty(self):
        from notify.channels.telegram_service import TelegramService
        svc = TelegramService("fake-token")
        assert svc.get_updates() == []

    @patch("notify.channels.telegram_service.telegram.Bot")
    def test_start_initializes_bot(self, mock_bot_class):
        """Verify start() creates bot and calls initialize + get_me."""
        from notify.channels.telegram_service import TelegramService

        mock_bot = MagicMock()
        mock_bot.initialize = AsyncMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
        mock_bot.shutdown = AsyncMock()
        mock_bot_class.return_value = mock_bot

        svc = TelegramService("fake-token")
        svc.start()

        try:
            assert svc.is_running
            mock_bot.initialize.assert_awaited_once()
            mock_bot.get_me.assert_awaited_once()
        finally:
            svc.stop()

    @patch("notify.channels.telegram_service.telegram.Bot")
    def test_stop_shuts_down_bot(self, mock_bot_class):
        """Verify stop() calls bot.shutdown and stops the loop."""
        from notify.channels.telegram_service import TelegramService

        mock_bot = MagicMock()
        mock_bot.initialize = AsyncMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
        mock_bot.shutdown = AsyncMock()
        mock_bot_class.return_value = mock_bot

        svc = TelegramService("fake-token")
        svc.start()
        assert svc.is_running

        svc.stop()
        assert not svc.is_running
        mock_bot.shutdown.assert_awaited_once()

    @patch("notify.channels.telegram_service.telegram.Bot")
    def test_send_message_success(self, mock_bot_class):
        """Verify send_message dispatches to bot and returns True."""
        from notify.channels.telegram_service import TelegramService

        mock_bot = MagicMock()
        mock_bot.initialize = AsyncMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
        mock_bot.send_message = AsyncMock()
        mock_bot.shutdown = AsyncMock()
        mock_bot_class.return_value = mock_bot

        svc = TelegramService("fake-token")
        svc.start()

        try:
            result = svc.send_message("123", "Hello", parse_mode="Markdown")
            assert result is True
            mock_bot.send_message.assert_awaited_once_with(
                chat_id="123", text="Hello", parse_mode="Markdown"
            )
        finally:
            svc.stop()

    @patch("notify.channels.telegram_service.telegram.Bot")
    def test_send_message_failure(self, mock_bot_class):
        """Verify send_message returns False on exception."""
        from notify.channels.telegram_service import TelegramService

        mock_bot = MagicMock()
        mock_bot.initialize = AsyncMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
        mock_bot.send_message = AsyncMock(side_effect=Exception("network error"))
        mock_bot.shutdown = AsyncMock()
        mock_bot_class.return_value = mock_bot

        svc = TelegramService("fake-token")
        svc.start()

        try:
            result = svc.send_message("123", "Hello")
            assert result is False
        finally:
            svc.stop()

    @patch("notify.channels.telegram_service.telegram.Bot")
    def test_get_updates_returns_dicts(self, mock_bot_class):
        """Verify get_updates converts Update objects to dicts."""
        from notify.channels.telegram_service import TelegramService

        mock_update = MagicMock()
        mock_update.to_dict.return_value = {
            "update_id": 1,
            "message": {"text": "hello", "chat": {"id": 123}},
        }

        mock_bot = MagicMock()
        mock_bot.initialize = AsyncMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
        mock_bot.get_updates = AsyncMock(return_value=[mock_update])
        mock_bot.shutdown = AsyncMock()
        mock_bot_class.return_value = mock_bot

        svc = TelegramService("fake-token")
        svc.start()

        try:
            updates = svc.get_updates(offset=1, timeout=1, limit=10)
            assert len(updates) == 1
            assert updates[0]["update_id"] == 1
        finally:
            svc.stop()

    @patch("notify.channels.telegram_service.telegram.Bot")
    def test_double_start_is_idempotent(self, mock_bot_class):
        """Verify calling start() twice doesn't create duplicate loops."""
        from notify.channels.telegram_service import TelegramService

        mock_bot = MagicMock()
        mock_bot.initialize = AsyncMock()
        mock_bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
        mock_bot.shutdown = AsyncMock()
        mock_bot_class.return_value = mock_bot

        svc = TelegramService("fake-token")
        svc.start()
        svc.start()  # should be no-op

        try:
            assert mock_bot.initialize.await_count == 1
        finally:
            svc.stop()

    def test_stop_when_not_started_is_safe(self):
        """Verify stop() on unstarted service doesn't raise."""
        from notify.channels.telegram_service import TelegramService
        svc = TelegramService("fake-token")
        svc.stop()  # should not raise
