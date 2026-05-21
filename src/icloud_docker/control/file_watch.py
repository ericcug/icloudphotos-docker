"""File-based command channel (fallback when Telegram not configured).

Provides an alternative remote control mechanism by watching a
command file for instructions. Follows the docker-icloudpd pattern
of file-watch-based control as fallback.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FileCommandWatcher:
    """Watches a command file for remote control instructions.

    Used as fallback when Telegram Bot is not configured (FR-021).
    Commands are written one per line in the command file:

        pause
        resume
        sync
        status

    After execution, the command file is truncated.

    Attributes:
        command_file: Path to the command file.
        engine: SyncEngine instance for command execution.
        polling_interval: Seconds between file checks.
    """

    VALID_COMMANDS = {"pause", "resume", "sync", "status"}

    def __init__(
        self,
        command_file: Path,
        engine=None,
        polling_interval: int = 10,
    ):
        """Initialize file command watcher.

        Args:
            command_file: Path to watch for commands.
            engine: SyncEngine instance.
            polling_interval: Poll interval in seconds.
        """
        self.command_file = Path(command_file)
        self.engine = engine
        self.polling_interval = polling_interval
        self.running = False

    def start(self) -> None:
        """Start watching in a simple loop (called from main thread)."""
        logger.info("File command watcher started: %s (interval=%ds)",
                     self.command_file, self.polling_interval)
        self.running = True
        # Note: In production, this should run in a separate thread
        # For now, it's polled synchronously by the engine

    def stop(self) -> None:
        """Stop watching."""
        self.running = False

    def check_commands(self) -> Optional[str]:
        """Check for and process any pending commands.

        Returns:
            The executed command string, or None if no command.
        """
        if not self.command_file.exists():
            return None

        try:
            content = self.command_file.read_text().strip()
            if not content:
                return None

            # Execute first valid command
            cmd = content.split("\n")[0].strip().lower()
            if cmd in self.VALID_COMMANDS:
                self._execute(cmd)
                # Clear the command file after execution
                self.command_file.write_text("")
                return cmd
            else:
                logger.warning("Unknown command in file: '%s'", cmd)
                self.command_file.write_text("")  # Clear unknown commands too

        except Exception as e:
            logger.error("File command error: %s", e)

        return None

    def _execute(self, cmd: str) -> None:
        """Execute a validated command.

        Args:
            cmd: Command name (pause, resume, sync, status).
        """
        if not self.engine:
            logger.warning("No engine configured for command '%s'", cmd)
            return

        if cmd == "pause":
            self.engine.pause()
            logger.info("File command: PAUSE")
        elif cmd == "resume":
            self.engine.resume()
            logger.info("File command: RESUME")
        elif cmd == "sync":
            self.engine.sync_now()
            logger.info("File command: SYNC")
        elif cmd == "status":
            state = self.engine.state.value if self.engine else "unknown"
            logger.info("File command: STATUS → state=%s", state)
