from __future__ import annotations

from dataclasses import dataclass

from src.models.enums import Platform
from src.models.seo import SEOPlatformMetadata
from src.services.seo.seo_context_builder import SEOContext


@dataclass(frozen=True, slots=True)
class PlatformConstraints:
    """
    Platform-specific SEO constraints.

    Values are conservative defaults representative of each platform's
    published limits at the time of writing, not a live, authoritative
    source. SEOValidationService treats these as the single source of
    truth for platform-dependent checks, so a business-logic change
    only has to happen here.
    """

    max_title_length: int
    max_description_length: int
    max_tags: int
    max_hashtags: int


_DEFAULT_CONSTRAINTS: dict[Platform, PlatformConstraints] = {
    Platform.YOUTUBE: PlatformConstraints(
        max_title_length=100,
        max_description_length=5000,
        max_tags=30,
        max_hashtags=15,
    ),
    Platform.FACEBOOK: PlatformConstraints(
        max_title_length=255,
        max_description_length=63206,
        max_tags=30,
        max_hashtags=30,
    ),
    Platform.TIKTOK: PlatformConstraints(
        max_title_length=150,
        max_description_length=2200,
        max_tags=30,
        max_hashtags=30,
    ),
}


class SEOPlatformMetadataService:
    """
    Build provider-independent platform metadata and expose the
    platform-specific constraints SEOValidationService checks against.

    No publishing API is called or referenced here - this only
    represents metadata and limits.
    """

    def build(self, context: SEOContext) -> SEOPlatformMetadata:
        """Build platform metadata for one video's SEO context."""

        return SEOPlatformMetadata(
            platform=context.platform,
            language=context.language,
            language_code=context.language_code,
        )

    def constraints_for(self, platform: Platform) -> PlatformConstraints:
        """Return the configured constraints for one platform."""

        constraints = _DEFAULT_CONSTRAINTS.get(platform)

        if constraints is None:
            raise ValueError(
                f"No platform constraints are configured for '{platform.value}'."
            )

        return constraints
