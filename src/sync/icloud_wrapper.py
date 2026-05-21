"""PyiCloudService wrapper for the iCloud Docker application.

Provides a simplified interface over icloudpd's PyiCloudService
for photo listing and download operations.
"""

import logging
from typing import Generator

from pyicloud_ipd.base import PyiCloudService
from pyicloud_ipd.services.photos import PhotoAsset, PhotosService

logger = logging.getLogger(__name__)


class ICloudWrapper:
    """Wraps PyiCloudService for simplified photo access.

    Provides lazy initialization of the photos service and a clean
    interface for iterating over photo assets.

    Attributes:
        service: The authenticated PyiCloudService instance.
    """

    def __init__(self, service: PyiCloudService):
        """Initialize with an authenticated service.

        Args:
            service: Authenticated PyiCloudService instance.
        """
        self.service = service

    @property
    def photos(self) -> Generator[PhotoAsset, None, None]:
        """Iterate over all photos in the iCloud library.

        Delegates to PyiCloudService.photos.all_photos for lazy pagination.
        This follows the icloudpd pattern.

        Yields:
            PhotoAsset instances for each photo/video in the library.
        """
        try:
            photos_service = self.service.photos
            # photos_service.all returns a PhotoAlbum (iterable) that
            # handles paginated fetching of all photos in the library.
            yield from photos_service.all
        except Exception as e:
            logger.error("Failed to fetch photos: %s", e)
            raise

    def download_asset(self, asset: PhotoAsset, download_path: str) -> str:
        """Download a single photo asset to the specified path.

        Uses icloudpd's download_media function for retry and resume support.

        Args:
            asset: PhotoAsset to download.
            download_path: Destination file path.

        Returns:
            The path where the file was saved.
        """
        from icloudpd.download import download_media
        from pyicloud_ipd.version_size import AssetVersionSize, LivePhotoVersionSize

        versions = asset.versions
        original = versions.get(AssetVersionSize.ORIGINAL)
        original_size = AssetVersionSize.ORIGINAL
        if not original:
            original = versions.get(LivePhotoVersionSize.ORIGINAL)
            original_size = LivePhotoVersionSize.ORIGINAL

        if not original:
            raise ValueError(f"No original version available for {asset.filename}")

        success = download_media(
            logger,
            dry_run=False,
            icloud=self.service,
            photo=asset,
            download_path=download_path,
            version=original,
            size=original_size,
            filename_builder=lambda a: a.filename,
        )
        if success:
            return download_path
        raise RuntimeError(f"Download failed for {asset.filename}")

    def get_asset_metadata(self, asset: PhotoAsset) -> dict:
        """Extract standardized metadata from a PhotoAsset.

        Args:
            asset: PhotoAsset instance.

        Returns:
            Dictionary with standardized metadata fields.
        """
        return {
            "record_name": getattr(asset, "id", ""),
            "filename": getattr(asset, "filename", ""),
            "media_type": self._detect_media_type(asset),
            "size_bytes": getattr(asset, "size", 0),
            "created_at": str(getattr(asset, "created", "")),
            "modified_at": str(getattr(asset, "modified", "")),
        }

    @staticmethod
    def _detect_media_type(asset: PhotoAsset) -> str:
        """Detect media type from asset filename extension.

        Args:
            asset: PhotoAsset instance.

        Returns:
            One of: photo, video, live_photo.
        """
        filename = str(getattr(asset, "filename", "")).lower()
        if filename.endswith((".mov", ".mp4", ".m4v", ".avi")):
            return "video"
        # Live photos have both .heic + .mov pair
        if getattr(asset, "is_live_photo", False):
            return "live_photo"
        return "photo"

    def delete_asset(self, asset: PhotoAsset) -> bool:
        """Delete an asset from iCloud (moves to Recently Deleted).

        Args:
            asset: PhotoAsset to delete.

        Returns:
            True if deletion was successful, False otherwise.
        """
        import urllib.parse
        import json
        
        try:
            library_object = self.service.photos
            logger.debug("Deleting %s in iCloud...", asset.filename)
            url = (
                f"{library_object.service_endpoint}/records/modify?"
                f"{urllib.parse.urlencode(library_object.params)}"
            )
            post_data = json.dumps(
                {
                    "atomic": True,
                    "desiredKeys": ["isDeleted"],
                    "operations": [
                        {
                            "operationType": "update",
                            "record": {
                                "fields": {"isDeleted": {"value": 1}},
                                "recordChangeTag": asset._asset_record["recordChangeTag"],
                                "recordName": asset._asset_record["recordName"],
                                "recordType": "CPLAsset",
                            },
                        }
                    ],
                    "zoneID": library_object.zone_id,
                }
            )
            response = library_object.session.post(
                url, data=post_data, headers={"Content-type": "application/json"}
            )
            
            if response.ok:
                logger.info("Successfully deleted asset %s from iCloud", asset.filename)
                return True
            else:
                logger.error("Failed to delete asset %s from iCloud: HTTP %s", asset.filename, response.status_code)
                return False
        except Exception as e:
            logger.error("Failed to delete asset %s from iCloud: %s", asset.filename, e)
            return False
