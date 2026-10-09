"""
A scene that names no character or place takes a reference picture by itself (2026-10-09). The
operator's rule: "Generate all" runs with no per-clip choice, and a scene's reference follows
from what it shows. A scene with nothing marked takes the best frame of the nearest earlier clip
made in the SAME setting; a graphic, an unspecified or new setting, or no earlier clip gets none
(a picture from another setting would pull that setting into the scene). A picture the operator
picked or removed is never replaced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.asset_index import AssetIndex
from src.models.scene import ReferencePickSource, Scene
from src.models.visual_continuity import VisualState
from src.services.asset_storage_service import AssetStorageService
from src.services.muse_scene_video_generation_service import (
    MuseSceneVideoGenerationService,
)
from src.services.recurring_identity_service import ReferenceCandidate
from src.services.scene_reference_override import (
    OVERRIDE_LABEL,
    override_reference_for_scene,
)
from src.services.scene_reference_service import (
    SceneReferenceService,
    same_setting,
)
from tests.test_muse_scene_video_generation_service import (
    _asset_workflow_service,
    _orchestrator,
    _real_video_file,
    _ScriptedProvider,
)
from tests.test_muse_scene_video_generation_service import (
    _job as muse_job,
)
from tests.test_muse_scene_video_generation_service import (
    _scene as muse_scene,
)
from tests.test_recurring_identity_service import (  # noqa: F401
    _add_clip,
    _job,
    _ManySelector,
    _mark_on_screen,
)


def _service(tmp_path: Path) -> SceneReferenceService:
    return SceneReferenceService(
        selection_service=_ManySelector(tmp_path), storage_root=tmp_path / "storage"
    )


def _scene_of(job, number: int) -> Scene:  # type: ignore[no-untyped-def]
    return next(s for s in job.scenes if s.scene_number == number)


def _set_locations(job, locations: dict[int, str]) -> None:  # type: ignore[no-untyped-def]
    assert job.visual_continuity_bible is not None

    for entry in job.visual_continuity_bible.clip_entries:
        if entry.scene_number in locations:
            entry.incoming_state = VisualState(location=locations[entry.scene_number])

        # the fixture marks the lake as "featured"; nothing is ON SCREEN unless a test says so
        entry.on_screen_entity_names = []


# ------------------------------------------------------------------ same setting


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Village", "Village and surrounding area"),
        ("Same rural village", "Rural village and surrounding countryside"),
        ("A rural village near Lake Nyos", "The original rural village"),
        ("Hill village", "hill VILLAGE"),
    ],
)
def test_wordings_of_one_setting_are_the_same_setting(first: str, second: str) -> None:
    assert same_setting(first, second) is True


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Village", "Lake shoreline"),
        ("Map room", "Hill village"),
        ("Village", ""),
        ("the", "the same"),
    ],
)
def test_different_or_empty_settings_are_not_the_same(first: str, second: str) -> None:
    assert same_setting(first, second) is False


# ------------------------------------------------------------------ taking the picture


def test_a_scene_naming_no_place_takes_a_frame_of_the_nearest_earlier_clip_in_its_setting(
    tmp_path: Path,
) -> None:
    job = _job(8)
    _set_locations(
        job,
        {
            1: "Hill village",
            2: "Map room",
            3: "Map room",
            6: "Hill village and surrounding area",
            7: "The hill village",
        },
    )

    for number in (1, 2, 3, 6):
        _add_clip(job, tmp_path, number)

    scene = _scene_of(job, 7)

    assert _service(tmp_path).ensure_automatic(job, 7) is True

    assert scene.reference_pick_source == ReferencePickSource.AUTOMATIC
    override = override_reference_for_scene(job.extracted_frame_asset_index, scene)
    assert override is not None
    assert Path(override.source_path).is_file()
    assert override.from_scene == 6  # the nearest clip in the SAME setting, not scene 3


def test_a_scene_in_a_setting_no_earlier_clip_shows_gets_nothing(
    tmp_path: Path,
) -> None:
    job = _job(8)
    _set_locations(job, {1: "Hill village", 2: "Hill village", 7: "Quarry"})
    _add_clip(job, tmp_path, 1)
    _add_clip(job, tmp_path, 2)

    assert _service(tmp_path).ensure_automatic(job, 7) is False
    assert _scene_of(job, 7).reference_override_asset_id is None
    assert _scene_of(job, 7).reference_pick_source is None


def test_a_scene_with_an_unspecified_setting_gets_nothing(tmp_path: Path) -> None:
    job = _job(8)
    _set_locations(job, {1: "Hill village"})
    _add_clip(job, tmp_path, 1)

    assert (
        _service(tmp_path).ensure_automatic(job, 7) is False
    )  # location is "unspecified"


def test_a_scene_that_already_names_a_place_is_left_to_that_places_own_reference(
    tmp_path: Path,
) -> None:
    job = _job(8)
    _set_locations(job, {1: "Hill village", 7: "Hill village"})
    _add_clip(job, tmp_path, 1)
    _mark_on_screen(job, "Lake Nyos", (7,))

    assert _service(tmp_path).ensure_automatic(job, 7) is False
    assert _scene_of(job, 7).reference_override_asset_id is None


def test_a_graphic_scene_gets_nothing(tmp_path: Path) -> None:
    job = _job(8)
    _set_locations(job, {1: "Hill village", 7: "Map overlay of the hill village"})
    _add_clip(job, tmp_path, 1)

    assert _service(tmp_path).ensure_automatic(job, 7) is False


def test_the_clip_of_a_graphic_scene_is_never_the_source(tmp_path: Path) -> None:
    job = _job(8)
    _set_locations(
        job,
        {
            1: "Hill village",
            6: "Diagram of the hill village",  # a graphic: its clip is not a place
            7: "Hill village",
        },
    )
    _add_clip(job, tmp_path, 1)
    _add_clip(job, tmp_path, 6)

    assert _service(tmp_path).ensure_automatic(job, 7) is True
    override = override_reference_for_scene(
        job.extracted_frame_asset_index, _scene_of(job, 7)
    )
    assert override is not None and override.from_scene == 1


def test_a_picture_the_operator_picked_is_not_replaced(tmp_path: Path) -> None:
    job = _job(8)
    _set_locations(job, {1: "Hill village", 7: "Hill village"})
    _add_clip(job, tmp_path, 1)
    service = _service(tmp_path)
    frame = tmp_path / "pick.jpg"
    frame.write_bytes(b"pick")
    service.set_override(job, 7, ReferenceCandidate(1, 0, str(frame), 1.0, 0.0))
    before = _scene_of(job, 7).reference_override_asset_id

    assert service.ensure_automatic(job, 7) is False
    assert _scene_of(job, 7).reference_override_asset_id == before
    assert _scene_of(job, 7).reference_pick_source == ReferencePickSource.OPERATOR


def test_removing_the_picture_means_none_and_the_app_does_not_pick_again(
    tmp_path: Path,
) -> None:
    job = _job(8)
    _set_locations(job, {1: "Hill village", 7: "Hill village"})
    _add_clip(job, tmp_path, 1)
    service = _service(tmp_path)

    assert service.ensure_automatic(job, 7) is True
    service.clear_override(job, 7)

    assert _scene_of(job, 7).reference_override_asset_id is None
    assert _scene_of(job, 7).reference_pick_source == ReferencePickSource.DECLINED
    assert service.ensure_automatic(job, 7) is False
    assert _scene_of(job, 7).reference_override_asset_id is None


def test_an_automatic_pick_is_not_taken_again_when_one_exists(tmp_path: Path) -> None:
    job = _job(8)
    _set_locations(job, {1: "Hill village", 7: "Hill village"})
    _add_clip(job, tmp_path, 1)
    service = _service(tmp_path)

    assert service.ensure_automatic(job, 7) is True
    first = _scene_of(job, 7).reference_override_asset_id

    assert service.ensure_automatic(job, 7) is False
    assert _scene_of(job, 7).reference_override_asset_id == first


def test_nothing_is_picked_when_frame_detection_is_unavailable(tmp_path: Path) -> None:
    class _Unavailable(_ManySelector):
        def is_available(self) -> bool:
            return False

    job = _job(8)
    _set_locations(job, {1: "Hill village", 7: "Hill village"})
    _add_clip(job, tmp_path, 1)
    service = SceneReferenceService(
        selection_service=_Unavailable(tmp_path), storage_root=tmp_path / "storage"
    )

    assert service.ensure_automatic(job, 7) is False


# ------------------------------------------------------------------------- the status


def test_the_status_line_says_the_picture_was_picked_automatically(
    tmp_path: Path,
) -> None:
    job = _job(8)
    _set_locations(job, {1: "Hill village", 7: "Hill village"})
    _add_clip(job, tmp_path, 1)
    service = _service(tmp_path)
    service.ensure_automatic(job, 7)

    status = service.status(job, _scene_of(job, 7))

    assert "picked automatically" in status.text
    assert "your pick" not in status.text
    assert status.has_reference is True


def test_the_status_line_of_a_removed_picture_says_so_and_asks_for_nothing(
    tmp_path: Path,
) -> None:
    job = _job(8)
    _set_locations(job, {1: "Hill village", 7: "Hill village"})
    _add_clip(job, tmp_path, 1)
    service = _service(tmp_path)
    service.ensure_automatic(job, 7)
    service.clear_override(job, 7)

    status = service.status(job, _scene_of(job, 7))

    assert "you removed it" in status.text
    assert status.needs_reference is False


def test_a_scene_saved_before_the_field_existed_loads_as_undecided() -> None:
    data = _job().scenes[0].model_dump(mode="json")
    data.pop("reference_pick_source")

    assert Scene.model_validate(data).reference_pick_source is None


# ------------------------------------------------- the generation service uses it


class _RecordingReferences:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[int] = []
        self._fail = fail

    def ensure_automatic(self, job, scene_number: int) -> bool:  # type: ignore[no-untyped-def]
        self.calls.append(scene_number)

        if self._fail:
            raise RuntimeError("boom")

        return False


def _muse_service(provider, references, tmp_path: Path):  # type: ignore[no-untyped-def]
    return MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=lambda _: None,
        asset_storage_service=AssetStorageService(
            storage_root=tmp_path / "svc", asset_index=AssetIndex()
        ),
        scene_reference_service=references,
    )


def _provider(tmp_path: Path) -> _ScriptedProvider:
    from src.models.muse_generation import MuseGenerationState

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    return provider


def test_muse_asks_for_the_automatic_reference_before_it_submits(
    tmp_path: Path,
) -> None:
    scene = muse_scene(2)
    scene.real_narration_duration_seconds = 3.0
    references = _RecordingReferences()
    service = _muse_service(_provider(tmp_path), references, tmp_path)

    service.generate_one(muse_job(scene), 2)

    assert references.calls == [2]


def test_a_failing_automatic_reference_does_not_stop_the_scene(tmp_path: Path) -> None:
    scene = muse_scene(2)
    scene.real_narration_duration_seconds = 3.0
    provider = _provider(tmp_path)
    service = _muse_service(provider, _RecordingReferences(fail=True), tmp_path)

    service.generate_one(muse_job(scene), 2)

    assert len(provider.submitted_requests) == 1


def test_an_automatic_pick_is_attached_to_the_muse_request(tmp_path: Path) -> None:
    """End to end through the Muse service: scene 2 names no place, an earlier clip of the
    same setting exists, and the request carries that frame as the scene's reference."""

    scene_one, scene_two = muse_scene(1), muse_scene(2)
    scene_two.real_narration_duration_seconds = 3.0
    job = muse_job(scene_one, scene_two)
    template = _job(4)
    job.visual_continuity_bible = template.visual_continuity_bible
    _set_locations(job, {1: "Hill village", 2: "The hill village"})
    _add_clip(job, tmp_path, 1)
    provider = _provider(tmp_path)
    service = _muse_service(
        provider,
        SceneReferenceService(
            selection_service=_ManySelector(tmp_path),
            storage_root=tmp_path / "storage",
        ),
        tmp_path,
    )

    service.generate_one(job, 2)

    request = provider.submitted_requests[0]
    assert [r.identity_name for r in request.reference_assets] == [OVERRIDE_LABEL]
    assert scene_two.reference_pick_source == ReferencePickSource.AUTOMATIC


def test_flow_asks_for_the_automatic_reference_before_it_submits(
    tmp_path: Path,
) -> None:
    from src.models.google_flow_generation import GoogleFlowGenerationState
    from tests.test_scene_video_generation_service import (
        _job as flow_job,
    )
    from tests.test_scene_video_generation_service import (
        _scene as flow_scene,
    )
    from tests.test_scene_video_generation_service import (
        _ScriptedProvider as FlowProvider,
    )
    from tests.test_scene_video_generation_service import (
        _service as flow_service,
    )

    provider = FlowProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    real_file = tmp_path / "scene.mp4"
    real_file.write_bytes(b"fake but present video bytes")
    provider.downloaded_file = str(real_file)
    references = _RecordingReferences()
    service = flow_service(provider)
    service._scene_reference_service = references  # type: ignore[assignment]  # noqa: SLF001

    service.generate_one(flow_job(flow_scene(1)), 1)

    assert references.calls == [1]
