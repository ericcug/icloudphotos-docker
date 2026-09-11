"""Tests for XMP sidecar generation in downloader."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from sync.downloader import Downloader


def test_downloader_calls_xmp_generation_when_enabled(tmp_path):
    wrapper = MagicMock()
    downloader = Downloader(
        wrapper=wrapper,
        download_delay=0,
        retry_interval=1,
        retry_count=1,
        xmp_sidecar=True,
    )

    from pyicloud_ipd.version_size import AssetVersionSize
    asset = MagicMock()
    asset.filename = "photo.jpg"
    asset.versions = {AssetVersionSize.ORIGINAL: MagicMock()}
    asset._asset_record = {"recordName": "rec1", "fields": {}}

    target_path = tmp_path / "photo.jpg"

    with patch("icloudpd.download.download_media", return_value=True):
        with patch("icloudpd.xmp_sidecar.generate_xmp_file") as mock_gen_xmp:
            res = downloader._do_download(asset, target_path)
            assert res == target_path
            mock_gen_xmp.assert_called_once()
