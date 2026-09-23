from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.render_result import SceneRenderTiming
from src.models.video_timeline import VideoTimeline

_PROBE_COMMAND_TIMEOUT_SECONDS = 30.0
_EXTRACTION_TIMEOUT_SECONDS = 60.0


def _run_ffprobe(command: list[str]) -> str:
    """Real ffprobe invocation - the default `ffprobe_runner` implementation."""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_PROBE_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "ffprobe command failed: "
            + " ".join(command)
            + (f"\n{completed.stderr.strip()}" if completed.stderr else "")
        )

    return completed.stdout


def _run_ffmpeg(command: list[str]) -> None:
    """Real ffmpeg invocation - the default `ffmpeg_runner` implementation."""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_EXTRACTION_TIMEOUT_SECONDS,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "ffmpeg native-clip-audio extraction failed: "
            + " ".join(command)
            + (f"\n{completed.stderr.strip()}" if completed.stderr else "")
        )


class NativeClipAudioExtractionService:
    """
    REQ-10(a) "Use native clip audio": extract a generated video
    clip's own embedded audio (e.g. Google Flow's real, confirmed
    lip-synced dialogue - see the character-oriented-video-mode
    memory) into a standalone AudioTrack, positioned at that clip's
    real, crossfade-corrected final-timeline start (see
    SceneRenderTiming/REQ-00 Stage 1) so it mixes correctly alongside
    voiceover/music/SFX through the exact same AudioTimeline/
    AudioMuxRenderService machinery, rather than a parallel audio path.

    Mirrors FrameExtractionService's own shape (a lightweight,
    standalone ffmpeg/ffprobe subprocess utility, not built on
    FFmpegCommandPlan/FFmpegExecutionService - those exist for long,
    multi-track renders with progress/cancellation, unjustified
    complexity for a fast, one-shot per-clip extraction).

    A scene whose own clip has no real audio stream at all (a manual
    upload or stock-footage clip, most commonly) is silently skipped,
    not an error - this is expected and routine, not a defect.
    """

    def __init__(
        self,
        *,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
        ffprobe_runner: Callable[[list[str]], str] | None = None,
        ffmpeg_runner: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._ffprobe_path = ffprobe_path
        self._ffprobe_runner = ffprobe_runner or _run_ffprobe
        self._ffmpeg_runner = ffmpeg_runner or _run_ffmpeg

    def has_audio_stream(self, video_path: str) -> bool:
        """Return whether a real video file has at least one real audio stream."""

        command = [
            self._ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(Path(video_path).resolve()),
        ]

        output = self._ffprobe_runner(command)

        return "audio" in output

    def extract_audio(self, *, video_path: str, output_path: str) -> str:
        """
        Extract a real video file's own audio track to output_path
        (parent directories created as needed), re-encoded to AAC so
        the extracted file is directly usable as an AudioTrack source
        regardless of the source container's own original audio codec.
        """

        destination = Path(output_path)

        destination.parent.mkdir(parents=True, exist_ok=True)

        command = [
            self._ffmpeg_path,
            "-y",
            "-i",
            str(Path(video_path).resolve()),
            "-vn",
            "-acodec",
            "aac",
            str(destination.resolve()),
        ]

        self._ffmpeg_runner(command)

        if not destination.exists():
            raise RuntimeError(
                "ffmpeg reported success but no audio file was written "
                f"to {destination}."
            )

        return str(destination.resolve())

    def extract_native_clip_audio_tracks(
        self,
        *,
        video_timeline: VideoTimeline,
        scene_timings: list[SceneRenderTiming],
        output_directory: str,
    ) -> list[AudioTrack]:
        """
        Build one NATIVE_CLIP AudioTrack per enabled timeline item
        whose own clip has real audio, positioned at that item's real,
        crossfade-corrected final-timeline start (from scene_timings -
        see ProductionRenderService._compute_real_scene_timings, the
        same computation REQ-00 Stage 1 already runs).

        Items with no matching scene_timings entry, or whose own clip
        has no real audio stream, are silently skipped - both are
        routine, not errors (a caller that never ran Stage 1's timing
        computation yet, or a scene sourced from silent footage).
        """

        timing_by_key = {
            (timing.scene_number, timing.clip_sequence_index): timing
            for timing in scene_timings
        }

        destination_root = Path(output_directory)

        tracks: list[AudioTrack] = []

        for item in video_timeline.items:
            if not item.enabled:
                continue

            key = (item.scene_number, item.clip_sequence_index)

            timing = timing_by_key.get(key)

            if timing is None:
                continue

            clip_source = item.clip.local_file or item.clip.source_url

            if not clip_source:
                continue

            if not self.has_audio_stream(clip_source):
                continue

            output_path = (
                destination_root
                / f"scene_{item.scene_number}_{item.clip_sequence_index}_native_audio.m4a"
            )

            extracted_path = self.extract_audio(
                video_path=clip_source,
                output_path=str(output_path),
            )

            tracks.append(
                AudioTrack(
                    track_type=AudioTrackType.NATIVE_CLIP,
                    source_file=extracted_path,
                    start_time_seconds=timing.start_seconds,
                    duration_seconds=(timing.end_seconds - timing.start_seconds),
                    status=AudioTrackStatus.READY,
                    metadata={
                        "scene_number": item.scene_number,
                        "clip_sequence_index": item.clip_sequence_index,
                    },
                )
            )

        return tracks
