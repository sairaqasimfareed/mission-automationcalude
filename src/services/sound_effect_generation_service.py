from __future__ import annotations

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
# has no duration field, so every cue uses this fixed clip length.
DEFAULT_CUE_DURATION_SECONDS = 2.0


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
    ) -> None:
        self.providers = providers

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

        audio_track = AudioTrack(
            track_type=AudioTrackType.SOUND_EFFECT,
            source_file=normalized_output_file,
            start_time_seconds=start_time_seconds,
            duration_seconds=DEFAULT_CUE_DURATION_SECONDS,
            volume=instruction.volume_percent / 100.0,
            loop_enabled=False,
            duck_under_voice=False,
            provider=provider.provider_name,
            license_type="library",
            status=AudioTrackStatus.READY,
            metadata={
                "scene_number": scene_number,
                "resolved_preset_id": instruction.preset.resolved_preset_id,
                "library_query": library_query,
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
        )

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
