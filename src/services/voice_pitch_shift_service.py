from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from src.models.voice_pitch_shift import VoicePitchShiftResult

_COMMAND_TIMEOUT_SECONDS = 60.0

# FFmpeg's atempo filter only accepts a factor in [0.5, 2.0] per
# instance - real, documented FFmpeg constraint, stable across
# versions. A pitch_adjustment at the extremes of ResolvedVoiceBlueprint's
# own -20..+20 semitone range needs a tempo-correction factor outside
# that window, so _build_atempo_chain() chains multiple atempo filters
# to reach it, exactly as FFmpeg's own documentation recommends for
# this case.
_ATEMPO_MIN_FACTOR = 0.5
_ATEMPO_MAX_FACTOR = 2.0


def _run_ffprobe(command: list[str]) -> str:
    """Real ffprobe invocation - the default `ffprobe_runner` implementation."""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "ffprobe command failed: "
            + " ".join(command)
            + (f"\n{completed.stderr.strip()}" if completed.stderr else "")
        )

    return completed.stdout


def _run_ffmpeg(command: list[str]) -> str:
    """Real ffmpeg invocation - the default `ffmpeg_runner` implementation."""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "ffmpeg command failed: "
            + " ".join(command)
            + (f"\n{completed.stderr.strip()}" if completed.stderr else "")
        )

    return completed.stdout


class VoicePitchShiftService:
    """
    Real FFmpeg-based pitch shifting for already-generated voice audio.

    Voice gap #3 (2026-09-09 audit): ElevenLabs has no pitch control
    at all, on any model - confirmed against ElevenLabs' own API
    documentation earlier this session. The only real path is FFmpeg
    post-processing on the rendered audio file, which is what this
    service does.

    Uses the standard, well-established FFmpeg technique for a
    pitch-only shift using only core filters (asetrate + aresample +
    atempo) - no optional library (e.g. librubberband) required, so
    this works with an ordinary bundled or PATH FFmpeg build rather
    than depending on a specific compile-time option. asetrate changes
    both pitch and playback speed together; atempo then corrects the
    speed back to normal while the pitch stays shifted. This is an
    honest tradeoff, not a studio-grade pitch shifter: atempo
    time-stretches the corrected audio, which can introduce mild
    artifacts for a large shift - documented here rather than
    silently assumed to be transparent.

    `pitch_adjustment`'s unit is treated as semitones - the natural,
    musically-meaningful unit for its -20..+20 range - though this is
    not explicitly documented anywhere else in this codebase's
    existing ResolvedVoiceBlueprint.pitch_adjustment field; flagged
    here as an assumption, not asserted as certain.

    Output is written to a staged `<name>.part<ext>` path and only
    promoted via atomic `Path.replace()` on genuine success, mirroring
    ProductionRenderService's own established staged-output pattern
    exactly - a crash or failure mid-write can never leave a corrupt
    or partial file at the path a caller would treat as finished.
    """

    def __init__(
        self,
        *,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
        ffmpeg_runner: Callable[[list[str]], str] | None = None,
        ffprobe_runner: Callable[[list[str]], str] | None = None,
    ) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self._ffmpeg_runner = ffmpeg_runner or _run_ffmpeg
        self._ffprobe_runner = ffprobe_runner or _run_ffprobe

    def apply(
        self,
        input_file: Path,
        *,
        semitones: float,
        output_file: Path | None = None,
    ) -> VoicePitchShiftResult:
        """
        Apply a real pitch shift to input_file, in semitones.

        semitones == 0.0 is a real no-op - returns success with
        skipped=True and output_file unchanged, never invoking FFmpeg
        for a shift that would do nothing.

        output_file defaults to input_file (in-place replacement,
        staged then atomically promoted) - the common case for a
        post-process step run right after voice generation.
        """

        target_output = output_file or input_file

        if semitones == 0.0:
            return VoicePitchShiftResult(
                success=True,
                output_file=str(input_file),
                applied_semitones=0.0,
                skipped=True,
            )

        if not input_file.exists() or not input_file.is_file():
            return VoicePitchShiftResult(
                success=False,
                applied_semitones=semitones,
                error_message=(f"Input audio file does not exist: {input_file}"),
            )

        try:
            sample_rate = self._detect_sample_rate(input_file)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            return VoicePitchShiftResult(
                success=False,
                applied_semitones=semitones,
                error_message=f"Could not determine input sample rate: {error}",
            )

        if sample_rate is None:
            return VoicePitchShiftResult(
                success=False,
                applied_semitones=semitones,
                error_message=(
                    "ffprobe did not report a usable audio sample rate for "
                    f"{input_file}."
                ),
            )

        pitch_ratio = 2.0 ** (semitones / 12.0)
        target_sample_rate = round(sample_rate * pitch_ratio)
        tempo_correction_factor = 1.0 / pitch_ratio

        audio_filter = ",".join(
            [
                f"asetrate={target_sample_rate}",
                f"aresample={sample_rate}",
                *_build_atempo_chain(tempo_correction_factor),
            ]
        )

        staging_path = target_output.with_name(
            f"{target_output.stem}.part{target_output.suffix}"
        )

        command = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(input_file),
            "-filter:a",
            audio_filter,
            str(staging_path),
        ]

        try:
            self._ffmpeg_runner(command)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            self._cleanup_staging_file(staging_path)

            return VoicePitchShiftResult(
                success=False,
                applied_semitones=semitones,
                error_message=f"FFmpeg pitch-shift failed: {error}",
                command=command,
            )

        if not staging_path.exists() or staging_path.stat().st_size <= 0:
            self._cleanup_staging_file(staging_path)

            return VoicePitchShiftResult(
                success=False,
                applied_semitones=semitones,
                error_message=(
                    "FFmpeg exited successfully but produced no usable "
                    "staged output file."
                ),
                command=command,
            )

        staging_path.replace(target_output)

        return VoicePitchShiftResult(
            success=True,
            output_file=str(target_output),
            applied_semitones=semitones,
            command=command,
        )

    def _detect_sample_rate(self, input_file: Path) -> int | None:
        raw_output = self._ffprobe_runner(
            [
                self.ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate",
                "-of",
                "csv=p=0",
                str(input_file),
            ]
        )

        cleaned = raw_output.strip()

        if not cleaned:
            return None

        try:
            return int(cleaned.splitlines()[0].strip())
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _cleanup_staging_file(staging_path: Path) -> None:
        try:
            staging_path.unlink(missing_ok=True)
        except OSError:
            pass


def _build_atempo_chain(factor: float) -> list[str]:
    """
    Chain atempo filters to reach an arbitrary positive factor.

    FFmpeg's atempo filter only accepts [0.5, 2.0] per instance - a
    real, documented, stable FFmpeg constraint. Chaining multiple
    atempo filters (each within range) to reach a factor outside it is
    FFmpeg's own documented recommendation for this exact case.
    """

    if factor <= 0.0:
        raise ValueError("Tempo-correction factor must be positive.")

    filters: list[str] = []
    remaining = factor

    while remaining < _ATEMPO_MIN_FACTOR:
        filters.append(f"atempo={_ATEMPO_MIN_FACTOR}")
        remaining /= _ATEMPO_MIN_FACTOR

    while remaining > _ATEMPO_MAX_FACTOR:
        filters.append(f"atempo={_ATEMPO_MAX_FACTOR}")
        remaining /= _ATEMPO_MAX_FACTOR

    filters.append(f"atempo={remaining:.6f}")

    return filters
