from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from src.models.audio_timeline import AudioTimeline
from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.enums import (
    JobStatus,
    Platform,
    ProductionMode,
    WorkflowStage,
)
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.project_specification import (
    ProjectSpecification,
)
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
)
from src.models.render_result import RenderResult, RenderStatus
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene, SceneStatus
from src.models.script import Script, ScriptStatus
from src.models.seo import SEOPackage, SEOPlatformMetadata, TitleCandidate
from src.models.thumbnail import (
    ThumbnailArtifact,
    ThumbnailConcept,
    ThumbnailImageSourceType,
    ThumbnailLayout,
)
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.providers.dry_run_thumbnail_image_provider import (
    DryRunThumbnailImageProvider,
)
from src.services.content_pipeline import (
    ContentPipeline,
)
from src.services.final_export.final_export_service import (
    FinalExportService,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.mission_application_service import (
    MissionApplicationService,
)
from src.services.project_render_runtime_factory import (
    ProjectRenderRuntimeFactory,
)
from src.services.project_specification_job_mapper import (
    ProjectSpecificationJobMapper,
)
from src.services.render_orchestrator_service import (
    RenderOrchestratorService,
)
from src.services.seo.seo_description_generation_service import (
    SEODescriptionGenerationService,
)
from src.services.seo.seo_package_service import SEOPackageService
from src.services.seo.seo_title_generation_service import (
    SEOTitleGenerationService,
)
from src.services.thumbnail.thumbnail_concept_generation_service import (
    ThumbnailConceptGenerationService,
)
from src.services.thumbnail.thumbnail_package_service import (
    ThumbnailPackageService,
)
from src.shared.exceptions import ConfigurationError
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


def _as[T](
    dependency_type: type[T],
    value: object,
) -> T:
    del dependency_type

    return cast(
        T,
        value,
    )


class FakeJobMapper:
    def __init__(
        self,
        *,
        job: VideoJob | None = None,
        error: Exception | None = None,
        call_order: list[str] | None = None,
    ) -> None:
        self.job = job
        self.error = error
        self.call_order = call_order

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

        if self.call_order is not None:
            self.call_order.append("mapper")

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
            self.call_order.append("content")

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
            self.call_order.append("render")

        return self.result


class FakeRenderRuntimeFactory:
    def __init__(
        self,
        *,
        orchestrator: FakeRenderOrchestrator,
        error: Exception | None = None,
        call_order: list[str] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.error = error
        self.call_order = call_order

        self.calls: list[
            tuple[
                VideoJob,
                str,
                str,
                str,
                str | None,
                dict[
                    int,
                    SceneEditingDirectives,
                ]
                | None,
                str,
                int,
                bool,
            ]
        ] = []

    def build(
        self,
        *,
        job: VideoJob,
        genre_id: str,
        language: str = "English",
        language_code: str = "en",
        voice_provider_name: str | None = None,
        overrides_by_scene: (
            dict[
                int,
                SceneEditingDirectives,
            ]
            | None
        ) = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
    ) -> RenderOrchestratorService:
        self.calls.append(
            (
                job,
                genre_id,
                language,
                language_code,
                voice_provider_name,
                overrides_by_scene,
                output_resolution,
                frame_rate,
                warn_on_blueprint_fallbacks,
            )
        )

        if self.call_order is not None:
            self.call_order.append("runtime")

        if self.error is not None:
            raise self.error

        return _as(
            RenderOrchestratorService,
            self.orchestrator,
        )


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
        error_message=("Synthetic render failure."),
    )


def build_specification() -> ProjectSpecification:
    from tests.test_project_specification_job_mapper import (
        build_specification as build_mapper_specification,
    )

    return build_mapper_specification()


def _service(
    *,
    mapper: FakeJobMapper,
    content: FakeContentPipeline,
    runtime_factory: FakeRenderRuntimeFactory,
    seo_package_service: SEOPackageService | None = None,
    thumbnail_package_service: ThumbnailPackageService | None = None,
    final_export_service: FinalExportService | None = None,
) -> MissionApplicationService:
    return MissionApplicationService(
        job_mapper=_as(
            ProjectSpecificationJobMapper,
            mapper,
        ),
        content_pipeline=_as(
            ContentPipeline,
            content,
        ),
        render_runtime_factory=_as(
            ProjectRenderRuntimeFactory,
            runtime_factory,
        ),
        seo_package_service=seo_package_service,
        thumbnail_package_service=thumbnail_package_service,
        final_export_service=final_export_service,
    )


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

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=mapper,
        content=content,
        runtime_factory=runtime_factory,
    )

    assert service.job_mapper is mapper
    assert service.content_pipeline is content
    assert service.render_runtime_factory is runtime_factory


