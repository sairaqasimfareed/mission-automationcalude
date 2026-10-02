from __future__ import annotations

from src.models.asset_state import (
    AssetCandidate,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.audio_timeline import AudioTimeline
from src.models.enums import WorkflowStage
from src.models.generated_script import GeneratedScript
from src.models.media_strategy import SceneSourceType
from src.models.render_result import RenderResult, RenderStatus
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.services.content_studio_journey_service import (
    JourneyCheckpoint,
    JourneyCheckpointStatus,
)
from src.services.project_production_journey_service import (
    ProjectProductionJourneyService,
)


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
        genre_id="genre.mystery",
    )
    base.update(overrides)
    return VideoJob(**base)


def _research() -> ResearchResult:
    return ResearchResult.model_construct(status=ResearchStatus.APPROVED)


def _script() -> Script:
    return Script(
        title="Test script",
        content="Synthetic script content for journey-service testing.",
        prompt_version="test-1.0",
        word_count=8,
        estimated_duration_seconds=20,
        status=ScriptStatus.APPROVED,
    )


def _scene(scene_number: int) -> Scene:
    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration=f"Narration for scene {scene_number}.",
        visual_prompt=f"Visual prompt for scene {scene_number}.",
        estimated_duration_seconds=8,
    )


def _job_with_scenes(*scenes: Scene, **overrides: object) -> VideoJob:
    return _job(
        research=_research(),
        script=_script(),
        scenes=list(scenes),
        **overrides,
    )


def _statuses(job: VideoJob, **kwargs: object) -> dict[str, JourneyCheckpointStatus]:
    checkpoints = ProjectProductionJourneyService().compute(job, **kwargs)  # type: ignore[arg-type]
    return {checkpoint.label: checkpoint.status for checkpoint in checkpoints}


def test_a_bare_job_has_every_checkpoint_not_started() -> None:
    statuses = _statuses(_job())

    assert all(
        status == JourneyCheckpointStatus.NOT_STARTED for status in statuses.values()
    )
    assert set(statuses) == {
        "Audience",
        "Research",
        "Angle",
        "Story",
        "Hook",
        "Script",
        "Quality",
        "Script Lock",
        "Scene Planning",
        "Assets",
        "Voice & Audio",
        "Timeline",
        "Render",
        "SEO Package",
        "Thumbnail",
        "Final Export",
    }


def test_scene_planning_is_approved_once_scenes_exist() -> None:
    job = _job_with_scenes(_scene(1))

    statuses = _statuses(job)

    assert statuses["Scene Planning"] == JourneyCheckpointStatus.APPROVED


def test_assets_is_approved_once_every_scene_has_a_ready_candidate() -> None:
    scene = _scene(1)
    job = _job_with_scenes(scene)

    state = SceneAssetState.model_construct(
        scene_id=str(scene.id),
        scene_number=1,
        status=AssetWorkflowStatus.READY,
        selected_candidate=AssetCandidate(
            title="Manual upload",
            source_type=SceneSourceType.MANUAL_UPLOAD,
            file_path="/data/manual_uploads/scene_1.mp4",
            approved=True,
        ),
    )
    job.scene_asset_states = [state]

    statuses = _statuses(job)

    assert statuses["Assets"] == JourneyCheckpointStatus.APPROVED


def test_assets_is_needs_revision_when_a_scene_has_failed() -> None:
    scene = _scene(1)
    job = _job_with_scenes(scene)

    state = SceneAssetState.model_construct(
        scene_id=str(scene.id),
        scene_number=1,
        status=AssetWorkflowStatus.FAILED_FATAL,
    )
    job.scene_asset_states = [state]

    statuses = _statuses(job)

    assert statuses["Assets"] == JourneyCheckpointStatus.NEEDS_REVISION


def test_assets_is_waiting_when_a_scene_is_still_in_progress() -> None:
    scene = _scene(1)
    job = _job_with_scenes(scene)

    state = SceneAssetState.model_construct(
        scene_id=str(scene.id),
        scene_number=1,
        status=AssetWorkflowStatus.SEARCHING_STOCK,
    )
    job.scene_asset_states = [state]

    statuses = _statuses(job)

    assert statuses["Assets"] == JourneyCheckpointStatus.WAITING


