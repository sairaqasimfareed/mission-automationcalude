from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.models.enums import (
    JobStatus,
    Platform,
    ProductionMode,
    WorkflowStage,
)
from src.models.project_specification import ProjectSpecification
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.video_job import VideoJob
from src.services.mission_application_service import (
    MissionApplicationService,
)
from src.shared.exceptions import ConfigurationError


class FakeJobMapper:
    def __init__(
        self,
        *,
        job: VideoJob | None = None,
        error: Exception | None = None,
    ) -> None:
        self.job = job
        self.error = error

        self.calls: list[
            tuple[
                ProjectSpecification,
                str,
            ]
        ] = []

    def map(
        self,
        specification: ProjectSpecification,
        *,
        niche: str,
    ) -> VideoJob:
        self.calls.append(
            (
                specification,
                niche,
            )
        )

        if self.error is not None:
            raise self.error

        assert self.job is not None

        return self.job


class FakeContentPipeline:
    def __init__(
        self,
        *,
        returned_job: VideoJob | None = None,
        error: Exception | None = None,
        call_order: list[str] | None = None,
    ) -> None:
        self.returned_job = returned_job
        self.error = error
        self.call_order = call_order

        self.calls: list[VideoJob] = []

    def run(
        self,
        job: VideoJob,
    ) -> VideoJob:
        self.calls.append(job)

        if self.call_order is not None:
            self.call_order.append(
                "content"
            )

        if self.error is not None:
            raise self.error

        if self.returned_job is not None:
            return self.returned_job

        return job


class FakeRenderOrchestrator:
    def __init__(
        self,
        *,
        result: RenderOrchestrationResult,
        call_order: list[str] | None = None,
    ) -> None:
        self.result = result
        self.call_order = call_order

        self.calls: list[
            tuple[
                VideoJob,
                bool,
                UUID | None,
                dict[str, Any] | None,
            ]
        ] = []

    def execute(
        self,
        job: VideoJob,
        *,
        dry_run: bool = False,
        checkpoint_id: UUID | None = None,
        user_input: dict[str, Any] | None = None,
    ) -> RenderOrchestrationResult:
        self.calls.append(
            (
                job,
                dry_run,
                checkpoint_id,
                user_input,
            )
        )

        if self.call_order is not None:
            self.call_order.append(
                "render"
            )

        return self.result


def build_job(
    *,
    project_name: str = "Application Service Test",
) -> VideoJob:
    return VideoJob(
        project_name=project_name,
        channel_name="Mission Channel",
        niche="History Documentary",
        topic="Hidden underground cities",
        platform=Platform.YOUTUBE,
        production_mode=ProductionMode.PREMIUM,
        status=JobStatus.PENDING,
        current_stage=WorkflowStage.RESEARCH,
    )


def build_result(
    job: VideoJob,
) -> RenderOrchestrationResult:
    job.status = JobStatus.FAILED
    job.current_stage = WorkflowStage.RENDER

    return RenderOrchestrationResult.failed(
        job=job,
        failed_stage=WorkflowStage.RENDER,
        completed_stages=[],
        elapsed_seconds=0.1,
        error_message="Synthetic render failure.",
    )


def build_specification() -> ProjectSpecification:
    from tests.test_project_specification_job_mapper import (
        build_specification as build_mapper_specification,
    )

    return build_mapper_specification()


def test_exposes_configured_dependencies() -> None:
    job = build_job()
    result = build_result(job)

    mapper = FakeJobMapper(
        job=job,
    )

    content = FakeContentPipeline()

    render = FakeRenderOrchestrator(
        result=result,
    )

    service = MissionApplicationService(
        job_mapper=mapper,  # type: ignore[arg-type]
        content_pipeline=content,  # type: ignore[arg-type]
        render_orchestrator=render,  # type: ignore[arg-type]
    )

    assert service.job_mapper is mapper
    assert service.content_pipeline is content
    assert service.render_orchestrator is render


def test_execute_maps_runs_content_and_renders() -> None:
    specification = build_specification()

    mapped_job = build_job(
        project_name="Mapped Job",
    )

    prepared_job = mapped_job.model_copy(
        deep=True
    )

    result = build_result(
        prepared_job
    )

    mapper = FakeJobMapper(
        job=mapped_job,
    )

    content = FakeContentPipeline(
        returned_job=prepared_job,
    )

    render = FakeRenderOrchestrator(
        result=result,
    )

    service = MissionApplicationService(
        job_mapper=mapper,  # type: ignore[arg-type]
        content_pipeline=content,  # type: ignore[arg-type]
        render_orchestrator=render,  # type: ignore[arg-type]
    )

    actual = service.execute(
        specification,
        niche="History Documentary",
        dry_run=True,
    )

    assert actual is result

    assert mapper.calls == [
        (
            specification,
            "History Documentary",
        )
    ]

    assert content.calls == [
        mapped_job
    ]

    assert render.calls == [
        (
            prepared_job,
            True,
            None,
            None,
        )
    ]


