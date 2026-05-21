"""End-to-end integration tests for iCloud Photo Downloader."""

import pytest

from config.loader import ConfigError, load_config
from config.schema import Config


@pytest.mark.integration
class TestEndToEnd:
    """End-to-end integration tests with mocked external dependencies."""

    def test_config_to_engine_startup(self, tmp_path, sample_config_dict):
        """Verify full startup flow: config → validation → (mock) engine."""
        import yaml

        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_path)
        assert config.apple_id == "test@example.com"
        assert config.download_interval == 3600
        assert config.notification.telegram.enabled is False
        assert config.pipeline.steps == []

    def test_missing_required_config_detected(self, tmp_path):
        """Verify error handling for missing required config."""
        import yaml

        config_path = tmp_path / "bad_config.yaml"
        with open(config_path, "w") as f:
            yaml.dump({"download_path": "/tmp"}, f)

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_password_filter_in_logger(self):
        """Verify password filter prevents credential leaks."""
        import logging
        import io

        from logger import PasswordFormatter

        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setFormatter(PasswordFormatter("%(message)s"))

        logger = logging.getLogger("test_password_filter")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        logger.warning("Using password my_secret_123 for auth")
        logger.info("Bot token abcdef123456 sent")

        output = log_stream.getvalue()
        assert "my_secret_123" not in output or "[REDACTED]" in output
