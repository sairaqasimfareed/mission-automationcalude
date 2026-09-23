"""
REQ-3 (cinematic letterboxing), 2026-09-22: real, non-mocked FFmpeg
proof that letterbox_enabled=True on ProductionRenderService.
render_video_only() actually produces black bars in the real rendered
pixels - a genuine visual result, not just "the filter_complex string
contains crop/pad". Uses testsrc2 (a colorful, never-black test
pattern) as the source so any black strip found in the output is
provably injected by the letterbox step itself, not already present.
"""

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
from src.services.production_render_service import ProductionRenderService

_DURATION_SECONDS = 2
_WIDTH = 1920
_HEIGHT = 1080
_FRAME_RATE = 30

# floor(1920 / 2.35) = 817, rounded down to even = 816,
# bar_height = (1080 - 816) // 2 = 132 - hand-verified, matches
# test_filter_graph_builder_letterbox.py's own unit-tested math.
_EXPECTED_BAR_HEIGHT = 132


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("Real letterbox smoke requires ffmpeg and ffprobe.")

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


def _video_timeline(source_file: Path) -> VideoTimeline:
    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=_DURATION_SECONDS,
        prompt="Real REQ-3 letterbox smoke.",
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
        end_time_seconds=float(_DURATION_SECONDS),
        track_index=0,
        layer_index=0,
        enabled=True,
        editing_blueprint=_editing_blueprint(1),
    )

    return VideoTimeline(
        clips=[clip],
        items=[item],
        output_resolution=f"{_WIDTH}x{_HEIGHT}",
        frame_rate=_FRAME_RATE,
    )


def _audio_timeline() -> AudioTimeline:
    return AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file="unused.wav",
                start_time_seconds=0.0,
                duration_seconds=float(_DURATION_SECONDS),
                status=AudioTrackStatus.READY,
                metadata={"scene_number": 1},
            )
        ]
    )


def _voice_blueprint() -> ResolvedVoiceBlueprint:
    return ResolvedVoiceBlueprint(
        scene_number=1,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.letterbox_smoke",
            resolved_profile_id="voice.letterbox_smoke",
            display_name="Letterbox Smoke Voice",
            found_exact_match=True,
            used_fallback=False,
        ),
        narration_text="Real REQ-3 letterbox smoke narration.",
    )


def _extract_frame(*, ffmpeg: str, video_file: Path, out: Path) -> None:
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            video_file.as_posix(),
            "-vframes",
            "1",
            "-pix_fmt",
            "gray",
            out.as_posix(),
        ]
    )


def _read_pgm_grayscale_pixels(pgm_file: Path) -> list[int]:
    data = pgm_file.read_bytes()

    assert data[:2] == b"P5", "Expected a raw grayscale (P5) PGM file."

    index = 2
    tokens_found = 0
    token_start: int | None = None

    while tokens_found < 3:
        char = data[index : index + 1]

        if char.isspace():
            if token_start is not None:
                tokens_found += 1
                token_start = None
        elif token_start is None:
            token_start = index

        index += 1

    return list(data[index:])


def test_real_letterbox_render_produces_actual_black_bars(tmp_path: Path) -> None:
    ffmpeg, ffprobe = _require_ffmpeg()

    source_video = tmp_path / "inputs" / "scene_001.mp4"

    _create_source_video(ffmpeg=ffmpeg, output_file=source_video)

    output_file = tmp_path / "outputs" / "letterbox_smoke.mp4"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    service = ProductionRenderService(
        ffmpeg_config=FFmpegConfig(
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            video_codec=FFmpegVideoCodec.LIBX264,
            hardware_acceleration=FFmpegHardwareAcceleration.NONE,
            timeout_seconds=60.0,
        ),
        output_file=output_file.as_posix(),
    )

    result = service.render_video_only(
        video_timeline=_video_timeline(source_video),
        audio_timeline=_audio_timeline(),
        voice_blueprints=[_voice_blueprint()],
        letterbox_enabled=True,
    )

    assert result.success is True

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

    assert rendered_file.is_file()

    frame_file = tmp_path / "frame.pgm"

    _extract_frame(ffmpeg=ffmpeg, video_file=rendered_file, out=frame_file)

    pixels = _read_pgm_grayscale_pixels(frame_file)

    assert len(pixels) == _WIDTH * _HEIGHT

    def _row_average(y: int) -> float:
        row = pixels[y * _WIDTH : (y + 1) * _WIDTH]

        return sum(row) / len(row)

    # Real black bars at the true top/bottom rows (comfortably inside
    # the expected ~132px bar).
    assert _row_average(5) < 8
    assert _row_average(_HEIGHT - 6) < 8

    # Real, un-barred content at the vertical center - testsrc2 is
    # never black, so a bright center proves this is genuine matting
    # (top/bottom only), not a uniformly darkened frame.
    assert _row_average(_HEIGHT // 2) > 40

    # The boundary between bar and content should sit close to the
    # hand-verified 132px bar height (some codec/filter slack allowed).
    just_inside_bar = _row_average(_EXPECTED_BAR_HEIGHT - 5)
    just_outside_bar = _row_average(_EXPECTED_BAR_HEIGHT + 5)

    assert just_inside_bar < 8
    assert just_outside_bar > just_inside_bar


def test_real_letterbox_disabled_has_no_black_bars(tmp_path: Path) -> None:
    """Backward-compat control: the exact same source, disabled
    (default) letterbox, must have no black bars at all - a bright top
    row, proving this REQ changes nothing when not opted into."""

    ffmpeg, ffprobe = _require_ffmpeg()

    source_video = tmp_path / "inputs" / "scene_001.mp4"

    _create_source_video(ffmpeg=ffmpeg, output_file=source_video)

    output_file = tmp_path / "outputs" / "no_letterbox_smoke.mp4"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    service = ProductionRenderService(
        ffmpeg_config=FFmpegConfig(
            ffmpeg_path=ffmpeg,
            ffprobe_path=ffprobe,
            video_codec=FFmpegVideoCodec.LIBX264,
            hardware_acceleration=FFmpegHardwareAcceleration.NONE,
            timeout_seconds=60.0,
        ),
        output_file=output_file.as_posix(),
    )

    result = service.render_video_only(
        video_timeline=_video_timeline(source_video),
        audio_timeline=_audio_timeline(),
        voice_blueprints=[_voice_blueprint()],
    )

    assert result.success is True

    rendered_file = Path(result.output_file)  # type: ignore[arg-type]

    frame_file = tmp_path / "frame.pgm"

    _extract_frame(ffmpeg=ffmpeg, video_file=rendered_file, out=frame_file)

    pixels = _read_pgm_grayscale_pixels(frame_file)

    def _row_average(y: int) -> float:
        row = pixels[y * _WIDTH : (y + 1) * _WIDTH]

        return sum(row) / len(row)

    assert _row_average(5) > 40
