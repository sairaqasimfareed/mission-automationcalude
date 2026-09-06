from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src.models.enums import Platform
from src.models.final_export import FinalExportPackage, FinalExportStatus
from src.models.final_export_validation import FinalExportValidationCode
from src.models.seo import SEOPackage, SEOPlatformMetadata, TitleCandidate
from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailArtifactStatus,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.services.final_export.final_export_validation_service import (
    FinalExportValidationService,
)
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)

_GOOD_PROBE_OUTPUT = """
{
    "format": {"duration": "120.0"},
    "streams": [
        {"codec_type": "video", "width": 1920, "height": 1080},
        {"codec_type": "audio"}
    ]
}
"""

_NO_AUDIO_PROBE_OUTPUT = """
{
    "format": {"duration": "120.0"},
    "streams": [
        {"codec_type": "video", "width": 1920, "height": 1080}
    ]
}
"""

_WRONG_RESOLUTION_PROBE_OUTPUT = """
{
    "format": {"duration": "120.0"},
    "streams": [
        {"codec_type": "video", "width": 1280, "height": 720},
        {"codec_type": "audio"}
    ]
}
"""


def _stubbed_technical_validation_service(
    probe_output: str,
) -> MediaTechnicalValidationService:
    return MediaTechnicalValidationService(
        runner=lambda _command: probe_output,
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
        "final_video_path": "dry-run://render/output.mp4",
        "resolution": "1920x1080",
        "frame_rate": 30,
        "duration_seconds": 600,
        "seo_package": _seo_package(),
        "thumbnail_artifact": _thumbnail_artifact(),
        "export_directory": "exports/deep-sea-doc",
    }
    defaults.update(overrides)

    return FinalExportPackage(**defaults)  # type: ignore[arg-type]


def test_validate_accepts_a_fully_valid_package(tmp_path: Path) -> None:
    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    package = _package(
        status=FinalExportStatus.APPROVED,
        seo_package=_seo_package(status="approved"),
        thumbnail_artifact=_thumbnail_artifact(
            status=ThumbnailArtifactStatus.APPROVED,
        ),
        manifest_path=str(manifest_file),
    )

    result = FinalExportValidationService().validate(package)

    assert result.is_valid is True
    assert result.errors == []
    assert result.warnings == []


def test_validate_flags_missing_video_file(tmp_path: Path) -> None:
    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    package = _package(
        final_video_path=str(tmp_path / "missing_video.mp4"),
        manifest_path=str(manifest_file),
    )

    result = FinalExportValidationService().validate(package)

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert FinalExportValidationCode.VIDEO_FILE_MISSING in codes


def test_validate_skips_video_check_for_uri_scheme_paths() -> None:
    package = _package(final_video_path="dry-run://render/output.mp4")

    result = FinalExportValidationService().validate(package)

    codes = [issue.code for issue in result.errors]

    assert FinalExportValidationCode.VIDEO_FILE_MISSING not in codes


def test_validate_flags_zero_duration() -> None:
    package = _package(duration_seconds=0)

    result = FinalExportValidationService().validate(package)

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert FinalExportValidationCode.INVALID_DURATION in codes


def test_validate_flags_missing_manifest_path() -> None:
    package = _package(manifest_path=None)

    result = FinalExportValidationService().validate(package)

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert FinalExportValidationCode.MANIFEST_MISSING in codes


def test_validate_flags_manifest_path_that_does_not_exist(
    tmp_path: Path,
) -> None:
    package = _package(manifest_path=str(tmp_path / "missing_manifest.json"))

    result = FinalExportValidationService().validate(package)

    codes = [issue.code for issue in result.errors]

    assert FinalExportValidationCode.MANIFEST_MISSING in codes


def test_validate_warns_when_thumbnail_not_approved(tmp_path: Path) -> None:
    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    package = _package(manifest_path=str(manifest_file))

    result = FinalExportValidationService().validate(package)

    codes = [issue.code for issue in result.warnings]

    assert result.is_valid is True
    assert FinalExportValidationCode.THUMBNAIL_NOT_READY in codes


