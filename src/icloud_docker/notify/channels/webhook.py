"""Webhook notification channel for system events."""

import logging

import requests

from icloud_docker.notify.bus import SystemEvent

logger = logging.getLogger(__name__)


class WebhookNotifier:
    """Sends system event notifications via HTTP webhook.

    Attributes:
        url: Webhook endpoint URL.
        method: HTTP method (POST).
        headers: Additional HTTP headers.
    """

    def __init__(self, url: str, method: str = "POST", headers: dict = None):
        """Initialize webhook notifier.

        Args:
            url: Webhook endpoint URL.
            method: HTTP method (default POST).
            headers: Additional request headers.
        """
        self.url = url
        self.method = method.upper()
        self.headers = headers or {}
        self.enabled = bool(url)

    def send(self, event: SystemEvent) -> bool:
        """Send an event notification via webhook.

        Args:
            event: SystemEvent to send.

        Returns:
            True if sent successfully.
        """
        if not self.enabled:
            return False

        payload = {
            "event_type": event.event_type,
            "severity": event.severity,
            "message": event.message,
            "timestamp": event.timestamp.isoformat(),
            "details": event.details,
        }

        try:
            defaults = {"Content-Type": "application/json"}
            defaults.update(self.headers)
            resp = requests.request(
                self.method, self.url, json=payload,
                headers=defaults, timeout=10,
            )

            if resp.status_code < 400:
                logger.debug("Webhook sent: %s (HTTP %d)", event.event_type, resp.status_code)
                return True
            else:
                logger.warning("Webhook failed (HTTP %d): %s", resp.status_code, resp.text)
                return False

        except Exception as e:
            logger.warning("Webhook send error: %s", e)
            return False
