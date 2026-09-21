from __future__ import annotations

import time

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrackType
from src.models.resolved_editing_blueprint import (
    ResolvedMusicInstruction,
    ResolvedPresetReference,
)
from src.models.sound_design_plan import MusicMoodSegment, SoundDesignItemStatus
from src.models.video_timeline_item import VideoTimelineItem
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import PipelineStageName, PipelineStageStatus
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.music_generation_service import MusicGenerationService

# Real-world finding, 2026-09-13: requesting a clip anywhere near a
# whole video's length from ElevenLabs's sound-generation endpoint
# fails with HTTP 400 (confirmed: 20s succeeds, 68s does not). Capped
# with a safety margin below the confirmed-working value.
MAX_SINGLE_MUSIC_CLIP_REQUEST_SECONDS = 18.0


class MusicPipelineStage(BasePipelineStage):
    """
    Pipeline adapter for provider-independent background-music
    generation.

    Runs after TimelinePipelineStage: the resolved music instruction
    it needs (genre-resolved preset, volume, fade, ducking) lives on
    each timeline item's editing_blueprint, which TimelinePipelineStage
    is what actually builds. Background music is one continuous track
    for the whole video rather than per-scene, so this stage only
    needs one enabled instruction - every scene sharing the same genre
    profile resolves to the same preset, so the first one found is
    used, sized to the full timeline duration.

    Unlike voice, a missing or failed music track does not fail the
    render: a video without background music is still a valid,
    deliverable video. Every failure path here returns COMPLETED with
    a warning, never FAILED.
    """

    def __init__(
        self,
        *,
        generation_service: MusicGenerationService,
        provider_name: str | None = None,
        transition_duration_seconds: float = 0.0,
    ) -> None:
        self._generation_service = generation_service

        normalized_provider = (
            provider_name.strip() if provider_name is not None else None
        )

        self._provider_name = normalized_provider or None

        self._transition_duration_seconds = transition_duration_seconds

    @property
    def stage_name(self) -> PipelineStageName:
        return PipelineStageName.BACKGROUND_MUSIC

    def execute(self, context: StageContext) -> StageResult:
        started_at = time.perf_counter()

        timeline = context.job.video_timeline

        if timeline is None:
            return self._skipped_result(
                started_at=started_at,
                warning="Music stage requires a built video timeline.",
            )

        audio_timeline = context.job.audio_timeline or AudioTimeline()

        music_segments = (
            context.job.sound_design_plan.music_segments
            if context.job.sound_design_plan is not None
            else None
        )

        if music_segments is not None:
            return self._execute_content_aware(
                started_at=started_at,
                timeline_items=timeline.items,
                music_segments=music_segments,
                audio_timeline=audio_timeline,
                context=context,
            )

        # Found via external audit: a full pipeline re-run
        # (resume_previous_pipeline=True + skip_completed_stages=False,
        # a real, reachable AdvancedSettings combination) re-executes
        # this stage even when it already completed, and this stage
        # used to regenerate and re-attach background music
        # unconditionally - double-paying for generation and leaving
        # two overlapping music tracks. Background music is one
        # continuous track for the whole video, so "already handled"
        # is exactly "a BACKGROUND_MUSIC track already exists."
        if any(
            track.track_type == AudioTrackType.BACKGROUND_MUSIC
            for track in audio_timeline.tracks
        ):
            return self._skipped_result(
                started_at=started_at,
                warning=None,
                metadata={"reason": "background_music_already_attached"},
            )

        instruction_item = self._first_enabled_music_item(timeline.items)

        if instruction_item is None:
            return self._skipped_result(
                started_at=started_at,
                warning=None,
                metadata={"reason": "no_music_configured_for_genre"},
            )

        assert instruction_item.editing_blueprint is not None

        duration_seconds = timeline.calculate_duration()

        result = self._generation_service.generate(
            instruction_item.editing_blueprint.music,
            duration_seconds=duration_seconds,
            provider_name=self._provider_name,
        )

        if not result.success:
            message = (
                result.failure.message
                if result.failure is not None
                else "Music generation failed without failure details."
            )

            return self._skipped_result(
                started_at=started_at,
                warning=f"Background music was not generated: {message}",
                metadata={"reason": "generation_failed"},
            )

        assert result.audio_track is not None

        audio_timeline.tracks.append(result.audio_track)
        context.job.audio_timeline = audio_timeline

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
            duration_seconds=time.perf_counter() - started_at,
            progress_percent=100,
            warnings=list(result.warnings),
            errors=[],
            metadata={
                "attached": True,
                "provider": result.provider,
                "output_file": result.output_file,
                "duration_seconds": duration_seconds,
            },
        )

    def _execute_content_aware(
        self,
        *,
        started_at: float,
        timeline_items: list[VideoTimelineItem],
        music_segments: list[MusicMoodSegment],
        audio_timeline: AudioTimeline,
        context: StageContext,
    ) -> StageResult:
        """
        Generate one background-music clip per MusicMoodSegment,
        replacing a single static genre-wide track with a mood curve
        that can actually shift as the story does. Each segment's clip
        is requested at a safely capped duration and looped (via
        MusicGenerationService's track_duration_seconds split) to fill
        its real scene-range span, positioned at that range's actual
        start time on the timeline - unlike the single-track legacy
        path, start_time_seconds is not always 0.0.
        """

        items_by_scene = {item.scene_number: item for item in timeline_items}

        warnings: list[str] = []
        attached_count = 0
        skipped_existing_count = 0

        # Real-world finding, same root cause already fixed for SFX
        # (SoundEffectPipelineStage): a job whose music was first
        # generated via the legacy single-whole-video-track path (the
        # else branch below) and only later acquired a real
        # sound_design_plan keeps that old track forever - nothing
        # ever reconciled it against the newer content-aware mood
        # segments. A real render ended up with a continuous, un-
        # faded legacy track (volume 0.2, no fade-in, running the
        # entire video) layered underneath 8 real, narration-aware
        # segments (volume 0.25, each with its own fade-in) - roughly
        # doubling the music energy for the whole video and burying
        # the start of narration under an immediate, un-faded music
        # entrance. Once a job has a real sound_design_plan, only its
        # own segments should exist; anything else is a stale leftover
        # from before that plan existed, identified by not matching
        # any segment's own audio_track_id (the one, authoritative
        # link between a content-aware segment and the track it
        # produced).
        content_aware_track_ids = {
            segment.audio_track_id
            for segment in music_segments
            if segment.audio_track_id is not None
        }

        stale_tracks = [
            track
            for track in audio_timeline.tracks
            if track.track_type == AudioTrackType.BACKGROUND_MUSIC
            and str(track.id) not in content_aware_track_ids
        ]

        if stale_tracks:
            stale_ids = {track.id for track in stale_tracks}

            audio_timeline.tracks = [
                track for track in audio_timeline.tracks if track.id not in stale_ids
            ]

            warnings.append(
                f"Removed {len(stale_tracks)} background-music track(s) "
                "left over from a legacy (non-content-aware) "
                "sound-design pass."
            )

        for segment in music_segments:
            if segment.status == SoundDesignItemStatus.GENERATED:
                skipped_existing_count += 1

                continue

            start_item = items_by_scene.get(segment.start_scene_number)
            end_item = items_by_scene.get(segment.end_scene_number)

            if start_item is None or end_item is None:
                warnings.append(
                    "Music segment "
                    f"{segment.start_scene_number}-{segment.end_scene_number} "
                    "has no matching timeline item(s)."
                )
                segment.status = SoundDesignItemStatus.FAILED

                continue

            # Real-world finding, 2026-09-18: start_item/end_item's own
            # start_time_seconds/end_time_seconds are TimelineBuilderService's
            # nominal, uncorrected positions (a pure sum of each
            # preceding scene's real clip duration, never subtracting
            # crossfade overlap) - the same gap already found and
            # fixed for SFX cues (see SoundEffectPipelineStage.
            # _resolve_start_time's own docstring) and originally for
            # voice (VoicePipelineStage._scene_video_start_offsets).
            # A segment's real span is shorter than its nominal span
            # by one transition_duration_seconds for every scene
            # boundary the segment actually crosses - confirmed
            # against a real job: a segment nominally spanning 52.0s
            # to 96.0s (44.0s) actually spans only 41.0s of real
            # screen time across its 10 crossed boundaries.
            crossed_boundaries = end_item.scene_number - start_item.scene_number

            real_start_time_seconds = start_item.start_time_seconds - (
                (start_item.scene_number - 1) * self._transition_duration_seconds
            )

            segment_span_seconds = (
                end_item.end_time_seconds - start_item.start_time_seconds
            ) - (crossed_boundaries * self._transition_duration_seconds)

            if segment_span_seconds <= 0:
                warnings.append(
                    "Music segment "
                    f"{segment.start_scene_number}-{segment.end_scene_number} "
                    "resolved to a non-positive duration."
                )
                segment.status = SoundDesignItemStatus.FAILED

                continue

            requested_duration_seconds = min(
                segment_span_seconds,
                MAX_SINGLE_MUSIC_CLIP_REQUEST_SECONDS,
            )

            instruction = self._instruction_from_mood_segment(segment)

            result = self._generation_service.generate(
                instruction,
                duration_seconds=requested_duration_seconds,
                track_duration_seconds=segment_span_seconds,
                provider_name=self._provider_name,
            )

            if not result.success:
                message = (
                    result.failure.message
                    if result.failure is not None
                    else "Music generation failed without failure details."
                )

                warnings.append(
                    "Music segment "
                    f"{segment.start_scene_number}-{segment.end_scene_number} "
                    f"was not generated: {message}"
                )
                segment.status = SoundDesignItemStatus.FAILED

                continue

            assert result.audio_track is not None

            audio_track = result.audio_track.model_copy(
                update={
                    "start_time_seconds": real_start_time_seconds,
                    # Real-world finding, 2026-09-18: needed by
                    # ProductionRenderService._slice_for_scenes to
                    # apply the same chunk-boundary correction voice
                    # tracks already get - this segment's position was
                    # computed assuming every scene boundary is a real
                    # crossfade (see real_start_time_seconds above),
                    # which is wrong for the specific boundary(ies)
                    # that end up as a chunk split (a hard cut, not a
                    # crossfade) - unknowable here since chunking is
                    # decided later, at render time.
                    "metadata": {
                        **result.audio_track.metadata,
                        "scene_number": start_item.scene_number,
                    },
                }
            )

            audio_timeline.tracks.append(audio_track)
            segment.status = SoundDesignItemStatus.GENERATED
            segment.audio_track_id = str(audio_track.id)
            attached_count += 1

        if skipped_existing_count:
            warnings.append(
                f"Skipped {skipped_existing_count} music segment(s) already "
                "attached from a previous run."
            )

        context.job.audio_timeline = audio_timeline

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
    def _instruction_from_mood_segment(
        segment: MusicMoodSegment,
    ) -> ResolvedMusicInstruction:
        preset = ResolvedPresetReference(
            directive_path="sound_design.music_segment",
            requested_preset_id="content_aware.custom",
            resolved_preset_id="content_aware.custom",
            found_exact_match=False,
            implementation={
                "library_query": segment.mood_description,
                "loop": True,
            },
        )

        return ResolvedMusicInstruction(
            preset=preset,
            intensity=segment.intensity,
            volume_percent=25.0,
            fade_in_seconds=1.0,
            fade_out_seconds=1.0,
            duck_under_voice=True,
            enabled=True,
        )

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

    def _skipped_result(
        self,
        *,
        started_at: float,
        warning: str | None,
        metadata: dict[str, object] | None = None,
    ) -> StageResult:
        """
        Build a non-fatal COMPLETED result for every "no music" path.

        Music is an enhancement, not a hard requirement - StageResult
        forbids errors on a COMPLETED status, so any failure here is
        surfaced only as a warning (or silently, when there was
        genuinely nothing to generate).
        """

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
            duration_seconds=time.perf_counter() - started_at,
            progress_percent=100,
            warnings=[warning] if warning else [],
            errors=[],
            metadata={"attached": False, **(metadata or {})},
        )
