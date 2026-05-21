"""Cookie persistence and expiry detection for iCloud authentication sessions.

Manages the local storage of iCloud session cookies with file permission
controls, following the docker-icloudpd pattern. Supports both MFA cookies
(X-APPLE-WEBAUTH-USER / X-APPLE-WEBAUTH-HSA-TRUST) and web cookies
(X_APPLE_WEB_KB) for expiry detection and pre-expiry notification.
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Cookie header patterns (from docker-icloudpd sync-icloud.sh)
# MFA cookie: X-APPLE-WEBAUTH-USER → expires="2026-06-20T12:34:56Z"; HttpOnly
# Web cookie: X_APPLE_WEB_KB → expires="2026-06-20T12:34:56Z"; HttpOnly
# Trust header: X-APPLE-WEBAUTH-HSA-TRUST (present = MFA authenticated)
_EXPIRY_PATTERN = re.compile(r'expires="([^"]+?)Z?";\s*HttpOnly', re.IGNORECASE)
_MFA_USER_LINE = re.compile(r'^.*X-APPLE-WEBAUTH-USER.*$', re.MULTILINE)
_WEB_KB_LINE = re.compile(r'^.*X_APPLE_WEB_KB.*$', re.MULTILINE)
_HSA_TRUST = "X-APPLE-WEBAUTH-HSA-TRUST"
_SESSION_TOKEN = "X-APPLE-DS-WEB-SESSION-TOKEN"


@dataclass
class CookieExpiryInfo:
    """Cookie expiry status information.

    Attributes:
        exists: Whether the cookie file exists.
        has_mfa_trust: Whether MFA authentication is complete (HSA-TRUST present).
        has_session_token: Whether session token header is present.
        mfa_expire_date: MFA cookie expiry datetime (from X-APPLE-WEBAUTH-USER).
        web_expire_date: Web cookie expiry datetime (from X_APPLE_WEB_KB).
        days_remaining: Days until nearest cookie expiry (None if unparseable).
    """
    exists: bool = False
    has_mfa_trust: bool = False
    has_session_token: bool = False
    mfa_expire_date: Optional[datetime] = None
    web_expire_date: Optional[datetime] = None
    days_remaining: Optional[int] = None


class CookieStore:
    """Manages iCloud authentication cookie persistence.

    Stores the session cookie on the filesystem with restricted permissions
    (chmod 600). Provides expiry checking and cleanup following the
    docker-icloudpd pattern for both MFA and web cookies.

    Attributes:
        cookie_dir: Directory where cookies are stored.
    """

    def __init__(self, cookie_dir: Path):
        """Initialize cookie store.

        Args:
            cookie_dir: Directory path for cookie storage.
        """
        self.cookie_dir = Path(cookie_dir)
        self.cookie_dir.mkdir(parents=True, exist_ok=True)

    def cookie_path(self, apple_id: str) -> Path:
        """Generate the cookie file path for a given Apple ID.

        Args:
            apple_id: iCloud email address.

        Returns:
            Path to the cookie file.
        """
        safe_name = "".join(c for c in apple_id if c.isalnum() or c in "_-@.").lower()
        return self.cookie_dir / safe_name

    def save_cookie(self, apple_id: str, cookie_content: str) -> None:
        """Save session cookie to filesystem with restricted permissions.

        Args:
            apple_id: iCloud email address.
            cookie_content: Raw cookie data from iCloud session.
        """
        path = self.cookie_path(apple_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(cookie_content)
        os.chmod(path, 0o600)
        logger.info("Cookie saved to %s (permissions: 600)", path)

    def load_cookie(self, apple_id: str) -> str | None:
        """Load an existing session cookie.

        Args:
            apple_id: iCloud email address.

        Returns:
            Cookie content string, or None if not found.
        """
        path = self.cookie_path(apple_id)
        if not path.exists():
            logger.debug("No cookie found at %s", path)
            return None
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        logger.debug("Cookie loaded from %s", path)
        return content

    def cookie_exists(self, apple_id: str) -> bool:
        """Check if a cookie file exists for the given Apple ID.

        Args:
            apple_id: iCloud email address.

        Returns:
            True if cookie file exists.
        """
        return self.cookie_path(apple_id).exists()

    def delete_cookie(self, apple_id: str) -> None:
        """Delete the cookie file for the given Apple ID.

        Args:
            apple_id: iCloud email address.
        """
        path = self.cookie_path(apple_id)
        if path.exists():
            path.unlink()
            logger.info("Cookie deleted: %s", path)

    @staticmethod
    def _parse_expiry_from_line(line: str) -> Optional[datetime]:
        """Extract expiry datetime from a cookie header line.

        Parses the expires="..." value following the docker-icloudpd pattern:
            sed -e 's#.*expires="\\(.*\\)Z"; HttpOnly.*#\\1#'

        Args:
            line: Single cookie header line.

        Returns:
            Parsed datetime or None if unparseable.
        """
        match = _EXPIRY_PATTERN.search(line)
        if not match:
            return None
        expire_str = match.group(1).strip()
        # Try common iCloud date formats
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(expire_str, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        logger.warning("Failed to parse expiry date: %s", expire_str)
        return None

    def get_expiry_details(self, apple_id: str) -> CookieExpiryInfo:
        """Get comprehensive cookie expiry information.

        Inspects the cookie file for both MFA and web cookie headers,
        following the docker-icloudpd pattern:
        - check_multifactor_authentication_cookie(): X-APPLE-WEBAUTH-USER,
          X-APPLE-WEBAUTH-HSA-TRUST, X-APPLE-DS-WEB-SESSION-TOKEN
        - check_web_cookie(): X_APPLE_WEB_KB

        Args:
            apple_id: iCloud email address.

        Returns:
            CookieExpiryInfo with all parsed cookie status details.
        """
        info = CookieExpiryInfo()
        content = self.load_cookie(apple_id)
        if content is None:
            return info

        info.exists = True
        info.has_mfa_trust = _HSA_TRUST in content
        info.has_session_token = _SESSION_TOKEN in content

        # Parse MFA cookie expiry (X-APPLE-WEBAUTH-USER)
        mfa_match = _MFA_USER_LINE.search(content)
        if mfa_match:
            info.mfa_expire_date = self._parse_expiry_from_line(mfa_match.group(0))

        # Parse web cookie expiry (X_APPLE_WEB_KB)
        web_match = _WEB_KB_LINE.search(content)
        if web_match:
            info.web_expire_date = self._parse_expiry_from_line(web_match.group(0))

        # Calculate days remaining (use the nearest expiry)
        now = datetime.now(timezone.utc)
        expire_dates = [d for d in (info.mfa_expire_date, info.web_expire_date) if d is not None]
        if expire_dates:
            nearest = min(expire_dates)
            info.days_remaining = (nearest - now).days

        return info

    def check_expiry(self, apple_id: str, notification_days: int = 7) -> int | None:
        """Check cookie expiry and return days remaining.

        Inspects the cookie file for MFA and web cookie expiry headers,
        following the docker-icloudpd pattern. Prefers MFA cookie expiry
        (X-APPLE-WEBAUTH-USER) over web cookie (X_APPLE_WEB_KB).

        Args:
            apple_id: iCloud email address.
            notification_days: Days threshold for expiry warning.

        Returns:
            Days remaining until expiry, or None if cookie doesn't exist
            or expiry is unparseable. Returns 0 or negative if expired.
        """
        details = self.get_expiry_details(apple_id)
        if not details.exists:
            return None

        days_remaining = details.days_remaining
        if days_remaining is None:
            logger.warning("Could not parse expiry from cookie for %s", apple_id)
            return None

        expire_date = details.mfa_expire_date or details.web_expire_date

        if days_remaining <= notification_days and days_remaining >= 1:
            logger.warning(
                "Cookie expires in %d days (at %s, notification threshold: %d)",
                days_remaining, expire_date, notification_days,
            )
        elif days_remaining < 1:
            logger.error("Cookie has expired at %s (%d days remaining)", expire_date, days_remaining)

        return days_remaining

    def validate_session(self, apple_id: str) -> bool:
        """Check if a valid (non-expired) cookie exists for the given Apple ID.

        Combines existence check and expiry validation into a single call.
        Returns True only if the cookie file exists and has at least 1 day
        remaining before expiry.

        Args:
            apple_id: iCloud email address.

        Returns:
            True if a valid, non-expired cookie exists.
        """
        if not self.cookie_exists(apple_id):
            logger.debug("No cookie found for %s", apple_id)
            return False

        days = self.check_expiry(apple_id)
        if days is None:
            # Could not parse expiry — treat cookie as potentially valid
            # since PyiCloudService will validate it server-side.
            logger.info("Cookie exists but expiry unknown for %s, will attempt reuse", apple_id)
            return True

        if days < 1:
            logger.info("Cookie expired for %s (%d days remaining)", apple_id, days)
            return False

        logger.info("Cookie valid for %s (%d days remaining)", apple_id, days)
        return True

