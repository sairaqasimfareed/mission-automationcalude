from __future__ import annotations

from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.enums import (
    JobStatus,
    WorkflowStage,
)
from src.models.genre_timeline_pipeline import (
    GenreTimelinePipelineResult,
    GenreTimelinePipelineStatus,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.research import (
    ResearchResult,
    ResearchStatus,
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
    TimelineValidationCode,
    TimelineValidationIssue,
    TimelineValidationResult,
    TimelineValidationSeverity,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext
from src.pipeline.timeline_stage import (
    TimelinePipelineStage,
)
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)


class SyntheticTimelineService(
    GenreTimelinePipelineService
):
    """
    Deterministic timeline service used to isolate the pipeline adapter.

    The production constructor is intentionally bypassed because these
    tests verify TimelinePipelineStage rather than directive-generation
    or directive-resolution services.
    """

    def __init__(
        self,
        *,
        result: GenreTimelinePipelineResult,
        raise_error: Exception | None = None,
    ) -> None:
        self._result = result
        self._raise_error = raise_error

        self.received_scenes: list[Scene] = []
        self.received_clips: list[VideoClip] = []
        self.received_genre_id: str | None = None

        self.received_overrides: (
            dict[int, SceneEditingDirectives]
            | None
        ) = None

        self.received_output_resolution: (
            str | None
        ) = None

        self.received_frame_rate: (
            int | None
        ) = None

        self.received_warn_on_fallbacks: (
            bool | None
        ) = None

    def build(
        self,
        *,
        scenes: list[Scene],
        clips: list[VideoClip],
        genre_id: str,
        overrides_by_scene: (
            dict[int, SceneEditingDirectives]
            | None
        ) = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
    ) -> GenreTimelinePipelineResult:
        self.received_scenes = list(
            scenes
        )

        self.received_clips = list(
            clips
        )

        self.received_genre_id = (
            genre_id
        )

        self.received_overrides = dict(
            overrides_by_scene
            or {}
        )

        self.received_output_resolution = (
            output_resolution
        )

        self.received_frame_rate = (
            frame_rate
        )

        self.received_warn_on_fallbacks = (
            warn_on_blueprint_fallbacks
        )

        if self._raise_error is not None:
            raise self._raise_error

        return self._result


def build_job(
    *,
    include_scenes: bool = True,
    include_clips: bool = True,
) -> VideoJob:
    """Build a domain-valid VideoJob for timeline-stage tests."""

    job = VideoJob(
        project_name="Timeline Stage Test",
        channel_name="Mission Channel",
        niche="horror",
        topic="Timeline stage adapter",
        status=JobStatus.RUNNING,
        current_stage=(
            WorkflowStage.EDITING
        ),
    )

    research = (
        ResearchResult.model_construct(
            status=ResearchStatus.APPROVED,
        )
    )

    script = Script(
        title="Timeline stage test",
        content=(
            "Synthetic narration for "
            "timeline-stage testing."
        ),
        prompt_version="test-1.0",
        word_count=5,
        estimated_duration_seconds=10,
        status=ScriptStatus.APPROVED,
    )

    job.research = research
    job.script = script

    if include_scenes:
        scene = Scene(
            scene_number=1,
            title="Synthetic Scene",
            narration=(
                "Synthetic narration for "
                "timeline-stage testing."
            ),
            visual_prompt=(
                "Synthetic timeline visual."
            ),
            estimated_duration_seconds=10,
            manual_file_path=(
                "assets/videos/manual/"
                "timeline_test.mp4"
            ),
            source_status=(
                SceneSourceStatus.READY
            ),
            status=SceneStatus.READY,
        )

        job.scenes = [
            scene,
        ]

        if include_clips:
            clip = VideoClip(
                scene_number=1,
                source_type=(
                    SceneSourceType
                    .MANUAL_UPLOAD
                ),
                duration_seconds=10,
                prompt=(
                    "Synthetic timeline clip."
                ),
                provider="Manual Upload",
                local_file=(
                    "assets/videos/manual/"
                    "timeline_test.mp4"
                ),
                source_status=(
                    SceneSourceStatus.READY
                ),
                status=(
                    VideoClipStatus.READY
                ),
            )

            job.video_clips = [
                clip,
            ]

    return job


def build_context(
    job: VideoJob,
) -> StageContext:
    """Build StageContext for timeline adapter execution."""

    return StageContext(
        job=job,
        pipeline_state=PipelineState(
            current_stage=(
                PipelineStageName
                .VIDEO_TIMELINE
            ),
        ),
        dry_run=True,
    )


def build_timeline(
    job: VideoJob,
) -> VideoTimeline:
    """Build a basic synthetic timeline from the job clips."""

    timeline = VideoTimeline(
        clips=list(
            job.video_clips
        ),
        output_resolution=(
            "1920x1080"
        ),
        frame_rate=30,
    )

    timeline.calculate_duration()

    return timeline


def build_success_validation() -> TimelineValidationResult:
    """Build a synthetic render-ready validation report."""

    return (
        TimelineValidationResult
        .model_construct(
            is_valid=True,
            item_count=1,
            enabled_item_count=1,
            track_count=1,
            total_duration_seconds=10.0,
            gap_duration_seconds=0.0,
            overlap_duration_seconds=0.0,
            blueprint_count=1,
            render_ready_item_count=1,
            blueprint_fallback_count=0,
            errors=[],
            warnings=[],
        )
    )


def build_failed_validation() -> TimelineValidationResult:
    """Build a synthetic invalid validation report."""

    issue = TimelineValidationIssue(
        code=(
            TimelineValidationCode
            .CLIP_NOT_READY
        ),
        severity=(
            TimelineValidationSeverity
            .ERROR
        ),
        message=(
            "Synthetic timeline "
            "validation failure."
        ),
        scene_number=1,
    )

    return (
        TimelineValidationResult
        .model_construct(
            is_valid=False,
            item_count=1,
            enabled_item_count=1,
            track_count=1,
            total_duration_seconds=10.0,
            gap_duration_seconds=0.0,
            overlap_duration_seconds=0.0,
            blueprint_count=0,
            render_ready_item_count=0,
            blueprint_fallback_count=0,
            errors=[
                issue,
            ],
            warnings=[],
        )
    )


def build_success_result(
    job: VideoJob,
    *,
    warnings: list[str] | None = None,
) -> GenreTimelinePipelineResult:
    """Build a synthetic successful timeline-pipeline result."""

    validation = (
        build_success_validation()
    )

    return (
        GenreTimelinePipelineResult
        .model_construct(
            requested_genre_id="horror",
            status=(
                GenreTimelinePipelineStatus
                .COMPLETED
            ),
            timeline=(
                build_timeline(
                    job
                )
            ),
            directives=[],
            blueprints=[],
            validation=validation,
            warnings=(
                warnings
                or []
            ),
            metadata={
                "synthetic": True,
            },
        )
    )


def build_failed_result(
    job: VideoJob,
) -> GenreTimelinePipelineResult:
    """Build a synthetic failed timeline-pipeline result."""

    return (
        GenreTimelinePipelineResult
        .model_construct(
            requested_genre_id="horror",
            status=(
                GenreTimelinePipelineStatus
                .FAILED
            ),
            timeline=(
                build_timeline(
                    job
                )
            ),
            directives=[],
            blueprints=[],
            validation=(
                build_failed_validation()
            ),
            warnings=[
                "Synthetic timeline warning.",
            ],
            metadata={
                "synthetic": True,
            },
        )
    )


def test_stage_name() -> None:
    job = build_job()

    service = SyntheticTimelineService(
        result=(
            build_success_result(
                job
            )
        ),
    )

    stage = TimelinePipelineStage(
        genre_id="horror",
        timeline_service=service,
    )

    assert (
        stage.stage_name
        == PipelineStageName
        .VIDEO_TIMELINE
    )


def test_genre_id_is_normalized() -> None:
    job = build_job()

    service = SyntheticTimelineService(
        result=(
            build_success_result(
                job
            )
        ),
    )

    stage = TimelinePipelineStage(
        genre_id="  HORROR  ",
        timeline_service=service,
    )

    assert (
        stage.genre_id
        == "horror"
    )


def test_empty_genre_id_rejected() -> None:
    job = build_job()

    service = SyntheticTimelineService(
        result=(
            build_success_result(
                job
            )
        ),
    )

    try:
        TimelinePipelineStage(
            genre_id="   ",
            timeline_service=service,
        )
    except ValueError as error:
        assert (
            "requires a genre ID"
            in str(error)
        )
    else:
        raise AssertionError(
            "Empty genre ID must fail."
        )


def test_empty_resolution_rejected() -> None:
    job = build_job()

    service = SyntheticTimelineService(
        result=(
            build_success_result(
                job
            )
        ),
    )

    try:
        TimelinePipelineStage(
            genre_id="horror",
            timeline_service=service,
            output_resolution="   ",
        )
    except ValueError as error:
        assert (
            "requires an output resolution"
            in str(error)
        )
    else:
        raise AssertionError(
            "Empty output resolution "
            "must fail."
        )


def test_invalid_frame_rate_rejected() -> None:
    job = build_job()

    service = SyntheticTimelineService(
        result=(
            build_success_result(
                job
            )
        ),
    )

    try:
        TimelinePipelineStage(
            genre_id="horror",
            timeline_service=service,
            frame_rate=0,
        )
    except ValueError as error:
        assert (
            "frame rate must be positive"
            in str(error)
        )
    else:
        raise AssertionError(
            "Non-positive frame rate "
            "must fail."
        )


def test_missing_scenes_fails() -> None:
    job = build_job(
        include_scenes=False,
        include_clips=False,
    )

    service = SyntheticTimelineService(
        result=(
            GenreTimelinePipelineResult
            .model_construct()
        ),
    )

    stage = TimelinePipelineStage(
        genre_id="horror",
        timeline_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.errors == [
        "Timeline stage requires planned scenes.",
    ]

    assert (
        job.video_timeline
        is None
    )


def test_missing_clips_fails() -> None:
    job = build_job(
        include_scenes=True,
        include_clips=False,
    )

    service = SyntheticTimelineService(
        result=(
            GenreTimelinePipelineResult
            .model_construct()
        ),
    )

    stage = TimelinePipelineStage(
        genre_id="horror",
        timeline_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.errors == [
        "Timeline stage requires ready video clips.",
    ]

    assert (
        job.video_timeline
        is None
    )


def test_successful_timeline_execution() -> None:
    job = build_job()

    pipeline_result = (
        build_success_result(
            job
        )
    )

    service = SyntheticTimelineService(
        result=pipeline_result,
    )

    stage = TimelinePipelineStage(
        genre_id="  HORROR  ",
        timeline_service=service,
        output_resolution="1280x720",
        frame_rate=24,
        warn_on_blueprint_fallbacks=False,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert result.successful is True

    assert (
        job.video_timeline
        is pipeline_result.timeline
    )

    assert (
        service.received_genre_id
        == "horror"
    )

    assert (
        len(
            service.received_scenes
        )
        == 1
    )

    assert (
        len(
            service.received_clips
        )
        == 1
    )

    assert (
        service
        .received_output_resolution
        == "1280x720"
    )

    assert (
        service.received_frame_rate
        == 24
    )

    assert (
        service
        .received_warn_on_fallbacks
        is False
    )

    assert (
        result.metadata[
            "genre_id"
        ]
        == "horror"
    )

    assert (
        result.metadata[
            "render_ready"
        ]
        is True
    )

    assert (
        result.metadata[
            "timeline_duration_seconds"
        ]
        == 10.0
    )


def test_warnings_are_propagated() -> None:
    job = build_job()

    service = SyntheticTimelineService(
        result=(
            build_success_result(
                job,
                warnings=[
                    (
                        "Synthetic timeline "
                        "warning."
                    ),
                ],
            )
        ),
    )

    stage = TimelinePipelineStage(
        genre_id="horror",
        timeline_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert result.warnings == [
        "Synthetic timeline warning.",
    ]


def test_failed_validation_is_translated() -> None:
    job = build_job()

    service = SyntheticTimelineService(
        result=(
            build_failed_result(
                job
            )
        ),
    )

    stage = TimelinePipelineStage(
        genre_id="horror",
        timeline_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.successful is False

    assert result.errors == [
        (
            "Synthetic timeline "
            "validation failure."
        ),
    ]

    assert result.warnings == [
        "Synthetic timeline warning.",
    ]

    assert (
        job.video_timeline
        is None
    )

    assert (
        result.metadata[
            "render_ready"
        ]
        is False
    )


def test_non_render_ready_result_without_errors_uses_fallback_message() -> None:
    job = build_job()

    validation = (
        TimelineValidationResult
        .model_construct(
            is_valid=True,
            item_count=1,
            enabled_item_count=1,
            track_count=1,
            total_duration_seconds=10.0,
            gap_duration_seconds=0.0,
            overlap_duration_seconds=0.0,
            blueprint_count=0,
            render_ready_item_count=0,
            blueprint_fallback_count=0,
            errors=[],
            warnings=[],
        )
    )

    pipeline_result = (
        GenreTimelinePipelineResult
        .model_construct(
            requested_genre_id="horror",
            status=(
                GenreTimelinePipelineStatus
                .COMPLETED
            ),
            timeline=(
                build_timeline(
                    job
                )
            ),
            directives=[],
            blueprints=[],
            validation=validation,
            warnings=[],
            metadata={},
        )
    )

    service = SyntheticTimelineService(
        result=pipeline_result,
    )

    stage = TimelinePipelineStage(
        genre_id="horror",
        timeline_service=service,
    )

    result = stage.execute(
        build_context(
            job
        )
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.errors == [
        (
            "Genre timeline pipeline did not "
            "produce a render-ready timeline."
        ),
    ]

    assert (
        job.video_timeline
        is None
    )


def test_service_exception_propagates() -> None:
    job = build_job()

    service = SyntheticTimelineService(
        result=(
            build_success_result(
                job
            )
        ),
        raise_error=RuntimeError(
            "Synthetic timeline exception."
        ),
    )

    stage = TimelinePipelineStage(
        genre_id="horror",
        timeline_service=service,
    )

    try:
        stage.execute(
            build_context(
                job
            )
        )
    except RuntimeError as error:
        assert (
            str(error)
            == (
                "Synthetic timeline "
                "exception."
            )
        )
    else:
        raise AssertionError(
            "Unexpected timeline-service "
            "exceptions must propagate."
        )


def main() -> None:
    print()
    print(
        "Running Timeline Pipeline Stage tests..."
    )
    print()

    test_stage_name()
    test_genre_id_is_normalized()
    test_empty_genre_id_rejected()
    test_empty_resolution_rejected()
    test_invalid_frame_rate_rejected()
    test_missing_scenes_fails()
    test_missing_clips_fails()
    test_successful_timeline_execution()
    test_warnings_are_propagated()
    test_failed_validation_is_translated()
    (
        test_non_render_ready_result_without_errors_uses_fallback_message()
    )
    test_service_exception_propagates()

    print()
    print(
        "Timeline Pipeline Stage tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()