def test_validate_warns_when_seo_package_not_approved(tmp_path: Path) -> None:
    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    package = _package(manifest_path=str(manifest_file))

    result = FinalExportValidationService().validate(package)

    codes = [issue.code for issue in result.warnings]

    assert FinalExportValidationCode.SEO_PACKAGE_NOT_READY in codes


def test_validate_accepts_a_real_video_file_that_passes_technical_checks(
    tmp_path: Path,
) -> None:
    video_file = tmp_path / "final_video.mp4"
    video_file.write_bytes(b"fake video bytes")

    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    package = _package(
        final_video_path=str(video_file),
        resolution="1920x1080",
        manifest_path=str(manifest_file),
    )

    service = FinalExportValidationService(
        technical_validation_service=(
            _stubbed_technical_validation_service(_GOOD_PROBE_OUTPUT)
        ),
    )

    result = service.validate(package)

    codes = [issue.code for issue in result.errors]

    assert FinalExportValidationCode.MEDIA_NOT_READABLE not in codes
    assert FinalExportValidationCode.MEDIA_NO_AUDIO_STREAM not in codes
    assert FinalExportValidationCode.MEDIA_RESOLUTION_MISMATCH not in codes


def test_validate_flags_final_video_with_no_audio_stream(
    tmp_path: Path,
) -> None:
    video_file = tmp_path / "final_video.mp4"
    video_file.write_bytes(b"fake video bytes")

    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    package = _package(
        final_video_path=str(video_file),
        resolution="1920x1080",
        manifest_path=str(manifest_file),
    )

    service = FinalExportValidationService(
        technical_validation_service=(
            _stubbed_technical_validation_service(_NO_AUDIO_PROBE_OUTPUT)
        ),
    )

    result = service.validate(package)

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert FinalExportValidationCode.MEDIA_NO_AUDIO_STREAM in codes


def test_validate_flags_final_video_resolution_mismatch(
    tmp_path: Path,
) -> None:
    video_file = tmp_path / "final_video.mp4"
    video_file.write_bytes(b"fake video bytes")

    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    package = _package(
        final_video_path=str(video_file),
        resolution="1920x1080",
        manifest_path=str(manifest_file),
    )

    service = FinalExportValidationService(
        technical_validation_service=(
            _stubbed_technical_validation_service(_WRONG_RESOLUTION_PROBE_OUTPUT)
        ),
    )

    result = service.validate(package)

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert FinalExportValidationCode.MEDIA_RESOLUTION_MISMATCH in codes


def test_validate_flags_unreadable_final_video(
    tmp_path: Path,
) -> None:
    video_file = tmp_path / "final_video.mp4"
    video_file.write_bytes(b"fake video bytes")

    manifest_file = tmp_path / "export_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    package = _package(
        final_video_path=str(video_file),
        manifest_path=str(manifest_file),
    )

    def _raising_runner(_command: list[str]) -> str:
        raise RuntimeError("ffprobe is not installed")

    service = FinalExportValidationService(
        technical_validation_service=MediaTechnicalValidationService(
            runner=_raising_runner,
        ),
    )

    result = service.validate(package)

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert FinalExportValidationCode.MEDIA_NOT_READABLE in codes


def test_validate_skips_technical_checks_for_uri_scheme_paths() -> None:
    package = _package(final_video_path="dry-run://render/output.mp4")

    service = FinalExportValidationService(
        technical_validation_service=(
            _stubbed_technical_validation_service(_NO_AUDIO_PROBE_OUTPUT)
        ),
    )

    result = service.validate(package)

    codes = [issue.code for issue in result.errors]

    assert FinalExportValidationCode.MEDIA_NOT_READABLE not in codes
    assert FinalExportValidationCode.MEDIA_NO_AUDIO_STREAM not in codes
    assert FinalExportValidationCode.MEDIA_RESOLUTION_MISMATCH not in codes
