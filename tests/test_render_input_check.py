"""Naming the broken file before a render fails with "Invalid data found when processing input"
(live, 2026-10-27), and keeping FFmpeg's own error lines in the message and the log."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_timeline import VideoTimeline
from src.services.ffmpeg_execution_service import FFmpegExecutionService
from src.services.render_input_check import unreadable_render_inputs


@dataclass
class _Probe:
    is_readable: bool


class _Validator:
    """Readable unless the file's content says it is broken."""

    def validate(self, file_path: Path) -> _Probe:
        return _Probe(is_readable=file_path.read_bytes() != b"broken")


def _clip(scene_number: int, path: Path) -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=6,
        local_file=str(path),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


def _timeline(*clips: VideoClip) -> VideoTimeline:
    return VideoTimeline(clips=list(clips), total_duration_seconds=6.0 * len(clips))


def _file(directory: Path, name: str, content: bytes = b"ok") -> Path:
    path = directory / name
    path.write_bytes(content)

    return path


def test_every_readable_input_gives_no_problem(tmp_path: Path) -> None:
    timeline = _timeline(_clip(1, _file(tmp_path, "a.mp4")))

    assert unreadable_render_inputs(timeline, None, _Validator()) == []  # type: ignore[arg-type]


def test_a_damaged_clip_is_named_with_its_scene(tmp_path: Path) -> None:
    timeline = _timeline(
        _clip(1, _file(tmp_path, "a.mp4")),
        _clip(8, _file(tmp_path, "scene_8.mp4", b"broken")),
    )

    problems = unreadable_render_inputs(timeline, None, _Validator())  # type: ignore[arg-type]

    assert len(problems) == 1
    assert "Scene 8" in problems[0]
    assert "scene_8.mp4" in problems[0]
    assert "generate or upload it again" in problems[0]


def test_a_missing_clip_is_named(tmp_path: Path) -> None:
    timeline = _timeline(_clip(2, tmp_path / "gone.mp4"))

    problems = unreadable_render_inputs(timeline, None, _Validator())  # type: ignore[arg-type]

    assert len(problems) == 1
    assert "gone.mp4" in problems[0] and "missing" in problems[0]


def test_a_copy_the_app_made_is_told_to_be_deleted(tmp_path: Path) -> None:
    timeline = _timeline(_clip(3, _file(tmp_path, "walk-7s_held.mp4", b"broken")))

    problems = unreadable_render_inputs(timeline, None, _Validator())  # type: ignore[arg-type]

    assert "delete the file and render again" in problems[0]


def test_a_damaged_voice_file_is_named_too(tmp_path: Path) -> None:
    audio = AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file=str(_file(tmp_path, "v.mp3", b"broken")),
                duration_seconds=5.0,
                status=AudioTrackStatus.READY,
                metadata={"scene_number": 4},
            )
        ]
    )

    problems = unreadable_render_inputs(
        _timeline(_clip(4, _file(tmp_path, "c.mp4"))), audio, _Validator()  # type: ignore[arg-type]
    )

    assert len(problems) == 1
    assert "Scene 4" in problems[0] and "v.mp3" in problems[0]


def test_ffmpegs_error_message_keeps_the_line_that_names_the_file() -> None:
    stderr = "\n".join(
        [
            "ffmpeg version 8.0",
            "[mov,mp4,m4a @ 0x1] moov atom not found",
            "data/muse_downloads/x/shopkeeper-9s.mp4: Invalid data found when processing input",
            "Error opening input files: Invalid data found when processing input",
        ]
    )

    message = FFmpegExecutionService._execution_error_message(  # noqa: SLF001
        exit_code=3199971767, stderr=stderr
    )

    assert "shopkeeper-9s.mp4" in message
    assert "Error opening input files" in message
