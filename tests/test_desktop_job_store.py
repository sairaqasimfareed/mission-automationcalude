from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from src.desktop.job_store import InMemoryJobStore, JobStoreError, JsonJobStore
from src.models.enums import JobStatus, Platform, WorkflowStage
from src.models.final_export import FinalExportPackage
from src.models.google_flow_generation import (
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.models.render_orchestration_result import RenderOrchestrationResult
from src.models.seo import SEOPackage, SEOPlatformMetadata, TitleCandidate
from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.models.video_job import VideoJob
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)


def _job(project_name: str = "Test Project") -> VideoJob:
    return VideoJob(
        project_name=project_name,
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )


def test_add_and_get_job() -> None:
    store = InMemoryJobStore()
    job = _job()

    store.add(job)

    assert store.get(job.id) is job


def test_get_returns_none_for_unknown_job() -> None:
    store = InMemoryJobStore()

    assert store.get(uuid4()) is None


def test_list_all_returns_newest_first() -> None:
    store = InMemoryJobStore()

    first = _job("First")
    second = _job("Second")

    store.add(first)
    store.add(second)

    jobs = store.list_all()

    assert [job.project_name for job in jobs] == ["Second", "First"]


def test_seo_package_round_trip() -> None:
    store = InMemoryJobStore()
    job = _job()

    seo_package = SEOPackage(
        video_job_id=job.id,
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )

    assert store.get_seo_package(job.id) is None

    store.set_seo_package(job.id, seo_package)

    assert store.get_seo_package(job.id) is seo_package


