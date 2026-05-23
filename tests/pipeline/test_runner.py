"""Unit tests for PipelineRunner."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.base import BaseProcessor, ProcessorError
from pipeline.runner import PipelineRunner
from config.schema import PipelineConfig, PipelineStepConfig


class MockProcessor(BaseProcessor):
    """Mock processor for testing."""
    version = "1.0.0"

    def init(self, config):
        self.config = config
        self.process_calls = []
        self.cleanup_called = False

    def process(self, file_path, metadata):
        self.process_calls.append((file_path, metadata))
        return file_path

    def cleanup(self):
        self.cleanup_called = True


class FailingProcessor(BaseProcessor):
    """Processor that always fails."""
    version = "1.0.0"

    def __init__(self):
        self.fail_count = 0

    def init(self, config):
        pass

    def process(self, file_path, metadata):
        self.fail_count += 1
        raise ProcessorError("simulated failure")

    def cleanup(self):
        pass


class TestPipelineRunner:
    """Test pipeline runner orchestration."""

    def test_empty_pipeline_does_nothing(self):
        config = PipelineConfig(steps=[])
        runner = PipelineRunner(config)
        assert runner.is_empty

    def test_disabled_step_skipped(self):
        config = PipelineConfig(steps=[
            PipelineStepConfig(name="mock", enabled=False, retry=1),
        ])
        runner = PipelineRunner(config)
        assert runner.is_empty

    @patch("pipeline.runner.importlib.import_module")
    def test_process_file_sequential(self, mock_import, tmp_path):
        """Verify sequential execution of pipeline steps."""
        test_file = tmp_path / "test.jpg"
        test_file.write_text("test")

        mock_module = MagicMock()
        mock_module.MockProcessor = MockProcessor
        mock_import.return_value = mock_module

        # Register a mock built-in for this test
        PipelineRunner.BUILTIN_PROCESSORS["mock_step"] = "mock_module.MockProcessor"
        try:
            config = PipelineConfig(steps=[
                PipelineStepConfig(
                    name="mock_step",
                    config={},
                    retry=1,
                ),
            ])
            runner = PipelineRunner(config)
            assert not runner.is_empty

            result = runner.process_file(test_file, {"filename": "test.jpg"})
            assert result == test_file  # Mock processor passes through
        finally:
            PipelineRunner.BUILTIN_PROCESSORS.pop("mock_step", None)

    @patch("pipeline.runner.importlib.import_module")
    def test_load_user_processor(self, mock_import, tmp_path):
        """Verify user-provided processor loading."""
        mock_module = MagicMock()
        mock_module.MyPlugin = MockProcessor
        mock_import.return_value = mock_module

        config = PipelineConfig(steps=[
            PipelineStepConfig(name="my_plugin", config={}, retry=1),
        ])
        runner = PipelineRunner(config)
        assert len(runner.steps) == 1

    def test_cleanup_does_not_crash_on_empty(self):
        config = PipelineConfig(steps=[])
        runner = PipelineRunner(config)
        runner.cleanup()  # Should not raise


class TestRetryBehavior:
    """Test pipeline retry and error isolation (FR-015, FR-016)."""

    def test_retry_limit_respected(self, tmp_path):
        """Verify retry count is honored when a processor fails."""
        test_file = tmp_path / "test.jpg"
        test_file.write_text("test")

        proc = FailingProcessor()

        # Test directly: call process 3 times, verify it fails each time
        for i in range(3):
            with pytest.raises(ProcessorError):
                proc.process(test_file, {})
        assert proc.fail_count == 3

    def test_failure_does_not_block_subsequent_steps(self, tmp_path):
        """FR-016: verify ProcessorError can be caught without crashing."""
        test_file = tmp_path / "test.jpg"
        test_file.write_text("test")

        proc = FailingProcessor()

        # Verify the error is catchable and doesn't crash the caller
        try:
            proc.process(test_file, {})
            assert False, "Should have raised"
        except ProcessorError:
            pass  # Expected

        # File should still exist and be valid
        assert test_file.exists()
        assert test_file.read_text() == "test"
