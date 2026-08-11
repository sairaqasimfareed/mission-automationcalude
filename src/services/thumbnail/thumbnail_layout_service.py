from __future__ import annotations

from src.models.enums import Platform
from src.models.thumbnail import ThumbnailLayout, ThumbnailTextPosition

_PLATFORM_DIMENSIONS: dict[Platform, tuple[int, int]] = {
    Platform.YOUTUBE: (1280, 720),
    Platform.FACEBOOK: (1200, 630),
    Platform.TIKTOK: (1080, 1920),
}


class ThumbnailLayoutService:
    """
    Build deterministic thumbnail layout rules for one platform.

    Platform dimensions are conservative defaults representative of
    each platform's recommended thumbnail size at the time of writing,
    not a live, authoritative source - the same caveat as
    PlatformConstraints in the SEO subsystem.
    """

    def build(
        self,
        platform: Platform,
        *,
        hook_text_position: ThumbnailTextPosition = ThumbnailTextPosition.BOTTOM,
        hook_text_font_scale: float = 0.12,
        safe_margin_ratio: float = 0.05,
    ) -> ThumbnailLayout:
        """Build one platform-appropriate thumbnail layout."""

        width, height = self.dimensions_for(platform)

        return ThumbnailLayout(
            width=width,
            height=height,
            hook_text_position=hook_text_position,
            hook_text_font_scale=hook_text_font_scale,
            safe_margin_ratio=safe_margin_ratio,
        )

    def dimensions_for(self, platform: Platform) -> tuple[int, int]:
        """Return the configured (width, height) for one platform."""

        dimensions = _PLATFORM_DIMENSIONS.get(platform)

        if dimensions is None:
            raise ValueError(
                f"No thumbnail dimensions are configured for '{platform.value}'."
            )

        return dimensions
