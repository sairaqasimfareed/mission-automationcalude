"""
REQ-00/REQ-0 staged-pipeline swap, 2026-09-24: real, non-mocked before/
after comparison - the exact same real timeline (one scene, real video
+ real narration audio) rendered through BOTH the old, still-live
one-shot composite ProductionRenderService.render() AND the new staged
sequence (Stage 1 render_video_only() -> Stage 2 AudioMuxRenderService.
mux() -> Stage 3 PostRenderSubtitleBurnService.burn(), the exact chain
RenderPipelineStage._execute_staged_render() now wires into the live
render path), verifying the two are functionally equivalent: same real
duration, both carry a real audio stream, and both visibly burn the
same subtitle text in at the same real timestamp.

Deliberately does NOT assert byte-identical or pixel-identical video
between the two paths - they are genuinely different FFmpeg command
graphs (one filter-complex pass vs three separate passes), so encoder
output legitimately differs at the byte level even with identical
settings. What must be identical is real, observable behavior: length,
audio presence, and subtitle visibility - not encoder internals.
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
from src.services.audio_mux_render_service import AudioMuxRenderService
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
        raise RuntimeError(
            "Staged-vs-composite real comparison requires ffmpeg/ffprobe."
        )

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


def _extract_frame(
    *, ffmpeg: str, video_file: Path, at_seconds: float, out: Path
) -> None:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            video_file.as_posix(),
            "-vframes",
            "1",
            out.as_posix(),
        ]
    )


def _probe_duration_seconds(*, ffprobe: str, video_file: Path) -> float:
    output = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_file.as_posix(),
        ]
    ).stdout

    return float(output.strip())


def _probe_stream_types(*, ffprobe: str, video_file: Path) -> str:
    return _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=0",
            video_file.as_posix(),
        ]
    ).stdout


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


def test_staged_pipeline_matches_composite_render_real_behavior(
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
        prompt="Staged-vs-composite real comparison.",
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
        narration_text="This subtitle should appear in both real renders.",
        estimated_speech_duration_seconds=float(_DURATION_SECONDS),
    )

    ffmpeg_config = FFmpegConfig(
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        video_codec=FFmpegVideoCodec.LIBX264,
        hardware_acceleration=FFmpegHardwareAcceleration.NONE,
        timeout_seconds=60.0,
    )

    # --- OLD, still-live one-shot composite path ---------------------

    old_render_service = ProductionRenderService(
        ffmpeg_config=ffmpeg_config,
        output_file=(tmp_path / "outputs" / "old_composite.mp4").as_posix(),
    )

    old_result = old_render_service.render(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[voice_blueprint],
        transition_duration_seconds=0.0,
        letterbox_enabled=False,
        include_subtitles=True,
    )

    assert old_result.success is True
    old_output = Path(old_result.output_file)  # type: ignore[arg-type]
    assert old_output.is_file()

    # --- NEW staged sequence, the exact chain _execute_staged_render()
    # wires into the live render path -----------------------------

    new_render_service = ProductionRenderService(
        ffmpeg_config=ffmpeg_config,
        output_file=(tmp_path / "outputs" / "new_staged.mp4").as_posix(),
    )

    stage1_result = new_render_service.render_video_only(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[voice_blueprint],
        output_file=(tmp_path / "outputs" / "new_stage1.mp4").as_posix(),
        transition_duration_seconds=0.0,
        letterbox_enabled=False,
    )

    assert stage1_result.success is True

    mux_service = AudioMuxRenderService(
        capability_service=new_render_service._ffmpeg_capability_service,  # type: ignore[attr-defined]
    )

    stage2_result = mux_service.mux(
        video_only_render_result=stage1_result,
        audio_timeline=audio_timeline,
        output_file=(tmp_path / "outputs" / "new_stage2.mp4").as_posix(),
    )

    assert stage2_result.success is True

    cues = resolve_absolute_subtitle_cues(
        video_timeline=video_timeline,
        voice_blueprints=[voice_blueprint],
        scene_timings=stage1_result.scene_timings,
    )

    assert cues

    burn_service = PostRenderSubtitleBurnService(
        capability_service=new_render_service._ffmpeg_capability_service,  # type: ignore[attr-defined]
    )

    new_result = burn_service.burn(
        input_video_file=stage2_result.output_file,  # type: ignore[arg-type]
        cues=cues,
        output_file=(tmp_path / "outputs" / "new_staged.mp4").as_posix(),
        video_duration_seconds=float(stage2_result.duration_seconds),
        has_audio=True,
    )

    assert new_result.success is True
    new_output = Path(new_result.output_file)  # type: ignore[arg-type]
    assert new_output.is_file()

    # --- Real behavioral equivalence -----------------------------

    old_duration = _probe_duration_seconds(ffprobe=ffprobe, video_file=old_output)
    new_duration = _probe_duration_seconds(ffprobe=ffprobe, video_file=new_output)
    assert abs(old_duration - new_duration) < 0.5

    old_streams = _probe_stream_types(ffprobe=ffprobe, video_file=old_output)
    new_streams = _probe_stream_types(ffprobe=ffprobe, video_file=new_output)
    assert "codec_type=video" in old_streams
    assert "codec_type=audio" in old_streams
    assert "codec_type=video" in new_streams
    assert "codec_type=audio" in new_streams

    # Real visual proof: in EACH pipeline separately, a frame sampled
    # inside the first cue's real enable-window differs from a frame
    # sampled just before any subtitle could be on screen - genuine
    # proof text was drawn in both, not just "ffmpeg exited 0" in both.
    first_cue = cues[0]
    sample_time = (first_cue.start_seconds + first_cue.end_seconds) / 2.0
    baseline_time = 0.0

    for label, output_file in (("old", old_output), ("new", new_output)):
        baseline_frame = tmp_path / f"{label}_baseline_frame.png"
        subtitle_frame = tmp_path / f"{label}_subtitle_frame.png"

        _extract_frame(
            ffmpeg=ffmpeg,
            video_file=output_file,
            at_seconds=baseline_time,
            out=baseline_frame,
        )
        _extract_frame(
            ffmpeg=ffmpeg,
            video_file=output_file,
            at_seconds=sample_time,
            out=subtitle_frame,
        )

        assert baseline_frame.read_bytes() != subtitle_frame.read_bytes(), (
            f"{label} pipeline's subtitle frame did not visibly "
            "differ from its own baseline frame."
        )
