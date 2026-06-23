"""Unit tests for ICloudWrapper."""

from unittest.mock import MagicMock, patch

import pytest
from pyicloud_ipd.base import PyiCloudService
from pyicloud_ipd.services.photos import PhotoAsset
from pyicloud_ipd.version_size import AssetVersionSize, LivePhotoVersionSize

from sync.icloud_wrapper import ICloudWrapper


@pytest.fixture
def mock_service():
    """Mock PyiCloudService."""
    service = MagicMock(spec=PyiCloudService)
    service.photos = MagicMock()
    return service


@pytest.fixture
def wrapper(mock_service):
    """ICloudWrapper instance with mocked service."""
    return ICloudWrapper(mock_service)


@pytest.fixture
def mock_photo_asset():
    """Mock PhotoAsset."""
    asset = MagicMock(spec=PhotoAsset)
    asset.id = "photo_123"
    asset.filename = "IMG_1234.JPG"
    asset.size = 1024
    asset.created = "2026-06-23T12:00:00Z"
    asset.added_date = "2026-06-23T12:00:00Z"
    asset._asset_record = {"recordChangeTag": "123", "recordName": "rec123"}
    asset.versions = {AssetVersionSize.ORIGINAL: "url"}
    return asset


class TestICloudWrapper:
    def test_photos_generator(self, wrapper, mock_service, mock_photo_asset):
        """Test photos generator yields assets from PyiCloudService."""
        mock_service.photos.all = [mock_photo_asset]
        
        photos = list(wrapper.photos)
        
        assert len(photos) == 1
        assert photos[0] is mock_photo_asset

    @patch("icloudpd.download.download_media")
    def test_download_asset_success(self, mock_download_media, wrapper, mock_photo_asset):
        """Test successful download calls download_media correctly."""
        mock_download_media.return_value = True
        
        result = wrapper.download_asset(mock_photo_asset, "/tmp/IMG_1234.JPG")
        
        assert result == "/tmp/IMG_1234.JPG"
        mock_download_media.assert_called_once()
        args, kwargs = mock_download_media.call_args
        assert kwargs["photo"] == mock_photo_asset
        assert kwargs["download_path"] == "/tmp/IMG_1234.JPG"
        assert kwargs["version"] == "url"

    @patch("icloudpd.download.download_media")
    def test_download_asset_live_photo(self, mock_download_media, wrapper, mock_photo_asset):
        """Test download live photo uses LivePhotoVersionSize."""
        mock_download_media.return_value = True
        mock_photo_asset.versions = {LivePhotoVersionSize.ORIGINAL: "live_url"}
        
        result = wrapper.download_asset(mock_photo_asset, "/tmp/IMG_1234.MOV")
        
        assert result == "/tmp/IMG_1234.MOV"
        kwargs = mock_download_media.call_args[1]
        assert kwargs["version"] == "live_url"

    def test_download_asset_no_original(self, wrapper, mock_photo_asset):
        """Test download fails if no original version."""
        mock_photo_asset.versions = {"medium": "url"}
        
        with pytest.raises(ValueError, match="No original version"):
            wrapper.download_asset(mock_photo_asset, "/tmp/IMG.JPG")

    @patch("icloudpd.download.download_media")
    def test_download_asset_failure(self, mock_download_media, wrapper, mock_photo_asset):
        """Test download failure raises RuntimeError."""
        mock_download_media.return_value = False
        
        with pytest.raises(RuntimeError, match="Download failed"):
            wrapper.download_asset(mock_photo_asset, "/tmp/IMG.JPG")

    def test_get_asset_metadata_photo(self, wrapper, mock_photo_asset):
        """Test get_asset_metadata parses photo."""
        meta = wrapper.get_asset_metadata(mock_photo_asset)
        
        assert meta["record_name"] == "photo_123"
        assert meta["filename"] == "IMG_1234.JPG"
        assert meta["media_type"] == "photo"
        assert meta["size_bytes"] == 1024
        assert meta["created_at"] == "2026-06-23T12:00:00Z"
        assert meta["modified_at"] == "2026-06-23T12:00:00Z"

    def test_detect_media_type_video(self, wrapper, mock_photo_asset):
        """Test _detect_media_type detects video."""
        mock_photo_asset.filename = "video.MOV"
        assert wrapper._detect_media_type(mock_photo_asset) == "video"
        
        mock_photo_asset.filename = "video.mp4"
        assert wrapper._detect_media_type(mock_photo_asset) == "video"

    def test_detect_media_type_live_photo(self, wrapper, mock_photo_asset):
        """Test _detect_media_type detects live photo based on version."""
        mock_photo_asset.versions = {LivePhotoVersionSize.ORIGINAL: "url"}
        assert wrapper._detect_media_type(mock_photo_asset) == "live_photo"

    def test_delete_asset_success(self, wrapper, mock_service, mock_photo_asset):
        """Test delete_asset sends correct POST request."""
        mock_service.photos.service_endpoint = "https://endpoint"
        mock_service.photos.params = {"foo": "bar"}
        mock_service.photos.zone_id = "zone"
        
        mock_response = MagicMock()
        mock_response.ok = True
        mock_service.photos.session.post.return_value = mock_response
        
        result = wrapper.delete_asset(mock_photo_asset)
        
        assert result is True
        mock_service.photos.session.post.assert_called_once()
        args, kwargs = mock_service.photos.session.post.call_args
        assert "https://endpoint/records/modify?foo=bar" in args[0]
        assert "isDeleted" in kwargs["data"]

    def test_delete_asset_failure(self, wrapper, mock_service, mock_photo_asset):
        """Test delete_asset returns False on HTTP error."""
        mock_service.photos.service_endpoint = "https://endpoint"
        mock_service.photos.params = {}
        mock_service.photos.zone_id = "zone"
        
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_service.photos.session.post.return_value = mock_response
        
        result = wrapper.delete_asset(mock_photo_asset)
        
        assert result is False
