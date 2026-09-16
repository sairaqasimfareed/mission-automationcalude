from __future__ import annotations

from src.models.audio_generation_summary import (
    AudioComponentResult,
    AudioComponentStatus,
    AudioGenerationSummary,
)
from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.editing_directives import DirectiveTimingMode
from src.models.manual_audio_requirement import (
    ManualAudioRequirement,
    ManualAudioRequirementType,
)
from src.models.media_strategy import VoiceStatus
from src.models.resolved_editing_blueprint import ResolvedSoundEffectInstruction
from src.models.sound_design_plan import SoundDesignItemStatus
from src.models.video_job import VideoJob
from src.models.video_timeline_item import VideoTimelineItem
from src.models.voice_generation import VoiceGenerationResult
from src.pipeline.music_stage import (
    MAX_SINGLE_MUSIC_CLIP_REQUEST_SECONDS,
    MusicPipelineStage,
)
from src.pipeline.sound_effect_stage import SoundEffectPipelineStage
from src.services.budget.provider_budget_service import ProviderBudgetService
from src.services.genre_timeline_pipeline_service import GenreTimelinePipelineService
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.invalidation_service import InvalidationService
from src.services.music_generation_service import MusicGenerationService
from src.services.sound_effect_generation_service import SoundEffectGenerationService
from src.services.voice_generation_service import VoiceGenerationService
from src.services.voice_resolution_runtime import (
    VoiceResolutionRequest,
    VoiceResolutionRuntime,
)
from src.services.voice_timeline_service import VoiceTimelineService


