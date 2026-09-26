from __future__ import annotations

import pytest

from src.models.scene import Scene
from src.models.shot_planning import (
    CinematicShotPlan,
    ShotAngle,
    ShotMovement,
    ShotSize,
    ShotSpecification,
    TemporalActionBeat,
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


def _shot_plan_with_beats(
    beats: list[TemporalActionBeat], duration_seconds: float = 8.0
) -> CinematicShotPlan:
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
                duration_seconds=duration_seconds,
                temporal_action_beats=beats,
            )
        ],
    )


def test_compile_renders_shot_by_shot_beats_when_present() -> None:
    service = CinematicPromptCompilationService()
    beats = [
        TemporalActionBeat(
            start_offset_seconds=0.0, end_offset_seconds=2.0, description="establish"
        ),
        TemporalActionBeat(
            start_offset_seconds=2.0, end_offset_seconds=8.0, description="reveal"
        ),
    ]

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan_with_beats(beats),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    assert "Shot progression: [0-2s] establish; [2-8s] reveal." in prompt.prompt_text
    assert "Action progression:" not in prompt.prompt_text


def test_compile_falls_back_to_flat_action_line_with_no_beats() -> None:
    service = CinematicPromptCompilationService()

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),  # no temporal_action_beats
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    assert "Action progression: The captain surveys the horizon." in prompt.prompt_text
    assert "Shot progression:" not in prompt.prompt_text


def test_compile_can_disable_shot_by_shot_beats_as_a_kill_switch() -> None:
    service = CinematicPromptCompilationService()
    beats = [
        TemporalActionBeat(
            start_offset_seconds=0.0, end_offset_seconds=8.0, description="establish"
        ),
    ]

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan_with_beats(beats),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        use_shot_by_shot_beats=False,
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    assert "Shot progression:" not in prompt.prompt_text
    assert "Action progression: The captain surveys the horizon." in prompt.prompt_text


def test_compile_rescales_beats_instead_of_dropping_them_past_the_resolved_duration() -> (
    None
):
    """
    Real-world finding, 2026-09-26: beats starting at or past a
    clamped duration used to be dropped outright, not shortened -
    confirmed live on a 13s scene planned across six beats (one per
    infographic icon), compiled down to a prompt describing only the
    first four once clamped to Flow's 8s cap. Every beat's real
    content must survive compilation, proportionally rescaled to fit
    the resolved duration rather than silently lost - continuity is
    still respected (no beat's rendered end time can exceed the
    resolved duration, since every offset is scaled by the same
    factor), but nothing the shot plan described disappears.
    """

    service = CinematicPromptCompilationService()
    beats = [
        TemporalActionBeat(
            start_offset_seconds=0.0, end_offset_seconds=6.0, description="establish"
        ),
        TemporalActionBeat(
            start_offset_seconds=6.0, end_offset_seconds=8.0, description="reveal"
        ),
    ]

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan_with_beats(beats, duration_seconds=8.0),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        duration_seconds_resolver=lambda _seconds: 6.0,
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    # scale = 6.0 / 8.0 = 0.75: [0-6s]->[0-4.5s], [6-8s]->[4.5-6s].
    assert (
        "Shot progression: [0-4.5s] establish; [4.5-6s] reveal." in prompt.prompt_text
    )
    assert "Duration: 6 seconds" in prompt.prompt_text


def test_compile_clamps_a_beats_end_offset_to_the_resolved_duration() -> None:
    service = CinematicPromptCompilationService()
    beats = [
        TemporalActionBeat(
            start_offset_seconds=0.0, end_offset_seconds=8.0, description="establish"
        ),
    ]

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan_with_beats(beats, duration_seconds=8.0),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        duration_seconds_resolver=lambda _seconds: 6.0,
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    assert "Shot progression: [0-6s] establish." in prompt.prompt_text


def test_compile_uses_the_duration_resolver_for_the_stated_duration() -> None:
    service = CinematicPromptCompilationService()

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),  # shot.duration_seconds = 8.0
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        duration_seconds_resolver=lambda _seconds: 6.0,
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    assert "Duration: 6 seconds" in prompt.prompt_text


