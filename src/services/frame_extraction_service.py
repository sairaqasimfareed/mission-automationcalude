from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

_FRAME_EXTRACTION_TIMEOUT_SECONDS = 30.0


def _run_ffmpeg(command: list[str]) -> None:
    """Real ffmpeg invocation - the default `runner` implementation."""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_FRAME_EXTRACTION_TIMEOUT_SECONDS,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "ffmpeg frame extraction failed: "
            + " ".join(command)
            + (f"\n{completed.stderr.strip()}" if completed.stderr else "")
        )


class FrameExtractionService:
    """
    Extracts one real still frame from a real video file via ffmpeg.

    Deliberately a lightweight, standalone utility rather than built
    on FFmpegCommandPlan/FFmpegExecutionService - those exist for
    long, multi-track renders (progress tracking, cancellation, a
    required positive total_duration_seconds for progress math). A
    single-frame grab is a fast, one-shot operation; reusing that
    heavier machinery here would be unjustified complexity for what
    this actually does. Mirrors VoiceGenerationService's own
    _run_ffprobe pattern (a direct, default-named-binary subprocess
    call) for the same reason - this is the same class of "cheap,
    standalone media probe/extraction," not a render.
    """

    def __init__(
        self,
        *,
        ffmpeg_path: str = "ffmpeg",
        runner: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._runner = runner or _run_ffmpeg

    def extract_last_frame(
        self,
        *,
        video_path: str,
        video_duration_seconds: float,
        output_path: str,
    ) -> str:
        """
        Extract the real last frame of a real video file to
        output_path (parent directories created as needed).

        Seeks a small margin before the clip's own real end, never
        exactly at it - seeking to the exact reported duration can
        land past the last real decodable frame on some containers,
        returning no frame at all. 0.1s is well under one frame's own
        real display duration at any realistic frame rate, so this
        still reads as "the real last frame" for continuity purposes.
        """

        if video_duration_seconds <= 0.0:
            raise ValueError("Frame extraction requires a positive video duration.")

        destination = Path(output_path)

        destination.parent.mkdir(parents=True, exist_ok=True)

        seek_seconds = max(0.0, video_duration_seconds - 0.1)

        command = [
            self._ffmpeg_path,
            "-y",
            "-ss",
            f"{seek_seconds:.3f}",
            "-i",
            str(Path(video_path).resolve()),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(destination.resolve()),
        ]

        self._runner(command)

        if not destination.exists():
            raise RuntimeError(
                f"ffmpeg reported success but no frame was written to {destination}."
            )

        return str(destination.resolve())
