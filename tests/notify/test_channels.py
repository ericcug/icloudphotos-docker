"""Unit tests for notification channels (Telegram + Webhook)."""

from unittest.mock import MagicMock, patch

from notify.bus import EventType, SystemEvent
from notify.channels.telegram import TelegramNotifier
from notify.channels.webhook import WebhookNotifier


def _make_service(send_result=True):
    """Create a mock TelegramService."""
    svc = MagicMock()
    svc.is_running = True
    svc.send_message.return_value = send_result
    return svc


class TestTelegramNotifier:
    """Test Telegram notification channel."""

    def test_disabled_when_no_chat_id(self):
        svc = _make_service()
        notifier = TelegramNotifier(svc, "")
        assert notifier.enabled is False

    def test_enabled_with_service_and_chat_id(self):
        svc = _make_service()
        notifier = TelegramNotifier(svc, "chat456")
        assert notifier.enabled is True

    def test_send_success(self):
        svc = _make_service(send_result=True)
        notifier = TelegramNotifier(svc, "chat")
        event = SystemEvent(event_type=EventType.START, message="Test started")

        result = notifier.send(event)
        assert result is True
        svc.send_message.assert_called_once()

    def test_send_failure(self):
        svc = _make_service(send_result=False)
        notifier = TelegramNotifier(svc, "chat")
        event = SystemEvent(event_type="error", message="fail")

        result = notifier.send(event)
        assert result is False

    def test_disabled_does_not_send(self):
        svc = MagicMock()
        svc.is_running = False
        notifier = TelegramNotifier(svc, "")
        event = SystemEvent(event_type="start", message="test")
        assert notifier.send(event) is False

    def test_emoji_mapping(self):
        svc = _make_service()
        notifier = TelegramNotifier(svc, "chat")
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
