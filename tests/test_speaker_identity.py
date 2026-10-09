"""
Character-Oriented Video mode, step 4 (2026-10-09): every character who speaks becomes a recurring
person - marked on the scenes they speak in, so their description repeats in each of those prompts and
their reference picture (taken from their first clip) is attached to the later ones. A speaker the
bible already has is marked, not added twice; adding is idempotent, so it is safe after every
regeneration of the bible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.dialogue import DialogueLine
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.recurring_identity_service import RecurringIdentityService
from src.services.speaker_identity_service import (
    SpeakerIdentityService,
    placeholder_description,
)
from tests.test_recurring_identity_service import _Selector


def _lines(*pairs: tuple[str, str]) -> list[DialogueLine]:
    return [DialogueLine(speaker=s, text=t) for s, t in pairs]


def _job(*, identities: list[CanonicalEntityIdentity] | None = None) -> VideoJob:
    dialogue = {
        1: _lines(("Walter", "The train is late.")),
        2: _lines(
            ("Walter", "We cannot hold the post."), ("Frank", "Then start sorting.")
        ),
        3: _lines(("Frank", "I will be on the platform.")),
    }
    job = VideoJob(
        project_name="Post office",
        channel_name="Channel",
        niche="history",
        topic="The post office",
        genre_id="genre.history",
        character_oriented=True,
    )
    job.scenes = [
        Scene(
            scene_number=n,
            title=f"Scene {n}",
            narration=" ".join(line.text for line in lines),
            visual_prompt="v",
            estimated_duration_seconds=8,
            dialogue=lines,
        )
        for n, lines in dialogue.items()
    ]
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=identities or [],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=n,
                incoming_state=VisualState(),
                shot_action=f"Shot {n}.",
                outgoing_state=VisualState(),
            )
            for n in dialogue
        ],
    )

    return job


def _service(tmp_path: Path) -> SpeakerIdentityService:
    return SpeakerIdentityService(
        recurring_identity_service=RecurringIdentityService(
            selection_service=_Selector(tmp_path),  # type: ignore[arg-type]
            storage_root=tmp_path / "frames",
        )
    )


def _person(name: str) -> CanonicalEntityIdentity:
    return CanonicalEntityIdentity(
        entity_type=CanonicalEntityType.PERSON,
        name=name,
        canonical_description=f"{name}, a grey-haired clerk in a wool jacket.",
    )


def _marks(job: VideoJob, name: str) -> list[int]:
    assert job.visual_continuity_bible is not None

    return sorted(
        e.scene_number
        for e in job.visual_continuity_bible.clip_entries
        if name in e.on_screen_entity_names
    )


# --------------------------------------------------------------------------- reading


def test_speakers_are_listed_with_the_scenes_they_speak_in() -> None:
    assert SpeakerIdentityService.scenes_by_speaker(_job()) == {
        "Walter": [1, 2],
        "Frank": [2, 3],
    }


def test_a_project_with_no_dialogue_has_no_speakers() -> None:
    job = _job()
    for scene in job.scenes:
        scene.dialogue = []

    assert SpeakerIdentityService.scenes_by_speaker(job) == {}


# ---------------------------------------------------------------------------- adding


def test_every_speaker_becomes_a_person_marked_on_their_scenes(tmp_path: Path) -> None:
    job = _job()

    linked = _service(tmp_path).link(job)

    bible = job.visual_continuity_bible
    assert bible is not None
    people = {i.name: i for i in bible.identities}
    assert linked == ["Walter", "Frank"]
    assert set(people) == {"Walter", "Frank"}
    assert all(i.entity_type == CanonicalEntityType.PERSON for i in people.values())
    assert people["Walter"].canonical_description == placeholder_description("Walter")
    assert _marks(job, "Walter") == [1, 2]
    assert _marks(job, "Frank") == [2, 3]


def test_an_added_speaker_can_be_edited_or_removed_like_any_other_character(
    tmp_path: Path,
) -> None:
    job = _job()
    _service(tmp_path).link(job)

    assert all(i.is_manual for i in job.visual_continuity_bible.identities)  # type: ignore[union-attr]


def test_linking_twice_changes_nothing(tmp_path: Path) -> None:
    job = _job()
    service = _service(tmp_path)
    service.link(job)
    before = [i.model_dump(mode="json") for i in job.visual_continuity_bible.identities]  # type: ignore[union-attr]
    marks = _marks(job, "Walter")

    service.link(job)

    after = [i.model_dump(mode="json") for i in job.visual_continuity_bible.identities]  # type: ignore[union-attr]
    assert after == before
    assert _marks(job, "Walter") == marks


# -------------------------------------------------------------- the bible has them already


def test_a_person_the_bible_already_has_is_marked_not_added_twice(
    tmp_path: Path,
) -> None:
    job = _job(identities=[_person("Walter"), _person("Frank")])

    _service(tmp_path).link(job)

    names = [i.name for i in job.visual_continuity_bible.identities]  # type: ignore[union-attr]
    assert names == ["Walter", "Frank"]
    assert _marks(job, "Walter") == [1, 2]
    # their description is the bible's own, not the placeholder
    assert "grey-haired clerk" in job.visual_continuity_bible.identities[0].canonical_description  # type: ignore[union-attr]


def test_the_same_person_under_a_longer_name_is_recognised(tmp_path: Path) -> None:
    job = _job(identities=[_person("Walter Hale")])

    linked = _service(tmp_path).link(job)

    assert "Walter Hale" in linked
    assert [i.name for i in job.visual_continuity_bible.identities] == [  # type: ignore[union-attr]
        "Walter Hale",
        "Frank",
    ]
    assert _marks(job, "Walter Hale") == [1, 2]


def test_a_speaker_with_the_longer_name_matches_a_shorter_bible_name(
    tmp_path: Path,
) -> None:
    job = _job(identities=[_person("Walter")])
    job.scenes[0].dialogue = _lines(("Walter Hale", "The train is late."))

    SpeakerIdentityService.find_identity(job, "Walter Hale")

    assert SpeakerIdentityService.find_identity(job, "Walter Hale").name == "Walter"  # type: ignore[union-attr]


def test_two_possible_matches_are_no_match() -> None:
    job = _job(identities=[_person("Walter Hale"), _person("Walter Frye")])

    assert SpeakerIdentityService.find_identity(job, "Walter") is None


def test_a_place_with_the_speakers_name_is_not_the_speaker() -> None:
    place = CanonicalEntityIdentity(
        entity_type=CanonicalEntityType.LOCATION,
        name="Walter",
        canonical_description="A town called Walter.",
    )
    job = _job(identities=[place])

    assert SpeakerIdentityService.find_identity(job, "Walter") is None


# ------------------------------------------------------------------------------ problems


def test_linking_needs_the_bible(tmp_path: Path) -> None:
    job = _job()
    job.visual_continuity_bible = None

    with pytest.raises(ValueError, match="visual continuity bible"):
        _service(tmp_path).link(job)


def test_a_speaker_that_cannot_be_added_is_skipped_and_the_rest_are_linked(
    tmp_path: Path,
) -> None:
    # a PLACE already called Frank: the name is taken, so Frank cannot be added as a person
    place = CanonicalEntityIdentity(
        entity_type=CanonicalEntityType.LOCATION,
        name="Frank",
        canonical_description="A town called Frank.",
    )
    job = _job(identities=[place])

    linked = _service(tmp_path).link(job)

    assert linked == ["Walter"]


# ------------------------------------------------------------------ the pipeline step


def _pipeline_with_speakers(tmp_path: Path):  # type: ignore[no-untyped-def]
    from tests.test_content_intelligence_pipeline import _job as pipeline_job
    from tests.test_content_intelligence_pipeline import _pipeline

    pipeline, _ = _pipeline()
    job = pipeline.run_all(pipeline_job())
    pipeline.recurring_identity_service = RecurringIdentityService(
        selection_service=_Selector(tmp_path),  # type: ignore[arg-type]
        storage_root=tmp_path / "frames",
    )
    job.character_oriented = True
    job.scenes[0].dialogue = _lines(("Walter", "The train is late."))
    job.scenes[1].dialogue = _lines(("Walter", "Hold the post."), ("Frank", "Sort it."))

    return pipeline, job


def test_the_visual_continuity_step_links_the_speakers_of_a_character_project(
    tmp_path: Path,
) -> None:
    pipeline, job = _pipeline_with_speakers(tmp_path)

    pipeline.run_visual_continuity(job)

    bible = job.visual_continuity_bible
    assert bible is not None
    names = {i.name for i in bible.identities}
    assert {"Walter", "Frank"} <= names
    assert 1 in _marks(job, "Walter") and 2 in _marks(job, "Walter")
    assert _marks(job, "Frank") == [2]


def test_regenerating_the_bible_keeps_the_speakers_and_does_not_duplicate_them(
    tmp_path: Path,
) -> None:
    pipeline, job = _pipeline_with_speakers(tmp_path)
    pipeline.run_visual_continuity(job)
    pipeline.run_visual_continuity(job)

    names = [i.name for i in job.visual_continuity_bible.identities]  # type: ignore[union-attr]
    assert names.count("Walter") == 1 and names.count("Frank") == 1


def test_an_ordinary_project_gets_no_speaker_identities(tmp_path: Path) -> None:
    pipeline, job = _pipeline_with_speakers(tmp_path)
    job.character_oriented = False

    pipeline.run_visual_continuity(job)

    names = {i.name for i in job.visual_continuity_bible.identities}  # type: ignore[union-attr]
    assert "Walter" not in names and "Frank" not in names


def test_marking_a_person_who_is_not_in_the_bible_is_a_plain_error(
    tmp_path: Path,
) -> None:
    job = _job()
    service = RecurringIdentityService(
        selection_service=_Selector(tmp_path),  # type: ignore[arg-type]
        storage_root=tmp_path / "frames",
    )

    with pytest.raises(ValueError, match="no character or place named Ghost"):
        service.mark_scenes(job, "Ghost", [1])
