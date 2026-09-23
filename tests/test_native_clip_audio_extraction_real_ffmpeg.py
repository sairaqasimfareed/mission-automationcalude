"""
REQ-10(a), 2026-09-22: real, end-to-end verification of the FULL
"use native clip audio" chain, no mocking anywhere - a real video
WITH its own embedded audio (unlike every other real-FFmpeg test this
session, which deliberately uses -an silent sources) feeds through:

  Stage 1 (video-only render, strips the clip's own audio)
  -> NativeClipAudioExtractionService (pulls that same clip's own
     audio back out, positioned at its real Stage 1 timing)
  -> filter_audio_timeline_for_mux (REQ-10(a)'s own toggle)
  -> Stage 2 (AudioMuxRenderService.mux)

producing one final file whose audio is genuinely the original clip's
own embedded audio, not narration - confirmed by comparing real
extracted PCM samples, not just stream presence.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.models.audio_inclusion_preferences import AudioInclusionPreferences
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
from src.services.audio_inclusion_filter_service import (
    filter_audio_timeline_for_mux,
)
from src.services.audio_mux_render_service import AudioMuxRenderService
from src.services.native_clip_audio_extraction_service import (
    NativeClipAudioExtractionService,
)
from src.services.production_render_service import ProductionRenderService

_DURATION_SECONDS = 3
_WIDTH = 640
_HEIGHT = 360
_FRAME_RATE = 30
_NATIVE_TONE_HZ = 880
_NARRATION_TONE_HZ = 220


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real native-clip-audio smoke requires ffmpeg/ffprobe.")

    return ffmpeg, ffprobe


def _create_clip_with_native_audio(
    *, ffmpeg: str, output_file: Path, tone_hz: int
) -> None:
    """A real clip carrying its OWN embedded audio - unlike this
    session's other synthetic fixtures (-an, deliberately silent)."""

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
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={tone_hz}:sample_rate=48000:duration={_DURATION_SECONDS}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            output_file.as_posix(),
        ]
    )


def _create_narration_audio(*, ffmpeg: str, output_file: Path, tone_hz: int) -> None:
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
            f"sine=frequency={tone_hz}:sample_rate=48000:duration={_DURATION_SECONDS}",
            "-c:a",
            "pcm_s16le",
            output_file.as_posix(),
        ]
    )


def _dominant_frequency_hz(*, ffmpeg: str, audio_file: Path) -> float:
    """
    Real spectral check, not just "an audio stream exists" - decodes
    to raw PCM and estimates the dominant tone via zero-crossing rate
    (stdlib only, no numpy - not a declared project dependency, so a
    test must not silently require it). For a clean, single-tone sine
    wave at frequency f, real zero crossings per second land at
    2f - good enough to tell 880Hz (native clip tone) apart from
    220Hz (narration tone), a 4x difference, not a general-purpose
    pitch detector.
    """

    import struct

    raw_path = audio_file.with_suffix(".raw")

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
            "-ac",
            "1",
            "-ar",
            "48000",
            raw_path.as_posix(),
        ]
    )

    raw_bytes = raw_path.read_bytes()
    sample_count = len(raw_bytes) // 2
    samples = struct.unpack(f"<{sample_count}h", raw_bytes[: sample_count * 2])

    zero_crossings = sum(
        1
        for previous, current in zip(samples, samples[1:], strict=False)
        if (previous < 0) != (current < 0)
    )

    duration_seconds = sample_count / 48000.0

    return (zero_crossings / 2.0) / duration_seconds


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


def test_real_native_clip_audio_survives_the_full_stage1_to_stage2_chain(
    tmp_path: Path,
) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    source_video = tmp_path / "inputs" / "scene_001.mp4"
    narration_audio = tmp_path / "inputs" / "voice_001.wav"

    _create_clip_with_native_audio(
        ffmpeg=ffmpeg, output_file=source_video, tone_hz=_NATIVE_TONE_HZ
    )
    _create_narration_audio(
        ffmpeg=ffmpeg, output_file=narration_audio, tone_hz=_NARRATION_TONE_HZ
    )

    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=_DURATION_SECONDS,
        prompt="Real native-clip-audio smoke.",
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
        source_file=narration_audio.as_posix(),
        start_time_seconds=0.0,
        duration_seconds=float(_DURATION_SECONDS),
        status=AudioTrackStatus.READY,
        metadata={"scene_number": 1},
    )

    audio_timeline_for_stage1 = AudioTimeline(
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
        narration_text="Real native-clip-audio smoke narration.",
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
        audio_timeline=audio_timeline_for_stage1,
        voice_blueprints=[voice_blueprint],
        transition_duration_seconds=0.0,
    )

    assert stage1_result.success is True
    assert len(stage1_result.scene_timings) == 1

    # Stage 1's own video-only output must NOT carry the clip's native
    # audio through - confirms the real premise this whole test
    # exists to verify: it has to be pulled back from the ORIGINAL
    # clip file, not from Stage 1's already-audio-stripped output.
    stage1_probe = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            stage1_result.output_file,  # type: ignore[list-item]
        ]
    ).stdout
    assert "audio" not in stage1_probe

    extraction_service = NativeClipAudioExtractionService(
        ffmpeg_path=ffmpeg, ffprobe_path=ffprobe
    )

    native_tracks = extraction_service.extract_native_clip_audio_tracks(
        video_timeline=video_timeline,
        scene_timings=stage1_result.scene_timings,
        output_directory=(tmp_path / "native_audio").as_posix(),
    )

    assert len(native_tracks) == 1
    assert native_tracks[0].track_type == AudioTrackType.NATIVE_CLIP
    assert native_tracks[0].start_time_seconds == 0.0

    full_audio_timeline = AudioTimeline(
        tracks=[narration_track, *native_tracks], sample_rate=48000, channels=2
    )

    # REQ-10(a): native clip audio ON, voiceover OFF - the final mux
    # should carry the clip's own 880Hz tone, never the 220Hz
    # narration tone.
    preferences = AudioInclusionPreferences(
        include_native_clip_audio=True,
        include_voiceover=False,
        include_music=True,
        include_sound_effects=True,
    )

    mux_input_timeline = filter_audio_timeline_for_mux(
        audio_timeline=full_audio_timeline, preferences=preferences
    )

    assert len(mux_input_timeline.tracks) == 1
    assert mux_input_timeline.tracks[0].track_type == AudioTrackType.NATIVE_CLIP

    mux_service = AudioMuxRenderService(
        capability_service=render_service._ffmpeg_capability_service,  # type: ignore[attr-defined]
    )

    stage2_output = tmp_path / "outputs" / "stage2_muxed.mp4"

    stage2_result = mux_service.mux(
        video_only_render_result=stage1_result,
        audio_timeline=mux_input_timeline,
        output_file=stage2_output.as_posix(),
    )

    assert stage2_result.success is True

    final_file = Path(stage2_result.output_file)  # type: ignore[arg-type]
    assert final_file.is_file()

    dominant_hz = _dominant_frequency_hz(ffmpeg=ffmpeg, audio_file=final_file)

    # Real spectral proof, not just "some audio exists": the final
    # muxed file's dominant tone is the clip's own native 880Hz, not
    # narration's 220Hz - confirms this is genuinely the original
    # clip's own audio, correctly carried through the whole chain.
    assert abs(dominant_hz - _NATIVE_TONE_HZ) < 20
    assert abs(dominant_hz - _NARRATION_TONE_HZ) > 100
