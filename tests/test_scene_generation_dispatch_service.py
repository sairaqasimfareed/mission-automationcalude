from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.models.asset_index import AssetIndex
from src.models.asset_state import AssetUserDecision, SceneAssetState
from src.models.google_flow_generation import (
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.models.muse_generation import (
    MuseGenerationRequest,
)
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.models.scene import Scene
from src.models.scene_completeness import (
    SceneCompletenessEntry,
    SceneCompletenessStatus,
)
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)
from src.services.local_asset_search_service import LocalAssetSearchService
from src.services.muse_generation_ledger_service import MuseGenerationLedgerService
from src.services.registry.provider_registry import ProviderRegistry
from src.services.scene_asset_video_clip_builder_service import (
    SceneAssetVideoClipBuilderService,
)
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_generation_dispatch_service import (
    SceneGenerationDispatchService,
)


def _scene(number: int = 1, *, preferred_profile_id: str | None = None) -> Scene:
    scene = Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=f"Narration for scene {number}.",
        visual_prompt=f"Visual prompt for scene {number}.",
        estimated_duration_seconds=10,
    )
    scene.preferred_profile_id = preferred_profile_id

    return scene


def _job(*scenes: Scene) -> VideoJob:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.horror",
    )
    job.scenes = list(scenes)

    return job


def _registry() -> ProviderRegistry:
    return ProviderRegistry(
        profiles=[
            ProviderProfile(
                profile_id="flow.primary",
                display_name="flow.primary",
                provider_name="Google Flow",
                category=ProviderCategory.EXTERNAL_UI_VIDEO,
                enabled=True,
                health_status=ProviderHealthStatus.HEALTHY,
                browser_profile_reference="flow_profiles/flow.primary",
            ),
            ProviderProfile(
                profile_id="muse.primary",
                display_name="muse.primary",
                provider_name="Muse",
                category=ProviderCategory.EXTERNAL_UI_VIDEO,
                enabled=True,
                health_status=ProviderHealthStatus.HEALTHY,
                browser_profile_reference="muse_profiles/muse.primary",
            ),
        ]
    )


class _FakeService:
    """Records which scenes it was asked to drive - the dispatch
    service's own job is routing, not the real generation flow
    itself (already covered by each real service's own test suite)."""

    def __init__(
        self, *, status: SceneCompletenessStatus = SceneCompletenessStatus.READY
    ) -> None:
        self.generate_one_calls: list[int] = []
        self.retry_calls: list[int] = []
        self.abandon_calls: list[tuple[int, bool]] = []
        self._status = status

    def generate_one(self, job: VideoJob, scene_number: int) -> SceneCompletenessEntry:
        self.generate_one_calls.append(scene_number)

        is_ready = self._status == SceneCompletenessStatus.READY

        return SceneCompletenessEntry(
            scene_number=scene_number,
            status=self._status,
            generated=is_ready,
            downloaded=is_ready,
            attached=is_ready,
            detail="fake",
        )

    def retry_scene_after_auth(
        self, job: VideoJob, scene_number: int
    ) -> SceneCompletenessEntry:
        self.retry_calls.append(scene_number)

        return self.generate_one(job, scene_number)

    def abandon_stuck_attempt(
        self, job: VideoJob, scene_number: int, *, force: bool = False
    ) -> None:
        self.abandon_calls.append((scene_number, force))


def _dispatch(
    *,
    flow_service: _FakeService | None = None,
    muse_service: _FakeService | None = None,
) -> tuple[SceneGenerationDispatchService, _FakeService, _FakeService]:
    flow = flow_service or _FakeService()
    muse = muse_service or _FakeService()

    dispatch = SceneGenerationDispatchService(
        registry=_registry(),
        flow_service=flow,  # type: ignore[arg-type]
        muse_service=muse,  # type: ignore[arg-type]
    )

    return dispatch, flow, muse


# --- generate_one routing ---


def test_generate_one_routes_to_flow_when_no_preference_is_set() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1))

    dispatch.generate_one(job, 1)

    assert flow.generate_one_calls == [1]
    assert muse.generate_one_calls == []


