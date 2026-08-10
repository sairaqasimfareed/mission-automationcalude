from __future__ import annotations

from typing import TypeVar, cast

from src.models.advanced_settings import AdvancedSettings
from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.models.voice_directives import (
    SceneVoiceDirectives,
)
from src.pipeline.base_stage import (
    BasePipelineStage,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
)
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.pipeline_checkpoint_service import (
    PipelineCheckpointService,
)
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointStorageService,
)
from src.services.pipeline_resume_planner_service import (
    PipelineResumePlannerService,
)
from src.services.project_render_runtime_factory import (
    ProjectRenderRuntimeFactory,
)
from src.services.render_orchestrator_service import (
    RenderOrchestratorService,
)
from src.services.render_workflow_stage_factory import (
    RenderWorkflowStageFactory,
)
from src.services.voice_resolution_runtime import (
    VoiceResolutionRequest,
    VoiceResolutionRuntime,
)


T = TypeVar("T")


def _dependency(
    dependency_type: type[T],
) -> T:
    """
    Create a typed identity-only dependency.

    These tests verify composition only. Dependencies that are merely
    retained by the runtime factory or orchestrator do not need to be
    executable.
    """

    del dependency_type

    return cast(
        T,
        object(),
    )


def _scene(
    scene_number: int,
) -> Scene:
    """Build one valid synthetic scene."""

    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration=f"Narration {scene_number}.",
        visual_prompt=(
            f"Visual prompt {scene_number}."
        ),
        estimated_duration_seconds=(
            scene_number * 10
        ),
    )


def _job() -> VideoJob:
    """
    Build one prepared render-runtime job.

    Scenes are deliberately reversed so deterministic scene/directive
    alignment can be verified.
    """

    job = VideoJob(
        project_name=(
            "Project Runtime Factory Test"
        ),
        channel_name="Mission Channel",
        niche="documentary",
        topic="Runtime assembly",
    )

    job.scenes = [
        _scene(2),
        _scene(1),
    ]

    return job


def _directive(
    scene_number: int,
) -> SceneVoiceDirectives:
    """Build one provider-independent synthetic voice directive."""

    return SceneVoiceDirectives(
        scene_number=scene_number,
        voice_profile_id=(
            "voice.documentary"
        ),
    )


def _blueprint(
    scene_number: int,
) -> ResolvedVoiceBlueprint:
    """Build one valid synthetic resolved voice blueprint."""

    return ResolvedVoiceBlueprint(
        scene_number=scene_number,
        status=(
            VoiceBlueprintResolutionStatus
            .RESOLVED
        ),
        profile=(
            ResolvedVoiceProfileReference(
                requested_profile_id=(
                    "voice.documentary"
                ),
                resolved_profile_id=(
                    "voice.documentary"
                ),
                display_name=(
                    "Documentary Narrator"
                ),
                found_exact_match=True,
                used_fallback=False,
            )
        ),
        narration_text=(
            f"Narration {scene_number}."
        ),
    )


class RecordingDirectiveService(
    GenreVoiceDirectiveGenerationService
):
    """
    Record directive-generation calls without invoking genre registries.
    """

    def __init__(self) -> None:
        self.calls: list[
            tuple[
                list[Scene],
                str,
                str,
                str,
            ]
        ] = []

    def generate_many(
        self,
        *,
        scenes: list[Scene],
        genre_id: str,
        language: str = "English",
        language_code: str = "en",
    ) -> list[SceneVoiceDirectives]:
        self.calls.append(
            (
                list(scenes),
                genre_id,
                language,
                language_code,
            )
        )

        return [
            _directive(
                scene.scene_number
            )
            for scene in sorted(
                scenes,
                key=lambda item: (
                    item.scene_number
                ),
            )
        ]


class RecordingVoiceResolutionRuntime(
    VoiceResolutionRuntime
):
    """
    Record voice-resolution requests and return valid blueprints.
    """

    def __init__(self) -> None:
        self.calls: list[
            list[VoiceResolutionRequest]
        ] = []

    def resolve_many(
        self,
        requests: list[
            VoiceResolutionRequest
        ],
    ) -> list[
        ResolvedVoiceBlueprint
    ]:
        self.calls.append(
            list(requests)
        )

        return [
            _blueprint(
                request[0].scene_number
            )
            for request in requests
        ]


class SyntheticStage:
    """
    Minimal construction-only stage object.

    ProjectRenderRuntimeFactory tests verify composition rather than
    pipeline execution. RenderOrchestratorService construction requires
    stage_name for ordering/registration, so no execution behavior is
    required here.
    """

    def __init__(
        self,
        stage_name: PipelineStageName,
    ) -> None:
        self.stage_name = stage_name