def test_thumbnail_round_trip() -> None:
    store = InMemoryJobStore()
    job = _job()

    thumbnail = ThumbnailArtifact(
        video_job_id=job.id,
        concept=ThumbnailConcept(
            concept_summary="A summary.",
            hook_text="HOOK",
            visual_prompt="A prompt.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="dry-run://thumbnail/1280x720.png",
        file_size_bytes=0,
    )

    assert store.get_thumbnail(job.id) is None

    store.set_thumbnail(job.id, thumbnail)

    assert store.get_thumbnail(job.id) is thumbnail


def test_render_result_round_trip() -> None:
    store = InMemoryJobStore()
    job = _job()
    job.status = JobStatus.FAILED
    job.current_stage = WorkflowStage.ASSET_GENERATION

    render_result = RenderOrchestrationResult.failed(
        job=job,
        failed_stage=WorkflowStage.ASSET_GENERATION,
        completed_stages=[],
        elapsed_seconds=0.1,
        error_message="No matching local asset was found.",
    )

    assert store.get_render_result(job.id) is None

    store.set_render_result(job.id, render_result)

    assert store.get_render_result(job.id) is render_result


def test_final_export_round_trip() -> None:
    store = InMemoryJobStore()
    job = _job()

    seo_package = SEOPackage(
        video_job_id=job.id,
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )

    thumbnail = ThumbnailArtifact(
        video_job_id=job.id,
        concept=ThumbnailConcept(
            concept_summary="A summary.",
            hook_text="HOOK",
            visual_prompt="A prompt.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="dry-run://thumbnail/1280x720.png",
        file_size_bytes=0,
    )

    final_export = FinalExportPackage(
        video_job_id=job.id,
        project_id="Test Project",
        final_video_path="data/final_exports/test_project/video.mp4",
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=60,
        seo_package=seo_package,
        thumbnail_artifact=thumbnail,
        export_directory="data/final_exports/test_project",
    )

    assert store.get_final_export(job.id) is None

    store.set_final_export(job.id, final_export)

    assert store.get_final_export(job.id) is final_export


def test_json_store_get_returns_same_instance_within_one_store(tmp_path: Path) -> None:
    """
    get() must return the exact object add() was given, not a fresh
    deserialize, within the lifetime of one store instance -
    ProjectWorkspaceView's workspace views mutate the returned VideoJob
    in place (`job.research = research`) and rely on a later add(job)
    call persisting that same mutated object.
    """

    store = JsonJobStore(storage_root=tmp_path)
    job = _job()

    store.add(job)

    assert store.get(job.id) is job

    job.topic = "A mutated topic"

    reloaded = store.get(job.id)

    assert reloaded is not None
    assert reloaded.topic == "A mutated topic"


def test_json_store_get_returns_none_for_unknown_job(tmp_path: Path) -> None:
    store = JsonJobStore(storage_root=tmp_path)

    assert store.get(uuid4()) is None


def test_json_store_list_all_returns_newest_first(tmp_path: Path) -> None:
    store = JsonJobStore(storage_root=tmp_path)

    first = _job("First")
    second = _job("Second")

    store.add(first)
    store.add(second)

    jobs = store.list_all()

    assert [job.project_name for job in jobs] == ["Second", "First"]


def test_json_store_list_all_excludes_artifact_files(tmp_path: Path) -> None:
    store = JsonJobStore(storage_root=tmp_path)
    job = _job()

    store.add(job)
    store.set_seo_package(
        job.id,
        SEOPackage(
            video_job_id=job.id,
            title_candidates=[TitleCandidate(text="Great Video")],
            selected_title="Great Video",
            description="A description.",
            platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
            prompt_version="seo_prompt_v1.0.0",
        ),
    )

    listed_ids = [listed_job.id for listed_job in store.list_all()]

    assert listed_ids == [job.id]


def test_json_store_persists_across_instances(tmp_path: Path) -> None:
    """Simulates an app restart: a fresh store pointed at the same
    storage_root must see everything the previous instance wrote."""

    first_instance = JsonJobStore(storage_root=tmp_path)
    job = _job()
    first_instance.add(job)

    second_instance = JsonJobStore(storage_root=tmp_path)

    assert second_instance.get(job.id) == job
    assert [loaded.id for loaded in second_instance.list_all()] == [job.id]


def test_json_store_flow_generation_attempts_survive_a_restart(
    tmp_path: Path,
) -> None:
    """
    Google Flow External UI Automation, GF-1: the durable attempt
    ledger is a plain VideoJob field, persisted the exact same way as
    every other artifact - proven here through a genuinely fresh
    JsonJobStore instance (a real restart, not just re-reading the
    same in-memory object), including the nested, append-only
    state_history a real crash-reconciliation depends on.
    """

    first_instance = JsonJobStore(storage_root=tmp_path)
    job = _job()

    request = GoogleFlowGenerationRequest(
        scene_number=1,
        prompt="A lighthouse at dusk.",
        prompt_version="v1",
        profile_id="flow.primary",
        idempotency_key="req-1",
    )
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, request)
    GoogleFlowGenerationLedgerService.record_transition(
        job, attempt.id, GoogleFlowGenerationState.SETTINGS_VERIFIED
    )

    first_instance.add(job)

    second_instance = JsonJobStore(storage_root=tmp_path)
    reloaded = second_instance.get(job.id)

    assert reloaded is not None
    assert len(reloaded.flow_generation_attempts) == 1

    reloaded_attempt = reloaded.flow_generation_attempts[0]
    assert reloaded_attempt.id == attempt.id
    assert reloaded_attempt.state.value == "settings_verified"
    assert [entry.state.value for entry in reloaded_attempt.state_history] == [
        "planned",
        "settings_verified",
    ]


def test_json_store_mutate_in_place_then_add_persists_across_restart(
    tmp_path: Path,
) -> None:
    """
    Reproduces the workspace views' exact pattern: fetch the job,
    mutate it in place, then call add() again (as
    ProjectWorkspaceView.refresh() does) - a fresh store pointed at
    the same storage_root afterward must see the mutation, not the
    original value.
    """

    first_instance = JsonJobStore(storage_root=tmp_path)
    job = _job()
    first_instance.add(job)

    fetched = first_instance.get(job.id)
    assert fetched is not None

    fetched.current_stage = WorkflowStage.SCRIPT
    first_instance.add(fetched)

    second_instance = JsonJobStore(storage_root=tmp_path)
    reloaded = second_instance.get(job.id)

    assert reloaded is not None
    assert reloaded.current_stage == WorkflowStage.SCRIPT


def test_json_store_seo_package_round_trip(tmp_path: Path) -> None:
    store = JsonJobStore(storage_root=tmp_path)
    job = _job()

    seo_package = SEOPackage(
        video_job_id=job.id,
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )

    assert store.get_seo_package(job.id) is None

    store.set_seo_package(job.id, seo_package)

    assert store.get_seo_package(job.id) == seo_package


def test_json_store_thumbnail_round_trip(tmp_path: Path) -> None:
    store = JsonJobStore(storage_root=tmp_path)
    job = _job()

    thumbnail = ThumbnailArtifact(
        video_job_id=job.id,
        concept=ThumbnailConcept(
            concept_summary="A summary.",
            hook_text="HOOK",
            visual_prompt="A prompt.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="dry-run://thumbnail/1280x720.png",
        file_size_bytes=0,
    )

    assert store.get_thumbnail(job.id) is None

    store.set_thumbnail(job.id, thumbnail)

    assert store.get_thumbnail(job.id) == thumbnail


def test_json_store_render_result_round_trip(tmp_path: Path) -> None:
    store = JsonJobStore(storage_root=tmp_path)
    job = _job()
    job.status = JobStatus.FAILED
    job.current_stage = WorkflowStage.ASSET_GENERATION

    render_result = RenderOrchestrationResult.failed(
        job=job,
        failed_stage=WorkflowStage.ASSET_GENERATION,
        completed_stages=[],
        elapsed_seconds=0.1,
        error_message="No matching local asset was found.",
    )

    assert store.get_render_result(job.id) is None

    store.set_render_result(job.id, render_result)

    assert store.get_render_result(job.id) == render_result


def test_json_store_final_export_round_trip(tmp_path: Path) -> None:
    store = JsonJobStore(storage_root=tmp_path)
    job = _job()

    seo_package = SEOPackage(
        video_job_id=job.id,
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )

    thumbnail = ThumbnailArtifact(
        video_job_id=job.id,
        concept=ThumbnailConcept(
            concept_summary="A summary.",
            hook_text="HOOK",
            visual_prompt="A prompt.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="dry-run://thumbnail/1280x720.png",
        file_size_bytes=0,
    )

    final_export = FinalExportPackage(
        video_job_id=job.id,
        project_id="Test Project",
        final_video_path="data/final_exports/test_project/video.mp4",
        resolution="1920x1080",
        frame_rate=30,
        duration_seconds=60,
        seo_package=seo_package,
        thumbnail_artifact=thumbnail,
        export_directory="data/final_exports/test_project",
    )

    assert store.get_final_export(job.id) is None

    store.set_final_export(job.id, final_export)

    assert store.get_final_export(job.id) == final_export


def test_json_store_corrupt_job_file_raises(tmp_path: Path) -> None:
    store = JsonJobStore(storage_root=tmp_path)
    job = _job()

    store.add(job)

    (tmp_path / f"{job.id}.json").write_text("not valid json", encoding="utf-8")

    # A fresh store instance is required here: the writing instance's
    # cache still holds the valid in-memory job and would never touch
    # the now-corrupted file.
    fresh_store = JsonJobStore(storage_root=tmp_path)

    with pytest.raises(JobStoreError):
        fresh_store.get(job.id)


def test_json_store_loads_a_legacy_video_job_json_missing_new_fields(
    tmp_path: Path,
) -> None:
    """
    MRA-PRE-2 (Pre-Installer Master Audit, persistence/restart/
    migration audit): the "new optional fields absorb via Pydantic
    defaults, no migration script needed" claim has been asserted
    repeatedly across this project's history for individual artifacts
    (see test_json_store_loads_a_legacy_seo_package_json_missing_new_fields)
    but never proven directly for VideoJob itself - the one model
    every other artifact is keyed against. Hand-writes the on-disk
    shape a project saved before content-intelligence/Google-Flow
    sprints existed would have (17 fields genuinely absent, not just
    null: editorial_profile_snapshot, flow_generation_attempts,
    content_decisions, script_version_history,
    production_ambiguities, stale_artifacts, audience_promise,
    research_plan, generated_script, story_angles,
    selected_story_angle, narrative_architecture, hook_candidates,
    selected_hook, editorial_critique, script_quality_report,
    packaging_hypothesis, approval_policy, content_strategy) and
    proves it still loads with correct, honest defaults - never a
    guessed or fabricated value for what a legacy project never had.
    """

    store = JsonJobStore(storage_root=tmp_path)
    job = _job()
    full_payload = json.loads(job.model_dump_json())

    fields_added_by_later_sprints = [
        "editorial_profile_snapshot",
        "flow_generation_attempts",
        "content_decisions",
        "script_version_history",
        "production_ambiguities",
        "stale_artifacts",
        "audience_promise",
        "research_plan",
        "generated_script",
        "story_angles",
        "selected_story_angle",
        "narrative_architecture",
        "hook_candidates",
        "selected_hook",
        "editorial_critique",
        "script_quality_report",
        "packaging_hypothesis",
        "approval_policy",
        "content_strategy",
    ]
    legacy_payload = {
        key: value
        for key, value in full_payload.items()
        if key not in fields_added_by_later_sprints
    }
    assert len(legacy_payload) < len(full_payload), (
        "sanity check: the stripped fields must actually exist on a "
        "real dump, or this test proves nothing"
    )

    (tmp_path / f"{job.id}.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8"
    )

    restored = store.get(job.id)

    assert restored is not None
    assert restored.id == job.id
    assert restored.project_name == job.project_name
    # Every field a legacy project never had defaults to its own
    # honest "nothing happened yet" value - never fabricated.
    assert restored.editorial_profile_snapshot is None
    assert restored.flow_generation_attempts == []
    assert restored.content_decisions == []
    assert restored.audience_promise is None
    assert restored.generated_script is None
    # approval_policy is the one exception among the stripped fields:
    # it has always had a real, sensible default_factory
    # (ApprovalPolicyConfig.review_critical_stages), not None - a
    # legacy project restores to that same default, not a fabricated
    # or missing policy.
    assert restored.approval_policy is not None


def test_json_store_seo_package_round_trips_all_step_2_provenance_fields(
    tmp_path: Path,
) -> None:
    """
    Step 2 (SEO, Thumbnail & Publishing Reconciliation), SEO-9: prove
    persistence, not just the model's own serialization - every new
    field added across SEO-2/SEO-3/SEO-4/SEO-6 survives a real write
    then a fresh-instance read, matching the existing round-trip
    tests' own established pattern.
    """

    store = JsonJobStore(storage_root=tmp_path)
    job = _job()

    seo_package = SEOPackage(
        video_job_id=job.id,
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
        version_number=3,
        source_script_lock_hash="abc123",
        source_script_version_number=2,
        source_genre_id="genre.documentary",
        source_target_country="United States",
        source_language="English",
        source_scene_count=4,
    )

    store.set_seo_package(job.id, seo_package)

    fresh_store = JsonJobStore(storage_root=tmp_path)
    restored = fresh_store.get_seo_package(job.id)

    assert restored == seo_package
    assert restored is not None
    assert restored.version_number == 3
    assert restored.source_script_lock_hash == "abc123"
    assert restored.source_genre_id == "genre.documentary"
    assert restored.source_target_country == "United States"
    assert restored.source_language == "English"
    assert restored.source_scene_count == 4


def test_json_store_loads_a_legacy_seo_package_json_missing_new_fields(
    tmp_path: Path,
) -> None:
    """
    Step 2, SEO-9: "Migrate conservatively; never invent SEO/genre/
    audience authority... Historical and interrupted projects recover
    without hidden regeneration or authority drift." Hand-writes the
    exact on-disk shape a pre-SEO-2/3/4/6 project would have (no
    version_number, no source_* fields at all) and proves it still
    loads - Pydantic's own default-filling, not any migration code
    this repo would need to maintain - with every new field honestly
    unset rather than guessed.
    """

    store = JsonJobStore(storage_root=tmp_path)
    job = _job()

    legacy_payload = {
        "id": str(uuid4()),
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "video_job_id": str(job.id),
        "title_candidates": [{"text": "A Legacy Title"}],
        "selected_title": "A Legacy Title",
        "description": "A legacy description.",
        "hook_summary": "",
        "keywords": {
            "primary_keywords": [],
            "secondary_keywords": [],
            "long_tail_keywords": [],
        },
        "tags": [],
        "hashtags": [],
        "platform_metadata": {
            "platform": "youtube",
            "category": None,
            "language": "English",
            "language_code": "en",
            "extra": {},
        },
        "prompt_version": "seo_prompt_v1.0.0",
        "status": "approved",
        "metadata": {},
    }

    artifact_path = tmp_path / f"{job.id}.seo_package.json"
    artifact_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    restored = store.get_seo_package(job.id)

    assert restored is not None
    assert restored.selected_title == "A Legacy Title"
    # Migration never invents authority it wasn't given - every
    # Step 2 field defaults to unset/1, not guessed from context.
    assert restored.version_number == 1
    assert restored.source_script_lock_hash is None
    assert restored.source_genre_id is None
    assert restored.source_target_country is None
    assert restored.source_language is None
    assert restored.source_scene_count is None
    # A legacy project's existing approval state is not disturbed by
    # migration - "stale approvals/reviews cannot become current by
    # migration" holds trivially here since nothing rewrites it.
    assert restored.status.value == "approved"


def test_json_store_thumbnail_round_trips_all_step_2_provenance_fields(
    tmp_path: Path,
) -> None:
    store = JsonJobStore(storage_root=tmp_path)
    job = _job()

    thumbnail = ThumbnailArtifact(
        video_job_id=job.id,
        concept=ThumbnailConcept(
            concept_summary="A summary.",
            hook_text="HOOK",
            visual_prompt="A prompt.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="dry-run://thumbnail/1280x720.png",
        file_size_bytes=0,
        version_number=2,
        source_script_lock_hash="abc123",
        source_script_version_number=1,
        source_genre_id="genre.documentary",
        source_target_country="United States",
        source_language="English",
        source_scene_count=3,
    )

    store.set_thumbnail(job.id, thumbnail)

    fresh_store = JsonJobStore(storage_root=tmp_path)
    restored = fresh_store.get_thumbnail(job.id)

    assert restored == thumbnail
    assert restored is not None
    assert restored.version_number == 2
    assert restored.source_genre_id == "genre.documentary"
    assert restored.source_scene_count == 3
