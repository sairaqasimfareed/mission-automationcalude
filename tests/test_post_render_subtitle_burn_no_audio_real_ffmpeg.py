"""
REQ-00/REQ-0 staged-pipeline swap, 2026-09-24: real, non-mocked proof
that PostRenderSubtitleBurnService.burn(has_audio=False) correctly
handles a genuinely audio-less input.

Real gap this proves: AudioInclusionPreferences' four toggles
(REQ-10(a)) are MUX-TIME deselects, not pre-generation skips - a real
voiceover track always still gets generated and must still be present
in the audio_timeline passed to render_video_only() (Stage 1), since
MasterEditPlanService's render-readiness validation requires it
regardless of what the user chose to mute. Stage 1's OWN output never
has an audio stream by construction (include_audio=False always), so
when every REQ-13 toggle ends up off at mux time and Stage 2's mux is
skipped entirely, Stage 1's raw output IS what reaches Stage 3
directly - and the previously-hardcoded `-map 0:a` would have failed
FFmpeg's own stream-mapping outright on such a file.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

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
from src.services.post_render_subtitle_burn_service import (
    PostRenderSubtitleBurnService,
)
from src.services.production_render_service import ProductionRenderService
from src.services.subtitle_cue_resolution_service import (
    resolve_absolute_subtitle_cues,
)

_DURATION_SECONDS = 4
_WIDTH = 640
_HEIGHT = 360
_FRAME_RATE = 30


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real subtitle burn-in smoke requires ffmpeg/ffprobe.")

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
            enabled=True,
            burn_into_video=False,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
    )


def test_real_subtitle_burn_with_no_audio_stream_at_all(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    source_video = tmp_path / "inputs" / "scene_001.mp4"
    source_audio = tmp_path / "inputs" / "voice_001.wav"

    _create_source_video(ffmpeg=ffmpeg, output_file=source_video)
    _create_source_audio(ffmpeg=ffmpeg, output_file=source_audio)

    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=_DURATION_SECONDS,
        prompt="Real no-audio subtitle burn-in smoke.",
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
        narration_text="This subtitle should still appear with no audio at all.",
        estimated_speech_duration_seconds=float(_DURATION_SECONDS),
    )

    render_service = ProductionRenderService(
        ffmpeg_config=FFmpegConfig(
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            video_codec=FFmpegVideoCodec.LIBX264,
            hardware_acceleration=FFmpegHardwareAcceleration.NONE,
            timeout_seconds=60.0,
        ),
        output_file=(tmp_path / "outputs" / "stage1_video_only.mp4").as_posix(),
    )

    # Voiceover generation still runs unconditionally (REQ-10(a)) even
    # when every mux-time toggle ends up off, so Stage 1 still receives
    # the real, unfiltered audio_timeline - MasterEditPlanService's
    # render-readiness validation requires a real voiceover track
    # regardless of what the caller will later choose to mux in.
    narration_track = AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file=source_audio.as_posix(),
        start_time_seconds=0.0,
        duration_seconds=float(_DURATION_SECONDS),
        status=AudioTrackStatus.READY,
        metadata={"scene_number": 1},
    )

    audio_timeline = AudioTimeline(
        tracks=[narration_track], sample_rate=48000, channels=2
    )

    # Stage 1's own command plan never includes audio nodes
    # (include_audio=False always) - its raw output has zero audio
    # streams by construction, which is exactly what reaches Stage 3
    # directly whenever a caller decides (because the real, filtered
    # mux-time audio_timeline turned out to have zero allowed tracks)
    # to skip Stage 2's mux entirely.
    stage1_result = render_service.render_video_only(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[voice_blueprint],
        transition_duration_seconds=0.0,
    )

    assert stage1_result.success is True

    probe_before = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=0",
            stage1_result.output_file,  # type: ignore[list-item]
        ]
    ).stdout

    assert "codec_type=audio" not in probe_before

    cues = resolve_absolute_subtitle_cues(
        video_timeline=video_timeline,
        voice_blueprints=[voice_blueprint],
        scene_timings=stage1_result.scene_timings,
    )

    assert cues

    burn_service = PostRenderSubtitleBurnService(
        capability_service=render_service._ffmpeg_capability_service,  # type: ignore[attr-defined]
    )

    final_output = tmp_path / "outputs" / "stage3_subtitled_no_audio.mp4"

    burn_result = burn_service.burn(
        input_video_file=stage1_result.output_file,  # type: ignore[arg-type]
        cues=cues,
        output_file=final_output.as_posix(),
        video_duration_seconds=float(stage1_result.duration_seconds),
        has_audio=False,
    )

    assert burn_result.success is True

    final_file = Path(burn_result.output_file)  # type: ignore[arg-type]
    assert final_file.is_file()

    probe_after = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=0",
            final_file.as_posix(),
        ]
    ).stdout

    assert "codec_type=video" in probe_after
    assert "codec_type=audio" not in probe_after
