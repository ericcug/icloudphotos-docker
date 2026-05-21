"""Unit tests for configuration loader."""

import tempfile
from pathlib import Path

import pytest
import yaml

from icloud_docker.config.loader import ConfigError, load_config
from icloud_docker.config.schema import Config


def _write_config(tmpdir: Path, data: dict) -> Path:
    """Helper: write a YAML config file and return path."""
    path = tmpdir / "config.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


class TestLoadConfig:
    """Test configuration loading and validation."""

    def test_load_minimal_valid_config(self, tmp_path):
        config_path = _write_config(tmp_path, {"apple_id": "test@example.com"})
        config = load_config(config_path)
        assert config.apple_id == "test@example.com"

    def test_missing_apple_id_raises(self, tmp_path):
        config_path = _write_config(tmp_path, {"download_path": "/tmp"})
        with pytest.raises(ConfigError, match="apple_id"):
            load_config(config_path)

    def test_invalid_folder_structure_raises(self, tmp_path):
        config_path = _write_config(tmp_path, {
            "apple_id": "test@example.com",
            "folder_structure": "invalid",
        })
        with pytest.raises(ConfigError, match="folder_structure"):
            load_config(config_path)

    def test_invalid_file_permissions_raises(self, tmp_path):
        config_path = _write_config(tmp_path, {
            "apple_id": "test@example.com",
            "file_permissions": "777",
        })
        with pytest.raises(ConfigError, match="file_permissions"):
            load_config(config_path)

    def test_invalid_delete_policy_raises(self, tmp_path):
        config_path = _write_config(tmp_path, {
            "apple_id": "test@example.com",
            "delete_policy": "destroy",
        })
        with pytest.raises(ConfigError, match="delete_policy"):
            load_config(config_path)

    def test_download_interval_too_small_raises(self, tmp_path):
        config_path = _write_config(tmp_path, {
            "apple_id": "test@example.com",
            "download_interval": 30,
        })
        with pytest.raises(ConfigError, match="download_interval"):
            load_config(config_path)

    def test_defaults_applied(self, tmp_path):
        config_path = _write_config(tmp_path, {"apple_id": "test@example.com"})
        config = load_config(config_path)
        assert config.download_interval == 86400
        assert config.file_permissions == "644"
        assert config.delete_policy == "keep"

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ICLOUD_APPLE_ID", "env@example.com")
        config_path = _write_config(tmp_path, {"apple_id": "file@example.com"})
        config = load_config(config_path)
        assert config.apple_id == "env@example.com"
