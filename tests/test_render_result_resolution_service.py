from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.desktop.job_store import JsonJobStore
from src.models.audio_timeline import AudioTimeline
from src.models.enums import JobStatus, WorkflowStage
from src.models.media_strategy import SceneSourceType
from src.models.render_orchestration_result import RenderOrchestrationResult
from src.models.render_result import RenderResult, RenderStatus
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.services.render_result_resolution_service import (
    replace_orchestration_render_result,
    resolve_effective_render_orchestration_result,
    resolve_effective_render_result,
)


def _scene(scene_number: int) -> Scene:
    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration=f"Narration for scene {scene_number}.",
        visual_prompt=f"Visual prompt for scene {scene_number}.",
        estimated_duration_seconds=8,
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


def _job_with_render_result(render_result: RenderResult) -> VideoJob:
    """
    VideoJob.render_result requires audio_timeline + voice_file and
    video_timeline + video_clips too (see its own model validator) -
    all four are set together purely to satisfy that, not because this
    test cares about audio/video content.
    """

    return _job(
        research=ResearchResult(
            topic="Test topic",
            research_summary="Synthetic research summary.",
            prompt_version="test-1.0",
            status=ResearchStatus.APPROVED,
        ),
        script=Script(
            title="Test script",
            content="Synthetic script content for resolution-service testing.",
            prompt_version="test-1.0",
            word_count=8,
            estimated_duration_seconds=20,
            status=ScriptStatus.APPROVED,
        ),
        scenes=[_scene(1)],
        voice_file="dry-run://voice/test.mp3",
        audio_timeline=AudioTimeline(),
        video_clips=[
            VideoClip(
                scene_number=1,
                source_type=SceneSourceType.MANUAL_UPLOAD,
                duration_seconds=8,
                local_file="/data/manual_uploads/scene_1.mp4",
            )
        ],
        video_timeline=VideoTimeline(),
        render_result=render_result,
    )


def _render_result(*, success: bool = True) -> RenderResult:
    return RenderResult(
        success=success,
        render_engine="ffmpeg",
        status=RenderStatus.COMPLETED if success else RenderStatus.FAILED,
        output_file="outputs/final_video.mp4" if success else None,
    )


def test_prefers_the_job_store_result_when_it_has_a_render_result() -> None:
    """
    A render genuinely triggered through the GUI keeps showing exactly
    what it always did - the job-store cache's own render_result. (Its
    own model validator requires RenderOrchestrationResult.render_result
    to match VideoJob.render_result whenever both are present, so this
    is also the only combination that can genuinely occur - "the two
    disagree" is not a real state this function needs to arbitrate.)
    """

    shared_render = _render_result()
    job = _job_with_render_result(shared_render)
    job.status = JobStatus.COMPLETED
    job.current_stage = WorkflowStage.READY_FOR_UPLOAD

    orchestration_result = RenderOrchestrationResult(
        success=True,
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
        job=job,
        render_result=shared_render,
    )

    resolved = resolve_effective_render_result(job, orchestration_result)

    assert resolved is shared_render


def test_falls_back_to_the_job_render_result_when_the_job_store_cache_is_empty() -> (
    None
):
    """
    Real-world finding, 2026-09-30: a render that happened through a
    standalone script never populates JobStore's own cache
    (set_render_result is only ever called from GUI button handlers) -
    the real, genuinely-completed render on VideoJob.render_result
    must still be recognized rather than reported as "not rendered".
    """

    real_render = _render_result()
    job = _job_with_render_result(real_render)

    resolved = resolve_effective_render_result(job, None)

    assert resolved is real_render


def test_falls_back_when_the_job_store_result_has_no_nested_render_result() -> None:
    real_render = _render_result()
    job = _job_with_render_result(real_render)
    job.status = JobStatus.FAILED
    job.current_stage = WorkflowStage.ASSET_GENERATION

    orchestration_result = RenderOrchestrationResult(
        success=False,
        status=JobStatus.FAILED,
        current_stage=WorkflowStage.ASSET_GENERATION,
        failed_stage=WorkflowStage.ASSET_GENERATION,
        job=job,
        render_result=None,
        errors=["Synthetic failure for resolution-service testing."],
    )

    resolved = resolve_effective_render_result(job, orchestration_result)

    assert resolved is real_render


def test_returns_none_when_neither_source_has_a_render_result() -> None:
    job = _job()

    assert resolve_effective_render_result(job, None) is None


def test_orchestration_resolution_prefers_the_job_store_result() -> None:
    shared_render = _render_result()
    job = _job_with_render_result(shared_render)
    job.status = JobStatus.COMPLETED
    job.current_stage = WorkflowStage.READY_FOR_UPLOAD

    orchestration_result = RenderOrchestrationResult(
        success=True,
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
        job=job,
        render_result=shared_render,
    )

    resolved = resolve_effective_render_orchestration_result(job, orchestration_result)

    assert resolved is orchestration_result


def test_orchestration_resolution_synthesizes_one_from_a_real_successful_job() -> None:
    """
    Real-world finding, 2026-09-30: this is what let a title-card
    generation or final-export build actually run for a project whose
    render happened outside the GUI, instead of the action silently
    no-opping because job_store's own cache was never populated.
    """
    real_render = _render_result()
    job = _job_with_render_result(real_render)
    job.status = JobStatus.COMPLETED
    job.current_stage = WorkflowStage.READY_FOR_UPLOAD

    resolved = resolve_effective_render_orchestration_result(job, None)

    assert resolved is not None
    assert resolved.success is True
    assert resolved.render_result is real_render
    assert resolved.job is job


