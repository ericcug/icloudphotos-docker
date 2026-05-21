"""Built-in HEIC to JPEG converter post-processing plugin."""

import logging
from pathlib import Path
from typing import Any, Dict

from icloud_docker.pipeline.base import BaseProcessor, ProcessorError

logger = logging.getLogger(__name__)


class HeicToJpgProcessor(BaseProcessor):
    """Converts HEIC images to JPEG format.

    Uses Pillow (with pillow-heif plugin) for conversion.
    Non-HEIC files are passed through unchanged.

    Config options:
        quality: JPEG quality (1-100, default 85)
        remove_original: Delete HEIC after conversion (default False)
    """

    version = "1.0.0"

    def init(self, config: Dict[str, Any]) -> None:
        """Initialize with quality and removal settings.

        Args:
            config: Must include 'quality' (int) and optionally
                    'remove_original' (bool).

        Raises:
            ValueError: If quality is not between 1 and 100.
        """
        self.quality = int(config.get("quality", 85))
        self.remove_original = bool(config.get("remove_original", False))

        if not 1 <= self.quality <= 100:
            raise ValueError(f"quality must be 1-100, got {self.quality}")

        logger.info("HEIC→JPG converter initialized (quality=%d, remove_original=%s)",
                     self.quality, self.remove_original)

    def process(self, file_path: Path, metadata: Dict[str, Any]) -> Path:
        """Convert HEIC file to JPEG if applicable.

        Args:
            file_path: Path to the file.
            metadata: File metadata dict.

        Returns:
            Path to JPEG file (or original if not HEIC).

        Raises:
            ProcessorError: If conversion fails.
        """
        suffix = file_path.suffix.lower()
        if suffix not in (".heic", ".heif"):
            logger.debug("Skipping non-HEIC file: %s", file_path.name)
            return file_path

        jpg_path = file_path.with_suffix(".jpg")

        # Skip if already converted
        if jpg_path.exists():
            logger.debug("JPEG already exists: %s", jpg_path.name)
            if self.remove_original and file_path.exists():
                file_path.unlink()
            return jpg_path

        try:
            from PIL import Image
            import pillow_heif

            pillow_heif.register_heif_opener()
            img = Image.open(file_path)
            img.save(jpg_path, "JPEG", quality=self.quality)
            logger.info("Converted: %s → %s", file_path.name, jpg_path.name)

            if self.remove_original:
                file_path.unlink()
                logger.debug("Removed original: %s", file_path.name)

            return jpg_path

        except ImportError:
            logger.warning(
                "pillow-heif not installed. HEIC conversion unavailable. "
                "Install with: pip install pillow-heif"
            )
            return file_path
        except Exception as e:
            raise ProcessorError(f"HEIC conversion failed: {e}") from e

    def cleanup(self) -> None:
        """No cleanup needed for HEIC converter."""
        pass
