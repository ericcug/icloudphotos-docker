"""Unit tests for TelegramMFAProvider."""

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

from auth.mfa import TelegramMFAProvider
from notify.channels.telegram_service import TelegramService


@pytest.fixture
def mock_service():
    """Provide a mock TelegramService."""
    service = MagicMock(spec=TelegramService)
    service.is_running = True
    service.send_message.return_value = True
    return service


@pytest.fixture
def provider(mock_service):
    """Provide a TelegramMFAProvider with mock service."""
    return TelegramMFAProvider(service=mock_service, chat_id="12345", timeout=1)


class TestTelegramMFAProvider:
    def test_is_telegram_configured_true(self, provider):
        """Test configured check returns True when valid."""
        assert provider.is_telegram_configured is True

    def test_is_telegram_configured_false_no_service(self):
        """Test configured check returns False without service."""
        provider = TelegramMFAProvider(chat_id="12345")
        assert provider.is_telegram_configured is False

    def test_is_telegram_configured_false_not_running(self, provider):
        """Test configured check returns False if service not running."""
        provider.service.is_running = False
        assert provider.is_telegram_configured is False

    def test_send_prompt_with_telegram(self, provider):
        """Test sending prompt via Telegram."""
        result = provider.send_prompt("Test prompt")
        assert result is True
        provider.service.send_message.assert_called_once()
        args, kwargs = provider.service.send_message.call_args
        assert kwargs["chat_id"] == "12345"
        assert "Test prompt" in kwargs["text"]

    def test_send_prompt_without_telegram(self, capsys):
        """Test sending prompt prints to console when Telegram not configured."""
        provider = TelegramMFAProvider()
        result = provider.send_prompt("Console prompt")
        
        assert result is False
        stderr = capsys.readouterr().err
        assert "MFA Required" in stderr
        assert "Console prompt" in stderr

    def test_provide_code(self, provider):
        """Test providing a code signals the event."""
        provider.provide_code("123456")
        assert provider._code == "123456"
        assert provider._code_event.is_set()

    def test_wait_for_code_timeout(self, provider):
        """Test wait_for_code raises TimeoutError."""
        # Use short timeout and no one provides code
        with pytest.raises(TimeoutError, match="No MFA code received"):
            provider.wait_for_code(timeout=0.1)

    def test_wait_for_code_success(self, provider):
        """Test wait_for_code returns provided code."""
        def provide_delayed():
            provider.provide_code(" 123456 ")

        # Schedule code injection after a slight delay
        timer = threading.Timer(0.1, provide_delayed)
        timer.start()

        code = provider.wait_for_code(timeout=1.0)
        assert code == "123456"

    @patch("sys.stdin.readline")
    def test_wait_for_code_stdin_fallback_when_telegram_enabled(self, mock_readline, provider):
        """Test stdin works even if Telegram is enabled."""
        # Simulate user typing code in stdin
        mock_readline.return_value = "654321\n"
        
        code = provider.wait_for_code(timeout=1.0)
        assert code == "654321"

    @patch("builtins.input")
    def test_wait_for_code_stdin_only(self, mock_input, capsys):
        """Test wait_for_code with no Telegram configured uses direct stdin."""
        provider = TelegramMFAProvider()
        
        # input() called directly
        mock_input.side_effect = ["abc", "123456"]
        
        code = provider.wait_for_code()
        assert code == "123456"
        
        stdout = capsys.readouterr().out
        assert "Invalid code" in stdout

    def test_request_code_convenience(self, provider):
        """Test request_code sends prompt and waits."""
        def provide_delayed():
            provider.provide_code("999999")

        timer = threading.Timer(0.1, provide_delayed)
        timer.start()

        code = provider.request_code("Action required")
        assert code == "999999"
        provider.service.send_message.assert_called_once()

    def test_reset(self, provider):
        """Test reset clears internal state."""
        provider.provide_code("111111")
        assert provider._code == "111111"
        assert provider._code_event.is_set()

        provider.reset()
        assert provider._code is None
        assert provider._code_event.is_set() is False
