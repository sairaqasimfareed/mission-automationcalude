from __future__ import annotations

from src.models.media_technical_validation import MediaTechnicalValidationResult


def test_is_valid_true_when_readable_and_no_issues() -> None:
    result = MediaTechnicalValidationResult(
        is_readable=True, duration_seconds=10.0, width=1920, height=1080
    )

    assert result.is_valid is True


def test_is_valid_false_when_not_readable() -> None:
    result = MediaTechnicalValidationResult(is_readable=False, issues=["File missing."])

    assert result.is_valid is False


def test_is_valid_false_when_readable_but_has_issues() -> None:
    result = MediaTechnicalValidationResult(
        is_readable=True, issues=["Resolution too low."]
    )

    assert result.is_valid is False


def test_defaults_are_sensible() -> None:
    result = MediaTechnicalValidationResult(is_readable=True)

    assert result.duration_seconds is None
    assert result.has_video_stream is False
    assert result.has_audio_stream is False
    assert result.issues == []
