"""
A clip's prompt must stand on its own (2026-10-09, live: Lake Nyos prompts read "Environment: Same
rural village. Lighting: Natural daylight." and were 380-500 characters; a fresh generation has never
seen "the same village"). The compiler removes relative / unspecified wording where it can, and
`PromptCompletenessService` reports what is left on the Prompts tab before credits are spent.
"""

from __future__ import annotations

import pytest

from src.models.cinematic_prompt import CinematicPromptPackage, ResolvedCinematicPrompt
from src.models.enriched_scene_prompt import EnrichedScenePrompt
from src.models.project_look import ProjectLook
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.cinematic_prompt_compilation_service import (
    CinematicPromptCompilationService,
)
from src.services.prompt_completeness_service import (
    MIN_LIVE_PROMPT_CHARACTERS,
    FindingCode,
    PromptCompletenessService,
    check_prompt_text,
)
from src.services.prompt_wording import (
    is_unspecified,
    relative_words_in,
    without_leading_relative_wording,
)
from tests.test_cinematic_prompt_compilation_service import (
    _bible,
    _scene,
    _shot_plan,
)

_GOOD = (
    "Identity: A cluster of simple rural homes with mud-brick walls and corrugated roofs. "
    "Environment: Hillside village among banana trees. Lighting: Flat overcast daylight, "
    "no hard shadows. Action progression: The camera holds on the huts as mist drifts "
    "between them, nothing moves. Composition: Wide, low angle, rule of thirds. "
    "Lens/camera: 35mm, wide shot, eye level, slow push-in. Duration: 8 seconds. "
) + "Muted earth tones with a cool grey-green grade. " * 6


def _codes(text: str, **kwargs) -> set[FindingCode]:  # type: ignore[no-untyped-def]
    return {f.code for f in check_prompt_text(text, **kwargs)}


# ------------------------------------------------------------------------- wording


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Same rural village", ["same"]),
        ("The same village as before", ["the same", "as before"]),
        ("Similar to scene two", ["similar to"]),
        ("Looks like the previous shot", ["previous shot"]),
        ("A hillside village", []),
        ("Some sameness of tone", []),
    ],
)
def test_relative_wording_is_found(text: str, expected: list[str]) -> None:
    assert relative_words_in(text) == expected


@pytest.mark.parametrize("value", ["unspecified", "Unspecified.", " ", "", "n/a", None])
def test_unspecified_values(value: str | None) -> None:
    assert is_unspecified(value) is True


def test_a_real_value_is_not_unspecified() -> None:
    assert is_unspecified("Flat overcast daylight") is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Same rural village", "Rural village"),
        ("The same village", "Village"),
        ("same", ""),
        ("Hill village", "Hill village"),
        ("A village, same as before", "A village, same as before"),
    ],
)
def test_a_leading_same_is_dropped(text: str, expected: str) -> None:
    assert without_leading_relative_wording(text) == expected


# ------------------------------------------------------------------------ the check


def test_a_prompt_that_names_everything_in_full_has_no_findings() -> None:
    assert len(_GOOD) >= MIN_LIVE_PROMPT_CHARACTERS
    assert check_prompt_text(_GOOD) == []


def test_relative_wording_is_flagged_and_named() -> None:
    findings = check_prompt_text(_GOOD + " Environment as before.")

    assert any(
        f.code == FindingCode.RELATIVE_WORDING and "'as before'" in f.message
        for f in findings
    )


def test_an_unspecified_environment_or_lighting_is_flagged() -> None:
    text = _GOOD.replace("Hillside village among banana trees", "unspecified")
    findings = check_prompt_text(text)

    assert any(
        f.code == FindingCode.UNSPECIFIED and "environment" in f.message
        for f in findings
    )

    text = _GOOD.replace("Flat overcast daylight, no hard shadows", "Unspecified")

    assert any(
        f.code == FindingCode.UNSPECIFIED and "lighting" in f.message
        for f in check_prompt_text(text)
    )


def test_a_short_prompt_is_flagged_with_its_length() -> None:
    short = (
        "Identity: x. Environment: Village. Lighting: Daylight. Action progression: y. "
    )
    findings = check_prompt_text(short)

    assert FindingCode.TOO_SHORT in {f.code for f in findings}
    assert any(str(len(short)) in f.message for f in findings)


def test_the_continuation_sentence_of_a_later_sub_clip_is_not_relative_wording() -> (
    None
):
    text = _GOOD + (
        " This clip continues directly from the previous one - for visual continuity, "
        "use the previous clip's own last frame as a reference image if your generator "
        "supports it."
    )

    assert FindingCode.RELATIVE_WORDING not in _codes(text)


