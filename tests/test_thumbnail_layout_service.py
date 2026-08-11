from __future__ import annotations

import pytest

from src.models.enums import Platform
from src.models.thumbnail import ThumbnailLayout, ThumbnailTextPosition
from src.services.thumbnail.thumbnail_layout_service import (
    ThumbnailLayoutService,
)


def test_build_returns_youtube_dimensions() -> None:
    layout = ThumbnailLayoutService().build(Platform.YOUTUBE)

    assert isinstance(layout, ThumbnailLayout)
    assert (layout.width, layout.height) == (1280, 720)


def test_build_respects_custom_text_position() -> None:
    layout = ThumbnailLayoutService().build(
        Platform.YOUTUBE,
        hook_text_position=ThumbnailTextPosition.TOP,
    )

    assert layout.hook_text_position == ThumbnailTextPosition.TOP


@pytest.mark.parametrize(
    "platform",
    [Platform.YOUTUBE, Platform.FACEBOOK, Platform.TIKTOK],
)
def test_dimensions_for_every_platform_supported_by_v1(
    platform: Platform,
) -> None:
    width, height = ThumbnailLayoutService().dimensions_for(platform)

    assert width > 0
    assert height > 0


def test_dimensions_differ_between_platforms() -> None:
    service = ThumbnailLayoutService()

    youtube = service.dimensions_for(Platform.YOUTUBE)
    tiktok = service.dimensions_for(Platform.TIKTOK)

    assert youtube != tiktok
