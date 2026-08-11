from __future__ import annotations

from pathlib import Path

import pytest

from src.models.thumbnail import ThumbnailImageSourceType
from src.providers.local_thumbnail_image_provider import (
    LocalThumbnailImageProvider,
)


def test_provider_name_is_local_upload() -> None:
    provider = LocalThumbnailImageProvider(image_path="does-not-matter.png")

    assert provider.provider_name == "local_upload"


def test_image_source_type_is_local_upload() -> None:
    provider = LocalThumbnailImageProvider(image_path="does-not-matter.png")

    assert provider.image_source_type == ThumbnailImageSourceType.LOCAL_UPLOAD


def test_health_check_reflects_file_existence(tmp_path: Path) -> None:
    existing_file = tmp_path / "thumbnail.png"
    existing_file.write_bytes(b"fake-image-bytes")

    present = LocalThumbnailImageProvider(image_path=str(existing_file))
    missing = LocalThumbnailImageProvider(
        image_path=str(tmp_path / "missing.png"),
    )

    assert present.health_check() is True
    assert missing.health_check() is False


def test_generate_image_returns_the_existing_file_path(tmp_path: Path) -> None:
    existing_file = tmp_path / "thumbnail.png"
    existing_file.write_bytes(b"fake-image-bytes")

    provider = LocalThumbnailImageProvider(image_path=str(existing_file))

    result = provider.generate_image("ignored prompt", width=1280, height=720)

    assert result == str(existing_file)


def test_generate_image_raises_when_file_is_missing(tmp_path: Path) -> None:
    provider = LocalThumbnailImageProvider(
        image_path=str(tmp_path / "missing.png"),
    )

    with pytest.raises(FileNotFoundError):
        provider.generate_image("ignored prompt", width=1280, height=720)
