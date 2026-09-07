from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.models.media_technical_validation import MediaTechnicalValidationResult

_DEFAULT_MIN_DURATION_SECONDS = 0.5
_DEFAULT_MAX_DURATION_SECONDS = 600.0
_DEFAULT_MIN_WIDTH = 200
_DEFAULT_MIN_HEIGHT = 200
_COMMAND_TIMEOUT_SECONDS = 30.0


def _run_ffprobe(command: list[str]) -> str:
    """Real ffprobe invocation - the default `runner` implementation."""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "ffprobe command failed: "
            + " ".join(command)
            + (f"\n{completed.stderr.strip()}" if completed.stderr else "")
        )

    return completed.stdout


class MediaTechnicalValidationService:
    """
    Post-Script-Approval Production Plan, Phase 8: "Run technical
    checks first: readability, duration, dimensions/aspect ratio and
    basic media validity" - applicable to any acquired clip in this
    codebase's actual acquisition paths (manual upload, stock
    footage), and, since the Google Flow External UI Automation
    initiative's own GF-9, a Google-Flow-generated download too -
    reused there directly rather than duplicated (see
    GoogleFlowGenerationOrchestratorService.validate_and_accept_download()).

    `runner` is injectable (mirroring this codebase's LLM-service
    injection pattern) so tests can stub ffprobe's output without a
    real binary or a real video file - the default is a genuine
    subprocess call.
    """

    def __init__(
        self,
        *,
        ffprobe_path: str = "ffprobe",
        min_duration_seconds: float = _DEFAULT_MIN_DURATION_SECONDS,
        max_duration_seconds: float = _DEFAULT_MAX_DURATION_SECONDS,
        min_width: int = _DEFAULT_MIN_WIDTH,
        min_height: int = _DEFAULT_MIN_HEIGHT,
        runner: Callable[[list[str]], str] | None = None,
    ) -> None:
        if min_duration_seconds < 0:
            raise ValueError("Minimum duration cannot be negative.")

        if max_duration_seconds <= min_duration_seconds:
            raise ValueError("Maximum duration must exceed the minimum duration.")

        if min_width <= 0 or min_height <= 0:
            raise ValueError("Minimum width/height must be positive.")

        self.ffprobe_path = ffprobe_path
        self.min_duration_seconds = min_duration_seconds
        self.max_duration_seconds = max_duration_seconds
        self.min_width = min_width
        self.min_height = min_height
        self._runner = runner or _run_ffprobe

    def validate(self, file_path: Path) -> MediaTechnicalValidationResult:
        if not file_path.exists() or not file_path.is_file():
            return MediaTechnicalValidationResult(
                is_readable=False,
                issues=[f"File does not exist or is not a file: {file_path}."],
            )

        resolved_binary = shutil.which(self.ffprobe_path) or self.ffprobe_path

        try:
            raw_output = self._runner(
                [
                    resolved_binary,
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    str(file_path),
                ]
            )
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            return MediaTechnicalValidationResult(
                is_readable=False,
                issues=[f"Media file could not be read by ffprobe: {error}"],
            )

        try:
            probe_data = json.loads(raw_output)
        except (json.JSONDecodeError, TypeError):
            return MediaTechnicalValidationResult(
                is_readable=False,
                issues=["ffprobe returned unparseable output."],
            )

        return self._evaluate(probe_data)

    def _evaluate(self, probe_data: dict[str, Any]) -> MediaTechnicalValidationResult:
        issues: list[str] = []

        streams = probe_data.get("streams") or []
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        has_video_stream = bool(video_streams)
        has_audio_stream = bool(audio_streams)

        if not has_video_stream:
            issues.append("No video stream found in the media file.")

        format_data = probe_data.get("format") or {}
        duration_raw = format_data.get("duration")
        duration_seconds: float | None = None

        try:
            duration_seconds = float(duration_raw) if duration_raw is not None else None
        except (TypeError, ValueError):
            duration_seconds = None

        if duration_seconds is None:
            issues.append("Could not determine media duration.")

        if duration_seconds is not None:
            if duration_seconds < self.min_duration_seconds:
                issues.append(
                    f"Duration {duration_seconds:.2f}s is below the minimum "
                    f"required {self.min_duration_seconds:.2f}s."
                )
            elif duration_seconds > self.max_duration_seconds:
                issues.append(
                    f"Duration {duration_seconds:.2f}s exceeds the maximum "
                    f"allowed {self.max_duration_seconds:.2f}s."
                )

        width: int | None = None
        height: int | None = None

        if video_streams:
            primary = video_streams[0]
            width = primary.get("width")
            height = primary.get("height")

            if width is None or height is None:
                issues.append("Video stream is missing width/height metadata.")
            else:
                if width < self.min_width or height < self.min_height:
                    issues.append(
                        f"Resolution {width}x{height} is below the minimum "
                        f"required {self.min_width}x{self.min_height}."
                    )

        return MediaTechnicalValidationResult(
            is_readable=True,
            duration_seconds=duration_seconds,
            width=width,
            height=height,
            has_video_stream=has_video_stream,
            has_audio_stream=has_audio_stream,
            issues=issues,
        )
