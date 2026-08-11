from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.models.enums import Platform
from src.models.final_export import FinalExportPackage, FinalExportStatus
from src.models.seo import SEOPackage, SEOPlatformMetadata, TitleCandidate
from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailArtifactStatus,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)


def _seo_package(**overrides: object) -> SEOPackage:
    defaults: dict[str, object] = {
        "video_job_id": uuid4(),
        "title_candidates": [TitleCandidate(text="Great Video")],
        "selected_title": "Great Video",
        "description": "A complete, publish-ready description.",
        "platform_metadata": SEOPlatformMetadata(platform=Platform.YOUTUBE),
        "prompt_version": "seo_prompt_v1.0.0",
    }
    defaults.update(overrides)

    return SEOPackage(**defaults)  # type: ignore[arg-type]


def _thumbnail_artifact(**overrides: object) -> ThumbnailArtifact:
    defaults: dict[str, object] = {
        "video_job_id": uuid4(),
        "concept": ThumbnailConcept(
            concept_summary="A diver facing a giant squid.",
            hook_text="GIANT SQUID",
            visual_prompt="A deep sea diver facing a giant squid.",
        ),
        "layout": ThumbnailLayout(width=1280, height=720),
        "image_source_type": ThumbnailImageSourceType.AI_GENERATED,
        "provider_name": "dry_run",
        "file_path": "dry-run://thumbnail/1280x720.png",
        "file_size_bytes": 0,
    }
    defaults.update(overrides)

    return ThumbnailArtifact(**defaults)  # type: ignore[arg-type]


def _package(**overrides: object) -> FinalExportPackage:
    defaults: dict[str, object] = {
        "video_job_id": uuid4(),
        "project_id": "deep-sea-doc",
        "final_video_path": "exports/deep-sea-doc/video/final_video.mp4",
        "resolution": "1920x1080",
        "frame_rate": 30,
        "duration_seconds": 600,
        "seo_package": _seo_package(),
        "thumbnail_artifact": _thumbnail_artifact(),
        "export_directory": "exports/deep-sea-doc",
    }
    defaults.update(overrides)

    return FinalExportPackage(**defaults)  # type: ignore[arg-type]


def test_package_rejects_empty_required_text() -> None:
    with pytest.raises(ValidationError):
        _package(project_id="   ")


def test_package_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        _package(duration_seconds=-1)


def test_package_embeds_full_seo_and_thumbnail_objects() -> None:
    package = _package()

    assert package.seo_package.selected_title == "Great Video"
    assert package.thumbnail_artifact.concept.hook_text == "GIANT SQUID"


def test_is_ready_for_publish_requires_approval_of_everything() -> None:
    incomplete = _package(status=FinalExportStatus.APPROVED)

    approved_seo = _seo_package(status="approved")
    approved_thumbnail = _thumbnail_artifact(
        status=ThumbnailArtifactStatus.APPROVED,
    )

    complete = _package(
        status=FinalExportStatus.APPROVED,
        seo_package=approved_seo,
        thumbnail_artifact=approved_thumbnail,
    )

    assert incomplete.is_ready_for_publish is False
    assert complete.is_ready_for_publish is True
