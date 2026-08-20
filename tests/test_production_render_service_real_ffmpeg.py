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
from src.models.editing_directives import (
    DirectiveIntensity,
)
from src.models.ffmpeg_config import (
    FFmpegConfig,
    FFmpegHardwareAcceleration,
    FFmpegVideoCodec,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.render_result import (
    RenderStatus,
)
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
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import (
    VideoTimeline,
)
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.production_render_service import (
    ProductionRenderService,
)

SMOKE_DURATION_SECONDS = 3
SMOKE_WIDTH = 640
SMOKE_HEIGHT = 360
SMOKE_FRAME_RATE = 30


def _run_command(
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    """
    Run one deterministic external command.

    The real-render smoke deliberately uses subprocess only to create
    synthetic source fixtures and to inspect the final output. The
    actual render under test is always executed by
    ProductionRenderService.
    """

    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )


def _require_ffmpeg() -> tuple[str, str]:
    """
    Return local FFmpeg and ffprobe executables.

    The test is intentionally a real-runtime integration smoke, so a
    machine without the binaries should fail rather than silently pass.
    """

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None:
        raise RuntimeError("Real production render smoke requires ffmpeg.")

    if ffprobe is None:
        raise RuntimeError("Real production render smoke requires ffprobe.")

    return (
        ffmpeg,
        ffprobe,
    )


def _create_source_video(
    *,
    ffmpeg: str,
    output_file: Path,
) -> None:
    """
    Create a short deterministic real H.264 source clip.

    This is fixture preparation only. It is not the render operation
    being tested.
    """

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    _run_command(
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
                "testsrc2="
                f"size={SMOKE_WIDTH}x{SMOKE_HEIGHT}:"
                f"rate={SMOKE_FRAME_RATE}:"
                f"duration={SMOKE_DURATION_SECONDS}"
            ),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            output_file.as_posix(),
        ]
    )

    assert output_file.is_file()
    assert output_file.stat().st_size > 0


def _create_source_audio(
    *,
    ffmpeg: str,
    output_file: Path,
) -> None:
    """
    Create a short deterministic PCM voiceover fixture.

    A generated sine wave is sufficient because this smoke verifies
    render plumbing rather than speech synthesis quality.
    """

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    _run_command(
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
                "sine="
                "frequency=440:"
                "sample_rate=48000:"
                f"duration={SMOKE_DURATION_SECONDS}"
            ),
            "-c:a",
            "pcm_s16le",
            output_file.as_posix(),
        ]
    )

    assert output_file.is_file()
    assert output_file.stat().st_size > 0


def _preset_reference(
    *,
    directive_path: str,
    preset_id: str,
    implementation: dict[str, object] | None = None,
) -> ResolvedPresetReference:
    """Build one exact resolved editing-preset reference."""

    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        used_fallback=False,
        implementation=dict(implementation or {}),
        metadata={},
    )


def _editing_blueprint(
    *,
    scene_number: int,
) -> ResolvedSceneEditingBlueprint:
    """
    Build a minimal resolved production editing blueprint.

    No creative effect is required for this smoke. The objective is to
    exercise the real production render architecture with the safest
    valid editing configuration.
    """

    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_preset_reference(
            directive_path="genre_preset_id",
            preset_id="genre.default",
        ),
        camera=ResolvedCameraInstruction(
            preset=_preset_reference(
                directive_path="camera.preset_id",
                preset_id="camera.none",
                implementation={
                    "motion": "none",
                },
            ),
            intensity=DirectiveIntensity.MEDIUM,
            start_offset_seconds=0.0,
        ),
        transition_in=(
            ResolvedTransitionInstruction(
                preset=_preset_reference(
                    directive_path=("transition_in.preset_id"),
                    preset_id="transition.cut",
                    implementation={
                        "type": "cut",
                    },
                ),
                duration_seconds=0.0,
                intensity=DirectiveIntensity.MEDIUM,
            )
        ),
        transition_out=(
            ResolvedTransitionInstruction(
                preset=_preset_reference(
                    directive_path=("transition_out.preset_id"),
                    preset_id="transition.cut",
                    implementation={
                        "type": "cut",
                    },
                ),
                duration_seconds=0.0,
                intensity=DirectiveIntensity.MEDIUM,
            )
        ),
        visual_effects=[],
        animations=[],
        music=ResolvedMusicInstruction(
            preset=_preset_reference(
                directive_path="music.preset_id",
                preset_id="music.none",
            ),
            intensity=DirectiveIntensity.LOW,
            volume_percent=25.0,
            fade_in_seconds=0.0,
            fade_out_seconds=0.0,
            duck_under_voice=True,
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=_preset_reference(
                directive_path=("subtitles.preset_id"),
                preset_id="subtitle.none",
            ),
            animation_preset=None,
            enabled=False,
            burn_into_video=False,
            maximum_words_per_line=8,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
        fallback_count=0,
        exact_match_count=6,
        warnings=[],
        metadata={},
    )


