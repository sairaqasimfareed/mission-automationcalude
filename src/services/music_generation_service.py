from __future__ import annotations

from pathlib import Path

from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.music_generation import (
    MusicGenerationFailure,
    MusicGenerationResult,
    MusicGenerationStatus,
)
from src.models.resolved_editing_blueprint import ResolvedMusicInstruction
from src.providers.music_provider import MusicProvider

_SUPPORTED_OUTPUT_FORMATS = {".mp3", ".wav", ".aac", ".ogg", ".flac"}


class MusicGenerationService:
    """
    Generate one whole-video background-music track from a resolved
    music instruction.

    Provider-independent, matching VoiceGenerationService's shape:
    real licensed-library-search or generative-music adapters can
    implement the existing MusicProvider interface.
    """

    def __init__(
        self,
        *,
        providers: list[MusicProvider],
    ) -> None:
        self.providers = providers

    def generate(
        self,
        instruction: ResolvedMusicInstruction,
        *,
        duration_seconds: float,
        provider_name: str | None = None,
    ) -> MusicGenerationResult:
        """Generate one background-music track."""

        if duration_seconds <= 0:
            return self._fail(
                reason="invalid_duration",
                message="Music track duration must be positive.",
            )

        provider = self._select_provider(preferred_provider=provider_name)

        if provider is None:
            return self._fail(
                reason="no_provider_available",
                message="No compatible music provider is available.",
            )

        try:
            provider_healthy = provider.health_check()
        except Exception as exc:
            return self._fail(
                reason="provider_unhealthy",
                message="Music provider health check failed.",
                provider=provider.provider_name,
                metadata={
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )

        if not provider_healthy:
            return self._fail(
                reason="provider_unhealthy",
                message="Selected music provider is unhealthy.",
                provider=provider.provider_name,
            )

        library_query = self._resolve_library_query(instruction)

        try:
            output_file = provider.generate_music(
                library_query=library_query,
                duration_seconds=duration_seconds,
            )
        except Exception as exc:
            return self._fail(
                reason="provider_error",
                message="Music provider failed during generation.",
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
                reason="empty_output_path",
                message="Music provider returned an empty output file path.",
                provider=provider.provider_name,
            )

        normalized_output_file = Path(cleaned_output_file).as_posix()
        output_suffix = Path(normalized_output_file).suffix.lower()

        if output_suffix not in _SUPPORTED_OUTPUT_FORMATS:
            return self._fail(
                reason="unsupported_output_format",
                message="Music provider returned an unsupported audio format.",
                provider=provider.provider_name,
                metadata={"output_file": normalized_output_file},
            )

        audio_track = AudioTrack(
            track_type=AudioTrackType.BACKGROUND_MUSIC,
            source_file=normalized_output_file,
            start_time_seconds=0.0,
            duration_seconds=duration_seconds,
            volume=instruction.volume_percent / 100.0,
            fade_in_seconds=instruction.fade_in_seconds,
            fade_out_seconds=instruction.fade_out_seconds,
            loop_enabled=bool(instruction.preset.implementation.get("loop", False)),
            duck_under_voice=instruction.duck_under_voice,
            provider=provider.provider_name,
            license_type="library",
            status=AudioTrackStatus.READY,
            metadata={
                "resolved_preset_id": instruction.preset.resolved_preset_id,
                "library_query": library_query,
                "intensity": instruction.intensity.value,
            },
        )

        return MusicGenerationResult(
            success=True,
            status=MusicGenerationStatus.COMPLETED,
            provider=provider.provider_name,
            output_file=normalized_output_file,
            audio_track=audio_track,
            metadata={"duration_seconds": duration_seconds},
        )

    def _select_provider(
        self,
        *,
        preferred_provider: str | None,
    ) -> MusicProvider | None:
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
    def _resolve_library_query(instruction: ResolvedMusicInstruction) -> str:
        query = instruction.preset.implementation.get("library_query")

        if isinstance(query, str) and query.strip():
            return query.strip()

        return instruction.preset.resolved_preset_id

    @staticmethod
    def _fail(
        *,
        reason: str,
        message: str,
        provider: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MusicGenerationResult:
        return MusicGenerationResult(
            success=False,
            status=MusicGenerationStatus.FAILED,
            provider=provider,
            failure=MusicGenerationFailure(
                reason=reason,
                message=message,
                provider=provider,
            ),
            metadata=metadata or {},
        )