def test_compile_still_rescales_a_beat_that_starts_very_late_in_the_original_plan() -> (
    None
):
    """
    Companion to the rescale test above: even a beat whose original
    start time is most of the way through the shot's own planned
    duration must still survive compilation once rescaled - there is
    no longer a "so late it gets dropped/falls back to flat action"
    threshold, since every beat is rescaled by the same factor rather
    than filtered by an absolute start-time comparison.
    """

    service = CinematicPromptCompilationService()
    beats = [
        TemporalActionBeat(
            start_offset_seconds=6.0, end_offset_seconds=8.0, description="reveal"
        ),
    ]

    package = service.compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan_with_beats(beats, duration_seconds=8.0),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        duration_seconds_resolver=lambda _seconds: 4.0,
    )

    prompt = package.prompt_for_scene(1)
    assert prompt is not None
    # scale = 4.0 / 8.0 = 0.5: [6-8s] -> [3-4s].
    assert "Shot progression: [3-4s] reveal." in prompt.prompt_text
    assert "Action progression:" not in prompt.prompt_text


# --- compile_sub_clip_prompts (Phase 5: multi-clip scene splitting) ---


def test_compile_sub_clip_prompts_divides_beats_across_windows_without_duplicating() -> (
    None
):
    """
    Real-world finding, 2026-09-26: before this method existed, every
    sub-clip of a split scene got the identical whole-scene prompt
    text - sub-clip 2 was never told to show anything different from
    sub-clip 1. Each sub-clip's own window must describe only its own
    real slice, re-based to start at 0.
    """

    service = CinematicPromptCompilationService()
    beats = [
        TemporalActionBeat(
            start_offset_seconds=0.0, end_offset_seconds=8.0, description="icons A+B"
        ),
        TemporalActionBeat(
            start_offset_seconds=8.0, end_offset_seconds=13.0, description="icons C+D"
        ),
    ]

    prompts = service.compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=_shot_plan_with_beats(beats, duration_seconds=13.0),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        sub_clip_durations=[8.0, 5.0],
    )

    assert len(prompts) == 2
    assert "Shot progression: [0-8s] icons A+B." in prompts[0].prompt_text
    assert "icons C+D" not in prompts[0].prompt_text

    assert "Shot progression: [0-5s] icons C+D." in prompts[1].prompt_text
    assert "icons A+B" not in prompts[1].prompt_text


def test_compile_sub_clip_prompts_sets_clip_sequence_index() -> None:
    service = CinematicPromptCompilationService()

    prompts = service.compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        sub_clip_durations=[8.0, 5.0],
    )

    assert [p.clip_sequence_index for p in prompts] == [0, 1]
    assert all(p.scene_number == 1 for p in prompts)


def test_compile_sub_clip_prompts_only_notes_continuation_from_the_second_clip() -> (
    None
):
    service = CinematicPromptCompilationService()

    prompts = service.compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        sub_clip_durations=[8.0, 5.0, 3.0],
    )

    assert "continues directly from the previous" not in prompts[0].prompt_text
    assert "continues directly from the previous" in prompts[1].prompt_text
    assert "continues directly from the previous" in prompts[2].prompt_text


def test_compile_sub_clip_prompts_states_which_part_out_of_how_many() -> None:
    service = CinematicPromptCompilationService()

    prompts = service.compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        sub_clip_durations=[8.0, 5.0],
    )

    assert "part 1 of 2" in prompts[0].prompt_text
    assert "Duration: 8 seconds" in prompts[0].prompt_text
    assert "part 2 of 2" in prompts[1].prompt_text
    assert "Duration: 5 seconds" in prompts[1].prompt_text


def test_compile_sub_clip_prompts_shares_identity_and_references_across_all_sub_clips() -> (
    None
):
    service = CinematicPromptCompilationService()

    prompts = service.compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=_shot_plan(),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        sub_clip_durations=[8.0, 5.0],
    )

    for prompt in prompts:
        assert "Captain of the Mary Celeste." in prompt.prompt_text
        assert prompt.reference_asset_ids == ["asset-1"]


def test_compile_sub_clip_prompts_falls_back_to_flat_action_with_no_overlap() -> None:
    """
    A window that no beat overlaps at all (a real gap in the shot
    plan) falls back to the same safe flat action line the whole-scene
    path uses, rather than an empty or nonsensical shot progression.
    """

    service = CinematicPromptCompilationService()
    beats = [
        TemporalActionBeat(
            start_offset_seconds=0.0, end_offset_seconds=3.0, description="only early"
        ),
    ]

    prompts = service.compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=_shot_plan_with_beats(beats, duration_seconds=13.0),
        visual_continuity_bible=_bible(),
        production_semantic_brief=None,
        script_lock_hash="hash123",
        sub_clip_durations=[3.0, 10.0],
    )

    assert "Shot progression:" not in prompts[1].prompt_text
    assert "Action progression: The captain surveys the horizon." in (
        prompts[1].prompt_text
    )
