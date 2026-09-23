"""
REQ-12 (top10 countdown rank cards), 2026-09-23: real, end-to-end
chained verification - Top10CountdownService.build() driving the REAL
TopTenRankCardRenderService and ProductionRenderService.
render_top10_countdown() (genuine FFmpeg execution throughout), with
fake image/voiceover generation standing in only for the paid LLM/
image/voice generation calls (so this test never needs real API keys
or spends real money) - matching OpeningTitleCardService's own real-
FFmpeg test precedent (REQ-4) and this session's established
discipline of proving every REQ-12 piece works TOGETHER, not just in
isolation, before considering the feature done.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.editing_directives import DirectiveIntensity
from src.models.enums import Platform
from src.models.genre_profile import GenreSEOProfile, GenreThumbnailProfile
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
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.models.voice_generation import VoiceGenerationResult, VoiceGenerationStatus
from src.services.seo.seo_context_builder import SEOContext
from src.services.top10_countdown_service import Top10CountdownService

_WIDTH = 640
_HEIGHT = 360
_FRAME_RATE = 30
_SCENE_DURATION_SECONDS = 2
_VOICEOVER_DURATION_SECONDS = 1.0


class _FakeImageGenerationService:
    """Stands in for the real LLM concept + AI image generation calls
    - returns a real, already-created image file rather than spending
    real money in a test."""

    def __init__(self, *, image_file: str) -> None:
        self._image_file = image_file

    def generate(
        self,
        context: SEOContext,
        *,
        width: int,
        height: int,
        selected_seo_title: str | None = None,
    ) -> str:
        return self._image_file


class _FakeNumberingVoiceoverService:
    """Stands in for the real voice-directive-resolution + TTS
    generation calls - returns a real, already-created short audio
    file (wrapped in a genuine VoiceGenerationResult/AudioTrack) so
    the real rank-card render still mixes in a real audio stream."""

    def __init__(self, *, voiceover_file: str) -> None:
        self._voiceover_file = voiceover_file

    def generate(
        self,
        *,
        rank: int,
        voice_profile_id: str,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        return VoiceGenerationResult(
            success=True,
            scene_number=rank,
            status=VoiceGenerationStatus.COMPLETED,
            provider="fake-numbering-voice-fixture",
            output_file=self._voiceover_file,
            audio_track=AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file=self._voiceover_file,
                start_time_seconds=0.0,
                duration_seconds=_VOICEOVER_DURATION_SECONDS,
                volume=1.0,
                provider="fake-numbering-voice-fixture",
                status=AudioTrackStatus.READY,
                metadata={"scene_number": rank},
            ),
        )


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real top10 countdown smoke requires ffmpeg/ffprobe.")

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


def _create_source_audio(
    *, ffmpeg: str, output_file: Path, duration: float = _SCENE_DURATION_SECONDS
) -> None:
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
            f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-c:a",
            "pcm_s16le",
            output_file.as_posix(),
        ]
    )


def _create_background_image(*, ffmpeg: str, output_file: Path) -> None:
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
            directive_path="genre_preset_id", preset_id="genre.top10"
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
        prompt=f"Top10 countdown service real smoke, scene {scene_number}.",
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


def _seo_context() -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic="Top 10 real countdown smoke test items.",
        niche="top10",
        genre_id="genre.top10",
        target_audience="General audience.",
        target_country="US",
        language="English",
        language_code="en",
        platform=Platform.YOUTUBE,
        script_title="Top 10 Real Countdown Smoke",
        script_content="Full narration text.",
        research_summary="Real research summary.",
        key_facts=["Fact one."],
        scene_count=2,
        estimated_duration_seconds=int(2 * _SCENE_DURATION_SECONDS),
        genre_seo_profile=GenreSEOProfile(),
        genre_thumbnail_profile=GenreThumbnailProfile(),
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


def test_real_countdown_service_end_to_end_produces_one_spliced_final_file(
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

    background = tmp_path / "shared_rank_background.png"
    _create_background_image(ffmpeg=ffmpeg, output_file=background)

    numbering_voiceover = tmp_path / "numbering_voiceover.wav"
    _create_source_audio(
        ffmpeg=ffmpeg,
        output_file=numbering_voiceover,
        duration=_VOICEOVER_DURATION_SECONDS,
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

    scenes = [
        Scene(
            scene_number=1,
            title="Hook",
            narration="Welcome to the countdown.",
            visual_prompt="An establishing hook shot.",
            estimated_duration_seconds=_SCENE_DURATION_SECONDS,
            status=SceneStatus.READY,
            list_rank=None,
        ),
        Scene(
            scene_number=2,
            title="Rank ten item",
            narration="Number ten on our list.",
            visual_prompt="A dramatic reveal shot.",
            estimated_duration_seconds=_SCENE_DURATION_SECONDS,
            status=SceneStatus.READY,
            list_rank=10,
        ),
    ]

    output_file = tmp_path / "final_countdown_service.mp4"

    service = Top10CountdownService(
        image_generation_service=_FakeImageGenerationService(  # type: ignore[arg-type]
            image_file=background.as_posix()
        ),
        numbering_voiceover_service=_FakeNumberingVoiceoverService(  # type: ignore[arg-type]
            voiceover_file=numbering_voiceover.as_posix()
        ),
    )

    result = service.build(
        scenes=scenes,
        video_timeline=video_timeline,
        audio_timeline=audio_timeline,
        voice_blueprints=[
            _voice_blueprint(scene_number=1),
            _voice_blueprint(scene_number=2),
        ],
        seo_context=_seo_context(),
        voice_profile_id="voice.ffmpeg_smoke",
        output_file=output_file.as_posix(),
        width=_WIDTH,
        height=_HEIGHT,
        frame_rate=float(_FRAME_RATE),
    )

    assert result.success is True

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

    assert rendered_file.is_file()

    # Real proof this is one genuinely spliced file, not just "some
    # file exists": both streams must span hook + card + ranked scene,
    # the same "audio silently stops at a segment boundary" class of
    # bug _concat_chunks()'s own docstring already documents finding
    # once for chunked rendering.
    video_duration = _stream_duration_seconds(
        ffprobe=ffprobe, output_file=rendered_file, codec_type="video"
    )
    audio_duration = _stream_duration_seconds(
        ffprobe=ffprobe, output_file=rendered_file, codec_type="audio"
    )

    minimum_expected_seconds = 2 * _SCENE_DURATION_SECONDS + _VOICEOVER_DURATION_SECONDS

    assert video_duration >= minimum_expected_seconds - 0.5
    assert audio_duration >= minimum_expected_seconds - 0.5


def test_missing_rank_raises_before_generating_or_rendering_anything(
    tmp_path: Path,
) -> None:
    scenes = [
        Scene(
            scene_number=1,
            title="Hook",
            narration="Welcome.",
            visual_prompt="A hook shot.",
            estimated_duration_seconds=_SCENE_DURATION_SECONDS,
            status=SceneStatus.READY,
            list_rank=None,
        )
    ]

    service = Top10CountdownService(
        image_generation_service=_FakeImageGenerationService(  # type: ignore[arg-type]
            image_file="unused.png"
        ),
        numbering_voiceover_service=_FakeNumberingVoiceoverService(  # type: ignore[arg-type]
            voiceover_file="unused.wav"
        ),
    )

    try:
        service.build(
            scenes=scenes,
            video_timeline=VideoTimeline(clips=[], items=[]),
            audio_timeline=AudioTimeline(tracks=[]),
            voice_blueprints=[],
            seo_context=_seo_context(),
            voice_profile_id="voice.ffmpeg_smoke",
            output_file=(tmp_path / "unused.mp4").as_posix(),
        )

        raise AssertionError("Expected a ValueError for zero ranked scenes.")
    except ValueError as error:
        assert "list_rank" in str(error)
