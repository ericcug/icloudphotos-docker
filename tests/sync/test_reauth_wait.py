"""Tests for wait_for_reauthentication behavior."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from sync.engine import SyncEngine, SyncState, WAITING_FOR_AUTH_MARKER


def test_wait_for_reauth_lifecycle(tmp_path):
    config = MagicMock()
    config.apple_id = "test@example.com"
    config.wait_for_reauthentication = True
    config.download_interval = 60
    config.reauth_notification_interval = 2
    config.cookie_dir = tmp_path / "cookies"
    config.download_path = tmp_path / "photos"
    config.xmp_sidecar = False

    wrapper = MagicMock()
    engine = SyncEngine(config, wrapper)

    auth_manager = MagicMock()
    engine.set_auth_manager(auth_manager)

    event_bus = MagicMock()
    engine.set_event_bus(event_bus)

    # Initially expired (days_remaining = 0)
    details_expired = MagicMock(days_remaining=0, mfa_expire_date="2026-09-11")
    # Later refreshed (days_remaining = 30)
    details_restored = MagicMock(days_remaining=30, mfa_expire_date="2026-10-11")

    call_count = 0
    def mock_check_expiry():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return details_expired
        return details_restored

    auth_manager.check_cookie_expiry.side_effect = mock_check_expiry

    # Run _wait_for_reauth
    with patch("time.sleep", return_value=None):
        engine._wait_for_reauth()

    # Should have recovered to IDLE
    assert engine.state == SyncState.IDLE
    # Marker file should be removed
    assert not WAITING_FOR_AUTH_MARKER.exists()
    # Event should have been published
    assert event_bus.publish.called
