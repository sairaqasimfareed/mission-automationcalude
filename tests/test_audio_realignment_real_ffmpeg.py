"""
Voice drift fix, 2026-10-03: real FFmpeg, no mocking of the render. Three real
colour clips (red, green, blue) with the medical genre's real 0.6s crossfades,
and three real voice files laid end to end the way the Audio tab lays them.

The audio is measured in the finished MP4 - when each scene's voice tone
actually starts - and compared with when the picture actually changes to that
scene. Before the fix the voice started early and the error grew with every
scene; after it, each voice starts where its scene starts.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.ffmpeg_config import (
    FFmpegConfig,
    FFmpegHardwareAcceleration,
    FFmpegVideoCodec,
)
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.pipeline.render_stage import RenderPipelineStage
from src.services import audio_realignment_service
from src.services.audio_realignment_service import BASIS_SEQUENTIAL, mark_position_basis
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.genre_timeline_pipeline_service import GenreTimelinePipelineService
from src.services.production_render_service import ProductionRenderService
from tests.test_render_stage import build_context, build_job

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="Real voice-alignment test requires ffmpeg and ffprobe.",
)

_REGISTRY = GenreProfileRegistryService.with_default_profiles()
_TRANSITION = _REGISTRY.resolve(
    "genre.medical"
).profile.editing.default_transition_duration_seconds
_CLIP_SECONDS = 4
_NARRATION_SECONDS = 3.0  # shorter than the clip, like real narration
_COLOURS = ("red", "green", "blue")


def _ffmpeg(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _make_clip(path: Path, colour: str) -> None:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c={colour}:size=320x180:rate=30:duration={_CLIP_SECONDS}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    )


def _make_voice(path: Path) -> None:
    """A 3s file: a 0.4s tone at its very start, then silence."""

    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=0.4",
        "-af",
        f"apad=whole_dur={_NARRATION_SECONDS}",
        "-ar",
        "48000",
        str(path),
    )


def _render(tmp_path: Path) -> Path:
    clips_dir = tmp_path / "clips"
    voice_dir = tmp_path / "voice"
    clips_dir.mkdir()
    voice_dir.mkdir()

    scenes: list[Scene] = []
    clips: list[VideoClip] = []
    tracks: list[AudioTrack] = []
    blueprints: list[ResolvedVoiceBlueprint] = []
    laid_at = 0.0

    for number, colour in enumerate(_COLOURS, start=1):
        clip_file = clips_dir / f"{number}.mp4"
        voice_file = voice_dir / f"{number}.wav"
        _make_clip(clip_file, colour)
        _make_voice(voice_file)

        scenes.append(
            Scene(
                scene_number=number,
                title=f"Scene {number}",
                narration=f"Narration {number}.",
                visual_prompt=f"Visual {number}.",
                estimated_duration_seconds=_CLIP_SECONDS,
                status=SceneStatus.READY,
            )
        )
        clips.append(
            VideoClip(
                scene_number=number,
                source_type=SceneSourceType.MANUAL_UPLOAD,
                duration_seconds=_CLIP_SECONDS,
                prompt=f"s{number}",
                provider="Manual Upload",
                local_file=clip_file.as_posix(),
                resolution="320x180",
                source_status=SceneSourceStatus.READY,
                status=VideoClipStatus.READY,
            )
        )

        track = AudioTrack(
            track_type=AudioTrackType.VOICEOVER,
            source_file=voice_file.as_posix(),
            start_time_seconds=laid_at,  # end to end, as the Audio tab does
            duration_seconds=_NARRATION_SECONDS,
            status=AudioTrackStatus.READY,
            metadata={"scene_number": number},
        )
        mark_position_basis(track, BASIS_SEQUENTIAL)
        tracks.append(track)
        laid_at += _NARRATION_SECONDS

        blueprints.append(
            ResolvedVoiceBlueprint(
                scene_number=number,
                status=VoiceBlueprintResolutionStatus.RESOLVED,
                profile=ResolvedVoiceProfileReference(
                    requested_profile_id="voice.test",
                    resolved_profile_id="voice.test",
                    display_name="Test Voice",
                    found_exact_match=True,
                    used_fallback=False,
                ),
                narration_text=f"Narration {number}.",
                estimated_speech_duration_seconds=_NARRATION_SECONDS,
            )
        )

    timeline = (
        GenreTimelinePipelineService(
            genre_directive_service=GenreDirectiveGenerationService(
                genre_registry=_REGISTRY
            ),
            directive_resolution_service=EditingDirectiveResolutionService(
                effect_registry=EffectRegistryService.with_default_presets()
            ),
        )
        .build(scenes=scenes, clips=clips, genre_id="genre.medical")
        .timeline
    )

    job = build_job()
    job.scenes = scenes
    job.video_clips = clips
    job.video_timeline = timeline
    job.voice_file = tracks[0].source_file
    job.audio_timeline = AudioTimeline(tracks=tracks, sample_rate=48000, channels=2)

    target = tmp_path / "out" / "final.mp4"
    service = ProductionRenderService(
        ffmpeg_config=FFmpegConfig(
            video_codec=FFmpegVideoCodec.LIBX264,
            hardware_acceleration=FFmpegHardwareAcceleration.NONE,
            timeout_seconds=120.0,
        ),
        output_file=target.as_posix(),
    )
    stage = RenderPipelineStage(
        production_render_service=service,
        voice_blueprints=blueprints,
        transition_duration_seconds=_TRANSITION,
        subtitles_enabled=False,
    )

    result = stage.execute(build_context(job))

    assert result.successful, result.errors
    assert target.is_file()

    return target


def _tone_onsets(video: Path) -> list[float]:
    """When each tone starts in the audio, from ffmpeg's silence detector."""

    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(video),
            "-vn",
            "-af",
            "silencedetect=noise=-35dB:d=0.3",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    ends = [float(m) for m in re.findall(r"silence_end: ([0-9.]+)", completed.stderr)]

    # The first tone starts at t=0 (no silence before it). The detector also
    # reports where the final silence ends (the end of the audio) - not a tone.
    return [0.0, *ends][: len(_COLOURS)]


