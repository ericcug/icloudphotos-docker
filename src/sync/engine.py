"""Core sync engine with state machine.

Coordinates the full sync cycle: authentication check → metadata diff →
download → post-processing. Implements crash recovery with exponential
backoff per the spec (FR-011).
"""

import logging
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

from notify.bus import EventType, SystemEvent
from sync.differ import AssetDiff, MetadataDiffer
from sync.downloader import Downloader
from sync.icloud_wrapper import ICloudWrapper

logger = logging.getLogger(__name__)


class SyncState(Enum):
    """Sync engine state machine states."""
    IDLE = "idle"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    WAITING = "waiting"
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

                # Check cookie expiry after each cycle (docker-icloudpd pattern)
                self._check_cookie_expiry()

                # Wait for next interval
                self.state = SyncState.WAITING
                self._wait_interval()

            except Exception as e:
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
        logger.info("=" * 40)
        logger.info("Sync cycle started")
        if self._event_bus:
            self._event_bus.publish(SystemEvent(
                event_type=EventType.START, severity="info", message="Sync cycle started"
            ))
        start_time = datetime.now(timezone.utc)

        # Phase 1: Check iCloud connection and build asset map
        self.state = SyncState.CHECKING
        logger.info("Phase: CHECKING — fetching cloud metadata...")
        cloud_assets = []
        asset_map: Dict[str, object] = {}  # record_name → PhotoAsset
        for asset in self.wrapper.photos:
            if self._pause_requested:
                self._handle_pause()
                break
            metadata = self.wrapper.get_asset_metadata(asset)
            cloud_assets.append(metadata)
            asset_map[metadata["record_name"]] = asset

        # Phase 2: Compute diff
        diffs = self.differ.compute_diff(cloud_assets)
        download_count = sum(1 for d in diffs if d.status in ("new", "modified"))

        if download_count == 0:
            logger.info("No new or modified assets to download")
            if self._event_bus:
                self._event_bus.publish(SystemEvent(
                    event_type=EventType.COMPLETE, severity="info",
                    message="Sync complete — no changes"
                ))
            self.state = SyncState.IDLE
            return self._build_summary(start_time, 0, 0)

        # Phase 3: Download
        self.state = SyncState.DOWNLOADING
        self.downloader.reset_stats()
        logger.info("Phase: DOWNLOADING — %d assets to download", download_count)

        processed = 0
        failed = 0
        deleted_count = 0
        limit_reached_logged = False

        for diff in diffs:
            if self._pause_requested:
                self._handle_pause()
                break

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

        self.state = SyncState.IDLE
        return self._build_summary(start_time, processed, failed)

    def _build_summary(self, start_time: datetime, processed: int, failed: int) -> dict:
        """Build task summary dictionary.

        Args:
            start_time: Cycle start time.
            processed: Number of successfully processed assets.
            failed: Number of failed assets.

        Returns:
            Summary dict.
        """
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        return {
            "started_at": start_time.isoformat(),
            "duration_seconds": duration,
            "processed": processed,
            "failed": failed,
            "state": self.state.value,
        }

    def _check_pause(self) -> None:
        """Check if pause was requested and handle it."""
        if self._pause_requested and self.state not in (SyncState.PAUSED, SyncState.IDLE):
            self._handle_pause()

    def _handle_pause(self) -> None:
        """Transition to paused state, blocking until resumed via Event."""
        logger.info("Pausing sync engine")
        self.state = SyncState.PAUSED
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
                            f"Please reinitialise authentication."
                        ),
                        details={"days_remaining": details.days_remaining},
                    ))
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

    def _wait_interval(self) -> None:
        """Wait for the next sync interval, checking for pause/resume.

        Uses monotonic clock for accurate timing instead of accumulating
        fixed increments.
        """
        interval = self.config.download_interval
        logger.info("Next sync in %d seconds", interval)

        deadline = time.monotonic() + interval
        while time.monotonic() < deadline:
            if self._pause_requested:
                self._handle_pause()
                # Reset deadline after resume
                deadline = time.monotonic() + interval
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(10, remaining))
