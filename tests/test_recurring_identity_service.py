"""
Characters and places the operator names by hand (live, 2026-10-07: the Lake Nyos
bible found one identity, so scenes 1-11 had no reference and drifted apart).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest

from src.models.media_strategy import SceneSourceType
from src.models.scene import Scene
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.recurring_identity_service import (
    RecurringIdentityService,
    carry_over_manual_identities,
    format_scene_numbers,
    parse_scene_numbers,
)
from src.services.reference_frame_selection_service import (
    ReferenceFrameSelection,
    ReferenceKind,
    ReferenceSelectionStatus,
)
from tests.test_content_studio_content_intelligence_gui import (  # noqa: F401
    qapp as qapp,  # noqa: PLC0414 - fixture
)


def _job(scene_count: int = 6) -> VideoJob:
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
        for n in range(1, scene_count + 1)
    ]
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="Lake Nyos",
                canonical_description="A crater lake.",
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=n,
                incoming_state=VisualState(),
                shot_action=f"Shot {n}.",
                outgoing_state=VisualState(),
                entity_names=["Lake Nyos"],
                on_screen_entity_names=[],
            )
            for n in range(1, scene_count + 1)
        ],
    )

    return job


class _Selector:
    """Stands in for the face/frame picker: every clip yields a frame whose value
    is the scene number, so the best one is easy to predict."""

    def __init__(self, tmp_path: Path, *, available: bool = True) -> None:
        self._tmp = tmp_path
        self._available = available
        self.calls: list[tuple[str, ReferenceKind]] = []

    def is_available(self) -> bool:
        return self._available

    def select(
        self, *, video_path: str, output_path: str, kind: ReferenceKind
    ) -> ReferenceFrameSelection:
        self.calls.append((video_path, kind))
        Path(output_path).write_bytes(video_path.encode())
        value = float(Path(video_path).stem.split("_")[-1])

        return ReferenceFrameSelection(
            status=ReferenceSelectionStatus.SELECTED,
            output_path=output_path,
            score=0.9,
            raw_value=value,
        )


def _service(tmp_path: Path, *, available: bool = True) -> RecurringIdentityService:
    return RecurringIdentityService(
        selection_service=_Selector(tmp_path, available=available),
        storage_root=tmp_path / "frames",
    )


def _add_clip(job: VideoJob, tmp_path: Path, scene_number: int) -> None:
    path = tmp_path / f"clip_{scene_number}.mp4"
    path.write_bytes(b"video")
    job.video_clips.append(
        VideoClip(
            scene_number=scene_number,
            source_type=SceneSourceType.AI_GENERATE,
            duration_seconds=8,
            local_file=str(path),
        )
    )


# ----------------------------------------------------------- scene numbers


def test_scene_numbers_accept_ranges_and_lists() -> None:
    assert parse_scene_numbers("1-3, 5", {1, 2, 3, 4, 5}) == [1, 2, 3, 5]
    assert parse_scene_numbers("5 2", {1, 2, 3, 4, 5}) == [2, 5]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "Say which scenes"),
        ("one", "not a scene number"),
        ("5-2", "runs backwards"),
        ("1-9", "no scene 7"),
    ],
)
def test_scene_numbers_reject_bad_input_in_plain_words(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_scene_numbers(text, {1, 2, 3, 4, 5, 6})


def test_scene_numbers_format_back_to_ranges() -> None:
    assert format_scene_numbers([8, 1, 2, 3, 5, 7]) == "1-3, 5, 7-8"


# ----------------------------------------------------------------- add / edit


def test_adding_marks_the_scenes_and_adds_the_identity(tmp_path: Path) -> None:
    job = _job()

    identity = _service(tmp_path).add(
        job,
        name="  Grandmother ",
        kind=CanonicalEntityType.PERSON,
        description="An elderly woman with grey hair, in a floral robe.",
        scene_text="1-3, 5",
    )

    assert identity.is_manual is True
    assert identity.name == "Grandmother"

    bible = job.visual_continuity_bible
    assert bible is not None
    assert bible.identities[-1] is identity

    for number in (1, 2, 3, 5):
        entry = bible.entry_for_scene(number)
        assert entry is not None
        assert "Grandmother" in entry.entity_names
        assert "Grandmother" in entry.on_screen_entity_names

    for number in (4, 6):
        entry = bible.entry_for_scene(number)
        assert entry is not None
        assert "Grandmother" not in entry.entity_names


def test_adding_needs_a_bible(tmp_path: Path) -> None:
    job = _job()
    job.visual_continuity_bible = None

    with pytest.raises(ValueError, match="continuity bible first"):
        _service(tmp_path).add(
            job,
            name="Grandmother",
            kind=CanonicalEntityType.PERSON,
            description="An elderly woman.",
            scene_text="1",
        )


@pytest.mark.parametrize(
    ("name", "description", "message"),
    [
        ("", "An elderly woman.", "Give it a name"),
        ("Grandmother", "  ", "Describe what it looks like"),
        ("lake nyos", "A lake.", "already a character or place"),
        ("G" * 61, "An elderly woman.", "longer than 60"),
        ("Grandmother", "d" * 401, "longer than 400"),
    ],
)
def test_adding_rejects_bad_input_without_changing_the_job(
    tmp_path: Path, name: str, description: str, message: str
) -> None:
    job = _job()
    before = job.visual_continuity_bible.model_dump()  # type: ignore[union-attr]

    with pytest.raises(ValueError, match=message):
        _service(tmp_path).add(
            job,
            name=name,
            kind=CanonicalEntityType.PERSON,
            description=description,
            scene_text="1",
        )

    assert job.visual_continuity_bible.model_dump() == before  # type: ignore[union-attr]


def test_editing_changes_the_scenes_and_keeps_the_reference(tmp_path: Path) -> None:
    job = _job()
    service = _service(tmp_path)
    service.add(
        job,
        name="Grandmother",
        kind=CanonicalEntityType.PERSON,
        description="An elderly woman.",
        scene_text="1-2",
    )
    identity = job.visual_continuity_bible.identities[-1]  # type: ignore[union-attr]
    identity.reference_asset_ids = ["asset-1"]

    service.update(
        job,
        "Grandmother",
        new_name="Nana",
        description="An elderly woman, grey hair.",
        scene_text="2-3",
    )

    bible = job.visual_continuity_bible
    assert bible is not None
    assert identity.name == "Nana"
    assert identity.reference_asset_ids == ["asset-1"]
    assert service.scenes_of(job, "Nana") == [2, 3]

    for entry in bible.clip_entries:
        assert "Grandmother" not in entry.entity_names
        assert "Grandmother" not in entry.on_screen_entity_names


def test_removing_clears_the_identity_and_its_marks(tmp_path: Path) -> None:
    job = _job()
    service = _service(tmp_path)
    service.add(
        job,
        name="Grandmother",
        kind=CanonicalEntityType.PERSON,
        description="An elderly woman.",
        scene_text="1-6",
    )

    service.remove(job, "Grandmother")

    bible = job.visual_continuity_bible
    assert bible is not None
    assert [i.name for i in bible.identities] == ["Lake Nyos"]
    assert all("Grandmother" not in e.entity_names for e in bible.clip_entries)


def test_a_generated_identity_cannot_be_edited_or_removed_here(
    tmp_path: Path,
) -> None:
    job = _job()

    with pytest.raises(ValueError, match="came from the generated bible"):
        _service(tmp_path).remove(job, "Lake Nyos")


# ------------------------------------------------------------------ reference


def test_the_reference_is_taken_from_the_best_frame_of_its_scenes(
    tmp_path: Path,
) -> None:
    job = _job()
    service = _service(tmp_path)
    service.add(
        job,
        name="Grandmother",
        kind=CanonicalEntityType.PERSON,
        description="An elderly woman.",
        scene_text="2-4",
    )

    for number in (1, 2, 3, 4, 5):
        _add_clip(job, tmp_path, number)

    result = service.fill_reference(job, "Grandmother")

    identity = job.visual_continuity_bible.identities[-1]  # type: ignore[union-attr]
    assert result.attached is True
    assert "scene 4" in result.detail  # best of its own scenes; scene 5 is not its
    assert len(identity.reference_asset_ids) == 1

    stored = job.extracted_frame_asset_index.assets[0]
    assert stored.metadata["named_by_operator"] is True
    assert stored.metadata["reference_kind"] == "person"


def test_a_place_gets_a_place_reference(tmp_path: Path) -> None:
    job = _job()
    service = _service(tmp_path)
    service.add(
        job,
        name="The village",
        kind=CanonicalEntityType.LOCATION,
        description="A hillside village of thatched huts.",
        scene_text="1",
    )
    _add_clip(job, tmp_path, 1)
    selector = service._selection
    assert isinstance(selector, _Selector)

    service.fill_reference(job, "The village")

    assert selector.calls[0][1] == ReferenceKind.ENVIRONMENT


def test_no_generated_clip_is_not_a_failure_and_changes_nothing(
    tmp_path: Path,
) -> None:
    job = _job()
    service = _service(tmp_path)
    service.add(
        job,
        name="Grandmother",
        kind=CanonicalEntityType.PERSON,
        description="An elderly woman.",
        scene_text="1-2",
    )

    result = service.fill_reference(job, "Grandmother")

    assert result.attached is False
    assert "first one that is made" in result.detail
    assert job.visual_continuity_bible.identities[-1].reference_asset_ids == []  # type: ignore[union-attr]


def test_without_frame_detection_it_says_so(tmp_path: Path) -> None:
    job = _job()
    service = _service(tmp_path, available=False)
    service.add(
        job,
        name="Grandmother",
        kind=CanonicalEntityType.PERSON,
        description="An elderly woman.",
        scene_text="1",
    )
    _add_clip(job, tmp_path, 1)

    result = service.fill_reference(job, "Grandmother")

    assert result.attached is False
    assert "not available" in result.detail


def test_an_existing_reference_is_kept_unless_replacement_is_asked_for(
    tmp_path: Path,
) -> None:
    job = _job()
    service = _service(tmp_path)
    service.add(
        job,
        name="Grandmother",
        kind=CanonicalEntityType.PERSON,
        description="An elderly woman.",
        scene_text="1",
    )
    identity = job.visual_continuity_bible.identities[-1]  # type: ignore[union-attr]
    identity.reference_asset_ids = ["asset-1"]
    _add_clip(job, tmp_path, 1)

    kept = service.fill_reference(job, "Grandmother")

    assert kept.attached is True
    assert identity.reference_asset_ids == ["asset-1"]

    service.fill_reference(job, "Grandmother", replace=True)

    assert identity.reference_asset_ids != ["asset-1"]


# ------------------------------------------------------------ regenerate keeps


def test_regenerating_the_bible_keeps_the_operators_identities(
    tmp_path: Path,
) -> None:
    job = _job()
    service = _service(tmp_path)
    service.add(
        job,
        name="Grandmother",
        kind=CanonicalEntityType.PERSON,
        description="An elderly woman.",
        scene_text="1-3, 5",
    )
    job.visual_continuity_bible.identities[-1].reference_asset_ids = ["asset-1"]  # type: ignore[union-attr]
    previous = job.visual_continuity_bible

    rebuilt = _job(scene_count=4).visual_continuity_bible
    assert rebuilt is not None

    carried = carry_over_manual_identities(previous, rebuilt)

    assert carried == 1
    kept = next(i for i in rebuilt.identities if i.name == "Grandmother")
    assert kept.is_manual is True
    assert kept.reference_asset_ids == ["asset-1"]

    for number in (1, 2, 3):
        entry = rebuilt.entry_for_scene(number)
        assert entry is not None
        assert "Grandmother" in entry.on_screen_entity_names

    # Scene 5 does not exist in the rebuilt bible; nothing breaks, nothing is added.
    assert rebuilt.entry_for_scene(5) is None
    assert rebuilt.entry_for_scene(4).on_screen_entity_names == []  # type: ignore[union-attr]


def test_a_generated_identity_with_the_same_name_wins_over_the_carried_one(
    tmp_path: Path,
) -> None:
    job = _job()
    service = _service(tmp_path)
    service.add(
        job,
        name="Grandmother",
        kind=CanonicalEntityType.PERSON,
        description="Mine.",
        scene_text="1",
    )

    rebuilt = _job().visual_continuity_bible
    assert rebuilt is not None
    rebuilt.identities.append(
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.PERSON,
            name="grandmother",
            canonical_description="Generated.",
        )
    )

    assert carry_over_manual_identities(job.visual_continuity_bible, rebuilt) == 0
    assert [
        i.canonical_description
        for i in rebuilt.identities
        if i.name.lower() == "grandmother"
    ] == ["Generated."]


# ------------------------------------------------------------ Content Studio


def _studio_view_with_bible():  # type: ignore[no-untyped-def]
    from src.desktop.job_store import InMemoryJobStore
    from tests.test_content_studio_content_intelligence_gui import _job as studio_job
    from tests.test_content_studio_content_intelligence_gui import _view as studio_view

    store = InMemoryJobStore()
    job = studio_job()
    source = _job()
    job.scenes = source.scenes
    job.visual_continuity_bible = source.visual_continuity_bible
    store.add(job)
    view = studio_view(store)
    view.set_job(job.id)
    errors: list[str] = []
    view._record_error = (  # type: ignore[method-assign]  # noqa: SLF001
        lambda j, message, **kwargs: errors.append(message)
    )

    return view, job, errors


def test_the_section_offers_a_form_for_a_new_character_or_place(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout, QWidget

    view, job, _errors = _studio_view_with_bible()
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._render_recurring_identities_section(layout, job)  # noqa: SLF001

    assert len(holder.findChildren(QLineEdit)) == 3
    buttons = [b.text() for b in holder.findChildren(QPushButton)]
    assert "Add to the video" in buttons
    assert "Suggest characters and places" in buttons


def test_saving_the_form_adds_the_identity_and_recompiles_the_prompts(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio_view_with_bible()
    recompiled: list[object] = []
    job.cinematic_prompt_package = object()  # type: ignore[assignment]
    view._content_intelligence_pipeline.run_cinematic_prompt_compilation = (  # type: ignore[method-assign]  # noqa: SLF001
        lambda j: recompiled.append(j) or j
    )
    view._recurring_form = {  # noqa: SLF001
        "name": "Grandmother",
        "kind": "person",
        "description": "An elderly woman with grey hair.",
        "scenes": "1-3",
    }

    view._handle_save_identity()  # noqa: SLF001

    assert errors == []
    identity = job.visual_continuity_bible.identities[-1]  # type: ignore[union-attr]
    assert identity.name == "Grandmother"
    assert identity.is_manual is True
    assert identity.entity_type == CanonicalEntityType.PERSON
    assert recompiled == [job]
    assert view._recurring_form["name"] == ""  # noqa: SLF001 - form cleared


def test_saving_a_bad_form_shows_the_reason_and_changes_nothing(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio_view_with_bible()
    view._recurring_form = {  # noqa: SLF001
        "name": "Grandmother",
        "kind": "person",
        "description": "",
        "scenes": "1-3",
    }

    view._handle_save_identity()  # noqa: SLF001

    assert len(errors) == 1
    assert "Describe what it looks like" in errors[0]
    assert [i.name for i in job.visual_continuity_bible.identities] == ["Lake Nyos"]  # type: ignore[union-attr]


def test_removing_from_the_list_takes_the_identity_out(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio_view_with_bible()
    view._recurring_form = {  # noqa: SLF001
        "name": "Grandmother",
        "kind": "person",
        "description": "An elderly woman.",
        "scenes": "1",
    }
    view._handle_save_identity()  # noqa: SLF001

    view._handle_remove_identity("Grandmother")  # noqa: SLF001

    assert errors == []
    assert [i.name for i in job.visual_continuity_bible.identities] == ["Lake Nyos"]  # type: ignore[union-attr]
