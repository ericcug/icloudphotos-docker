"""Tests for keep_icloud_recent_days cloud retention policy."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest

from sync.engine import SyncEngine


def test_retention_skipped_if_keep_icloud_recent_only_false():
    config = MagicMock()
    config.keep_icloud_recent_days = 30
    config.keep_icloud_recent_only = False
    config.max_deletions_per_run = 10
    config.download_delay = 0
    config.xmp_sidecar = False

    wrapper = MagicMock()
    engine = SyncEngine(config, wrapper)

    # Assets older than 30 days
    old_date = datetime.now(timezone.utc) - timedelta(days=60)
    asset = MagicMock(created=old_date)
    cloud_assets = [{"record_name": "rec1", "filename": "old.jpg", "created_at": old_date.isoformat()}]
    asset_map = {"rec1": asset}

    deleted = engine._apply_cloud_retention(cloud_assets, asset_map, max_deletions=10)
    # Because keep_icloud_recent_only is False, 0 should be deleted
    assert deleted == 0
    assert not wrapper.delete_asset.called


def test_retention_deletes_old_assets_when_enabled():
    config = MagicMock()
    config.keep_icloud_recent_days = 30
    config.keep_icloud_recent_only = True
    config.max_deletions_per_run = 10
    config.download_delay = 0
    config.xmp_sidecar = False

    wrapper = MagicMock()
    wrapper.delete_asset.return_value = True
    engine = SyncEngine(config, wrapper)

    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=40)
    new_date = now - timedelta(days=5)

    old_asset = MagicMock(created=old_date)
    new_asset = MagicMock(created=new_date)

    cloud_assets = [
        {"record_name": "old1", "filename": "old.jpg", "created_at": old_date.isoformat()},
        {"record_name": "new1", "filename": "new.jpg", "created_at": new_date.isoformat()},
    ]
    asset_map = {"old1": old_asset, "new1": new_asset}

    deleted = engine._apply_cloud_retention(cloud_assets, asset_map, max_deletions=10)
    assert deleted == 1
    wrapper.delete_asset.assert_called_once_with(old_asset)
