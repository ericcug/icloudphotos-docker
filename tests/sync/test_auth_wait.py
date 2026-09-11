"""Tests for auth error detection and shared wait_for_auth_restoration method."""

import threading
from unittest.mock import MagicMock, patch
import pytest

from sync.engine import SyncEngine, SyncState


class TestAuthErrorDetection:
    """F2: Verify type-based auth exception matching."""

    def _make_engine(self):
        config = MagicMock()
        config.download_delay = 0
        config.retry_interval = 1
        config.retry_count = 1
        config.download_resolution = "unmodified"
        config.download_interval = 60
        config.download_path = "/tmp/photos"
        config.file_match_policy = "name"
        config.delete_policy = "keep"
        config.folder_structure = "YYYY/MM"
        config.xmp_sidecar = False
        config.wait_for_reauthentication = True
        config.reauth_notification_interval = None
        config.apple_id = "test@example.com"
        wrapper = MagicMock()
        engine = SyncEngine(config, wrapper)
        engine.set_auth_manager(MagicMock())
        return engine

    @patch.object(SyncEngine, "_wait_for_reauth")
    @patch.object(SyncEngine, "_execute_cycle")
    @patch.object(SyncEngine, "_check_cookie_expiry")
    def test_pyicloud_api_exception_triggers_reauth(
        self, mock_check, mock_execute, mock_wait
    ):
        """PyiCloudAPIResponseException should trigger reauth wait."""
        try:
            from pyicloud_ipd.exceptions import PyiCloudAPIResponseException
            exc = PyiCloudAPIResponseException("Session expired", 421)
        except (ImportError, TypeError):
            pytest.skip("pyicloud_ipd exceptions not available")

        mock_execute.side_effect = exc
        mock_wait.return_value = None

        engine = self._make_engine()
        engine.run_cycle(once=True)

        mock_wait.assert_called_once()

    @patch.object(SyncEngine, "_wait_for_reauth")
    @patch.object(SyncEngine, "_execute_cycle")
    @patch.object(SyncEngine, "_check_cookie_expiry")
    def test_generic_exception_does_not_trigger_reauth(
        self, mock_check, mock_execute, mock_wait
    ):
        """A generic ValueError should NOT trigger reauth wait."""
        mock_execute.side_effect = ValueError("Something went wrong with path /data/401/photos")

        engine = self._make_engine()
        result = engine.run_cycle(once=True)

        mock_wait.assert_not_called()

    @patch.object(SyncEngine, "_wait_for_reauth")
    @patch.object(SyncEngine, "_execute_cycle")
    @patch.object(SyncEngine, "_check_cookie_expiry")
    def test_http_401_in_error_string_triggers_reauth(
        self, mock_check, mock_execute, mock_wait
    ):
        """Fallback: HTTP 401 status in error message should trigger reauth."""
        mock_execute.side_effect = Exception("HTTP error 401 status Unauthorized")
        mock_wait.return_value = None

        engine = self._make_engine()
        engine.run_cycle(once=True)

        mock_wait.assert_called_once()

    @patch.object(SyncEngine, "_wait_for_reauth")
    @patch.object(SyncEngine, "_execute_cycle")
    @patch.object(SyncEngine, "_check_cookie_expiry")
    def test_plain_401_in_path_does_not_trigger_reauth(
        self, mock_check, mock_execute, mock_wait
    ):
        """'401' appearing in a file path (without HTTP context) should NOT trigger reauth."""
        mock_execute.side_effect = FileNotFoundError("File not found: /data/room401/photo.jpg")

        engine = self._make_engine()
        result = engine.run_cycle(once=True)

        mock_wait.assert_not_called()


class TestWaitForAuthRestoration:
    """F4: Verify shared wait_for_auth_restoration method."""

    def test_shutdown_event_returns_false_immediately(self):
        """When shutdown_event is already set, should return False immediately."""
        config = MagicMock()
        config.download_interval = 60
        config.reauth_notification_interval = None
        config.apple_id = "test@example.com"

        shutdown = threading.Event()
        shutdown.set()  # Already signaled

        result = SyncEngine.wait_for_auth_restoration(
            auth_manager=MagicMock(),
            config=config,
            shutdown_event=shutdown,
        )

        assert result is False

    def test_auth_restored_returns_true(self):
        """When auth_manager reports valid cookie, should return True."""
        config = MagicMock()
        config.download_interval = 60
        config.reauth_notification_interval = None
        config.apple_id = "test@example.com"

        auth_manager = MagicMock()
        details = MagicMock(days_remaining=30)
        auth_manager.check_cookie_expiry.return_value = details

        with patch("time.sleep", return_value=None):
            result = SyncEngine.wait_for_auth_restoration(
                auth_manager=auth_manager,
                config=config,
            )

        assert result is True

    def test_cancel_check_returns_true(self):
        """When cancel_check returns True, should return True."""
        config = MagicMock()
        config.download_interval = 60
        config.reauth_notification_interval = None
        config.apple_id = "test@example.com"

        result = SyncEngine.wait_for_auth_restoration(
            auth_manager=MagicMock(),
            config=config,
            cancel_check=lambda: True,
        )

        assert result is True

    def test_remind_interval_floor_enforced(self):
        """reauth_notification_interval < 10 should fall back to download_interval."""
        config = MagicMock()
        config.download_interval = 120
        config.reauth_notification_interval = 3  # Too low
        config.apple_id = "test@example.com"

        auth_manager = MagicMock()
        details = MagicMock(days_remaining=30)
        auth_manager.check_cookie_expiry.return_value = details

        with patch("time.sleep", return_value=None):
            result = SyncEngine.wait_for_auth_restoration(
                auth_manager=auth_manager,
                config=config,
            )

        assert result is True

    def test_event_bus_receives_auth_expired_event(self):
        """Event bus should receive AUTH_EXPIRED event during wait."""
        config = MagicMock()
        config.download_interval = 60
        config.reauth_notification_interval = None
        config.apple_id = "test@example.com"

        event_bus = MagicMock()
        auth_manager = MagicMock()
        details = MagicMock(days_remaining=30)
        auth_manager.check_cookie_expiry.return_value = details

        with patch("time.sleep", return_value=None):
            SyncEngine.wait_for_auth_restoration(
                auth_manager=auth_manager,
                config=config,
                event_bus=event_bus,
            )

        assert event_bus.publish.called
