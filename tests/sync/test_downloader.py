"""Unit tests for Downloader."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pyicloud_ipd.services.photos import PhotoAsset
from pyicloud_ipd.version_size import AssetVersionSize

from sync.downloader import Downloader, RateLimitError


@pytest.fixture
def mock_wrapper():
    """Mock ICloudWrapper."""
    wrapper = MagicMock()
    wrapper.service = MagicMock()
    return wrapper


@pytest.fixture
def downloader(mock_wrapper):
    """Downloader instance with mocked wrapper."""
    return Downloader(
        wrapper=mock_wrapper,
        download_delay=0,
        retry_interval=0,  # Fast tests
        retry_count=3,
        download_resolution="unmodified",
    )


@pytest.fixture
def mock_asset():
    """Mock PhotoAsset."""
    asset = MagicMock(spec=PhotoAsset)
    asset.filename = "test.jpg"
    asset.versions = {AssetVersionSize.ORIGINAL: "url"}
    return asset


class TestDownloader:
    @patch("sync.downloader.Downloader._do_download")
    def test_download_file_success_first_try(self, mock_do_download, downloader, mock_asset, tmp_path):
        """Test successful download on first attempt."""
        target_path = tmp_path / "test.jpg"
        
        # Mock file creation for size stat
        def side_effect(*args):
            target_path.touch()
            target_path.write_text("dummy")
            return target_path
            
        mock_do_download.side_effect = side_effect
        
        result = downloader.download_file(mock_asset, target_path, {})
        
        assert result == target_path
        assert downloader.stats["downloaded"] == 1
        assert downloader.stats["failed"] == 0
        assert mock_do_download.call_count == 1

    @patch("sync.downloader.time.sleep")
    @patch("sync.downloader.Downloader._do_download")
    def test_download_file_retry_on_exception(self, mock_do_download, mock_sleep, downloader, mock_asset, tmp_path):
        """Test retry on normal exception."""
        target_path = tmp_path / "test.jpg"
        
        # Fail twice, succeed on third
        mock_do_download.side_effect = [
            Exception("Network error"),
            Exception("Network error"),
            target_path,
        ]
        
        result = downloader.download_file(mock_asset, target_path, {})
        
        assert result == target_path
        assert mock_do_download.call_count == 3
        # Should sleep twice before retry
        assert mock_sleep.call_count == 2

    @patch("sync.downloader.time.sleep")
    @patch("sync.downloader.Downloader._do_download")
    def test_download_file_fails_after_retries(self, mock_do_download, mock_sleep, downloader, mock_asset, tmp_path):
        """Test failure after max retries."""
        target_path = tmp_path / "test.jpg"
        
        mock_do_download.side_effect = Exception("Persistent error")
        
        result = downloader.download_file(mock_asset, target_path, {})
        
        assert result is None
        assert mock_do_download.call_count == 3
        assert downloader.stats["failed"] == 1
        assert downloader.stats["downloaded"] == 0

    @patch("sync.downloader.time.sleep")
    @patch("sync.downloader.Downloader._do_download")
    def test_download_file_rate_limit(self, mock_do_download, mock_sleep, downloader, mock_asset, tmp_path):
        """Test 429 rate limit triggers delay increase."""
        target_path = tmp_path / "test.jpg"
        downloader.current_delay = 10
        downloader.download_delay = 10
        
        # 429 on first, success on second
        mock_do_download.side_effect = [
            RateLimitError("HTTP 429"),
            target_path,
        ]
        
        result = downloader.download_file(mock_asset, target_path, {})
        
        assert result == target_path
        assert mock_do_download.call_count == 2
        # Delay should double: 10 -> 20
        assert downloader.current_delay == 20

    @patch("sync.downloader.os.statvfs")
    def test_check_disk_space(self, mock_statvfs, downloader, tmp_path):
        """Test disk space check does not throw exceptions."""
        mock_stat = MagicMock()
        mock_stat.f_frsize = 1024
        mock_stat.f_bavail = 10  # 10KB free -> Warning
        mock_statvfs.return_value = mock_stat
        
        target = tmp_path / "test.jpg"
        target.touch()
        
        downloader._check_disk_space(target)
        # Should just log, no exception raised

    @patch("sync.downloader.Downloader._do_download")
    def test_download_delay_enforced(self, mock_do_download, mock_asset, mock_wrapper, tmp_path):
        """Test download_delay is enforced before do_download."""
        downloader = Downloader(
            wrapper=mock_wrapper,
            download_delay=1,  # 1 second delay
            retry_count=1,
        )
        
        target = tmp_path / "test.jpg"
        mock_do_download.return_value = target
        
        with patch("sync.downloader.time.sleep") as mock_sleep:
            downloader.download_file(mock_asset, target, {})
            # Sleep should be called for current_delay before download
            mock_sleep.assert_called_once_with(1)

    @patch("icloudpd.download.download_media")
    def test_do_download_success(self, mock_download_media, downloader, mock_asset, tmp_path):
        """Test _do_download uses download_media correctly."""
        mock_download_media.return_value = True
        target = tmp_path / "test.jpg"
        
        result = downloader._do_download(mock_asset, target)
        
        assert result == target
        mock_download_media.assert_called_once()
        assert mock_download_media.call_args[1]["version"] == "url"

    @patch("icloudpd.download.download_media")
    def test_do_download_raises_rate_limit(self, mock_download_media, downloader, mock_asset, tmp_path):
        """Test HTTP 429 from download_media is translated to RateLimitError."""
        mock_download_media.side_effect = Exception("HTTP 429 Too Many Requests")
        target = tmp_path / "test.jpg"
        
        with pytest.raises(RateLimitError):
            downloader._do_download(mock_asset, target)
