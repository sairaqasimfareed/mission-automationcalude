from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_directives import (
    SceneVoiceDirectives,
    VoiceDirectiveStatus,
)
from src.services.dynamic_voice_selection_service import DynamicVoiceSelectionService
from src.services.voice_directive_validation_service import (
    VoiceDirectiveValidationService,
)
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)
from src.services.voice_provider_mapping_service import VoiceProviderMappingService


class VoiceDirectiveResolutionService:
    """
    Convert validated scene voice directives into a final,
    provider-independent voice generation blueprint.
    """

    def __init__(
        self,
        *,
        voice_profile_registry: VoiceProfileRegistryService,
        validation_service: VoiceDirectiveValidationService,
        voice_provider_mapping_service: VoiceProviderMappingService | None = None,
        dynamic_voice_selection_service: DynamicVoiceSelectionService | None = None,
    ) -> None:
        self.voice_profile_registry = voice_profile_registry

        self.validation_service = validation_service

        # Voice gap #1 (2026-09-09 audit) - optional so every existing
        # caller/test keeps working unchanged; when supplied, a real,
        # persisted voice_id overlays whatever the resolved profile's
        # own provider_mappings carries (see resolve()'s own comment
        # for why a real id can never simply be hardcoded there).
        self.voice_provider_mapping_service = voice_provider_mapping_service

        # 2026-09-11 real fix ("don't hardcode a voice per genre, I
        # want it flexible") - optional so every existing caller/test
        # keeps working unchanged; when supplied, resolve() falls
        # through to a real, live ElevenLabs search only after both
        # tiers above found nothing, so an explicit manual pin (via
        # voice_provider_mapping_service) still wins when one exists.
        self.dynamic_voice_selection_service = dynamic_voice_selection_service

    def resolve(
        self,
        directives: SceneVoiceDirectives,
        *,
        narration_text: str,
        scene_duration_seconds: float | None = None,
        target_provider: str | None = None,
        previous_scene_narration_text: str | None = None,
        next_scene_narration_text: str | None = None,
    ) -> ResolvedVoiceBlueprint:
        """
        Validate and resolve one scene voice request.

        target_provider is a real fix for a second real bug found
        alongside gap #1: _select_provider_mapping only ever returns a
        non-empty mapping when directives.provider_preferences.preferred_provider
        is explicitly set - but the ordinary genre-driven directive
        path (GenreVoiceDirectiveGenerationService) never sets it, so
        selected_provider_mapping was always {} in the real pipeline,
        making any per-profile provider_mappings (including a real
        voice_id, once registered) silently unreachable end to end.
        target_provider lets the real caller (which knows which
        provider it's about to generate through) supply it explicitly
        without requiring every directive to carry a provider
        preference of its own; directives' own explicit preference
        still wins when both are set.

        previous_scene_narration_text/next_scene_narration_text are
        voice gap #9's real stitching context - carried straight onto
        the resolved blueprint's own fields, consumed only when
        directives.voice_delivery_mode is CONTINUITY_STITCHING
        (ElevenLabsVoiceTranslationService ignores them otherwise).
        resolve_many() derives these automatically from adjacent
        requests in the same batch; a standalone resolve() call simply
        omits them, matching this method's exact prior behavior.
        """

        validation = self.validation_service.validate(
            directives,
            narration_text=narration_text,
            scene_duration_seconds=(scene_duration_seconds),
        )

        if not validation.is_generation_ready:
            directives.status = VoiceDirectiveStatus.FAILED

            error_text = self._format_errors(validation.errors)

            raise ValueError("Voice directives cannot be resolved. " f"{error_text}")

        profile_resolution = self.voice_profile_registry.resolve(
            directives.voice_profile_id,
            allow_fallback=True,
        )

        if (
            not profile_resolution.is_resolved
            or profile_resolution.profile is None
            or (profile_resolution.resolved_profile_id is None)
        ):
            directives.status = VoiceDirectiveStatus.FAILED

            raise ValueError(
                "Voice profile could not be resolved: " f"{directives.voice_profile_id}"
            )

        profile = profile_resolution.profile

        warnings = self._collect_warnings(
            directive_warnings=(directives.warnings),
            validation_warnings=[issue.message for issue in validation.warnings],
            profile_warning=(profile_resolution.warning),
        )

        effective_provider = (
            directives.provider_preferences.preferred_provider or target_provider
        )

        selected_provider_mapping = self._select_provider_mapping(
            provider_mappings=(profile.provider_mappings),
            preferred_provider=effective_provider,
        )

        if self.voice_provider_mapping_service is not None and effective_provider:
            real_voice_id = self.voice_provider_mapping_service.get_voice_id(
                voice_profile_id=profile_resolution.resolved_profile_id,
                provider_name=effective_provider,
            )

            if real_voice_id:
                selected_provider_mapping = {
                    **selected_provider_mapping,
                    "voice_id": real_voice_id,
                }

        if (
            self.dynamic_voice_selection_service is not None
            and effective_provider
            and not selected_provider_mapping.get("voice_id")
        ):
            # 2026-09-11 real fix ("don't hardcode a voice per genre,
            # I want it flexible") - only reached when neither a
            # manual pin (voice_provider_mapping_service) nor a
            # static profile.provider_mappings entry already resolved
            # a voice_id, so an explicit pin still wins when one
            # exists. Uses the directive's own emotion/pitch_style
            # (which may be LLM-produced and differ scene-to-scene),
            # not the profile's fixed baseline.
            dynamic_voice_id = self.dynamic_voice_selection_service.select_voice_id(
                profile=profile,
                emotion=directives.emotion,
                pitch_style=directives.pitch_style,
            )

            if dynamic_voice_id:
                selected_provider_mapping = {
                    **selected_provider_mapping,
                    "voice_id": dynamic_voice_id,
                }

        status = (
            VoiceBlueprintResolutionStatus.RESOLVED_WITH_FALLBACK
            if profile_resolution.used_fallback
            else (VoiceBlueprintResolutionStatus.RESOLVED)
        )

        blueprint = ResolvedVoiceBlueprint(
            scene_number=directives.scene_number,
            status=status,
            profile=ResolvedVoiceProfileReference(
                requested_profile_id=(directives.voice_profile_id),
                resolved_profile_id=(profile_resolution.resolved_profile_id),
                display_name=profile.display_name,
                profile_version=profile.version,
                found_exact_match=(profile_resolution.found_exact_match),
                used_fallback=(profile_resolution.used_fallback),
                provider_mappings=deepcopy(profile.provider_mappings),
                warning=(profile_resolution.warning),
            ),
            narration_text=(narration_text.strip()),
            language=directives.language,
            language_code=(directives.language_code),
            voice_delivery_mode=(directives.voice_delivery_mode),
            previous_scene_narration_text=previous_scene_narration_text,
            next_scene_narration_text=next_scene_narration_text,
            emotion=directives.emotion,
            pace=directives.pace,
            energy=directives.energy,
            pitch_style=(directives.pitch_style),
            pause_style=(directives.pause_style),
            emphasis_style=(directives.emphasis_style),
            speed=directives.speed,
            pitch_adjustment=(directives.pitch_adjustment),
            volume_gain_db=(directives.volume_gain_db),
            stability=directives.stability,
            similarity_boost=(directives.similarity_boost),
            style_strength=(directives.style_strength),
            speaker_boost=(directives.speaker_boost),
            pause_before_seconds=(directives.pause_before_seconds),
            pause_after_seconds=(directives.pause_after_seconds),
            pronunciation_directives=deepcopy(directives.pronunciation_directives),
            pause_directives=deepcopy(directives.pause_directives),
            emphasis_directives=deepcopy(directives.emphasis_directives),
            provider_preferences=(
                directives.provider_preferences.model_copy(deep=True)
            ),
            selected_provider_mapping=(selected_provider_mapping),
            estimated_speech_duration_seconds=(
                validation.estimated_speech_duration_seconds
            ),
            available_scene_duration_seconds=(
                validation.available_scene_duration_seconds
            ),
            narration_word_count=(validation.narration_word_count),
            narration_character_count=(validation.narration_character_count),
            source=directives.source,
            warnings=warnings,
            metadata={
                **deepcopy(directives.metadata),
                "directive_schema_version": (directives.schema_version),
                "profile_schema_version": (profile.schema_version),
                "profile_version": (profile.version),
                "profile_exact_match": (profile_resolution.found_exact_match),
                "profile_fallback_used": (profile_resolution.used_fallback),
                "validation_issue_count": (validation.issue_count),
                "explicit_instruction_count": (directives.explicit_instruction_count),
            },
        )

        directives.status = VoiceDirectiveStatus.READY

        for warning in warnings:
            if warning not in directives.warnings:
                directives.warnings.append(warning)

        return blueprint

    def resolve_many(
        self,
        requests: list[
            tuple[
                SceneVoiceDirectives,
                str,
                float | None,
            ]
        ],
        *,
        target_provider: str | None = None,
    ) -> list[ResolvedVoiceBlueprint]:
        """
        Resolve multiple scene voice requests.

        Each tuple contains:
        directives, narration text, scene duration.

        Voice gap #9 (2026-09-09 audit): requests are resolved in
        scene_number order (not input order, which callers don't
        guarantee) so each scene's real previous/next narration
        context comes from its genuinely adjacent scene - the first
        and last scenes in the batch simply get None for the
        respective side, matching a standalone resolve() call.
        """

        scene_numbers = [directives.scene_number for directives, _, _ in requests]

        if len(scene_numbers) != len(set(scene_numbers)):
            raise ValueError(
                "Duplicate voice directive scene numbers "
                "cannot be resolved together."
            )

        ordered_requests = sorted(
            requests,
            key=lambda request: request[0].scene_number,
        )

        blueprints = [
            self.resolve(
                directives,
                narration_text=narration_text,
                scene_duration_seconds=(scene_duration_seconds),
                target_provider=target_provider,
                previous_scene_narration_text=(
                    ordered_requests[index - 1][1] if index > 0 else None
                ),
                next_scene_narration_text=(
                    ordered_requests[index + 1][1]
                    if index < len(ordered_requests) - 1
                    else None
                ),
            )
            for index, (
                directives,
                narration_text,
                scene_duration_seconds,
            ) in enumerate(ordered_requests)
        ]

        return sorted(
            blueprints,
            key=lambda blueprint: (blueprint.scene_number),
        )

    @staticmethod
    def mark_generated(
        blueprint: ResolvedVoiceBlueprint,
        *,
        output_file: str,
    ) -> ResolvedVoiceBlueprint:
        """Mark a resolved blueprint as generated."""

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Generated voice output file " "cannot be empty.")

        if not blueprint.is_resolved:
            raise ValueError(
                "Only a resolved voice blueprint " "can be marked as generated."
            )

        blueprint.output_file = Path(cleaned_output_file).as_posix()

        blueprint.status = VoiceBlueprintResolutionStatus.GENERATED

        return blueprint

    @staticmethod
    def _select_provider_mapping(
        *,
        provider_mappings: dict[
            str,
            dict[str, Any],
        ],
        preferred_provider: str | None,
    ) -> dict[str, Any]:
        """Select the requested provider's profile mapping."""

        if preferred_provider is None:
            return {}

        normalized_provider = preferred_provider.strip().lower()

        mapping = provider_mappings.get(normalized_provider)

        if mapping is None:
            return {}

        return deepcopy(mapping)

    @staticmethod
    def _collect_warnings(
        *,
        directive_warnings: list[str],
        validation_warnings: list[str],
        profile_warning: str | None,
    ) -> list[str]:
        """Collect unique warnings from all resolution stages."""

        warnings: list[str] = []

        candidates = [
            *directive_warnings,
            *validation_warnings,
        ]

        if profile_warning is not None:
            candidates.append(profile_warning)

        for candidate in candidates:
            cleaned = candidate.strip()

            if cleaned and cleaned not in warnings:
                warnings.append(cleaned)

        return warnings

    @staticmethod
    def _format_errors(
        errors: list[Any],
    ) -> str:
        """Format validation errors for a resolution exception."""

        if not errors:
            return "The voice request is not " "generation-ready."

        return " ".join(issue.message for issue in errors)