def test_execute_maps_runs_content_builds_runtime_and_renders() -> None:
    specification = build_specification()

    mapped_job = build_job(
        project_name="Mapped Job",
    )

    prepared_job = mapped_job.model_copy(deep=True)

    result = build_result(prepared_job)

    mapper = FakeJobMapper(
        job=mapped_job,
    )

    content = FakeContentPipeline(
        returned_job=prepared_job,
    )

    render = FakeRenderOrchestrator(
        result=result,
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=mapper,
        content=content,
        runtime_factory=runtime_factory,
    )

    actual = service.execute(
        specification,
        niche="History Documentary",
        genre_id="documentary",
    )

    assert actual is result

    assert mapper.calls == [
        (
            specification,
            "History Documentary",
        )
    ]

    assert content.calls == [mapped_job]

    assert len(runtime_factory.calls) == 1

    runtime_call = runtime_factory.calls[0]

    assert runtime_call[0] is prepared_job
    assert runtime_call[1] == "documentary"
    assert runtime_call[2] == "English"
    assert runtime_call[3] == "en"
    assert runtime_call[4] is None
    assert runtime_call[5] is None
    assert runtime_call[6] == "1920x1080"
    assert runtime_call[7] == 30
    assert runtime_call[8] is True

    assert render.calls == [
        (
            prepared_job,
            False,
            None,
            None,
        )
    ]


def test_execute_preserves_dependency_call_order() -> None:
    specification = build_specification()
    job = build_job()

    call_order: list[str] = []

    mapper = FakeJobMapper(
        job=job,
        call_order=call_order,
    )

    content = FakeContentPipeline(
        call_order=call_order,
    )

    result = build_result(job)

    render = FakeRenderOrchestrator(
        result=result,
        call_order=call_order,
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
        call_order=call_order,
    )

    service = _service(
        mapper=mapper,
        content=content,
        runtime_factory=runtime_factory,
    )

    service.execute(
        specification,
        niche="History Documentary",
        genre_id="documentary",
    )

    assert call_order == [
        "mapper",
        "content",
        "runtime",
        "render",
    ]


def test_execute_forwards_runtime_configuration() -> None:
    specification = build_specification()
    job = build_job()

    result = build_result(job)

    render = FakeRenderOrchestrator(
        result=result,
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=FakeJobMapper(
            job=job,
        ),
        content=FakeContentPipeline(),
        runtime_factory=runtime_factory,
    )

    overrides = cast(
        dict[int, SceneEditingDirectives],
        {
            3: object(),
        },
    )

    service.execute(
        specification,
        niche="History Documentary",
        genre_id="history-documentary",
        language="Urdu",
        language_code="ur-pk",
        voice_provider_name="elevenlabs",
        overrides_by_scene=overrides,
        output_resolution="3840x2160",
        frame_rate=60,
        warn_on_blueprint_fallbacks=False,
        dry_run=True,
    )

    assert runtime_factory.calls == [
        (
            job,
            "history-documentary",
            "Urdu",
            "ur-pk",
            "elevenlabs",
            overrides,
            "3840x2160",
            60,
            False,
        )
    ]

    assert render.calls == [
        (
            job,
            True,
            None,
            None,
        )
    ]


