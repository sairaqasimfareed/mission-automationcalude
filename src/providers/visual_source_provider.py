from __future__ import annotations

from abc import abstractmethod

from src.models.scene import Scene
from src.models.video_clip import VideoClip
from src.providers.base_provider import BaseProvider


class VisualSourceProvider(BaseProvider):
    """Base interface for every active visual source provider."""

    @abstractmethod
    def supports(self, scene: Scene) -> bool:
        """Return whether this provider can handle the scene."""

    @abstractmethod
    def acquire(self, scene: Scene) -> VideoClip:
        """
        Acquire or prepare the visual asset for a scene.

        Implementations may:

        - validate a manually uploaded clip
        - search stock footage
        - locate a local-library asset
        - create an image-to-video clip

        Every provider must return the standard VideoClip model.
        """
