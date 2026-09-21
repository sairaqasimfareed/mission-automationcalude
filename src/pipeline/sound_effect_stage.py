from __future__ import annotations

import time
from collections import Counter

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrackType
from src.models.editing_directives import DirectiveTimingMode
from src.models.resolved_editing_blueprint import (
    ResolvedPresetReference,
    ResolvedSoundEffectInstruction,
)
from src.models.sound_design_plan import SoundDesignItemStatus, SoundEffectCueDirective
from src.models.video_timeline_item import VideoTimelineItem
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import PipelineStageName, PipelineStageStatus
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.audio_cue_policy_service import AudioCuePolicyService
from src.services.sound_effect_generation_service import (
    SoundEffectGenerationService,
)


class SoundEffectPipelineStage(BasePipelineStage):
    """
    Pipeline adapter for provider-independent sound-effect generation.

    Runs after TimelinePipelineStage, for the same reason
    MusicPipelineStage does: each scene's resolved sound-effect cues
    live on VideoTimelineItem.editing_blueprint. Unlike music, sound
    effects are per-scene and there can be several per scene, each
    placed at its own cue point (scene start/middle/end, or an
    absolute offset) - resolved here into an absolute timeline
    position using the scene's actual start_time_seconds.

    Sound effects are an enhancement like music: a failed cue is
    skipped with a warning rather than failing the whole stage.
    """

    def __init__(
        self,
        *,
        generation_service: SoundEffectGenerationService,
        provider_name: str | None = None,
        cue_policy_service: AudioCuePolicyService | None = None,
        transition_duration_seconds: float = 0.0,
    ) -> None:
        self._generation_service = generation_service

        normalized_provider = (
            provider_name.strip() if provider_name is not None else None
        )

        self._provider_name = normalized_provider or None
        # Post-Script-Approval Production Plan, Phase 10: "Prevent
        # duplicate/repetitive SFX and uncontrolled loudness
        # accumulation." Defaults to a real, active instance rather
        # than None - unlike Phase 8's technical-validation gate, this
        # check only ever appends warnings, it never blocks or changes
        # attached_count, so there is no existing behavior for a
        # default-off posture to protect.
        self._cue_policy_service = cue_policy_service or AudioCuePolicyService()

        self._transition_duration_seconds = transition_duration_seconds

    @property
    def stage_name(self) -> PipelineStageName:
        return PipelineStageName.SOUND_EFFECTS

    def execute(self, context: StageContext) -> StageResult:
        started_at = time.perf_counter()

        timeline = context.job.video_timeline

        if timeline is None:
            return StageResult(
                stage=self.stage_name,
                status=PipelineStageStatus.COMPLETED,
                duration_seconds=time.perf_counter() - started_at,
                progress_percent=100,
                warnings=["Sound-effect stage requires a built video timeline."],
                errors=[],
                metadata={"attached_count": 0},
            )

        audio_timeline = context.job.audio_timeline or AudioTimeline()
        warnings: list[str] = []
        attached_count = 0
        skipped_existing_count = 0

        # Found via external audit: a full pipeline re-run
        # (resume_previous_pipeline=True + skip_completed_stages=False,
        # a real, reachable AdvancedSettings combination) re-executes
        # this stage even when it already completed, and this loop
        # used to append every cue unconditionally - silently
        # double-generating and double-attaching every SFX cue on
        # each re-run. This mirrors VoiceTimelineService's own
        # duplicate-scene guard: (scene_number, resolved start time)
        # is exactly what makes two cues "the same cue" here, since
        # start-time resolution is itself deterministic from the same
        # editing blueprint. A Counter, not a set, because two
        # genuinely distinct cues within one planning pass can
        # legitimately share a key (e.g. the repetitive-cue case
        # AudioCuePolicyService itself is meant to flag) - a snapshot
        # taken once, before this run attaches anything, so it only
        # ever matches tracks a *previous* run already created, never
        # a sibling cue from this same pass.
        remaining_existing_counts = Counter(
            (track.metadata.get("scene_number"), track.start_time_seconds)
            for track in audio_timeline.tracks
            if track.track_type == AudioTrackType.SOUND_EFFECT
        )

        items_by_scene = {item.scene_number: item for item in timeline.items}

        # Real-world finding, 2026-09-18: confirmed on two real,
        # separate scenes via direct frame inspection - a cue placed
        # "at the end" of its own scene, clamped against that scene's
        # nominal VideoTimelineItem boundary, lands roughly
        # transition_duration_seconds into the *next* scene's real
        # screen time once crossfade shrinkage is accounted for (the
        # nominal boundary assumes no crossfade eats into it - the
        # same gap already fixed for voice, music-boundary-clipping,
        # and subtitle timing, just never applied to a cue's own
        # position within its scene before now). first_scene_number/
        # last_scene_number let _resolve_start_time know which edges
        # of a given scene have a real transition to leave room for -
        # this pipeline stage runs before chunking is ever decided,
        # so every internal boundary here is a real crossfade, with
        # no chunk-boundary hard-cut exception to account for (unlike
        # ProductionRenderService._slice_for_scenes, which runs after
        # chunking is known).
        first_scene_number = min(items_by_scene) if items_by_scene else None

        last_scene_number = max(items_by_scene) if items_by_scene else None

        content_aware_cues = (
            context.job.sound_design_plan.sfx_cues
            if context.job.sound_design_plan is not None
            else None
        )

        if content_aware_cues is not None:
            # Real-world finding: a job whose SFX were first generated
            # via the legacy genre-preset path (the else branch below)
            # and only later acquired a real sound_design_plan (e.g. a
            # job rendered before content-aware sound design ran, then
            # re-rendered afterward) keeps those old genre-preset
            # tracks forever - nothing ever reconciled them against
            # the newer content-aware plan. A real render ended up
            # with the SAME generic "impact hit" cue on every single
            # scene (genre-preset, from an early run) stacked on top
            # of real, narration-grounded cues (content-aware, from a
            # later run) - exactly the "SFX everywhere" a listener
            # would notice. Once a job has a real sound_design_plan,
            # only content-aware cues should exist; anything else on
            # the timeline is a stale leftover from before that plan
            # existed, identified by not matching any cue's own
            # audio_track_id (the one, authoritative link between a
            # content-aware cue and the track it produced).
            content_aware_track_ids = {
                cue.audio_track_id
                for cue in content_aware_cues
                if cue.audio_track_id is not None
            }

            stale_tracks = [
                track
                for track in audio_timeline.tracks
                if track.track_type == AudioTrackType.SOUND_EFFECT
                and str(track.id) not in content_aware_track_ids
            ]

            if stale_tracks:
                stale_ids = {track.id for track in stale_tracks}

                audio_timeline.tracks = [
                    track
                    for track in audio_timeline.tracks
                    if track.id not in stale_ids
                ]

                warnings.append(
                    f"Removed {len(stale_tracks)} sound-effect track(s) "
                    "left over from a legacy (non-content-aware) "
                    "sound-design pass."
                )

            # Content-aware cues carry their own PENDING/GENERATED/
            # FAILED status (set by SceneSoundDesignService, or reset
            # by an operator asking to regenerate one), so a rerun of
            # this stage skips by that status directly instead of the
            # legacy path's audio_timeline reverse-lookup.
            for cue in content_aware_cues:
                if cue.status == SoundDesignItemStatus.GENERATED:
                    skipped_existing_count += 1
                    continue

                item = items_by_scene.get(cue.scene_number)

                if item is None:
                    warnings.append(
                        f"Sound design cue for scene {cue.scene_number} has "
                        "no matching timeline item."
                    )
                    cue.status = SoundDesignItemStatus.FAILED

                    continue

                instruction = self._instruction_from_content_aware_cue(cue)

                start_time_seconds = self._resolve_start_time(
                    item=item,
                    cue=instruction,
                    transition_duration_seconds=self._transition_duration_seconds,
                    first_scene_number=first_scene_number,
                    last_scene_number=last_scene_number,
                )

                result = self._generation_service.generate(
                    instruction,
                    scene_number=item.scene_number,
                    start_time_seconds=start_time_seconds,
                    provider_name=self._provider_name,
                )

                if not result.success:
                    message = (
                        result.failure.message
                        if result.failure is not None
                        else "Sound-effect generation failed without details."
                    )

                    warnings.append(
                        f"Scene {item.scene_number} sound effect was not "
                        f"generated: {message}"
                    )
                    cue.status = SoundDesignItemStatus.FAILED

                    continue

                assert result.audio_track is not None

                audio_timeline.tracks.append(result.audio_track)
                cue.status = SoundDesignItemStatus.GENERATED
                cue.audio_track_id = str(result.audio_track.id)
                attached_count += 1
        else:
            for item in sorted(timeline.items, key=lambda value: value.scene_number):
                if item.editing_blueprint is None:
                    continue

                for genre_cue in item.editing_blueprint.sound_effects:
                    if not genre_cue.enabled:
                        continue

                    start_time_seconds = self._resolve_start_time(
                        item=item,
                        cue=genre_cue,
                        transition_duration_seconds=self._transition_duration_seconds,
                        first_scene_number=first_scene_number,
                        last_scene_number=last_scene_number,
                    )

                    cue_key = (item.scene_number, start_time_seconds)

                    if remaining_existing_counts[cue_key] > 0:
                        remaining_existing_counts[cue_key] -= 1
                        skipped_existing_count += 1
                        continue

                    result = self._generation_service.generate(
                        genre_cue,
                        scene_number=item.scene_number,
                        start_time_seconds=start_time_seconds,
                        provider_name=self._provider_name,
                    )

                    if not result.success:
                        message = (
                            result.failure.message
                            if result.failure is not None
                            else "Sound-effect generation failed without details."
                        )

                        warnings.append(
                            f"Scene {item.scene_number} sound effect was not "
                            f"generated: {message}"
                        )

                        continue

                    assert result.audio_track is not None

                    audio_timeline.tracks.append(result.audio_track)
                    attached_count += 1

        if skipped_existing_count:
            warnings.append(
                f"Skipped {skipped_existing_count} sound-effect cue(s) "
                "already attached from a previous run."
            )

        context.job.audio_timeline = audio_timeline

        policy_result = self._cue_policy_service.evaluate(audio_timeline.tracks)

        for conflict in policy_result.conflicts:
            warnings.append(f"Audio cue policy: {conflict.detail}")

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
            duration_seconds=time.perf_counter() - started_at,
            progress_percent=100,
            warnings=warnings,
            errors=[],
            metadata={
                "attached_count": attached_count,
                "skipped_existing_count": skipped_existing_count,
            },
        )

    @staticmethod
    def _instruction_from_content_aware_cue(
        cue: SoundEffectCueDirective,
    ) -> ResolvedSoundEffectInstruction:
        """
        Adapt a content-aware SoundEffectCueDirective (a bespoke,
        scene-specific generation_prompt) into the same
        ResolvedSoundEffectInstruction shape SoundEffectGenerationService
        already consumes, so no change is needed there. preset_id is
        preserved on the synthetic preset reference purely for
        traceability (shown in the AudioTrack's own metadata) - the
        actual provider query always comes from generation_prompt,
        since that is what the sound designer LLM wrote specifically
        for this scene.
        """

        preset = ResolvedPresetReference(
            directive_path="sound_design.sfx_cue",
            requested_preset_id=(cue.preset_id or "content_aware.custom"),
            resolved_preset_id=(cue.preset_id or "content_aware.custom"),
            found_exact_match=(cue.preset_id is not None),
            implementation={"library_query": cue.generation_prompt},
        )

        return ResolvedSoundEffectInstruction(
            preset=preset,
            timing_mode=cue.timing_mode,
            start_offset_seconds=cue.start_offset_seconds,
            relative_position_percent=cue.relative_position_percent,
            volume_percent=cue.volume_percent,
            intensity=cue.intensity,
            enabled=True,
            # Content-aware cues have no per-cue directive for this
            # (unlike the genre-preset path's SoundEffectDirective) -
            # real-world finding: SFX never ducking under voice at all
            # buried narration under a scene with several cues, so
            # this defaults on here too rather than silently opting
            # every content-aware cue out of it.
            duck_under_voice=True,
        )

    @staticmethod
    def _resolve_start_time(
        *,
        item: VideoTimelineItem,
        cue: ResolvedSoundEffectInstruction,
        transition_duration_seconds: float = 0.0,
        first_scene_number: int | None = None,
        last_scene_number: int | None = None,
    ) -> float:
        """
        Resolve one cue's absolute timeline position.

        transition_duration_seconds/first_scene_number/
        last_scene_number reserve the same real-crossfade dead zone
        already used for subtitle timing (see
        SubtitleExecutionService.build_plan's own docstring) - a cue
        clamped against this scene's *nominal* boundary can land
        squarely in the next scene's real screen time once crossfade
        shrinkage is accounted for. Confirmed directly on a real
        render: a scene's own "scene end" cue, positioned at its
        nominal boundary, played after that scene's real content had
        already given way to the next one.

        Real-world finding, 2026-09-18 (second pass): the fix above
        only reserves the dead zone at a scene's OWN edges - it still
        anchored the cue to item.start_time_seconds, which
        TimelineBuilderService builds as a pure, uncorrected sum of
        each preceding scene's real clip duration (never subtracting
        any crossfade overlap). VoicePipelineStage learned this same
        lesson a day earlier for voice tracks (see its own
        _scene_video_start_offsets docstring) and computes voice
        positions in real, crossfade-corrected time - but SFX cues
        kept using the raw, nominal VideoTimelineItem position
        directly, unlike voice. Confirmed directly against a real job:
        scene 8's nominal item.start_time_seconds is 44.0s, but the
        real, composed video actually reaches scene 8 at 39.8s (matching
        VoicePipelineStage's own corrected voice-track start for that
        exact scene, and the real xfade offset baked into the
        rendered command) - a 4.2s error (seven preceding crossfades'
        worth) that grows by another transition_duration_seconds every
        scene boundary. The per-scene edge reservation above closes
        the ~0.6s gap at a scene's own edges; this closes the much
        larger, compounding gap between a scene's nominal and real
        start position. Assumes contiguous 1-indexed scene numbering,
        the same assumption ProductionRenderService._slice_for_scenes
        already relies on for its own crossfade-count math.
        """

        real_item_start_seconds = item.start_time_seconds - (
            (item.scene_number - 1) * transition_duration_seconds
        )

        scene_duration = max(item.end_time_seconds - item.start_time_seconds, 0.0)

        window_start = (
            transition_duration_seconds
            if first_scene_number is not None
            and item.scene_number != first_scene_number
            else 0.0
        )

        window_end = (
            scene_duration - transition_duration_seconds
            if last_scene_number is not None and item.scene_number != last_scene_number
            else scene_duration
        )

        window_end = max(window_start, window_end)

        if cue.relative_position_percent is not None:
            offset = scene_duration * (cue.relative_position_percent / 100.0)
        elif cue.timing_mode == DirectiveTimingMode.SCENE_START:
            offset = window_start
        elif cue.timing_mode == DirectiveTimingMode.SCENE_MIDDLE:
            offset = (window_start + window_end) / 2.0
        elif cue.timing_mode == DirectiveTimingMode.SCENE_END:
            offset = window_end
        else:
            offset = cue.start_offset_seconds

        clamped_offset = min(max(offset, window_start), window_end)

        return real_item_start_seconds + clamped_offset
