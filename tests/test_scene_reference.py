"""
A reference picture picked for ONE scene (2026-10-08, live: Lake Nyos village). A character or
place has one reference for every scene it is marked in; a scene that names none had nothing to
carry its scenery and light from the shots before it. The operator picks a frame of an earlier
clip for the scene; it replaces the automatic references, says what it is for in the prompt, and
the Clips tab shows which scenes have a reference and which still need one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton

from src.models.asset_index import AssetIndex
from src.models.google_flow_generation import GoogleFlowReferenceRole
from src.models.muse_generation import MuseReferenceRole
from src.models.scene import Scene
from src.models.visual_continuity import VisualState
from src.services.asset_storage_service import AssetStorageService
from src.services.recurring_identity_service import ReferenceCandidate
from src.services.scene_reference_override import (
    OVERRIDE_LABEL,
    OVERRIDE_PROMPT_SENTENCE,
    override_reference_for_scene,
    with_override_sentence,
)
from src.services.scene_reference_service import SceneReferenceService
from tests.test_recurring_identity_service import (  # noqa: F401
    _add_clip,
    _job,
    _ManySelector,
    _mark_on_screen,
)
from tests.test_recurring_identity_service import (
    qapp as qapp,  # noqa: PLC0414 - fixture
)


def _store_frame(job, tmp_path: Path, name: str = "frame.jpg", **metadata) -> str:  # type: ignore[no-untyped-def]
    source = tmp_path / name
    source.write_bytes(f"pixels-{name}".encode())
    stored = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=job.extracted_frame_asset_index
    ).store_extracted_frame(
        source_path=source,
        project_id="p",
        scene_number=1,
        title=name,
        metadata=dict(metadata) or {"scene_number": 1},
    )
    assert stored.success and stored.asset is not None

    return str(stored.asset.id)


def _service(tmp_path: Path) -> SceneReferenceService:
    return SceneReferenceService(
        selection_service=_ManySelector(tmp_path), storage_root=tmp_path / "storage"
    )


def _scene_of(job, number: int) -> Scene:  # type: ignore[no-untyped-def]
    return next(s for s in job.scenes if s.scene_number == number)


# ------------------------------------------------------------- the shared helper


def test_the_picked_picture_is_resolved_with_its_origin(tmp_path: Path) -> None:
    job = _job()
    scene = _scene_of(job, 3)
    scene.reference_override_asset_id = _store_frame(job, tmp_path, scene_number=1)

    override = override_reference_for_scene(job.extracted_frame_asset_index, scene)

    assert override is not None
    assert Path(override.source_path).is_file()
    assert override.from_scene == 1
    assert len(override.checksum) >= 32


def test_a_scene_without_a_pick_or_with_a_lost_picture_resolves_to_nothing(
    tmp_path: Path,
) -> None:
    job = _job()
    scene = _scene_of(job, 3)
    index = job.extracted_frame_asset_index

    assert override_reference_for_scene(index, scene) is None

    scene.reference_override_asset_id = "not-a-real-id"
    assert override_reference_for_scene(index, scene) is None

    scene.reference_override_asset_id = "12345678-1234-5678-1234-567812345678"
    assert override_reference_for_scene(index, scene) is None

    asset_id = _store_frame(job, tmp_path)
    scene.reference_override_asset_id = asset_id
    asset = index.get(asset_id)
    assert asset is not None
    Path(asset.file_path).unlink()

    assert override_reference_for_scene(index, scene) is None


def test_the_sentence_is_added_once() -> None:
    once = with_override_sentence("A wide shot of the village.")

    assert once.endswith(OVERRIDE_PROMPT_SENTENCE)
    assert with_override_sentence(once) == once


def test_a_scene_from_before_this_existed_loads_without_a_pick() -> None:
    data = _job().scenes[0].model_dump(mode="json")
    data.pop("reference_override_asset_id")

    assert Scene.model_validate(data).reference_override_asset_id is None


# ------------------------------------------------------------------- candidates


def test_only_clips_made_before_the_scene_are_offered_nearest_first(
    tmp_path: Path,
) -> None:
    job = _job(8)

    for number in (1, 2, 3, 5, 6):
        _add_clip(job, tmp_path, number)

    candidates = _service(tmp_path).candidates(
        job, 5, cache_directory=tmp_path / "cache"
    )

    scenes = [c.scene_number for c in candidates]

    assert set(scenes) == {1, 2, 3}  # scene 5's own clip and scene 6's are not offered
    assert scenes[0] == 3  # nearest first
    assert len(candidates) == 9  # three frames of each of three clips


def test_scenes_planned_in_the_same_place_come_first(tmp_path: Path) -> None:
    job = _job(8)
    assert job.visual_continuity_bible is not None

    for entry in job.visual_continuity_bible.clip_entries:
        entry.incoming_state = VisualState(
            location="Hill village" if entry.scene_number in (1, 6, 7) else "Map room"
        )

    for number in (1, 2, 3, 4, 5, 6):
        _add_clip(job, tmp_path, number)

    candidates = _service(tmp_path).candidates(
        job, 7, cache_directory=tmp_path / "cache", limit=30
    )
    order = []

    for c in candidates:
        if c.scene_number not in order:
            order.append(c.scene_number)

    # the village scenes (6 then 1) lead, then the nearest of the rest (5, 4, ...)
    assert order[:2] == [6, 1]
    assert order[2] == 5


def test_by_default_only_the_nearest_scenes_are_offered_and_all_on_request(
    tmp_path: Path,
) -> None:
    job = _job(12)

    for number in range(1, 11):
        _add_clip(job, tmp_path, number)

    service = _service(tmp_path)
    default = service.candidates(job, 11, cache_directory=tmp_path / "c1", limit=100)
    everything = service.candidates(
        job, 11, cache_directory=tmp_path / "c2", include_all=True, limit=100
    )

    assert {c.scene_number for c in default} == {10, 9, 8, 7}
    assert {c.scene_number for c in everything} == set(range(1, 11))


def test_there_is_a_plain_message_when_no_earlier_clip_exists(tmp_path: Path) -> None:
    job = _job()
    _add_clip(job, tmp_path, 4)  # only a LATER clip

    with pytest.raises(ValueError, match="No clip has been made before this scene"):
        _service(tmp_path).candidates(job, 2, cache_directory=tmp_path / "cache")


def test_there_is_a_plain_message_when_frame_detection_is_unavailable(
    tmp_path: Path,
) -> None:
    job = _job()
    _add_clip(job, tmp_path, 1)
    service = SceneReferenceService(
        selection_service=_ManySelector(tmp_path, available=False),
        storage_root=tmp_path / "storage",
    )

    with pytest.raises(ValueError, match="not available"):
        service.candidates(job, 3, cache_directory=tmp_path / "cache")


# --------------------------------------------------------------- set and clear


def _candidate(tmp_path: Path, scene: int = 1) -> ReferenceCandidate:
    image = tmp_path / f"cand{scene}.jpg"
    image.write_bytes(b"candidate pixels")

    return ReferenceCandidate(
        scene_number=scene,
        clip_sequence_index=0,
        image_path=str(image),
        value=1.0,
        time_seconds=1.1,
    )


def test_picking_a_frame_stores_it_and_records_it_on_the_scene(tmp_path: Path) -> None:
    job = _job()

    result = _service(tmp_path).set_override(job, 3, _candidate(tmp_path, scene=1))

    scene = _scene_of(job, 3)

    assert result.attached is True
    assert scene.reference_override_asset_id is not None
    asset = job.extracted_frame_asset_index.get(scene.reference_override_asset_id)
    assert asset is not None
    assert asset.metadata["override_for_scene"] == 3
    assert asset.metadata["scene_number"] == 1
    assert asset.metadata["chosen_by_operator"] is True
    assert _scene_of(job, 4).reference_override_asset_id is None  # only that scene


def test_a_frame_that_disappeared_cannot_be_picked(tmp_path: Path) -> None:
    job = _job()
    candidate = _candidate(tmp_path)
    Path(candidate.image_path).unlink()

    with pytest.raises(ValueError, match="no longer available"):
        _service(tmp_path).set_override(job, 3, candidate)


def test_a_scene_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        _service(tmp_path).set_override(_job(), 99, _candidate(tmp_path))


def test_removing_the_pick_returns_the_scene_to_automatic(tmp_path: Path) -> None:
    job = _job()
    service = _service(tmp_path)
    service.set_override(job, 3, _candidate(tmp_path))

    service.clear_override(job, 3)

    assert _scene_of(job, 3).reference_override_asset_id is None


# ------------------------------------------------------------------------ status


def test_a_scene_with_no_character_or_place_is_flagged_as_needing_one(
    tmp_path: Path,
) -> None:
    job = _job()  # nobody is marked on screen anywhere
    status = _service(tmp_path).status(job, _scene_of(job, 2))

    assert status.needs_reference is True
    assert status.has_reference is False
    assert status.role == "warning"
    assert "No character or place is marked" in status.text


def test_a_marked_place_with_a_reference_is_reported_with_its_source_scene(
    tmp_path: Path,
) -> None:
    job = _job()
    _mark_on_screen(job, "Lake Nyos", (2,))
    assert job.visual_continuity_bible is not None
    job.visual_continuity_bible.identities[0].reference_asset_ids = [
        _store_frame(job, tmp_path, scene_number=1)
    ]

    status = _service(tmp_path).status(job, _scene_of(job, 2))

    assert status.has_reference is True
    assert status.needs_reference is False
    assert status.role == "success"
    assert status.text == "Marked here: Lake Nyos (reference, from scene 1)."
    assert status.image_path is not None


def test_a_marked_place_without_a_reference_is_flagged(tmp_path: Path) -> None:
    job = _job()
    _mark_on_screen(job, "Lake Nyos", (2,))

    status = _service(tmp_path).status(job, _scene_of(job, 2))

    assert status.needs_reference is True
    assert status.text == "Marked here: Lake Nyos (no reference yet)."


def test_the_pick_is_reported_and_counts_as_a_reference(tmp_path: Path) -> None:
    job = _job()
    service = _service(tmp_path)
    service.set_override(job, 2, _candidate(tmp_path, scene=1))

    status = service.status(job, _scene_of(job, 2))

    assert status.has_override is True
    assert status.needs_reference is False
    assert status.text == "Reference: a frame of scene 1 (your pick)."
    assert 2 not in service.scenes_needing_reference(job)


def test_a_pick_whose_picture_is_gone_says_so_and_needs_a_new_one(
    tmp_path: Path,
) -> None:
    job = _job()
    service = _service(tmp_path)
    service.set_override(job, 2, _candidate(tmp_path))
    scene = _scene_of(job, 2)
    asset = job.extracted_frame_asset_index.get(scene.reference_override_asset_id or "")
    assert asset is not None
    Path(asset.file_path).unlink()

    status = service.status(job, scene)

    assert status.needs_reference is True
    assert "is missing" in status.text


def test_a_graphic_scene_needs_no_reference(tmp_path: Path) -> None:
    job = _job()
    assert job.visual_continuity_bible is not None
    job.visual_continuity_bible.clip_entries[1].incoming_state = VisualState(
        location="Informational graphic/overlay"
    )

    status = _service(tmp_path).status(job, _scene_of(job, 2))

    assert status.role == "muted"
    assert status.needs_reference is False
    assert "Graphic scene" in status.text
    assert 2 not in _service(tmp_path).scenes_needing_reference(job)


def test_the_count_lists_exactly_the_scenes_with_no_reference(tmp_path: Path) -> None:
    job = _job(4)
    service = _service(tmp_path)
    service.set_override(job, 2, _candidate(tmp_path))

    assert service.scenes_needing_reference(job) == [1, 3, 4]


# ------------------------------------------------- inside the two video providers


def _flow_service_and_job(tmp_path: Path, scene_number: int = 2):  # type: ignore[no-untyped-def]
    from src.models.google_flow_generation import GoogleFlowGenerationState
    from tests.test_scene_video_generation_service import (
        _job as flow_job,
    )
    from tests.test_scene_video_generation_service import (
        _real_video_file,
        _ScriptedProvider,
    )
    from tests.test_scene_video_generation_service import (
        _scene as flow_scene,
    )
    from tests.test_scene_video_generation_service import (
        _service as flow_service,
    )

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    scene = flow_scene(scene_number)
    scene.real_narration_duration_seconds = 3.0
    job = flow_job(scene)
    service = flow_service(
        provider,
        asset_storage_service=AssetStorageService(
            storage_root=tmp_path / "svc", asset_index=AssetIndex()
        ),
    )

    return service, job, scene, provider


def test_flow_attaches_exactly_the_picked_picture_and_says_what_it_is_for(
    tmp_path: Path,
) -> None:
    service, job, scene, provider = _flow_service_and_job(tmp_path)
    scene.reference_override_asset_id = _store_frame(job, tmp_path, scene_number=1)

    service.generate_one(job, scene.scene_number)

    request = provider.submitted_requests[0]

    assert len(request.reference_assets) == 1
    assert request.reference_assets[0].identity_name == OVERRIDE_LABEL
    assert request.reference_assets[0].role == GoogleFlowReferenceRole.LOCATION
    assert OVERRIDE_PROMPT_SENTENCE in request.prompt


def test_flow_without_a_pick_adds_no_sentence_and_no_picture(tmp_path: Path) -> None:
    service, job, scene, provider = _flow_service_and_job(tmp_path)

    service.generate_one(job, scene.scene_number)

    request = provider.submitted_requests[0]

    assert request.reference_assets == []
    assert OVERRIDE_PROMPT_SENTENCE not in request.prompt


def test_flow_pick_replaces_the_characters_references(tmp_path: Path) -> None:
    from tests.test_scene_video_generation_service import (
        _continuity_bible,
        _stored_reference_asset,
    )

    service, job, scene, provider = _flow_service_and_job(tmp_path)
    identity_asset = _stored_reference_asset(job, tmp_path)
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[identity_asset], scene_numbers=[scene.scene_number]
    )
    scene.reference_override_asset_id = _store_frame(
        job, tmp_path, name="picked.jpg", scene_number=1
    )

    service.generate_one(job, scene.scene_number)

    request = provider.submitted_requests[0]

    assert [r.identity_name for r in request.reference_assets] == [OVERRIDE_LABEL]


def test_flow_falls_back_to_the_characters_reference_when_the_pick_is_lost(
    tmp_path: Path,
) -> None:
    from tests.test_scene_video_generation_service import (
        _continuity_bible,
        _stored_reference_asset,
    )

    service, job, scene, provider = _flow_service_and_job(tmp_path)
    identity_asset = _stored_reference_asset(job, tmp_path)
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[identity_asset], scene_numbers=[scene.scene_number]
    )
    scene.reference_override_asset_id = "12345678-1234-5678-1234-567812345678"

    service.generate_one(job, scene.scene_number)

    request = provider.submitted_requests[0]

    assert len(request.reference_assets) == 1
    assert request.reference_assets[0].identity_name != OVERRIDE_LABEL
    assert OVERRIDE_PROMPT_SENTENCE not in request.prompt


def test_muse_attaches_exactly_the_picked_picture_and_says_what_it_is_for(
    tmp_path: Path,
) -> None:
    from src.models.muse_generation import MuseGenerationState
    from tests.test_muse_scene_video_generation_service import (
        _job as muse_job,
    )
    from tests.test_muse_scene_video_generation_service import (
        _real_video_file,
        _ScriptedProvider,
    )
    from tests.test_muse_scene_video_generation_service import (
        _scene as muse_scene,
    )
    from tests.test_muse_scene_video_generation_service import (
        _service as muse_service,
    )

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    scene = muse_scene(2)
    scene.real_narration_duration_seconds = 3.0
    job = muse_job(scene)
    service = muse_service(
        provider,
        asset_storage_service=AssetStorageService(
            storage_root=tmp_path / "svc", asset_index=AssetIndex()
        ),
    )
    scene.reference_override_asset_id = _store_frame(job, tmp_path, scene_number=1)

    service.generate_one(job, 2)

    request = provider.submitted_requests[0]

    assert len(request.reference_assets) == 1
    assert request.reference_assets[0].identity_name == OVERRIDE_LABEL
    assert request.reference_assets[0].role == MuseReferenceRole.LOCATION
    assert OVERRIDE_PROMPT_SENTENCE in request.prompt


# --------------------------------------------------------------------- Clip check


def test_the_clip_check_reports_a_pick_the_clip_was_made_without(
    tmp_path: Path,
) -> None:
    from src.models.clip_attachment_verification import (
        ClipVerificationIssueCode,
        ReferenceUse,
    )
    from src.models.google_flow_generation import GoogleFlowGenerationState
    from src.services.clip_attachment_verification_service import (
        ClipAttachmentVerificationService,
    )

    service, job, scene, _provider = _flow_service_and_job(tmp_path)
    service.generate_one(job, scene.scene_number)  # made WITHOUT a pick
    scene.reference_override_asset_id = _store_frame(job, tmp_path, scene_number=1)

    report = ClipAttachmentVerificationService(
        thumbnails_root=tmp_path / "thumbs"
    ).verify(job)
    result = next(s for s in report.scenes if s.scene_number == scene.scene_number)

    assert any(
        r.name == OVERRIDE_LABEL and r.state == ReferenceUse.NOT_ATTACHED
        for r in result.references
    )
    assert ClipVerificationIssueCode.REFERENCE_NOT_ATTACHED in {
        i.code for i in result.issues
    }
    assert GoogleFlowGenerationState.READY  # (the clip itself was made)


# ------------------------------------------------------------------ the Clips tab


def _clips_view(qapp, tmp_path: Path):  # type: ignore[no-untyped-def]
    from src.models.video_provider import VideoProvider
    from tests.test_clip_workspace_clip_length_labels_gui import _view

    view, job = _view(VideoProvider.MUSE, narration=5.0)
    view._scene_reference_service = SceneReferenceService(  # noqa: SLF001
        selection_service=_ManySelector(tmp_path), storage_root=tmp_path / "storage"
    )

    return view, job


def _labels(view) -> list[str]:  # type: ignore[no-untyped-def]
    return [label.text() for label in view.findChildren(QLabel)]


def _buttons(view) -> list[str]:  # type: ignore[no-untyped-def]
    return [b.text() for b in view.findChildren(QPushButton)]


def test_each_scene_row_says_whether_it_has_a_reference_and_offers_to_add_one(  # type: ignore[no-untyped-def]
    qapp, tmp_path: Path
) -> None:
    view, job = _clips_view(qapp, tmp_path)
    view.refresh(job)

    assert any("have no reference picture" in t for t in _labels(view))
    assert any("No character or place is marked" in t for t in _labels(view))
    assert "Add reference" in _buttons(view)


def test_a_picked_reference_changes_the_row_and_the_count(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, job = _clips_view(qapp, tmp_path)
    scene = job.scenes[0]
    view._scene_reference_service.set_override(  # noqa: SLF001
        job, scene.scene_number, _candidate(tmp_path)
    )
    view.refresh(job)

    texts = _labels(view)
    buttons = _buttons(view)

    assert any("(your pick)" in t for t in texts)
    assert "Change reference" in buttons
    assert "Remove my reference" in buttons
    assert any(t.startswith("0 of") and "have no reference picture" in t for t in texts)


def test_removing_the_pick_from_the_row_returns_to_automatic(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, job = _clips_view(qapp, tmp_path)
    scene = job.scenes[0]
    view._job_store.add(job)  # noqa: SLF001
    view._scene_reference_service.set_override(  # noqa: SLF001
        job, scene.scene_number, _candidate(tmp_path)
    )
    view.refresh(job)

    next(
        b for b in view.findChildren(QPushButton) if b.text() == "Remove my reference"
    ).click()

    assert scene.reference_override_asset_id is None


def test_the_filter_shows_only_scenes_without_a_reference(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QCoreApplication, QEvent

    view, job = _clips_view(qapp, tmp_path)
    view._job_store.add(job)  # noqa: SLF001
    view.set_job(job.id)
    view.refresh(job)

    def scene_lines() -> list[str]:
        # the previous build's labels are only deleted once Qt gets to them
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)

        return [t for t in _labels(view) if t.startswith("Scene 1:")]

    assert len(scene_lines()) >= 1  # the scene has no reference: listed
    box = next(
        b
        for b in view.findChildren(QCheckBox)
        if b.text() == "Show only scenes without a reference"
    )

    view._scene_reference_service.set_override(  # noqa: SLF001
        job, job.scenes[0].scene_number, _candidate(tmp_path)
    )
    view.refresh(job)

    assert len(scene_lines()) >= 1  # with the filter off it is still listed

    box = next(
        b
        for b in view.findChildren(QCheckBox)
        if b.text() == "Show only scenes without a reference"
    )
    box.setChecked(True)

    assert scene_lines() == []  # it has a reference now, so the filter hides it


def test_a_scene_with_nothing_earlier_gets_a_plain_message_not_a_crash(  # type: ignore[no-untyped-def]
    qapp, tmp_path: Path, monkeypatch
) -> None:
    from src.desktop.views import clip_workspace_view as module

    shown: list[str] = []
    monkeypatch.setattr(
        module,
        "show_recoverable_error",
        lambda _p, _t, message, **_k: shown.append(message),
    )
    view, job = _clips_view(qapp, tmp_path)
    view._job_store.add(job)  # noqa: SLF001
    view.set_job(job.id)
    view.refresh(job)

    view._handle_scene_reference(
        job.scenes[0].scene_number, include_all=False
    )  # noqa: SLF001
    deadline_threads = list(view._reference_threads.values())  # noqa: SLF001

    for thread, _worker in deadline_threads:
        thread.wait(20000)

    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()

    assert any("No clip has been made before this scene" in m for m in shown)
