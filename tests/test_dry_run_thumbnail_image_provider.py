from __future__ import annotations

from src.models.thumbnail import ThumbnailImageSourceType
from src.providers.dry_run_thumbnail_image_provider import (
    DryRunThumbnailImageProvider,
)


def test_provider_name_is_dry_run() -> None:
    provider = DryRunThumbnailImageProvider()

    assert provider.provider_name == "dry_run"


def test_image_source_type_is_ai_generated() -> None:
    provider = DryRunThumbnailImageProvider()

    assert provider.image_source_type == ThumbnailImageSourceType.AI_GENERATED


def test_health_check_always_succeeds() -> None:
    provider = DryRunThumbnailImageProvider()

    assert provider.health_check() is True


def test_generate_image_returns_deterministic_path() -> None:
    provider = DryRunThumbnailImageProvider()

    path = provider.generate_image("a squid", width=1280, height=720)

    assert path == "dry-run://thumbnail/1280x720.png"


def test_generate_image_output_reflects_requested_dimensions() -> None:
    provider = DryRunThumbnailImageProvider()

    first = provider.generate_image("a", width=1280, height=720)
    second = provider.generate_image("b", width=640, height=360)

    assert first != second
    assert "1280x720" in first
    assert "640x360" in second