def _stage(
    stage_name: PipelineStageName,
) -> BasePipelineStage:
    """
    Return one construction-only stage using the pipeline stage type.

    The cast is intentional because these tests never execute the stage;
    they only verify orchestration composition and registration.
    """

    return cast(
        BasePipelineStage,
        SyntheticStage(
            stage_name
        ),
    )


class RecordingStageFactory(
    RenderWorkflowStageFactory
):
    """
    Record stage-factory inputs and return canonical ordered stages.
    """

    def __init__(self) -> None:
        self.calls: list[
            tuple[
                list[
                    ResolvedVoiceBlueprint
                ],
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
        voice_blueprints: list[
            ResolvedVoiceBlueprint
        ],
        genre_id: str,
        voice_provider_name: (
            str | None
        ) = None,
        overrides_by_scene: (
            dict[
                int,
                SceneEditingDirectives,
            ]
            | None
        ) = None,
        output_resolution: str = (
            "1920x1080"
        ),
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: (
            bool
        ) = True,
    ) -> list[
        BasePipelineStage
    ]:
        self.calls.append(
            (
                list(
                    voice_blueprints
                ),
                genre_id,
                voice_provider_name,
                overrides_by_scene,
                output_resolution,
                frame_rate,
                warn_on_blueprint_fallbacks,
            )
        )

        return [
            _stage(
                PipelineStageName.VOICE
            ),
            _stage(
                PipelineStageName
                .ASSET_SELECTION
            ),
            _stage(
                PipelineStageName
                .VIDEO_TIMELINE
            ),
            _stage(
                PipelineStageName.RENDER
            ),
        ]


def _factory(
    *,
    directive_service: (
        RecordingDirectiveService
        | None
    ) = None,
    voice_runtime: (
        RecordingVoiceResolutionRuntime
        | None
    ) = None,
    stage_factory: (
        RecordingStageFactory
        | None
    ) = None,
    advanced_settings: (
        AdvancedSettings
        | None
    ) = None,
    checkpoint_storage_service: (
        PipelineCheckpointStorageService
        | None
    ) = None,
    checkpoint_service: (
        PipelineCheckpointService
        | None
    ) = None,
    resume_planner_service: (
        PipelineResumePlannerService
        | None
    ) = None,
) -> ProjectRenderRuntimeFactory:
    """Build a test runtime factory."""

    return ProjectRenderRuntimeFactory(
        voice_directive_generation_service=(
            directive_service
            or RecordingDirectiveService()
        ),
        voice_resolution_runtime=(
            voice_runtime
            or RecordingVoiceResolutionRuntime()
        ),
        stage_factory=(
            stage_factory
            or RecordingStageFactory()
        ),
        advanced_settings=(
            advanced_settings
        ),
        checkpoint_storage_service=(
            checkpoint_storage_service
        ),
        checkpoint_service=(
            checkpoint_service
        ),
        resume_planner_service=(
            resume_planner_service
        ),
    )


def test_exposes_configured_dependencies() -> None:
    directive_service = (
        RecordingDirectiveService()
    )

    voice_runtime = (
        RecordingVoiceResolutionRuntime()
    )

    stage_factory = (
        RecordingStageFactory()
    )

    advanced_settings = (
        AdvancedSettings()
    )

    checkpoint_storage = _dependency(
        PipelineCheckpointStorageService
    )

    checkpoint_service = _dependency(
        PipelineCheckpointService
    )

    resume_planner = _dependency(
        PipelineResumePlannerService
    )

    factory = _factory(
        directive_service=(
            directive_service
        ),
        voice_runtime=(
            voice_runtime
        ),
        stage_factory=(
            stage_factory
        ),
        advanced_settings=(
            advanced_settings
        ),
        checkpoint_storage_service=(
            checkpoint_storage
        ),
        checkpoint_service=(
            checkpoint_service
        ),
        resume_planner_service=(
            resume_planner
        ),
    )

    assert (
        factory
        .voice_directive_generation_service
        is directive_service
    )

    assert (
        factory.voice_resolution_runtime
        is voice_runtime
    )

    assert (
        factory.stage_factory
        is stage_factory
    )

    assert (
        factory.advanced_settings
        is advanced_settings
    )

    assert (
        factory.checkpoint_storage_service
        is checkpoint_storage
    )

    assert (
        factory.checkpoint_service
        is checkpoint_service
    )

    assert (
        factory.resume_planner_service
        is resume_planner
    )


def test_build_generates_directives_for_job_scenes() -> None:
    directive_service = (
        RecordingDirectiveService()
    )

    factory = _factory(
        directive_service=(
            directive_service
        ),
    )

    job = _job()

    factory.build(
        job=job,
        genre_id=(
            "genre.documentary"
        ),
        language="Urdu",
        language_code="ur-pk",
    )

    assert (
        len(
            directive_service.calls
        )
        == 1
    )

    (
        scenes,
        genre_id,
        language,
        language_code,
    ) = directive_service.calls[0]

    assert scenes == job.scenes

    assert (
        genre_id
        == "genre.documentary"
    )

    assert language == "Urdu"

    assert (
        language_code
        == "ur-pk"
    )


def test_build_aligns_resolution_requests_by_scene_number() -> None:
    voice_runtime = (
        RecordingVoiceResolutionRuntime()
    )

    factory = _factory(
        voice_runtime=(
            voice_runtime
        ),
    )

    factory.build(
        job=_job(),
        genre_id=(
            "genre.documentary"
        ),
    )

    assert (
        len(
            voice_runtime.calls
        )
        == 1
    )

    requests = (
        voice_runtime.calls[0]
    )

    assert [
        request[0].scene_number
        for request in requests
    ] == [
        1,
        2,
    ]

    assert [
        request[1]
        for request in requests
    ] == [
        "Narration 1.",
        "Narration 2.",
    ]

    assert [
        request[2]
        for request in requests
    ] == [
        10,
        20,
    ]


def test_build_forwards_resolved_blueprints_to_stage_factory() -> None:
    stage_factory = (
        RecordingStageFactory()
    )

    factory = _factory(
        stage_factory=(
            stage_factory
        ),
    )

    factory.build(
        job=_job(),
        genre_id=(
            "genre.documentary"
        ),
    )

    assert (
        len(
            stage_factory.calls
        )
        == 1
    )

    blueprints = (
        stage_factory.calls[0][0]
    )

    assert [
        blueprint.scene_number
        for blueprint in blueprints
    ] == [
        1,
        2,
    ]


def test_build_forwards_render_configuration() -> None:
    stage_factory = (
        RecordingStageFactory()
    )

    overrides = cast(
        dict[
            int,
            SceneEditingDirectives,
        ],
        {
            1: _dependency(
                SceneEditingDirectives
            ),
        },
    )

    factory = _factory(
        stage_factory=(
            stage_factory
        ),
    )

    factory.build(
        job=_job(),
        genre_id=(
            "genre.documentary"
        ),
        voice_provider_name=(
            "elevenlabs"
        ),
        overrides_by_scene=(
            overrides
        ),
        output_resolution=(
            "3840x2160"
        ),
        frame_rate=60,
        warn_on_blueprint_fallbacks=(
            False
        ),
    )

    assert (
        len(
            stage_factory.calls
        )
        == 1
    )

    call = stage_factory.calls[0]

    assert (
        call[1]
        == "genre.documentary"
    )

    assert (
        call[2]
        == "elevenlabs"
    )

    assert (
        call[3]
        is overrides
    )

    assert (
        call[4]
        == "3840x2160"
    )

    assert call[5] == 60

    assert (
        call[6]
        is False
    )


def test_build_returns_render_orchestrator() -> None:
    orchestrator = (
        _factory().build(
            job=_job(),
            genre_id=(
                "genre.documentary"
            ),
        )
    )

    assert isinstance(
        orchestrator,
        RenderOrchestratorService,
    )


def test_build_registers_canonical_stage_order() -> None:
    orchestrator = (
        _factory().build(
            job=_job(),
            genre_id=(
                "genre.documentary"
            ),
        )
    )

    assert [
        stage.stage_name
        for stage in orchestrator.stages
    ] == [
        PipelineStageName.VOICE,
        PipelineStageName.ASSET_SELECTION,
        PipelineStageName.VIDEO_TIMELINE,
        PipelineStageName.RENDER,
    ]


def test_build_creates_fresh_orchestrator() -> None:
    factory = _factory()
    job = _job()

    first = factory.build(
        job=job,
        genre_id=(
            "genre.documentary"
        ),
    )

    second = factory.build(
        job=job,
        genre_id=(
            "genre.documentary"
        ),
    )

    assert first is not second


def test_build_preserves_orchestrator_runtime_configuration() -> None:
    advanced_settings = (
        AdvancedSettings()
    )

    checkpoint_storage = _dependency(
        PipelineCheckpointStorageService
    )

    checkpoint_service = _dependency(
        PipelineCheckpointService
    )

    resume_planner = _dependency(
        PipelineResumePlannerService
    )

    factory = _factory(
        advanced_settings=(
            advanced_settings
        ),
        checkpoint_storage_service=(
            checkpoint_storage
        ),
        checkpoint_service=(
            checkpoint_service
        ),
        resume_planner_service=(
            resume_planner
        ),
    )

    orchestrator = factory.build(
        job=_job(),
        genre_id=(
            "genre.documentary"
        ),
    )

    assert (
        orchestrator.advanced_settings
        is advanced_settings
    )

    assert (
        orchestrator
        .checkpoint_storage_service
        is checkpoint_storage
    )

    assert (
        orchestrator
        ._checkpoint_service
        is checkpoint_service
    )

    assert (
        orchestrator
        ._resume_planner_service
        is resume_planner
    )