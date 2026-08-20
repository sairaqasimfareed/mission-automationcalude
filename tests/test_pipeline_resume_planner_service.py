from __future__ import annotations

from uuid import uuid4

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.models.video_job import VideoJob
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_checkpoint import (
    PipelineCheckpoint,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.pipeline_resume_planner_service import (
    PipelineResumePlannerService,
)


class SyntheticStage(BasePipelineStage):
    def __init__(
        self,
        stage_name: PipelineStageName,
    ) -> None:
        self._stage_name = stage_name

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return self._stage_name

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        del context

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.COMPLETED),
        )


def build_job() -> VideoJob:
    return VideoJob(
        project_name="Resume Planner Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Pipeline resume planning",
    )


def build_stages() -> list[BasePipelineStage]:
    return [
        SyntheticStage(PipelineStageName.VOICE),
        SyntheticStage(PipelineStageName.ASSET_SELECTION),
        SyntheticStage(PipelineStageName.VIDEO_TIMELINE),
        SyntheticStage(PipelineStageName.RENDER),
    ]


def completed(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(PipelineStageStatus.COMPLETED),
    )


def failed(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(PipelineStageStatus.FAILED),
        errors=[
            "Synthetic failure.",
        ],
    )


def waiting(
    stage: PipelineStageName,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=(PipelineStageStatus.WAITING_FOR_USER),
    )


def test_failed_stage_resume_plan() -> None:
    job = build_job()

    checkpoint = PipelineCheckpoint(
        job_id=job.id,
        current_stage=(PipelineStageName.VIDEO_TIMELINE),
        overall_progress=75,
        completed_stages=[
            PipelineStageName.VOICE,
            PipelineStageName.ASSET_SELECTION,
        ],
        failed_stage=(PipelineStageName.VIDEO_TIMELINE),
        stage_results=[
            completed(PipelineStageName.VOICE),
            completed(PipelineStageName.ASSET_SELECTION),
            failed(PipelineStageName.VIDEO_TIMELINE),
        ],
    )

    plan = PipelineResumePlannerService().create_plan(
        job=job,
        checkpoint=checkpoint,
        stages=build_stages(),
        settings=AdvancedSettings(),
    )

    assert plan.resume_enabled is True

    assert plan.resume_stage == PipelineStageName.VIDEO_TIMELINE

    assert plan.skipped_stages == [
        PipelineStageName.VOICE,
        PipelineStageName.ASSET_SELECTION,
    ]

    assert plan.execution_stages == [
        PipelineStageName.VIDEO_TIMELINE,
        PipelineStageName.RENDER,
    ]

    assert plan.resumed_from_failure is True


def test_waiting_stage_resume_plan() -> None:
    job = build_job()

    checkpoint = PipelineCheckpoint(
        job_id=job.id,
        current_stage=(PipelineStageName.ASSET_SELECTION),
        overall_progress=50,
        completed_stages=[
            PipelineStageName.VOICE,
        ],
        waiting_stage=(PipelineStageName.ASSET_SELECTION),
        stage_results=[
            completed(PipelineStageName.VOICE),
            waiting(PipelineStageName.ASSET_SELECTION),
        ],
    )

    plan = PipelineResumePlannerService().create_plan(
        job=job,
        checkpoint=checkpoint,
        stages=build_stages(),
        settings=AdvancedSettings(),
    )

    assert plan.resume_stage == PipelineStageName.ASSET_SELECTION

    assert plan.skipped_stages == [
        PipelineStageName.VOICE,
    ]

    assert plan.execution_stages == [
        PipelineStageName.ASSET_SELECTION,
        PipelineStageName.VIDEO_TIMELINE,
        PipelineStageName.RENDER,
    ]

    assert plan.resumed_from_waiting is True


def test_resume_disabled_executes_full_pipeline() -> None:
    job = build_job()

    checkpoint = PipelineCheckpoint(
        job_id=job.id,
        current_stage=(PipelineStageName.RENDER),
        failed_stage=(PipelineStageName.RENDER),
        stage_results=[
            failed(PipelineStageName.RENDER),
        ],
    )

    settings = AdvancedSettings(
        resume_previous_pipeline=False,
    )

    plan = PipelineResumePlannerService().create_plan(
        job=job,
        checkpoint=checkpoint,
        stages=build_stages(),
        settings=settings,
    )

    assert plan.resume_enabled is False

    assert plan.execution_stages == [
        PipelineStageName.VOICE,
        PipelineStageName.ASSET_SELECTION,
        PipelineStageName.VIDEO_TIMELINE,
        PipelineStageName.RENDER,
    ]


