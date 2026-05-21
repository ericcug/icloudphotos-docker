"""File downloader with retry, resume, and rate limiting.

Implements the docker-icloudpd fixed-delay pattern for download
throttling and retry logic.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from pyicloud_ipd.services.photos import PhotoAsset

logger = logging.getLogger(__name__)


class Downloader:
    """Downloads iCloud photo assets with configurable retry and delay.

    Uses the docker-icloudpd fixed-delay pattern:
    - download_delay: fixed seconds between each download
    - retry_interval: wait before retry on failure
    - On HTTP 429 (rate limited): doubles download_delay automatically

    Attributes:
        wrapper: ICloudWrapper for download operations.
        download_delay: Seconds between downloads (0 = no delay).
        retry_interval: Seconds to wait before retry on failure.
        retry_count: Maximum retries per file.
        current_delay: Current active delay (may change due to 429).
    """

    def __init__(
        self,
        wrapper,
        download_delay: int = 0,
        retry_interval: int = 120,
        retry_count: int = 3,
    ):
        """Initialize downloader.

        Args:
            wrapper: ICloudWrapper instance.
            download_delay: Fixed delay between downloads in seconds.
            retry_interval: Wait time before retry in seconds.
            retry_count: Max number of retries per file.
        """
        self.wrapper = wrapper
        self.download_delay = download_delay
        self.retry_interval = retry_interval
        self.retry_count = retry_count
        self.current_delay = download_delay
        self.stats = {"downloaded": 0, "failed": 0, "skipped": 0, "total_bytes": 0}

    def download_file(
        self, asset: PhotoAsset, target_path: Path, metadata: dict
    ) -> Optional[Path]:
        """Download a single asset with retry and delay.

        Args:
            asset: PhotoAsset to download.
            target_path: Destination file path.
            metadata: Asset metadata dict.

        Returns:
            Path to downloaded file, or None if failed after all retries.
        """
        # Check disk space before download (FR-004)
        self._check_disk_space(target_path)

        # Fixed delay before download (docker-icloudpd pattern)
        if self.current_delay > 0:
            logger.debug("Waiting %ds (download delay)...", self.current_delay)
            time.sleep(self.current_delay)

        for attempt in range(1, self.retry_count + 1):
            try:
                logger.debug(
                    "Downloading %s (attempt %d/%d) → %s",
                    asset.filename, attempt, self.retry_count, target_path,
                )

                result = self._do_download(asset, target_path)

                if result:
                    self.stats["downloaded"] += 1
                    self.stats["total_bytes"] += result.stat().st_size if result.exists() else 0
                    logger.info("Downloaded: %s", target_path.name)
                    return result

            except RateLimitError:
                # 429 response → double the delay (docker-icloudpd auto-adjust)
                old_delay = self.current_delay
                self.current_delay = max(self.current_delay * 2, self.download_delay * 2 or 60)
                logger.warning(
                    "Rate limited (429). Delay increased: %ds → %ds",
                    old_delay, self.current_delay,
                )
                if attempt < self.retry_count:
                    time.sleep(self.retry_interval)
                continue

            except Exception as e:
                logger.error("Download failed (attempt %d/%d): %s — %s",
                             attempt, self.retry_count, asset.filename, e)
                if attempt < self.retry_count:
                    logger.info("Retrying in %ds...", self.retry_interval)
                    time.sleep(self.retry_interval)
                else:
                    self.stats["failed"] += 1
                    return None

        self.stats["failed"] += 1
        return None

    def _do_download(self, asset: PhotoAsset, target_path: Path) -> Optional[Path]:
        """Perform the actual download using icloudpd's download_media.

        Leverages the submodule's built-in retry, resume (.part files),
        and checksum tracking for robust downloads.

        Args:
            asset: PhotoAsset to download.
            target_path: Destination file path.

        Returns:
            Path to downloaded file, or None if download failed.

        Raises:
            RateLimitError: Propagated from download_media on HTTP 429.
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from icloudpd.download import download_media
            from pyicloud_ipd.version_size import VersionSize

            versions = asset.versions
            original = versions.get(VersionSize.ORIGINAL)
            if not original:
                logger.warning("No original version available for %s", asset.filename)
                return None

            # download_media handles retry, resume, rate limiting, and session renewal
            success = download_media(
                logger=logging.getLogger("icloudpd"),
                dry_run=False,
                icloud=self.wrapper.service,
                photo=asset,
                download_path=str(target_path),
                version=original,
                size=VersionSize.ORIGINAL,
                filename_builder=lambda a: a.filename,
            )

            if success:
                return target_path
            else:
                logger.error("download_media failed for %s", asset.filename)
                return None

        except Exception as e:
            error_str = str(e)
            # Detect rate limiting to propagate as RateLimitError for auto-delay adjustment
            if "429" in error_str or "Too Many Requests" in error_str:
                raise RateLimitError(f"HTTP 429: {error_str}") from e
            logger.error("Download error: %s", e)
            raise

    def _check_disk_space(self, target_path: Path) -> None:
        """Check available disk space before download.

        Args:
            target_path: Destination path (used to determine filesystem).

        Logs a warning if space is low. Follows the "按需报错" assumption
        from the spec.
        """
        try:
            stat = os.statvfs(target_path.parent if target_path.parent.exists() else "/")
            free_bytes = stat.f_frsize * stat.f_bavail
            free_mb = free_bytes / (1024 * 1024)

            if free_mb < 1024:  # Less than 1GB
                logger.warning(
                    "Low disk space: %.0f MB available on %s",
                    free_mb, target_path.parent,
                )
        except Exception:
            pass  # Can't check, proceed anyway

    def reset_stats(self) -> None:
        """Reset download statistics."""
        self.stats = {"downloaded": 0, "failed": 0, "skipped": 0, "total_bytes": 0}


class RateLimitError(Exception):
    """Raised when iCloud API returns HTTP 429."""
    pass
