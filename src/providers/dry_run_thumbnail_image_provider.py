from __future__ import annotations

from src.models.thumbnail import ThumbnailImageSourceType
from src.providers.thumbnail_image_provider import ThumbnailImageProvider


class DryRunThumbnailImageProvider(ThumbnailImageProvider):
    """
    Deterministic thumbnail image provider used during dry-run
    execution.

    Mirrors the role DryRunVoiceProvider plays for voice generation:
    it lets a full production runtime be composed and exercised
    without a real AI image-generation provider or credentials
    configured.
    """

    @property
    def provider_name(self) -> str:
        return "dry_run"

    @property
    def image_source_type(self) -> ThumbnailImageSourceType:
        return ThumbnailImageSourceType.AI_GENERATED

    def health_check(self) -> bool:
        return True

    def generate_image(
        self,
        prompt: str,
        *,
        width: int,
        height: int,
    ) -> str:
        del prompt

        return f"dry-run://thumbnail/{width}x{height}.png"
