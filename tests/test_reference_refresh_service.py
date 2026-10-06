"""
Reference refresh (2026-10-06): re-pick each character's and place's reference
from the footage generated so far, replacing the current one only when the new
frame is clearly better - so references taken by the old "last frame" rule can be
upgraded without regenerating anything.

The selection service is stubbed with programmed values; storage, the asset index
and the job are real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.media_strategy import SceneSourceType
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
)
from src.services.reference_frame_selection_service import (
    ReferenceFrameSelection,
    ReferenceKind,
    ReferenceSelectionStatus,
)
from src.services.reference_refresh_service import (
    ReferenceRefreshOutcome,
    ReferenceRefreshService,
)
from tests.test_clip_check_references import _job, _store_reference


class _Selector:
    """Per-clip programmed answers. `picks` maps (identity prefix, clip stem) to a
    value - the identity prefix is how the service names its temp files, which is
    how this stub knows who is being asked about."""

    def __init__(
        self,
        picks: dict[tuple[str, str], float] | None = None,
        current: dict[str, float] | None = None,
        *,
        available: bool = True,
        raises_for: set[str] | None = None,
    ) -> None:
        self._picks = picks or {}
        self._current = current or {}
        self._available = available
        self._raises_for = raises_for or set()
        self.asked: list[tuple[str, str]] = []

    def is_available(self) -> bool:
        return self._available

    def select(
        self, *, video_path: str, output_path: str, kind: ReferenceKind
    ) -> ReferenceFrameSelection:
        # <identity>_<scene>_<sequence>.jpg - the identity may itself contain
        # underscores (spaces become underscores), so peel the last two parts.
        who = "_".join(Path(output_path).stem.split("_")[:-2])
        stem = Path(video_path).stem
        self.asked.append((who, stem))

        if stem in self._raises_for:
            raise RuntimeError("unreadable clip")

        value = self._picks.get((who, stem))

        if value is None:
            return ReferenceFrameSelection(
                status=ReferenceSelectionStatus.NO_QUALIFYING_FACE, reason="none"
            )

        Path(output_path).write_bytes(f"new-{who}-{stem}".encode())

        return ReferenceFrameSelection(
            status=ReferenceSelectionStatus.SELECTED,
            output_path=output_path,
            score=value,
            raw_value=value,
            time_seconds=1.5,
        )

    def value_of_stored_reference(self, path: str, kind: ReferenceKind) -> float | None:
        # The stored picture's bytes are "picture of <name>" (see
        # _store_reference) - the file name is rewritten by storage.
        content = Path(path).read_bytes().decode()

        return self._current.get(content.removeprefix("picture of "))


def _service(selector: _Selector, tmp_path: Path) -> ReferenceRefreshService:
    return ReferenceRefreshService(
        selection_service=selector,  # type: ignore[arg-type]
        storage_root=tmp_path / "frames",
    )


def _entry(report, name: str):  # type: ignore[no-untyped-def]
    return next(e for e in report.entries if e.name == name)


def _mara(job):  # type: ignore[no-untyped-def]
    return next(i for i in job.visual_continuity_bible.identities if i.name == "Mara")


def _refs(job, name: str) -> list[str]:  # type: ignore[no-untyped-def]
    return list(
        next(
            i for i in job.visual_continuity_bible.identities if i.name == name
        ).reference_asset_ids
    )


# ---- people -----------------------------------------------------------


def test_a_person_gets_a_clearly_better_reference(tmp_path: Path) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    old_id = _refs(job, "Mara")[0]
    selector = _Selector(
        picks={("Mara", "2"): 0.80, ("Mara", "3"): 0.60},
        current={"Mara": 0.30},
    )

    report = _service(selector, tmp_path).refresh(job)

    entry = _entry(report, "Mara")
    assert entry.outcome == ReferenceRefreshOutcome.REPLACED
    assert entry.from_scene == 2
    assert entry.old_value == pytest.approx(0.30)
    assert entry.new_value == pytest.approx(0.80)
    assert "scene 2" in entry.detail and "0.30 to 0.80" in entry.detail

    new_id = _refs(job, "Mara")[0]
    assert new_id != old_id
    new_asset = job.extracted_frame_asset_index.get(new_id)
    assert new_asset is not None
    assert Path(new_asset.file_path).read_bytes() == b"new-Mara-2"
    assert new_asset.metadata["refreshed"] is True
    assert new_asset.metadata["replaced_asset_id"] == old_id
    assert new_asset.metadata["reference_kind"] == "person"
    assert new_asset.metadata["scene_number"] == 2
    # the old picture is kept in the index as history
    assert job.extracted_frame_asset_index.get(old_id) is not None


def test_a_small_improvement_is_not_worth_changing_the_reference(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    before = _refs(job, "Mara")
    selector = _Selector(picks={("Mara", "2"): 0.80}, current={"Mara": 0.75})

    report = _service(selector, tmp_path).refresh(job)

    assert _entry(report, "Mara").outcome == ReferenceRefreshOutcome.KEPT
    assert _refs(job, "Mara") == before


def test_nothing_clear_enough_in_the_footage_keeps_the_current_reference(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    before = _refs(job, "Mara")

    report = _service(_Selector(current={"Mara": 0.3}), tmp_path).refresh(job)

    entry = _entry(report, "Mara")
    assert entry.outcome == ReferenceRefreshOutcome.KEPT
    assert "kept the current reference" in entry.detail
    assert _refs(job, "Mara") == before


def test_a_person_with_no_reference_gets_one_if_the_footage_has_a_good_frame(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    assert _refs(job, "Mara") == []

    report = _service(_Selector(picks={("Mara", "3"): 0.7}), tmp_path).refresh(job)

    assert _entry(report, "Mara").outcome == ReferenceRefreshOutcome.REPLACED
    assert len(_refs(job, "Mara")) == 1


def test_a_reference_whose_file_is_gone_is_treated_as_having_none(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    asset = job.extracted_frame_asset_index.get(_refs(job, "Mara")[0])
    assert asset is not None
    Path(asset.file_path).unlink()

    report = _service(_Selector(picks={("Mara", "2"): 0.6}), tmp_path).refresh(job)

    assert _entry(report, "Mara").outcome == ReferenceRefreshOutcome.REPLACED


def test_the_best_frame_already_being_the_reference_is_not_a_change(
    tmp_path: Path,
) -> None:
    """Storing identical bytes reuses the existing asset - that is "kept"."""

    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    current = job.extracted_frame_asset_index.get(_refs(job, "Mara")[0])
    assert current is not None

    class _SameFrame(_Selector):
        def select(self, *, video_path, output_path, kind):  # type: ignore[no-untyped-def]
            Path(output_path).write_bytes(Path(current.file_path).read_bytes())

            return ReferenceFrameSelection(
                status=ReferenceSelectionStatus.SELECTED,
                output_path=output_path,
                score=0.9,
                raw_value=0.9,
            )

    before = _refs(job, "Mara")

    report = _service(_SameFrame(current={"Mara": 0.2}), tmp_path).refresh(job)

    assert _entry(report, "Mara").outcome == ReferenceRefreshOutcome.KEPT
    assert _refs(job, "Mara") == before


# ---- places -----------------------------------------------------------


def test_a_place_is_never_replaced_automatically(tmp_path: Path) -> None:
    """Live, 2026-10-06: a sharpness-based pick chose the honey jar again - with a
    text panel in frame - as a "better" kitchen. A frame cannot be told to be a
    place and not an object or an overlay, so places keep what they have."""

    job = _job(tmp_path)
    _store_reference(job, tmp_path, "The Apiary", from_scene=1)
    before = _refs(job, "The Apiary")
    selector = _Selector(
        picks={("The_Apiary", "2"): 500.0}, current={"The Apiary": 100.0}
    )

    report = _service(selector, tmp_path).refresh(job)

    entry = _entry(report, "The Apiary")
    assert entry.outcome == ReferenceRefreshOutcome.KEPT
    assert "not refreshed automatically" in entry.detail
    assert _refs(job, "The Apiary") == before
    assert not [who for who, _ in selector.asked if who == "The_Apiary"]


# ---- who counts as them ----------------------------------------------


def _with_second_person(job, *, jack_scenes: list[int]) -> None:  # type: ignore[no-untyped-def]
    bible = job.visual_continuity_bible
    bible.identities.append(
        CanonicalEntityIdentity(
            entity_type=CanonicalEntityType.PERSON,
            name="Jack",
            canonical_description="A neighbour.",
        )
    )

    for entry in bible.clip_entries:
        if entry.scene_number in jack_scenes:
            entry.on_screen_entity_names = ["Mara", "Jack", "The Apiary"]
        else:
            entry.on_screen_entity_names = ["Mara", "The Apiary"]


def test_only_scenes_where_a_person_is_alone_are_used_for_them(tmp_path: Path) -> None:
    """In a scene with two people a face could be either's, so while Mara has
    scenes of her own, only those are looked at for her."""

    job = _job(tmp_path)
    _with_second_person(job, jack_scenes=[1, 2])  # 3 and 4 are Mara alone
    selector = _Selector(picks={("Mara", "3"): 0.7})

    _service(selector, tmp_path).refresh(job)

    asked_for_mara = {stem for who, stem in selector.asked if who == "Mara"}

    assert asked_for_mara == {"3", "4"}


def test_with_no_scene_alone_every_scene_they_are_in_is_used(tmp_path: Path) -> None:
    job = _job(tmp_path)
    _with_second_person(job, jack_scenes=[1, 2, 3, 4])
    selector = _Selector(picks={("Mara", "1"): 0.7})

    _service(selector, tmp_path).refresh(job)

    assert {stem for who, stem in selector.asked if who == "Mara"} == {
        "1",
        "2",
        "3",
        "4",
    }


# ---- no footage / problems -------------------------------------------


def test_an_identity_with_no_generated_footage_is_reported_not_guessed(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    job.video_clips = []

    report = _service(_Selector(), tmp_path).refresh(job)

    assert _entry(report, "Mara").outcome == ReferenceRefreshOutcome.NO_FOOTAGE
    assert "no generated clip shows them" in _entry(report, "Mara").detail


def test_stock_footage_is_never_mined_for_a_character(tmp_path: Path) -> None:
    job = _job(tmp_path)

    for clip in job.video_clips:
        clip.source_type = SceneSourceType.STOCK_FOOTAGE

    selector = _Selector(picks={("Mara", "1"): 0.9})
    report = _service(selector, tmp_path).refresh(job)

    assert selector.asked == []
    assert _entry(report, "Mara").outcome == ReferenceRefreshOutcome.NO_FOOTAGE


def test_one_unreadable_clip_does_not_stop_the_rest(tmp_path: Path) -> None:
    job = _job(tmp_path)
    selector = _Selector(
        picks={("Mara", "2"): 0.4, ("Mara", "3"): 0.7}, raises_for={"2"}
    )

    report = _service(selector, tmp_path).refresh(job)

    entry = _entry(report, "Mara")
    assert entry.outcome == ReferenceRefreshOutcome.REPLACED
    assert entry.from_scene == 3


def test_without_face_detection_nothing_changes_and_it_says_so(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    before = _refs(job, "Mara")

    report = _service(_Selector(available=False), tmp_path).refresh(job)

    assert report.available is False
    assert "not available" in report.text()
    assert _refs(job, "Mara") == before


def test_a_job_without_a_continuity_bible_has_nothing_to_refresh(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    job.visual_continuity_bible = None

    report = _service(_Selector(), tmp_path).refresh(job)

    assert report.entries == []


def test_the_clips_themselves_are_never_touched(tmp_path: Path) -> None:
    job = _job(tmp_path)
    before = [
        (c.scene_number, c.local_file, c.duration_seconds) for c in job.video_clips
    ]

    _service(_Selector(picks={("Mara", "2"): 0.9}), tmp_path).refresh(job)

    assert [
        (c.scene_number, c.local_file, c.duration_seconds) for c in job.video_clips
    ] == before


# ---- report text and bringing a copy's result back -------------------


def test_the_report_reads_in_plain_words(tmp_path: Path) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)

    report = _service(
        _Selector(picks={("Mara", "2"): 0.8}, current={"Mara": 0.2}), tmp_path
    ).refresh(job)

    text = report.text()

    assert text.startswith("Refreshed 1 of 2 reference(s).")
    assert "Mara: new reference taken from scene 2" in text
    assert "The Apiary: places are not refreshed automatically" in text


def test_a_refresh_done_on_a_copy_can_be_brought_back_to_the_real_job(
    tmp_path: Path,
) -> None:
    """The GUI refreshes a deep copy off the main thread, then applies it."""

    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    before = _refs(job, "Mara")
    working = job.model_copy(deep=True)

    _service(
        _Selector(picks={("Mara", "2"): 0.8}, current={"Mara": 0.2}), tmp_path
    ).refresh(working)

    assert _refs(job, "Mara") == before  # the real job is untouched so far

    changed = ReferenceRefreshService.apply_to(job, working)

    assert changed == 1
    assert _refs(job, "Mara") == _refs(working, "Mara")
    assert job.extracted_frame_asset_index.get(_refs(job, "Mara")[0]) is not None
    assert ReferenceRefreshService.apply_to(job, working) == 0  # idempotent
