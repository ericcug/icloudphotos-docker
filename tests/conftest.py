"""Shared pytest fixtures for iCloud Docker tests."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config_dir():
    """Temporary config directory with example config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_config_dict():
    """Minimal valid configuration dictionary."""
    return {
        "apple_id": "test@example.com",
        "download_path": "/tmp/test_photos",
        "folder_structure": "YYYY/MM",
        "download_interval": 3600,
        "download_delay": 0,
        "retry_interval": 120,
        "retry_count": 3,
        "file_permissions": "644",
        "directory_permissions": "755",
        "keep_unicode": True,
        "set_exif_datetime": True,
        "file_match_policy": "name",
        "delete_policy": "keep",
        "icloud_china": False,
        "auth_china": False,
        "log_level": "info",
        "notification": {
            "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
            "webhook": {"enabled": False, "url": ""},
            "events": ["start", "complete", "error"],
        },
        "pipeline": {"steps": []},
    }


@pytest.fixture
def mock_icloud_service(mocker):
    """Mock PyiCloudService for testing without real iCloud."""
    mock = mocker.patch("pyicloud_ipd.base.PyiCloudService", autospec=True)
    mock_instance = mock.return_value
    mock_instance.authenticate.return_value = None
    return mock_instance


@pytest.fixture
def tmp_download_dir():
    """Temporary download directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
