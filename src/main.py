"""Application entry point for iCloud Photo Downloader.

Parses CLI arguments, loads configuration, initializes logging,
and orchestrates the startup sequence of all subsystems.
"""

import sys
from pathlib import Path

# Add local icloud_photos_downloader library path
_libs_path = Path(__file__).resolve().parent.parent.parent / "libs" / "icloud_photos_downloader" / "src"
if _libs_path.exists():
    sys.path.insert(0, str(_libs_path))

import argparse
import os
import logging

from logger import setup_logging

logger = None  # Set after config loaded


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="iCloud Photo Downloader — Docker-based iCloud photo sync",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("ICLOUD_CONFIG", "/config/config.yaml")),
        help="Path to config.yaml (default: /config/config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single sync cycle and exit (default: loop forever)",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default=None,
        help="Override log level from config",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point. Loads config, initializes subsystems, runs sync loop."""
    global logger

    args = parse_args()

    # Early logging setup (level will be refined after config load)
    logger = setup_logging(level="info", debug=False)

    import signal
    def handle_sigterm(signum, frame):
        if logger:
            logger.info("Received SIGTERM, initiating shutdown...")
        raise KeyboardInterrupt("SIGTERM received")
    signal.signal(signal.SIGTERM, handle_sigterm)

    from config.loader import ConfigError, load_config

    # Get password from environment (never from config file)
    password = os.environ.get("ICLOUD_PASSWORD", "")

    try:
        if not args.config.exists():
            # Try to find config.example.yaml relative to main.py
            example_path = Path(__file__).resolve().parent.parent / "config" / "config.example.yaml"
            if example_path.exists():
                import shutil
                args.config.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(example_path, args.config)
                print(f"INFO: Created default config file at {args.config}", file=sys.stderr)
                print("Please edit it and restart the container.", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"ERROR: Config file not found at {args.config} and no example found.", file=sys.stderr)
                sys.exit(1)

        config = load_config(args.config, password=password or None)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Copy config.example.yaml to config.yaml and edit it.", file=sys.stderr)
        sys.exit(1)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Refine logging level based on config
    log_level = args.log_level or config.log_level
    if log_level != "info":
        logger = setup_logging(level=log_level)

    logger.info("=" * 50)
    logger.info("iCloud Photo Downloader starting")
    logger.info("Config: %s", args.config)
    from config.loader import _mask
    logger.info("Apple ID: %s", _mask(config.apple_id))
    logger.info("Download path: %s", config.download_path)
    logger.info("Sync interval: %ds", config.download_interval)
    logger.info("Cookie expiry notification: %d days", config.notification_days)
    logger.info("Once mode: %s", args.once)
    logger.info("=" * 50)

    # Phase 3 (US1): Initialize auth and sync engine
    from auth.cookie_store import CookieStore
    from auth.mfa import TelegramMFAProvider
    from auth.session import AuthManager
    from sync.icloud_wrapper import ICloudWrapper
    from sync.engine import SyncEngine

    # Shared Telegram Bot service (connection pooling)
    from notify.channels.telegram_service import TelegramService
    from notify.bus import EventBus
    from notify.channels.telegram import TelegramNotifier
    from notify.channels.webhook import WebhookNotifier

    telegram_service = None
    tg_config = config.notification.telegram
    if tg_config.bot_token and tg_config.chat_id:
        telegram_service = TelegramService(bot_token=tg_config.bot_token)
        import time as _time
        for _attempt in range(1, 4):
            try:
                telegram_service.start()
                break
            except Exception as e:
                if _attempt < 3:
                    logger.warning(
                        "Failed to start TelegramService (attempt %d/3): %s — retrying in 5s...",
                        _attempt, e,
                    )
                    _time.sleep(5)
                else:
                    logger.warning("Failed to start TelegramService after 3 attempts: %s (continuing without)", e)
                    telegram_service = None

    # Phase 5 (US3): Event bus + notification channels (Initialized early so startup auth events are delivered)
    event_bus = EventBus(subscribed_events=config.notification.events)

    if (tg_config.enabled or (tg_config.bot_token and tg_config.chat_id)) and telegram_service:
        tg_notifier = TelegramNotifier(
            service=telegram_service,
            chat_id=tg_config.chat_id,
        )
        for etype in ["start", "complete", "error", "auth_expired", "cookie_expiring", "low_space", "rate_limited", "sync_paused", "sync_resumed"]:
            event_bus.subscribe(etype, tg_notifier.send)
        logger.info("Telegram notifications enabled")

    if config.notification.webhook.enabled:
        wh_notifier = WebhookNotifier(
            url=config.notification.webhook.url,
            method=config.notification.webhook.method,
            headers=config.notification.webhook.headers,
        )
        for etype in ["start", "complete", "error", "auth_expired", "cookie_expiring", "low_space", "rate_limited", "sync_paused", "sync_resumed"]:
            event_bus.subscribe(etype, wh_notifier.send)
        logger.info("Webhook notifications enabled")

    # Auth subsystem
    cookie_store = CookieStore(cookie_dir=config.cookie_dir)
    mfa_provider = TelegramMFAProvider(
        service=telegram_service,
        chat_id=tg_config.chat_id,
    )
    auth_manager = AuthManager(config, cookie_store, mfa_provider)

    # Phase 6 (US4): Telegram Bot controller (Initialize early for MFA)
    from control.telegram_bot import TelegramController
    from control.file_watch import FileCommandWatcher

    telegram_ctrl = TelegramController(
        service=telegram_service,
        chat_id=tg_config.chat_id,
        engine=None,  # Will attach later
        mfa_provider=mfa_provider,
        auth_manager=auth_manager,
    )
    if telegram_ctrl.enabled:
        telegram_ctrl.start()
        logger.info("Telegram remote control enabled (Listening for MFA...)")

    # Authenticate with iCloud
    if not password:
        logger.error("ICLOUD_PASSWORD environment variable is required")
        logger.error("Set it via: export ICLOUD_PASSWORD='your-apple-id-password'")
        sys.exit(1)

    try:
        service = auth_manager.authenticate(password)
    except Exception as e:
        logger.error("Authentication failed: %s", e)
        import requests.exceptions as _req_exc
        try:
            from pyicloud_ipd.exceptions import PyiCloudConnectionErrorException as _ConnExc
            _conn_types = (_ConnExc, _req_exc.RequestException, ConnectionError)
        except ImportError:
            _conn_types = (_req_exc.RequestException, ConnectionError)

        is_network_err = isinstance(e, _conn_types)
        can_wait_reauth = (
            getattr(config, "wait_for_reauthentication", True)
            and not is_network_err
            and telegram_ctrl.enabled
        )
        if can_wait_reauth:
            logger.warning("wait_for_reauthentication is enabled. Holding container open for authentication...")
            from sync.engine import WAITING_FOR_AUTH_MARKER, SyncEngine
            WAITING_FOR_AUTH_MARKER.parent.mkdir(parents=True, exist_ok=True)
            WAITING_FOR_AUTH_MARKER.touch(exist_ok=True)

            # Use threading.Event so SIGTERM can interrupt the wait
            import threading as _threading
            _shutdown_event = _threading.Event()

            _orig_sigterm = signal.getsignal(signal.SIGTERM)
            def _shutdown_handler(signum, frame):
                _shutdown_event.set()
                if callable(_orig_sigterm) and _orig_sigterm not in (signal.SIG_DFL, signal.SIG_IGN):
                    _orig_sigterm(signum, frame)
            signal.signal(signal.SIGTERM, _shutdown_handler)

            try:
                restored = SyncEngine.wait_for_auth_restoration(
                    auth_manager=auth_manager,
                    config=config,
                    event_bus=event_bus,
                    shutdown_event=_shutdown_event,
                    cancel_check=lambda: auth_manager.service is not None,
                )
            except KeyboardInterrupt:
                restored = False

            if WAITING_FOR_AUTH_MARKER.exists():
                WAITING_FOR_AUTH_MARKER.unlink(missing_ok=True)

            if restored:
                service = auth_manager.service or auth_manager.authenticate(password)
                logger.info("Authentication completed! Resuming startup sequence.")
            else:
                logger.info("Shutdown requested during authentication wait.")
                if telegram_ctrl.enabled:
                    telegram_ctrl.stop()
                if telegram_service:
                    telegram_service.stop()
                sys.exit(0)
        else:
            if is_network_err:
                logger.error("Network error during startup authentication — exiting so container can retry.")
            elif not telegram_ctrl.enabled:
                logger.error("Telegram remote control is unavailable — cannot wait for interactive re-authentication.")
            else:
                logger.error("Check your Apple ID and password.")
            if telegram_ctrl.enabled:
                telegram_ctrl.stop()
            if telegram_service:
                telegram_service.stop()
            sys.exit(1)

    # Sync engine
    wrapper = ICloudWrapper(service)
    engine = SyncEngine(config, wrapper)
    engine.set_auth_manager(auth_manager)
    engine.set_event_bus(event_bus)
    telegram_ctrl.engine = engine  # Attach engine to controller

    # Phase 4 (US2): Pipeline runner
    from pipeline.runner import PipelineRunner
    pipeline_runner = PipelineRunner(config.pipeline)
    if not pipeline_runner.is_empty:
        engine.set_pipeline_runner(pipeline_runner)
        logger.info("Pipeline runner loaded (%d steps)", len(pipeline_runner.steps))

    if not telegram_ctrl.enabled:
        # File-based fallback
        file_watcher = FileCommandWatcher(
            command_file=config.temp_dir / "commands.txt",
            engine=engine,
        )
        file_watcher.start()
        logger.info("File-based remote control enabled (Telegram not configured)")

    logger.info("Startup complete. Beginning sync...")

    if args.once:
        result = engine.run_cycle(once=True)
        logger.info("Sync complete: %s", result)
        if telegram_service:
            telegram_service.stop()
        return

    # Main sync loop
    try:
        result = engine.run_cycle(once=False)
        logger.info("Sync engine stopped: %s", result)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        engine.pause()
    finally:
        if telegram_ctrl.enabled:
            telegram_ctrl.stop()
        if telegram_service:
            telegram_service.stop()


if __name__ == "__main__":
    main()
