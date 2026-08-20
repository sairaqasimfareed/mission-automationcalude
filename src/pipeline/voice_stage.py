from __future__ import annotations

import time

from src.models.audio_timeline import AudioTimeline
from src.models.media_strategy import (
    VoiceStatus,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.models.voice_generation import (
    VoiceGenerationResult,
)
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.voice_generation_service import (
    VoiceGenerationService,
)
from src.services.voice_timeline_service import (
    VoiceTimelineService,
)


class VoicePipelineStage(BasePipelineStage):
    """
    Pipeline adapter for provider-independent voice generation.

    ResolvedVoiceBlueprint instances are injected explicitly because
    voice directive resolution is owned by the existing voice
    resolution services and must not be duplicated here.

    Responsibilities:
    - verify scene/blueprint coverage;
    - generate one voice result per scene;
    - stop on failed voice generation;
    - attach successful tracks through VoiceTimelineService;
    - update VideoJob's public voice state;
    - return a generic StageResult.

    Provider selection and provider execution remain owned by
    VoiceGenerationService.
    """

    def __init__(
        self,
        *,
        blueprints: list[ResolvedVoiceBlueprint],
        generation_service: VoiceGenerationService,
        timeline_service: VoiceTimelineService,
        provider_name: str | None = None,
    ) -> None:
        if not blueprints:
            raise ValueError(
                "Voice pipeline stage requires at least "
                "one resolved voice blueprint."
            )

        normalized_provider = (
            provider_name.strip() if provider_name is not None else None
        )

        self._blueprints = list(blueprints)

        self._generation_service = generation_service

        self._timeline_service = timeline_service

        self._provider_name = normalized_provider or None

        self._validate_blueprints(self._blueprints)

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        """Return the pipeline identifier."""

        return PipelineStageName.VOICE

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        """
        Generate and attach narration for all planned scenes.

        Unexpected service exceptions intentionally propagate so the
        outer RenderOrchestratorService can normalize them.
        """

        started_at = time.perf_counter()

        if not context.job.scenes:
            return self._failed_result(
                started_at=started_at,
                error_message=("Voice stage requires " "planned scenes."),
            )

        coverage_error = self._validate_scene_coverage(
            context=context,
        )

        if coverage_error is not None:
            return self._failed_result(
                started_at=started_at,
                error_message=(coverage_error),
            )

        results: list[VoiceGenerationResult] = []

        warnings: list[str] = []

        start_time_seconds = 0.0

        for blueprint in sorted(
            self._blueprints,
            key=lambda value: (value.scene_number),
        ):
            result = self._generation_service.generate(
                blueprint,
                start_time_seconds=(start_time_seconds),
                provider_name=(self._provider_name),
            )

            results.append(result)

            self._extend_unique(
                warnings,
                result.warnings,
            )

            if not result.success:
                message = (
                    result.failure.message
                    if result.failure is not None
                    else ("Voice generation failed " "without failure details.")
                )

                context.job.voice_status = VoiceStatus.FAILED

                context.job.voice_file = None

                return StageResult(
                    stage=self.stage_name,
                    status=(PipelineStageStatus.FAILED),
                    duration_seconds=(time.perf_counter() - started_at),
                    progress_percent=100,
                    warnings=warnings,
                    errors=[
                        message,
                    ],
                    metadata=(
                        self._build_metadata(
                            results=results,
                            attached=False,
                        )
                    ),
                )

            if result.audio_track is None:
                context.job.voice_status = VoiceStatus.FAILED

                context.job.voice_file = None

                return StageResult(
                    stage=self.stage_name,
                    status=(PipelineStageStatus.FAILED),
                    duration_seconds=(time.perf_counter() - started_at),
                    progress_percent=100,
                    warnings=warnings,
                    errors=[
                        ("Successful voice generation " "result has no audio track."),
                    ],
                    metadata=(
                        self._build_metadata(
                            results=results,
                            attached=False,
                        )
                    ),
                )

            start_time_seconds = (
                result.audio_track.start_time_seconds
                + result.audio_track.duration_seconds
            )

        audio_timeline = context.job.audio_timeline or AudioTimeline()

        self._timeline_service.attach_many(
            audio_timeline,
            results=results,
            replace=False,
        )

        context.job.audio_timeline = audio_timeline

        last_result = results[-1]

        first_result = results[0]

        context.job.voice_file = first_result.output_file

        context.job.voice_provider = self._single_provider(results)

        context.job.voice_status = VoiceStatus.READY

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.COMPLETED),
            duration_seconds=(time.perf_counter() - started_at),
            progress_percent=100,
            warnings=warnings,
            errors=[],
            metadata={
                **self._build_metadata(
                    results=results,
                    attached=True,
                ),
                "timeline_duration_seconds": (audio_timeline.calculate_duration()),
                "voice_file": (first_result.output_file),
                "last_output_file": (last_result.output_file),
            },
        )

    @staticmethod
    def _validate_blueprints(
        blueprints: list[ResolvedVoiceBlueprint],
    ) -> None:
        """Reject duplicate scene mappings."""

        scene_numbers = [blueprint.scene_number for blueprint in blueprints]

        if len(scene_numbers) != len(set(scene_numbers)):
            raise ValueError(
                "Voice pipeline stage cannot " "contain duplicate scene blueprints."
            )

    def _validate_scene_coverage(
        self,
        *,
        context: StageContext,
    ) -> str | None:
        """
        Ensure the supplied blueprints map exactly to the planned scenes.
        """

        expected = {scene.scene_number for scene in (context.job.scenes)}

        supplied = {blueprint.scene_number for blueprint in (self._blueprints)}

        missing = sorted(expected - supplied)

        unexpected = sorted(supplied - expected)

        if missing:
            return (
                "Voice stage is missing resolved "
                "blueprints for scene(s): "
                + ", ".join(str(value) for value in missing)
                + "."
            )

        if unexpected:
            return (
                "Voice stage received blueprints "
                "for unknown scene(s): "
                + ", ".join(str(value) for value in unexpected)
                + "."
            )

        return None

    @staticmethod
    def _single_provider(
        results: list[VoiceGenerationResult],
    ) -> str | None:
        """
        Return the provider when all results used the same provider.

        Mixed-provider generation remains valid; VideoJob's single
        voice_provider field is left unset in that case.
        """

        providers = {
            result.provider for result in results if result.provider is not None
        }

        if len(providers) != 1:
            return None

        return next(iter(providers))

    @staticmethod
    def _build_metadata(
        *,
        results: list[VoiceGenerationResult],
        attached: bool,
    ) -> dict[str, object]:
        """Build deterministic voice-stage metadata."""

        successful_count = sum(1 for result in results if result.success)

        failed_count = len(results) - successful_count

        providers = sorted(
            {result.provider for result in results if result.provider is not None}
        )

        return {
            "result_count": len(results),
            "successful_count": (successful_count),
            "failed_count": (failed_count),
            "providers": (providers),
            "timeline_attached": (attached),
        }

    @staticmethod
    def _extend_unique(
        target: list[str],
        values: list[str],
    ) -> None:
        """Append normalized unique diagnostics."""

        for value in values:
            cleaned = value.strip()

            if cleaned and cleaned not in target:
                target.append(cleaned)

    def _failed_result(
        self,
        *,
        started_at: float,
        error_message: str,
    ) -> StageResult:
        """Create a normalized voice-stage precondition failure."""

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.FAILED),
            duration_seconds=(time.perf_counter() - started_at),
            progress_percent=100,
            errors=[
                error_message,
            ],
            metadata={
                "result_count": 0,
                "successful_count": 0,
                "failed_count": 0,
                "providers": [],
                "timeline_attached": False,
            },
        )
