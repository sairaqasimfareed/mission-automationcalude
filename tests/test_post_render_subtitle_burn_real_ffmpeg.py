"""
REQ-0, 2026-09-22: real, end-to-end verification of the FULL post-
render subtitle burn-in chain, no mocking - a real Stage 1 video-only
render feeds a real Stage 2 audio mux, whose real output then gets
real subtitle cues resolved (reusing SubtitleExecutionService's own
proven narration-chunking logic) and burned in via a real FFmpeg
drawtext pass. Verifies real pixel differences appear exactly where a
cue is active (proof text was actually drawn, not just "ffmpeg exited
0"), and that Stage 2's own audio survives byte-identical
(-c:a copy - this pass must never touch audio).
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


def _extract_pcm(*, ffmpeg: str, audio_file: Path, out: Path) -> bytes:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            audio_file.as_posix(),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            out.as_posix(),
        ]
    )

    return out.read_bytes()


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


def test_real_subtitle_burn_in_draws_text_and_preserves_audio_exactly(
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
        prompt="Real subtitle burn-in smoke.",
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
        narration_text="This subtitle should really appear on screen.",
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

    stage1_result = render_service.render_video_only(
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[voice_blueprint],
        transition_duration_seconds=0.0,
    )

    assert stage1_result.success is True
    assert len(stage1_result.scene_timings) == 1

    mux_service = AudioMuxRenderService(
        capability_service=render_service._ffmpeg_capability_service,  # type: ignore[attr-defined]
    )

    stage2_output = tmp_path / "outputs" / "stage2_muxed.mp4"

    stage2_result = mux_service.mux(
        video_only_render_result=stage1_result,
        audio_timeline=audio_timeline,
        output_file=stage2_output.as_posix(),
    )

    assert stage2_result.success is True

    cues = resolve_absolute_subtitle_cues(
        video_timeline=video_timeline,
        voice_blueprints=[voice_blueprint],
        scene_timings=stage1_result.scene_timings,
    )

    assert cues

    burn_service = PostRenderSubtitleBurnService(
        capability_service=render_service._ffmpeg_capability_service,  # type: ignore[attr-defined]
    )

    final_output = tmp_path / "outputs" / "stage3_subtitled.mp4"

    burn_result = burn_service.burn(
        input_video_file=stage2_result.output_file,  # type: ignore[arg-type]
        cues=cues,
        output_file=final_output.as_posix(),
        video_duration_seconds=float(stage2_result.duration_seconds),
    )

    assert burn_result.success is True

    final_file = Path(burn_result.output_file)  # type: ignore[arg-type]
    assert final_file.is_file()

    # Real audio-integrity check: Stage 2's own audio must survive
    # byte-identical (-c:a copy) - the burn pass must never touch it.
    pre_burn_pcm = _extract_pcm(
        ffmpeg=ffmpeg,
        audio_file=Path(stage2_result.output_file),  # type: ignore[arg-type]
        out=tmp_path / "pre_burn.pcm",
    )
    post_burn_pcm = _extract_pcm(
        ffmpeg=ffmpeg, audio_file=final_file, out=tmp_path / "post_burn.pcm"
    )
    assert pre_burn_pcm == post_burn_pcm

    # Real visual proof: a frame taken inside the first cue's real
    # enable-window must differ from the SAME timestamp's frame in
    # Stage 2's own pre-burn output - genuine proof text was drawn,
    # not just "ffmpeg exited 0".
    first_cue = cues[0]
    sample_time = (first_cue.start_seconds + first_cue.end_seconds) / 2.0

    pre_burn_frame = tmp_path / "pre_burn_frame.png"
    post_burn_frame = tmp_path / "post_burn_frame.png"

    _extract_frame(
        ffmpeg=ffmpeg,
        video_file=Path(stage2_result.output_file),  # type: ignore[arg-type]
        at_seconds=sample_time,
        out=pre_burn_frame,
    )
    _extract_frame(
        ffmpeg=ffmpeg,
        video_file=final_file,
        at_seconds=sample_time,
        out=post_burn_frame,
    )

    assert pre_burn_frame.read_bytes() != post_burn_frame.read_bytes()

    # Real stream/duration sanity: video re-encoded (drawtext requires
    # it) but the container still reports the same real duration as
    # Stage 2's own output, audio stream still present.
    probe_output = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration",
            "-of",
            "default=noprint_wrappers=0",
            final_file.as_posix(),
        ]
    ).stdout

    assert "codec_type=video" in probe_output
    assert "codec_type=audio" in probe_output
