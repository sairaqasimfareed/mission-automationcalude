from __future__ import annotations

from pathlib import Path

from src.models.thumbnail import ThumbnailImageSourceType
from src.providers.thumbnail_image_provider import ThumbnailImageProvider


class LocalThumbnailImageProvider(ThumbnailImageProvider):
    """
    Uses a pre-existing local image file as a thumbnail's base image.

    Accepts any locally available image: a manual upload, or a frame
    a caller already extracted from a scene elsewhere. This is how
    Mission Automation supports local/scene-frame thumbnail input
    without requiring a dedicated frame-extraction pipeline: whatever
    produced the file, this provider only validates and returns it.
    """

    def __init__(self, *, image_path: str) -> None:
        self._image_path = image_path

    @property
    def provider_name(self) -> str:
        return "local_upload"

    @property
    def image_source_type(self) -> ThumbnailImageSourceType:
        return ThumbnailImageSourceType.LOCAL_UPLOAD

    def health_check(self) -> bool:
        return Path(self._image_path).exists()

    def generate_image(
        self,
        prompt: str,
        *,
        width: int,
        height: int,
    ) -> str:
        del prompt, width, height

        file_path = Path(self._image_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Local thumbnail image not found: {file_path}")

        return str(file_path)
