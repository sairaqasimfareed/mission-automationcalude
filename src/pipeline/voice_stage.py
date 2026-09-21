from __future__ import annotations

import time
from collections.abc import Callable

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
        transition_duration_seconds: float = 0.0,
        clip_duration_rounding_fn: Callable[[float], float] | None = None,
    ) -> None:
        if not blueprints:
            raise ValueError(
                "Voice pipeline stage requires at least "
                "one resolved voice blueprint."
            )

        if transition_duration_seconds < 0.0:
            raise ValueError(
                "Voice pipeline stage transition duration " "cannot be negative."
            )

        normalized_provider = (
            provider_name.strip() if provider_name is not None else None
        )

        self._blueprints = list(blueprints)

        self._generation_service = generation_service

        self._timeline_service = timeline_service

        self._provider_name = normalized_provider or None

        self._transition_duration_seconds = transition_duration_seconds

        # Real-world finding, 2026-09-20: real Google Flow clips only
        # come in a few fixed lengths (see
        # src.providers.google_flow.locators.clamp_to_verified_duration),
        # so the real video position of scene N+1 depends on scene N's
        # real narration duration ROUNDED to whatever length its clip
        # will actually request, not the raw narration length itself.
        # Injected rather than imported directly - this pipeline layer
        # has no existing dependency on src.providers, and shouldn't
        # gain one just for this. Defaults to identity (no rounding),
        # reproducing this class's own prior, unrounded behavior when
        # not wired by the caller (e.g. in tests).
        self._clip_duration_rounding_fn = clip_duration_rounding_fn or (
            lambda seconds: seconds
        )

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

        audio_timeline = context.job.audio_timeline or AudioTimeline()

        # Real-world finding, same root cause MusicPipelineStage was
        # already fixed for: a full pipeline re-run
        # (resume_previous_pipeline=True + skip_completed_stages=False,
        # a real, reachable AdvancedSettings combination - also hit
        # directly retrying a render after voice already generated)
        # re-executes this stage even though voice already completed.
        # This used to unconditionally regenerate every scene (real,
        # billed provider calls) and then hard-fail at attach_many()
        # on the tracks it had JUST regenerated, because they were
        # already present from the earlier successful run. "Already
        # handled" is exactly "every expected scene already has a
        # voiceover track" - unlike music, this does not silently
        # skip when generation would be genuinely needed (missing or
        # partial coverage still runs the real generation loop below,
        # and a real failure there still fails the stage).
        expected_scene_numbers = [
            blueprint.scene_number for blueprint in self._blueprints
        ]

        if not self._timeline_service.missing_voice_scenes(
            audio_timeline,
            expected_scene_numbers=expected_scene_numbers,
        ):
            return self._reused_result(
                started_at=started_at,
                context=context,
                audio_timeline=audio_timeline,
            )

        results: list[VoiceGenerationResult] = []

        warnings: list[str] = []

        scenes_by_number = {scene.scene_number: scene for scene in context.job.scenes}

        # Real-world finding, 2026-09-20: this used to be a single
        # dict precomputed up front by summing each scene's own
        # estimated_duration_seconds (see the now-removed
        # _scene_video_start_offsets), because - at the time - each
        # scene's real generated video clip was requested at, and
        # landed at, exactly that estimate. Now that video clip
        # duration follows voice's own real, measured result instead
        # (see ProjectRenderRuntimeFactory and
        # SceneVideoGenerationService), that premise is inverted: a
        # scene's real video position can only be known after every
        # PRECEDING scene's own real, clamp-rounded duration is known.
        # Scenes already generate in scene_number order below, so this
        # is fully reconstructible incrementally, one running total
        # (running_video_position) updated after each scene's own real
        # result - see the update after the audio_track checks below.
        # Still subtracts one transition's worth of overlap per
        # boundary, same reasoning as the real-world finding this
        # replaces documented.
        running_video_position = 0.0

        # Real-world finding, 2026-09-17: positioning scene N+1's voice
        # at its own crossfade-corrected start (see the running
        # running_video_position update below) without ALSO shrinking
        # scene N's own usable duration by the same
        # transition_duration_seconds lets scene N's real narration
        # run into scene N+1's already-started track - confirmed on a
        # real 18-scene render: 13 of 17 scene boundaries had 0.36-0.6s
        # where two different lines of narration played simultaneously
        # at full volume (voice tracks are never ducked against each
        # other, only music/SFX are ducked against voice). Only
        # relevant when a real scene-slot ceiling IS set (Phase 2 or a
        # caller that still passes one) - available_scene_duration_seconds
        # is None by default now, so this block is a no-op for the
        # default flow, left in place rather than deleted.
        if self._transition_duration_seconds > 0.0:
            for blueprint in self._blueprints:
                if blueprint.available_scene_duration_seconds is not None:
                    blueprint.available_scene_duration_seconds = max(
                        0.1,
                        blueprint.available_scene_duration_seconds
                        - self._transition_duration_seconds,
                    )

        for blueprint in sorted(
            self._blueprints,
            key=lambda value: (value.scene_number),
        ):
            scene_start_seconds = max(0.0, running_video_position)

            result = self._generation_service.generate(
                blueprint,
                start_time_seconds=scene_start_seconds,
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

            # This scene's real, measured duration - what
            # SceneVideoGenerationService will size its real Google
            # Flow clip request from, instead of the pre-generation
            # word-count guess (see Scene.real_narration_duration_seconds's
            # own docstring). Mutated in place on the job's own Scene
            # object, same pattern as blueprint.narration_text
            # elsewhere in this pipeline.
            scene = scenes_by_number.get(blueprint.scene_number)

            if scene is not None:
                scene.real_narration_duration_seconds = (
                    result.audio_track.duration_seconds
                )

            # The next scene's real video position depends on THIS
            # scene's own real duration rounded to whatever clip
            # length will actually be requested for it (identity when
            # no rounding function was wired - see __init__).
            rounded_clip_seconds = self._clip_duration_rounding_fn(
                result.audio_track.duration_seconds
            )

            running_video_position = (
                scene_start_seconds
                + rounded_clip_seconds
                - self._transition_duration_seconds
            )

        # replace=True: this branch only runs when coverage is missing
        # or partial (full coverage already returned above), so some
        # of the scenes being regenerated here may still have a stale
        # track attached from an earlier, incomplete run - replacing
        # it is correct (these results are the freshly regenerated,
        # authoritative ones), hard-failing on it is not. Harmless
        # no-op for the common case of a genuinely empty timeline.
        self._timeline_service.attach_many(
            audio_timeline,
            results=results,
            replace=True,
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

    def _reused_result(
        self,
        *,
        started_at: float,
        context: StageContext,
        audio_timeline: AudioTimeline,
    ) -> StageResult:
        """
        Build the COMPLETED result for reusing already-attached voice
        tracks instead of regenerating them.

        Mirrors VoicePipelineStage's normal success path's job-state
        updates (voice_file, voice_provider, voice_status) from the
        existing tracks rather than fresh generation results, since
        none were generated this run.
        """

        ordered_scene_numbers = sorted(
            blueprint.scene_number for blueprint in self._blueprints
        )

        existing_tracks = [
            self._timeline_service.get_scene_voice(
                audio_timeline,
                scene_number=scene_number,
            )
            for scene_number in ordered_scene_numbers
        ]

        providers = sorted(
            {track.provider for track in existing_tracks if track.provider is not None}
        )

        context.job.audio_timeline = audio_timeline

        context.job.voice_file = existing_tracks[0].source_file

        context.job.voice_provider = providers[0] if len(providers) == 1 else None

        context.job.voice_status = VoiceStatus.READY

        return StageResult(
            stage=self.stage_name,
            status=(PipelineStageStatus.COMPLETED),
            duration_seconds=(time.perf_counter() - started_at),
            progress_percent=100,
            warnings=[],
            errors=[],
            metadata={
                "result_count": 0,
                "successful_count": 0,
                "failed_count": 0,
                "providers": providers,
                "timeline_attached": True,
                "reused_existing": True,
                "timeline_duration_seconds": (audio_timeline.calculate_duration()),
                "voice_file": (existing_tracks[0].source_file),
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