def test_execute_propagates_mapper_configuration_error() -> None:
    specification = build_specification()

    mapper = FakeJobMapper(error=ConfigurationError("Unsupported specification."))

    content = FakeContentPipeline()

    job = build_job()

    render = FakeRenderOrchestrator(
        result=build_result(job),
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=mapper,
        content=content,
        runtime_factory=runtime_factory,
    )

    with pytest.raises(
        ConfigurationError,
        match="Unsupported specification",
    ):
        service.execute(
            specification,
            niche="History Documentary",
            genre_id="documentary",
        )

    assert content.calls == []
    assert runtime_factory.calls == []
    assert render.calls == []


def test_execute_propagates_content_pipeline_error() -> None:
    specification = build_specification()
    job = build_job()

    mapper = FakeJobMapper(
        job=job,
    )

    content = FakeContentPipeline(error=RuntimeError("Content generation failed."))

    render = FakeRenderOrchestrator(
        result=build_result(job),
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=mapper,
        content=content,
        runtime_factory=runtime_factory,
    )

    with pytest.raises(
        RuntimeError,
        match="Content generation failed",
    ):
        service.execute(
            specification,
            niche="History Documentary",
            genre_id="documentary",
        )

    assert len(mapper.calls) == 1
    assert runtime_factory.calls == []
    assert render.calls == []


def test_execute_propagates_runtime_factory_error() -> None:
    specification = build_specification()
    job = build_job()

    render = FakeRenderOrchestrator(
        result=build_result(job),
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
        error=RuntimeError("Runtime composition failed."),
    )

    service = _service(
        mapper=FakeJobMapper(
            job=job,
        ),
        content=FakeContentPipeline(),
        runtime_factory=runtime_factory,
    )

    with pytest.raises(
        RuntimeError,
        match="Runtime composition failed",
    ):
        service.execute(
            specification,
            niche="History Documentary",
            genre_id="documentary",
        )

    assert len(runtime_factory.calls) == 1
    assert render.calls == []


def test_execute_forwards_dry_run_false_by_default() -> None:
    specification = build_specification()
    job = build_job()

    result = build_result(job)

    render = FakeRenderOrchestrator(
        result=result,
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=FakeJobMapper(
            job=job,
        ),
        content=FakeContentPipeline(),
        runtime_factory=runtime_factory,
    )

    actual = service.execute(
        specification,
        niche="History Documentary",
        genre_id="documentary",
    )

    assert actual is result

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

    result = build_result(job)

    mapper = FakeJobMapper(error=AssertionError("Mapper must not run during resume."))

    content = FakeContentPipeline(
        error=AssertionError("Content pipeline must not run during resume.")
    )

    render = FakeRenderOrchestrator(
        result=result,
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=mapper,
        content=content,
        runtime_factory=runtime_factory,
    )

    actual = service.resume(
        job,
        genre_id="documentary",
    )

    assert actual is result
    assert mapper.calls == []
    assert content.calls == []

    assert len(runtime_factory.calls) == 1
    assert runtime_factory.calls[0][0] is job
    assert runtime_factory.calls[0][1] == "documentary"

    assert render.calls == [
        (
            job,
            False,
            None,
            None,
        )
    ]


def test_resume_forwards_runtime_configuration() -> None:
    job = build_job()

    result = build_result(job)

    render = FakeRenderOrchestrator(
        result=result,
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=FakeJobMapper(
            job=job,
        ),
        content=FakeContentPipeline(),
        runtime_factory=runtime_factory,
    )

    overrides = cast(
        dict[int, SceneEditingDirectives],
        {
            2: object(),
        },
    )

    service.resume(
        job,
        genre_id="history-documentary",
        language="Urdu",
        language_code="ur-pk",
        voice_provider_name="elevenlabs",
        overrides_by_scene=overrides,
        output_resolution="3840x2160",
        frame_rate=60,
        warn_on_blueprint_fallbacks=False,
    )

    assert runtime_factory.calls == [
        (
            job,
            "history-documentary",
            "Urdu",
            "ur-pk",
            "elevenlabs",
            overrides,
            "3840x2160",
            60,
            False,
        )
    ]


