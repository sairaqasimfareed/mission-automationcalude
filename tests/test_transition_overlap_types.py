"""
Every between-scene transition that FFmpeg draws with its two-stream `xfade` overlaps the two clips and must
be recorded as overlapping (2026-10-10). Only the six original type names were listed, so the eleven presets
added later (fade_black, wipe_*, slide_*, pixelize, circle_crop) were recorded as NOT overlapping - a wrong
overlap count and wrong overlap times on their executions - although the filter graph overlaps them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.models.effect_registry import EffectCategory
from src.services.effect_registry_service import EffectRegistryService
from src.services.transition_execution_service import TransitionExecutionService
from src.services.video_filter_translation_service import VideoFilterTranslationService

_REGISTRY = EffectRegistryService.with_default_presets()
_TRANSITIONS = _REGISTRY.list_by_category(EffectCategory.TRANSITION)
_NON_CUT = [p for p in _TRANSITIONS if p.preset_id != "transition.cut"]


def _instruction(preset) -> SimpleNamespace:  # type: ignore[no-untyped-def]
    return SimpleNamespace(preset=SimpleNamespace(implementation=preset.implementation))


def _requires_overlap(preset) -> bool:  # type: ignore[no-untyped-def]
    service = TransitionExecutionService.__new__(TransitionExecutionService)

    return service._requires_overlap(  # noqa: SLF001
        instruction=_instruction(preset),  # type: ignore[arg-type]
        transition_type=str(preset.implementation["type"]),
    )


def test_the_registry_really_holds_the_thirteen_transitions() -> None:
    assert len(_TRANSITIONS) == 13
    assert len(_NON_CUT) == 12


@pytest.mark.parametrize("preset", _NON_CUT, ids=lambda p: p.preset_id)
def test_every_registered_non_cut_transition_is_recorded_as_overlapping(preset) -> None:  # type: ignore[no-untyped-def]
    assert _requires_overlap(preset) is True


def test_a_cut_does_not_overlap() -> None:
    cut = next(p for p in _TRANSITIONS if p.preset_id == "transition.cut")

    assert _requires_overlap(cut) is False


@pytest.mark.parametrize("preset", _NON_CUT, ids=lambda p: p.preset_id)
def test_the_overlap_list_and_the_ffmpeg_translation_know_the_same_types(preset) -> None:  # type: ignore[no-untyped-def]
    """A type the render can draw is a type the execution step records as overlapping, and the other
    way round, so a new preset cannot be added to one and forgotten in the other."""

    transition_type = str(preset.implementation["type"])

    assert transition_type in TransitionExecutionService.OVERLAP_TRANSITION_TYPES
    assert VideoFilterTranslationService._xfade_transition_name(
        transition_type
    )  # noqa: SLF001


def test_an_explicit_configuration_still_wins_over_the_type_list() -> None:
    service = TransitionExecutionService.__new__(TransitionExecutionService)
    forced_off = SimpleNamespace(
        preset=SimpleNamespace(implementation={"requires_overlap": False})
    )
    forced_on = SimpleNamespace(
        preset=SimpleNamespace(implementation={"requires_overlap": True})
    )

    assert (
        service._requires_overlap(  # noqa: SLF001
            instruction=forced_off,  # type: ignore[arg-type]
            transition_type="cross_dissolve",
        )
        is False
    )
    assert (
        service._requires_overlap(  # noqa: SLF001
            instruction=forced_on,  # type: ignore[arg-type]
            transition_type="cut",
        )
        is True
    )
