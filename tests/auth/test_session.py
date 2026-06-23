"""Unit tests for AuthManager."""

from unittest.mock import MagicMock, patch

import pytest
from pyicloud_ipd.exceptions import (
    PyiCloudFailedLoginException,
    PyiCloudFailedMFAException,
)

from auth.cookie_store import CookieStore, CookieExpiryInfo
from auth.mfa import TelegramMFAProvider
from auth.session import AuthManager


@pytest.fixture
def mock_config():
    """Mock application configuration."""
    config = MagicMock()
    config.apple_id = "test@example.com"
    config.cookie_dir = "/tmp/cookies"
    config.auth_china = False
    return config


@pytest.fixture
def mock_cookie_store():
    """Mock CookieStore."""
    store = MagicMock(spec=CookieStore)
    store.cookie_dir = MagicMock()
    return store


@pytest.fixture
def mock_mfa_provider():
    """Mock TelegramMFAProvider."""
    provider = MagicMock(spec=TelegramMFAProvider)
    return provider


@pytest.fixture
def auth_manager(mock_config, mock_cookie_store, mock_mfa_provider):
    """AuthManager instance with mocked dependencies."""
    return AuthManager(mock_config, mock_cookie_store, mock_mfa_provider)


class TestAuthManager:
    @patch("auth.session.PyiCloudService")
    def test_authenticate_session_reuse_success(self, mock_pyicloud, auth_manager, mock_cookie_store):
        """Test successful session reuse (no MFA)."""
        # Setup: Valid cookies exist
        mock_cookie_store.validate_session.return_value = True
        
        # Setup: PyiCloudService does not require MFA
        mock_service = MagicMock()
        mock_service.requires_2fa = False
        mock_service.requires_2sa = False
        mock_pyicloud.return_value = mock_service

        result = auth_manager.authenticate("password123", force_refresh=False)
        
        assert result is mock_service
        assert auth_manager.service is mock_service
        mock_cookie_store.delete_cookie.assert_not_called()

    @patch("auth.session.PyiCloudService")
    def test_authenticate_session_reuse_fails_fallback_to_login(
        self, mock_pyicloud, auth_manager, mock_cookie_store
    ):
        """Test session reuse fails because server rejects it, fallback to full login."""
        mock_cookie_store.validate_session.return_value = True
        
        # First call (reuse attempt): requires MFA
        # Second call (full login): also requires MFA
        mock_service_1 = MagicMock()
        mock_service_1.requires_2fa = True
        mock_service_1.requires_2sa = False

        mock_service_2 = MagicMock()
        mock_service_2.requires_2fa = False
        mock_service_2.requires_2sa = False
        
        mock_pyicloud.side_effect = [mock_service_1, mock_service_2]

        result = auth_manager.authenticate("password123", force_refresh=False)
        
        assert result is mock_service_2
        # Verify it fell back and deleted cookies
        mock_cookie_store.delete_cookie.assert_called_once_with("test@example.com")
        assert mock_pyicloud.call_count == 2

    @patch("auth.session.PyiCloudService")
    def test_authenticate_force_refresh(self, mock_pyicloud, auth_manager, mock_cookie_store):
        """Test force_refresh skips reuse attempt and deletes cookies immediately."""
        mock_service = MagicMock()
        mock_service.requires_2fa = False
        mock_service.requires_2sa = False
        mock_pyicloud.return_value = mock_service

        result = auth_manager.authenticate("password123", force_refresh=True)
        
        assert result is mock_service
        mock_cookie_store.validate_session.assert_not_called()
        mock_cookie_store.delete_cookie.assert_called_once_with("test@example.com")

    @patch("auth.session.PyiCloudService")
    def test_authenticate_2fa_push_direct(
        self, mock_pyicloud, auth_manager, mock_cookie_store, mock_mfa_provider
    ):
        """Test full login with 2FA push code (no trusted devices SMS fallback)."""
        mock_cookie_store.validate_session.return_value = False
        
        mock_service = MagicMock()
        mock_service.requires_2fa = True
        mock_service.requires_2sa = False
        mock_service.get_trusted_phone_numbers.return_value = []
        mock_service.validate_2fa_code.side_effect = [False, True]  # fail once, then succeed
        mock_pyicloud.return_value = mock_service
        
        # Mock user providing code
        mock_mfa_provider.wait_for_code.side_effect = ["123", "123456", "654321"]

        result = auth_manager.authenticate("password123")
        
        assert result is mock_service
        # Called 3 times:
        # 1. "123" -> invalid length, rejected before calling validate
        # 2. "123456" -> validate_2fa_code returns False
        # 3. "654321" -> validate_2fa_code returns True
        assert mock_service.validate_2fa_code.call_count == 2
        mock_service.validate_2fa_code.assert_called_with("654321")

    @patch("auth.session.PyiCloudService")
    def test_authenticate_2fa_sms_fallback(
        self, mock_pyicloud, auth_manager, mock_cookie_store, mock_mfa_provider
    ):
        """Test 2FA using trusted device SMS fallback."""
        mock_cookie_store.validate_session.return_value = False
        
        mock_device = MagicMock()
        mock_device.obfuscated_number = "********12"
        mock_device.id = 1
        
        mock_service = MagicMock()
        mock_service.requires_2fa = True
        mock_service.requires_2sa = False
        mock_service.get_trusted_phone_numbers.return_value = [mock_device]
        mock_service.send_2fa_code_sms.return_value = True
        mock_service.validate_2fa_code_sms.return_value = True
        mock_pyicloud.return_value = mock_service
        
        # User selects 'a' for SMS, then enters code '123456'
        mock_mfa_provider.wait_for_code.side_effect = ["a", "123456"]

        result = auth_manager.authenticate("password123")
        
        assert result is mock_service
        mock_service.send_2fa_code_sms.assert_called_once_with(1)
        mock_service.validate_2fa_code_sms.assert_called_once_with(1, "123456")

    @patch("auth.session.PyiCloudService")
    def test_authenticate_login_exception(self, mock_pyicloud, auth_manager, mock_cookie_store):
        """Test PyiCloudFailedLoginException propagates."""
        mock_cookie_store.validate_session.return_value = False
        mock_pyicloud.side_effect = PyiCloudFailedLoginException("Bad password")

        with pytest.raises(PyiCloudFailedLoginException):
            auth_manager.authenticate("bad_password")

    def test_check_session_no_service(self, auth_manager):
        """Test check_session without authenticated service."""
        assert auth_manager.check_session() is False

    def test_check_session_valid(self, auth_manager, mock_cookie_store):
        """Test check_session with valid cookie."""
        auth_manager._service = MagicMock()
        
        info = CookieExpiryInfo(exists=True, days_remaining=5)
        mock_cookie_store.get_expiry_details.return_value = info
        
        assert auth_manager.check_session() is True

    def test_check_session_expired(self, auth_manager, mock_cookie_store):
        """Test check_session with expired cookie."""
        auth_manager._service = MagicMock()
        
        info = CookieExpiryInfo(exists=True, days_remaining=0)
        mock_cookie_store.get_expiry_details.return_value = info
        
        assert auth_manager.check_session() is False

    def test_check_cookie_expiry(self, auth_manager, mock_cookie_store):
        """Test check_cookie_expiry calls store and returns info."""
        auth_manager.config.notification_days = 7
        info = CookieExpiryInfo(exists=True, days_remaining=3)
        mock_cookie_store.get_expiry_details.return_value = info
        
        result = auth_manager.check_cookie_expiry()
        
        assert result is info
        mock_cookie_store.get_expiry_details.assert_called_once_with("test@example.com")
