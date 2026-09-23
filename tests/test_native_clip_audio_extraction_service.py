from __future__ import annotations

from pathlib import Path

import pytest

from src.models.audio_track import AudioTrackType
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.render_result import SceneRenderTiming
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
)
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.native_clip_audio_extraction_service import (
    NativeClipAudioExtractionService,
)


def _preset(*, directive_path: str, preset_id: str) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        used_fallback=False,
    )


def _blueprint(scene_number: int) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_preset(
            directive_path="genre_preset_id", preset_id="genre.default"
        ),
        camera=ResolvedCameraInstruction(
            preset=_preset(directive_path="camera.preset_id", preset_id="camera.none")
        ),
        transition_in=ResolvedTransitionInstruction(
            preset=_preset(
                directive_path="transition_in.preset_id", preset_id="transition.cut"
            ),
            duration_seconds=0.0,
        ),
        transition_out=ResolvedTransitionInstruction(
            preset=_preset(
                directive_path="transition_out.preset_id", preset_id="transition.cut"
            ),
            duration_seconds=0.0,
        ),
        music=ResolvedMusicInstruction(
            preset=_preset(directive_path="music.preset_id", preset_id="music.none"),
            enabled=False,
        ),
        subtitles=ResolvedSubtitleInstruction(
            preset=_preset(
                directive_path="subtitles.preset_id", preset_id="subtitle.default"
            ),
            enabled=False,
            burn_into_video=False,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
    )


def _item(
    scene_number: int,
    *,
    clip_sequence_index: int = 0,
    local_file: str,
    start: float,
    duration: float = 4.0,
    enabled: bool = True,
) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=int(duration),
        prompt="test",
        local_file=local_file,
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        start_time_seconds=start,
        end_time_seconds=start + duration,
        enabled=enabled,
        editing_blueprint=_blueprint(scene_number),
    )


# --- has_audio_stream / extract_audio unit tests (mocked runners) ---


def test_has_audio_stream_true_when_ffprobe_reports_audio() -> None:
    service = NativeClipAudioExtractionService(ffprobe_runner=lambda command: "audio\n")

    assert service.has_audio_stream("clip.mp4") is True


def test_has_audio_stream_false_when_ffprobe_reports_nothing() -> None:
    service = NativeClipAudioExtractionService(ffprobe_runner=lambda command: "")

    assert service.has_audio_stream("clip.mp4") is False


def test_extract_audio_writes_and_returns_the_real_output_path(
    tmp_path: Path,
) -> None:
    output_path = str(tmp_path / "nested" / "audio.m4a")

    received_commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        received_commands.append(command)
        Path(output_path).write_bytes(b"fake aac bytes")

    service = NativeClipAudioExtractionService(ffmpeg_runner=runner)

    result_path = service.extract_audio(video_path="clip.mp4", output_path=output_path)

    assert Path(result_path).exists()
    assert Path(result_path).read_bytes() == b"fake aac bytes"
    assert Path(output_path).parent.is_dir()

    command = received_commands[0]
    assert "-vn" in command
    assert "-acodec" in command


def test_extract_audio_raises_when_runner_succeeds_but_writes_nothing(
    tmp_path: Path,
) -> None:
    output_path = str(tmp_path / "audio.m4a")

    service = NativeClipAudioExtractionService(ffmpeg_runner=lambda command: None)

    with pytest.raises(RuntimeError):
        service.extract_audio(video_path="clip.mp4", output_path=output_path)


# --- extract_native_clip_audio_tracks orchestration tests ---


def test_extracts_one_track_per_scene_positioned_at_its_real_timing(
    tmp_path: Path,
) -> None:
    written_files: list[str] = []

    def ffmpeg_runner(command: list[str]) -> None:
        output_path = command[-1]
        written_files.append(output_path)
        Path(output_path).write_bytes(b"fake audio")

    service = NativeClipAudioExtractionService(
        ffprobe_runner=lambda command: "audio\n",
        ffmpeg_runner=ffmpeg_runner,
    )

    video_timeline = VideoTimeline(
        items=[
            _item(1, local_file="scene1.mp4", start=0.0, duration=4.0),
            _item(2, local_file="scene2.mp4", start=4.0, duration=4.0),
        ]
    )

    scene_timings = [
        SceneRenderTiming(
            scene_number=1, clip_sequence_index=0, start_seconds=0.0, end_seconds=4.0
        ),
        SceneRenderTiming(
            scene_number=2, clip_sequence_index=0, start_seconds=3.4, end_seconds=7.4
        ),
    ]

    tracks = service.extract_native_clip_audio_tracks(
        video_timeline=video_timeline,
        scene_timings=scene_timings,
        output_directory=str(tmp_path),
    )

    assert len(tracks) == 2
    assert len(written_files) == 2

    by_scene = {track.metadata["scene_number"]: track for track in tracks}

    assert by_scene[1].track_type == AudioTrackType.NATIVE_CLIP
    assert by_scene[1].start_time_seconds == 0.0
    assert by_scene[1].duration_seconds == 4.0

    # Scene 2's real, crossfade-corrected position (3.4s), not its
    # naive timeline position (4.0s) - this is the whole point of
    # reusing scene_timings instead of item.start_time_seconds.
    assert by_scene[2].start_time_seconds == 3.4
    assert by_scene[2].duration_seconds == 4.0


def test_skips_a_scene_with_no_real_audio_stream(tmp_path: Path) -> None:
    service = NativeClipAudioExtractionService(
        ffprobe_runner=lambda command: "",  # no audio stream at all
        ffmpeg_runner=lambda command: pytest.fail(
            "extract_audio must never run for a silent clip"
        ),
    )

    video_timeline = VideoTimeline(
        items=[_item(1, local_file="silent.mp4", start=0.0, duration=4.0)]
    )

    scene_timings = [
        SceneRenderTiming(
            scene_number=1, clip_sequence_index=0, start_seconds=0.0, end_seconds=4.0
        )
    ]

    tracks = service.extract_native_clip_audio_tracks(
        video_timeline=video_timeline,
        scene_timings=scene_timings,
        output_directory=str(tmp_path),
    )

    assert tracks == []


def test_skips_a_disabled_item(tmp_path: Path) -> None:
    service = NativeClipAudioExtractionService(
        ffprobe_runner=lambda command: pytest.fail(
            "a disabled item must never be probed"
        ),
    )

    video_timeline = VideoTimeline(
        items=[
            _item(1, local_file="scene1.mp4", start=0.0, duration=4.0, enabled=False)
        ]
    )

    scene_timings = [
        SceneRenderTiming(
            scene_number=1, clip_sequence_index=0, start_seconds=0.0, end_seconds=4.0
        )
    ]

    tracks = service.extract_native_clip_audio_tracks(
        video_timeline=video_timeline,
        scene_timings=scene_timings,
        output_directory=str(tmp_path),
    )

    assert tracks == []


def test_skips_an_item_with_no_matching_scene_timing(tmp_path: Path) -> None:
    service = NativeClipAudioExtractionService(
        ffprobe_runner=lambda command: pytest.fail(
            "an item with no real timing entry must never be probed"
        ),
    )

    video_timeline = VideoTimeline(
        items=[_item(1, local_file="scene1.mp4", start=0.0, duration=4.0)]
    )

    tracks = service.extract_native_clip_audio_tracks(
        video_timeline=video_timeline,
        scene_timings=[],
        output_directory=str(tmp_path),
    )

    assert tracks == []
