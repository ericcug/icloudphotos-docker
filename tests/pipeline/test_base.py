"""Unit tests for BaseProcessor abstract base class."""

from pathlib import Path

import pytest

from pipeline.base import BaseProcessor, ProcessorError


class TestBaseProcessor:
    """Test BaseProcessor ABC enforcement."""

    def test_cannot_instantiate_abstract(self):
        """Verify ABC cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseProcessor()

    def test_incomplete_implementation_raises(self):
        """Verify incomplete subclass raises TypeError."""
        with pytest.raises(TypeError):

            class IncompleteProcessor(BaseProcessor):
                pass

            IncompleteProcessor()

    def test_complete_implementation_ok(self):
        """Verify complete subclass can be instantiated."""

        class OkProcessor(BaseProcessor):
            version = "1.0.0"

            def init(self, config):
                pass

            def process(self, file_path, metadata):
                return file_path

            def cleanup(self):
                pass

        proc = OkProcessor()
        assert proc.version == "1.0.0"

    def test_version_default(self):
        """Verify default version string."""

        class DefaultVersionProcessor(BaseProcessor):
            def init(self, config):
                pass

            def process(self, file_path, metadata):
                return file_path

            def cleanup(self):
                pass

        proc = DefaultVersionProcessor()
        assert proc.version == "1.0.0"

    def test_processor_error(self):
        """Verify ProcessorError can be raised and caught."""
        with pytest.raises(ProcessorError, match="test error"):
            raise ProcessorError("test error")


class TestProcessorLifecycle:
    """Test processor lifecycle methods."""

    def test_init_called_with_config(self):
        config_received = {}

        class ConfigProcessor(BaseProcessor):
            def init(self, config):
                config_received.update(config)

            def process(self, file_path, metadata):
                return file_path

            def cleanup(self):
                pass

        proc = ConfigProcessor()
        proc.init({"key": "value"})
        assert config_received == {"key": "value"}

    def test_process_returns_path(self):
        class PathProcessor(BaseProcessor):
            def init(self, config):
                pass

            def process(self, file_path, metadata):
                return Path(str(file_path) + ".processed")

            def cleanup(self):
                pass

        proc = PathProcessor()
        proc.init({})
        result = proc.process(Path("/tmp/test.jpg"), {})
        assert result == Path("/tmp/test.jpg.processed")

    def test_cleanup_called(self):
        cleanup_called = []

        class CleanupProcessor(BaseProcessor):
            def init(self, config):
                pass

            def process(self, file_path, metadata):
                return file_path

            def cleanup(self):
                cleanup_called.append(True)

        proc = CleanupProcessor()
        proc.init({})
        proc.cleanup()
        assert cleanup_called == [True]