def test_skip_completed_disabled_restarts_pipeline() -> None:
    job = build_job()

    checkpoint = PipelineCheckpoint(
        job_id=job.id,
        current_stage=(PipelineStageName.RENDER),
        completed_stages=[
            PipelineStageName.VOICE,
            PipelineStageName.ASSET_SELECTION,
            PipelineStageName.VIDEO_TIMELINE,
        ],
        failed_stage=(PipelineStageName.RENDER),
        stage_results=[
            completed(PipelineStageName.VOICE),
            completed(PipelineStageName.ASSET_SELECTION),
            completed(PipelineStageName.VIDEO_TIMELINE),
            failed(PipelineStageName.RENDER),
        ],
    )

    settings = AdvancedSettings(
        skip_completed_stages=False,
    )

    plan = PipelineResumePlannerService().create_plan(
        job=job,
        checkpoint=checkpoint,
        stages=build_stages(),
        settings=settings,
    )

    assert plan.resume_enabled is True

    assert plan.resume_stage == PipelineStageName.VOICE

    assert plan.skipped_stages == []

    assert plan.execution_stages == [
        PipelineStageName.VOICE,
        PipelineStageName.ASSET_SELECTION,
        PipelineStageName.VIDEO_TIMELINE,
        PipelineStageName.RENDER,
    ]


def test_wrong_job_checkpoint_rejected() -> None:
    job = build_job()

    checkpoint = PipelineCheckpoint(
        job_id=uuid4(),
        current_stage=(PipelineStageName.RENDER),
        failed_stage=(PipelineStageName.RENDER),
        stage_results=[
            failed(PipelineStageName.RENDER),
        ],
    )

    try:
        (
            PipelineResumePlannerService().create_plan(
                job=job,
                checkpoint=checkpoint,
                stages=build_stages(),
                settings=AdvancedSettings(),
            )
        )
    except ValueError as error:
        assert "does not belong" in str(error)
    else:
        raise AssertionError("Wrong-job checkpoint must fail.")


def test_unregistered_checkpoint_stage_rejected() -> None:
    job = build_job()

    checkpoint = PipelineCheckpoint(
        job_id=job.id,
        current_stage=(PipelineStageName.SCRIPT),
        failed_stage=(PipelineStageName.SCRIPT),
        stage_results=[
            failed(PipelineStageName.SCRIPT),
        ],
    )

    try:
        (
            PipelineResumePlannerService().create_plan(
                job=job,
                checkpoint=checkpoint,
                stages=build_stages(),
                settings=AdvancedSettings(),
            )
        )
    except ValueError as error:
        assert "unregistered stage" in str(error)
    else:
        raise AssertionError("Unregistered checkpoint " "stage must fail.")


def test_completed_checkpoint_has_no_resume_execution() -> None:
    job = build_job()

    checkpoint = PipelineCheckpoint(
        job_id=job.id,
        current_stage=(PipelineStageName.RENDER),
        overall_progress=100,
        completed_stages=[
            PipelineStageName.VOICE,
            PipelineStageName.ASSET_SELECTION,
            PipelineStageName.VIDEO_TIMELINE,
            PipelineStageName.RENDER,
        ],
        stage_results=[
            completed(PipelineStageName.VOICE),
            completed(PipelineStageName.ASSET_SELECTION),
            completed(PipelineStageName.VIDEO_TIMELINE),
            completed(PipelineStageName.RENDER),
        ],
    )

    plan = PipelineResumePlannerService().create_plan(
        job=job,
        checkpoint=checkpoint,
        stages=build_stages(),
        settings=AdvancedSettings(),
    )

    assert plan.resume_enabled is False
    assert plan.execution_stages == []


def main() -> None:
    print()
    print("Running Pipeline Resume Planner tests...")
    print()

    test_failed_stage_resume_plan()
    test_waiting_stage_resume_plan()
    test_resume_disabled_executes_full_pipeline()
    test_skip_completed_disabled_restarts_pipeline()
    test_wrong_job_checkpoint_rejected()
    test_unregistered_checkpoint_stage_rejected()
    test_completed_checkpoint_has_no_resume_execution()

    print()
    print("Pipeline Resume Planner tests " "completed successfully.")


if __name__ == "__main__":
    main()
