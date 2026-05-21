"""Application entry point for iCloud Photo Downloader.

Parses CLI arguments, loads configuration, initializes logging,
and orchestrates the startup sequence of all subsystems.
"""

import sys
from pathlib import Path

# 添加本地 icloud_photos_downloader 库路径
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

    from config.loader import ConfigError, load_config

    # Get password from environment (never from config file)
    password = os.environ.get("ICLOUD_PASSWORD", "")

    try:
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
    if log_level != "info" or config.debug_logging:
        logger.setLevel(logging.DEBUG if config.debug_logging else getattr(logging, log_level.upper(), logging.INFO))

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

    # Auth subsystem
    cookie_store = CookieStore(cookie_dir=config.cookie_dir)
    mfa_provider = TelegramMFAProvider(
        bot_token=config.notification.telegram.bot_token,
        chat_id=config.notification.telegram.chat_id,
    )
    auth_manager = AuthManager(config, cookie_store, mfa_provider)

    # Authenticate with iCloud
    if not password:
        logger.error("ICLOUD_PASSWORD environment variable is required")
        logger.error("Set it via: export ICLOUD_PASSWORD='your-apple-id-password'")
        sys.exit(1)

    try:
        service = auth_manager.authenticate(password)
    except Exception as e:
        logger.error("Authentication failed: %s", e)
        logger.error("Check your Apple ID and password.")
        sys.exit(1)

    # Sync engine
    wrapper = ICloudWrapper(service)
    engine = SyncEngine(config, wrapper)
    engine.set_auth_manager(auth_manager)

    # Phase 4 (US2): Pipeline runner
    from pipeline.runner import PipelineRunner
    pipeline_runner = PipelineRunner(config.pipeline)
    if not pipeline_runner.is_empty:
        engine.set_pipeline_runner(pipeline_runner)
        logger.info("Pipeline runner loaded (%d steps)", len(pipeline_runner.steps))

    # Phase 5 (US3): Event bus + notification channels
    from notify.bus import EventBus
    from notify.channels.telegram import TelegramNotifier
    from notify.channels.webhook import WebhookNotifier

    event_bus = EventBus(subscribed_events=config.notification.events)
    engine.set_event_bus(event_bus)

    if config.notification.telegram.enabled:
        tg_notifier = TelegramNotifier(
            bot_token=config.notification.telegram.bot_token,
            chat_id=config.notification.telegram.chat_id,
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
        for etype in ["start", "complete", "error", "auth_expired", "cookie_expiring", "low_space", "rate_limited"]:
            event_bus.subscribe(etype, wh_notifier.send)
        logger.info("Webhook notifications enabled")

    # Phase 6 (US4): Telegram Bot controller
    from control.telegram_bot import TelegramController
    from control.file_watch import FileCommandWatcher

    telegram_ctrl = TelegramController(
        bot_token=config.notification.telegram.bot_token,
        chat_id=config.notification.telegram.chat_id,
        engine=engine,
        mfa_provider=mfa_provider,
        polling_interval=config.notification.telegram.polling_interval,
    )
    if telegram_ctrl.enabled:
        telegram_ctrl.start()
        logger.info("Telegram remote control enabled")
    else:
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
        return

    # Main sync loop
    try:
        result = engine.run_cycle(once=False)
        logger.info("Sync engine stopped: %s", result)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        engine.pause()


if __name__ == "__main__":
    main()
