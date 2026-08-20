from __future__ import annotations

from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene
from src.models.stock_acquisition_request import (
    StockAcquisitionRequest,
)
from src.models.video_clip import VideoClip
from src.providers.stock_footage_provider import (
    StockFootageProvider,
)
from src.providers.visual_source_provider import (
    VisualSourceProvider,
)


class VisualAssetRouter:
    """Route visual acquisition requests to the correct provider."""

    def __init__(
        self,
        providers: list[VisualSourceProvider],
    ) -> None:
        self.providers = providers

    def acquire(
        self,
        scene: Scene,
    ) -> VideoClip:
        """
        Acquire a visual clip through the legacy scene-based path.

        This method remains available for local, manual, and legacy
        stock providers.
        """

        for provider in self.providers:
            if provider.supports(scene):
                return provider.acquire(scene)

        raise ValueError("No visual provider found for " f"{scene.source_type.value}.")

    def acquire_selected_stock(
        self,
        request: StockAcquisitionRequest,
    ) -> VideoClip:
        """
        Acquire an explicitly approved stock candidate.

        Only a configured StockFootageProvider may handle this
        production stock-acquisition request.
        """

        for provider in self.providers:
            if not isinstance(
                provider,
                StockFootageProvider,
            ):
                continue

            if not provider.supports(request.scene):
                continue

            return provider.acquire_selected(request)

        raise ValueError(
            "No stock footage provider is configured " "for approved stock acquisition."
        )

    def available_sources(
        self,
    ) -> list[SceneSourceType]:
        """
        Return active source types supported by registered providers.

        Providers without a valid supported_source_type attribute
        are ignored.
        """

        sources: set[SceneSourceType] = set()

        for provider in self.providers:
            source_type = getattr(
                provider,
                "supported_source_type",
                None,
            )

            if isinstance(
                source_type,
                SceneSourceType,
            ):
                sources.add(source_type)

        return sorted(
            sources,
            key=lambda source: source.value,
        )

    def supports_source(
        self,
        source_type: SceneSourceType,
    ) -> bool:
        """Return whether any registered provider supports a source."""

        return source_type in self.available_sources()

    @property
    def provider_count(self) -> int:
        """Return the number of registered visual providers."""

        return len(self.providers)
