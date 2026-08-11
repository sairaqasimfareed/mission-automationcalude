from __future__ import annotations

from abc import abstractmethod

from src.models.thumbnail import ThumbnailImageSourceType
from src.providers.base_provider import BaseProvider


class ThumbnailImageProvider(BaseProvider):
    """
    Base interface for every thumbnail base-image source.

    Examples:
    - an AI image-generation API
    - a locally supplied image file (manual upload, or a frame a
      caller extracted from a scene elsewhere)
    """

    @property
    @abstractmethod
    def image_source_type(self) -> ThumbnailImageSourceType:
        """Return which ThumbnailImageSourceType this provider produces."""

    @abstractmethod
    def generate_image(
        self,
        prompt: str,
        *,
        width: int,
        height: int,
    ) -> str:
        """
        Produce one base image for a thumbnail.

        Returns:
            Path to the produced image file.
        """
