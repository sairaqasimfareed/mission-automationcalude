from __future__ import annotations

from dataclasses import dataclass

from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.enums import (
    JobStatus,
    WorkflowStage,
)
from src.models.media_strategy import (
    VoiceStatus,
)
from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.models.scene import Scene
from src.models.script import (
    Script,
    ScriptStatus,
)
from src.models.video_job import VideoJob
from src.models.voice_generation import (
    VoiceGenerationFailure,
    VoiceGenerationFailureReason,
    VoiceGenerationResult,
    VoiceGenerationStatus,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext
from src.pipeline.voice_stage import (
    VoicePipelineStage,
)
from src.services.voice_generation_service import (
    VoiceGenerationService,
)
from src.services.voice_timeline_service import (
    VoiceTimelineService,
)


@dataclass(frozen=True)
class SyntheticVoiceSpecification:
    """Synthetic generation behavior for one scene."""

    duration_seconds: float = 5.0

    provider: str = "synthetic-voice"

    warning: str | None = None

    failure_message: str | None = None


class SyntheticVoiceGenerationService(VoiceGenerationService):
    """
    Deterministic voice service used to isolate VoicePipelineStage.

    Production provider dependencies are intentionally bypassed because
    this suite tests pipeline-adapter behavior rather than provider
    execution.
    """

    def __init__(
        self,
        *,
        specifications: dict[
            int,
            SyntheticVoiceSpecification,
        ],
        raise_error: Exception | None = None,
    ) -> None:
        self._specifications = dict(specifications)

        self._raise_error = raise_error

        self.generated_scene_numbers: list[int] = []

        self.received_start_times: list[float] = []

        self.received_provider_names: list[str | None] = []

    def generate(
        self,
        blueprint: ResolvedVoiceBlueprint,
        *,
        start_time_seconds: float = 0.0,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        self.generated_scene_numbers.append(blueprint.scene_number)

        self.received_start_times.append(start_time_seconds)

        self.received_provider_names.append(provider_name)

        if self._raise_error is not None:
            raise self._raise_error

        specification = self._specifications[blueprint.scene_number]

        if specification.failure_message is not None:
            return VoiceGenerationResult(
                success=False,
                scene_number=(blueprint.scene_number),
                status=(VoiceGenerationStatus.FAILED),
                provider=(specification.provider),
                attempts=1,
                failure=(
                    VoiceGenerationFailure(
                        reason=(VoiceGenerationFailureReason.PROVIDER_ERROR),
                        message=(specification.failure_message),
                        provider=(specification.provider),
                        recoverable=True,
                    )
                ),
                warnings=(
                    [specification.warning]
                    if (specification.warning is not None)
                    else []
                ),
            )

        output_file = "outputs/audio/" f"scene_{blueprint.scene_number:03d}.wav"

        track = AudioTrack(
            track_type=(AudioTrackType.VOICEOVER),
            source_file=output_file,
            start_time_seconds=(start_time_seconds),
            duration_seconds=(specification.duration_seconds),
            provider=(specification.provider),
            status=(AudioTrackStatus.READY),
            metadata={
                "scene_number": (blueprint.scene_number),
            },
        )

        return VoiceGenerationResult(
            success=True,
            scene_number=(blueprint.scene_number),
            status=(VoiceGenerationStatus.COMPLETED),
            provider=(specification.provider),
            output_file=output_file,
            audio_track=track,
            attempts=1,
            warnings=(
                [specification.warning] if (specification.warning is not None) else []
            ),
        )


class RaisingVoiceTimelineService(VoiceTimelineService):
    """Timeline service used to verify exception propagation."""

    def attach_many(
        self,
        timeline: object,
        *,
        results: list[VoiceGenerationResult],
        replace: bool = False,
    ) -> list[AudioTrack]:
        del timeline
        del results
        del replace

        raise RuntimeError("Synthetic voice timeline exception.")


def build_research() -> ResearchResult:
    """Build approved research required by VideoJob."""

    return ResearchResult.model_construct(
        status=ResearchStatus.APPROVED,
    )


def build_script() -> Script:
    """Build an approved script required before scenes."""

    return Script(
        title="Voice stage test script",
        content=("Synthetic narration content " "for voice-stage testing."),
        prompt_version="test-1.0",
        word_count=7,
        estimated_duration_seconds=10,
        status=ScriptStatus.APPROVED,
    )


def build_scene(
    scene_number: int,
) -> Scene:
    """Build one valid synthetic scene."""

    return Scene(
        scene_number=scene_number,
        title=(f"Voice Scene {scene_number}"),
        narration=(f"Synthetic narration for " f"scene {scene_number}."),
        visual_prompt=("Synthetic visual for " "voice-stage testing."),
        estimated_duration_seconds=5,
    )


def build_job(
    *,
    include_scenes: bool = True,
) -> VideoJob:
    """Build a domain-valid VideoJob for voice-stage tests."""

    job = VideoJob(
        project_name="Voice Stage Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Voice pipeline adapter",
        status=JobStatus.RUNNING,
        current_stage=WorkflowStage.VOICE,
        research=build_research(),
        script=build_script(),
    )

    if include_scenes:
        # Reversed intentionally so generation ordering can be tested.
        job.scenes = [
            build_scene(2),
            build_scene(1),
        ]

    return job


def build_context(
    job: VideoJob,
) -> StageContext:
    """Build pipeline context for voice-stage execution."""

    return StageContext(
        job=job,
        pipeline_state=PipelineState(
            current_stage=(PipelineStageName.VOICE),
        ),
        dry_run=True,
    )


def build_blueprint(
    scene_number: int,
) -> ResolvedVoiceBlueprint:
    """
    Build the minimum resolved blueprint needed by the adapter tests.

    model_construct is intentional because blueprint validation and
    directive resolution have their own dedicated test suites.
    """

    return ResolvedVoiceBlueprint.model_construct(
        scene_number=scene_number,
    )


def build_blueprints() -> list[ResolvedVoiceBlueprint]:
    """Build deliberately reversed blueprint ordering."""

    return [
        build_blueprint(2),
        build_blueprint(1),
    ]


def build_success_service(
    *,
    provider_one: str = "synthetic-voice",
    provider_two: str = "synthetic-voice",
    warning_one: str | None = None,
    warning_two: str | None = None,
) -> SyntheticVoiceGenerationService:
    """Build successful deterministic generation for two scenes."""

    return SyntheticVoiceGenerationService(
        specifications={
            1: (
                SyntheticVoiceSpecification(
                    duration_seconds=4.0,
                    provider=provider_one,
                    warning=warning_one,
                )
            ),
            2: (
                SyntheticVoiceSpecification(
                    duration_seconds=6.0,
                    provider=provider_two,
                    warning=warning_two,
                )
            ),
        },
    )


def test_requires_blueprints() -> None:
    service = SyntheticVoiceGenerationService(
        specifications={},
    )

    try:
        VoicePipelineStage(
            blueprints=[],
            generation_service=service,
            timeline_service=(VoiceTimelineService()),
        )
    except ValueError as error:
        assert "at least one resolved voice blueprint" in str(error)
    else:
        raise AssertionError("Empty blueprint collection " "must fail.")


def test_duplicate_blueprints_rejected() -> None:
    service = SyntheticVoiceGenerationService(
        specifications={
            1: (SyntheticVoiceSpecification()),
        },
    )

    try:
        VoicePipelineStage(
            blueprints=[
                build_blueprint(1),
                build_blueprint(1),
            ],
            generation_service=service,
            timeline_service=(VoiceTimelineService()),
        )
    except ValueError as error:
        assert "duplicate scene blueprints" in str(error)
    else:
        raise AssertionError("Duplicate voice blueprints " "must fail.")


def test_stage_name() -> None:
    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=(build_success_service()),
        timeline_service=(VoiceTimelineService()),
    )

    assert stage.stage_name == PipelineStageName.VOICE


def test_missing_scenes_fails() -> None:
    job = build_job(
        include_scenes=False,
    )

    stage = VoicePipelineStage(
        blueprints=[
            build_blueprint(1),
        ],
        generation_service=(
            SyntheticVoiceGenerationService(
                specifications={
                    1: (SyntheticVoiceSpecification()),
                },
            )
        ),
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.FAILED

    assert result.errors == [
        "Voice stage requires planned scenes.",
    ]

    assert result.metadata["result_count"] == 0


def test_missing_blueprint_coverage_fails() -> None:
    job = build_job()

    service = SyntheticVoiceGenerationService(
        specifications={
            1: (SyntheticVoiceSpecification()),
        },
    )

    stage = VoicePipelineStage(
        blueprints=[
            build_blueprint(1),
        ],
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.FAILED

    assert result.errors == [
        ("Voice stage is missing resolved " "blueprints for scene(s): 2."),
    ]

    assert service.generated_scene_numbers == []


def test_unknown_blueprint_scene_fails() -> None:
    job = build_job()

    service = SyntheticVoiceGenerationService(specifications={})

    stage = VoicePipelineStage(
        blueprints=[
            build_blueprint(1),
            build_blueprint(2),
            build_blueprint(3),
        ],
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.FAILED

    assert result.errors == [
        ("Voice stage received blueprints " "for unknown scene(s): 3."),
    ]

    assert service.generated_scene_numbers == []


def test_successful_voice_generation() -> None:
    job = build_job()

    service = build_success_service()

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.COMPLETED

    assert result.successful is True

    assert result.errors == []

    assert job.voice_status == VoiceStatus.READY

    assert job.voice_file == "outputs/audio/scene_001.wav"

    assert job.voice_provider == "synthetic-voice"

    assert job.audio_timeline is not None

    assert len(job.audio_timeline.tracks) == 2

    assert result.metadata["result_count"] == 2

    assert result.metadata["successful_count"] == 2

    assert result.metadata["failed_count"] == 0

    assert result.metadata["timeline_attached"] is True


def test_generation_order_is_deterministic() -> None:
    job = build_job()

    service = build_success_service()

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.COMPLETED

    assert service.generated_scene_numbers == [
        1,
        2,
    ]


def test_scene_start_times_are_sequential() -> None:
    job = build_job()

    service = build_success_service()

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.COMPLETED

    assert service.received_start_times == [
        0.0,
        4.0,
    ]

    assert job.audio_timeline is not None

    assert job.audio_timeline.calculate_duration() == 10.0


def test_provider_override_is_normalized_and_forwarded() -> None:
    job = build_job()

    service = build_success_service()

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
        provider_name=("  synthetic-voice  "),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.COMPLETED

    assert service.received_provider_names == [
        "synthetic-voice",
        "synthetic-voice",
    ]


def test_empty_provider_override_becomes_none() -> None:
    job = build_job()

    service = build_success_service()

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
        provider_name="   ",
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.COMPLETED

    assert service.received_provider_names == [
        None,
        None,
    ]


def test_warnings_are_aggregated_and_deduplicated() -> None:
    job = build_job()

    service = build_success_service(
        warning_one=("Shared voice warning."),
        warning_two=("Shared voice warning."),
    )

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.COMPLETED

    assert result.warnings == [
        "Shared voice warning.",
    ]


def test_failed_generation_stops_pipeline() -> None:
    job = build_job()

    service = SyntheticVoiceGenerationService(
        specifications={
            1: (
                SyntheticVoiceSpecification(
                    provider=("synthetic-voice"),
                    failure_message=("Synthetic voice failure."),
                )
            ),
            2: (
                SyntheticVoiceSpecification(
                    provider=("synthetic-voice"),
                )
            ),
        },
    )

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.FAILED

    assert result.successful is False

    assert result.errors == [
        "Synthetic voice failure.",
    ]

    assert service.generated_scene_numbers == [
        1,
    ]

    assert job.voice_status == VoiceStatus.FAILED

    assert job.voice_file is None

    assert job.audio_timeline is None

    assert result.metadata["result_count"] == 1

    assert result.metadata["failed_count"] == 1

    assert result.metadata["timeline_attached"] is False


def test_mixed_providers_do_not_claim_single_provider() -> None:
    job = build_job()

    service = build_success_service(
        provider_one="provider-a",
        provider_two="provider-b",
    )

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.COMPLETED

    assert job.voice_provider is None

    assert result.metadata["providers"] == [
        "provider-a",
        "provider-b",
    ]


def test_single_provider_is_recorded() -> None:
    job = build_job()

    service = build_success_service(
        provider_one="provider-a",
        provider_two="provider-a",
    )

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    result = stage.execute(build_context(job))

    assert result.status == PipelineStageStatus.COMPLETED

    assert job.voice_provider == "provider-a"


def test_generation_service_exception_propagates() -> None:
    job = build_job()

    service = SyntheticVoiceGenerationService(
        specifications={
            1: (SyntheticVoiceSpecification()),
            2: (SyntheticVoiceSpecification()),
        },
        raise_error=RuntimeError("Synthetic generation exception."),
    )

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(VoiceTimelineService()),
    )

    try:
        stage.execute(build_context(job))
    except RuntimeError as error:
        assert str(error) == ("Synthetic generation " "exception.")
    else:
        raise AssertionError(
            "Unexpected voice-generation " "exceptions must propagate."
        )


def test_timeline_service_exception_propagates() -> None:
    job = build_job()

    service = build_success_service()

    stage = VoicePipelineStage(
        blueprints=build_blueprints(),
        generation_service=service,
        timeline_service=(RaisingVoiceTimelineService()),
    )

    try:
        stage.execute(build_context(job))
    except RuntimeError as error:
        assert str(error) == ("Synthetic voice timeline " "exception.")
    else:
        raise AssertionError("Unexpected voice-timeline " "exceptions must propagate.")


def main() -> None:
    print()
    print("Running Voice Pipeline Stage tests...")
    print()

    test_requires_blueprints()
    test_duplicate_blueprints_rejected()
    test_stage_name()
    test_missing_scenes_fails()
    test_missing_blueprint_coverage_fails()
    test_unknown_blueprint_scene_fails()
    test_successful_voice_generation()
    test_generation_order_is_deterministic()
    test_scene_start_times_are_sequential()
    test_provider_override_is_normalized_and_forwarded()
    test_empty_provider_override_becomes_none()
    test_warnings_are_aggregated_and_deduplicated()
    test_failed_generation_stops_pipeline()
    test_mixed_providers_do_not_claim_single_provider()
    test_single_provider_is_recorded()
    test_generation_service_exception_propagates()
    test_timeline_service_exception_propagates()

    print()
    print("Voice Pipeline Stage tests " "completed successfully.")


if __name__ == "__main__":
    main()
