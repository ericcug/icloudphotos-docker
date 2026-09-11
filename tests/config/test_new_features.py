"""Tests for newly introduced configuration options from upstream."""

import os
from pathlib import Path
import pytest

from config.loader import load_config
from config.schema import Config


def test_schema_defaults(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("apple_id: test@example.com\n")

    cfg = load_config(config_file)
    assert cfg.wait_for_reauthentication is True
    assert cfg.reauth_notification_interval is None
    assert cfg.xmp_sidecar is False
    assert cfg.keep_icloud_recent_days is None
    assert cfg.keep_icloud_recent_only is False
    assert cfg.min_free_disk_bytes == 1073741824


def test_env_overrides(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("apple_id: test@example.com\n")

    monkeypatch.setenv("ICLOUD_WAIT_FOR_REAUTHENTICATION", "false")
    monkeypatch.setenv("ICLOUD_REAUTH_NOTIFICATION_INTERVAL", "3600")
    monkeypatch.setenv("ICLOUD_XMP_SIDECAR", "true")
    monkeypatch.setenv("ICLOUD_KEEP_ICLOUD_RECENT_DAYS", "15")
    monkeypatch.setenv("ICLOUD_KEEP_ICLOUD_RECENT_ONLY", "true")
    monkeypatch.setenv("ICLOUD_MIN_FREE_DISK_BYTES", "524288000")

    cfg = load_config(config_file)
    assert cfg.wait_for_reauthentication is False
    assert cfg.reauth_notification_interval == 3600
    assert cfg.xmp_sidecar is True
    assert cfg.keep_icloud_recent_days == 15
    assert cfg.keep_icloud_recent_only is True
    assert cfg.min_free_disk_bytes == 524288000
