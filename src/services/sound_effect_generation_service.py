from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.resolved_editing_blueprint import ResolvedSoundEffectInstruction
from src.models.sound_effect_generation import (
    SoundEffectGenerationFailure,
    SoundEffectGenerationResult,
    SoundEffectGenerationStatus,
)
from src.providers.sound_effect_provider import SoundEffectProvider

_SUPPORTED_OUTPUT_FORMATS = {".mp3", ".wav", ".aac", ".ogg", ".flac"}

# Sound-effect presets describe a short one-shot cue (a "whoosh" or a
# "sting"), not a track with its own duration - ResolvedSoundEffectInstruction
# has no duration field, and generate_sound_effect() has no way to
# request a specific length from the provider either, so this is the
# fallback used only when the real generated file's duration cannot
# be measured (see _detect_duration_seconds).
DEFAULT_CUE_DURATION_SECONDS = 2.0

_PROBE_COMMAND_TIMEOUT_SECONDS = 30.0


def _run_ffprobe(command: list[str]) -> str:
    """Real ffprobe invocation - the default `ffprobe_runner` implementation."""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_PROBE_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "ffprobe command failed: "
            + " ".join(command)
            + (f"\n{completed.stderr.strip()}" if completed.stderr else "")
        )

    return completed.stdout


