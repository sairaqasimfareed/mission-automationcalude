from __future__ import annotations

import pytest

from src.models.resolved_voice_blueprint import (
    VoiceBlueprintResolutionStatus,
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
from src.services.voice_resolution_runtime import (
    VoiceResolutionRuntime,
    VoiceResolutionRuntimeFactory,
)


def _neutral_profile() -> VoiceProfile:
    return VoiceProfile(
        profile_id="voice.neutral_narrator",
        display_name="Neutral Narrator",
        fallback_profile_id=None,
    )


def _documentary_profile() -> VoiceProfile:
    return VoiceProfile(
        profile_id="voice.documentary",
        display_name="Documentary Narrator",
        fallback_profile_id=("voice.neutral_narrator"),
        provider_mappings={
            "elevenlabs": {
                "voice_id": "test-voice",
            },
        },
    )


def _directives(
    *,
    scene_number: int,
    voice_profile_id: str = "voice.documentary",
) -> SceneVoiceDirectives:
    return SceneVoiceDirectives(
        scene_number=scene_number,
        voice_profile_id=voice_profile_id,
    )


def _runtime() -> VoiceResolutionRuntime:
    return VoiceResolutionRuntimeFactory().build(
        profiles=[
            _neutral_profile(),
            _documentary_profile(),
        ],
    )


def test_factory_builds_complete_runtime() -> None:
    runtime = _runtime()

    assert isinstance(
        runtime,
        VoiceResolutionRuntime,
    )

    assert isinstance(
        runtime.voice_profile_registry,
        VoiceProfileRegistryService,
    )

    assert isinstance(
        runtime.validation_service,
        VoiceDirectiveValidationService,
    )

    assert isinstance(
        runtime.resolution_service,
        VoiceDirectiveResolutionService,
    )


def test_runtime_services_share_registry() -> None:
    runtime = _runtime()

    assert (
        runtime.validation_service.voice_profile_registry
        is runtime.voice_profile_registry
    )

    assert (
        runtime.resolution_service.voice_profile_registry
        is runtime.voice_profile_registry
    )


def test_resolution_service_uses_runtime_validation_service() -> None:
    runtime = _runtime()

    assert runtime.resolution_service.validation_service is runtime.validation_service


def test_factory_registers_supplied_profiles() -> None:
    runtime = _runtime()

    assert runtime.voice_profile_registry.contains("voice.neutral_narrator")

    assert runtime.voice_profile_registry.contains("voice.documentary")


def test_factory_creates_fresh_runtime_graph() -> None:
    factory = VoiceResolutionRuntimeFactory()

    profiles = [
        _neutral_profile(),
        _documentary_profile(),
    ]

    first = factory.build(
        profiles=profiles,
    )

    second = factory.build(
        profiles=profiles,
    )

    assert first is not second

    assert first.voice_profile_registry is not second.voice_profile_registry

    assert first.validation_service is not second.validation_service

    assert first.resolution_service is not second.resolution_service


def test_resolve_many_returns_resolved_blueprints() -> None:
    runtime = _runtime()

    blueprints = runtime.resolve_many(
        [
            (
                _directives(
                    scene_number=1,
                ),
                "First scene narration.",
                20.0,
            ),
        ]
    )

    assert len(blueprints) == 1

    blueprint = blueprints[0]

    assert blueprint.scene_number == 1

    assert blueprint.status == VoiceBlueprintResolutionStatus.RESOLVED

    assert blueprint.profile.requested_profile_id == "voice.documentary"

    assert blueprint.profile.resolved_profile_id == "voice.documentary"

    assert blueprint.profile.found_exact_match
    assert not blueprint.profile.used_fallback

    assert blueprint.narration_text == "First scene narration."


def test_resolve_many_orders_blueprints_by_scene_number() -> None:
    runtime = _runtime()

    blueprints = runtime.resolve_many(
        [
            (
                _directives(
                    scene_number=2,
                ),
                "Second scene narration.",
                20.0,
            ),
            (
                _directives(
                    scene_number=1,
                ),
                "First scene narration.",
                20.0,
            ),
        ]
    )

    assert [blueprint.scene_number for blueprint in blueprints] == [
        1,
        2,
    ]


def test_resolve_many_rejects_duplicate_scene_numbers() -> None:
    runtime = _runtime()

    with pytest.raises(
        ValueError,
        match=(
            "Duplicate voice directive scene numbers " "cannot be resolved together"
        ),
    ):
        runtime.resolve_many(
            [
                (
                    _directives(
                        scene_number=1,
                    ),
                    "First narration.",
                    20.0,
                ),
                (
                    _directives(
                        scene_number=1,
                    ),
                    "Duplicate narration.",
                    20.0,
                ),
            ]
        )


def test_unknown_profile_uses_neutral_fallback() -> None:
    runtime = _runtime()

    blueprints = runtime.resolve_many(
        [
            (
                _directives(
                    scene_number=1,
                    voice_profile_id=("voice.unknown_profile"),
                ),
                "Fallback narration.",
                20.0,
            ),
        ]
    )

    assert len(blueprints) == 1

    blueprint = blueprints[0]

    assert blueprint.status == (VoiceBlueprintResolutionStatus.RESOLVED_WITH_FALLBACK)

    assert blueprint.profile.requested_profile_id == "voice.unknown_profile"

    assert blueprint.profile.resolved_profile_id == "voice.neutral_narrator"

    assert blueprint.profile.used_fallback


def test_runtime_does_not_require_provider_credentials() -> None:
    runtime = _runtime()

    blueprints = runtime.resolve_many(
        [
            (
                _directives(
                    scene_number=1,
                ),
                "Provider-independent narration.",
                20.0,
            ),
        ]
    )

    assert len(blueprints) == 1

    assert blueprints[0].profile.resolved_profile_id == "voice.documentary"