def test_resume_forwards_checkpoint_user_input_and_dry_run() -> None:
    job = build_job()

    result = build_result(job)

    checkpoint_id = uuid4()

    user_input: dict[str, Any] = {
        "scene_number": 3,
        "decision": "manual_upload",
    }

    render = FakeRenderOrchestrator(
        result=result,
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=FakeJobMapper(
            job=job,
        ),
        content=FakeContentPipeline(),
        runtime_factory=runtime_factory,
    )

    actual = service.resume(
        job,
        genre_id="documentary",
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


def test_resume_builds_fresh_runtime_for_each_call() -> None:
    job = build_job()

    result = build_result(job)

    render = FakeRenderOrchestrator(
        result=result,
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=FakeJobMapper(
            job=job,
        ),
        content=FakeContentPipeline(),
        runtime_factory=runtime_factory,
    )

    service.resume(
        job,
        genre_id="documentary",
    )

    service.resume(
        job,
        genre_id="documentary",
    )

    assert len(runtime_factory.calls) == 2
    assert len(render.calls) == 2


def test_execute_returns_orchestrator_result_unchanged() -> None:
    specification = build_specification()
    job = build_job()

    expected = build_result(job)

    render = FakeRenderOrchestrator(
        result=expected,
    )

    runtime_factory = FakeRenderRuntimeFactory(
        orchestrator=render,
    )

    service = _service(
        mapper=FakeJobMapper(
            job=job,
        ),
        content=FakeContentPipeline(),
        runtime_factory=runtime_factory,
    )

    actual = service.execute(
        specification,
        niche="History Documentary",
        genre_id="documentary",
    )

    assert actual is expected


def _approved_seo_job() -> VideoJob:
    research = ResearchResult(
        topic="Hidden underground cities",
        research_summary="An overview of hidden underground cities.",
        key_facts=["Fact one."],
        prompt_version="research_prompt_v1.0.0",
        status=ResearchStatus.APPROVED,
    )

    script = Script(
        title="Hidden Underground Cities Explained",
        content="Full script content about hidden underground cities.",
        prompt_version="script_prompt_v1.0.0",
        estimated_duration_seconds=600,
        status=ScriptStatus.APPROVED,
    )

    return VideoJob(
        project_name="Underground Cities Documentary",
        channel_name="Mission Channel",
        niche="History Documentary",
        topic="Hidden underground cities",
        platform=Platform.YOUTUBE,
        research=research,
        script=script,
    )


class _StubSEOLLMService:
    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        content = (
            "Hidden Underground Cities Explained"
            if request.prompt_version == "seo_title_prompt_v1.0.0"
            else "A deep dive into hidden underground cities."
        )

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=content,
        )

        return LLMServiceResult(result=result, selected_profile_id="openai-main")


def _seo_package_service() -> SEOPackageService:
    stub = _StubSEOLLMService()

    return SEOPackageService(
        title_generation_service=SEOTitleGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
        ),
        description_generation_service=SEODescriptionGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
        ),
    )


def test_generate_seo_package_raises_when_not_configured() -> None:
    service = _service(
        mapper=FakeJobMapper(job=build_job()),
        content=FakeContentPipeline(),
        runtime_factory=FakeRenderRuntimeFactory(
            orchestrator=FakeRenderOrchestrator(result=None),  # type: ignore[arg-type]
        ),
    )

    with pytest.raises(ValueError, match="requires a configured"):
        service.generate_seo_package(
            _approved_seo_job(),
            genre_id="genre.documentary",
            target_audience="History enthusiasts",
        )


def test_generate_seo_package_returns_validated_package() -> None:
    service = _service(
        mapper=FakeJobMapper(job=build_job()),
        content=FakeContentPipeline(),
        runtime_factory=FakeRenderRuntimeFactory(
            orchestrator=FakeRenderOrchestrator(result=None),  # type: ignore[arg-type]
        ),
        seo_package_service=_seo_package_service(),
    )

    result = service.generate_seo_package(
        _approved_seo_job(),
        genre_id="genre.documentary",
        target_audience="History enthusiasts",
    )

    assert result.package.selected_title == "Hidden Underground Cities Explained"
    assert result.validation.is_valid is True


