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


def _make_service(updates=None):
    """Create a mock TelegramService."""
    svc = MagicMock()
    svc.is_running = True
    svc.get_updates.return_value = updates or []
    svc.send_message.return_value = True
    return svc


class TestTelegramController:
    """Test Telegram Bot command handling."""

    def test_poll_loop_processes_updates(self):
        """Verify update polling calls TelegramService."""
        svc = _make_service(updates=[])

        engine = MagicMock()
        engine.state = SyncState.IDLE
        engine.downloader = MagicMock()
        engine.downloader.stats = {"downloaded": 10, "failed": 0}

        ctrl = TelegramController(svc, "chat123", engine=engine)
        ctrl._check_updates()
        svc.get_updates.assert_called_once()

    def test_pause_command(self):
        """Verify /pause command pauses engine."""
        svc = _make_service(updates=[{
            "update_id": 1,
            "message": {
                "chat": {"id": 123},
                "text": "/pause",
            },
        }])

        engine = MagicMock()
        engine.state = SyncState.IDLE

        ctrl = TelegramController(svc, "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        engine.pause.assert_called_once()

    def test_resume_command(self):
        """Verify /resume command resumes engine."""
        svc = _make_service(updates=[{
            "update_id": 1,
            "message": {
                "chat": {"id": 123},
                "text": "/resume",
            },
        }])

        engine = MagicMock()
        engine.state = SyncState.PAUSED

        ctrl = TelegramController(svc, "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        engine.resume.assert_called_once()

    def test_sync_command(self):
        """Verify /sync command triggers immediate sync."""
        svc = _make_service(updates=[{
            "update_id": 1,
            "message": {
                "chat": {"id": 123},
                "text": "/sync",
            },
        }])

        engine = MagicMock()
        ctrl = TelegramController(svc, "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        engine.sync_now.assert_called_once()

    def test_status_command(self):
        """Verify /status command reports state."""
        svc = _make_service(updates=[{
            "update_id": 1,
            "message": {
                "chat": {"id": 123},
                "text": "/status",
            },
        }])

        engine = MagicMock()
        engine.state = SyncState.DOWNLOADING
        engine.downloader = MagicMock()
        engine.downloader.stats = {"downloaded": 42, "failed": 3}

        ctrl = TelegramController(svc, "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        # Verify reply was sent with status info
        assert svc.send_message.called

    def test_disabled_when_no_credentials(self):
        ctrl = TelegramController(None, "")
        assert ctrl.enabled is False

    def test_enabled_with_credentials(self):
        svc = _make_service()
        ctrl = TelegramController(svc, "chat123")
        assert ctrl.enabled is True

    def test_mfa_code_detection(self):
        """Verify 6-digit code is detected as MFA."""
        svc = _make_service(updates=[{
            "update_id": 1,
            "message": {
                "chat": {"id": 123},
                "text": "123456",
            },
        }])

        mfa_provider = MagicMock()

        ctrl = TelegramController(svc, "123", mfa_provider=mfa_provider)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        mfa_provider.provide_code.assert_called_once_with("123456")

    def test_unauthorized_chat_ignored(self):
        """Verify messages from unauthorized chats are ignored (FR-023)."""
        svc = _make_service(updates=[{
            "update_id": 1,
            "message": {
                "chat": {"id": 999},  # Different from authorized 123
                "text": "/pause",
            },
        }])

        engine = MagicMock()
        ctrl = TelegramController(svc, "123", engine=engine)
        ctrl._last_update_id = 0
        ctrl._check_updates()

        engine.pause.assert_not_called()
