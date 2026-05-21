"""Metadata differ: compares iCloud photos with local filesystem.

Determines which photos need to be downloaded (new or modified) and
which local copies can be deleted (per delete_policy).
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AssetDiff:
    """Result of comparing a single iCloud asset with local filesystem.

    Attributes:
        record_name: iCloud unique identifier.
        status: One of: new, modified, unchanged, deleted_remotely.
        cloud_metadata: Metadata from iCloud.
        local_path: Path on local filesystem (if exists).
    """

    def __init__(self, record_name: str, status: str, cloud_metadata: dict, local_path: Optional[Path] = None):
        self.record_name = record_name
        self.status = status
        self.cloud_metadata = cloud_metadata
        self.local_path = local_path


class MetadataDiffer:
    """Compares iCloud photo library with local filesystem.

    Determines the difference set: which assets need downloading,
    which are up-to-date, and which should be deleted locally.

    Attributes:
        download_path: Root directory for local photos.
        file_match_policy: Strategy for matching files (name/size/checksum).
        delete_policy: Strategy for handling remotely deleted photos.
        folder_structure: Directory organization scheme.
    """

    def __init__(
        self,
        download_path: Path,
        file_match_policy: str = "name",
        delete_policy: str = "keep",
        folder_structure: str = "YYYY/MM",
    ):
        """Initialize the differ.

        Args:
            download_path: Root directory for downloaded photos.
            file_match_policy: How to match cloud↔local files.
            delete_policy: keep/delete/trash for remotely deleted files.
            folder_structure: Directory naming scheme.
        """
        self.download_path = Path(download_path)
        self.file_match_policy = file_match_policy
        self.delete_policy = delete_policy
        self.folder_structure = folder_structure

    def compute_diff(
        self, cloud_assets: List[dict], local_index: Optional[Dict[str, Path]] = None
    ) -> List[AssetDiff]:
        """Compute diff between cloud assets and local files.

        Args:
            cloud_assets: List of asset metadata dicts from iCloud.
            local_index: Pre-built local file index (optional; built if None).

        Returns:
            List of AssetDiff objects describing actions needed.
        """
        if local_index is None:
            local_index = self._build_local_index()

        cloud_keys = {a["record_name"] for a in cloud_assets}
        diffs = []

        # Check each cloud asset against local files
        for asset in cloud_assets:
            record_name = asset["record_name"]
            local_path = local_index.get(record_name)

            if local_path is None:
                diffs.append(AssetDiff(record_name, "new", asset))
            elif self._is_modified(asset, local_path):
                diffs.append(AssetDiff(record_name, "modified", asset, local_path))
            else:
                diffs.append(AssetDiff(record_name, "unchanged", asset, local_path))

        # Handle remotely deleted files
        if self.delete_policy != "keep":
            local_keys = set(local_index.keys())
            deleted_keys = local_keys - cloud_keys
            if deleted_keys:
                logger.info("Found %d remotely deleted assets (policy=%s)", len(deleted_keys), self.delete_policy)
                for key in deleted_keys:
                    diffs.append(AssetDiff(
                        key, "deleted_remotely",
                        {"record_name": key},
                        local_index[key],
                    ))

        new_count = sum(1 for d in diffs if d.status == "new")
        mod_count = sum(1 for d in diffs if d.status == "modified")
        del_count = sum(1 for d in diffs if d.status == "deleted_remotely")

        logger.info(
            "Diff complete: %d total, %d new, %d modified, %d deleted, %d unchanged",
            len(diffs), new_count, mod_count, del_count,
            len(diffs) - new_count - mod_count - del_count,
        )
        return diffs

    def _build_local_index(self) -> Dict[str, Path]:
        """Build an index of local files keyed by iCloud record_name.

        Scans the download directory and extracts metadata from filenames
        or sidecar files to map local files back to cloud assets.

        Returns:
            Dictionary mapping record_name → local file path.
        """
        index: Dict[str, Path] = {}
        if not self.download_path.exists():
            return index

        for root, _, files in os.walk(self.download_path):
            for filename in files:
                filepath = Path(root) / filename
                # Simple name-based matching (can be extended for checksum)
                if self.file_match_policy == "name":
                    # Use filename sans extension as record key
                    key = filepath.stem
                    index[key] = filepath
                # Future: size/checksum matching

        return index

    def _is_modified(self, cloud_asset: dict, local_path: Path) -> bool:
        """Check if a cloud asset has been modified since local download.

        Args:
            cloud_asset: Asset metadata from iCloud.
            local_path: Local file path.

        Returns:
            True if the cloud version is newer/different.
        """
        if not local_path.exists():
            return True

        if self.file_match_policy == "name":
            # Simple check: file exists with matching name → assume unchanged
            return False
        elif self.file_match_policy == "size":
            cloud_size = cloud_asset.get("size_bytes", 0)
            return local_path.stat().st_size != cloud_size
        elif self.file_match_policy == "checksum":
            # Future: SHA256 comparison
            return False

        return False

    def get_target_path(self, asset_metadata: dict) -> Path:
        """Compute the target download path for an asset.

        Args:
            asset_metadata: Asset metadata dict.

        Returns:
            Target file path on local filesystem.
        """
        created_str = asset_metadata.get("created_at", "")
        filename = asset_metadata.get("filename", "unknown.jpg")

        try:
            created = datetime.fromisoformat(created_str)
            if self.folder_structure == "YYYY/MM":
                subdir = created.strftime("%Y/%m")
            elif self.folder_structure == "YYYY/MM/DD":
                subdir = created.strftime("%Y/%m/%d")
            elif self.folder_structure == "YYYY-MM-DD":
                subdir = created.strftime("%Y-%m-%d")
            elif self.folder_structure == "album":
                subdir = asset_metadata.get("album", "unknown")
            else:
                subdir = ""
        except (ValueError, TypeError):
            subdir = "unknown_date"

        target_dir = self.download_path / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / filename
