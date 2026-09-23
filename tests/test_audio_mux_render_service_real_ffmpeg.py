"""
REQ-00 Stage 2 (audio mux), 2026-09-21: real, end-to-end verification -
a genuine Stage 1 video-only render (no mocking) feeds into
AudioMuxRenderService.mux(), producing one final file with a real
video stream (stream-copied, untouched) and a real, mixed audio
stream. Mirrors test_production_render_service_real_ffmpeg.py's own
real-FFmpeg-integration-test shape rather than mocking any of it -
this is exactly the kind of file where "the types line up" and "the
real muxed output is actually a correct, playable video with sound"
are two different, both necessary claims.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.editing_directives import DirectiveIntensity
from src.models.ffmpeg_config import (
    FFmpegConfig,
    FFmpegHardwareAcceleration,
    FFmpegVideoCodec,
)
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
from src.services.audio_mux_render_service import AudioMuxRenderService
from src.services.production_render_service import ProductionRenderService

_DURATION_SECONDS = 3
_WIDTH = 640
_HEIGHT = 360
_FRAME_RATE = 30


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real Stage 2 mux smoke requires ffmpeg and ffprobe.")

    return ffmpeg, ffprobe


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
            f"testsrc2=size={_WIDTH}x{_HEIGHT}:rate={_FRAME_RATE}:duration={_DURATION_SECONDS}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            output_file.as_posix(),
        ]
    )


def _create_source_audio(*, ffmpeg: str, output_file: Path) -> None:
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
            f"sine=frequency=440:sample_rate=48000:duration={_DURATION_SECONDS}",
            "-c:a",
            "pcm_s16le",
            output_file.as_posix(),
        ]
    )


def _probe_output(*, ffprobe: str, output_file: Path) -> str:
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,duration",
            output_file.as_posix(),
        ]
    )

    return result.stdout


def _preset(*, directive_path: str, preset_id: str) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        used_fallback=False,
    )


def _editing_blueprint(scene_number: int) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_preset(
            directive_path="genre_preset_id", preset_id="genre.default"
        ),
        camera=ResolvedCameraInstruction(
            preset=_preset(directive_path="camera.preset_id", preset_id="camera.none"),
            intensity=DirectiveIntensity.MEDIUM,
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


def test_real_stage2_mux_produces_a_playable_file_with_real_audio(
    tmp_path: Path,
) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    source_video = tmp_path / "inputs" / "scene_001.mp4"
    source_audio = tmp_path / "inputs" / "voice_001.wav"

    _create_source_video(ffmpeg=ffmpeg, output_file=source_video)
    _create_source_audio(ffmpeg=ffmpeg, output_file=source_audio)

    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=_DURATION_SECONDS,
        prompt="Real Stage 2 mux smoke.",
        local_file=source_video.as_posix(),
        resolution=f"{_WIDTH}x{_HEIGHT}",
        aspect_ratio="16:9",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    item = VideoTimelineItem(
        clip=clip,
        scene_number=1,
        start_time_seconds=0.0,
        end_time_seconds=float(_DURATION_SECONDS),
        track_index=0,
        layer_index=0,
        enabled=True,
        editing_blueprint=_editing_blueprint(1),
    )

    video_timeline = VideoTimeline(
        clips=[clip],
        items=[item],
        output_resolution=f"{_WIDTH}x{_HEIGHT}",
        frame_rate=_FRAME_RATE,
    )

    audio_track = AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file=source_audio.as_posix(),
        start_time_seconds=0.0,
        duration_seconds=float(_DURATION_SECONDS),
        status=AudioTrackStatus.READY,
        metadata={"scene_number": 1},
    )

    audio_timeline = AudioTimeline(tracks=[audio_track], sample_rate=48000, channels=2)

    voice_blueprint = ResolvedVoiceBlueprint(
        scene_number=1,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.smoke",
            resolved_profile_id="voice.smoke",
            display_name="Smoke Voice",
            found_exact_match=True,
            used_fallback=False,
        ),
        narration_text="Real Stage 2 mux smoke narration.",
    )

    stage1_output = tmp_path / "outputs" / "stage1_video_only.mp4"

    render_service = ProductionRenderService(
        ffmpeg_config=FFmpegConfig(
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            video_codec=FFmpegVideoCodec.LIBX264,
            hardware_acceleration=FFmpegHardwareAcceleration.NONE,
            timeout_seconds=60.0,
        ),
        output_file=stage1_output.as_posix(),
    )

    stage1_result = render_service.render_video_only(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[voice_blueprint],
    )

    assert stage1_result.success is True

    stage2_output = tmp_path / "outputs" / "stage2_muxed.mp4"

    mux_service = AudioMuxRenderService(
        capability_service=render_service._ffmpeg_capability_service,  # type: ignore[attr-defined]
    )

    stage2_result = mux_service.mux(
        video_only_render_result=stage1_result,
        audio_timeline=audio_timeline,
        output_file=stage2_output.as_posix(),
    )

    assert stage2_result.success is True
    assert stage2_result.status.value == "completed"

    rendered_file = Path(stage2_result.output_file)  # type: ignore[arg-type]
    assert rendered_file == stage2_output
    assert rendered_file.is_file()
    assert rendered_file.stat().st_size > 0

    probe_output = _probe_output(ffprobe=ffprobe, output_file=rendered_file)

    assert "codec_type=video" in probe_output
    assert "codec_type=audio" in probe_output
    assert "codec_name=h264" in probe_output

    # scene_timings must survive from Stage 1 through to Stage 2's own
    # result unchanged - REQ-0's future consumer needs it regardless
    # of which stage's RenderResult it ends up reading.
    assert stage2_result.scene_timings == stage1_result.scene_timings


def test_mux_rejects_a_failed_stage1_result(tmp_path: Path) -> None:
    from src.models.render_result import RenderResult, RenderStatus

    failed_stage1 = RenderResult(
        success=False,
        output_file=None,
        render_engine="ffmpeg",
        status=RenderStatus.FAILED,
    )

    audio_timeline = AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file="unused.wav",
                start_time_seconds=0.0,
                duration_seconds=1.0,
                status=AudioTrackStatus.READY,
            )
        ]
    )

    with pytest.raises(ValueError, match="successful Stage 1"):
        AudioMuxRenderService().mux(
            video_only_render_result=failed_stage1,
            audio_timeline=audio_timeline,
            output_file=(tmp_path / "out.mp4").as_posix(),
        )


def test_mux_rejects_an_empty_audio_timeline(tmp_path: Path) -> None:
    from src.models.render_result import RenderResult, RenderStatus

    stage1_result = RenderResult(
        success=True,
        output_file=(tmp_path / "video.mp4").as_posix(),
        render_engine="ffmpeg",
        status=RenderStatus.COMPLETED,
        duration_seconds=3,
    )

    with pytest.raises(ValueError, match="at least one audio track"):
        AudioMuxRenderService().mux(
            video_only_render_result=stage1_result,
            audio_timeline=AudioTimeline(),
            output_file=(tmp_path / "out.mp4").as_posix(),
        )
