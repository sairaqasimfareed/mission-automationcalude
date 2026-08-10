from __future__ import annotations

from dataclasses import dataclass

from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.models.voice_directives import (
    SceneVoiceDirectives,
)
from src.models.voice_profile import (
    VoiceProfile,
)
from src.services.voice_directive_resolution_service import (
    VoiceDirectiveResolutionService,
)
from src.services.voice_directive_validation_service import (
    VoiceDirectiveValidationService,
)
from src.services.voice_profile_registry_service import (
    VoiceProfileRegistryService,
)


VoiceResolutionRequest = tuple[
    SceneVoiceDirectives,
    str,
    float | None,
]


@dataclass(
    frozen=True,
    slots=True,
)
class VoiceResolutionRuntime:
    """
    Shared provider-independent voice-resolution runtime.

    The runtime owns the registry, validation service, and resolution
    service that must operate over the same voice-profile collection.
    """

    voice_profile_registry: VoiceProfileRegistryService
    validation_service: VoiceDirectiveValidationService
    resolution_service: VoiceDirectiveResolutionService

    def resolve_many(
        self,
        requests: list[VoiceResolutionRequest],
    ) -> list[ResolvedVoiceBlueprint]:
        """
        Resolve scene voice requests into generation blueprints.

        Validation, duplicate-scene detection, fallback handling, and
        result ordering remain owned by VoiceDirectiveResolutionService.
        """

        return self.resolution_service.resolve_many(
            requests
        )


class VoiceResolutionRuntimeFactory:
    """
    Compose the provider-independent voice-resolution dependency graph.

    Voice profiles are explicit runtime configuration. The factory does
    not invent profiles, provider mappings, credentials, or directives.
    """

    def build(
        self,
        *,
        profiles: list[VoiceProfile],
    ) -> VoiceResolutionRuntime:
        """
        Build one internally consistent voice-resolution runtime.

        The registry instance is shared by both validation and resolution
        services so they always operate against the same profile set.
        """

        registry = VoiceProfileRegistryService(
            profiles=profiles,
        )

        validation_service = (
            VoiceDirectiveValidationService(
                voice_profile_registry=registry,
            )
        )

        resolution_service = (
            VoiceDirectiveResolutionService(
                voice_profile_registry=registry,
                validation_service=validation_service,
            )
        )

        return VoiceResolutionRuntime(
            voice_profile_registry=registry,
            validation_service=validation_service,
            resolution_service=resolution_service,
        )