def test_execute_preserves_dependency_call_order() -> None:
    specification = build_specification()

    job = build_job()

    call_order: list[str] = []

    class OrderedMapper(
        FakeJobMapper
    ):
        def map(
            self,
            specification: ProjectSpecification,
            *,
            niche: str,
        ) -> VideoJob:
            call_order.append(
                "mapper"
            )

            return super().map(
                specification,
                niche=niche,
            )

    mapper = OrderedMapper(
        job=job,
    )

    content = FakeContentPipeline(
        call_order=call_order,
    )

    result = build_result(
        job
    )

    render = FakeRenderOrchestrator(
        result=result,
        call_order=call_order,
    )

    service = MissionApplicationService(
        job_mapper=mapper,  # type: ignore[arg-type]
        content_pipeline=content,  # type: ignore[arg-type]
        render_orchestrator=render,  # type: ignore[arg-type]
    )

    service.execute(
        specification,
        niche="History Documentary",
    )

    assert call_order == [
        "mapper",
        "content",
        "render",
    ]


def test_execute_propagates_mapper_configuration_error() -> None:
    specification = build_specification()

    mapper = FakeJobMapper(
        error=ConfigurationError(
            "Unsupported specification."
        )
    )

    job = build_job()

    content = FakeContentPipeline()

    render = FakeRenderOrchestrator(
        result=build_result(job),
    )

    service = MissionApplicationService(
        job_mapper=mapper,  # type: ignore[arg-type]
        content_pipeline=content,  # type: ignore[arg-type]
        render_orchestrator=render,  # type: ignore[arg-type]
    )

    with pytest.raises(
        ConfigurationError,
        match="Unsupported specification",
    ):
        service.execute(
            specification,
            niche="History Documentary",
        )

    assert content.calls == []
    assert render.calls == []


def test_execute_propagates_content_pipeline_error() -> None:
    specification = build_specification()

    job = build_job()

    mapper = FakeJobMapper(
        job=job,
    )

    content = FakeContentPipeline(
        error=RuntimeError(
            "Content generation failed."
        )
    )

    render = FakeRenderOrchestrator(
        result=build_result(job),
    )

    service = MissionApplicationService(
        job_mapper=mapper,  # type: ignore[arg-type]
        content_pipeline=content,  # type: ignore[arg-type]
        render_orchestrator=render,  # type: ignore[arg-type]
    )

    with pytest.raises(
        RuntimeError,
        match="Content generation failed",
    ):
        service.execute(
            specification,
            niche="History Documentary",
        )

    assert len(mapper.calls) == 1

    assert content.calls == [
        job
    ]

    assert render.calls == []


def test_execute_forwards_dry_run_false_by_default() -> None:
    specification = build_specification()

    job = build_job()

    result = build_result(
        job
    )

    service = MissionApplicationService(
        job_mapper=FakeJobMapper(
            job=job,
        ),  # type: ignore[arg-type]
        content_pipeline=FakeContentPipeline(),  # type: ignore[arg-type]
        render_orchestrator=FakeRenderOrchestrator(
            result=result,
        ),  # type: ignore[arg-type]
    )

    actual = service.execute(
        specification,
        niche="History Documentary",
    )

    assert actual is result

    render = service.render_orchestrator

    assert isinstance(
        render,
        FakeRenderOrchestrator,
    )

    assert render.calls == [
        (
            job,
            False,
            None,
            None,
        )
    ]


def test_resume_bypasses_mapper_and_content_pipeline() -> None:
    job = build_job()

    result = build_result(
        job
    )

    mapper = FakeJobMapper(
        error=AssertionError(
            "Mapper must not run during resume."
        )
    )

    content = FakeContentPipeline(
        error=AssertionError(
            "Content pipeline must not run during resume."
        )
    )

    render = FakeRenderOrchestrator(
        result=result,
    )

    service = MissionApplicationService(
        job_mapper=mapper,  # type: ignore[arg-type]
        content_pipeline=content,  # type: ignore[arg-type]
        render_orchestrator=render,  # type: ignore[arg-type]
    )

    actual = service.resume(
        job,
    )

    assert actual is result
    assert mapper.calls == []
    assert content.calls == []

    assert render.calls == [
        (
            job,
            False,
            None,
            None,
        )
    ]


def test_resume_forwards_checkpoint_user_input_and_dry_run() -> None:
    job = build_job()

    result = build_result(
        job
    )

    checkpoint_id = uuid4()

    user_input: dict[str, Any] = {
        "scene_number": 3,
        "decision": "manual_upload",
    }

    render = FakeRenderOrchestrator(
        result=result,
    )

    service = MissionApplicationService(
        job_mapper=FakeJobMapper(
            job=job,
        ),  # type: ignore[arg-type]
        content_pipeline=FakeContentPipeline(),  # type: ignore[arg-type]
        render_orchestrator=render,  # type: ignore[arg-type]
    )

    actual = service.resume(
        job,
        checkpoint_id=checkpoint_id,
        user_input=user_input,
        dry_run=True,
    )

    assert actual is result

    assert render.calls == [
        (
            job,
            True,
            checkpoint_id,
            user_input,
        )
    ]


def test_execute_returns_orchestrator_result_unchanged() -> None:
    specification = build_specification()

    job = build_job()

    expected = build_result(
        job
    )

    service = MissionApplicationService(
        job_mapper=FakeJobMapper(
            job=job,
        ),  # type: ignore[arg-type]
        content_pipeline=FakeContentPipeline(),  # type: ignore[arg-type]
        render_orchestrator=FakeRenderOrchestrator(
            result=expected,
        ),  # type: ignore[arg-type]
    )

    actual = service.execute(
        specification,
        niche="History Documentary",
    )

    assert actual is expected