def test_generate_one_routes_to_muse_when_preference_names_a_muse_account() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1, preferred_profile_id="muse.primary"))

    dispatch.generate_one(job, 1)

    assert muse.generate_one_calls == [1]
    assert flow.generate_one_calls == []


def test_generate_one_routes_to_flow_when_preference_names_a_flow_account() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1, preferred_profile_id="flow.primary"))

    dispatch.generate_one(job, 1)

    assert flow.generate_one_calls == [1]
    assert muse.generate_one_calls == []


def test_generate_one_routes_to_muse_when_the_project_chose_muse() -> None:
    """
    Project-level provider (2026-10-03): with no per-scene account choice
    ("Auto"), the project's own video_provider decides.
    """

    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1))
    job.video_provider = VideoProvider.MUSE

    dispatch.generate_one(job, 1)

    assert muse.generate_one_calls == [1]
    assert flow.generate_one_calls == []


def test_a_scenes_explicit_flow_account_beats_a_muse_project() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1, preferred_profile_id="flow.primary"))
    job.video_provider = VideoProvider.MUSE

    dispatch.generate_one(job, 1)

    assert flow.generate_one_calls == [1]
    assert muse.generate_one_calls == []


def test_a_scenes_explicit_muse_account_beats_a_flow_project() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1, preferred_profile_id="muse.primary"))
    job.video_provider = VideoProvider.GOOGLE_FLOW

    dispatch.generate_one(job, 1)

    assert muse.generate_one_calls == [1]
    assert flow.generate_one_calls == []


def test_generate_all_follows_the_projects_provider_for_unassigned_scenes() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1), _scene(2, preferred_profile_id="flow.primary"), _scene(3))
    job.video_provider = VideoProvider.MUSE

    dispatch.generate_all(job)

    assert muse.generate_one_calls == [1, 3]
    assert flow.generate_one_calls == [2]


def test_generate_one_raises_a_clear_error_for_an_unregistered_preference() -> None:
    dispatch, _, _ = _dispatch()
    job = _job(_scene(1, preferred_profile_id="ghost.account"))

    with pytest.raises(ValueError, match="is not registered"):
        dispatch.generate_one(job, 1)


def test_generate_one_raises_for_an_unknown_scene() -> None:
    dispatch, _, _ = _dispatch()
    job = _job(_scene(1))

    with pytest.raises(ValueError, match="Job has no scene numbered"):
        dispatch.generate_one(job, 99)


# --- generate_all: skip already-ready, route per scene ---


def test_generate_all_dispatches_each_scene_to_its_own_preferred_service() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(
        _scene(1),
        _scene(2, preferred_profile_id="muse.primary"),
    )

    dispatch.generate_all(job)

    assert flow.generate_one_calls == [1]
    assert muse.generate_one_calls == [2]


def test_generate_all_skips_a_scene_already_ready() -> None:
    flow = _FakeService()
    dispatch, flow, muse = _dispatch(flow_service=flow)
    job = _job(_scene(1), _scene(2))

    # Real completeness READY requires a real attached clip - simplest
    # real way to get there without a full generation stack is to
    # attach one directly, matching how other tests in this codebase
    # simulate an already-ready scene.
    workflow = SceneAssetWorkflowService(
        asset_manager=AssetManager(
            local_search_service=LocalAssetSearchService(asset_source=AssetIndex())
        ),
        decision_service=AssetDecisionService(),
        asset_search_service=AssetSearchService(),
    )
    real_file = Path(tempfile.gettempdir()) / "dispatch_test_scene1.mp4"
    real_file.write_bytes(b"fake but present video bytes")
    state = workflow.apply_decision(
        scene=job.scenes[0],
        state=SceneAssetState(scene_id=str(job.scenes[0].id), scene_number=1),
        decision=AssetUserDecision.AI_GENERATE,
        ai_generated_file_path=str(real_file),
        ai_generated_duration_seconds=10.0,
    )
    job.scene_asset_states.append(state)
    job.video_clips = SceneAssetVideoClipBuilderService().build_clips(
        scenes=job.scenes, states=job.scene_asset_states
    )

    dispatch.generate_all(job)

    assert flow.generate_one_calls == [2]  # scene 1 skipped, already ready


