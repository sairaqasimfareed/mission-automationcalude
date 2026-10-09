"""
Character-Oriented Video mode, step 5 (2026-10-09): the words of a clip's prompt that make characters
speak on camera, copied from the prompts that worked on Muse - attributed lines in order, lips in
sync, real speech with quiet ambient sound and no music, one-speaker-at-a-time for a two-person scene,
and a continuity request for a speaker who already appeared.
"""

from __future__ import annotations

from src.models.dialogue import DialogueLine
from src.models.scene import Scene
from src.services.dialogue_prompt import (
    CONTINUITY_MARKER,
    ambient_sound_for,
    dialogue_prompt_text,
    speakers_before,
)


def _lines(*pairs: tuple[str, str]) -> list[DialogueLine]:
    return [DialogueLine(speaker=s, text=t) for s, t in pairs]


# ------------------------------------------------------------------- one speaker


def test_one_speaker_gets_the_tested_wording() -> None:
    text = dialogue_prompt_text(_lines(("Walter", "The train is late.")))

    assert text == (
        'Walter says clearly in their own voice: "The train is late." '
        "Their lips move naturally in sync with the speech. "
        "Real spoken audio with only quiet room sound, no music."
    )


def test_the_same_speaker_twice_is_attributed_each_time() -> None:
    text = dialogue_prompt_text(_lines(("Walter", "One."), ("Walter", "Two.")))

    assert 'Walter says clearly in their own voice: "One."' in text
    assert 'Then Walter says clearly in their own voice: "Two."' in text
    assert "people speak" not in text  # still one person


def test_no_dialogue_adds_nothing() -> None:
    assert dialogue_prompt_text([]) == ""


def test_the_wording_never_guesses_a_gender() -> None:
    text = dialogue_prompt_text(_lines(("Walter", "x"), ("Frank", "y")))

    for word in (" his ", " her ", " he ", " she ", " him "):
        assert word not in f" {text.lower()} "


# ----------------------------------------------------------------- two speakers


def test_two_speakers_are_attributed_in_order_with_turn_taking() -> None:
    text = dialogue_prompt_text(
        _lines(("Walter", "We cannot hold the post."), ("Frank", "Then start sorting."))
    )

    assert text.startswith("Two people speak in this scene, in this order.")
    assert text.index("Walter says clearly") < text.index("Then Frank says clearly")
    assert (
        "Only one person speaks at a time; the listener's mouth stays closed." in text
    )
    assert "Each person keeps exactly their own voice throughout." in text
    assert "Both faces are three-quarter to the camera." in text
    assert "Each speaker's lips move naturally in sync with their own words." in text
    assert "Their lips move naturally" not in text


def test_three_speakers_are_counted_and_all_faces_are_asked_for() -> None:
    text = dialogue_prompt_text(_lines(("A", "x"), ("B", "y"), ("C", "z")))

    assert text.startswith("Three people speak in this scene")
    assert "All faces are three-quarter to the camera." in text


def test_a_crowd_is_counted_as_several() -> None:
    text = dialogue_prompt_text(_lines(*[(f"P{n}", "x") for n in range(6)]))

    assert text.startswith("Several people speak in this scene")


# ---------------------------------------------------------------------- continuity


def test_a_returning_single_speaker_is_asked_to_keep_face_and_voice() -> None:
    text = dialogue_prompt_text(_lines(("Walter", "x")), earlier_speakers={"Walter"})

    assert text.endswith(f"Same face, same voice, {CONTINUITY_MARKER}.")


def test_a_new_speaker_gets_no_continuity_request() -> None:
    text = dialogue_prompt_text(_lines(("Walter", "x")), earlier_speakers={"Frank"})

    assert CONTINUITY_MARKER not in text


def test_in_a_two_person_scene_only_the_returning_one_is_named() -> None:
    text = dialogue_prompt_text(
        _lines(("Walter", "x"), ("Frank", "y")), earlier_speakers={"Walter"}
    )

    assert (
        f"Walter keeps the same face and the same voice, {CONTINUITY_MARKER}." in text
    )
    assert "Frank keeps" not in text


def test_both_returning_speakers_are_named_together() -> None:
    text = dialogue_prompt_text(
        _lines(("Walter", "x"), ("Frank", "y")), earlier_speakers={"Walter", "Frank"}
    )

    assert (
        f"Walter and Frank keep the same face and the same voice, {CONTINUITY_MARKER}."
        in text
    )