def _ready_clip() -> VideoClip:
    return VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=8,
        local_file="/data/manual_uploads/scene_1.mp4",
    )


def test_audio_and_timeline_are_approved_once_built() -> None:
    job = _job_with_scenes(
        _scene(1),
        voice_file="dry-run://voice/test.mp3",
        audio_timeline=AudioTimeline(),
        video_clips=[_ready_clip()],
        video_timeline=VideoTimeline(),
    )

    statuses = _statuses(job)

    assert statuses["Voice & Audio"] == JourneyCheckpointStatus.APPROVED
    assert statuses["Timeline"] == JourneyCheckpointStatus.APPROVED


def test_render_is_approved_on_success_and_needs_revision_on_failure() -> None:
    success_job = _job_with_scenes(
        _scene(1),
        voice_file="dry-run://voice/test.mp3",
        audio_timeline=AudioTimeline(),
        video_clips=[_ready_clip()],
        video_timeline=VideoTimeline(),
        render_result=RenderResult(
            success=True, render_engine="ffmpeg", status=RenderStatus.COMPLETED
        ),
    )
    failure_job = _job_with_scenes(
        _scene(1),
        voice_file="dry-run://voice/test.mp3",
        audio_timeline=AudioTimeline(),
        video_clips=[_ready_clip()],
        video_timeline=VideoTimeline(),
        render_result=RenderResult(
            success=False, render_engine="ffmpeg", status=RenderStatus.FAILED
        ),
    )

    assert _statuses(success_job)["Render"] == JourneyCheckpointStatus.APPROVED
    assert _statuses(failure_job)["Render"] == JourneyCheckpointStatus.NEEDS_REVISION


def test_current_stage_label_falls_back_to_legacy_stage_for_a_non_ci_project() -> None:
    """
    A project that never touched ContentIntelligencePipeline (no CI-
    only marker field set) gets VideoJob.current_stage back exactly as
    before - real-world finding, 2026-09-30: that field IS accurate
    for a legacy-pipeline project, only wrong for a CI-pipeline one.
    """

    job = _job(current_stage=WorkflowStage.RENDER)
    service = ProjectProductionJourneyService()

    label = service.current_stage_label(job, service.compute(job))

    assert label == "render"


def test_current_stage_label_reports_the_first_unapproved_checkpoint_in_order() -> None:
    """
    Checkpoints are evaluated in real pipeline order - a later field
    being set (generated_script) does not skip an earlier, still-
    unpopulated one (Audience). This is what a real project the user
    saw live looked like: Script/Script Lock already Approved while
    Research showed Not started, most likely from manual content mode
    skipping the upstream chain - current_stage_label reports the
    genuinely first not-yet-approved checkpoint either way, rather
    than the stale legacy VideoJob.current_stage.
    """

    job = _job(
        current_stage=WorkflowStage.RESEARCH,
        generated_script=GeneratedScript.model_construct(
            segments=[],
            prompt_version="v1",
        ),
    )
    service = ProjectProductionJourneyService()

    label = service.current_stage_label(job, service.compute(job))

    assert label == "Audience"


def test_current_stage_label_reports_completed_once_everything_is_approved() -> None:
    """
    current_stage_label() takes its checkpoint list as an explicit
    argument precisely so this case doesn't need to fight through
    constructing all 16 real underlying artifacts (AudiencePromise,
    StoryAngle, StoryBlueprint, HookEvaluation, ...) - it only needs a
    job with one real CI marker (to select the journey-aware branch)
    and an all-APPROVED checkpoint list, exercising exactly the
    "nothing left to do" fallback at the end of the real loop.
    """

    job = _job(
        generated_script=GeneratedScript.model_construct(
            segments=[],
            prompt_version="v1",
        ),
    )
    service = ProjectProductionJourneyService()

    all_approved = [
        JourneyCheckpoint(label=label, status=JourneyCheckpointStatus.APPROVED)
        for label in (
            "Audience",
            "Research",
            "Angle",
            "Story",
            "Hook",
            "Script",
            "Quality",
            "Script Lock",
            "Scene Planning",
            "Assets",
            "Voice & Audio",
            "Timeline",
            "Render",
            "SEO Package",
            "Thumbnail",
            "Final Export",
        )
    ]

    label = service.current_stage_label(job, all_approved)

    assert label == "Completed"