def test_a_graphic_scene_is_judged_on_relative_wording_only() -> None:
    graphic = "Environment: unspecified. Lighting: unspecified. Short. "

    assert _codes(graphic, graphic=True) == set()
    assert _codes(graphic + "Same as before.", graphic=True) == {
        FindingCode.RELATIVE_WORDING
    }


# ------------------------------------------------- the compiler removes what it can


def _compile(bible, project_look=None):  # type: ignore[no-untyped-def]
    package = CinematicPromptCompilationService().compile(
        scenes=[_scene(1)],
        shot_plan=_shot_plan(),
        visual_continuity_bible=bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
        project_look=project_look,
    )
    prompt = package.prompt_for_scene(1)
    assert prompt is not None

    return prompt.prompt_text


def test_a_leading_same_in_the_environment_is_dropped() -> None:
    bible = _bible()
    bible.clip_entries[0].outgoing_state.location = "Same rural village"

    text = _compile(bible)

    assert "Environment: Rural village." in text
    assert "Same rural village" not in text


def test_an_unspecified_environment_takes_the_place_on_screen() -> None:
    from src.models.visual_continuity import (
        CanonicalEntityIdentity,
        CanonicalEntityType,
    )

    bible = _bible()
    bible.identities.append(
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.LOCATION,
            name="The village",
            canonical_description="A hillside village of thatched huts.",
        )
    )
    entry = bible.clip_entries[0]
    entry.outgoing_state.location = "unspecified"
    entry.entity_names = ["Captain Briggs", "The village"]
    entry.on_screen_entity_names = ["The village"]

    text = _compile(bible)

    assert "Environment: The village." in text


def test_an_unspecified_environment_with_no_place_is_left_for_the_check_to_flag() -> (
    None
):
    bible = _bible()
    bible.clip_entries[0].outgoing_state.location = "unspecified"

    assert "Environment: unspecified." in _compile(bible)


def test_unspecified_lighting_takes_the_project_look_or_a_consistency_line() -> None:
    bible = _bible()
    bible.clip_entries[0].outgoing_state.lighting = "unspecified"

    assert "Lighting: natural light, consistent with the surrounding scenes." in (
        _compile(bible)
    )
    assert "Lighting: Cool dawn light." in _compile(
        bible, ProjectLook(lighting="Cool dawn light.")
    )


def test_a_concrete_environment_and_lighting_are_untouched() -> None:
    text = _compile(_bible())

    assert "Environment: The deck." in text
    assert "Lighting: Bright." in text


# ------------------------------------------------------------- the report for a job


class _FakeEnriched:
    def __init__(self, texts: dict[int, str]) -> None:
        self._texts = texts

    def build_entries(self, *, job, scene):  # type: ignore[no-untyped-def]
        return [
            EnrichedScenePrompt(
                scene_number=scene.scene_number,
                base_prompt_text=self._texts[scene.scene_number],
            )
        ]


def _job(scenes: int = 3, *, with_package: bool = True) -> VideoJob:
    job = VideoJob(
        project_name="Lake Nyos",
        channel_name="Channel",
        niche="documentary",
        topic="Lake Nyos",
    )
    job.scenes = [
        Scene(
            scene_number=n,
            title=f"Scene {n}",
            narration=f"Narration {n}.",
            visual_prompt=f"Visual {n}.",
            estimated_duration_seconds=8,
        )
        for n in range(1, scenes + 1)
    ]

    if with_package:
        job.cinematic_prompt_package = CinematicPromptPackage(
            script_lock_hash="hash123",
            prompts=[
                ResolvedCinematicPrompt(
                    scene_number=1, script_lock_hash="hash123", prompt_text="x"
                )
            ],
        )

    return job


def test_the_report_lists_the_scenes_with_a_thin_prompt() -> None:
    service = PromptCompletenessService(
        _FakeEnriched({1: _GOOD, 2: "Environment: Same village.", 3: _GOOD})  # type: ignore[arg-type]
    )

    report = service.report(_job())

    assert report.checked is True
    assert report.is_complete is False
    assert report.flagged_scene_numbers == [2]
    assert report.findings_for(1) == []
    assert {f.code for f in report.findings_for(2)} >= {FindingCode.RELATIVE_WORDING}


def test_a_report_with_nothing_wrong_is_complete() -> None:
    service = PromptCompletenessService(_FakeEnriched({1: _GOOD, 2: _GOOD, 3: _GOOD}))  # type: ignore[arg-type]

    report = service.report(_job())

    assert report.checked is True
    assert report.is_complete is True
    assert report.flagged_scene_numbers == []


def test_nothing_is_reported_before_prompts_are_compiled() -> None:
    service = PromptCompletenessService(_FakeEnriched({}))  # type: ignore[arg-type]

    report = service.report(_job(with_package=False))

    assert report.checked is False
    assert report.scenes == []
