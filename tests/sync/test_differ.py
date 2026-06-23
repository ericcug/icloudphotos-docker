"""Unit tests for MetadataDiffer."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sync.differ import MetadataDiffer


@pytest.fixture
def base_differ(tmp_path):
    """Fixture to provide a basic MetadataDiffer instance."""
    return MetadataDiffer(
        download_path=tmp_path,
        file_match_policy="name",
        delete_policy="keep",
        folder_structure="YYYY/MM",
    )


@pytest.fixture
def mock_cloud_assets():
    """Mock cloud assets for testing."""
    return [
        {
            "record_name": "rec1",
            "filename": "photo1.jpg",
            "created_at": "2026-06-20T12:00:00Z",
            "size_bytes": 1000,
        },
        {
            "record_name": "rec2",
            "filename": "photo2.jpg",
            "created_at": "2026-06-21T12:00:00Z",
            "size_bytes": 2000,
        },
        {
            "record_name": "rec3",
            "filename": "video1.mp4",
            "created_at": "invalid_date",
            "size_bytes": 5000,
        },
    ]


class TestMetadataDiffer:
    def test_get_target_path(self, base_differ):
        """Test target path generation handles various formats."""
        asset = {
            "record_name": "rec1",
            "filename": "test.jpg",
            "created_at": "2026-06-20T12:00:00Z",
        }
        
        base_differ.folder_structure = "YYYY/MM"
        path1 = base_differ.get_target_path(asset)
        assert path1 == base_differ.download_path / "2026" / "06" / "test.jpg"
        
        base_differ.folder_structure = "YYYY-MM-DD"
        path2 = base_differ.get_target_path(asset)
        assert path2 == base_differ.download_path / "2026-06-20" / "test.jpg"
        
        base_differ.folder_structure = "none"
        path3 = base_differ.get_target_path(asset)
        assert path3 == base_differ.download_path / "" / "test.jpg"

    def test_get_target_path_invalid_date(self, base_differ):
        """Test target path with invalid date uses fallback."""
        asset = {
            "record_name": "rec1",
            "filename": "test.jpg",
            "created_at": "invalid",
        }
        path = base_differ.get_target_path(asset)
        assert path == base_differ.download_path / "unknown_date" / "test.jpg"

    def test_compute_diff_all_new(self, base_differ, mock_cloud_assets):
        """Test compute_diff when local dir is empty."""
        diffs = base_differ.compute_diff(mock_cloud_assets)
        
        assert len(diffs) == 3
        for d in diffs:
            assert d.status == "new"
            assert d.local_path is None

    def test_compute_diff_unchanged_name_policy(self, base_differ, mock_cloud_assets):
        """Test compute_diff with name policy identifies unchanged files."""
        # Create local file for rec1
        path1 = base_differ.get_target_path(mock_cloud_assets[0])
        path1.parent.mkdir(parents=True, exist_ok=True)
        path1.write_text("dummy")
        
        diffs = base_differ.compute_diff(mock_cloud_assets)
        
        diff_rec1 = next(d for d in diffs if d.record_name == "rec1")
        assert diff_rec1.status == "unchanged"
        assert diff_rec1.local_path == path1
        
        diff_rec2 = next(d for d in diffs if d.record_name == "rec2")
        assert diff_rec2.status == "new"

    def test_compute_diff_modified_size_policy(self, base_differ, mock_cloud_assets):
        """Test compute_diff with size policy identifies modified files."""
        base_differ.file_match_policy = "size"
        
        # Create local file for rec1 with WRONG size
        path1 = base_differ.get_target_path(mock_cloud_assets[0])
        path1.parent.mkdir(parents=True, exist_ok=True)
        path1.write_text("a" * 500)  # 500 bytes != 1000 bytes
        
        # We need to manually provide local_index because the size policy
        # currently relies on a lookup key. For size policy, key = record_name.
        # But _build_local_index currently only supports name policy.
        # We'll pass the index directly.
        local_index = {"rec1": path1}
        
        diffs = base_differ.compute_diff(mock_cloud_assets, local_index=local_index)
        
        diff_rec1 = next(d for d in diffs if d.record_name == "rec1")
        assert diff_rec1.status == "modified"
        assert diff_rec1.local_path == path1

    def test_compute_diff_deleted_remotely(self, base_differ):
        """Test compute_diff detects remotely deleted files when policy is not keep."""
        base_differ.delete_policy = "delete"
        
        cloud_assets = []  # Empty cloud
        
        # Local file exists
        local_path = base_differ.download_path / "2026" / "06" / "deleted.jpg"
        local_index = {"2026/06/deleted": local_path}
        
        diffs = base_differ.compute_diff(cloud_assets, local_index=local_index)
        
        assert len(diffs) == 1
        assert diffs[0].status == "deleted_remotely"
        assert diffs[0].record_name == "2026/06/deleted"
        assert diffs[0].local_path == local_path

    def test_compute_diff_keep_policy_ignores_deleted(self, base_differ):
        """Test compute_diff with keep policy ignores remotely deleted files."""
        base_differ.delete_policy = "keep"
        
        cloud_assets = []
        local_path = base_differ.download_path / "2026" / "06" / "deleted.jpg"
        local_index = {"2026/06/deleted": local_path}
        
        diffs = base_differ.compute_diff(cloud_assets, local_index=local_index)
        
        assert len(diffs) == 0

    def test_build_local_index(self, base_differ):
        """Test building local index."""
        # Create some files
        p1 = base_differ.download_path / "2026" / "06" / "photo1.jpg"
        p2 = base_differ.download_path / "2026" / "07" / "photo2.mp4"
        p1.parent.mkdir(parents=True, exist_ok=True)
        p2.parent.mkdir(parents=True, exist_ok=True)
        p1.touch()
        p2.touch()
        
        index = base_differ._build_local_index()
        
        assert "2026/06/photo1" in index
        assert index["2026/06/photo1"] == p1
        assert "2026/07/photo2" in index
        assert index["2026/07/photo2"] == p2