def test_generate_all_with_forced_profile_id_persists_it_on_every_scene() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1), _scene(2, preferred_profile_id="flow.primary"))

    dispatch.generate_all(job, forced_profile_id="muse.primary")

    assert job.scenes[0].preferred_profile_id == "muse.primary"
    assert job.scenes[1].preferred_profile_id == "muse.primary"
    assert muse.generate_one_calls == [1, 2]
    assert flow.generate_one_calls == []


# --- abandon_stuck_attempt: checks both ledgers ---


def _flow_request(scene_number: int = 1) -> GoogleFlowGenerationRequest:
    return GoogleFlowGenerationRequest(
        scene_number=scene_number,
        prompt="A lighthouse at dusk.",
        prompt_version="v1",
        profile_id="flow.primary",
        idempotency_key=f"req-{scene_number}",
    )


def _muse_request(scene_number: int = 1) -> MuseGenerationRequest:
    return MuseGenerationRequest(
        scene_number=scene_number,
        prompt="A lighthouse at dusk.",
        prompt_version="v1",
        profile_id="muse.primary",
        idempotency_key=f"req-{scene_number}",
    )


def test_abandon_stuck_attempt_routes_to_flow_when_flow_ledger_has_one() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1))
    GoogleFlowGenerationLedgerService.create_attempt(job, _flow_request())

    dispatch.abandon_stuck_attempt(job, 1)

    assert flow.abandon_calls == [(1, False)]
    assert muse.abandon_calls == []


def test_abandon_stuck_attempt_routes_to_muse_when_muse_ledger_has_one() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1))
    MuseGenerationLedgerService.create_attempt(job, _muse_request())

    dispatch.abandon_stuck_attempt(job, 1, force=True)

    assert muse.abandon_calls == [(1, True)]
    assert flow.abandon_calls == []


def test_abandon_stuck_attempt_raises_when_neither_ledger_has_one() -> None:
    dispatch, _, _ = _dispatch()
    job = _job(_scene(1))

    with pytest.raises(ValueError, match="no non-terminal attempt"):
        dispatch.abandon_stuck_attempt(job, 1)


def test_abandon_stuck_attempt_ignores_a_terminal_flow_attempt() -> None:
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1))
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _flow_request())
    GoogleFlowGenerationLedgerService.replace_attempt(
        job, attempt.with_transition(GoogleFlowGenerationState.FAILED)
    )
    MuseGenerationLedgerService.create_attempt(job, _muse_request())

    dispatch.abandon_stuck_attempt(job, 1)

    assert muse.abandon_calls == [(1, False)]
    assert flow.abandon_calls == []


# --- retry_scene_after_auth: routes by which ledger is actually stuck,
# not by Scene.preferred_profile_id (an operator may switch the
# dropdown after a scene got stuck on the other provider) ---


def test_retry_scene_after_auth_routes_to_flow_when_flow_ledger_is_stuck_on_auth() -> (
    None
):
    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1))
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _flow_request())
    GoogleFlowGenerationLedgerService.replace_attempt(
        job, attempt.with_transition(GoogleFlowGenerationState.AUTH_REQUIRED)
    )

    dispatch.retry_scene_after_auth(job, 1)

    assert flow.retry_calls == [1]
    assert muse.retry_calls == []


def test_retry_scene_after_auth_routes_to_muse_even_when_preference_names_flow() -> (
    None
):
    """
    The dropdown may have been switched to Flow (or left at Auto)
    after a scene actually got stuck waiting on Muse's own login -
    resolving purely by Scene.preferred_profile_id would call the
    wrong service and fail with a confusing "no attempt waiting on
    authentication" error instead of actually retrying.
    """

    dispatch, flow, muse = _dispatch()
    job = _job(_scene(1, preferred_profile_id="flow.primary"))
    MuseGenerationLedgerService.create_attempt(job, _muse_request())

    dispatch.retry_scene_after_auth(job, 1)

    assert muse.retry_calls == [1]
    assert flow.retry_calls == []
