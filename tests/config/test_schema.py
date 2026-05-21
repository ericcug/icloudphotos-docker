"""Unit tests for configuration schema definitions."""

from config.schema import (
    VALID_DELETE_POLICIES,
    VALID_FILE_MATCH_POLICIES,
    VALID_FILE_PERMISSIONS,
    VALID_FOLDER_STRUCTURES,
    VALID_LOG_LEVELS,
    Config,
    NotificationConfig,
    PipelineConfig,
    TelegramConfig,
    WebhookConfig,
)


class TestConfigDefaults:
    """Test Config default values."""

    def test_default_apple_id_empty(self):
        config = Config()
        assert config.apple_id == ""

    def test_default_download_path(self):
        config = Config()
        assert str(config.download_path) == "/data/photos"

    def test_default_intervals(self):
        config = Config()
        assert config.download_interval == 86400
        assert config.download_delay == 0
        assert config.retry_interval == 120
        assert config.retry_count == 3

    def test_default_delete_policy(self):
        config = Config()
        assert config.delete_policy == "keep"

    def test_default_notification_disabled(self):
        config = Config()
        assert config.notification.telegram.enabled is False
        assert config.notification.webhook.enabled is False

    def test_default_pipeline_empty(self):
        config = Config()
        assert config.pipeline.steps == []


class TestValidationConstants:
    """Test validation constant sets."""

    def test_valid_folder_structures(self):
        assert "YYYY/MM" in VALID_FOLDER_STRUCTURES
        assert "YYYY-MM-DD" in VALID_FOLDER_STRUCTURES
        assert "album" in VALID_FOLDER_STRUCTURES
        assert "none" in VALID_FOLDER_STRUCTURES

    def test_valid_delete_policies(self):
        assert "keep" in VALID_DELETE_POLICIES
        assert "delete" in VALID_DELETE_POLICIES
        assert "trash" in VALID_DELETE_POLICIES

    def test_valid_file_permissions(self):
        assert "644" in VALID_FILE_PERMISSIONS
        assert "600" in VALID_FILE_PERMISSIONS

    def test_valid_log_levels(self):
        assert "info" in VALID_LOG_LEVELS
        assert "debug" in VALID_LOG_LEVELS
