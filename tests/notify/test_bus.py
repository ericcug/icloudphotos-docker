"""Unit tests for event bus and caching."""

from datetime import datetime, timedelta, timezone

from notify.bus import EventBus, EventType, SystemEvent


class TestEventBus:
    """Test EventBus pub/sub and caching."""

    def test_publish_to_subscriber(self):
        received = []
        bus = EventBus()

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.START, handler)
        event = SystemEvent(event_type=EventType.START, message="Test start")
        bus.publish(event)
        assert len(received) == 1
        assert received[0].message == "Test start"

    def test_no_subscriber_caches_event(self):
        bus = EventBus()
        event = SystemEvent(event_type=EventType.ERROR, message="Test error")
        bus.publish(event)
        assert len(bus.cached_events) == 1

    def test_cache_flush_delivers_to_late_subscriber(self):
        bus = EventBus()
        received = []

        # Publish before subscriber
        event = SystemEvent(event_type=EventType.START, message="delayed")
        bus.publish(event)
        assert len(received) == 0

        # Subscribe and flush
        bus.subscribe(EventType.START, lambda e: received.append(e))
        bus.flush_cache()
        assert len(received) == 1

    def test_subscription_filter(self):
        bus = EventBus(subscribed_events=["start", "error"])
        received = []

        bus.subscribe("start", lambda e: received.append(e))
        bus.subscribe("error", lambda e: received.append(e))
        bus.subscribe("complete", lambda e: received.append(e))

        bus.publish(SystemEvent(event_type="start", message="s"))
        bus.publish(SystemEvent(event_type="complete", message="c"))

        assert len(received) == 1  # Only "start" passed through

    def test_cache_ttl_expiry(self):
        bus = EventBus()
        expired_event = SystemEvent(
            event_type=EventType.START,
            message="expired",
            timestamp=datetime.now(timezone.utc) - timedelta(days=2),
        )
        bus.cached_events.append(expired_event)

        received = []
        bus.subscribe(EventType.START, lambda e: received.append(e))
        delivered = bus.flush_cache()
        assert delivered == 0  # Expired, not delivered
        assert len(received) == 0

    def test_cache_size_limit(self):
        bus = EventBus()
        for i in range(1500):
            bus._cache_event(SystemEvent(event_type="start", message=f"evt{i}"))
        assert len(bus.cached_events) <= bus.MAX_CACHE_SIZE

    def test_handler_exception_does_not_crash_bus(self):
        bus = EventBus()
        received = []

        def failing_handler(event):
            raise RuntimeError("boom")

        def ok_handler(event):
            received.append(event)

        bus.subscribe(EventType.ERROR, failing_handler)
        bus.subscribe(EventType.ERROR, ok_handler)

        bus.publish(SystemEvent(event_type=EventType.ERROR, message="test"))
        assert len(received) == 1  # Second handler still delivered


class TestSystemEvent:
    """Test SystemEvent dataclass."""

    def test_default_timestamp(self):
        event = SystemEvent(event_type="test")
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)

    def test_fields(self):
        event = SystemEvent(
            event_type=EventType.AUTH_EXPIRED,
            severity="warning",
            message="Cookie expires in 1 day",
            details={"apple_id": "test@example.com"},
        )
        assert event.event_type == "auth_expired"
        assert event.severity == "warning"
        assert event.details["apple_id"] == "test@example.com"
