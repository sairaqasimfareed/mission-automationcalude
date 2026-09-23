"""
REQ-12 (top10 countdown rank cards), 2026-09-23: rank_badge_text must
carry through EditingDirectiveResolutionService.resolve() from a
VisualEffectDirective onto its ResolvedVisualEffectInstruction - the
same copy-through this codebase already does for
numeric_intensity_percent (REQ-1/2).
"""

from __future__ import annotations

from src.models.editing_directives import (
    DirectiveTimingMode,
    SceneEditingDirectives,
    VisualEffectDirective,
)
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService


def _service() -> EditingDirectiveResolutionService:
    return EditingDirectiveResolutionService(
        effect_registry=EffectRegistryService.with_default_presets(),
    )


def _directives(*, rank_badge_text: str | None) -> SceneEditingDirectives:
    return SceneEditingDirectives(
        scene_number=1,
        visual_effects=[
            VisualEffectDirective(
                preset_id="visual.top10_rank_badge",
                rank_badge_text=rank_badge_text,
                timing_mode=DirectiveTimingMode.FULL_SCENE,
            )
        ],
    )


def test_rank_badge_text_carries_through_resolution() -> None:
    service = _service()

    blueprint = service.resolve(_directives(rank_badge_text="10"))

    assert len(blueprint.visual_effects) == 1
    assert blueprint.visual_effects[0].rank_badge_text == "10"
    assert blueprint.visual_effects[0].preset.resolved_preset_id == (
        "visual.top10_rank_badge"
    )


def test_non_badge_directive_resolves_with_rank_badge_text_none() -> None:
    service = _service()

    blueprint = service.resolve(_directives(rank_badge_text=None))

    assert blueprint.visual_effects[0].rank_badge_text is None
