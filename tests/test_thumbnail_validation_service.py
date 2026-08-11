from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailArtifactStatus,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.models.thumbnail_validation import ThumbnailValidationCode
from src.services.thumbnail.thumbnail_validation_service import (
    ThumbnailValidationService,
)


def _concept(hook_text: str = "SHORT HOOK") -> ThumbnailConcept:
    return ThumbnailConcept(
        concept_summary="A diver facing a giant squid.",
        hook_text=hook_text,
        visual_prompt="A deep sea diver facing a giant squid.",
    )


def _layout(**overrides: object) -> ThumbnailLayout:
    defaults: dict[str, object] = {
        "width": 1280,
        "height": 720,
        "hook_text_font_scale": 0.12,
        "safe_margin_ratio": 0.05,
    }
    defaults.update(overrides)

    return ThumbnailLayout(**defaults)  # type: ignore[arg-type]


def _artifact(*, file_path: str, **overrides: object) -> ThumbnailArtifact:
    defaults: dict[str, object] = {
        "video_job_id": uuid4(),
        "concept": _concept(),
        "layout": _layout(),
        "image_source_type": ThumbnailImageSourceType.AI_GENERATED,
        "provider_name": "dry_run",
        "file_path": file_path,
        "file_size_bytes": 1024,
    }
    defaults.update(overrides)

    return ThumbnailArtifact(**defaults)  # type: ignore[arg-type]


def test_validate_accepts_a_fully_valid_artifact(tmp_path: Path) -> None:
    existing_file = tmp_path / "thumbnail.png"
    existing_file.write_bytes(b"fake-image-bytes")

    artifact = _artifact(file_path=str(existing_file))

    result = ThumbnailValidationService().validate(artifact)

    assert result.is_valid is True
    assert result.errors == []


def test_validate_skips_file_check_for_uri_scheme_paths() -> None:
    artifact = _artifact(file_path="dry-run://thumbnail/1280x720.png")

    result = ThumbnailValidationService().validate(artifact)

    codes = [issue.code for issue in result.errors]

    assert ThumbnailValidationCode.FILE_MISSING not in codes


def test_validate_flags_missing_file(tmp_path: Path) -> None:
    artifact = _artifact(file_path=str(tmp_path / "missing.png"))

    result = ThumbnailValidationService().validate(artifact)

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert ThumbnailValidationCode.FILE_MISSING in codes


def test_validate_flags_dimension_mismatch() -> None:
    artifact = _artifact(
        file_path="dry-run://thumbnail/1280x720.png",
        layout=_layout(width=1280, height=720),
    )

    result = ThumbnailValidationService().validate(
        artifact,
        expected_dimensions=(1200, 630),
    )

    codes = [issue.code for issue in result.errors]

    assert result.is_valid is False
    assert ThumbnailValidationCode.INVALID_DIMENSIONS in codes


def test_validate_skips_dimension_check_when_not_expected() -> None:
    artifact = _artifact(
        file_path="dry-run://thumbnail/1280x720.png",
        layout=_layout(width=999, height=999),
    )

    result = ThumbnailValidationService().validate(artifact)

    codes = [issue.code for issue in result.errors]

    assert ThumbnailValidationCode.INVALID_DIMENSIONS not in codes


def test_validate_warns_on_long_hook_text() -> None:
    artifact = _artifact(
        file_path="dry-run://thumbnail/1280x720.png",
        concept=_concept(hook_text="A" * 70),
    )

    result = ThumbnailValidationService().validate(artifact)

    codes = [issue.code for issue in result.warnings]

    assert result.is_valid is True
    assert ThumbnailValidationCode.HOOK_TEXT_TOO_LONG in codes


def test_validate_warns_when_hook_text_likely_exceeds_safe_margin() -> None:
    artifact = _artifact(
        file_path="dry-run://thumbnail/100x100.png",
        concept=_concept(hook_text="A" * 30),
        layout=_layout(
            width=100,
            height=100,
            hook_text_font_scale=0.5,
            safe_margin_ratio=0.05,
        ),
    )

    result = ThumbnailValidationService().validate(artifact)

    codes = [issue.code for issue in result.warnings]

    assert ThumbnailValidationCode.HOOK_TEXT_OUTSIDE_SAFE_MARGIN in codes


def test_validate_accepts_approved_artifact_status() -> None:
    artifact = _artifact(
        file_path="dry-run://thumbnail/1280x720.png",
        status=ThumbnailArtifactStatus.APPROVED,
    )

    result = ThumbnailValidationService().validate(artifact)

    assert result.is_valid is True
