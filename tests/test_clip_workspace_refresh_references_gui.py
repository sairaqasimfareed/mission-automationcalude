"""
"Refresh references" button on the Clip check card (2026-10-06): re-pick each
character's and place's reference from the footage generated so far.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from src.models.asset_index import (  # noqa: E402
    IndexedAsset,
    IndexedAssetSource,
    IndexedAssetType,
)
from src.models.video_job import VideoJob  # noqa: E402
from src.services.reference_frame_selection_service import ReferenceKind  # noqa: E402
from src.services.reference_refresh_service import (  # noqa: E402
    ReferenceRefreshEntry,
    ReferenceRefreshOutcome,
    ReferenceRefreshReport,
)
from tests.test_clip_check_references import _bible  # noqa: E402
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    _build_view,
    _FakeJobStore,
    _FakeSceneVideoGenerationService,
    _job,
)
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)


class _StubRefresh:
    """Stands in for ReferenceRefreshService: no OpenCV, programmed result. Works
    on the copy it is given, as the real one does."""

    def __init__(self, *, replace: bool = True, raises: bool = False) -> None:
        self.calls = 0
        self._replace = replace
        self._raises = raises
        self.saw_job_ids: list[object] = []

    def refresh(self, job: VideoJob) -> ReferenceRefreshReport:
        self.calls += 1
        self.saw_job_ids.append(id(job))

        if self._raises:
            raise RuntimeError("detector exploded")

        entries = []

        if self._replace and job.visual_continuity_bible is not None:
            asset = IndexedAsset(
                asset_type=IndexedAssetType.IMAGE,
                source=IndexedAssetSource.GENERATED,
                file_path="new-reference.jpg",
            )
            job.extracted_frame_asset_index.add(asset)
            job.visual_continuity_bible.identities[0].reference_asset_ids = [
                str(asset.id)
            ]
            entries.append(
                ReferenceRefreshEntry(
                    name="Mara",
                    kind=ReferenceKind.PERSON,
                    outcome=ReferenceRefreshOutcome.REPLACED,
                    detail="new reference taken from scene 2 (face score 0.30 to 0.80).",
                )
            )
        else:
            entries.append(
                ReferenceRefreshEntry(
                    name="Mara",
                    kind=ReferenceKind.PERSON,
                    outcome=ReferenceRefreshOutcome.KEPT,
                    detail="the current reference is as good as anything in the "
                    "footage - kept.",
                )
            )

        return ReferenceRefreshReport(entries=entries)


def _view(stub: _StubRefresh, *, with_bible: bool = True):  # type: ignore[no-untyped-def]
    job = _job(1, 2)

    if with_bible:
        job.visual_continuity_bible = _bible([1, 2])

    store = _FakeJobStore(job)
    view = _build_view(job, service=_FakeSceneVideoGenerationService(), job_store=store)
    view._reference_refresh_service = stub  # type: ignore[assignment]  # noqa: SLF001
    view.refresh(job)
    _flush()

    return view, job, store


def _flush() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _refresh_button(view) -> QPushButton | None:  # type: ignore[no-untyped-def]
    _flush()

    return next(
        (
            b
            for b in view.findChildren(QPushButton)
            if b.text() in ("Refresh references", "Refreshing references...")
        ),
        None,
    )


def _texts(view) -> list[str]:  # type: ignore[no-untyped-def]
    job = view._current_job()  # noqa: SLF001

    if job is not None:
        view.refresh(job)

    _flush()

    return [label.text() for label in view.findChildren(QLabel)]


def _wait(app: QApplication, view) -> None:  # type: ignore[no-untyped-def]
    for thread, _worker in list(view._refresh_threads.values()):  # noqa: SLF001
        thread.wait(3000)

    for _ in range(30):
        app.processEvents()


def test_the_button_is_offered_when_the_project_has_characters_or_places(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, _, _ = _view(_StubRefresh())
    button = _refresh_button(view)

    assert button is not None
    assert button.isEnabled()
    assert not button.isHidden()


def test_the_button_is_hidden_when_there_is_no_continuity_bible(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, _, _ = _view(_StubRefresh(), with_bible=False)
    button = _refresh_button(view)

    assert button is None or button.isHidden()


def test_pressing_it_re_picks_and_saves_the_new_reference(
    qapp: QApplication,  # noqa: F811
) -> None:
    stub = _StubRefresh(replace=True)
    view, job, store = _view(stub)
    before = list(job.visual_continuity_bible.identities[0].reference_asset_ids)  # type: ignore[union-attr]

    button = _refresh_button(view)
    assert button is not None
    button.click()

    in_progress = (_refresh_button(view) or button).text()

    _wait(qapp, view)  # always join the worker before asserting anything

    assert "Refreshing" in in_progress

    after = list(job.visual_continuity_bible.identities[0].reference_asset_ids)  # type: ignore[union-attr]
    assert stub.calls == 1
    assert after != before and len(after) == 1
    assert job.extracted_frame_asset_index.get(after[0]) is not None
    assert store.added, "the refreshed job must be saved"

    texts = _texts(view)
    assert any(t.startswith("Refreshed 1 of 1 reference(s).") for t in texts)
    assert any("Mara: new reference taken from scene 2" in t for t in texts)


def test_it_works_on_a_copy_not_the_live_job(qapp: QApplication) -> None:  # noqa: F811
    stub = _StubRefresh(replace=True)
    view, job, _ = _view(stub)

    button = _refresh_button(view)
    assert button is not None
    button.click()
    _wait(qapp, view)

    assert stub.saw_job_ids and stub.saw_job_ids[0] != id(job)


def test_when_nothing_needed_replacing_it_says_so(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job, _ = _view(_StubRefresh(replace=False))
    before = list(job.visual_continuity_bible.identities[0].reference_asset_ids)  # type: ignore[union-attr]

    button = _refresh_button(view)
    assert button is not None
    button.click()
    _wait(qapp, view)

    assert any("No reference needed replacing." in t for t in _texts(view))
    assert list(job.visual_continuity_bible.identities[0].reference_asset_ids) == before  # type: ignore[union-attr]


def test_a_failure_is_reported_and_changes_nothing(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job, store = _view(_StubRefresh(raises=True))
    before = list(job.visual_continuity_bible.identities[0].reference_asset_ids)  # type: ignore[union-attr]

    button = _refresh_button(view)
    assert button is not None
    button.click()
    _wait(qapp, view)

    assert any(
        "References could not be refreshed: detector exploded" in t
        for t in _texts(view)
    )
    assert list(job.visual_continuity_bible.identities[0].reference_asset_ids) == before  # type: ignore[union-attr]
    assert not store.added
    assert _refresh_button(view).isEnabled()  # type: ignore[union-attr]  # can try again


def test_the_button_is_off_while_clips_are_being_generated(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, job, _ = _view(_StubRefresh())
    view._generating_job_ids.add(job.id)  # noqa: SLF001
    view.refresh(job)
    _flush()

    button = _refresh_button(view)

    assert button is not None and not button.isEnabled()


def test_the_default_service_is_a_real_one(
    qapp: QApplication, tmp_path: Path, monkeypatch  # type: ignore[no-untyped-def]  # noqa: F811
) -> None:
    monkeypatch.chdir(tmp_path)
    job = _job(1)
    view = _build_view(job, service=_FakeSceneVideoGenerationService())

    assert (
        type(view._reference_refresh_service).__name__ == "ReferenceRefreshService"
    )  # noqa: SLF001
