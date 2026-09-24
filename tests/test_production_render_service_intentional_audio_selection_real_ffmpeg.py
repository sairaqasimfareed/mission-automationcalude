"""
REQ-13 real gap, found and fixed 2026-09-24: real, non-mocked proof
that ProductionRenderService.render()'s new audio_selection_is_
intentional parameter actually fixes the live crash - before this fix,
RenderPipelineStage's real, production call chain would raise a
ValueError from MasterEditPlanService.validate_render_ready() any time
the REQ-13-filtered audio_timeline ended up with zero tracks (every
mux-time toggle off) or simply no VOICEOVER track (include_voiceover
toggled off alone), even though AudioInclusionPreferences' own
docstring says this is meant to be a legitimate, deliberate mux-time
choice, not an incomplete-generation error.

Proves both halves: the OLD strict default behavior is completely
unchanged for every existing caller (audio_selection_is_intentional
omitted still raises exactly as before), and the NEW True path
genuinely renders real, silent (or partial-audio) video successfully
where it previously crashed outright.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

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


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError(
            "Intentional audio selection real smoke requires ffmpeg/ffprobe."
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


def _editing_blueprint() -> ResolvedSceneEditingBlueprint:
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
            enabled=False,
            burn_into_video=False,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
    )


def _video_timeline(*, source_file: Path) -> VideoTimeline:
    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=_SCENE_DURATION_SECONDS,
        prompt="Intentional audio selection real smoke.",
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
        editing_blueprint=_editing_blueprint(),
    )

    return VideoTimeline(
        clips=[clip],
        items=[item],
        output_resolution=f"{_WIDTH}x{_HEIGHT}",
        frame_rate=_FRAME_RATE,
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
        narration_text="Unused - subtitles are disabled for this fixture.",
    )


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


def test_default_strict_behavior_still_rejects_empty_audio_timeline(
    tmp_path: Path,
) -> None:
    """
    audio_selection_is_intentional omitted (every prior real caller's
    exact behavior) must still refuse an empty audio_timeline - the
    strict default is deliberately unchanged.
    """

    ffmpeg, _ffprobe = _require_ffmpeg()

    source_video = tmp_path / "source.mp4"
    _create_source_video(ffmpeg=ffmpeg, output_file=source_video)

    service = ProductionRenderService()

    with pytest.raises(ValueError, match="not ready for rendering"):
        service.render(
            video_timeline=_video_timeline(source_file=source_video),
            audio_timeline=AudioTimeline(),
            voice_blueprints=[_voice_blueprint()],
            output_file=(tmp_path / "should_not_render.mp4").as_posix(),
            include_subtitles=False,
        )


def test_intentional_empty_audio_selection_renders_a_real_silent_video(
    tmp_path: Path,
) -> None:
    """
    The real fix: audio_selection_is_intentional=True with a genuinely
    empty audio_timeline (every REQ-13 mux-time toggle off) must
    succeed and produce a real video with zero audio streams - the
    exact scenario that crashed RenderPipelineStage's fallback call
    before this fix.
    """

    ffmpeg, ffprobe = _require_ffmpeg()

    source_video = tmp_path / "source.mp4"
    _create_source_video(ffmpeg=ffmpeg, output_file=source_video)

    service = ProductionRenderService()

    result = service.render(
        video_timeline=_video_timeline(source_file=source_video),
        audio_timeline=AudioTimeline(),
        voice_blueprints=[_voice_blueprint()],
        output_file=(tmp_path / "silent.mp4").as_posix(),
        include_subtitles=False,
        audio_selection_is_intentional=True,
    )

    assert result.success is True

    output_file = Path(result.output_file)  # type: ignore[arg-type]
    assert output_file.is_file()

    streams = _probe_stream_types(ffprobe=ffprobe, video_file=output_file)
    assert "codec_type=video" in streams
    assert "codec_type=audio" not in streams


def test_intentional_voiceoverless_selection_with_real_music_renders(
    tmp_path: Path,
) -> None:
    """
    The partial case: include_voiceover=False but include_music=True
    (a real BACKGROUND_MUSIC track present, no VOICEOVER track at
    all) - audio_selection_is_intentional=True must still succeed and
    the real music track must genuinely reach the output.
    """

    ffmpeg, ffprobe = _require_ffmpeg()

    source_video = tmp_path / "source.mp4"
    _create_source_video(ffmpeg=ffmpeg, output_file=source_video)

    source_music = tmp_path / "music.wav"
    _create_source_audio(ffmpeg=ffmpeg, output_file=source_music)

    service = ProductionRenderService()

    music_only_timeline = AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.BACKGROUND_MUSIC,
                source_file=source_music.as_posix(),
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

    result = service.render(
        video_timeline=_video_timeline(source_file=source_video),
        audio_timeline=music_only_timeline,
        voice_blueprints=[_voice_blueprint()],
        output_file=(tmp_path / "music_only.mp4").as_posix(),
        include_subtitles=False,
        audio_selection_is_intentional=True,
    )

    assert result.success is True

    output_file = Path(result.output_file)  # type: ignore[arg-type]
    assert output_file.is_file()

    streams = _probe_stream_types(ffprobe=ffprobe, video_file=output_file)
    assert "codec_type=video" in streams
    assert "codec_type=audio" in streams
