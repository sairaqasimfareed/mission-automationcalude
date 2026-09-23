"""
REQ-12 (top10 countdown rank cards), 2026-09-23: real, non-mocked
FFmpeg proof that ProductionRenderService.render_top10_countdown()
actually splices a real, independently-rendered rank-card clip into
the middle of a real multi-scene render as a real hard cut - not just
that the internal grouping/validation logic "looks right" in a unit
test. Matches this session's own established discipline for anything
touching the real render path (see _slice_for_scenes' own documented
real-world bug history, only ever caught by an actual render).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.editing_directives import DirectiveIntensity
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.production_render_service import ProductionRenderService
from src.services.top10_rank_card_render_service import (
    TopTenRankCardRenderService,
)

_WIDTH = 640
_HEIGHT = 360
_FRAME_RATE = 30
_SCENE_DURATION_SECONDS = 2


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real top10 countdown render smoke requires ffmpeg.")

    return ffmpeg, ffprobe


def _create_source_video(*, ffmpeg: str, output_file: Path, pattern: str) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            (
                f"{pattern}=size={_WIDTH}x{_HEIGHT}:"
                f"rate={_FRAME_RATE}:duration={_SCENE_DURATION_SECONDS}"
            ),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            output_file.as_posix(),
        ]
    )


def _create_source_audio(*, ffmpeg: str, output_file: Path) -> None:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={_SCENE_DURATION_SECONDS}",
            "-c:a",
            "pcm_s16le",
            output_file.as_posix(),
        ]
    )


def _create_background_image(*, ffmpeg: str, output_file: Path) -> None:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={_WIDTH}x{_HEIGHT}:duration=1",
            "-frames:v",
            "1",
            output_file.as_posix(),
        ]
    )


def _preset_reference(
    *, directive_path: str, preset_id: str
) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        used_fallback=False,
        implementation={},
        metadata={},
    )


def _editing_blueprint(*, scene_number: int) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_preset_reference(
            directive_path="genre_preset_id", preset_id="genre.default"
        ),
        camera=ResolvedCameraInstruction(
            preset=_preset_reference(
                directive_path="camera.preset_id", preset_id="camera.none"
            ),
            intensity=DirectiveIntensity.MEDIUM,
        ),
        transition_in=ResolvedTransitionInstruction(
            preset=_preset_reference(
                directive_path="transition_in.preset_id", preset_id="transition.cut"
            ),
            duration_seconds=0.0,
        ),
        transition_out=ResolvedTransitionInstruction(
            preset=_preset_reference(
                directive_path="transition_out.preset_id", preset_id="transition.cut"
            ),
            duration_seconds=0.0,
        ),
        visual_effects=[],
        animations=[],
        music=ResolvedMusicInstruction(
            preset=_preset_reference(
                directive_path="music.preset_id", preset_id="music.none"
            ),
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=_preset_reference(
                directive_path="subtitles.preset_id", preset_id="subtitle.none"
            ),
            enabled=False,
            burn_into_video=False,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
    )


def _video_item(
    *, scene_number: int, source_file: Path, start: float
) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=_SCENE_DURATION_SECONDS,
        prompt=f"Top10 countdown real render smoke, scene {scene_number}.",
        provider="Real render smoke fixture",
        local_file=source_file.as_posix(),
        resolution=f"{_WIDTH}x{_HEIGHT}",
        aspect_ratio="16:9",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=start,
        end_time_seconds=start + _SCENE_DURATION_SECONDS,
        track_index=0,
        layer_index=0,
        enabled=True,
        editing_blueprint=_editing_blueprint(scene_number=scene_number),
    )


def _voice_blueprint(*, scene_number: int) -> ResolvedVoiceBlueprint:
    return ResolvedVoiceBlueprint(
        scene_number=scene_number,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.ffmpeg_smoke",
            resolved_profile_id="voice.ffmpeg_smoke",
            display_name="FFmpeg Smoke Voice",
            found_exact_match=True,
            used_fallback=False,
        ),
        narration_text=f"Scene {scene_number} real countdown smoke narration.",
    )


def _stream_duration_seconds(
    *, ffprobe: str, output_file: Path, codec_type: str
) -> float:
    probe = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v" if codec_type == "video" else "a",
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            output_file.as_posix(),
        ]
    )

    lines = [line for line in probe.stdout.splitlines() if line.strip()]

    assert lines, f"No {codec_type} stream duration reported for {output_file}."

    return float(lines[0])


def test_real_countdown_render_splices_the_rank_card_as_a_real_hard_cut(
    tmp_path: Path,
) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    hook_source = tmp_path / "hook.mp4"
    _create_source_video(ffmpeg=ffmpeg, output_file=hook_source, pattern="testsrc2")

    rank_scene_source = tmp_path / "rank_scene.mp4"
    _create_source_video(
        ffmpeg=ffmpeg, output_file=rank_scene_source, pattern="smptebars"
    )

    hook_audio = tmp_path / "hook_voice.wav"
    _create_source_audio(ffmpeg=ffmpeg, output_file=hook_audio)

    rank_scene_audio = tmp_path / "rank_scene_voice.wav"
    _create_source_audio(ffmpeg=ffmpeg, output_file=rank_scene_audio)

    background = tmp_path / "rank_bg.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    card_output = tmp_path / "rank10.mp4"

    card_result = TopTenRankCardRenderService().build(
        rank=10,
        background_image_file=background.as_posix(),
        whoosh_sfx_file=None,
        voiceover_file=None,
        voiceover_duration_seconds=None,
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=float(_FRAME_RATE),
        output_file=card_output.as_posix(),
    )

    assert card_result.success is True
    assert card_result.output_file is not None

    hook_item = _video_item(scene_number=1, source_file=hook_source, start=0.0)
    rank_item = _video_item(
        scene_number=2,
        source_file=rank_scene_source,
        start=float(_SCENE_DURATION_SECONDS),
    )

    video_timeline = VideoTimeline(
        clips=[hook_item.clip, rank_item.clip],
        items=[hook_item, rank_item],
        output_resolution=f"{_WIDTH}x{_HEIGHT}",
        frame_rate=_FRAME_RATE,
    )

    audio_timeline = AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file=hook_audio.as_posix(),
                start_time_seconds=0.0,
                duration_seconds=float(_SCENE_DURATION_SECONDS),
                volume=1.0,
                provider="Real render smoke fixture",
                status=AudioTrackStatus.READY,
                metadata={"scene_number": 1},
            ),
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file=rank_scene_audio.as_posix(),
                start_time_seconds=float(_SCENE_DURATION_SECONDS),
                duration_seconds=float(_SCENE_DURATION_SECONDS),
                volume=1.0,
                provider="Real render smoke fixture",
                status=AudioTrackStatus.READY,
                metadata={"scene_number": 2},
            ),
        ],
        sample_rate=48000,
        channels=2,
    )

    output_file = tmp_path / "final_countdown.mp4"

    service = ProductionRenderService()

    result = service.render_top10_countdown(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[
            _voice_blueprint(scene_number=1),
            _voice_blueprint(scene_number=2),
        ],
        rank_by_scene_number={2: 10},
        rank_card_results={10: card_result},
        output_file=output_file.as_posix(),
    )

    assert result.success is True

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

    assert rendered_file.is_file()

    expected_total_seconds = 2 * _SCENE_DURATION_SECONDS + card_result.duration_seconds

    video_duration = _stream_duration_seconds(
        ffprobe=ffprobe, output_file=rendered_file, codec_type="video"
    )
    audio_duration = _stream_duration_seconds(
        ffprobe=ffprobe, output_file=rendered_file, codec_type="audio"
    )

    # Real proof, not just a status flag: both streams span the full
    # hook + card + ranked-scene duration - the same class of bug this
    # codebase already found once for chunked rendering (audio
    # silently stopping at a segment boundary while video kept going).
    assert abs(video_duration - expected_total_seconds) <= 0.5
    assert abs(audio_duration - expected_total_seconds) <= 0.5


def test_missing_rank_card_raises_instead_of_rendering_without_it(
    tmp_path: Path,
) -> None:
    ffmpeg, _ffprobe = _require_ffmpeg()

    hook_source = tmp_path / "hook.mp4"
    _create_source_video(ffmpeg=ffmpeg, output_file=hook_source, pattern="testsrc2")

    rank_scene_source = tmp_path / "rank_scene.mp4"
    _create_source_video(
        ffmpeg=ffmpeg, output_file=rank_scene_source, pattern="smptebars"
    )

    hook_item = _video_item(scene_number=1, source_file=hook_source, start=0.0)
    rank_item = _video_item(
        scene_number=2,
        source_file=rank_scene_source,
        start=float(_SCENE_DURATION_SECONDS),
    )

    video_timeline = VideoTimeline(
        clips=[hook_item.clip, rank_item.clip],
        items=[hook_item, rank_item],
        output_resolution=f"{_WIDTH}x{_HEIGHT}",
        frame_rate=_FRAME_RATE,
    )

    audio_timeline = AudioTimeline(tracks=[], sample_rate=48000, channels=2)

    service = ProductionRenderService()

    try:
        service.render_top10_countdown(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            voice_blueprints=[
                _voice_blueprint(scene_number=1),
                _voice_blueprint(scene_number=2),
            ],
            rank_by_scene_number={2: 10},
            rank_card_results={},
            output_file=(tmp_path / "unused.mp4").as_posix(),
        )

        raise AssertionError("Expected a ValueError for the missing rank card.")
    except ValueError as error:
        assert "10" in str(error)