class SoundEffectGenerationService:
    """
    Generate one short sound-effect clip from a resolved sound-effect
    instruction.

    Provider-independent, matching VoiceGenerationService/
    MusicGenerationService's shape.
    """

    def __init__(
        self,
        *,
        providers: list[SoundEffectProvider],
        ffprobe_path: str = "ffprobe",
        ffprobe_runner: Callable[[list[str]], str] | None = None,
    ) -> None:
        self.providers = providers
        self.ffprobe_path = ffprobe_path
        self._ffprobe_runner = ffprobe_runner or _run_ffprobe

    def generate(
        self,
        instruction: ResolvedSoundEffectInstruction,
        *,
        scene_number: int,
        start_time_seconds: float,
        provider_name: str | None = None,
    ) -> SoundEffectGenerationResult:
        """Generate one sound-effect cue and return an audio track."""

        if start_time_seconds < 0:
            return self._fail(
                scene_number=scene_number,
                reason="invalid_start_time",
                message="Sound-effect cue start time cannot be negative.",
            )

        provider = self._select_provider(preferred_provider=provider_name)

        if provider is None:
            return self._fail(
                scene_number=scene_number,
                reason="no_provider_available",
                message="No compatible sound-effect provider is available.",
            )

        try:
            provider_healthy = provider.health_check()
        except Exception as exc:
            return self._fail(
                scene_number=scene_number,
                reason="provider_unhealthy",
                message="Sound-effect provider health check failed.",
                provider=provider.provider_name,
                metadata={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        if not provider_healthy:
            return self._fail(
                scene_number=scene_number,
                reason="provider_unhealthy",
                message="Selected sound-effect provider is unhealthy.",
                provider=provider.provider_name,
            )

        library_query = self._resolve_library_query(instruction)

        try:
            output_file = provider.generate_sound_effect(library_query=library_query)
        except Exception as exc:
            return self._fail(
                scene_number=scene_number,
                reason="provider_error",
                message="Sound-effect provider failed during generation.",
                provider=provider.provider_name,
                metadata={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        cleaned_output_file = (
            output_file.strip() if isinstance(output_file, str) else ""
        )

        if not cleaned_output_file:
            return self._fail(
                scene_number=scene_number,
                reason="empty_output_path",
                message="Sound-effect provider returned an empty output file path.",
                provider=provider.provider_name,
            )

        normalized_output_file = Path(cleaned_output_file).as_posix()
        output_suffix = Path(normalized_output_file).suffix.lower()

        if output_suffix not in _SUPPORTED_OUTPUT_FORMATS:
            return self._fail(
                scene_number=scene_number,
                reason="unsupported_output_format",
                message=(
                    "Sound-effect provider returned an unsupported " "audio format."
                ),
                provider=provider.provider_name,
                metadata={"output_file": normalized_output_file},
            )

        # Real-world finding: generate_sound_effect() has no way to
        # request a specific duration, so the real file's actual
        # length was always unknown - the fixed 2.0s label was just
        # assumed regardless of what the provider actually produced,
        # a real mismatch that can make a cue feel out of sync with
        # whatever it was meant to accompany. Measuring the real file
        # directly removes the guess; a measurement failure falls
        # back to the old fixed-length behavior with a warning.
        measured_duration_seconds = self._detect_duration_seconds(
            Path(normalized_output_file)
        )

        warnings: list[str] = []

        if measured_duration_seconds is not None and measured_duration_seconds > 0.0:
            resolved_duration_seconds = measured_duration_seconds
        else:
            resolved_duration_seconds = DEFAULT_CUE_DURATION_SECONDS

            warnings.append(
                "Could not measure the real generated sound-effect "
                "duration; used a fixed 2.0s fallback instead, which "
                "can make this cue feel out of sync with the audio."
            )

        audio_track = AudioTrack(
            track_type=AudioTrackType.SOUND_EFFECT,
            source_file=normalized_output_file,
            start_time_seconds=start_time_seconds,
            duration_seconds=resolved_duration_seconds,
            volume=instruction.volume_percent / 100.0,
            loop_enabled=False,
            # Real-world finding: this was hardcoded False,
            # unconditionally, with no directive able to override it -
            # unlike background music, which already ducks correctly.
            # A real render with several SFX cues per scene buried the
            # narration under them. instruction.duck_under_voice now
            # carries the real per-cue directive (default True).
            duck_under_voice=instruction.duck_under_voice,
            provider=provider.provider_name,
            license_type="library",
            status=AudioTrackStatus.READY,
            metadata={
                "scene_number": scene_number,
                "resolved_preset_id": instruction.preset.resolved_preset_id,
                "library_query": library_query,
                "measured_duration_seconds": measured_duration_seconds,
                "timing_mode": instruction.timing_mode.value,
                "intensity": instruction.intensity.value,
            },
        )

        return SoundEffectGenerationResult(
            success=True,
            scene_number=scene_number,
            status=SoundEffectGenerationStatus.COMPLETED,
            provider=provider.provider_name,
            output_file=normalized_output_file,
            audio_track=audio_track,
            warnings=warnings,
        )

    def _detect_duration_seconds(
        self,
        file_path: Path,
    ) -> float | None:
        """Return the real, measured duration of a generated audio file."""

        try:
            raw_output = self._ffprobe_runner(
                [
                    self.ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(file_path),
                ]
            )
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return None

        cleaned = raw_output.strip()

        if not cleaned:
            return None

        try:
            return float(cleaned.splitlines()[0].strip())
        except (ValueError, IndexError):
            return None

    def _select_provider(
        self,
        *,
        preferred_provider: str | None,
    ) -> SoundEffectProvider | None:
        """Select a requested or first healthy provider."""

        if preferred_provider is not None:
            normalized_preference = preferred_provider.strip().lower()

            for provider in self.providers:
                if provider.provider_name.strip().lower() == normalized_preference:
                    return provider

            return None

        for provider in self.providers:
            try:
                if provider.health_check():
                    return provider
            except Exception:
                continue

        return None

    @staticmethod
    def _resolve_library_query(instruction: ResolvedSoundEffectInstruction) -> str:
        query = instruction.preset.implementation.get("library_query")

        if isinstance(query, str) and query.strip():
            return query.strip()

        return instruction.preset.resolved_preset_id

    @staticmethod
    def _fail(
        *,
        scene_number: int,
        reason: str,
        message: str,
        provider: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> SoundEffectGenerationResult:
        return SoundEffectGenerationResult(
            success=False,
            scene_number=scene_number,
            status=SoundEffectGenerationStatus.FAILED,
            provider=provider,
            failure=SoundEffectGenerationFailure(
                reason=reason,
                message=message,
                provider=provider,
            ),
            metadata=metadata or {},
        )
