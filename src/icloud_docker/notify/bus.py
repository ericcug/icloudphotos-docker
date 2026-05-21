"""Event bus for system event publishing and subscription.

Defines standard event types and provides pub/sub dispatching
to configured notification channels.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SystemEvent:
    """A system event for notification.

    Attributes:
        event_type: Type identifier (start, complete, error, etc.)
        timestamp: When the event occurred.
        severity: info, warning, error, critical.
        message: Human-readable description.
        details: Optional extra data dict.
    """
    event_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    severity: str = "info"
    message: str = ""
    details: Optional[Dict] = None


# Standard event types (FR-017)
class EventType:
    """Standard system event type constants."""
    START = "start"
    COMPLETE = "complete"
    ERROR = "error"
    AUTH_EXPIRED = "auth_expired"
    COOKIE_EXPIRING = "cookie_expiring"
    LOW_SPACE = "low_space"
    RATE_LIMITED = "rate_limited"
    SYNC_PAUSED = "sync_paused"
    SYNC_RESUMED = "sync_resumed"
    MFA_REQUESTED = "mfa_requested"


class EventBus:
    """Publish/subscribe event bus for system notifications.

    Routes events to subscribed handlers (notification channels).
    Supports selective event type subscription and caching for
    offline channels.

    Attributes:
        subscribers: Dict mapping event_type → list of handlers.
        cached_events: Cached events for offline channels (max 24h TTL).
    """

    MAX_CACHE_SIZE = 1000  # Maximum cached events
    CACHE_TTL_SECONDS = 86400  # 24 hours

    def __init__(self, subscribed_events: Optional[List[str]] = None):
        """Initialize event bus.

        Args:
            subscribed_events: List of event types to relay (None = all).
        """
        self.subscribers: Dict[str, List[Callable]] = {}
        self.subscribed_events = subscribed_events or []
        self.cached_events: deque = deque()
        self._cache_cleanup()

    def subscribe(self, event_type: str, handler: Callable[[SystemEvent], None]) -> None:
        """Subscribe a handler to an event type.

        Args:
            event_type: Event type to subscribe to.
            handler: Callable that receives SystemEvent.
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)

    def publish(self, event: SystemEvent) -> None:
        """Publish an event to all subscribers.

        If no subscribers are available for the event type (e.g., channel
        offline), the event is cached for later retry (FR-020).

        Args:
            event: SystemEvent to publish.
        """
        # Filter by subscription list
        if self.subscribed_events and event.event_type not in self.subscribed_events:
            logger.debug("Event '%s' not in subscribed list, skipping", event.event_type)
            return

        handlers = self.subscribers.get(event.event_type, [])

        if not handlers:
            # Cache for later when handlers may become available
            self._cache_event(event)
            logger.debug("No handlers for event '%s', cached", event.event_type)
            return

        delivered = False
        for handler in handlers:
            try:
                handler(event)
                delivered = True
            except Exception as e:
                logger.warning("Failed to deliver event '%s': %s", event.event_type, e)

        if not delivered:
            self._cache_event(event)

    def _cache_event(self, event: SystemEvent) -> None:
        """Cache an event for later retry.

        Events older than 24h are discarded (FR-020).
        Max cache size enforced to prevent unbounded growth.

        Args:
            event: SystemEvent to cache.
        """
        self.cached_events.append(event)

        # Enforce max cache size
        while len(self.cached_events) > self.MAX_CACHE_SIZE:
            self.cached_events.popleft()

        logger.debug("Event '%s' cached (%d total in cache)",
                      event.event_type, len(self.cached_events))

    def flush_cache(self) -> int:
        """Attempt to re-deliver all cached events.

        Events that fail again are re-cached. Expired events are dropped.

        Returns:
            Number of events delivered successfully.
        """
        delivered = 0
        expired = 0
        retry = deque()

        while self.cached_events:
            event = self.cached_events.popleft()

            # Check TTL
            age = (datetime.now(timezone.utc) - event.timestamp).total_seconds()
            if age > self.CACHE_TTL_SECONDS:
                expired += 1
                continue

            handlers = self.subscribers.get(event.event_type, [])
            success = False
            for handler in handlers:
                try:
                    handler(event)
                    success = True
                except Exception:
                    pass

            if success:
                delivered += 1
            else:
                retry.append(event)

        self.cached_events = retry
        logger.info("Cache flush: %d delivered, %d expired, %d retry",
                     delivered, expired, len(retry))
        return delivered

    def _cache_cleanup(self) -> None:
        """Remove expired events from cache."""
        now = datetime.now(timezone.utc)
        keep = deque()
        expired = 0
        while self.cached_events:
            event = self.cached_events.popleft()
            if (now - event.timestamp).total_seconds() <= self.CACHE_TTL_SECONDS:
                keep.append(event)
            else:
                expired += 1
        self.cached_events = keep
        if expired:
            logger.debug("Cleaned up %d expired events from cache", expired)