def _video_timeline(
    *,
    source_file: Path,
) -> VideoTimeline:
    """Build one real-file explicit production video timeline."""

    clip = VideoClip(
        scene_number=1,
        source_type=(SceneSourceType.MANUAL_UPLOAD),
        duration_seconds=(SMOKE_DURATION_SECONDS),
        prompt=("Real ProductionRenderService " "FFmpeg integration smoke."),
        provider="F.4E synthetic fixture",
        local_file=source_file.as_posix(),
        resolution=(f"{SMOKE_WIDTH}x{SMOKE_HEIGHT}"),
        aspect_ratio="16:9",
        source_status=(SceneSourceStatus.READY),
        status=VideoClipStatus.READY,
    )

    item = VideoTimelineItem(
        clip=clip,
        scene_number=1,
        start_time_seconds=0.0,
        end_time_seconds=float(SMOKE_DURATION_SECONDS),
        track_index=0,
        layer_index=0,
        enabled=True,
        editing_blueprint=(
            _editing_blueprint(
                scene_number=1,
            )
        ),
    )

    timeline = VideoTimeline(
        clips=[
            clip,
        ],
        items=[
            item,
        ],
        output_resolution=(f"{SMOKE_WIDTH}x{SMOKE_HEIGHT}"),
        frame_rate=SMOKE_FRAME_RATE,
    )

    assert timeline.calculate_duration() == float(SMOKE_DURATION_SECONDS)

    assert item.is_render_ready is True

    return timeline


def _audio_timeline(
    *,
    source_file: Path,
) -> AudioTimeline:
    """Build one real-file production voiceover timeline."""

    track = AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file=source_file.as_posix(),
        start_time_seconds=0.0,
        duration_seconds=float(SMOKE_DURATION_SECONDS),
        volume=1.0,
        fade_in_seconds=0.0,
        fade_out_seconds=0.0,
        loop_enabled=False,
        duck_under_voice=False,
        provider="F.4E synthetic fixture",
        status=AudioTrackStatus.READY,
        metadata={
            "scene_number": 1,
        },
    )

    timeline = AudioTimeline(
        tracks=[
            track,
        ],
        sample_rate=48000,
        channels=2,
    )

    assert timeline.calculate_duration() == float(SMOKE_DURATION_SECONDS)

    return timeline


def _voice_blueprint() -> ResolvedVoiceBlueprint:
    """
    Build the authoritative resolved voice blueprint for scene one.

    Subtitles are intentionally disabled in the editing blueprint, but
    ProductionRenderService still requires the canonical voice
    blueprint collection as part of its render contract.
    """

    return ResolvedVoiceBlueprint(
        scene_number=1,
        status=(VoiceBlueprintResolutionStatus.RESOLVED),
        profile=ResolvedVoiceProfileReference(
            requested_profile_id=("voice.ffmpeg_smoke"),
            resolved_profile_id=("voice.ffmpeg_smoke"),
            display_name=("FFmpeg Smoke Voice"),
            found_exact_match=True,
            used_fallback=False,
        ),
        narration_text=(
            "This is the real production render " "integration smoke test."
        ),
    )


def _probe_output(
    *,
    ffprobe: str,
    output_file: Path,
) -> str:
    """Return compact stream metadata from the produced MP4."""

    completed = _run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            ("format=duration:" "stream=index,codec_type," "codec_name,width,height"),
            "-of",
            "default=noprint_wrappers=1",
            output_file.as_posix(),
        ]
    )

    return completed.stdout


def test_real_production_render_service_executes_ffmpeg(
    tmp_path: Path,
) -> None:
    """
    Verify the complete real production render path.

    This test crosses all of the production boundaries that F.4 was
    created to connect:

    VideoTimeline + AudioTimeline
        -> MasterEditPlan
        -> execution plans
        -> RenderGraph
        -> FilterGraph
        -> FFmpegCommandPlan
        -> FFmpegExecutionService
        -> physical MP4
        -> RenderResult
    """

    (
        ffmpeg,
        ffprobe,
    ) = _require_ffmpeg()

    source_video = tmp_path / "inputs" / "scene_001.mp4"

    source_audio = tmp_path / "inputs" / "voice_001.wav"

    output_file = tmp_path / "outputs" / "production_render_smoke.mp4"

    _create_source_video(
        ffmpeg=ffmpeg,
        output_file=source_video,
    )

    _create_source_audio(
        ffmpeg=ffmpeg,
        output_file=source_audio,
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    video_timeline = _video_timeline(
        source_file=source_video,
    )

    audio_timeline = _audio_timeline(
        source_file=source_audio,
    )

    voice_blueprint = _voice_blueprint()

    service = ProductionRenderService(
        ffmpeg_config=FFmpegConfig(
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            video_codec=(FFmpegVideoCodec.LIBX264),
            hardware_acceleration=(FFmpegHardwareAcceleration.NONE),
            timeout_seconds=60.0,
        ),
        output_file=output_file.as_posix(),
    )

    result = service.render(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[
            voice_blueprint,
        ],
    )

    assert result.success is True

    assert result.status == RenderStatus.COMPLETED

    assert result.render_engine == "ffmpeg"

    assert result.output_file is not None

    rendered_file = Path(result.output_file)

    assert rendered_file == output_file

    assert rendered_file.is_file()

    assert rendered_file.stat().st_size > 0

    assert result.render_time_seconds >= 0.0

    assert result.duration_seconds == SMOKE_DURATION_SECONDS

    probe_output = _probe_output(
        ffprobe=ffprobe,
        output_file=rendered_file,
    )

    assert "codec_type=video" in probe_output

    assert "codec_type=audio" in probe_output

    assert "codec_name=h264" in probe_output

    assert f"width={SMOKE_WIDTH}" in probe_output

    assert f"height={SMOKE_HEIGHT}" in probe_output
