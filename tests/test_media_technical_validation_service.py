from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)

_GOOD_PROBE = json.dumps(
    {
        "format": {"duration": "8.0"},
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio"},
        ],
    }
)

_TOO_SHORT_PROBE = json.dumps(
    {
        "format": {"duration": "0.1"},
        "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
    }
)

_TOO_SMALL_PROBE = json.dumps(
    {
        "format": {"duration": "8.0"},
        "streams": [{"codec_type": "video", "width": 100, "height": 100}],
    }
)

_NO_VIDEO_PROBE = json.dumps(
    {"format": {"duration": "8.0"}, "streams": [{"codec_type": "audio"}]}
)


def _real_file(tmp_path: Path) -> Path:
    file_path = tmp_path / "clip.mp4"
    file_path.write_bytes(b"not a real video, just needs to exist")
    return file_path


def test_validate_accepts_a_good_clip(tmp_path: Path) -> None:
    service = MediaTechnicalValidationService(runner=lambda command: _GOOD_PROBE)

    result = service.validate(_real_file(tmp_path))

    assert result.is_valid is True
    assert result.duration_seconds == 8.0
    assert result.width == 1920
    assert result.height == 1080
    assert result.has_audio_stream is True


def test_validate_rejects_a_missing_file(tmp_path: Path) -> None:
    service = MediaTechnicalValidationService(runner=lambda command: _GOOD_PROBE)

    result = service.validate(tmp_path / "does_not_exist.mp4")

    assert result.is_valid is False
    assert result.is_readable is False


def test_validate_rejects_too_short_duration(tmp_path: Path) -> None:
    service = MediaTechnicalValidationService(runner=lambda command: _TOO_SHORT_PROBE)

    result = service.validate(_real_file(tmp_path))

    assert result.is_valid is False
    assert any("below the minimum" in issue for issue in result.issues)


def test_validate_rejects_too_small_resolution(tmp_path: Path) -> None:
    service = MediaTechnicalValidationService(runner=lambda command: _TOO_SMALL_PROBE)

    result = service.validate(_real_file(tmp_path))

    assert result.is_valid is False
    assert any("below the minimum required" in issue for issue in result.issues)


def test_validate_rejects_missing_video_stream(tmp_path: Path) -> None:
    service = MediaTechnicalValidationService(runner=lambda command: _NO_VIDEO_PROBE)

    result = service.validate(_real_file(tmp_path))

    assert result.is_valid is False
    assert result.has_video_stream is False


def test_validate_handles_runner_failure_gracefully(tmp_path: Path) -> None:
    def _failing_runner(command: list[str]) -> str:
        raise RuntimeError("ffprobe not found")

    service = MediaTechnicalValidationService(runner=_failing_runner)

    result = service.validate(_real_file(tmp_path))

    assert result.is_valid is False
    assert result.is_readable is False


def test_validate_handles_unparseable_output(tmp_path: Path) -> None:
    service = MediaTechnicalValidationService(runner=lambda command: "not json")

    result = service.validate(_real_file(tmp_path))

    assert result.is_valid is False
    assert result.is_readable is False


def test_constructor_rejects_negative_min_duration() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        MediaTechnicalValidationService(min_duration_seconds=-1.0)


def test_constructor_rejects_max_below_min_duration() -> None:
    with pytest.raises(ValueError, match="must exceed"):
        MediaTechnicalValidationService(
            min_duration_seconds=10.0, max_duration_seconds=5.0
        )


def test_constructor_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        MediaTechnicalValidationService(min_width=0)