def test_orchestration_resolution_never_crashes_on_a_job_state_mismatch() -> None:
    """
    Real, important robustness finding: RenderOrchestrationResult.
    succeeded() cross-validates job.status (must be COMPLETED) and
    job.current_stage (must be READY_FOR_UPLOAD/UPLOADED) against what
    it derives from them - true for a job whose render completed
    through the real orchestrator's own full stage sequence, but not
    guaranteed for one that succeeded through some other path (e.g.
    render succeeded but job.status is still RUNNING because packaging
    hasn't happened yet). This is a display/gating decision, not a
    correctness one, so a real ValidationError here must degrade to
    "nothing to show" rather than crash the GUI.
    """

    real_render = _render_result()
    job = _job_with_render_result(real_render)
    # Deliberately NOT setting job.status/current_stage to the values
    # succeeded() requires - this is the real mismatch case.

    resolved = resolve_effective_render_orchestration_result(job, None)

    assert resolved is None


def test_orchestration_resolution_does_not_synthesize_for_a_failed_render() -> None:
    failed_render = _render_result(success=False)
    job = _job_with_render_result(failed_render)
    job.status = JobStatus.FAILED
    job.current_stage = WorkflowStage.RENDER

    assert resolve_effective_render_orchestration_result(job, None) is None


def test_orchestration_resolution_returns_none_when_nothing_is_available() -> None:
    job = _job()

    assert resolve_effective_render_orchestration_result(job, None) is None


def _completed_orchestration(
    job: VideoJob, render: RenderResult
) -> RenderOrchestrationResult:
    job.status = JobStatus.COMPLETED
    job.current_stage = WorkflowStage.READY_FOR_UPLOAD

    return RenderOrchestrationResult(
        success=True,
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
        job=job,
        render_result=render,
    )


def _with_title_card_render(
    output_file: str = "outputs/with_title_card.mp4",
) -> RenderResult:
    return RenderResult(
        success=True,
        render_engine="ffmpeg",
        status=RenderStatus.COMPLETED,
        output_file=output_file,
    )


def test_replace_helper_updates_both_the_nested_and_embedded_render_result() -> None:
    old_render = _render_result()
    new_render = _with_title_card_render()
    job = _job_with_render_result(old_render)
    original = _completed_orchestration(job, old_render)

    replaced = replace_orchestration_render_result(original, new_render)

    assert replaced.render_result is new_render
    assert replaced.job.render_result is new_render
    # The original must not be mutated - callers hold references to it.
    assert original.render_result is old_render
    assert original.job.render_result is old_render


def test_replace_helper_result_survives_a_full_validation_round_trip() -> None:
    """
    The exact failure from 2026-10-02: a bare model_copy() of only the
    nested render_result produces an object that serializes fine but
    fails RenderOrchestrationResult's own consistency check when it is
    read back. The helper's output must re-validate.
    """

    old_render = _render_result()
    new_render = _with_title_card_render()
    job = _job_with_render_result(old_render)
    original = _completed_orchestration(job, old_render)

    naive = original.model_copy(update={"render_result": new_render})

    with pytest.raises(ValidationError):
        RenderOrchestrationResult.model_validate_json(naive.model_dump_json())

    replaced = replace_orchestration_render_result(original, new_render)

    assert (
        RenderOrchestrationResult.model_validate_json(replaced.model_dump_json())
        == replaced
    )


def test_replaced_result_saved_to_json_store_loads_back_in_a_fresh_store(
    tmp_path: Path,
) -> None:
    """
    Reproduces the real crash end to end: save through one JsonJobStore,
    then read through a brand-new one (what an app restart does, with
    no in-memory cache to hide an invalid file).
    """

    old_render = _render_result()
    new_render = _with_title_card_render()
    job = _job_with_render_result(old_render)
    replaced = replace_orchestration_render_result(
        _completed_orchestration(job, old_render), new_render
    )

    JsonJobStore(storage_root=tmp_path).set_render_result(job.id, replaced)

    loaded = JsonJobStore(storage_root=tmp_path).get_render_result(job.id)

    assert loaded is not None
    assert loaded.render_result is not None
    assert loaded.render_result.output_file == "outputs/with_title_card.mp4"
    assert loaded.job.render_result is not None
    assert loaded.job.render_result.output_file == "outputs/with_title_card.mp4"


def test_json_store_treats_an_invalid_render_result_file_as_no_cached_result(
    tmp_path: Path,
) -> None:
    """
    An already-corrupt render_result.json (written before the fix) must
    not make the project unopenable - it degrades to "no cached result"
    so the VideoJob.render_result fallback takes over.
    """

    old_render = _render_result()
    new_render = _with_title_card_render()
    job = _job_with_render_result(old_render)
    original = _completed_orchestration(job, old_render)
    naive = original.model_copy(update={"render_result": new_render})

    (tmp_path / f"{job.id}.render_result.json").write_text(
        json.dumps(json.loads(naive.model_dump_json())),
        encoding="utf-8",
    )

    store = JsonJobStore(storage_root=tmp_path)

    assert store.get_render_result(job.id) is None
    assert (
        resolve_effective_render_result(job, store.get_render_result(job.id))
        is old_render
    )
