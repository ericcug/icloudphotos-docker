"""Pipeline runner: orchestrates post-processing steps in sequence."""

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List

from pipeline.base import BaseProcessor, ProcessorError

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Executes post-processing pipeline steps sequentially.

    Loads processor plugins, executes them in configured order,
    with retry logic and error isolation (one step failure does
    not block others per FR-016).

    Attributes:
        steps: List of (processor_instance, config, retry_count) tuples.
    """

    # Built-in processors by name
    BUILTIN_PROCESSORS = {}

    def __init__(self, pipeline_config):
        """Initialize pipeline runner from configuration.

        Args:
            pipeline_config: PipelineConfig instance with step definitions.
        """
        self.steps: List[tuple] = []
        self._load_steps(pipeline_config)

    def _load_steps(self, pipeline_config) -> None:
        """Load and instantiate processor plugins from config.

        Args:
            pipeline_config: PipelineConfig instance.
        """
        for step_cfg in pipeline_config.steps:
            if not step_cfg.enabled:
                logger.info("Skipping disabled step: %s", step_cfg.name)
                continue

            processor = self._load_processor(step_cfg.name, step_cfg.config)
            if processor:
                self.steps.append((processor, step_cfg.retry))
                logger.info("Loaded pipeline step: %s (retry=%d)", step_cfg.name, step_cfg.retry)

    def _load_processor(self, name: str, config: Dict[str, Any]) -> BaseProcessor | None:
        """Load a processor by name (built-in or user module).

        Args:
            name: Processor identifier (built-in name or module path).
            config: Processor configuration dict.

        Returns:
            Instantiated BaseProcessor, or None if loading fails.
        """
        # Try built-in first
        if name in self.BUILTIN_PROCESSORS:
            module_path, class_name = self.BUILTIN_PROCESSORS[name].rsplit(".", 1)
        else:
            # User-provided module path (e.g., my_plugins.watermark)
            module_path = name
            # Default class name convention: PascalCase of module name
            class_name = "".join(part.capitalize() for part in name.split(".")[-1].split("_"))
            class_name = class_name or "Processor"

        try:
            module = importlib.import_module(module_path)
            processor_cls = getattr(module, class_name)
            processor = processor_cls()
            processor.init(config)
            return processor
        except Exception as e:
            logger.error("Failed to load processor '%s': %s", name, e)
            return None

    def process_file(self, file_path: Path, metadata: Dict[str, Any]) -> Path:
        """Run all pipeline steps on a single file.

        Steps execute sequentially. If a step fails, it retries up to
        its configured limit, then the pipeline continues with the
        original file (pre-failed-step state) for subsequent steps.

        Args:
            file_path: Path to the file to process.
            metadata: File metadata dict.

        Returns:
            Final file path after all steps complete.
        """
        current_path = file_path

        for processor, retry_count in self.steps:
            for attempt in range(1, retry_count + 1):
                try:
                    new_path = processor.process(current_path, metadata)
                    current_path = new_path
                    break
                except ProcessorError as e:
                    logger.warning(
                        "Step failed (attempt %d/%d): %s — %s",
                        attempt, retry_count, processor.__class__.__name__, e,
                    )
                    if attempt >= retry_count:
                        logger.error(
                            "Step '%s' failed after %d retries. Continuing with current file.",
                            processor.__class__.__name__, retry_count,
                        )
                        # Continue with current_path unchanged (FR-016: don't block)
                except Exception as e:
                    logger.error("Unexpected error in step '%s': %s",
                                 processor.__class__.__name__, e)
                    break

        return current_path

    def cleanup(self) -> None:
        """Call cleanup on all loaded processors."""
        for processor, _ in self.steps:
            try:
                processor.cleanup()
            except Exception as e:
                logger.warning("Cleanup error in '%s': %s",
                               processor.__class__.__name__, e)

    @property
    def is_empty(self) -> bool:
        """Check if pipeline has any active steps."""
        return len(self.steps) == 0
