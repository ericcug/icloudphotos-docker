"""Tests for pre-flight disk space safety check."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from sync.engine import SyncEngine


def test_preflight_passes_when_disk_space_sufficient(tmp_path):
    config = MagicMock()
    config.cookie_dir = tmp_path / "cookies"
    config.download_path = tmp_path / "photos"
    config.min_free_disk_bytes = 1000
    config.xmp_sidecar = False

    config.cookie_dir.mkdir(parents=True, exist_ok=True)
    config.download_path.mkdir(parents=True, exist_ok=True)

    engine = SyncEngine(config, MagicMock())

    # Mock statvfs with ample free blocks
    mock_stat = MagicMock(f_frsize=4096, f_bavail=1000000)
    with patch("os.statvfs", return_value=mock_stat):
        assert engine._check_preflight_disk() is True


def test_preflight_fails_when_config_volume_critically_low(tmp_path):
    config = MagicMock()
    config.cookie_dir = tmp_path / "cookies"
    config.download_path = tmp_path / "photos"
    config.min_free_disk_bytes = 1000
    config.xmp_sidecar = False

    config.cookie_dir.mkdir(parents=True, exist_ok=True)
    config.download_path.mkdir(parents=True, exist_ok=True)

    event_bus = MagicMock()
    engine = SyncEngine(config, MagicMock())
    engine.set_event_bus(event_bus)

    # Free bytes = 4096 * 10 = 40960 (< 1MB)
    mock_stat = MagicMock(f_frsize=4096, f_bavail=10)
    with patch("os.statvfs", return_value=mock_stat):
        assert engine._check_preflight_disk() is False
        assert event_bus.publish.called


def test_preflight_fails_when_download_volume_low(tmp_path):
    config = MagicMock()
    config.cookie_dir = tmp_path / "cookies"
    config.download_path = tmp_path / "photos"
    config.min_free_disk_bytes = 10000000  # 10MB
    config.xmp_sidecar = False

    config.cookie_dir.mkdir(parents=True, exist_ok=True)
    config.download_path.mkdir(parents=True, exist_ok=True)

    event_bus = MagicMock()
    engine = SyncEngine(config, MagicMock())
    engine.set_event_bus(event_bus)

    def mock_statvfs(path):
        if "cookies" in str(path):
            return MagicMock(f_frsize=4096, f_bavail=1000)  # 4MB > 1MB
        return MagicMock(f_frsize=4096, f_bavail=10)  # 40KB < 10MB

    with patch("os.statvfs", side_effect=mock_statvfs):
        assert engine._check_preflight_disk() is False
        assert event_bus.publish.called
