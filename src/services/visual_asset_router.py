from __future__ import annotations

from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene
from src.models.video_clip import VideoClip
from src.providers.visual_source_provider import VisualSourceProvider


class VisualAssetRouter:
    """Routes each scene to the correct visual provider."""

    def __init__(
        self,
        providers: list[VisualSourceProvider],
    ) -> None:
        self.providers = providers

    def acquire(self, scene: Scene) -> VideoClip:
        for provider in self.providers:
            if provider.supports(scene):
                return provider.acquire(scene)

        raise ValueError(f"No visual provider found for {scene.source_type.value}.")

    def available_sources(self) -> list[SceneSourceType]:
        """
        Return active visual source types supported by registered providers.

        Each provider may expose a `supported_source_type` attribute.
        Providers without that attribute are ignored here.
        """

        sources: set[SceneSourceType] = set()

        for provider in self.providers:
            source_type = getattr(
                provider,
                "supported_source_type",
                None,
            )

            if isinstance(source_type, SceneSourceType):
                sources.add(source_type)

        return sorted(
            sources,
            key=lambda source: source.value,
        )
