"""
A prompt describes only the people and places that are ON SCREEN in its scene (2026-10-10, live: Haunted
wife). Scene 1 is a close-up of a letter on papyrus; its prompt still began "Identity: A man who wrote a
letter to his dead wife...", because the compiler listed every identity attached to the scene's continuity
entry even though the bible knew the man does not appear - which invites a generator to add a man to a
papyrus shot. A bible made before the on-screen list existed has none anywhere, so it keeps the old rule.
"""

from __future__ import annotations

from src.models.scene import Scene
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
from tests.test_cinematic_prompt_compilation_service import _scene, _shot_plan

_MAN = "A man who wrote a letter to his dead wife, his identity not given."
_EGYPT = "A sun-scorched Nile-valley settlement of mudbrick houses."


def _bible(
    *,
    on_screen: dict[int, list[str]],
    attached: list[str] | None = None,
    scenes: int = 2,
) -> VisualContinuityBible:
    attached = attached if attached is not None else ["The letter writer", "Egypt"]

    return VisualContinuityBible(
        script_lock_hash="hash123",
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="The letter writer",
                canonical_description=_MAN,
                reference_asset_ids=["asset-man"],
            ),
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="Egypt",
                canonical_description=_EGYPT,
                reference_asset_ids=["asset-egypt"],
            ),
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=n,
                incoming_state=VisualState(),
                shot_action=f"Shot {n}.",
                outgoing_state=VisualState(location="The papyrus", lighting="Dim"),
                entity_names=list(attached),
                on_screen_entity_names=on_screen.get(n, []),
            )
            for n in range(1, scenes + 1)
        ],
    )


def _compile(bible: VisualContinuityBible, number: int = 1):  # type: ignore[no-untyped-def]
    from src.models.shot_planning import CinematicShotPlan

    scenes: list[Scene] = [_scene(n) for n in (1, 2)]
    base = _shot_plan().shots[0]
    plan = CinematicShotPlan(
        script_lock_hash="hash123",
        shots=[base.model_copy(update={"scene_number": n}) for n in (1, 2)],
    )
    package = CinematicPromptCompilationService().compile(
        scenes=scenes,
        shot_plan=plan,
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )
    prompt = package.prompt_for_scene(number)
    assert prompt is not None

    return prompt


def test_a_person_attached_but_not_on_screen_is_left_out_of_the_prompt() -> None:
    bible = _bible(on_screen={1: ["Egypt"], 2: ["Egypt"]})

    prompt = _compile(bible)

    assert _MAN not in prompt.prompt_text
    assert _EGYPT in prompt.prompt_text


def test_a_person_who_is_on_screen_is_described() -> None:
    bible = _bible(on_screen={1: ["The letter writer", "Egypt"], 2: ["Egypt"]})

    text = _compile(bible, 1).prompt_text

    assert _MAN in text and _EGYPT in text


def test_the_same_person_is_described_in_the_scene_they_are_in_and_not_the_other() -> (
    None
):
    bible = _bible(on_screen={1: ["The letter writer"], 2: ["Egypt"]})

    first, second = _compile(bible, 1).prompt_text, _compile(bible, 2).prompt_text

    assert _MAN in first and _EGYPT not in first
    assert _EGYPT in second and _MAN not in second


def test_a_scene_with_nobody_on_screen_names_no_identity() -> None:
    bible = _bible(on_screen={2: ["Egypt"]})  # scene 1: a close-up of the letter

    text = _compile(bible, 1).prompt_text

    assert "no recurring identity present" in text
    assert _MAN not in text and _EGYPT not in text


def test_reference_pictures_follow_the_same_rule() -> None:
    bible = _bible(on_screen={1: ["Egypt"], 2: ["The letter writer", "Egypt"]})

    assert _compile(bible, 1).reference_asset_ids == ["asset-egypt"]
    assert sorted(_compile(bible, 2).reference_asset_ids) == [
        "asset-egypt",
        "asset-man",
    ]


def test_a_bible_made_before_the_on_screen_list_existed_keeps_the_old_rule() -> None:
    """No entry anywhere has an on-screen list, so an empty one cannot mean "nobody is
    on screen" - it means the list was never written."""

    bible = _bible(on_screen={})

    text = _compile(bible, 1).prompt_text

    assert _MAN in text and _EGYPT in text


def test_sub_clip_prompts_follow_the_same_rule() -> None:
    from src.models.shot_planning import CinematicShotPlan

    bible = _bible(on_screen={1: ["Egypt"], 2: ["Egypt"]})
    base = _shot_plan().shots[0]
    plan = CinematicShotPlan(
        script_lock_hash="hash123",
        shots=[base.model_copy(update={"scene_number": n}) for n in (1, 2)],
    )

    prompts = CinematicPromptCompilationService().compile_sub_clip_prompts(
        scene=_scene(1),
        shot_plan=plan,
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
        sub_clip_durations=[6.0, 6.0],
    )

    assert len(prompts) == 2
    assert all(_MAN not in p.prompt_text and _EGYPT in p.prompt_text for p in prompts)