def test_speakers_before_a_scene_are_everyone_who_spoke_earlier() -> None:
    scenes = [
        Scene(
            scene_number=n,
            title=f"S{n}",
            narration="n",
            visual_prompt="v",
            estimated_duration_seconds=8,
            dialogue=_lines(*pairs),
        )
        for n, pairs in (
            (1, [("Walter", "x")]),
            (2, [("Frank", "y")]),
            (3, [("Ann", "z")]),
        )
    ]

    assert speakers_before(scenes, 1) == set()
    assert speakers_before(scenes, 3) == {"Walter", "Frank"}


# ---------------------------------------------------------------------- the ambience


def test_the_ambience_follows_the_setting() -> None:
    assert ambient_sound_for("A sorting room above the station") == "quiet room sound"
    assert ambient_sound_for("The village square at dawn") == "quiet outdoor sound"
    assert ambient_sound_for("") == "quiet room sound"


def test_an_outdoor_setting_changes_the_sentence() -> None:
    text = dialogue_prompt_text(
        _lines(("Walter", "x")), environment="The station platform"
    )

    assert "only quiet outdoor sound, no music." in text


# ------------------------------------------------- the compiler uses the wording


def _compile_dialogue(*, scenes: list[Scene], target: int):  # type: ignore[no-untyped-def]
    from src.models.shot_planning import CinematicShotPlan
    from src.services.cinematic_prompt_compilation_service import (
        CinematicPromptCompilationService,
    )
    from tests.test_cinematic_prompt_compilation_service import _bible, _shot_plan

    base = _shot_plan().shots[0]
    plan = CinematicShotPlan(
        script_lock_hash="hash123",
        shots=[
            base.model_copy(update={"scene_number": s.scene_number}) for s in scenes
        ],
    )
    bible = _bible()
    first = bible.clip_entries[0]
    bible.clip_entries = [
        first.model_copy(update={"scene_number": s.scene_number}) for s in scenes
    ]
    package = CinematicPromptCompilationService().compile(
        scenes=scenes,
        shot_plan=plan,
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )
    prompt = package.prompt_for_scene(target)
    assert prompt is not None

    return prompt.prompt_text


def _scene(number: int, *pairs: tuple[str, str]) -> Scene:
    return Scene(
        scene_number=number,
        title=f"S{number}",
        narration=" ".join(t for _s, t in pairs) or "Narration.",
        visual_prompt="v",
        estimated_duration_seconds=8,
        dialogue=_lines(*pairs),
    )


def test_a_speaking_scene_prompt_carries_the_dialogue_wording_after_the_lighting() -> (
    None
):
    text = _compile_dialogue(
        scenes=[_scene(1, ("Walter", "The train is late."))], target=1
    )

    assert 'Walter says clearly in their own voice: "The train is late."' in text
    assert (
        text.index("Lighting:")
        < text.index("Walter says clearly")
        < text.index("Composition:")
    )
    assert "only quiet room sound, no music" in text


def test_the_second_scene_asks_the_returning_speaker_to_keep_face_and_voice() -> None:
    scenes = [_scene(1, ("Walter", "One.")), _scene(2, ("Walter", "Two."))]

    first = _compile_dialogue(scenes=scenes, target=1)
    second = _compile_dialogue(scenes=scenes, target=2)

    assert CONTINUITY_MARKER not in first
    assert f"Same face, same voice, {CONTINUITY_MARKER}." in second


def test_a_narrated_scene_has_no_dialogue_wording() -> None:
    text = _compile_dialogue(scenes=[_scene(1)], target=1)

    assert "says clearly" not in text and "lips move" not in text


# ------------------------------------------------- the completeness check's blind spots


def test_the_continuity_sentence_is_not_flagged_as_relative_wording() -> None:
    from src.services.prompt_completeness_service import (
        FindingCode,
        check_prompt_text,
    )

    good = (
        "Identity: Walter, a clerk in a wool jacket. Environment: A sorting room. "
        "Lighting: Flat overcast daylight, no hard shadows. "
        f"Same face, same voice, {CONTINUITY_MARKER}. "
        "Action progression: He sorts letters. Composition: Wide, low angle. "
        "Lens/camera: 35mm, wide shot. Duration: 8 seconds. "
    ) + "Muted earth tones with a cool grey-green grade. " * 8

    assert FindingCode.RELATIVE_WORDING not in {f.code for f in check_prompt_text(good)}