def test_generate_seo_package_does_not_require_render_result() -> None:
    # The job has never been rendered - render_result is None - and
    # generate_seo_package must still succeed, since SEO metadata only
    # needs research/script/scene content.
    job = _approved_seo_job()

    assert job.render_result is None

    service = _service(
        mapper=FakeJobMapper(job=build_job()),
        content=FakeContentPipeline(),
        runtime_factory=FakeRenderRuntimeFactory(
            orchestrator=FakeRenderOrchestrator(result=None),  # type: ignore[arg-type]
        ),
        seo_package_service=_seo_package_service(),
    )

    result = service.generate_seo_package(
        job,
        genre_id="genre.documentary",
        target_audience="History enthusiasts",
    )

    assert result.package is not None
    assert job.render_result is None
    assert job.current_stage == WorkflowStage.RESEARCH
    assert job.status == JobStatus.PENDING
    assert job.script is not None
    assert job.script.status == ScriptStatus.APPROVED
    assert job.research is not None
    assert job.research.status == ResearchStatus.APPROVED


class _StubThumbnailLLMService:
    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        content = (
            "CONCEPT: An underground city hallway.\n"
            "HOOK: HIDDEN CITY\n"
            "PROMPT: An ancient underground city hallway, dramatic lighting."
        )

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=content,
        )

        return LLMServiceResult(result=result, selected_profile_id="openai-main")


def _thumbnail_package_service(tmp_path: Path) -> ThumbnailPackageService:
    return ThumbnailPackageService(
        concept_generation_service=ThumbnailConceptGenerationService(
            llm_service=_StubThumbnailLLMService(),  # type: ignore[arg-type]
        ),
        image_provider=DryRunThumbnailImageProvider(),
        storage_root=tmp_path,
    )


def test_generate_thumbnail_raises_when_not_configured() -> None:
    service = _service(
        mapper=FakeJobMapper(job=build_job()),
        content=FakeContentPipeline(),
        runtime_factory=FakeRenderRuntimeFactory(
            orchestrator=FakeRenderOrchestrator(result=None),  # type: ignore[arg-type]
        ),
    )

    with pytest.raises(ValueError, match="requires a configured"):
        service.generate_thumbnail(
            _approved_seo_job(),
            genre_id="genre.documentary",
            target_audience="History enthusiasts",
            project_id="underground-cities-doc",
        )


def test_generate_thumbnail_returns_validated_artifact(tmp_path: Path) -> None:
    service = _service(
        mapper=FakeJobMapper(job=build_job()),
        content=FakeContentPipeline(),
        runtime_factory=FakeRenderRuntimeFactory(
            orchestrator=FakeRenderOrchestrator(result=None),  # type: ignore[arg-type]
        ),
        thumbnail_package_service=_thumbnail_package_service(tmp_path),
    )

    result = service.generate_thumbnail(
        _approved_seo_job(),
        genre_id="genre.documentary",
        target_audience="History enthusiasts",
        project_id="underground-cities-doc",
    )

    assert result.artifact.concept.hook_text == "HIDDEN CITY"
    assert result.validation.is_valid is True


def test_generate_thumbnail_does_not_require_render_result(
    tmp_path: Path,
) -> None:
    job = _approved_seo_job()

    assert job.render_result is None

    service = _service(
        mapper=FakeJobMapper(job=build_job()),
        content=FakeContentPipeline(),
        runtime_factory=FakeRenderRuntimeFactory(
            orchestrator=FakeRenderOrchestrator(result=None),  # type: ignore[arg-type]
        ),
        thumbnail_package_service=_thumbnail_package_service(tmp_path),
    )

    result = service.generate_thumbnail(
        job,
        genre_id="genre.documentary",
        target_audience="History enthusiasts",
        project_id="underground-cities-doc",
    )

    assert result.artifact is not None
    assert job.render_result is None
    assert job.current_stage == WorkflowStage.RESEARCH
    assert job.status == JobStatus.PENDING


def _seo_package() -> SEOPackage:
    return SEOPackage(
        video_job_id=uuid4(),
        title_candidates=[TitleCandidate(text="Great Video")],
        selected_title="Great Video",
        description="A complete, publish-ready description.",
        platform_metadata=SEOPlatformMetadata(platform=Platform.YOUTUBE),
        prompt_version="seo_prompt_v1.0.0",
    )