class MediaGenerationPipeline:
    """
    Runs voice, timeline, music, and sound-effect generation as
    separate, explicitly triggered stages - the same convention
    ContentIntelligencePipeline follows - instead of only as internal
    steps of one atomic render call.

    Every stage here calls the exact same underlying services
    VoicePipelineStage/MusicPipelineStage/SoundEffectPipelineStage
    already call inside the render pipeline; this class only removes
    the StageContext/render-orchestrator wrapper so a GUI can trigger
    one stage at a time. Unlike those pipeline stages - where a failed
    music or sound-effect cue is only a warning, since a video without
    them is still deliverable - every stage here raises on failure,
    matching how every other standalone-triggered stage in this
    application surfaces errors to its GUI.

    Budget gating (opt-in): pass `budget_service` plus the relevant
    `*_profile_id` to gate a stage's provider call against
    ProviderBudgetService, the same way LLMService already gates every
    real LLM call. Voice/music/SFX providers have no native per-call
    cost estimate today (unlike LLM requests), so gating only actually
    engages when a caller supplies a real `estimated_cost_usd` on the
    call itself - it defaults to 0.0, which never blocks and never
    reserves, so existing callers are unaffected unless they opt in.
    """

    def __init__(
        self,
        *,
        voice_directive_generation_service: GenreVoiceDirectiveGenerationService,
        voice_resolution_runtime: VoiceResolutionRuntime,
        voice_generation_service: VoiceGenerationService,
        voice_timeline_service: VoiceTimelineService,
        genre_timeline_service: GenreTimelinePipelineService,
        music_generation_service: MusicGenerationService | None = None,
        sound_effect_generation_service: SoundEffectGenerationService | None = None,
        invalidation_service: InvalidationService | None = None,
        budget_service: ProviderBudgetService | None = None,
        voice_profile_id: str | None = None,
        music_profile_id: str | None = None,
        sound_effect_profile_id: str | None = None,
    ) -> None:
        self.voice_directive_generation_service = voice_directive_generation_service
        self.voice_resolution_runtime = voice_resolution_runtime
        self.voice_generation_service = voice_generation_service
        self.voice_timeline_service = voice_timeline_service
        self.genre_timeline_service = genre_timeline_service
        self.music_generation_service = music_generation_service
        self.sound_effect_generation_service = sound_effect_generation_service
        self.invalidation_service = invalidation_service or InvalidationService()
        self.budget_service = budget_service
        self.voice_profile_id = voice_profile_id
        self.music_profile_id = music_profile_id
        self.sound_effect_profile_id = sound_effect_profile_id

    def run_voice(self, job: VideoJob, *, estimated_cost_usd: float = 0.0) -> VideoJob:
        """Stage 1: generate narration for every planned scene."""

        if not job.scenes:
            raise RuntimeError("Voice generation requires planned scenes.")

        self._gate_budget(
            self.voice_profile_id, estimated_cost_usd, stage="Voice generation"
        )

        try:
            ordered_scenes = sorted(job.scenes, key=lambda scene: scene.scene_number)

            requests: list[VoiceResolutionRequest] = [
                (
                    self.voice_directive_generation_service.generate(
                        scene=scene,
                        genre_id=job.genre_id,
                        language=job.language,
                    ),
                    scene.narration,
                    float(scene.estimated_duration_seconds),
                )
                for scene in ordered_scenes
            ]

            blueprints = self.voice_resolution_runtime.resolve_many(requests)
            results = self.voice_generation_service.generate_many(blueprints)

            failed = next((result for result in results if not result.success), None)

            if failed is not None:
                job.voice_status = VoiceStatus.FAILED
                job.voice_file = None
                job.voice_script_version = None

                message = (
                    failed.failure.message
                    if failed.failure is not None
                    else "Voice generation failed without failure details."
                )

                raise RuntimeError(
                    f"Voice generation failed for scene {failed.scene_number}: {message}"
                )

            audio_timeline = job.audio_timeline or AudioTimeline()
            self.voice_timeline_service.attach_many(
                audio_timeline, results=results, replace=True
            )
            job.audio_timeline = audio_timeline

            job.voice_file = results[0].output_file
            job.voice_provider = self._single_provider(results)
            job.voice_status = VoiceStatus.READY
            job.voice_script_version = (
                job.script_version_history.current_version.version_number
                if job.script_version_history is not None
                else None
            )
        except Exception:
            self._release_budget(self.voice_profile_id, estimated_cost_usd)
            raise

        self.invalidation_service.clear_stale(job, "audio_timeline")
        self.invalidation_service.on_audio_regenerated(
            job, reason="Voice narration was regenerated."
        )

        return job

    def run_timeline(self, job: VideoJob) -> VideoJob:
        """Stage 2: build the genre-aware editing timeline."""

        if not job.scenes:
            raise RuntimeError("Timeline generation requires planned scenes.")

        if not job.video_clips:
            raise RuntimeError(
                "Timeline generation requires resolved video clips - "
                "see Clip Workspace."
            )

        result = self.genre_timeline_service.build(
            scenes=job.scenes,
            clips=job.video_clips,
            genre_id=job.genre_id,
        )
        job.video_timeline = result.timeline

        self.invalidation_service.clear_stale(job, "video_timeline")

        return job

    def run_music(self, job: VideoJob, *, estimated_cost_usd: float = 0.0) -> VideoJob:
        """Stage 3: generate one whole-video background-music track."""

        if self.music_generation_service is None:
            raise RuntimeError("No music provider is configured.")

        if job.video_timeline is None:
            raise RuntimeError(
                "Music generation requires a built video timeline - run "
                "Timeline first."
            )

        instruction_item = self._first_enabled_music_item(job.video_timeline.items)

        if instruction_item is None or instruction_item.editing_blueprint is None:
            raise RuntimeError(
                "This genre has no background music configured for any scene."
            )

        self._gate_budget(
            self.music_profile_id, estimated_cost_usd, stage="Music generation"
        )

        try:
            duration_seconds = job.video_timeline.calculate_duration()

            # Real-world finding: ElevenLabs's sound-generation endpoint
            # rejects a single request anywhere near a whole video's
            # length (confirmed live: HTTP 400, "expected to be...
            # less or equal to 30" for a 100s request) - the same gap
            # generate_single_music_segment() already closes below.
            # Request only a short clip and let AudioTrack.loop_enabled
            # (set from the resolved instruction's own "loop" flag)
            # repeat it to fill the real track_duration_seconds at
            # render time, instead of asking the provider for the
            # whole video's length in one call.
            requested_duration_seconds = min(
                duration_seconds,
                MAX_SINGLE_MUSIC_CLIP_REQUEST_SECONDS,
            )

            result = self.music_generation_service.generate(
                instruction_item.editing_blueprint.music,
                duration_seconds=requested_duration_seconds,
                track_duration_seconds=duration_seconds,
            )

            if not result.success or result.audio_track is None:
                message = (
                    result.failure.message
                    if result.failure is not None
                    else "Music generation failed without failure details."
                )

                raise RuntimeError(f"Music generation failed: {message}")

            audio_timeline = job.audio_timeline or AudioTimeline()
            audio_timeline.tracks = [
                track
                for track in audio_timeline.tracks
                if track.track_type != AudioTrackType.BACKGROUND_MUSIC
            ]
            audio_timeline.tracks.append(result.audio_track)
            job.audio_timeline = audio_timeline
        except Exception:
            self._release_budget(self.music_profile_id, estimated_cost_usd)
            raise

        self.invalidation_service.on_audio_regenerated(
            job, reason="Background music was regenerated."
        )

        return job

    def run_sound_effects(
        self, job: VideoJob, *, estimated_cost_usd: float = 0.0
    ) -> VideoJob:
        """Stage 4: generate every planned sound-effect cue."""

        if self.sound_effect_generation_service is None:
            raise RuntimeError("No sound-effect provider is configured.")

        if job.video_timeline is None:
            raise RuntimeError(
                "Sound-effect generation requires a built video timeline - "
                "run Timeline first."
            )

        self._gate_budget(
            self.sound_effect_profile_id,
            estimated_cost_usd,
            stage="Sound-effect generation",
        )

        try:
            new_tracks: list[AudioTrack] = []
            failures: list[str] = []

            for item in sorted(
                job.video_timeline.items, key=lambda value: value.scene_number
            ):
                if item.editing_blueprint is None:
                    continue

                for cue in item.editing_blueprint.sound_effects:
                    if not cue.enabled:
                        continue

                    start_time_seconds = self._resolve_start_time(item=item, cue=cue)

                    result = self.sound_effect_generation_service.generate(
                        cue,
                        scene_number=item.scene_number,
                        start_time_seconds=start_time_seconds,
                    )

                    if not result.success or result.audio_track is None:
                        message = (
                            result.failure.message
                            if result.failure is not None
                            else "unknown error"
                        )
                        failures.append(f"Scene {item.scene_number}: {message}")

                        continue

                    new_tracks.append(result.audio_track)

            attached_count = len(new_tracks)

            if attached_count == 0:
                # Nothing regenerated successfully - leave any existing
                # sound-effect tracks on job.audio_timeline untouched
                # rather than wiping known-good state on a failed attempt.
                if failures:
                    raise RuntimeError(
                        "No sound effects were generated: " + "; ".join(failures)
                    )

                raise RuntimeError(
                    "This genre has no sound effects configured for any scene."
                )

            audio_timeline = job.audio_timeline or AudioTimeline()
            audio_timeline.tracks = [
                track
                for track in audio_timeline.tracks
                if track.track_type != AudioTrackType.SOUND_EFFECT
            ] + new_tracks
            job.audio_timeline = audio_timeline
        except Exception:
            self._release_budget(self.sound_effect_profile_id, estimated_cost_usd)
            raise

        self.invalidation_service.on_audio_regenerated(
            job, reason="Sound effects were regenerated."
        )

        return job

    def generate_single_sfx_cue(
        self, job: VideoJob, cue_id: str, *, estimated_cost_usd: float = 0.0
    ) -> VideoJob:
        """
        Generate exactly one SoundEffectCueDirective from
        job.sound_design_plan, for a review-and-approve UI where an
        operator generates cues individually (optionally after editing
        a cue's prompt) rather than committing to every planned cue at
        once.
        """

        if self.sound_effect_generation_service is None:
            raise RuntimeError("No sound-effect provider is configured.")

        if job.sound_design_plan is None:
            raise RuntimeError("This job has no sound design plan.")

        if job.video_timeline is None:
            raise RuntimeError(
                "Sound-effect generation requires a built video timeline - "
                "run Timeline first."
            )

        cue = next(
            (c for c in job.sound_design_plan.sfx_cues if str(c.id) == cue_id),
            None,
        )

        if cue is None:
            raise RuntimeError(f"No sound-effect cue found with id '{cue_id}'.")

        items_by_scene = {item.scene_number: item for item in job.video_timeline.items}
        item = items_by_scene.get(cue.scene_number)

        if item is None:
            raise RuntimeError(
                f"Scene {cue.scene_number} has no matching timeline item."
            )

        self._gate_budget(
            self.sound_effect_profile_id,
            estimated_cost_usd,
            stage="Sound-effect generation",
        )

        try:
            instruction = SoundEffectPipelineStage._instruction_from_content_aware_cue(
                cue
            )
            start_time_seconds = self._resolve_start_time(item=item, cue=instruction)

            result = self.sound_effect_generation_service.generate(
                instruction,
                scene_number=item.scene_number,
                start_time_seconds=start_time_seconds,
            )

            if not result.success or result.audio_track is None:
                message = (
                    result.failure.message
                    if result.failure is not None
                    else "unknown error"
                )
                cue.status = SoundDesignItemStatus.FAILED

                raise RuntimeError(f"Sound-effect generation failed: {message}")

            audio_timeline = job.audio_timeline or AudioTimeline()
            audio_timeline.tracks = [
                track
                for track in audio_timeline.tracks
                if track.metadata.get("sound_design_cue_id") != cue_id
            ]
            audio_track = result.audio_track.model_copy(
                update={
                    "metadata": {
                        **result.audio_track.metadata,
                        "sound_design_cue_id": cue_id,
                    }
                }
            )
            audio_timeline.tracks.append(audio_track)
            job.audio_timeline = audio_timeline

            cue.status = SoundDesignItemStatus.GENERATED
            cue.audio_track_id = str(audio_track.id)
        except Exception:
            self._release_budget(self.sound_effect_profile_id, estimated_cost_usd)
            raise

        self.invalidation_service.on_audio_regenerated(
            job, reason=f"Sound-effect cue for scene {cue.scene_number} was generated."
        )

        return job

    def generate_single_music_segment(
        self, job: VideoJob, segment_id: str, *, estimated_cost_usd: float = 0.0
    ) -> VideoJob:
        """
        Generate exactly one MusicMoodSegment from
        job.sound_design_plan, for the same review-and-approve UI
        generate_single_sfx_cue serves.
        """

        if self.music_generation_service is None:
            raise RuntimeError("No music provider is configured.")

        if job.sound_design_plan is None:
            raise RuntimeError("This job has no sound design plan.")

        if job.video_timeline is None:
            raise RuntimeError(
                "Music generation requires a built video timeline - run "
                "Timeline first."
            )

        segment = next(
            (
                s
                for s in job.sound_design_plan.music_segments
                if str(s.id) == segment_id
            ),
            None,
        )

        if segment is None:
            raise RuntimeError(f"No music segment found with id '{segment_id}'.")

        items_by_scene = {item.scene_number: item for item in job.video_timeline.items}
        start_item = items_by_scene.get(segment.start_scene_number)
        end_item = items_by_scene.get(segment.end_scene_number)

        if start_item is None or end_item is None:
            raise RuntimeError(
                "Music segment "
                f"{segment.start_scene_number}-{segment.end_scene_number} has "
                "no matching timeline item(s)."
            )

        segment_span_seconds = end_item.end_time_seconds - start_item.start_time_seconds

        if segment_span_seconds <= 0:
            raise RuntimeError(
                "Music segment "
                f"{segment.start_scene_number}-{segment.end_scene_number} "
                "resolved to a non-positive duration."
            )

        self._gate_budget(
            self.music_profile_id, estimated_cost_usd, stage="Music generation"
        )

        try:
            instruction = MusicPipelineStage._instruction_from_mood_segment(segment)
            requested_duration_seconds = min(
                segment_span_seconds,
                MAX_SINGLE_MUSIC_CLIP_REQUEST_SECONDS,
            )

            result = self.music_generation_service.generate(
                instruction,
                duration_seconds=requested_duration_seconds,
                track_duration_seconds=segment_span_seconds,
            )

            if not result.success or result.audio_track is None:
                message = (
                    result.failure.message
                    if result.failure is not None
                    else "Music generation failed without failure details."
                )
                segment.status = SoundDesignItemStatus.FAILED

                raise RuntimeError(f"Music generation failed: {message}")

            audio_timeline = job.audio_timeline or AudioTimeline()
            audio_timeline.tracks = [
                track
                for track in audio_timeline.tracks
                if track.metadata.get("sound_design_segment_id") != segment_id
            ]
            audio_track = result.audio_track.model_copy(
                update={
                    "start_time_seconds": start_item.start_time_seconds,
                    "metadata": {
                        **result.audio_track.metadata,
                        "sound_design_segment_id": segment_id,
                    },
                }
            )
            audio_timeline.tracks.append(audio_track)
            job.audio_timeline = audio_timeline

            segment.status = SoundDesignItemStatus.GENERATED
            segment.audio_track_id = str(audio_track.id)
        except Exception:
            self._release_budget(self.music_profile_id, estimated_cost_usd)
            raise

        self.invalidation_service.on_audio_regenerated(
            job,
            reason=(
                "Music segment "
                f"{segment.start_scene_number}-{segment.end_scene_number} "
                "was generated."
            ),
        )

        return job

    def run_all_audio(self, job: VideoJob) -> AudioGenerationSummary:
        """
        Coordinate voice, timeline, music, and sound-effect generation
        as one action: reuse whatever is already valid, generate
        whatever is missing or stale, and report each component's
        outcome individually rather than letting one failure abort the
        rest (spec section on unified production audio).
        """

        results: list[AudioComponentResult] = []

        results.append(self._run_voice_component(job))
        results.append(self._run_timeline_component(job))
        results.append(self._run_music_component(job))
        results.append(self._run_sound_effects_component(job))

        return AudioGenerationSummary(results=results)

    def _run_voice_component(self, job: VideoJob) -> AudioComponentResult:
        if self._voice_is_current(job):
            return AudioComponentResult(
                component="voice",
                status=AudioComponentStatus.REUSED,
                detail=f"Existing voiceover ('{job.voice_file}') is still valid.",
            )

        try:
            self.run_voice(job)
        except (RuntimeError, ValueError) as error:
            return AudioComponentResult(
                component="voice", status=AudioComponentStatus.FAILED, detail=str(error)
            )

        return AudioComponentResult(
            component="voice",
            status=AudioComponentStatus.GENERATED,
            detail=f"Generated voiceover ('{job.voice_file}').",
        )

    def _run_timeline_component(self, job: VideoJob) -> AudioComponentResult:
        if job.video_timeline is not None and not self.invalidation_service.is_stale(
            job, "video_timeline"
        ):
            return AudioComponentResult(
                component="timeline",
                status=AudioComponentStatus.REUSED,
                detail="Existing editing timeline is still valid.",
            )

        try:
            self.run_timeline(job)
        except (RuntimeError, ValueError) as error:
            return AudioComponentResult(
                component="timeline",
                status=AudioComponentStatus.FAILED,
                detail=str(error),
            )

        return AudioComponentResult(
            component="timeline",
            status=AudioComponentStatus.GENERATED,
            detail="Built the editing timeline.",
        )

    def _run_music_component(self, job: VideoJob) -> AudioComponentResult:
        if self.music_generation_service is None:
            self._record_manual_requirement(
                job,
                requirement_type=ManualAudioRequirementType.MUSIC,
                reason="No music provider is configured.",
                instructions=(
                    "Configure a music provider, or supply a background-music "
                    "track manually."
                ),
            )

            return AudioComponentResult(
                component="music",
                status=AudioComponentStatus.MANUAL_REQUIRED,
                detail="No music provider is configured.",
            )

        if job.video_timeline is None:
            return AudioComponentResult(
                component="music",
                status=AudioComponentStatus.FAILED,
                detail="Music generation requires a built editing timeline.",
            )

        if self._first_enabled_music_item(job.video_timeline.items) is None:
            return AudioComponentResult(
                component="music",
                status=AudioComponentStatus.SKIPPED,
                detail="This genre has no background music configured for any scene.",
            )

        if self._track_is_current(job, AudioTrackType.BACKGROUND_MUSIC):
            return AudioComponentResult(
                component="music",
                status=AudioComponentStatus.REUSED,
                detail="Existing background-music track is still valid.",
            )

        try:
            self.run_music(job)
        except (RuntimeError, ValueError) as error:
            return AudioComponentResult(
                component="music", status=AudioComponentStatus.FAILED, detail=str(error)
            )

        return AudioComponentResult(
            component="music",
            status=AudioComponentStatus.GENERATED,
            detail="Generated background music.",
        )

    def _run_sound_effects_component(self, job: VideoJob) -> AudioComponentResult:
        if self.sound_effect_generation_service is None:
            self._record_manual_requirement(
                job,
                requirement_type=ManualAudioRequirementType.SOUND_EFFECT,
                reason="No sound-effect provider is configured.",
                instructions=(
                    "Configure a sound-effect provider, or supply sound-effect "
                    "tracks manually."
                ),
            )

            return AudioComponentResult(
                component="sound_effects",
                status=AudioComponentStatus.MANUAL_REQUIRED,
                detail="No sound-effect provider is configured.",
            )

        if job.video_timeline is None:
            return AudioComponentResult(
                component="sound_effects",
                status=AudioComponentStatus.FAILED,
                detail="Sound-effect generation requires a built editing timeline.",
            )

        if self._track_is_current(job, AudioTrackType.SOUND_EFFECT):
            return AudioComponentResult(
                component="sound_effects",
                status=AudioComponentStatus.REUSED,
                detail="Existing sound-effect tracks are still valid.",
            )

        try:
            self.run_sound_effects(job)
        except (RuntimeError, ValueError) as error:
            if "has no sound effects configured" in str(error):
                return AudioComponentResult(
                    component="sound_effects",
                    status=AudioComponentStatus.SKIPPED,
                    detail=str(error),
                )

            return AudioComponentResult(
                component="sound_effects",
                status=AudioComponentStatus.FAILED,
                detail=str(error),
            )

        return AudioComponentResult(
            component="sound_effects",
            status=AudioComponentStatus.GENERATED,
            detail="Generated sound effects.",
        )

    def _voice_is_current(self, job: VideoJob) -> bool:
        if job.voice_status != VoiceStatus.READY or not job.voice_file:
            return False

        if self.invalidation_service.is_stale(job, "audio_timeline"):
            return False

        if job.script_version_history is None:
            return True

        return (
            job.voice_script_version
            == job.script_version_history.current_version.version_number
        )

    def _track_is_current(self, job: VideoJob, track_type: AudioTrackType) -> bool:
        if job.audio_timeline is None:
            return False

        if self.invalidation_service.is_stale(job, "audio_timeline"):
            return False

        return any(
            track.track_type == track_type for track in job.audio_timeline.tracks
        )

    def _gate_budget(
        self, profile_id: str | None, estimated_cost_usd: float, *, stage: str
    ) -> None:
        """
        Check and reserve budget for one stage's provider call, if
        both a profile id and a real (non-zero) cost estimate are
        configured. A no-op otherwise, so existing callers that never
        opted into gating see no behavior change.
        """

        if self.budget_service is None or profile_id is None:
            return

        if estimated_cost_usd <= 0:
            return

        check = self.budget_service.check_request(profile_id, estimated_cost_usd)

        if not check.allowed:
            raise RuntimeError(f"{stage} blocked by budget: {check.reason}")

        self.budget_service.reserve(profile_id, estimated_cost_usd)

    def _release_budget(
        self, profile_id: str | None, estimated_cost_usd: float
    ) -> None:
        """Release a reservation made by _gate_budget when a stage doesn't complete."""

        if self.budget_service is None or profile_id is None:
            return

        if estimated_cost_usd <= 0:
            return

        self.budget_service.release(profile_id, estimated_cost_usd)

    @staticmethod
    def _record_manual_requirement(
        job: VideoJob,
        *,
        requirement_type: ManualAudioRequirementType,
        reason: str,
        instructions: str,
    ) -> None:
        already_recorded = any(
            requirement.requirement_type == requirement_type
            for requirement in job.manual_audio_requirements
        )

        if already_recorded:
            return

        job.manual_audio_requirements.append(
            ManualAudioRequirement(
                requirement_type=requirement_type,
                reason=reason,
                instructions=instructions,
            )
        )

    @staticmethod
    def _single_provider(results: list[VoiceGenerationResult]) -> str | None:
        providers = {
            result.provider for result in results if result.provider is not None
        }

        if len(providers) != 1:
            return None

        return next(iter(providers))

    @staticmethod
    def _first_enabled_music_item(
        items: list[VideoTimelineItem],
    ) -> VideoTimelineItem | None:
        for item in sorted(items, key=lambda value: value.scene_number):
            if (
                item.editing_blueprint is not None
                and item.editing_blueprint.music.enabled
            ):
                return item

        return None

    @staticmethod
    def _resolve_start_time(
        *,
        item: VideoTimelineItem,
        cue: ResolvedSoundEffectInstruction,
    ) -> float:
        scene_duration = max(item.end_time_seconds - item.start_time_seconds, 0.0)

        if cue.relative_position_percent is not None:
            offset = scene_duration * (cue.relative_position_percent / 100.0)
        elif cue.timing_mode == DirectiveTimingMode.SCENE_START:
            offset = 0.0
        elif cue.timing_mode == DirectiveTimingMode.SCENE_MIDDLE:
            offset = scene_duration / 2.0
        elif cue.timing_mode == DirectiveTimingMode.SCENE_END:
            offset = scene_duration
        else:
            offset = cue.start_offset_seconds

        clamped_offset = min(max(offset, 0.0), scene_duration)

        return item.start_time_seconds + clamped_offset
