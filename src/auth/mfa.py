"""Telegram + stdin MFA provider for iCloud authentication.

Follows the docker-icloudpd pattern: sends MFA prompt via Telegram,
waits for user response (Telegram reply or stdin), feeds code to the
authentication flow. Uses threading.Event for cross-thread coordination.
"""

import logging
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramMFAProvider:
    """MFA code provider: Telegram notification + stdin fallback.

    Two modes of operation:
    1. **Synchronous** (`request_code`): blocks until code received,
       used by AuthManager._handle_2fa() for the main auth flow.
    2. **Asynchronous** (`send_prompt` + `wait_for_code`): sends prompt
       first, then blocks; used when prompt delivery needs to happen
       before waiting.

    External code (TelegramController) calls `provide_code(code)` to
    inject the MFA code from a Telegram reply.

    Attributes:
        bot_token: Telegram Bot API token.
        chat_id: Target Telegram chat ID.
        timeout: Maximum seconds to wait for code (default 600s).
    """

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        timeout: int = 600,
    ):
        """Initialize MFA provider.

        Args:
            bot_token: Telegram Bot API token (empty = stdin-only).
            chat_id: Target Telegram chat ID.
            timeout: Max wait time for code in seconds.
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self._code: Optional[str] = None
        self._code_event = threading.Event()

    @property
    def is_telegram_configured(self) -> bool:
        """Check if Telegram is configured for MFA."""
        return bool(self.bot_token and self.chat_id)

    # ---- Public API ----

    def send_prompt(self, message: str) -> bool:
        """Send MFA prompt via Telegram (non-blocking).

        If Telegram is not configured, prints to stderr instead.

        Args:
            message: Prompt message to send.

        Returns:
            True if Telegram message was sent successfully.
        """
        if not self.is_telegram_configured:
            logger.info("Telegram not configured; MFA prompt on console only")
            print(f"\n{'=' * 40}", file=sys.stderr)
            print(f"MFA Required", file=sys.stderr)
            print(f"{'=' * 40}", file=sys.stderr)
            print(message, file=sys.stderr)
            return False

        import requests

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            resp = requests.post(url, json={
                "chat_id": self.chat_id,
                "text": (
                    f"🔐 *MFA Verification Required*\n\n"
                    f"{message}\n\n"
                    f"Please reply with the 6‑digit code within 10 minutes."
                ),
                "parse_mode": "Markdown",
            }, timeout=10)
            if resp.status_code == 200:
                logger.info("MFA prompt sent to Telegram chat %s", self.chat_id)
                return True
            else:
                logger.warning("Telegram sendMessage failed: %s", resp.text)
                return False
        except Exception as e:
            logger.warning("Failed to send Telegram MFA prompt: %s", e)
            return False

    def provide_code(self, code: str) -> None:
        """Inject MFA code from external source (e.g., Telegram controller).

        Thread-safe: signals the waiting `wait_for_code()` to return.

        Args:
            code: The 6-digit MFA verification code.
        """
        self._code = code.strip()
        self._code_event.set()
        logger.info("MFA code provided externally (%d chars)", len(self._code))

    def wait_for_code(self, timeout: Optional[int] = None) -> str:
        """Block until a code is provided via `provide_code()` or stdin.

        If Telegram is configured, waits for `provide_code()` call.
        Otherwise, reads from stdin immediately.

        Args:
            timeout: Max seconds to wait (default: self.timeout).

        Returns:
            The 6-digit MFA code.

        Raises:
            TimeoutError: If no code received within timeout.
        """
        effective_timeout = timeout if timeout is not None else self.timeout

        if self.is_telegram_configured:
            return self._wait_for_telegram_or_stdin(effective_timeout)
        else:
            return self._read_from_stdin()

    def request_code(self, prompt: str = "") -> str:
        """Send prompt + wait for code (convenience, synchronous).

        Args:
            prompt: Message to include in the Telegram prompt.

        Returns:
            The 6-digit MFA code.
        """
        if prompt:
            self.send_prompt(prompt)
        return self.wait_for_code()

    def reset(self) -> None:
        """Reset internal state for a new MFA cycle."""
        self._code = None
        self._code_event.clear()

    # ---- Internal ----

    def _wait_for_telegram_or_stdin(self, timeout: int) -> str:
        """Wait for code from Telegram, with stdin as interruptible fallback.

        Runs a background thread for Telegram polling, while simultaneously
        offering stdin input. Returns whichever comes first.
        """
        self._code_event.clear()
        self._code = None

        logger.info("Waiting for MFA code (Telegram or stdin, timeout=%ds)...", timeout)

        # Start a stdin reader thread so we don't block on input()
        stdin_code: list = [None]  # mutable container for thread result

        def read_stdin():
            try:
                print("\nOr enter MFA code here: ", end="", flush=True)
                stdin_code[0] = sys.stdin.readline().strip()
                if stdin_code[0]:
                    self.provide_code(stdin_code[0])
            except (EOFError, OSError):
                pass

        stdin_thread = threading.Thread(target=read_stdin, daemon=True)
        stdin_thread.start()

        # Wait for code from either Telegram or stdin
        received = self._code_event.wait(timeout=timeout)

        if not received:
            # Check if stdin got something after timeout
            if stdin_code[0]:
                return stdin_code[0]
            raise TimeoutError(f"No MFA code received within {timeout}s")

        return self._code or ""

    def _read_from_stdin(self) -> str:
        """Read MFA code directly from stdin (no Telegram)."""
        logger.info("MFA via stdin (Telegram not configured)")
        print(f"\n{'=' * 40}")
        print("MFA Verification Required")
        print(f"{'=' * 40}")
        print("Check your trusted Apple device for the 6-digit code.")
        print("If no push notification appears, generate a code from:")
        print("  Settings > Apple ID > Sign-In & Security > Get Verification Code")
        print()
        while True:
            code = input("Enter 6-digit code: ").strip()
            if len(code) == 6 and code.isdigit():
                return code
            print("Invalid code — must be exactly 6 digits. Try again.")
