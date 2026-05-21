"""Unit tests for HEIC to JPEG converter."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from icloud_docker.pipeline.base import ProcessorError
from icloud_docker.pipeline.builtin.heic_convert import HeicToJpgProcessor


class TestHeicToJpgProcessor:
    """Test HEIC converter initialization."""

    def test_default_config(self):
        proc = HeicToJpgProcessor()
        proc.init({})
        assert proc.quality == 85
        assert proc.remove_original is False

    def test_custom_quality(self):
        proc = HeicToJpgProcessor()
        proc.init({"quality": 50})
        assert proc.quality == 50

    def test_invalid_quality_raises(self):
        proc = HeicToJpgProcessor()
        with pytest.raises(ValueError):
            proc.init({"quality": 101})
        with pytest.raises(ValueError):
            proc.init({"quality": 0})

    def test_remove_original_config(self):
        proc = HeicToJpgProcessor()
        proc.init({"remove_original": True})
        assert proc.remove_original is True

    def test_non_heic_passthrough(self, tmp_path):
        """Non-HEIC files should pass through unchanged."""
        test_jpg = tmp_path / "test.jpg"
        test_jpg.write_text("fake jpg data")

        proc = HeicToJpgProcessor()
        proc.init({})
        result = proc.process(test_jpg, {"filename": "test.jpg"})
        assert result == test_jpg  # Pass through unchanged
        assert test_jpg.exists()

    def test_heic_conversion(self, tmp_path):
        """HEIC file triggers conversion attempt (pillow_heif not installed in test env)."""
        test_heic = tmp_path / "test.heic"
        test_heic.write_text("fake heic data")

        proc = HeicToJpgProcessor()
        proc.init({"quality": 80})

        # pillow_heif not installed → should return original path
        result = proc.process(test_heic, {"filename": "test.heic"})
        assert result == test_heic  # Passthrough without pillow_heif

    def test_remove_original_with_passthrough(self, tmp_path):
        """remove_original flag is stored correctly (passthrough without pillow_heif)."""
        test_jpg = tmp_path / "test.jpg"
        test_jpg.write_text("fake jpg data")

        proc = HeicToJpgProcessor()
        proc.init({"remove_original": True})
        assert proc.remove_original is True

        # Non-HEIC passthrough with remove_original
        result = proc.process(test_jpg, {"filename": "test.jpg"})
        assert result == test_jpg
        assert test_jpg.exists()

    def test_cleanup_noop(self):
        """Cleanup should not raise."""
        proc = HeicToJpgProcessor()
        proc.init({})
        proc.cleanup()  # No error
