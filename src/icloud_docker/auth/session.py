"""iCloud authentication session management.

Creates PyiCloudService directly (bypassing icloudpd's authenticator)
to retain full control over the MFA flow: Telegram notification + stdin
fallback, following the docker-icloudpd expect-based pattern.
"""

import logging
from typing import List, Optional

from pyicloud_ipd.base import PyiCloudService
from pyicloud_ipd.exceptions import (
    PyiCloudFailedLoginException,
    PyiCloudFailedMFAException,
)
from pyicloud_ipd.sms import TrustedDevice

from icloud_docker.auth.cookie_store import CookieStore
from icloud_docker.auth.mfa import TelegramMFAProvider

logger = logging.getLogger(__name__)

# Alphabet used for SMS device selection (matching submodule convention)
DEVICE_INDEX_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


class AuthManager:
    """Manages iCloud authentication lifecycle.

    Handles login, MFA interaction (Telegram + stdin), session cookie
    persistence, and re-authentication when sessions expire.

    Attributes:
        config: Application configuration.
        cookie_store: Cookie persistence manager.
        mfa_provider: Telegram-based MFA code provider.
        _service: Authenticated PyiCloudService instance (lazy).
    """

    def __init__(self, config, cookie_store: CookieStore, mfa_provider: TelegramMFAProvider):
        """Initialize auth manager.

        Args:
            config: Application Config instance.
            cookie_store: CookieStore for session persistence.
            mfa_provider: MFA provider for two-factor codes.
        """
        self.config = config
        self.cookie_store = cookie_store
        self.mfa_provider = mfa_provider
        self._service: Optional[PyiCloudService] = None

    @property
    def service(self) -> Optional[PyiCloudService]:
        """Get the authenticated PyiCloudService (lazy init)."""
        return self._service

    def authenticate(self, password: str, force_refresh: bool = False) -> PyiCloudService:
        """Authenticate with iCloud and return a service instance.

        If valid cookies exist and force_refresh is False, attempts to reuse
        the existing session (session-token path) which avoids triggering MFA.
        Only when cookies are missing, expired, or force_refresh is True will
        it delete cookies and perform a full SRP login (which triggers Apple
        push notification for MFA).

        Args:
            password: iCloud Apple ID password.
            force_refresh: If True, delete existing cookies before auth.

        Returns:
            Authenticated PyiCloudService instance.

        Raises:
            PyiCloudFailedLoginException: If credentials are invalid.
            PyiCloudFailedMFAException: If MFA verification fails.
        """
        logger.info("Authenticating with iCloud (force_refresh=%s)...", force_refresh)

        cookie_dir = str(self.config.cookie_dir)
        self.cookie_store.cookie_dir.mkdir(parents=True, exist_ok=True)

        domain = "cn" if self.config.auth_china else "com"

        # Try to reuse existing cookies if they are valid and not force-refreshing.
        if not force_refresh and self.cookie_store.validate_session(self.config.apple_id):
            logger.info("Valid cookies found — attempting session reuse (no MFA)...")
            try:
                icloud = PyiCloudService(
                    domain=domain,
                    apple_id=self.config.apple_id,
                    password_provider=lambda: password,
                    cookie_directory=cookie_dir,
                )

                # If the session is still valid server-side, requires_2fa/2sa
                # will be False and is_trusted_session will be True.
                if not icloud.requires_2fa and not icloud.requires_2sa:
                    logger.info("Session reused successfully — no MFA needed")
                    self._service = icloud
                    return icloud

                # Server rejected the session — cookies are stale.
                logger.info(
                    "Session reuse failed (requires_2fa=%s, requires_2sa=%s) "
                    "— falling back to full login",
                    icloud.requires_2fa, icloud.requires_2sa,
                )
            except Exception as e:
                logger.warning(
                    "Session reuse failed with error: %s — falling back to full login", e
                )

        # Full SRP login path: delete cookies to force fresh authentication.
        # This triggers Apple push notification to trusted devices for MFA.
        logger.info("Performing full SRP login (will trigger MFA)...")
        self.cookie_store.delete_cookie(self.config.apple_id)

        try:
            # Step 1: Create PyiCloudService — triggers SRP login.
            # Apple sends push notification to trusted devices at this point.
            icloud = PyiCloudService(
                domain=domain,
                apple_id=self.config.apple_id,
                password_provider=lambda: password,
                cookie_directory=cookie_dir,
            )

            # Step 2: Handle MFA if required
            logger.info("Auth check: requires_2fa=%s requires_2sa=%s is_trusted=%s",
                        icloud.requires_2fa, icloud.requires_2sa,
                        icloud.is_trusted_session)
            if icloud.requires_2fa:
                logger.info("Two-factor authentication required (2FA)")
                self.mfa_provider.send_prompt(
                    "iCloud requires two-factor authentication.\n"
                    "Check your trusted Apple device for the 6‑digit code."
                )
                self._handle_2fa(icloud)

            elif icloud.requires_2sa:
                logger.info("Two-step authentication required (2SA)")
                self.mfa_provider.send_prompt(
                    "iCloud requires two-step authentication.\n"
                    "An SMS code will be sent to your trusted device."
                )
                self._handle_2sa(icloud)

            self._service = icloud
            logger.info("Authentication successful")
            return icloud

        except PyiCloudFailedLoginException:
            logger.error("Login failed — check Apple ID and password")
            raise
        except PyiCloudFailedMFAException:
            logger.error("MFA verification failed")
            raise
        except Exception as e:
            logger.error("Authentication failed: %s", e)
            raise

    # ---- 2FA (modern two-factor) ----

    def _handle_2fa(self, icloud: PyiCloudService) -> None:
        """Handle modern two-factor authentication (trusted device push).

        Flow (matches docker-icloudpd expect script):
        1. Get trusted phone numbers for SMS fallback
        2. User can enter: (a) 6‑digit push code, or (b) device letter for SMS
        3. If SMS path: send code → wait for SMS code → validate
        4. If push code path: validate directly

        Args:
            icloud: Authenticated PyiCloudService (requires_2fa=True).

        Raises:
            PyiCloudFailedMFAException: If verification fails.
        """
        self.mfa_provider.reset()

        # Trigger push notification to trusted devices (Apple 2026+ requirement).
        # Apple sends the push only after receiving PUT /verify/trusteddevice/securitycode.
        if not icloud.trigger_push_notification():
            logger.debug("Failed to trigger 2FA push notification, continuing anyway")
        else:
            logger.debug("2FA push notification triggered successfully")

        devices = icloud.get_trusted_phone_numbers()
        devices_count = len(devices)
        logger.info("2FA: trusted phone numbers count = %d", devices_count)
        if devices_count > 0:
            for i, d in enumerate(devices):
                logger.info("2FA: device[%d] = %s (id=%d)", i, d.obfuscated_number, d.id)

        if devices_count > 0:
            self._handle_2fa_with_devices(icloud, devices, devices_count)
        else:
            self._handle_2fa_direct(icloud)

    def _handle_2fa_with_devices(
        self, icloud: PyiCloudService, devices: List[TrustedDevice], count: int
    ) -> None:
        """2FA with trusted phone numbers (can send SMS or accept push code)."""
        if count > len(DEVICE_INDEX_ALPHABET):
            raise PyiCloudFailedMFAException("Too many trusted devices")

        # Build device list message
        device_lines = []
        for i, dev in enumerate(devices):
            device_lines.append(f"  {DEVICE_INDEX_ALPHABET[i]}: {dev.obfuscated_number}")
        index_range = (
            f"{DEVICE_INDEX_ALPHABET[0]}..{DEVICE_INDEX_ALPHABET[count - 1]}"
            if count > 1
            else DEVICE_INDEX_ALPHABET[0]
        )

        self.mfa_provider.send_prompt(
            "Trusted phone numbers:\n"
            + "\n".join(device_lines)
            + f"\n\nReply with a letter ({index_range}) to receive an SMS code, "
            f"or reply with the 6‑digit code from your trusted device."
        )

        while True:
            response = self.mfa_provider.wait_for_code()

            if len(response) == 1 and response in DEVICE_INDEX_ALPHABET[:count]:
                # SMS path
                device_index = DEVICE_INDEX_ALPHABET.index(response)
                device = devices[device_index]
                logger.info("Sending SMS code to %s...", device.obfuscated_number)

                if not icloud.send_2fa_code_sms(device.id):
                    raise PyiCloudFailedMFAException("Failed to send SMS code")

                # Wait for the SMS code
                self.mfa_provider.reset()
                self.mfa_provider.send_prompt(
                    "SMS code sent. Please reply with the 6‑digit code you received."
                )
                sms_code = self.mfa_provider.wait_for_code()

                if not icloud.validate_2fa_code_sms(device.id, sms_code):
                    raise PyiCloudFailedMFAException("SMS code verification failed")
                return

            elif len(response) == 6 and response.isdigit():
                # Direct push code
                if icloud.validate_2fa_code(response):
                    return
                logger.warning("Invalid verification code, please try again")
                self.mfa_provider.reset()
                self.mfa_provider.send_prompt(
                    "❌ Invalid code. Please try again with the correct 6‑digit code."
                )
                continue

            else:
                logger.warning("Invalid response: '%s'", response)
                self.mfa_provider.reset()
                self.mfa_provider.send_prompt(
                    "Invalid response. Reply with a single letter for SMS "
                    "or the 6‑digit verification code."
                )
                continue

    def _handle_2fa_direct(self, icloud: PyiCloudService) -> None:
        """2FA without trusted phone numbers — push code only."""
        while True:
            code = self.mfa_provider.wait_for_code()

            if len(code) != 6 or not code.isdigit():
                logger.warning("Invalid code format: '%s'", code)
                self.mfa_provider.reset()
                self.mfa_provider.send_prompt(
                    "Invalid format. Please reply with exactly 6 digits."
                )
                continue

            if icloud.validate_2fa_code(code):
                return

            logger.warning("Invalid verification code, please try again")
            self.mfa_provider.reset()
            self.mfa_provider.send_prompt(
                "❌ Invalid code. Please try again with the correct 6‑digit code."
            )

    # ---- 2SA (legacy two-step) ----

    def _handle_2sa(self, icloud: PyiCloudService) -> None:
        """Handle legacy two-step authentication (SMS to trusted device).

        Args:
            icloud: Authenticated PyiCloudService (requires_2sa=True).

        Raises:
            PyiCloudFailedMFAException: If verification fails.
        """
        self.mfa_provider.reset()
        devices = list(icloud.trusted_devices)
        devices_count = len(devices)
        device_index: int = 0

        if devices_count > 1:
            device_lines = []
            for i, device in enumerate(devices):
                number = device.get("phoneNumber", "unknown")
                name = device.get("deviceName", f"SMS to {number}")
                device_lines.append(f"  {i}: {name}")

            self.mfa_provider.send_prompt(
                "Select a device for SMS code:\n" + "\n".join(device_lines)
            )
            while True:
                response = self.mfa_provider.wait_for_code()
                try:
                    idx = int(response)
                    if 0 <= idx < devices_count:
                        device_index = idx
                        break
                except ValueError:
                    pass
                self.mfa_provider.reset()
                self.mfa_provider.send_prompt(
                    f"Invalid selection. Enter a number 0–{devices_count - 1}."
                )

        device = devices[device_index]
        logger.info("Sending 2SA verification code to %s...", device.get("deviceName", "unknown"))

        if not icloud.send_verification_code(device):
            raise PyiCloudFailedMFAException("Failed to send verification code")

        self.mfa_provider.reset()
        self.mfa_provider.send_prompt("Enter the verification code sent to your device.")
        code = self.mfa_provider.wait_for_code()

        if not icloud.validate_verification_code(device, code):
            raise PyiCloudFailedMFAException("Verification code validation failed")

    # ---- Session management ----

    def check_session(self) -> bool:
        """Check if current session is still valid.

        Returns:
            True if session is valid and authenticated.
        """
        if self._service is None:
            return False

        details = self.cookie_store.get_expiry_details(self.config.apple_id)
        if not details.exists:
            logger.warning("Session cookie does not exist")
            return False

        if details.days_remaining is not None and details.days_remaining < 1:
            logger.warning("Session expired or invalid")
            return False

        logger.debug("Session valid (%s days remaining)", details.days_remaining)
        return True

    def check_cookie_expiry(self) -> 'CookieExpiryInfo':
        """Check cookie expiry and log status.

        Follows docker-icloudpd's display_multifactor_authentication_expiry
        pattern: logs MFA cookie expiry date and days remaining, returns
        the details for the caller (sync engine) to decide on notifications.

        Returns:
            CookieExpiryInfo with expiry details.
        """
        from icloud_docker.auth.cookie_store import CookieExpiryInfo

        details = self.cookie_store.get_expiry_details(self.config.apple_id)

        if not details.exists:
            logger.warning("No cookie file found for %s", self.config.apple_id)
            return details

        # Log MFA cookie status (like docker-icloudpd)
        if details.mfa_expire_date:
            logger.info(
                "MFA cookie expires: %s",
                details.mfa_expire_date.strftime("%Y-%m-%d @ %H:%M:%S"),
            )
        if details.web_expire_date:
            logger.info(
                "Web cookie expires: %s",
                details.web_expire_date.strftime("%Y-%m-%d @ %H:%M:%S"),
            )

        if details.days_remaining is not None:
            logger.info("Days remaining until cookie expiration: %d", details.days_remaining)

            notification_days = getattr(self.config, "notification_days", 7)
            if details.days_remaining <= notification_days:
                if details.days_remaining <= 1:
                    logger.error(
                        "Final day before cookie expires for Apple ID: %s "
                        "— Please reinitialise now. This is your last reminder",
                        self.config.apple_id,
                    )
                else:
                    logger.warning(
                        "Only %d days until cookie expires for Apple ID: %s "
                        "— Please reinitialise",
                        details.days_remaining, self.config.apple_id,
                    )
        else:
            logger.info("Cookie expiry date could not be determined")

        if details.has_mfa_trust:
            logger.debug("MFA authentication: verified (HSA-TRUST present)")
        elif details.has_session_token:
            logger.debug("Session token present but MFA not yet verified")

        return details

    def reauthenticate(self, password: str) -> PyiCloudService:
        """Re-authenticate after session expiry.

        Delegates to authenticate() which performs a fresh login when
        force_refresh=True.

        Args:
            password: iCloud Apple ID password.

        Returns:
            Fresh PyiCloudService instance.
        """
        logger.info("Re-authenticating with iCloud...")
        return self.authenticate(password, force_refresh=True)
