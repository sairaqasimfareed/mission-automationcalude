"""
The third video provider (2026-10-18): Google Flow on the "Omni 1.1 Flash" model - 4/6/8/10 s clips, and
reference images accepted at every length (confirmed live on the account owner's settings popover). It reuses
all the Flow browser automation; only the clip rules differ, and a project on it never falls back to the
older model's 8 s ceiling or its "a reference forces 8 s" rule.
"""

from __future__ import annotations

from pathlib import Path

from src.agents.scene_planner.agent import ScenePlannerAgent
from src.models.asset_index import AssetIndex
from src.models.google_flow_generation import GoogleFlowGenerationState
from src.models.video_provider import VideoProvider
from src.providers.google_flow.clip_profile import (
    OMNI,
    STANDARD,
    flow_clip_profile_for,
)
from src.services.asset_storage_service import AssetStorageService
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.video_provider_rules import (
    merge_target_seconds,
    resolve_scene_video_provider,
    rules_for,
)
from tests.test_scene_merge import _script, _segment
from tests.test_scene_planner_generated_script import _editorial_profile
from tests.test_scene_video_generation_service import (
    _continuity_bible,
    _job,
    _real_video_file,
    _scene,
    _ScriptedProvider,
    _service,
    _stored_reference_asset,
)

_OMNI = VideoProvider.GOOGLE_FLOW_OMNI


def test_the_profiles_know_their_own_lengths_and_model() -> None:
    assert STANDARD.durations == (4, 6, 8)
    assert STANDARD.references_need_max_duration is True
    assert STANDARD.model_family is None
    assert OMNI.durations == (4, 6, 8, 10)
    assert OMNI.references_need_max_duration is False
    assert OMNI.model_family == "Omni 1.1 Flash"
    assert flow_clip_profile_for(_OMNI) is OMNI
    assert flow_clip_profile_for(VideoProvider.GOOGLE_FLOW) is STANDARD


def test_the_clip_length_is_rounded_up_on_each_models_own_lengths() -> None:
    assert OMNI.clamp(5.1) == 6
    assert OMNI.clamp(8.2) == 10
    assert OMNI.clamp(10.0) == 10
    assert STANDARD.clamp(8.2) == 8


def test_a_nine_second_narration_is_one_clip_on_omni_and_two_on_the_older_model() -> (
    None
):
    assert OMNI.plan(9.0) == [10.0]
    assert len(STANDARD.plan(9.0)) == 2


def test_a_longer_narration_splits_on_the_omni_grid_without_wasting_footage() -> None:
    plan = OMNI.plan(12.0)

    assert plan == [6.0, 6.0]
    assert sum(plan) >= 12.0
    assert OMNI.needs_split(10.5) and not OMNI.needs_split(10.0)


def test_the_rules_describe_and_size_for_omni() -> None:
    rules = rules_for(_OMNI)

    assert rules.max_single_clip_seconds == 10.0
    assert "10s" in rules.summary and "Omni" in rules.summary
    assert rules.display_name == "Google Flow (Omni)"
    assert rules.single_clip_seconds(7.4) == 8.0
    assert rules.single_clip_seconds(9.1) == 10.0
    assert rules.plan_clips(9.1) == [10.0]
    assert _OMNI.is_flow and VideoProvider.GOOGLE_FLOW.is_flow
    assert not VideoProvider.MUSE.is_flow


def test_the_merge_target_follows_the_longer_omni_clip() -> None:
    assert merge_target_seconds(_OMNI) == 9.0
    assert merge_target_seconds(VideoProvider.GOOGLE_FLOW) == 7.0


def test_a_scene_account_that_is_a_flow_account_keeps_the_projects_omni_rules() -> None:
    job = _job(_scene(1))
    job.video_provider = _OMNI
    scene = job.scenes[0]
    scene.preferred_profile_id = "flow-account"

    assert resolve_scene_video_provider(job, scene, lambda _id: "Google Flow") == _OMNI
    assert (
        resolve_scene_video_provider(job, scene, lambda _id: "Muse")
        == VideoProvider.MUSE
    )

    job.video_provider = VideoProvider.GOOGLE_FLOW
    assert (
        resolve_scene_video_provider(job, scene, lambda _id: "Google Flow")
        == VideoProvider.GOOGLE_FLOW
    )


def test_the_planner_allows_longer_scenes_only_when_told_to() -> None:
    text = (
        "The door was open and the room was cold. Nobody had a key to it. "
        "A lamp still burned beside the bed. The letter lay on the floor."
    )
    script = _script(_segment(1, 0, 60, text))
    agent = ScenePlannerAgent()
    profile = _editorial_profile()

    older = agent.plan_from_generated_script(script, profile)
    omni = agent.plan_from_generated_script(script, profile, max_scene_seconds=10.0)

    assert len(omni) <= len(older)
    assert max(s.estimated_duration_seconds for s in omni) <= 10
    assert max(s.estimated_duration_seconds for s in older) <= 8


def test_the_pipeline_plans_omni_projects_for_ten_seconds() -> None:
    job = _job(_scene(1))

    assert ContentIntelligencePipeline._max_scene_seconds(job) == 8.0  # noqa: SLF001
    job.video_provider = _OMNI
    assert ContentIntelligencePipeline._max_scene_seconds(job) == 10.0  # noqa: SLF001


# ------------------------------------------------------------------- the real submission


def _provider_for(tmp_path: Path) -> _ScriptedProvider:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    return provider


def _referenced_job(tmp_path: Path, provider: VideoProvider):  # type: ignore[no-untyped-def]
    scene = _scene(2)
    scene.real_narration_duration_seconds = 2.5
    job = _job(scene)
    job.video_provider = provider
    asset_id = _stored_reference_asset(job, tmp_path)
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[asset_id], scene_numbers=[2]
    )

    return job


def test_an_omni_scene_with_a_reference_is_not_forced_to_the_longest_clip(
    tmp_path: Path,
) -> None:
    provider = _provider_for(tmp_path)
    storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(provider, asset_storage_service=storage)
    job = _referenced_job(tmp_path, _OMNI)

    service.generate_one(job, 2)

    request = provider.submitted_requests[0]
    assert len(request.reference_assets) == 1
    assert request.execution_settings.duration_seconds == 4.0
    assert request.execution_settings.model_family == "Omni 1.1 Flash"


def test_the_older_model_still_forces_the_longest_clip_with_a_reference(
    tmp_path: Path,
) -> None:
    provider = _provider_for(tmp_path)
    storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(provider, asset_storage_service=storage)
    job = _referenced_job(tmp_path, VideoProvider.GOOGLE_FLOW)

    service.generate_one(job, 2)

    request = provider.submitted_requests[0]
    assert request.execution_settings.duration_seconds == 8.0
    assert request.execution_settings.model_family != "Omni 1.1 Flash"


def test_an_omni_scene_of_nine_seconds_is_one_ten_second_clip(tmp_path: Path) -> None:
    provider = _provider_for(tmp_path)
    service = _service(provider)
    scene = _scene(1)
    scene.real_narration_duration_seconds = 9.2
    job = _job(scene)
    job.video_provider = _OMNI

    service.generate_one(job, 1)

    assert len(provider.submitted_requests) == 1
    assert provider.submitted_requests[0].execution_settings.duration_seconds == 10.0
