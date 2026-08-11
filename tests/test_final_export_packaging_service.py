from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from src.models.enums import Platform
from src.models.seo import SEOPackage, SEOPlatformMetadata, TitleCandidate
from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.services.final_export.final_export_packaging_service import (
    FinalExportPackagingService,
)


def _seo_package() -> SEOPackage:
    return SEOPackage(
        video_job_id=uuid4(),
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A complete, publish-ready description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )


def _thumbnail_artifact(*, file_path: str) -> ThumbnailArtifact:
    return ThumbnailArtifact(
        video_job_id=uuid4(),
        concept=ThumbnailConcept(
            concept_summary="A diver facing a giant squid.",
            hook_text="GIANT SQUID",
            visual_prompt="A deep sea diver facing a giant squid.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path=file_path,
        file_size_bytes=0,
    )


def test_package_copies_real_video_and_thumbnail_files(tmp_path: Path) -> None:
    video_source = tmp_path / "render_output.mp4"
    video_source.write_bytes(b"fake-video-bytes")

    thumbnail_source = tmp_path / "thumb_source.png"
    thumbnail_source.write_bytes(b"fake-image-bytes")

    service = FinalExportPackagingService(export_root=tmp_path / "exports")

    package = service.package(
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        final_video_source_path=str(video_source),
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=600,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(file_path=str(thumbnail_source)),
    )

    assert Path(package.final_video_path).exists()
    assert Path(package.thumbnail_artifact.file_path).exists()
    assert package.final_video_path != str(video_source)
    assert video_source.exists()  # copied, not moved
    assert package.warnings == []
    assert package.manifest_path is not None
    assert Path(package.manifest_path).exists()


def test_package_creates_expected_directory_structure(tmp_path: Path) -> None:
    video_source = tmp_path / "render_output.mp4"
    video_source.write_bytes(b"fake-video-bytes")

    thumbnail_source = tmp_path / "thumb_source.png"
    thumbnail_source.write_bytes(b"fake-image-bytes")

    export_root = tmp_path / "exports"

    service = FinalExportPackagingService(export_root=export_root)

    package = service.package(
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        final_video_source_path=str(video_source),
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=600,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(file_path=str(thumbnail_source)),
    )

    project_directory = Path(package.export_directory)

    assert (project_directory / "video" / "final_video.mp4").exists()
    assert (project_directory / "thumbnail" / "thumbnail.png").exists()
    assert (project_directory / "metadata" / "seo.json").exists()
    assert (project_directory / "metadata" / "project.json").exists()
    assert (project_directory / "metadata" / "export_manifest.json").exists()


def test_package_handles_dry_run_uri_paths_without_copying(
    tmp_path: Path,
) -> None:
    service = FinalExportPackagingService(export_root=tmp_path / "exports")

    package = service.package(
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        final_video_source_path="dry-run://render/output.mp4",
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=600,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(
            file_path="dry-run://thumbnail/1280x720.png",
        ),
    )

    assert package.final_video_path == "dry-run://render/output.mp4"
    assert package.thumbnail_artifact.file_path == "dry-run://thumbnail/1280x720.png"
    assert len(package.warnings) == 2


def test_package_warns_but_does_not_raise_for_missing_source_file(
    tmp_path: Path,
) -> None:
    service = FinalExportPackagingService(export_root=tmp_path / "exports")

    package = service.package(
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        final_video_source_path=str(tmp_path / "missing_video.mp4"),
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=600,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(
            file_path="dry-run://thumbnail/1280x720.png",
        ),
    )

    assert any("does not exist" in warning for warning in package.warnings)


def test_seo_json_matches_serialized_seo_package(tmp_path: Path) -> None:
    video_source = tmp_path / "render_output.mp4"
    video_source.write_bytes(b"fake-video-bytes")

    seo_package = _seo_package()

    service = FinalExportPackagingService(export_root=tmp_path / "exports")

    package = service.package(
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        final_video_source_path=str(video_source),
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=600,
        seo_package=seo_package,
        thumbnail_artifact=_thumbnail_artifact(
            file_path="dry-run://thumbnail/1280x720.png",
        ),
    )

    seo_json_path = Path(package.export_directory) / "metadata" / "seo.json"

    with seo_json_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["selected_title"] == "Great Video"


def test_manifest_json_is_valid_and_matches_the_package(tmp_path: Path) -> None:
    video_source = tmp_path / "render_output.mp4"
    video_source.write_bytes(b"fake-video-bytes")

    service = FinalExportPackagingService(export_root=tmp_path / "exports")

    package = service.package(
        video_job_id=uuid4(),
        project_id="deep-sea-doc",
        final_video_source_path=str(video_source),
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=600,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(
            file_path="dry-run://thumbnail/1280x720.png",
        ),
    )

    assert package.manifest_path is not None

    with Path(package.manifest_path).open(encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["project_id"] == "deep-sea-doc"
    assert payload["resolution"] == "1920x1080"
    assert payload["duration_seconds"] == 600


def test_package_sanitizes_project_id_for_the_directory_name(
    tmp_path: Path,
) -> None:
    video_source = tmp_path / "render_output.mp4"
    video_source.write_bytes(b"fake-video-bytes")

    service = FinalExportPackagingService(export_root=tmp_path / "exports")

    package = service.package(
        video_job_id=uuid4(),
        project_id="Deep Sea / Doc!",
        final_video_source_path=str(video_source),
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=600,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(
            file_path="dry-run://thumbnail/1280x720.png",
        ),
    )

    assert package.project_id == "Deep_Sea___Doc"
    assert "Deep_Sea___Doc" in package.export_directory