def _picture_change_times(video: Path) -> list[float]:
    """When the picture starts moving to the green and blue scenes."""

    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            "fps=20,scale=4:4,format=rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    frame_size = 4 * 4 * 3
    times: dict[str, float] = {}

    for index in range(len(raw) // frame_size):
        frame = raw[index * frame_size : (index + 1) * frame_size]
        pixels = [frame[i : i + 3] for i in range(0, frame_size, 3)]
        red = sum(p[0] for p in pixels) / len(pixels)
        green = sum(p[1] for p in pixels) / len(pixels)
        blue = sum(p[2] for p in pixels) / len(pixels)
        at = index / 20.0

        if "green" not in times and green > 25:
            times["green"] = at

        if (
            "blue" not in times
            and blue > 25
            and green < 200
            and at > times.get("green", 0)
        ):
            times["blue"] = at

        del red

    return [0.0, times["green"], times["blue"]]


def test_each_voice_starts_where_its_scene_starts_in_the_real_render(
    tmp_path: Path,
) -> None:
    video = _render(tmp_path)

    onsets = _tone_onsets(video)
    scene_starts = _picture_change_times(video)

    assert len(onsets) == 3
    for onset, start in zip(onsets, scene_starts, strict=True):
        # A fade begins at the scene start; the detector sees it a frame or
        # two later, so allow a small margin.
        assert onset == pytest.approx(start, abs=0.25)


def test_without_the_fix_the_voice_is_visibly_off_in_the_same_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the test measures something: with realignment disabled the voice
    sits where the Audio tab laid it (0, 3.0, 6.0) and the later scenes miss
    their picture by the accumulated crossfade overlap."""

    monkeypatch.setattr(
        "src.pipeline.render_stage.realign_audio_to_scene_timings",
        lambda *args, **kwargs: 0,
    )
    assert audio_realignment_service.realign_audio_to_scene_timings is not None

    video = _render(tmp_path)

    onsets = _tone_onsets(video)
    scene_starts = _picture_change_times(video)
    errors = [abs(o - s) for o, s in zip(onsets, scene_starts, strict=True)]

    assert errors[0] < 0.25
    assert errors[2] > 0.5  # scene 3: two crossfades of drift (~1.2s)