def test_a_word_a_character_says_is_not_the_prompts_own_wording() -> None:
    from src.services.prompt_completeness_service import (
        FindingCode,
        check_prompt_text,
    )

    spoken = (
        "Identity: Walter, a clerk in a wool jacket. Environment: A sorting room. "
        "Lighting: Flat overcast daylight, no hard shadows. "
        'Walter says clearly in their own voice: "It is the same train as before." '
        "Action progression: He sorts letters. Composition: Wide, low angle. "
        "Lens/camera: 35mm, wide shot. Duration: 8 seconds. "
    ) + "Muted earth tones with a cool grey-green grade. " * 8

    assert FindingCode.RELATIVE_WORDING not in {
        f.code for f in check_prompt_text(spoken)
    }


def test_real_relative_wording_outside_the_quotes_is_still_flagged() -> None:
    from src.services.prompt_completeness_service import (
        FindingCode,
        check_prompt_text,
    )

    text = 'Walter says "hello". Environment: Same village. Lighting: Overcast. ' * 3

    assert FindingCode.RELATIVE_WORDING in {f.code for f in check_prompt_text(text)}


# ------------------------------------------------ telling Muse to use the attached picture


def test_the_reference_picture_sentence_is_added_once_and_only_when_a_picture_is_attached() -> (
    None
):
    from src.services.dialogue_prompt import (
        MULTIPLE_REFERENCE_PICTURES_SENTENCE,
        REFERENCE_PICTURE_SENTENCE,
        with_reference_picture_sentence,
    )

    base = "Walter says clearly."

    assert with_reference_picture_sentence(base, character_pictures=0) == base
    one = with_reference_picture_sentence(base, character_pictures=1)
    assert one.endswith(REFERENCE_PICTURE_SENTENCE)
    assert with_reference_picture_sentence(one, character_pictures=1) == one
    assert with_reference_picture_sentence(base, character_pictures=2).endswith(
        MULTIPLE_REFERENCE_PICTURES_SENTENCE
    )


def _muse_run(tmp_path, *, with_dialogue: bool, with_picture: bool):  # type: ignore[no-untyped-def]
    from src.models.visual_continuity import (
        CanonicalEntityIdentity,
        CanonicalEntityType,
        ClipContinuityEntry,
        VisualContinuityBible,
        VisualState,
    )
    from tests.test_muse_scene_video_generation_service import _job as muse_job
    from tests.test_muse_scene_video_generation_service import _scene as muse_scene
    from tests.test_scene_reference import _store_frame
    from tests.test_scene_reference_automatic import _muse_service, _provider

    one, two = muse_scene(1), muse_scene(2)
    two.real_narration_duration_seconds = 3.0

    if with_dialogue:
        two.dialogue = _lines(("Walter", "Hold the post."))

    job = muse_job(one, two)
    frame = _store_frame(job, tmp_path, scene_number=1) if with_picture else None
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="Walter",
                canonical_description="Walter, a clerk in a wool jacket.",
                reference_asset_ids=[frame] if frame else [],
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=n,
                incoming_state=VisualState(),
                shot_action=f"Shot {n}.",
                outgoing_state=VisualState(),
                entity_names=["Walter"],
                on_screen_entity_names=["Walter"],
            )
            for n in (1, 2)
        ],
    )
    provider = _provider(tmp_path)
    _muse_service(provider, None, tmp_path).generate_one(job, 2)

    return provider.submitted_requests[0]


def test_a_speaking_scene_with_a_character_picture_tells_muse_to_use_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from src.services.dialogue_prompt import REFERENCE_PICTURE_SENTENCE

    request = _muse_run(tmp_path, with_dialogue=True, with_picture=True)

    assert [r.identity_name for r in request.reference_assets] == ["Walter"]
    assert REFERENCE_PICTURE_SENTENCE in request.prompt


def test_a_speaking_scene_with_no_picture_yet_is_not_told_about_one(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from src.services.dialogue_prompt import REFERENCE_PICTURE_SENTENCE

    request = _muse_run(tmp_path, with_dialogue=True, with_picture=False)

    assert request.reference_assets == []
    assert REFERENCE_PICTURE_SENTENCE not in request.prompt


def test_a_narrated_scene_with_a_character_picture_is_left_as_before(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from src.services.dialogue_prompt import REFERENCE_PICTURE_SENTENCE

    request = _muse_run(tmp_path, with_dialogue=False, with_picture=True)

    assert len(request.reference_assets) == 1
    assert REFERENCE_PICTURE_SENTENCE not in request.prompt
