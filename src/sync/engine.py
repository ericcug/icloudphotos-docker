"""Core sync engine with state machine.

Coordinates the full sync cycle: authentication check → metadata diff →
download → post-processing. Implements crash recovery with exponential
backoff per the spec (FR-011).
"""

import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

from notify.bus import EventType, SystemEvent
from sync.differ import AssetDiff, MetadataDiffer
from sync.downloader import Downloader
from sync.icloud_wrapper import ICloudWrapper

# Import pyicloud auth exceptions for precise error matching
try:
    from pyicloud_ipd.exceptions import (
        PyiCloudAPIResponseException,
        PyiCloudFailedLoginException,
    )
    _AUTH_EXCEPTIONS = (PyiCloudAPIResponseException, PyiCloudFailedLoginException)
except ImportError:
    _AUTH_EXCEPTIONS = ()

logger = logging.getLogger(__name__)

WAITING_FOR_AUTH_MARKER = Path("/tmp/icloudpd/waiting_for_auth")


class SyncState(Enum):
    """Sync engine state machine states."""
    IDLE = "idle"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    WAITING = "waiting"
    WAITING_FOR_AUTH = "waiting_for_auth"
    PAUSED = "paused"
    FAILED = "failed"


class SyncEngine:
    """Orchestrates the iCloud photo synchronization cycle.

    State machine:
        IDLE → CHECKING → DOWNLOADING → PROCESSING → WAITING → IDLE
        Any state → PAUSED (on pause command)
        Any state → FAILED (on unrecoverable error)

    Crash recovery: auto-restart with exponential backoff (1m→5m→15m),
    max 3 retries (FR-011).

    Attributes:
        config: Application Config.
        wrapper: ICloudWrapper for iCloud API access.
        differ: MetadataDiffer for cloud↔local comparison.
        downloader: Downloader for file transfer.
        state: Current sync state.
        task: Current sync task metadata.
    """

    # Crash recovery configuration
    RECOVERY_BACKOFF = [60, 300, 900]  # 1min, 5min, 15min
    MAX_RECOVERY_ATTEMPTS = 3

    def __init__(self, config, wrapper: ICloudWrapper):
        """Initialize sync engine.

        Args:
            config: Application Config instance.
            wrapper: Initialized ICloudWrapper.
        """
        self.config = config
        self.wrapper = wrapper
        self.differ = MetadataDiffer(
            download_path=config.download_path,
            file_match_policy=config.file_match_policy,
            delete_policy=config.delete_policy,
            folder_structure=config.folder_structure,
        )
        self.downloader = Downloader(
            wrapper=wrapper,
            download_delay=config.download_delay,
            retry_interval=config.retry_interval,
            retry_count=config.retry_count,
            download_resolution=config.download_resolution,
            xmp_sidecar=getattr(config, "xmp_sidecar", False),
        )
        self.state = SyncState.IDLE
        self.task: Optional[dict] = None
        self._pause_requested = False
        self._resume_event = threading.Event()  # Replaces busy-wait for pause/resume
        self._event_bus = None  # Set via set_event_bus()
        self._auth_manager = None  # Set via set_auth_manager()
        self._pipeline_runner = None  # Set via set_pipeline_runner()

    def set_event_bus(self, event_bus) -> None:
        """Inject event bus for notifications (US3 integration)."""
        self._event_bus = event_bus

    def set_auth_manager(self, auth_manager) -> None:
        """Inject auth manager for cookie expiry checking."""
        self._auth_manager = auth_manager

    def set_pipeline_runner(self, runner) -> None:
        """Inject pipeline runner for post-processing (US2 integration)."""
        self._pipeline_runner = runner

    @property
    def is_paused(self) -> bool:
        """Check if sync is paused."""
        return self.state == SyncState.PAUSED

    def pause(self) -> None:
        """Request sync pause at next checkpoint."""
        logger.info("Pause requested — will pause at next checkpoint")
        self._pause_requested = True

    def resume(self) -> None:
        """Resume sync from paused state."""
        logger.info("Resuming sync from paused state")
        self._pause_requested = False
        if self.state == SyncState.PAUSED:
            self.state = SyncState.IDLE
            if self._event_bus:
                self._event_bus.publish(SystemEvent(
                    event_type=EventType.SYNC_RESUMED,
                    severity="info",
                    message="Sync engine resumed.",
                ))
            self._resume_event.set()

    def sync_now(self) -> None:
        """Trigger immediate sync cycle (override interval)."""
        logger.info("Immediate sync requested")
        self.state = SyncState.IDLE

    def run_cycle(self, once: bool = False) -> dict:
        """Execute a complete sync cycle with crash recovery.

        Args:
            once: If True, run single cycle and return.

        Returns:
            Task summary dict with statistics.
        """
        recovery_attempt = 0

        while True:
            try:
                # Check cookie expiry before every cycle
                self._check_cookie_expiry()

                if self.state == SyncState.WAITING_FOR_AUTH:
                    if getattr(self.config, "wait_for_reauthentication", True):
                        self._wait_for_reauth()
                    else:
                        break

                self._check_pause()
                if self.state == SyncState.PAUSED:
                    # Block until resumed instead of busy-waiting
                    self._resume_event.wait(timeout=5)
                    continue

                result = self._execute_cycle()

                if once:
                    return result

                # Reset recovery counter on success
                recovery_attempt = 0

                # Wait for next interval
                self.state = SyncState.WAITING
                self._wait_interval()

            except Exception as e:
                is_auth_error = isinstance(e, _AUTH_EXCEPTIONS)
                if not is_auth_error:
                    # Fallback: check HTTP status codes in exception message
                    err_str = str(e)
                    is_auth_error = any(
                        code in err_str for code in ("401", "421", "403")
                    ) and ("HTTP" in err_str or "status" in err_str.lower())

                if is_auth_error and getattr(self.config, "wait_for_reauthentication", True):
                    logger.warning(
                        "Authentication error in sync cycle: %s. Holding for re-authentication.",
                        e,
                    )
                    self._wait_for_reauth()
                    if once:
                        return {"error": "Authentication required", "state": self.state.value}
                    continue

                logger.error("Sync cycle failed: %s", e, exc_info=True)
                recovery_attempt += 1

                if recovery_attempt > self.MAX_RECOVERY_ATTEMPTS:
                    logger.critical(
                        "Max recovery attempts (%d) reached. Stopping.",
                        self.MAX_RECOVERY_ATTEMPTS,
                    )
                    self.state = SyncState.FAILED
                    if self._event_bus:
                        self._event_bus.publish(SystemEvent(
                            event_type=EventType.ERROR,
                            severity="critical",
                            message=f"Sync failed after {recovery_attempt} attempts: {e}",
                        ))
                    if once:
                        return {"error": str(e), "recovery_attempts": recovery_attempt}
                    break

                delay = self.RECOVERY_BACKOFF[min(recovery_attempt - 1, len(self.RECOVERY_BACKOFF) - 1)]
                logger.warning(
                    "Recovery attempt %d/%d — waiting %ds before retry...",
                    recovery_attempt, self.MAX_RECOVERY_ATTEMPTS, delay,
                )
                time.sleep(delay)
                self.state = SyncState.IDLE

        return {"error": "Max recovery attempts exceeded"}

    def _execute_cycle(self) -> dict:
        """Execute a single sync cycle.

        Returns:
            Task summary dict.
        """
        logger.info("="  * 40)
        logger.info("Sync cycle started")
        start_time = datetime.now(timezone.utc)

        # Phase 1: Check iCloud connection and build asset map
        self.state = SyncState.CHECKING
        logger.info("Phase: CHECKING — fetching cloud metadata...")
        cloud_assets = []
        asset_map: Dict[str, object] = {}  # record_name → PhotoAsset
        for asset in self.wrapper.photos:
            if self._pause_requested:
                self._handle_pause()
            metadata = self.wrapper.get_asset_metadata(asset)
            cloud_assets.append(metadata)
            asset_map[metadata["record_name"]] = asset

        # Phase 2: Compute diff
        diffs = self.differ.compute_diff(cloud_assets)
        download_count = sum(1 for d in diffs if d.status in ("new", "modified"))
        delete_count = sum(1 for d in diffs if d.status == "deleted_remotely")
        total_cloud = len(cloud_assets)

        if download_count == 0 and delete_count == 0:
            logger.info("No new, modified, or remotely deleted assets to process")
            self.state = SyncState.IDLE
            return self._build_summary(start_time, 0, 0, total_cloud=total_cloud)

        # Pre-flight disk space check (docker-icloudpd preflight check)
        if not self._check_preflight_disk():
            logger.warning("Pre-flight disk check failed. Skipping download.")
            self.state = SyncState.IDLE
            return self._build_summary(start_time, 0, 0, total_cloud=total_cloud)

        # Phase 3: Download & Cleanup
        self.state = SyncState.DOWNLOADING
        self.downloader.reset_stats()
        logger.info("Phase: DOWNLOADING — %d to download, %d to clean up", download_count, delete_count)

        processed = 0
        failed = 0
        deleted_count = 0
        limit_reached_logged = False
        # Track media type breakdown for summary notification
        media_counts: Dict[str, int] = {"photo": 0, "video": 0, "live_photo": 0}
        total_bytes_downloaded = 0

        for diff in diffs:
            if self._pause_requested:
                self._handle_pause()

            if diff.status == "deleted_remotely":
                if self.config.delete_policy in ("delete", "trash"):
                    try:
                        if self.config.delete_policy == "trash":
                            trash_dir = self.config.download_path / ".trash"
                            trash_dir.mkdir(parents=True, exist_ok=True)
                            if diff.local_path and diff.local_path.exists():
                                trash_path = trash_dir / diff.local_path.name
                                shutil.move(str(diff.local_path), str(trash_path))
                                logger.info("Trashed local file: %s", diff.local_path.name)
                        else:
                            if diff.local_path and diff.local_path.exists():
                                diff.local_path.unlink()
                                logger.info("Deleted local file: %s", diff.local_path.name)
                    except Exception as e:
                        logger.error("Failed to remove local file %s: %s", diff.local_path, e)
                continue

            if diff.status not in ("new", "modified"):
                continue

            target_path = self.differ.get_target_path(diff.cloud_metadata)

            # Resolve the original PhotoAsset from the asset map
            photo_asset = asset_map.get(diff.record_name)
            if photo_asset is None:
                logger.warning(
                    "No PhotoAsset found for record_name=%s, skipping",
                    diff.record_name,
                )
                failed += 1
                continue

            result = self.downloader.download_file(
                asset=photo_asset,
                target_path=target_path,
                metadata=diff.cloud_metadata,
            )

            if result:
                processed += 1
                # Track media type for completion summary
                media_type = diff.cloud_metadata.get("media_type", "photo")
                media_counts[media_type] = media_counts.get(media_type, 0) + 1
                # Track downloaded size
                try:
                    if result.exists():
                        total_bytes_downloaded += result.stat().st_size
                except OSError:
                    pass

                # Phase 4: Post-processing (US2 integration point)
                if self._pipeline_runner:
                    self.state = SyncState.PROCESSING
                    self._pipeline_runner.process_file(result, diff.cloud_metadata)
                
                # Phase 5: Delete after download (if enabled)
                if getattr(self.config, "delete_after_download", False):
                    max_del = getattr(self.config, "max_deletions_per_run", 100)
                    if deleted_count < max_del:
                        if self.wrapper.delete_asset(photo_asset):
                            deleted_count += 1
                            if self.config.download_delay > 0:
                                time.sleep(self.config.download_delay)
                    elif not limit_reached_logged:
                        logger.info("Max deletions per run (%d) reached. Skipping further deletions.", max_del)
                        limit_reached_logged = True
            else:
                failed += 1

            # Progress report every 10 files
            if (processed + failed) % 10 == 0:
                logger.info(
                    "Progress: %d/%d downloaded, %d failed",
                    processed, download_count, failed,
                )

        # Phase 5b: Cloud retention policy (keep_icloud_recent_days)
        days = getattr(self.config, "keep_icloud_recent_days", None)
        keep_only = getattr(self.config, "keep_icloud_recent_only", False)
        if isinstance(days, int) and not isinstance(days, bool) and days > 0:
            if not keep_only:
                logger.warning(
                    "keep_icloud_recent_days is set (%d), but keep_icloud_recent_only is False. "
                    "Skipping retention cleanup (requires double confirmation).",
                    days,
                )
            else:
                max_del = getattr(self.config, "max_deletions_per_run", 100)
                max_del_val = max_del if isinstance(max_del, int) and not isinstance(max_del, bool) else 100
                max_del_remain = max_del_val - deleted_count
                if max_del_remain > 0:
                    retention_deleted = self._apply_cloud_retention(
                        cloud_assets=cloud_assets,
                        asset_map=asset_map,
                        max_deletions=max_del_remain,
                    )
                    deleted_count += retention_deleted

        # Publish detailed completion notification
        if self._event_bus:
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            message = self._format_complete_message(
                processed=processed,
                failed=failed,
                media_counts=media_counts,
                total_bytes=total_bytes_downloaded,
                total_cloud=total_cloud,
                duration=duration,
                deleted=deleted_count,
            )
            self._event_bus.publish(SystemEvent(
                event_type=EventType.COMPLETE,
                severity="info" if failed == 0 else "warning",
                message=message,
                details={
                    "downloaded": processed,
                    "failed": failed,
                    "photos": media_counts.get("photo", 0),
                    "videos": media_counts.get("video", 0),
                    "live_photos": media_counts.get("live_photo", 0),
                    "total_bytes": total_bytes_downloaded,
                    "cloud_total": total_cloud,
                },
            ))

        self.state = SyncState.IDLE
        return self._build_summary(
            start_time, processed, failed,
            media_counts=media_counts,
            total_bytes=total_bytes_downloaded,
            total_cloud=total_cloud,
            deleted=deleted_count,
        )

    def _build_summary(
        self,
        start_time: datetime,
        processed: int,
        failed: int,
        media_counts: Optional[Dict[str, int]] = None,
        total_bytes: int = 0,
        total_cloud: int = 0,
        deleted: int = 0,
    ) -> dict:
        """Build task summary dictionary.

        Args:
            start_time: Cycle start time.
            processed: Number of successfully processed assets.
            failed: Number of failed assets.
            media_counts: Breakdown by media type (photo/video/live_photo).
            total_bytes: Total bytes downloaded this cycle.
            total_cloud: Total cloud library size.
            deleted: Number of assets deleted from iCloud.

        Returns:
            Summary dict.
        """
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        summary = {
            "started_at": start_time.isoformat(),
            "duration_seconds": duration,
            "processed": processed,
            "failed": failed,
            "state": self.state.value,
            "cloud_total": total_cloud,
        }
        if media_counts:
            summary["photos"] = media_counts.get("photo", 0)
            summary["videos"] = media_counts.get("video", 0)
            summary["live_photos"] = media_counts.get("live_photo", 0)
        if total_bytes:
            summary["total_bytes"] = total_bytes
        if deleted:
            summary["deleted"] = deleted
        return summary

    def _format_complete_message(
        self,
        processed: int,
        failed: int,
        media_counts: Dict[str, int],
        total_bytes: int,
        total_cloud: int,
        duration: float,
        deleted: int = 0,
    ) -> str:
        """Format a human-readable sync completion message.

        Args:
            processed: Total files downloaded.
            failed: Total files failed.
            media_counts: Breakdown by media type.
            total_bytes: Total bytes downloaded.
            total_cloud: Total items in cloud library.
            duration: Cycle duration in seconds.
            deleted: Number of assets deleted from iCloud.

        Returns:
            Formatted multi-line message string.
        """
        lines = [f"Sync complete — {processed} downloaded"]

        # Media type breakdown
        parts = []
        photos = media_counts.get("photo", 0)
        videos = media_counts.get("video", 0)
        live_photos = media_counts.get("live_photo", 0)
        if photos:
            parts.append(f"📷 {photos} photo{'s' if photos != 1 else ''}")
        if videos:
            parts.append(f"🎬 {videos} video{'s' if videos != 1 else ''}")
        if live_photos:
            parts.append(f"🔄 {live_photos} live photo{'s' if live_photos != 1 else ''}")
        if parts:
            lines.append(", ".join(parts))

        # Download size
        if total_bytes > 0:
            lines.append(f"💾 {self._format_size(total_bytes)}")

        # Failures
        if failed:
            lines.append(f"⚠️ {failed} failed")

        # Deletions
        if deleted:
            lines.append(f"🗑 {deleted} deleted from iCloud")

        # Cloud total and duration
        lines.append(f"☁️ Cloud library: {total_cloud} items")
        lines.append(f"⏱ Duration: {self._format_duration(duration)}")

        return "\n".join(lines)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format byte count to human-readable string.

        Args:
            size_bytes: Size in bytes.

        Returns:
            Human-readable size string (e.g. '1.5 GB').
        """
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if abs(size_bytes) < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in seconds to human-readable string.

        Args:
            seconds: Duration in seconds.

        Returns:
            Formatted string like '2m 30s' or '1h 5m'.
        """
        if seconds < 60:
            return f"{int(seconds)}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        if minutes < 60:
            return f"{minutes}m {secs}s"
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"

    def _check_pause(self) -> None:
        """Check if pause was requested and handle it."""
        if self._pause_requested and self.state not in (SyncState.PAUSED, SyncState.IDLE):
            self._handle_pause()

    def _handle_pause(self) -> None:
        """Transition to paused state, blocking until resumed via Event."""
        logger.info("Pausing sync engine")
        self.state = SyncState.PAUSED
        if self._event_bus:
            self._event_bus.publish(SystemEvent(
                event_type=EventType.SYNC_PAUSED,
                severity="info",
                message="Sync engine paused.",
            ))
        self._resume_event.clear()
        # Block until resume() signals the event (replaces busy-wait)
        self._resume_event.wait()
        self._pause_requested = False

    def _check_cookie_expiry(self) -> None:
        """Check cookie expiry and send notification if within threshold.

        Follows docker-icloudpd's display_multifactor_authentication_expiry:
        after each sync cycle, check cookie expiry and send notifications
        when days_remaining <= notification_days.
        """
        if self._auth_manager is None:
            return

        try:
            details = self._auth_manager.check_cookie_expiry()
            if details.days_remaining is None:
                return

            notification_days = getattr(self.config, "notification_days", 7)

            if details.days_remaining < 1:
                # Cookie expired
                if self._event_bus:
                    expire_date = details.mfa_expire_date or details.web_expire_date
                    self._event_bus.publish(SystemEvent(
                        event_type=EventType.AUTH_EXPIRED,
                        severity="error",
                        message=(
                            f"Cookie expired at: {expire_date}. "
                            f"Please reinitialise authentication (send /reauth in Telegram)."
                        ),
                        details={"days_remaining": details.days_remaining},
                    ))
                if getattr(self.config, "wait_for_reauthentication", True):
                    self.state = SyncState.WAITING_FOR_AUTH
            elif details.days_remaining <= notification_days:
                # Cookie expiring soon
                if self._event_bus:
                    if details.days_remaining == 1:
                        msg = (
                            f"Final day before cookie expires for Apple ID: "
                            f"{self.config.apple_id} — Please reinitialise now"
                        )
                    else:
                        msg = (
                            f"Only {details.days_remaining} days until cookie expires "
                            f"for Apple ID: {self.config.apple_id} — Please reinitialise"
                        )
                    self._event_bus.publish(SystemEvent(
                        event_type=EventType.COOKIE_EXPIRING,
                        severity="warning",
                        message=msg,
                        details={"days_remaining": details.days_remaining},
                    ))
        except Exception as e:
            logger.warning("Cookie expiry check failed: %s", e)

    def _check_preflight_disk(self) -> bool:
        """Check available space on /config and download_path before syncing."""
        # Check /config (needs >= 1MB for cookies/db)
        config_dir = getattr(self.config, "cookie_dir", None)
        if isinstance(config_dir, (str, Path)):
            try:
                config_path = Path(config_dir)
                target_cfg = config_path if config_path.exists() else config_path.parent
                if target_cfg.exists():
                    stat_cfg = os.statvfs(target_cfg)
                    free_cfg = stat_cfg.f_frsize * stat_cfg.f_bavail
                    if free_cfg < 1048576:  # 1MB
                        logger.error("Critically low space on config volume: %d bytes (min 1MB required)", free_cfg)
                        if self._event_bus:
                            self._event_bus.publish(SystemEvent(
                                event_type=EventType.LOW_SPACE,
                                severity="error",
                                message=f"Critically low space on config volume: {self._format_size(free_cfg)} available (1MB required)",
                            ))
                        return False
            except Exception as e:
                logger.debug("Could not statvfs for config dir: %s", e)

        # Check download_path (needs >= min_free_disk_bytes, default 1GB)
        dl_dir = getattr(self.config, "download_path", None)
        min_dl_bytes = getattr(self.config, "min_free_disk_bytes", 1073741824)
        if not isinstance(min_dl_bytes, int) or isinstance(min_dl_bytes, bool):
            min_dl_bytes = 1073741824

        if isinstance(dl_dir, (str, Path)):
            try:
                dl_path = Path(dl_dir)
                target_check = dl_path if dl_path.exists() else dl_path.parent
                if target_check.exists():
                    stat_dl = os.statvfs(target_check)
                    free_dl = stat_dl.f_frsize * stat_dl.f_bavail
                    if free_dl < min_dl_bytes:
                        logger.error(
                            "Insufficient space on download volume: %d bytes (min %d bytes required)",
                            free_dl, min_dl_bytes,
                        )
                        if self._event_bus:
                            self._event_bus.publish(SystemEvent(
                                event_type=EventType.LOW_SPACE,
                                severity="error",
                                message=f"Low disk space on download path: {self._format_size(free_dl)} available ({self._format_size(min_dl_bytes)} required)",
                            ))
                        return False
            except Exception as e:
                logger.debug("Could not statvfs for download dir: %s", e)

        return True

    def _apply_cloud_retention(
        self,
        cloud_assets: list,
        asset_map: Dict[str, object],
        max_deletions: int,
    ) -> int:
        """Apply cloud retention policy: delete assets older than keep_icloud_recent_days.

        Args:
            cloud_assets: List of asset metadata dicts.
            asset_map: Map of record_name to PhotoAsset.
            max_deletions: Maximum number of deletions allowed in this pass.

        Returns:
            Number of assets deleted from iCloud.
        """
        days = getattr(self.config, "keep_icloud_recent_days", None)
        keep_only = getattr(self.config, "keep_icloud_recent_only", False)
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0 or not keep_only:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = 0

        for meta in cloud_assets:
            if deleted >= max_deletions:
                logger.info("Max deletions limit reached during cloud retention cleanup (%d)", max_deletions)
                break

            record_name = meta.get("record_name")
            asset = asset_map.get(record_name)
            if not asset:
                continue

            asset_dt = getattr(asset, "created", None)
            if not asset_dt:
                created_str = meta.get("created_at")
                if created_str:
                    try:
                        asset_dt = datetime.fromisoformat(str(created_str))
                    except Exception:
                        pass

            if not asset_dt:
                continue

            if asset_dt.tzinfo is None:
                asset_dt = asset_dt.replace(tzinfo=timezone.utc)

            if asset_dt < cutoff:
                logger.info(
                    "Asset %s (%s) is older than %d days (cutoff: %s) -> deleting from iCloud",
                    meta.get("filename"), asset_dt.isoformat(), days, cutoff.isoformat(),
                )
                if self.wrapper.delete_asset(asset):
                    deleted += 1
                    if self.config.download_delay > 0:
                        time.sleep(self.config.download_delay)

        return deleted

    def _wait_for_reauth(self) -> None:
        """Hold the engine in waiting_for_auth state until re-authenticated.

        Creates the marker file for Docker healthcheck, sends periodic
        reminders, and blocks until authentication is restored.
        Delegates to the shared wait_for_auth_restoration() method.
        """
        logger.warning("Entering re-authentication hold state...")
        self.state = SyncState.WAITING_FOR_AUTH

        WAITING_FOR_AUTH_MARKER.parent.mkdir(parents=True, exist_ok=True)
        WAITING_FOR_AUTH_MARKER.touch(exist_ok=True)

        def _state_check():
            """Return True when external code (e.g. /reauth) has reset state."""
            return self.state != SyncState.WAITING_FOR_AUTH

        try:
            restored = SyncEngine.wait_for_auth_restoration(
                auth_manager=self._auth_manager,
                config=self.config,
                event_bus=self._event_bus,
                cancel_check=_state_check,
            )
            if restored:
                logger.info("Authentication restored! Resuming normal sync.")
            self.state = SyncState.IDLE
        finally:
            if WAITING_FOR_AUTH_MARKER.exists():
                WAITING_FOR_AUTH_MARKER.unlink(missing_ok=True)

    @staticmethod
    def wait_for_auth_restoration(
        auth_manager,
        config,
        event_bus=None,
        shutdown_event=None,
        cancel_check=None,
    ) -> bool:
        """Block until authentication is restored or shutdown is requested.

        Shared by both startup auth failure (main.py) and runtime cookie
        expiry (engine._wait_for_reauth).

        Args:
            auth_manager: AuthManager to poll for cookie validity.
            config: Config for apple_id, download_interval, etc.
            event_bus: Optional EventBus for publishing AUTH_EXPIRED events.
            shutdown_event: Optional threading.Event; when set, abort wait.
            cancel_check: Optional callable returning True to abort wait
                (used by engine when /reauth resets state externally).

        Returns:
            True if auth restored, False if shutdown/cancel requested.
        """
        remind_interval = getattr(config, "reauth_notification_interval", None)
        if not remind_interval or (isinstance(remind_interval, int) and remind_interval < 10):
            remind_interval = config.download_interval

        msg = (
            f"⚠️ Authentication required for Apple ID: {config.apple_id}\n"
            f"Please send /reauth in Telegram to restore sync."
        )

        while True:
            # Check cancel condition before each reminder cycle
            if cancel_check and cancel_check():
                return True

            if event_bus:
                event_bus.publish(SystemEvent(
                    event_type=EventType.AUTH_EXPIRED,
                    severity="error",
                    message=msg,
                ))

            # Poll for auth restoration (check every 2 seconds)
            elapsed = 0
            while elapsed < remind_interval:
                # Check for shutdown request (SIGTERM)
                if shutdown_event is not None:
                    if shutdown_event.wait(timeout=2):
                        return False
                else:
                    time.sleep(2)
                elapsed += 2

                # Check external cancel (e.g. /reauth changed engine state)
                if cancel_check and cancel_check():
                    return True

                # Check if auth manager says cookie is now valid
                if auth_manager:
                    try:
                        details = auth_manager.check_cookie_expiry()
                        if details.days_remaining is not None and details.days_remaining >= 1:
                            return True
                    except Exception:
                        pass

    def _wait_interval(self) -> None:
        """Wait for the next sync interval, checking for pause/resume."""
        interval = self.config.download_interval
        logger.info("Next sync in %d seconds", interval)

        remaining = interval
        while remaining > 0:
            if self._pause_requested:
                self._handle_pause()
            sleep_time = min(10, remaining)
            time.sleep(sleep_time)
            remaining -= sleep_time
