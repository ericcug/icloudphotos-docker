"""Unit tests for Telegram Bot controller."""

from unittest.mock import MagicMock, patch

from control.telegram_bot import TelegramController
from enum import Enum


class SyncState(Enum):
    IDLE = "idle"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    FAILED = "failed"


class TestTelegramController:
    """Test Telegram Bot command handling."""

    @patch("control.telegram_bot.requests.get")
    def test_poll_loop_processes_updates(self, mock_get):
        """Verify update polling calls Telegram API."""
        mock_get.return_value.json.return_value = {"ok": True, "result": []}

        engine = MagicMock()
        engine.state = SyncState.IDLE
        engine.downloader = MagicMock()
        engine.downloader.stats = {"downloaded": 10, "failed": 0}

        ctrl = TelegramController("token", "chat123", engine=engine)
        ctrl._check_updates()
        mock_get.assert_called_once()

    @patch("control.telegram_bot.requests.post")
    @patch("control.telegram_bot.requests.get")
    def test_pause_command(self, mock_get, mock_post):
        """Verify /pause command pauses engine."""
        mock_get.return_value.json.return_value = {
            "ok": True,
            "result": [{
                "update_id": 1,
                "message": {
                    "chat": {"id": 123},
                    "text": "/pause",
                },
            }],
        }
        mock_post.return_value.status_code = 200

        engine = MagicMock()
        engine.state = SyncState.IDLE

        ctrl = TelegramController("token", "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        engine.pause.assert_called_once()

    @patch("control.telegram_bot.requests.post")
    @patch("control.telegram_bot.requests.get")
    def test_resume_command(self, mock_get, mock_post):
        """Verify /resume command resumes engine."""
        mock_get.return_value.json.return_value = {
            "ok": True,
            "result": [{
                "update_id": 1,
                "message": {
                    "chat": {"id": 123},
                    "text": "/resume",
                },
            }],
        }
        mock_post.return_value.status_code = 200

        engine = MagicMock()
        engine.state = SyncState.PAUSED

        ctrl = TelegramController("token", "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        engine.resume.assert_called_once()

    @patch("control.telegram_bot.requests.post")
    @patch("control.telegram_bot.requests.get")
    def test_sync_command(self, mock_get, mock_post):
        """Verify /sync command triggers immediate sync."""
        mock_get.return_value.json.return_value = {
            "ok": True,
            "result": [{
                "update_id": 1,
                "message": {
                    "chat": {"id": 123},
                    "text": "/sync",
                },
            }],
        }
        mock_post.return_value.status_code = 200

        engine = MagicMock()
        ctrl = TelegramController("token", "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        engine.sync_now.assert_called_once()

    @patch("control.telegram_bot.requests.post")
    @patch("control.telegram_bot.requests.get")
    def test_status_command(self, mock_get, mock_post):
        """Verify /status command reports state."""
        mock_get.return_value.json.return_value = {
            "ok": True,
            "result": [{
                "update_id": 1,
                "message": {
                    "chat": {"id": 123},
                    "text": "/status",
                },
            }],
        }
        mock_post.return_value.status_code = 200

        engine = MagicMock()
        engine.state = SyncState.DOWNLOADING
        engine.downloader = MagicMock()
        engine.downloader.stats = {"downloaded": 42, "failed": 3}

        ctrl = TelegramController("token", "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        # Verify reply was sent with status info
        assert mock_post.called

    def test_disabled_when_no_credentials(self):
        ctrl = TelegramController("", "")
        assert ctrl.enabled is False

    def test_enabled_with_credentials(self):
        ctrl = TelegramController("token", "chat123")
        assert ctrl.enabled is True

    @patch("control.telegram_bot.requests.post")
    @patch("control.telegram_bot.requests.get")
    def test_mfa_code_detection(self, mock_get, mock_post):
        """Verify 6-digit code is detected as MFA."""
        mock_get.return_value.json.return_value = {
            "ok": True,
            "result": [{
                "update_id": 1,
                "message": {
                    "chat": {"id": 123},
                    "text": "123456",
                },
            }],
        }
        mock_post.return_value.status_code = 200

        mfa_provider = MagicMock()

        ctrl = TelegramController("token", "123", mfa_provider=mfa_provider)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        mfa_provider.provide_code.assert_called_once_with("123456")

    @patch("control.telegram_bot.requests.get")
    def test_unauthorized_chat_ignored(self, mock_get):
        """Verify messages from unauthorized chats are ignored (FR-023)."""
        mock_get.return_value.json.return_value = {
            "ok": True,
            "result": [{
                "update_id": 1,
                "message": {
                    "chat": {"id": 999},  # Different from authorized 123
                    "text": "/pause",
                },
            }],
        }

        engine = MagicMock()
        ctrl = TelegramController("token", "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        engine.pause.assert_not_called()
