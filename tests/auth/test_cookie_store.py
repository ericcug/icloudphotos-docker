"""Unit tests for CookieStore."""

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from auth.cookie_store import CookieStore, CookieExpiryInfo

# Mock cookie content strings
MFA_COOKIE = '''# Netscape HTTP Cookie File
# http://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file!  Do not edit.

.apple.com	TRUE	/	TRUE	1781843696	X-APPLE-WEBAUTH-USER	expires="2026-06-20T12:34:56Z"; HttpOnly
.apple.com	TRUE	/	TRUE	1781843696	X-APPLE-WEBAUTH-HSA-TRUST	trust-token
.apple.com	TRUE	/	TRUE	1781843696	X-APPLE-DS-WEB-SESSION-TOKEN	session-token
'''

WEB_COOKIE = '''# Netscape HTTP Cookie File
.apple.com	TRUE	/	TRUE	1781843696	X_APPLE_WEB_KB	expires="2026-06-25T12:34:56Z"; HttpOnly
'''

NO_EXPIRY_COOKIE = '''# Netscape HTTP Cookie File
.apple.com	TRUE	/	TRUE	1781843696	X-APPLE-WEBAUTH-USER	v=1
'''

@pytest.fixture
def cookie_store(tmp_path):
    """Fixture to provide a CookieStore instance."""
    return CookieStore(cookie_dir=tmp_path)


class TestCookieStore:
    def test_cookie_path_generation(self, cookie_store, tmp_path):
        """Test cookie file path generation handles special chars."""
        apple_id = "test.user+alias@example.com"
        expected = tmp_path / "testuseraliasexamplecom"
        assert cookie_store.cookie_path(apple_id) == expected

    def test_save_and_load_cookie(self, cookie_store):
        """Test saving and loading cookie content."""
        apple_id = "test@example.com"
        cookie_store.save_cookie(apple_id, MFA_COOKIE)
        
        # Verify content
        content = cookie_store.load_cookie(apple_id)
        assert content == MFA_COOKIE
        
        # Verify permissions
        path = cookie_store.cookie_path(apple_id)
        assert oct(path.stat().st_mode & 0o777) == oct(0o600)

    def test_load_nonexistent_cookie(self, cookie_store):
        """Test loading a cookie that doesn't exist returns None."""
        assert cookie_store.load_cookie("nonexistent@example.com") is None

    def test_cookie_exists(self, cookie_store):
        """Test checking if cookie exists."""
        apple_id = "test@example.com"
        assert cookie_store.cookie_exists(apple_id) is False
        
        cookie_store.save_cookie(apple_id, MFA_COOKIE)
        assert cookie_store.cookie_exists(apple_id) is True

    def test_delete_cookie(self, cookie_store):
        """Test deleting a cookie."""
        apple_id = "test@example.com"
        cookie_store.save_cookie(apple_id, MFA_COOKIE)
        assert cookie_store.cookie_exists(apple_id) is True
        
        cookie_store.delete_cookie(apple_id)
        assert cookie_store.cookie_exists(apple_id) is False
        
        # Deleting nonexistent should not raise error
        cookie_store.delete_cookie("nonexistent@example.com")

    def test_get_expiry_details_mfa(self, cookie_store):
        """Test parsing MFA cookie expiry."""
        apple_id = "test@example.com"
        cookie_store.save_cookie(apple_id, MFA_COOKIE)
        
        details = cookie_store.get_expiry_details(apple_id)
        assert details.exists is True
        assert details.has_mfa_trust is True
        assert details.has_session_token is True
        assert details.mfa_expire_date == datetime(2026, 6, 20, 12, 34, 56, tzinfo=timezone.utc)
        assert details.web_expire_date is None

    def test_get_expiry_details_web(self, cookie_store):
        """Test parsing web cookie expiry."""
        apple_id = "test@example.com"
        cookie_store.save_cookie(apple_id, WEB_COOKIE)
        
        details = cookie_store.get_expiry_details(apple_id)
        assert details.exists is True
        assert details.has_mfa_trust is False
        assert details.has_session_token is False
        assert details.web_expire_date == datetime(2026, 6, 25, 12, 34, 56, tzinfo=timezone.utc)
        assert details.mfa_expire_date is None

    def test_get_expiry_details_none(self, cookie_store):
        """Test parsing cookie without expiry."""
        apple_id = "test@example.com"
        cookie_store.save_cookie(apple_id, NO_EXPIRY_COOKIE)
        
        details = cookie_store.get_expiry_details(apple_id)
        assert details.exists is True
        assert details.mfa_expire_date is None
        assert details.web_expire_date is None
        assert details.days_remaining is None

    def test_check_expiry_days_remaining(self, cookie_store, mocker):
        """Test calculating days remaining."""
        apple_id = "test@example.com"
        cookie_store.save_cookie(apple_id, MFA_COOKIE)
        
        # Mock current time to 5 days before expiry
        class MockDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 6, 15, 12, 34, 56, tzinfo=timezone.utc)
                
        mocker.patch("auth.cookie_store.datetime", MockDatetime)
        
        days = cookie_store.check_expiry(apple_id)
        assert days == 5

    def test_validate_session_valid(self, cookie_store, mocker):
        """Test session validation when valid."""
        apple_id = "test@example.com"
        cookie_store.save_cookie(apple_id, MFA_COOKIE)
        
        class MockDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 6, 15, 12, 34, 56, tzinfo=timezone.utc)
                
        mocker.patch("auth.cookie_store.datetime", MockDatetime)
        
        assert cookie_store.validate_session(apple_id) is True

    def test_validate_session_expired(self, cookie_store, mocker):
        """Test session validation when expired."""
        apple_id = "test@example.com"
        cookie_store.save_cookie(apple_id, MFA_COOKIE)
        
        # Mock current time to 1 day after expiry
        class MockDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 6, 21, 12, 34, 56, tzinfo=timezone.utc)
                
        mocker.patch("auth.cookie_store.datetime", MockDatetime)
        
        assert cookie_store.validate_session(apple_id) is False

    def test_validate_session_unknown_expiry(self, cookie_store):
        """Test session validation falls back to True if unparseable."""
        apple_id = "test@example.com"
        cookie_store.save_cookie(apple_id, NO_EXPIRY_COOKIE)
        
        assert cookie_store.validate_session(apple_id) is True
