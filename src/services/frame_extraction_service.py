from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

# Generous: a re-encode of a 10 s clip took 55 s on a busy machine (live, 2026-10-20) and the 30 s limit
# silently kept the clip too short.
_FRAME_EXTRACTION_TIMEOUT_SECONDS = 300.0


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

    def extract_frame_at(
        self,
        *,
        video_path: str,
        at_seconds: float,
        output_path: str,
        width: int = 320,
    ) -> str:
        """
        Extract one downscaled still frame at `at_seconds` into the clip -
        used for review thumbnails (a small JPEG, not a continuity
        reference), so it is scaled to `width` with the height following the
        aspect ratio.
        """

        if at_seconds < 0.0:
            raise ValueError("Frame extraction requires a non-negative time.")

        if width <= 0:
            raise ValueError("Thumbnail width must be positive.")

        destination = Path(output_path)

        destination.parent.mkdir(parents=True, exist_ok=True)

        command = [
            self._ffmpeg_path,
            "-y",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            str(Path(video_path).resolve()),
            "-vframes",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-q:v",
            "4",
            str(destination.resolve()),
        ]

        self._runner(command)

        if not destination.exists():
            raise RuntimeError(
                f"ffmpeg reported success but no frame was written to {destination}."
            )

        return str(destination.resolve())

    def hold_to_duration(
        self,
        *,
        video_path: str,
        target_duration_seconds: float,
        output_path: str,
    ) -> str:
        """
        Make a real video file at least target_duration_seconds long by holding its LAST
        frame (a freeze), for a clip whose scene has more narration than the clip has picture.
        The clip's own picture is untouched; only the end is extended.
        """

        if target_duration_seconds <= 0.0:
            raise ValueError("Hold requires a positive target duration.")

        destination = Path(output_path)

        destination.parent.mkdir(parents=True, exist_ok=True)

        command = [
            self._ffmpeg_path,
            "-y",
            "-i",
            str(Path(video_path).resolve()),
            "-vf",
            "tpad=stop_mode=clone:stop_duration=" f"{target_duration_seconds:.3f}",
            "-t",
            f"{target_duration_seconds:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(destination.resolve()),
        ]

        self._runner(command)

        if not destination.exists():
            raise RuntimeError(
                f"ffmpeg reported success but no extended file was written to {destination}."
            )

        return str(destination.resolve())

    def trim_to_duration(
        self,
        *,
        video_path: str,
        target_duration_seconds: float,
        output_path: str,
    ) -> str:
        """
        Trim a real video file down to at most target_duration_seconds.

        Built for Muse's fixed ~10s clip length: Muse's own agent can
        already execute a "trim to N seconds" instruction embedded in
        its own prompt (confirmed live, 2026-09-29 - a real "trim 10
        seconds video to only 7 seconds video" instruction produced a
        genuinely ~7s clip), but that is an LLM-driven agent following
        an instruction, not a deterministic operation - this is the
        verified safety-net correction for whenever it isn't exact,
        never the primary trimming mechanism.

        `-t` placed AFTER `-i` (not a fast `-ss`-before-`-i` seek) so
        ffmpeg decodes and re-encodes precisely up to the target
        duration rather than only being able to cut on an input
        keyframe boundary - correctness matters more than speed here
        for a short safety-net correction on an already-short clip.
        """

        if target_duration_seconds <= 0.0:
            raise ValueError("Trim requires a positive target duration.")

        destination = Path(output_path)

        destination.parent.mkdir(parents=True, exist_ok=True)

        command = [
            self._ffmpeg_path,
            "-y",
            "-i",
            str(Path(video_path).resolve()),
            "-t",
            f"{target_duration_seconds:.3f}",
            # A fast encode: the default preset took 55 s for a 10 s clip on a busy machine and the
            # cut was given up on (live, 2026-10-19: clips of scenes 5, 7, 8 and 9 stayed 10 s long).
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(destination.resolve()),
        ]

        self._runner(command)

        if not destination.exists():
            raise RuntimeError(
                f"ffmpeg reported success but no trimmed file was written to {destination}."
            )

        return str(destination.resolve())
