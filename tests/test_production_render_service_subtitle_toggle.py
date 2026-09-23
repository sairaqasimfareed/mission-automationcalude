"""
Subtitle on/off toggle, 2026-09-23: real, non-mocked proof that
ProductionRenderService.render()'s new include_subtitles parameter -
previously only ever exercised by REQ-00 Stage 1's render_video_only()
- now genuinely gates subtitle burn-in on the LIVE composite render()
path too. RenderGraphBuilderService/FilterGraphBuilderService's own
include_subtitles relaxation is already real, tested infrastructure
(REQ-00 Stage 1); what's new here is render() actually exposing and
forwarding it, so this test proves the WIRING, not the underlying
drawtext mechanism (already extensively real-FFmpeg-verified by
REQ-0/REQ-5's own subtitle tests).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
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

_WIDTH = 640
_HEIGHT = 360
_FRAME_RATE = 30
_SCENE_DURATION_SECONDS = 4


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg is None:
        raise RuntimeError("Real subtitle toggle smoke requires ffmpeg.")

    return ffmpeg


def _create_source_video(*, ffmpeg: str, output_file: Path) -> None:
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
                f"testsrc2=size={_WIDTH}x{_HEIGHT}:"
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


def _editing_blueprint_with_subtitles() -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=1,
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
                directive_path="subtitles.preset_id", preset_id="subtitle.default"
            ),
            enabled=True,
            burn_into_video=True,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
    )


def _video_timeline(*, source_file: Path) -> VideoTimeline:
    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=_SCENE_DURATION_SECONDS,
        prompt="Subtitle toggle real smoke.",
        provider="Real render smoke fixture",
        local_file=source_file.as_posix(),
        resolution=f"{_WIDTH}x{_HEIGHT}",
        aspect_ratio="16:9",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    item = VideoTimelineItem(
        clip=clip,
        scene_number=1,
        start_time_seconds=0.0,
        end_time_seconds=float(_SCENE_DURATION_SECONDS),
        track_index=0,
        layer_index=0,
        enabled=True,
        editing_blueprint=_editing_blueprint_with_subtitles(),
    )

    return VideoTimeline(
        clips=[clip],
        items=[item],
        output_resolution=f"{_WIDTH}x{_HEIGHT}",
        frame_rate=_FRAME_RATE,
    )


def _audio_timeline(*, source_file: Path) -> AudioTimeline:
    return AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file=source_file.as_posix(),
                start_time_seconds=0.0,
                duration_seconds=float(_SCENE_DURATION_SECONDS),
                volume=1.0,
                provider="Real render smoke fixture",
                status=AudioTrackStatus.READY,
                metadata={"scene_number": 1},
            )
        ],
        sample_rate=48000,
        channels=2,
    )


def _voice_blueprint() -> ResolvedVoiceBlueprint:
    return ResolvedVoiceBlueprint(
        scene_number=1,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.ffmpeg_smoke",
            resolved_profile_id="voice.ffmpeg_smoke",
            display_name="FFmpeg Smoke Voice",
            found_exact_match=True,
            used_fallback=False,
        ),
        narration_text=(
            "This is a real subtitle line that should only appear "
            "on screen when subtitles are enabled for this render."
        ),
    )


def test_include_subtitles_true_builds_a_real_drawtext_filter() -> None:
    ffmpeg = _require_ffmpeg()

    service = ProductionRenderService()

    resolved_config = service._ffmpeg_capability_service.resolve(
        service._with_bounded_keyframe_interval(
            service._ffmpeg_config, frame_rate=_FRAME_RATE
        )
    )

    command_plan, _master_plan, _warnings, _staging_output_file = (
        service._build_command_plan(
            video_timeline=_video_timeline(source_file=Path(ffmpeg)),
            audio_timeline=_audio_timeline(source_file=Path(ffmpeg)),
            voice_blueprints=[_voice_blueprint()],
            target_output_file="outputs/subtitle_toggle_smoke.mp4",
            resolved_config=resolved_config,
            include_subtitles=True,
        )
    )

    assert "drawtext" in command_plan.filter_complex


def test_include_subtitles_false_builds_no_drawtext_filter_at_all() -> None:
    ffmpeg = _require_ffmpeg()

    service = ProductionRenderService()

    resolved_config = service._ffmpeg_capability_service.resolve(
        service._with_bounded_keyframe_interval(
            service._ffmpeg_config, frame_rate=_FRAME_RATE
        )
    )

    command_plan, _master_plan, _warnings, _staging_output_file = (
        service._build_command_plan(
            video_timeline=_video_timeline(source_file=Path(ffmpeg)),
            audio_timeline=_audio_timeline(source_file=Path(ffmpeg)),
            voice_blueprints=[_voice_blueprint()],
            target_output_file="outputs/subtitle_toggle_smoke.mp4",
            resolved_config=resolved_config,
            include_subtitles=False,
        )
    )

    assert "drawtext" not in command_plan.filter_complex


def test_real_render_succeeds_both_with_and_without_subtitles(
    tmp_path: Path,
) -> None:
    ffmpeg = _require_ffmpeg()

    source_video = tmp_path / "source.mp4"
    _create_source_video(ffmpeg=ffmpeg, output_file=source_video)

    source_audio = tmp_path / "source_voice.wav"
    _create_source_audio(ffmpeg=ffmpeg, output_file=source_audio)

    service = ProductionRenderService()

    with_subtitles_result = service.render(
        video_timeline=_video_timeline(source_file=source_video),
        audio_timeline=_audio_timeline(source_file=source_audio),
        voice_blueprints=[_voice_blueprint()],
        output_file=(tmp_path / "with_subtitles.mp4").as_posix(),
        include_subtitles=True,
    )

    assert with_subtitles_result.success is True
    assert Path(with_subtitles_result.output_file).is_file()  # type: ignore[arg-type]

    without_subtitles_result = service.render(
        video_timeline=_video_timeline(source_file=source_video),
        audio_timeline=_audio_timeline(source_file=source_audio),
        voice_blueprints=[_voice_blueprint()],
        output_file=(tmp_path / "without_subtitles.mp4").as_posix(),
        include_subtitles=False,
    )

    assert without_subtitles_result.success is True
    assert Path(without_subtitles_result.output_file).is_file()  # type: ignore[arg-type]
