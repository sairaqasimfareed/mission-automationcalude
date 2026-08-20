from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_generation import (
    VoiceGenerationFailure,
    VoiceGenerationFailureReason,
    VoiceGenerationJob,
    VoiceGenerationResult,
    VoiceGenerationStatus,
)
from src.providers.voice_provider import VoiceProvider


class VoiceGenerationService:
    """
    Generate narration audio from resolved voice blueprints.

    The service is provider-independent. Real ElevenLabs,
    OpenAI, Google, or Azure adapters can implement the existing
    VoiceProvider interface.
    """

    SUPPORTED_OUTPUT_FORMATS = {
        ".mp3",
        ".wav",
        ".aac",
        ".ogg",
        ".flac",
    }

    def __init__(
        self,
        *,
        providers: list[VoiceProvider],
    ) -> None:
        self.providers = providers

    def generate(
        self,
        blueprint: ResolvedVoiceBlueprint,
        *,
        start_time_seconds: float = 0.0,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        """Generate one voiceover and return an audio track."""

        job = VoiceGenerationJob(
            scene_number=blueprint.scene_number,
            blueprint=blueprint,
            status=VoiceGenerationStatus.PENDING,
            metadata={
                "requested_profile_id": (blueprint.profile.requested_profile_id),
                "resolved_profile_id": (blueprint.profile.resolved_profile_id),
            },
        )

        return self.run_job(
            job,
            start_time_seconds=start_time_seconds,
            provider_name=provider_name,
        )

    def run_job(
        self,
        job: VoiceGenerationJob,
        *,
        start_time_seconds: float = 0.0,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        """Execute one voice generation job."""

        if start_time_seconds < 0:
            raise ValueError("Voice track start time cannot be negative.")

        blueprint = job.blueprint

        if not blueprint.is_generation_ready:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.BLUEPRINT_NOT_READY),
                message=("Voice blueprint is not ready " "for generation."),
                recoverable=False,
            )

        preferred_provider = provider_name or (
            blueprint.provider_preferences.preferred_provider
        )

        provider = self._select_provider(
            preferred_provider=(preferred_provider),
        )

        if provider is None:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.NO_PROVIDER_AVAILABLE),
                message=("No compatible voice provider " "is available."),
            )

        job.selected_provider = provider.provider_name

        try:
            provider_healthy = provider.health_check()
        except Exception as exc:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.PROVIDER_UNHEALTHY),
                message=("Voice provider health check failed."),
                provider=provider.provider_name,
                metadata={
                    "exception_type": (type(exc).__name__),
                    "exception_message": str(exc),
                },
            )

        if not provider_healthy:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.PROVIDER_UNHEALTHY),
                message=("Selected voice provider is unhealthy."),
                provider=provider.provider_name,
            )

        job.status = VoiceGenerationStatus.GENERATING
        job.attempts += 1

        try:
            output_file = provider.generate_voice(
                text=blueprint.narration_text,
                voice=(
                    self._resolve_provider_voice(
                        blueprint=blueprint,
                    )
                ),
            )
        except Exception as exc:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.PROVIDER_ERROR),
                message=("Voice provider failed during " "audio generation."),
                provider=provider.provider_name,
                metadata={
                    "exception_type": (type(exc).__name__),
                    "exception_message": str(exc),
                },
            )

        cleaned_output_file = (
            output_file.strip() if isinstance(output_file, str) else ""
        )

        if not cleaned_output_file:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.EMPTY_OUTPUT_PATH),
                message=("Voice provider returned an empty " "output file path."),
                provider=provider.provider_name,
            )

        normalized_output_file = Path(cleaned_output_file).as_posix()

        output_suffix = Path(normalized_output_file).suffix.lower()

        if output_suffix not in self.SUPPORTED_OUTPUT_FORMATS:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.UNSUPPORTED_OUTPUT_FORMAT),
                message=("Voice provider returned an " "unsupported audio format."),
                provider=provider.provider_name,
                metadata={
                    "output_file": (normalized_output_file),
                    "output_suffix": output_suffix,
                },
            )

        audio_track = AudioTrack(
            track_type=AudioTrackType.VOICEOVER,
            source_file=normalized_output_file,
            start_time_seconds=(start_time_seconds),
            duration_seconds=(blueprint.estimated_speech_duration_seconds),
            volume=self._gain_db_to_linear(blueprint.volume_gain_db),
            fade_in_seconds=(blueprint.pause_before_seconds),
            fade_out_seconds=(blueprint.pause_after_seconds),
            loop_enabled=False,
            duck_under_voice=False,
            provider=provider.provider_name,
            license_type="generated",
            status=AudioTrackStatus.READY,
            metadata={
                "scene_number": (blueprint.scene_number),
                "voice_profile_id": (blueprint.profile.resolved_profile_id),
                "requested_voice_profile_id": (blueprint.profile.requested_profile_id),
                "language": blueprint.language,
                "language_code": (blueprint.language_code),
                "emotion": (blueprint.emotion.value),
                "pace": blueprint.pace.value,
                "energy": blueprint.energy.value,
                "speed": blueprint.speed,
                "pitch_adjustment": (blueprint.pitch_adjustment),
                "stability": (blueprint.stability),
                "similarity_boost": (blueprint.similarity_boost),
                "style_strength": (blueprint.style_strength),
                "speaker_boost": (blueprint.speaker_boost),
                "explicit_instruction_count": (blueprint.explicit_instruction_count),
            },
        )

        job.status = VoiceGenerationStatus.COMPLETED
        job.output_file = normalized_output_file
        job.failure = None

        blueprint.output_file = normalized_output_file

        blueprint.status = VoiceBlueprintResolutionStatus.GENERATED

        return VoiceGenerationResult(
            success=True,
            scene_number=job.scene_number,
            status=(VoiceGenerationStatus.COMPLETED),
            provider=provider.provider_name,
            output_file=normalized_output_file,
            audio_track=audio_track,
            attempts=job.attempts,
            warnings=list(
                dict.fromkeys(
                    [
                        *job.warnings,
                        *blueprint.warnings,
                    ]
                )
            ),
            metadata={
                **job.metadata,
                "blueprint_status": (blueprint.status.value),
                "estimated_duration_seconds": (
                    blueprint.estimated_speech_duration_seconds
                ),
            },
        )

    def generate_many(
        self,
        blueprints: list[ResolvedVoiceBlueprint],
        *,
        provider_name: str | None = None,
        sequential_placement: bool = True,
    ) -> list[VoiceGenerationResult]:
        """Generate voiceovers for multiple scenes."""

        scene_numbers = [blueprint.scene_number for blueprint in blueprints]

        if len(scene_numbers) != len(set(scene_numbers)):
            raise ValueError(
                "Duplicate voice blueprint scene numbers "
                "cannot be generated together."
            )

        results: list[VoiceGenerationResult] = []

        current_start_time = 0.0

        for blueprint in sorted(
            blueprints,
            key=lambda item: item.scene_number,
        ):
            start_time = current_start_time if sequential_placement else 0.0

            result = self.generate(
                blueprint,
                start_time_seconds=start_time,
                provider_name=provider_name,
            )

            results.append(result)

            if (
                sequential_placement
                and result.success
                and result.audio_track is not None
            ):
                current_start_time = (
                    result.audio_track.start_time_seconds
                    + result.audio_track.duration_seconds
                )

        return results

    def available_providers(
        self,
        *,
        healthy_only: bool = False,
    ) -> list[str]:
        """Return registered provider names."""

        names: list[str] = []

        for provider in self.providers:
            if healthy_only:
                try:
                    if not provider.health_check():
                        continue
                except Exception:
                    continue

            if provider.provider_name not in names:
                names.append(provider.provider_name)

        return sorted(
            names,
            key=str.lower,
        )

    def _select_provider(
        self,
        *,
        preferred_provider: str | None,
    ) -> VoiceProvider | None:
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
    def _resolve_provider_voice(
        *,
        blueprint: ResolvedVoiceBlueprint,
    ) -> str:
        """Resolve the voice identifier sent to a provider."""

        preferred_voice_id = blueprint.provider_preferences.preferred_voice_id

        if preferred_voice_id:
            return preferred_voice_id

        mapping_voice_id = blueprint.selected_provider_mapping.get("voice_id")

        if (
            isinstance(
                mapping_voice_id,
                str,
            )
            and mapping_voice_id.strip()
        ):
            return mapping_voice_id.strip()

        return blueprint.profile.resolved_profile_id

    @staticmethod
    def _gain_db_to_linear(
        gain_db: float,
    ) -> float:
        """Convert decibel gain to linear volume."""

        linear_volume = 10 ** (gain_db / 20.0)

        return max(
            0.0,
            min(
                linear_volume,
                4.0,
            ),
        )

    @staticmethod
    def _fail(
        *,
        job: VoiceGenerationJob,
        reason: VoiceGenerationFailureReason,
        message: str,
        provider: str | None = None,
        recoverable: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceGenerationResult:
        """Return a normalized failed generation result."""

        failure = VoiceGenerationFailure(
            reason=reason,
            message=message,
            provider=provider,
            recoverable=recoverable,
            metadata=metadata or {},
        )

        job.status = VoiceGenerationStatus.FAILED
        job.failure = failure

        return VoiceGenerationResult(
            success=False,
            scene_number=job.scene_number,
            status=VoiceGenerationStatus.FAILED,
            provider=provider,
            attempts=job.attempts,
            failure=failure,
            warnings=list(job.warnings),
            metadata=dict(job.metadata),
        )
