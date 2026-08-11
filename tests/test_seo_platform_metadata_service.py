from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import Platform
from src.services.seo.seo_context_builder import SEOContext
from src.services.seo.seo_platform_metadata_service import (
    PlatformConstraints,
    SEOPlatformMetadataService,
)


def _context(platform: Platform = Platform.YOUTUBE) -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic="Deep sea creatures",
        niche="ocean-life",
        genre_id="genre.documentary",
        target_audience="Ocean enthusiasts",
        target_country="United States",
        language="English",
        language_code="en",
        platform=platform,
        script_title="Deep Sea Creatures Explained",
        script_content="Full script content.",
        research_summary="An overview.",
        key_facts=[],
        scene_count=1,
        estimated_duration_seconds=600,
    )


def test_build_returns_metadata_matching_context() -> None:
    service = SEOPlatformMetadataService()

    metadata = service.build(_context())

    assert metadata.platform == Platform.YOUTUBE
    assert metadata.language == "English"
    assert metadata.language_code == "en"


@pytest.mark.parametrize(
    "platform",
    [Platform.YOUTUBE, Platform.FACEBOOK, Platform.TIKTOK],
)
def test_constraints_for_every_platform_supported_by_v1(
    platform: Platform,
) -> None:
    service = SEOPlatformMetadataService()

    constraints = service.constraints_for(platform)

    assert isinstance(constraints, PlatformConstraints)
    assert constraints.max_title_length > 0
    assert constraints.max_description_length > 0
    assert constraints.max_tags > 0
    assert constraints.max_hashtags > 0


def test_constraints_differ_between_platforms() -> None:
    service = SEOPlatformMetadataService()

    youtube = service.constraints_for(Platform.YOUTUBE)
    tiktok = service.constraints_for(Platform.TIKTOK)

    assert youtube.max_title_length != tiktok.max_title_length
