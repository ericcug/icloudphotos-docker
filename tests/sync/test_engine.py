"""Unit tests for SyncEngine."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from notify.bus import EventType
from sync.differ import AssetDiff
from sync.engine import SyncEngine, SyncState


@pytest.fixture
def mock_config():
    """Mock application configuration."""
    config = MagicMock()
    config.download_path = "/tmp"
    config.file_match_policy = "name"
    config.delete_policy = "keep"
    config.folder_structure = "YYYY/MM"
    config.download_delay = 0
    config.retry_interval = 0
    config.retry_count = 1
    config.download_resolution = "unmodified"
    config.download_interval = 1
    config.delete_after_download = False
    config.max_deletions_per_run = 100
    return config


@pytest.fixture
def mock_wrapper():
    """Mock ICloudWrapper."""
    wrapper = MagicMock()
    # Mock photos generator
    wrapper.photos = []
    return wrapper


@pytest.fixture
def mock_differ():
    """Mock MetadataDiffer."""
    differ = MagicMock()
    differ.compute_diff.return_value = []
    differ.get_target_path.return_value = MagicMock()
    return differ


@pytest.fixture
def mock_downloader():
    """Mock Downloader."""
    downloader = MagicMock()
    downloader.download_file.return_value = MagicMock()
    return downloader


@pytest.fixture
def engine(mock_config, mock_wrapper, mock_differ, mock_downloader):
    """SyncEngine with mocked dependencies."""
    eng = SyncEngine(mock_config, mock_wrapper)
    eng.differ = mock_differ
    eng.downloader = mock_downloader
    # Mock RECOVERY_BACKOFF for faster tests
    eng.RECOVERY_BACKOFF = [0, 0, 0]
    return eng


class TestSyncEngine:
    def test_run_cycle_no_assets(self, engine):
        """Test a cycle where there are no new/modified assets."""
        summary = engine.run_cycle(once=True)
        
        assert summary["processed"] == 0
        assert summary["state"] == "idle"
        assert engine.state == SyncState.IDLE
        engine.downloader.download_file.assert_not_called()

    def test_run_cycle_with_new_assets(self, engine, mock_wrapper, mock_differ, mock_downloader):
        """Test a cycle where new assets are downloaded."""
        asset_meta = {"record_name": "rec1", "filename": "test.jpg", "media_type": "photo"}
        mock_wrapper.photos = [MagicMock()]
        mock_wrapper.get_asset_metadata.return_value = asset_meta
        
        diff = AssetDiff(record_name="rec1", status="new", cloud_metadata=asset_meta)
        mock_differ.compute_diff.return_value = [diff]
        
        # Mock file return from downloader
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.stat().st_size = 1024
        mock_downloader.download_file.return_value = mock_path
        
        summary = engine.run_cycle(once=True)
        
        assert summary["processed"] == 1
        assert summary["failed"] == 0
        assert summary["photos"] == 1
        assert summary["total_bytes"] == 1024
        mock_downloader.download_file.assert_called_once()

    def test_run_cycle_with_failed_download(self, engine, mock_wrapper, mock_differ, mock_downloader):
        """Test a cycle where downloading an asset fails."""
        asset_meta = {"record_name": "rec1"}
        mock_wrapper.photos = [MagicMock()]
        mock_wrapper.get_asset_metadata.return_value = asset_meta
        
        diff = AssetDiff(record_name="rec1", status="new", cloud_metadata=asset_meta)
        mock_differ.compute_diff.return_value = [diff]
        
        mock_downloader.download_file.return_value = None  # Failed
        
        summary = engine.run_cycle(once=True)
        
        assert summary["processed"] == 0
        assert summary["failed"] == 1

    def test_run_cycle_crash_recovery(self, engine, mock_wrapper):
        """Test crash recovery retries and then fails."""
        mock_wrapper.get_asset_metadata.side_effect = Exception("API Error")
        mock_wrapper.photos = [MagicMock()]
        
        summary = engine.run_cycle(once=True)
        
        # Max attempts = 3. Since `once=True` in our wrapper but it's an exception,
        # it will retry up to MAX_RECOVERY_ATTEMPTS then break.
        # Wait, the `once=True` returns on the first success, OR on max attempts reached.
        assert "error" in summary
        assert summary["recovery_attempts"] == 4  # Initial + 3 retries
        assert engine.state == SyncState.FAILED

    def test_pause_and_resume(self, engine, mock_wrapper, mock_differ):
        """Test pausing and resuming the engine."""
        asset_meta = {"record_name": "rec1"}
        mock_wrapper.photos = [MagicMock()]
        mock_wrapper.get_asset_metadata.return_value = asset_meta
        
        diff = AssetDiff(record_name="rec1", status="new", cloud_metadata=asset_meta)
        mock_differ.compute_diff.return_value = [diff]
        
        # Mock resume_event so we can test it blocks/unblocks
        engine._resume_event = MagicMock()
        
        # Must be in a running state to be paused
        engine.state = SyncState.DOWNLOADING
        
        engine.pause()
        assert engine._pause_requested is True
        
        engine._check_pause()
        assert engine.state == SyncState.PAUSED
        engine._resume_event.clear.assert_called_once()
        engine._resume_event.wait.assert_called_once()
        
        engine.resume()
        assert engine.state == SyncState.IDLE
        assert engine._pause_requested is False
        engine._resume_event.set.assert_called_once()

    def test_delete_after_download(self, engine, mock_wrapper, mock_differ, mock_downloader):
        """Test delete_after_download calls wrapper.delete_asset."""
        engine.config.delete_after_download = True
        
        asset_meta = {"record_name": "rec1"}
        mock_asset = MagicMock()
        mock_wrapper.photos = [mock_asset]
        mock_wrapper.get_asset_metadata.return_value = asset_meta
        mock_wrapper.delete_asset.return_value = True
        
        diff = AssetDiff(record_name="rec1", status="new", cloud_metadata=asset_meta)
        mock_differ.compute_diff.return_value = [diff]
        mock_downloader.download_file.return_value = MagicMock()
        
        summary = engine.run_cycle(once=True)
        
        assert summary["processed"] == 1
        assert summary["deleted"] == 1
        mock_wrapper.delete_asset.assert_called_once_with(mock_asset)

    def test_post_processing_integration(self, engine, mock_wrapper, mock_differ, mock_downloader):
        """Test post-processing pipeline is invoked after download."""
        mock_pipeline = MagicMock()
        engine.set_pipeline_runner(mock_pipeline)
        
        asset_meta = {"record_name": "rec1"}
        mock_wrapper.photos = [MagicMock()]
        mock_wrapper.get_asset_metadata.return_value = asset_meta
        
        diff = AssetDiff(record_name="rec1", status="new", cloud_metadata=asset_meta)
        mock_differ.compute_diff.return_value = [diff]
        
        mock_file = MagicMock()
        mock_downloader.download_file.return_value = mock_file
        
        engine.run_cycle(once=True)
        
        mock_pipeline.process_file.assert_called_once_with(mock_file, asset_meta)

    def test_cookie_expiry_check(self, engine):
        """Test cookie expiry notification."""
        mock_auth = MagicMock()
        mock_bus = MagicMock()
        
        engine.set_auth_manager(mock_auth)
        engine.set_event_bus(mock_bus)
        
        # Expired
        details = MagicMock()
        details.days_remaining = 0
        details.mfa_expire_date = "2026-06-20"
        mock_auth.check_cookie_expiry.return_value = details
        
        engine._check_cookie_expiry()
        
        mock_bus.publish.assert_called_once()
        event = mock_bus.publish.call_args[0][0]
        assert event.event_type == EventType.AUTH_EXPIRED
