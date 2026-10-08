"""
What the character/place rows in Content Studio say about a reference (2026-10-08):
whether there is one, which scene's clip it came from, who picked it, and the picture -
so it is visible which identities still need attention. A reference only helps keep a
look the same ACROSS scenes, so an identity in a single scene gets no frame picker.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from src.models.asset_index import IndexedAsset, IndexedAssetSource, IndexedAssetType
from src.models.video_job import VideoJob
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
)
from src.services.reference_status import reference_status
from tests.test_recurring_identity_service import (  # noqa: F401
    _add_clip,
    _job,
    _mark_on_screen,
    _studio_view_with_bible,
)
from tests.test_recurring_identity_service import (
    qapp as qapp,  # noqa: PLC0414 - fixture
)


def _identity(job: VideoJob, name: str = "Lake Nyos") -> CanonicalEntityIdentity:
    assert job.visual_continuity_bible is not None

    return next(i for i in job.visual_continuity_bible.identities if i.name == name)


def _attach(
    job: VideoJob, tmp_path: Path, identity: CanonicalEntityIdentity, **metadata: object
) -> Path:
    image = tmp_path / "ref.jpg"
    image.write_bytes(b"jpg")
    asset = IndexedAsset(
        asset_type=IndexedAssetType.IMAGE,
        source=IndexedAssetSource.GENERATED,
        file_path=str(image),
        metadata=dict(metadata),
    )
    job.extracted_frame_asset_index.add(asset)
    identity.reference_asset_ids = [str(asset.id)]

    return image


# ------------------------------------------------------------------ the status


def test_no_reference_is_said_plainly() -> None:
    job = _job()

    status = reference_status(job, _identity(job))

    assert status.has_reference is False
    assert status.image_path is None
    assert "No reference picture yet" in status.text


def test_a_reference_names_its_scene_and_that_it_was_picked_automatically(
    tmp_path: Path,
) -> None:
    job = _job()
    image = _attach(job, tmp_path, _identity(job), scene_number=3)

    status = reference_status(job, _identity(job))

    assert status.has_reference is True
    assert status.image_path == str(image)
    assert status.from_scene == 3
    assert status.chosen_by_operator is False
    assert status.text == "Reference: a frame from scene 3 (picked automatically)."


def test_a_frame_chosen_in_the_picker_says_picked_by_you(tmp_path: Path) -> None:
    job = _job()
    _attach(job, tmp_path, _identity(job), scene_number=5, chosen_by_operator=True)

    status = reference_status(job, _identity(job))

    assert status.chosen_by_operator is True
    assert "picked by you" in status.text


def test_naming_an_identity_yourself_does_not_make_its_frame_your_pick(
    tmp_path: Path,
) -> None:
    """named_by_operator only records who named the identity - its frame was still
    chosen by the automatic selection."""

    job = _job()
    _attach(job, tmp_path, _identity(job), scene_number=2, named_by_operator=True)

    assert "picked automatically" in reference_status(job, _identity(job)).text


def test_a_reference_without_a_recorded_scene_still_reads_sensibly(
    tmp_path: Path,
) -> None:
    job = _job()
    _attach(job, tmp_path, _identity(job))

    status = reference_status(job, _identity(job))

    assert status.from_scene is None
    assert "a generated clip" in status.text


def test_a_missing_picture_file_is_reported_not_crashed_on(tmp_path: Path) -> None:
    job = _job()
    image = _attach(job, tmp_path, _identity(job), scene_number=1)
    image.unlink()

    status = reference_status(job, _identity(job))

    assert status.has_reference is True
    assert status.image_path is None
    assert "image file is missing" in status.text


def test_an_id_that_is_not_a_real_asset_is_treated_as_missing() -> None:
    job = _job()
    _identity(job).reference_asset_ids = ["old-asset"]

    assert "missing" in reference_status(job, _identity(job)).text

    _identity(job).reference_asset_ids = ["12345678-1234-5678-1234-567812345678"]

    assert "missing" in reference_status(job, _identity(job)).text


# ------------------------------------------------------- the Content Studio rows


def _render(view, job):  # type: ignore[no-untyped-def]
    holder = QWidget()
    layout = QVBoxLayout(holder)
    view._render_visual_continuity_section(layout, job)  # noqa: SLF001

    return holder


def _texts(holder: QWidget) -> list[str]:
    return [label.text() for label in holder.findChildren(QLabel)]


def _buttons(holder: QWidget) -> list[str]:
    return [b.text() for b in holder.findChildren(QPushButton)]


def test_a_generated_identity_shows_its_scenes_and_reference_state(  # type: ignore[no-untyped-def]
    qapp, tmp_path: Path
) -> None:
    view, job, _errors = _studio_view_with_bible()
    _mark_on_screen(job, "Lake Nyos", (1, 2, 3, 4, 5, 6))
    _attach(job, tmp_path, _identity(job), scene_number=2)

    texts = _texts(_render(view, job))

    assert any(
        "Scenes: 1-6" in t and "a frame from scene 2 (picked automatically)" in t
        for t in texts
    )


def test_an_identity_without_a_reference_says_so_in_its_row(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, _errors = _studio_view_with_bible()
    _mark_on_screen(job, "Lake Nyos", (1, 2, 3))

    assert any("No reference picture yet" in t for t in _texts(_render(view, job)))


def test_an_identity_in_one_scene_gets_no_frame_picker_and_a_reason(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, _errors = _studio_view_with_bible()
    _mark_on_screen(job, "Lake Nyos", (1, 2, 3, 4, 5, 6))
    bible = job.visual_continuity_bible
    assert bible is not None
    bible.identities.append(
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.PERSON,
            name="Baby",
            canonical_description="An infant.",
        )
    )

    for entry in bible.clip_entries:
        if entry.scene_number == 4:
            entry.on_screen_entity_names.append("Baby")

    holder = _render(view, job)

    # Lake Nyos (6 scenes) keeps its picker; Baby (1 scene) has none
    assert _buttons(holder).count("Choose a reference frame") == 1
    assert any("Appears in one scene only" in t for t in _texts(holder))


def test_an_identity_you_added_for_one_scene_has_no_frame_picker(  # type: ignore[no-untyped-def]
    qapp, tmp_path: Path
) -> None:
    view, job, _errors = _studio_view_with_bible()
    _add_clip(job, tmp_path, 1)
    view._recurring_identity_service.add(  # noqa: SLF001
        job,
        name="Grandmother",
        kind=CanonicalEntityType.PERSON,
        description="An elderly woman.",
        scene_text="1",
    )

    holder = _render(view, job)
    choose = [
        b
        for b in holder.findChildren(QPushButton)
        if b.text() == "Choose another frame"
    ]

    assert choose, "the button is built but hidden"
    assert all(b.isHidden() for b in choose)
    assert any("Appears in one scene only" in t for t in _texts(holder))


def test_an_identity_in_no_scene_says_so_and_has_no_picker(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, _errors = _studio_view_with_bible()  # nobody is marked on screen

    holder = _render(view, job)

    assert "Choose a reference frame" not in _buttons(holder)
    assert any("Not in any scene yet" in t for t in _texts(holder))
