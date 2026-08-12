from __future__ import annotations

from src.models.asset_state import (
    AssetCandidate,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.enums import (
    JobStatus,
    WorkflowStage,
)
from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.genre_timeline_pipeline import (
    GenreTimelinePipelineResult,
    GenreTimelinePipelineStatus,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
    VoiceStatus,
)
from src.models.render_result import (
    RenderResult,
    RenderStatus,
)
from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.models.scene import (
    Scene,
    SceneStatus,
)
from src.models.script import (
    Script,
    ScriptStatus,
)
from src.models.timeline_validation import (
    TimelineValidationResult,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_job import VideoJob
from src.models.video_timeline import (
    VideoTimeline,
)
from src.models.voice_generation import (
    VoiceGenerationResult,
    VoiceGenerationStatus,
)
from src.pipeline.asset_stage import (
    AssetPipelineStage,
)
from src.pipeline.pipeline_runner import (
    PipelineRunner,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import (
    PipelineState,
)
from src.pipeline.render_stage import (
    RenderPipelineStage,
)
from src.pipeline.stage_context import (
    StageContext,
)
from src.pipeline.timeline_stage import (
    TimelinePipelineStage,
)
from src.pipeline.voice_stage import (
    VoicePipelineStage,
)
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.render_orchestrator_service import (
    RenderOrchestratorService,
)
from src.services.render_service import (
    RenderService,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)
from src.services.voice_generation_service import (
    VoiceGenerationService,
)
from src.services.voice_timeline_service import (
    VoiceTimelineService,
)


class SyntheticVoiceGenerationService(
    VoiceGenerationService
):
    """Successful deterministic voice generation."""

    def __init__(
        self,
    ) -> None:
        self.generated_scene_numbers: list[int] = []

    def generate(
        self,
        blueprint: ResolvedVoiceBlueprint,
        *,
        start_time_seconds: float = 0.0,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        del provider_name

        self.generated_scene_numbers.append(
            blueprint.scene_number
        )

        output_file = (
            "outputs/audio/"
            f"scene_{blueprint.scene_number:03d}.wav"
        )

        track = AudioTrack(
            track_type=(
                AudioTrackType.VOICEOVER
            ),
            source_file=output_file,
            start_time_seconds=(
                start_time_seconds
            ),
            duration_seconds=5.0,
            provider="synthetic-voice",
            status=AudioTrackStatus.READY,
            metadata={
                "scene_number": (
                    blueprint.scene_number
                ),
            },
        )

        return VoiceGenerationResult(
            success=True,
            scene_number=(
                blueprint.scene_number
            ),
            status=(
                VoiceGenerationStatus.COMPLETED
            ),
            provider="synthetic-voice",
            output_file=output_file,
            audio_track=track,
            attempts=1,
        )


class SyntheticReadyAssetService(
    SceneAssetWorkflowService
):
    """Return an immediately-ready state for each scene."""

    def __init__(
        self,
    ) -> None:
        self.started_scene_numbers: list[int] = []

    def start(
        self,
        scene: Scene,
    ) -> SceneAssetState:
        self.started_scene_numbers.append(
            scene.scene_number
        )

        state = SceneAssetState.model_construct(
            scene_number=scene.scene_number,
            status=AssetWorkflowStatus.READY,
            warnings=[],
            errors=[],
        )

        state.selected_source = SceneSourceType.MANUAL_UPLOAD
        state.selected_candidate = AssetCandidate(
            title=f"Synthetic asset for scene {scene.scene_number}",
            source_type=SceneSourceType.MANUAL_UPLOAD,
            file_path=(
                "assets/videos/manual/"
                f"scene_{scene.scene_number:03d}.mp4"
            ),
            approved=True,
        )

        return state


class SyntheticWaitingAssetService(
    SceneAssetWorkflowService
):
    """Return a state requiring manual user interaction."""

    def __init__(
        self,
    ) -> None:
        self.started_scene_numbers: list[int] = []

    def start(
        self,
        scene: Scene,
    ) -> SceneAssetState:
        self.started_scene_numbers.append(
            scene.scene_number
        )

        return SceneAssetState.model_construct(
            scene_number=scene.scene_number,
            status=(
                AssetWorkflowStatus
                .WAITING_FOR_MANUAL_UPLOAD
            ),
            warnings=[
                "Manual upload required.",
            ],
            errors=[],
        )


class SyntheticTimelineService(
    GenreTimelinePipelineService
):
    """Create a deterministic render-ready timeline."""

    def __init__(
        self,
    ) -> None:
        self.called = False

    def build(
        self,
        *,
        scenes: list[Scene],
        clips: list[VideoClip],
        genre_id: str,
        overrides_by_scene: dict[int, SceneEditingDirectives] | None = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
    ) -> GenreTimelinePipelineResult:
        del scenes
        del overrides_by_scene
        del warn_on_blueprint_fallbacks

        self.called = True

        timeline = VideoTimeline(
            clips=list(
                clips
            ),
            output_resolution=(
                output_resolution
            ),
            frame_rate=frame_rate,
        )

        timeline.calculate_duration()

        validation = (
            TimelineValidationResult
            .model_construct(
                is_valid=True,
                item_count=1,
                enabled_item_count=1,
                track_count=1,
                total_duration_seconds=(
                    timeline.total_duration_seconds
                ),
                gap_duration_seconds=0.0,
                overlap_duration_seconds=0.0,
                blueprint_count=1,
                render_ready_item_count=1,
                blueprint_fallback_count=0,
                errors=[],
                warnings=[],
            )
        )

        return (
            GenreTimelinePipelineResult
            .model_construct(
                requested_genre_id=(
                    genre_id
                ),
                status=(
                    GenreTimelinePipelineStatus
                    .COMPLETED
                ),
                timeline=timeline,
                directives=[],
                blueprints=[],
                validation=validation,
                warnings=[],
                metadata={
                    "synthetic": True,
                },
            )
        )


class SyntheticRenderService(
    RenderService
):
    """Successful deterministic render service."""

    def __init__(
        self,
    ) -> None:
        self.called = False

    def render(
        self,
        timeline: VideoTimeline,
    ) -> RenderResult:
        self.called = True

        return RenderResult(
            success=True,
            output_file=(
                "outputs/"
                "integration_final.mp4"
            ),
            render_engine=(
                "synthetic-render"
            ),
            render_time_seconds=0.01,
            duration_seconds=int(
                timeline.calculate_duration()
            ),
            status=RenderStatus.COMPLETED,
        )


def build_research() -> ResearchResult:
    """Build approved upstream research."""

    return ResearchResult.model_construct(
        status=ResearchStatus.APPROVED,
    )


def build_script() -> Script:
    """Build approved upstream script."""

    return Script(
        title="Adapter integration test",
        content=(
            "Synthetic narration for "
            "pipeline adapter integration."
        ),
        prompt_version="test-1.0",
        word_count=7,
        estimated_duration_seconds=10,
        status=ScriptStatus.APPROVED,
    )


def build_scene(
    scene_number: int,
) -> Scene:
    """Build one planned scene."""

    return Scene(
        scene_number=scene_number,
        title=(
            f"Integration Scene "
            f"{scene_number}"
        ),
        narration=(
            f"Synthetic narration "
            f"for scene {scene_number}."
        ),
        visual_prompt=(
            "Synthetic integration visual."
        ),
        estimated_duration_seconds=5,
        manual_file_path=(
            "assets/videos/manual/"
            f"scene_{scene_number:03d}.mp4"
        ),
        source_status=(
            SceneSourceStatus.READY
        ),
        status=SceneStatus.READY,
    )


def build_clip(
    scene_number: int,
) -> VideoClip:
    """Build one ready video clip."""

    return VideoClip(
        scene_number=scene_number,
        source_type=(
            SceneSourceType.MANUAL_UPLOAD
        ),
        duration_seconds=5,
        prompt=(
            "Synthetic integration clip."
        ),
        provider="Manual Upload",
        local_file=(
            "assets/videos/manual/"
            f"scene_{scene_number:03d}.mp4"
        ),
        source_status=(
            SceneSourceStatus.READY
        ),
        status=VideoClipStatus.READY,
    )


def build_job() -> VideoJob:
    """Build a complete pre-render integration job."""

    return VideoJob(
        project_name=(
            "Pipeline Adapter Integration"
        ),
        channel_name="Mission Channel",
        niche="horror",
        topic="Adapter integration",
        status=JobStatus.PENDING,
        current_stage=WorkflowStage.VOICE,
        research=build_research(),
        script=build_script(),
        scenes=[
            build_scene(1),
            build_scene(2),
        ],
        video_clips=[
            build_clip(1),
            build_clip(2),
        ],
    )


def build_blueprint(
    scene_number: int,
) -> ResolvedVoiceBlueprint:
    """
    Build a synthetic resolved voice blueprint.

    Blueprint validation itself belongs to its dedicated tests.
    """

    return (
        ResolvedVoiceBlueprint
        .model_construct(
            scene_number=scene_number,
        )
    )


def build_success_stages(
    *,
    voice_service: (
        SyntheticVoiceGenerationService
    ),
    asset_service: (
        SyntheticReadyAssetService
    ),
    timeline_service: (
        SyntheticTimelineService
    ),
    render_service: (
        SyntheticRenderService
    ),
) -> list[
    VoicePipelineStage
    | AssetPipelineStage
    | TimelinePipelineStage
    | RenderPipelineStage
]:
    """Build the real adapter chain with synthetic dependencies."""

    return [
        VoicePipelineStage(
            blueprints=[
                build_blueprint(1),
                build_blueprint(2),
            ],
            generation_service=(
                voice_service
            ),
            timeline_service=(
                VoiceTimelineService()
            ),
        ),
        AssetPipelineStage(
            asset_workflow_service=(
                asset_service
            ),
        ),
        TimelinePipelineStage(
            genre_id="horror",
            timeline_service=(
                timeline_service
            ),
        ),
        RenderPipelineStage(
            render_service=(
                render_service
            ),
        ),
    ]


def test_real_adapter_chain_succeeds() -> None:
    job = build_job()

    voice_service = (
        SyntheticVoiceGenerationService()
    )

    asset_service = (
        SyntheticReadyAssetService()
    )

    timeline_service = (
        SyntheticTimelineService()
    )

    render_service = (
        SyntheticRenderService()
    )

    service = (
        RenderOrchestratorService(
            stages=(
                build_success_stages(
                    voice_service=(
                        voice_service
                    ),
                    asset_service=(
                        asset_service
                    ),
                    timeline_service=(
                        timeline_service
                    ),
                    render_service=(
                        render_service
                    ),
                )
            ),
        )
    )

    result = service.execute(
        job,
        dry_run=True,
    )

    assert result.success is True

    assert (
        result.status
        == JobStatus.COMPLETED
    )

    assert (
        job.status
        == JobStatus.COMPLETED
    )

    assert (
        job.current_stage
        == WorkflowStage
        .READY_FOR_UPLOAD
    )

    assert (
        job.voice_status
        == VoiceStatus.READY
    )

    assert (
        job.voice_file
        == "outputs/audio/scene_001.wav"
    )

    assert (
        job.voice_provider
        == "synthetic-voice"
    )

    assert (
        job.audio_timeline
        is not None
    )

    assert (
        len(
            job.audio_timeline.tracks
        )
        == 2
    )

    assert (
        len(
            job.scene_asset_states
        )
        == 2
    )

    assert (
        job.video_timeline
        is not None
    )

    assert (
        job.render_result
        is not None
    )

    assert (
        job.render_result.success
        is True
    )

    assert (
        job.render_result.output_file
        == (
            "outputs/"
            "integration_final.mp4"
        )
    )


def test_real_adapter_execution_order() -> None:
    job = build_job()

    voice_service = (
        SyntheticVoiceGenerationService()
    )

    asset_service = (
        SyntheticReadyAssetService()
    )

    timeline_service = (
        SyntheticTimelineService()
    )

    render_service = (
        SyntheticRenderService()
    )

    service = (
        RenderOrchestratorService(
            stages=(
                build_success_stages(
                    voice_service=(
                        voice_service
                    ),
                    asset_service=(
                        asset_service
                    ),
                    timeline_service=(
                        timeline_service
                    ),
                    render_service=(
                        render_service
                    ),
                )
            ),
        )
    )

    result = service.execute(
        job
    )

    assert result.success is True

    assert (
        voice_service
        .generated_scene_numbers
        == [
            1,
            2,
        ]
    )

    assert (
        asset_service
        .started_scene_numbers
        == [
            1,
            2,
        ]
    )

    assert (
        timeline_service.called
        is True
    )

    assert (
        render_service.called
        is True
    )


def test_real_adapter_completed_stage_mapping() -> None:
    job = build_job()

    service = (
        RenderOrchestratorService(
            stages=(
                build_success_stages(
                    voice_service=(
                        SyntheticVoiceGenerationService()
                    ),
                    asset_service=(
                        SyntheticReadyAssetService()
                    ),
                    timeline_service=(
                        SyntheticTimelineService()
                    ),
                    render_service=(
                        SyntheticRenderService()
                    ),
                )
            ),
        )
    )

    result = service.execute(
        job
    )

    assert result.success is True

    assert (
        result.completed_stages
        == [
            WorkflowStage.VOICE,
            (
                WorkflowStage
                .ASSET_GENERATION
            ),
            WorkflowStage.EDITING,
            WorkflowStage.RENDER,
        ]
    )

    assert (
        result.metadata[
            "pipeline_stage_count"
        ]
        == 4
    )

    assert (
        result.metadata[
            "pipeline_completed_stage_count"
        ]
        == 4
    )

    assert (
        result.metadata[
            "pipeline_progress_percent"
        ]
        == 100
    )


def test_waiting_asset_blocks_downstream_adapters() -> None:
    """
    Verify real adapter blocking semantics directly at PipelineRunner.

    RenderOrchestratorService result normalization is tested separately;
    this test is specifically about stage execution stopping at the
    interactive asset boundary.
    """

    job = build_job()

    voice_service = (
        SyntheticVoiceGenerationService()
    )

    asset_service = (
        SyntheticWaitingAssetService()
    )

    timeline_service = (
        SyntheticTimelineService()
    )

    render_service = (
        SyntheticRenderService()
    )

    runner = PipelineRunner()

    runner.register(
        VoicePipelineStage(
            blueprints=[
                build_blueprint(1),
                build_blueprint(2),
            ],
            generation_service=(
                voice_service
            ),
            timeline_service=(
                VoiceTimelineService()
            ),
        )
    )

    runner.register(
        AssetPipelineStage(
            asset_workflow_service=(
                asset_service
            ),
        )
    )

    runner.register(
        TimelinePipelineStage(
            genre_id="horror",
            timeline_service=(
                timeline_service
            ),
        )
    )

    runner.register(
        RenderPipelineStage(
            render_service=(
                render_service
            ),
        )
    )

    context = StageContext(
        job=job,
        pipeline_state=PipelineState(
            current_stage=(
                PipelineStageName.VOICE
            ),
        ),
        dry_run=True,
    )

    results = runner.run(
        context
    )

    assert (
        len(results)
        == 2
    )

    assert (
        results[0].stage
        == PipelineStageName.VOICE
    )

    assert (
        results[0].status
        == PipelineStageStatus.COMPLETED
    )

    assert (
        results[1].stage
        == (
            PipelineStageName
            .ASSET_SELECTION
        )
    )

    assert (
        results[1].status
        == (
            PipelineStageStatus
            .WAITING_FOR_USER
        )
    )

    assert (
        timeline_service.called
        is False
    )

    assert (
        render_service.called
        is False
    )

    assert (
        job.video_timeline
        is None
    )

    assert (
        job.render_result
        is None
    )

    assert (
        context
        .pipeline_state
        .overall_progress
        == 50
    )


def test_integration_preserves_pipeline_diagnostics() -> None:
    job = build_job()

    asset_service = (
        SyntheticWaitingAssetService()
    )

    runner = PipelineRunner()

    runner.register(
        VoicePipelineStage(
            blueprints=[
                build_blueprint(1),
                build_blueprint(2),
            ],
            generation_service=(
                SyntheticVoiceGenerationService()
            ),
            timeline_service=(
                VoiceTimelineService()
            ),
        )
    )

    runner.register(
        AssetPipelineStage(
            asset_workflow_service=(
                asset_service
            ),
        )
    )

    context = StageContext(
        job=job,
        pipeline_state=PipelineState(
            current_stage=(
                PipelineStageName.VOICE
            ),
        ),
        dry_run=True,
    )

    runner.run(
        context
    )

    assert (
        context.pipeline_state.warnings
        == [
            "Manual upload required.",
        ]
    )

    assert (
        context.pipeline_state.errors
        == []
    )


def main() -> None:
    print()
    print(
        "Running Pipeline Adapter "
        "Integration tests..."
    )
    print()

    test_real_adapter_chain_succeeds()
    test_real_adapter_execution_order()
    test_real_adapter_completed_stage_mapping()
    (
        test_waiting_asset_blocks_downstream_adapters()
    )
    (
        test_integration_preserves_pipeline_diagnostics()
    )

    print()
    print(
        "Pipeline Adapter Integration tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()