def _thumbnail_artifact() -> ThumbnailArtifact:
    return ThumbnailArtifact(
        video_job_id=uuid4(),
        concept=ThumbnailConcept(
            concept_summary="A diver facing a giant squid.",
            hook_text="GIANT SQUID",
            visual_prompt="A deep sea diver facing a giant squid.",
        ),
        layout=ThumbnailLayout(width=1280, height=720),
        image_source_type=ThumbnailImageSourceType.AI_GENERATED,
        provider_name="dry_run",
        file_path="dry-run://thumbnail/1280x720.png",
        file_size_bytes=0,
    )


def _successful_render_orchestration_result() -> RenderOrchestrationResult:
    job = VideoJob(
        project_name="Mission Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Render orchestration",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
    )

    job.research = ResearchResult.model_construct(status=ResearchStatus.APPROVED)

    job.script = Script(
        title="Synthetic orchestration script",
        content="Synthetic narration for orchestration testing.",
        prompt_version="test-1.0",
        word_count=5,
        estimated_duration_seconds=30,
        status=ScriptStatus.APPROVED,
    )

    scene = Scene(
        scene_number=1,
        title="Synthetic Scene",
        narration="Synthetic narration for orchestration testing.",
        visual_prompt="Synthetic visual prompt.",
        estimated_duration_seconds=30,
        manual_file_path="assets/videos/manual/test_scene.mp4",
        source_status=SceneSourceStatus.READY,
        status=SceneStatus.READY,
    )

    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=30,
        prompt="Synthetic orchestration test scene.",
        provider="Manual Upload",
        local_file="assets/videos/manual/test_scene.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    job.scenes = [scene]
    job.voice_file = "assets/audio/test_voice.wav"
    job.video_clips = [clip]

    job.video_timeline = VideoTimeline(clips=[clip])
    job.video_timeline.calculate_duration()

    job.audio_timeline = AudioTimeline()

    job.render_result = RenderResult(
        success=True,
        output_file="outputs/final_video.mp4",
        render_engine="ffmpeg",
        render_time_seconds=2.0,
        duration_seconds=30,
        status=RenderStatus.COMPLETED,
    )

    return RenderOrchestrationResult.succeeded(
        job=job,
        completed_stages=[
            WorkflowStage.RESEARCH,
            WorkflowStage.SCRIPT,
            WorkflowStage.RENDER,
        ],
        elapsed_seconds=3.5,
    )


def test_export_final_package_raises_when_not_configured() -> None:
    service = _service(
        mapper=FakeJobMapper(job=build_job()),
        content=FakeContentPipeline(),
        runtime_factory=FakeRenderRuntimeFactory(
            orchestrator=FakeRenderOrchestrator(result=None),  # type: ignore[arg-type]
        ),
    )

    with pytest.raises(ValueError, match="requires a configured"):
        service.export_final_package(
            _successful_render_orchestration_result(),
            project_id="deep-sea-doc",
            resolution="1920x1080",
            frame_rate=30,
            seo_package=_seo_package(),
            thumbnail_artifact=_thumbnail_artifact(),
        )


def test_export_final_package_returns_validated_package(
    tmp_path: Path,
) -> None:
    service = _service(
        mapper=FakeJobMapper(job=build_job()),
        content=FakeContentPipeline(),
        runtime_factory=FakeRenderRuntimeFactory(
            orchestrator=FakeRenderOrchestrator(result=None),  # type: ignore[arg-type]
        ),
        final_export_service=FinalExportService(
            export_root=tmp_path / "exports",
        ),
    )

    render_orchestration_result = _successful_render_orchestration_result()

    result = service.export_final_package(
        render_orchestration_result,
        project_id="deep-sea-doc",
        resolution="1920x1080",
        frame_rate=30,
        seo_package=_seo_package(),
        thumbnail_artifact=_thumbnail_artifact(),
    )

    assert result.package.video_job_id == render_orchestration_result.job.id
    assert result.package.duration_seconds == 30
