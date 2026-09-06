from __future__ import annotations

import pytest

from src.models.scene import Scene
from src.models.shot_planning import (
    CinematicShotPlan,
    ShotAngle,
    ShotMovement,
    ShotSize,
    ShotSpecification,
)
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.cinematic_prompt_compilation_service import (
    CinematicPromptCompilationService,
)


def _scene(number: int) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration="The captain surveys the horizon.",
        visual_prompt="A ship at sea.",
        estimated_duration_seconds=8,
    )


def _shot_plan() -> CinematicShotPlan:
    return CinematicShotPlan(
        script_lock_hash="hash123",
        shots=[
            ShotSpecification(
                scene_number=1,
                shot_size=ShotSize.MEDIUM,
                shot_angle=ShotAngle.EYE_LEVEL,
                movement=ShotMovement.STATIC,
                lens="35mm",
                composition="Rule of thirds.",
                blocking="Center frame.",
                lighting="Soft morning light.",
                action="The captain surveys the horizon.",
                transition_in="cut",
                transition_out="cut",
                duration_seconds=8.0,
            )
        ],
    )


def _bible() -> VisualContinuityBible:
    return VisualContinuityBible(
        script_lock_hash="hash123",
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="Captain Briggs",
                canonical_description="Captain of the Mary Celeste.",
                reference_asset_ids=["asset-1"],
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(),
                shot_action="The captain surveys.",
                outgoing_state=VisualState(location="The deck", lighting="Bright"),
                entity_names=["Captain Briggs"],
            )
        ],
    )


def test_compile_produces_one_prompt_per_scene() -> None:
    service = CinematicPromptCompilationService()

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )

    assert len(package.prompts) == 1
    assert package.script_lock_hash == "hash123"


def test_compile_includes_identity_environment_and_lighting() -> None:
    service = CinematicPromptCompilationService()

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    assert "Captain of the Mary Celeste" in prompt.prompt_text
    assert "The deck" in prompt.prompt_text
    assert "Bright" in prompt.prompt_text


def test_compile_carries_reference_asset_ids_from_identities() -> None:
    service = CinematicPromptCompilationService()

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    assert prompt.reference_asset_ids == ["asset-1"]


def test_compile_includes_standard_negative_constraints() -> None:
    service = CinematicPromptCompilationService()

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    assert len(prompt.negative_constraints) == 4


def test_compile_is_reproducible_from_unchanged_inputs() -> None:
    service = CinematicPromptCompilationService()

    package_a = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )
    package_b = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )

    prompt_a = package_a.prompt_for_scene(1)
    prompt_b = package_b.prompt_for_scene(1)
    assert prompt_a is not None and prompt_b is not None
    assert prompt_a.prompt_text == prompt_b.prompt_text


def test_compile_requires_at_least_one_scene() -> None:
    service = CinematicPromptCompilationService()

    with pytest.raises(ValueError, match="at least one scene"):
        service.compile(
            scenes=[],
            shot_plan=_shot_plan(),
            visual_continuity_bible=_bible(),
            production_semantic_brief=None,
            script_lock_hash="hash123",
        )


def test_compile_handles_a_scene_with_no_shot_or_continuity_gracefully() -> None:
    service = CinematicPromptCompilationService()

    package = service.compile(
        scenes=[_scene(2)],
        shot_plan=_shot_plan(),  # only has scene 1
        visual_continuity_bible=_bible(),  # only has scene 1
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )

    prompt = package.prompt_for_scene(2)
    assert prompt is not None
    assert "unspecified" in prompt.prompt_text
