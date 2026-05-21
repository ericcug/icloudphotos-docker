"""Post-processing pipeline plugin base class.

Defines the BaseProcessor abstract class that all post-processing
plugins must implement, following the contract in contracts/plugin-interface.md.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict


class BaseProcessor(ABC):
    """Abstract base class for post-processing pipeline plugins.

    All post-processing plugins MUST inherit from this class and
    implement all three lifecycle methods. Plugins process files
    internally within the pipeline; no intermediate data is exposed
    to external systems.

    Attributes:
        version: Plugin version string for compatibility checks.
    """

    version: str = "1.0.0"
    """Plugin version identifier for compatibility checking."""

    @abstractmethod
    def init(self, config: Dict[str, Any]) -> None:
        """Initialize the processor.

        Called once when the pipeline starts. Use this to validate
        configuration, load models, establish connections, etc.

        Args:
            config: User-provided configuration parameters for this processor.

        Raises:
            ValueError: If configuration parameters are invalid.
        """
        ...

    @abstractmethod
    def process(self, file_path: Path, metadata: Dict[str, Any]) -> Path:
        """Process a single media file.

        Called for each file after download completes. The processor
        may modify the file in place or create a new version.
        The returned path is passed to the next processor in the pipeline.

        Args:
            file_path: Absolute path to the file to process.
            metadata: File metadata dict with keys:
                - record_name: iCloud unique identifier
                - filename: Original filename
                - media_type: photo | video | live_photo
                - size_bytes: File size in bytes
                - created_at: Creation time (ISO 8601)
                - modified_at: Modification time (ISO 8601)

        Returns:
            Path to the processed file (may be same as input).

        Raises:
            ProcessorError: If processing fails (handled by retry logic).
        """
        ...

    @abstractmethod
    def cleanup(self) -> None:
        """Release resources held by the processor.

        Called once when the pipeline shuts down. Use this to close
        connections, delete temporary files, etc.
        This method SHOULD NOT raise exceptions (they will be caught
        and logged).
        """
        ...


class ProcessorError(Exception):
    """Exception raised when a post-processing step fails."""
    pass
