"""Unit tests for notification channels (Telegram + Webhook)."""

from unittest.mock import MagicMock, patch

from notify.bus import EventType, SystemEvent
from notify.channels.telegram import TelegramNotifier
from notify.channels.webhook import WebhookNotifier


class TestTelegramNotifier:
    """Test Telegram notification channel."""

    def test_disabled_when_no_token(self):
        notifier = TelegramNotifier("", "")
        assert notifier.enabled == False

    def test_enabled_with_credentials(self):
        notifier = TelegramNotifier("token123", "chat456")
        assert notifier.enabled is True

    @patch("notify.channels.telegram.requests.post")
    def test_send_success(self, mock_post):
        mock_post.return_value.status_code = 200
        notifier = TelegramNotifier("token", "chat")
        event = SystemEvent(event_type=EventType.START, message="Test started")

        result = notifier.send(event)
        assert result is True
        mock_post.assert_called_once()

    @patch("notify.channels.telegram.requests.post")
    def test_send_failure(self, mock_post):
        mock_post.return_value.status_code = 500
        notifier = TelegramNotifier("token", "chat")
        event = SystemEvent(event_type="error", message="fail")

        result = notifier.send(event)
        assert result is False

    def test_disabled_does_not_send(self):
        notifier = TelegramNotifier("", "")
        event = SystemEvent(event_type="start", message="test")
        assert notifier.send(event) is False

    def test_emoji_mapping(self):
        notifier = TelegramNotifier("token", "chat")
        assert isinstance(notifier.EVENT_EMOJI, dict)
        assert "start" in notifier.EVENT_EMOJI
        assert "error" in notifier.EVENT_EMOJI


class TestWebhookNotifier:
    """Test Webhook notification channel."""

    def test_disabled_when_no_url(self):
        notifier = WebhookNotifier("")
        assert notifier.enabled == False

    def test_enabled_with_url(self):
        notifier = WebhookNotifier("https://hooks.example.com/webhook")
        assert notifier.enabled is True

    @patch("notify.channels.webhook.requests.request")
    def test_send_success(self, mock_request):
        mock_request.return_value.status_code = 200
        notifier = WebhookNotifier("https://hooks.example.com/webhook")
        event = SystemEvent(event_type="complete", message="Done")

        result = notifier.send(event)
        assert result is True

    @patch("notify.channels.webhook.requests.request")
    def test_send_failure(self, mock_request):
        mock_request.return_value.status_code = 500
        notifier = WebhookNotifier("https://hooks.example.com/webhook")
        event = SystemEvent(event_type="error", message="fail")

        result = notifier.send(event)
        assert result is False

    def test_custom_headers(self):
        notifier = WebhookNotifier(
            "https://hooks.example.com",
            method="PUT",
            headers={"Authorization": "Bearer test"},
        )
        assert notifier.method == "PUT"
        assert notifier.headers["Authorization"] == "Bearer test"
