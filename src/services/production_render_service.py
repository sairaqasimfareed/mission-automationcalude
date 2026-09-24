from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_config import FFmpegConfig, FFmpegResolvedConfig
from src.models.ffmpeg_input import FFmpegInputPlan
from src.models.master_edit_plan import MasterEditPlan
from src.models.render_failure_diagnosis import classify_render_failure
from src.models.render_result import RenderResult, RenderStatus, SceneRenderTiming
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.animation_execution_service import (
    AnimationExecutionService,
)
from src.services.camera_execution_service import (
    CameraExecutionService,
)
from src.services.effect_execution_service import (
    EffectExecutionService,
)
from src.services.ffmpeg_capability_service import (
    FFmpegCapabilityService,
)
from src.services.ffmpeg_command_builder_service import (
    FFmpegCommandBuilderService,
)
from src.services.ffmpeg_execution_service import (
    CancellationCheck,
    FFmpegExecutionService,
    ProgressCallback,
)
from src.services.filter_graph_builder_service import (
    FilterGraphBuilderService,
)
from src.services.master_edit_plan_service import (
    MasterEditPlanService,
)
from src.services.render_graph_builder_service import (
    RenderGraphBuilderService,
)
from src.services.subtitle_execution_service import (
    SubtitleExecutionService,
)
from src.services.transition_execution_service import (
    TransitionExecutionService,
)


class ProductionRenderService:
    """
    Execute one prepared video job through the real FFmpeg render stack.

    This service is the production rendering boundary between the
    provider-independent editing/timeline architecture and FFmpeg.

    It does not create scenes, generate assets, resolve editing
    directives, generate voice, or own pipeline orchestration.

    Its responsibilities are limited to:

    - combine prepared video/audio timelines into a master edit plan;
    - build renderer-independent execution plans;
    - build the renderer-independent render graph;
    - resolve local FFmpeg capabilities;
    - build the FFmpeg filter graph;
    - build the deterministic FFmpeg command plan;
    - execute FFmpeg, with optional progress and cancellation support;
    - promote a successfully staged render to its final output path;
    - normalize the execution into RenderResult, including resolved
      capabilities, command metadata, and a coarse failure category.
    """

    DEFAULT_OUTPUT_FILE = "outputs/final_video.mp4"

    # Windows' CreateProcess has a real, hard ~32,767 character limit
    # on one assembled command line - a large render (many scenes,
    # subtitles, and audio tracks) can produce a filter_complex
    # string that exceeds it, failing with WinError 206 before FFmpeg
    # even starts. macOS/Linux launch processes via execve instead,
    # governed by ARG_MAX - roughly 1MB on macOS and ~2MB on Linux,
    # 30-60x more headroom than Windows for the same command. Without
    # a platform split here, every platform would chunk at the same
    # conservative Windows-sized threshold even where it is never
    # actually needed, trading away real quality (a hard cut and a
    # music-loop restart at each chunk boundary) for nothing.
    _SAFE_COMMAND_LINE_LENGTH = 30000 if sys.platform == "win32" else 500000

    # Upper bound on how many pieces a single render will ever be
    # split into. At ~24 scenes fitting safely in one chunk (measured
    # empirically against a real command), 40 chunks covers roughly
    # 1,000 scenes - well over an hour of video even at a fast 4s
    # average scene length - while still bounding the worst case
    # against a pathological scene count (e.g. a planning bug).
    _MAXIMUM_RENDER_CHUNKS = 40

    # Real-world finding, 2026-09-16: with no explicit keyframe
    # interval, libx264/libx265 fall back to adaptive scenecut-based
    # keyframe placement - inspecting a real render found only 2
    # keyframes in the first 12 seconds (an 8.3s gap) on a scene with
    # little motion. A long GOP forces a decoder to reconstruct many
    # frames from a single distant keyframe, which is a well-known
    # real cause of stutter/hitching during ordinary playback on
    # constrained hardware or software decoders - independent of
    # anything about the video/audio content itself. Capping the
    # keyframe interval at a conservative, industry-standard 2 seconds
    # bounds this regardless of scene content.
    _MAX_KEYFRAME_INTERVAL_SECONDS = 2.0

    def __init__(
        self,
        *,
        master_edit_plan_service: MasterEditPlanService | None = None,
        transition_execution_service: TransitionExecutionService | None = None,
        effect_execution_service: EffectExecutionService | None = None,
        subtitle_execution_service: SubtitleExecutionService | None = None,
        camera_execution_service: CameraExecutionService | None = None,
        animation_execution_service: AnimationExecutionService | None = None,
        render_graph_builder_service: RenderGraphBuilderService | None = None,
        ffmpeg_capability_service: FFmpegCapabilityService | None = None,
        filter_graph_builder_service: FilterGraphBuilderService | None = None,
        ffmpeg_command_builder_service: FFmpegCommandBuilderService | None = None,
        ffmpeg_execution_service: FFmpegExecutionService | None = None,
        ffmpeg_config: FFmpegConfig | None = None,
        output_file: str = DEFAULT_OUTPUT_FILE,
    ) -> None:
        self._master_edit_plan_service = (
            master_edit_plan_service or MasterEditPlanService()
        )

        self._transition_execution_service = (
            transition_execution_service or TransitionExecutionService()
        )

        self._effect_execution_service = (
            effect_execution_service or EffectExecutionService()
        )

        self._subtitle_execution_service = (
            subtitle_execution_service or SubtitleExecutionService()
        )

        self._camera_execution_service = (
            camera_execution_service or CameraExecutionService()
        )

        self._animation_execution_service = (
            animation_execution_service or AnimationExecutionService()
        )

        self._render_graph_builder_service = (
            render_graph_builder_service or RenderGraphBuilderService()
        )

        self._ffmpeg_capability_service = (
            ffmpeg_capability_service or FFmpegCapabilityService()
        )

        self._filter_graph_builder_service = (
            filter_graph_builder_service or FilterGraphBuilderService()
        )

        self._ffmpeg_command_builder_service = (
            ffmpeg_command_builder_service or FFmpegCommandBuilderService()
        )

        self._ffmpeg_execution_service = (
            ffmpeg_execution_service or FFmpegExecutionService()
        )

        self._ffmpeg_config = ffmpeg_config or FFmpegConfig()

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Production render output file " "cannot be empty.")

        self._output_file = Path(cleaned_output_file).as_posix()

    @property
    def output_file(self) -> str:
        """Return the configured default output file."""

        return self._output_file

    @property
    def ffmpeg_config(self) -> FFmpegConfig:
        """Return the configured FFmpeg preferences."""

        return self._ffmpeg_config

    def render(
        self,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        output_file: str | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
        transition_duration_seconds: float = 0.0,
        letterbox_enabled: bool = False,
        include_subtitles: bool = True,
        audio_selection_is_intentional: bool = False,
    ) -> RenderResult:
        """
        Execute a prepared production timeline through FFmpeg.

        The supplied timelines remain authoritative. This method does
        not mutate creative directives or regenerate any upstream work.

        cancellation_check is optional (Post-Script-Approval
        Production Plan, Phase 14) and forwarded straight through to
        FFmpegExecutionService.execute(), which already supports
        cooperative cancellation - omitting it reproduces this
        method's exact prior behavior.

        FFmpeg writes to a staged path alongside the requested output
        file and this method promotes it to the final path only after
        a genuine success, so a crashed, cancelled, or rejected render
        never leaves a partial or corrupt file at the requested output
        path (Phase 14: "write staged output then safely promote to
        final path").

        transition_duration_seconds should be the same value the
        caller resolved and gave to VoicePipelineStage for this same
        job (see RenderWorkflowStageFactory.build()) - it exists here
        only to undo, at chunk-boundary time, the exact over-correction
        VoicePipelineStage's crossfade-aware voice positioning applies
        at a scene boundary that turns out to become a chunk split (a
        hard cut, not a real crossfade) rather than a real transition;
        see _slice_for_scenes for the full real-world finding. Omitting
        it (the default, 0.0) reproduces this method's exact prior
        behavior and is correct whenever the render never needs
        chunking, or the genre has no configured transition duration.

        letterbox_enabled (REQ-3, cinematic letterboxing) should be
        the caller's own already-resolved value (genre default + real
        per-project override - see VideoJob.letterbox_enabled's own
        docstring). Omitting it (the default, False) reproduces this
        method's exact prior behavior.

        include_subtitles - the caller's own real per-project
        VideoJob.subtitles_enabled toggle. Omitting it (the default,
        True) reproduces this method's exact prior behavior - every
        real render up to this point always burned subtitles in
        unconditionally. False reuses the exact same
        RenderGraphBuilderService/FilterGraphBuilderService relaxation
        REQ-00 Stage 1's render_video_only() already proved (skips
        SUBTITLE node construction entirely) - this is the first
        caller to expose it as a real per-project choice rather than
        an all-or-nothing Stage 1/Stage 2 split.

        audio_selection_is_intentional defaults to False, reproducing
        this method's exact prior strict behavior - see
        MasterEditPlan.audio_selection_is_intentional's own docstring.
        A caller that has already applied a real, deliberate mux-time
        filter (RenderPipelineStage, REQ-13) passes True.
        """

        duration_seconds = video_timeline.calculate_duration()

        if duration_seconds <= 0.0:
            raise ValueError(
                "Production rendering requires " "positive video duration."
            )

        if not voice_blueprints:
            raise ValueError(
                "Production rendering requires " "resolved voice blueprints."
            )

        target_output_file = self._resolve_output_file(output_file)

        effective_ffmpeg_config = self._with_bounded_keyframe_interval(
            self._ffmpeg_config,
            frame_rate=video_timeline.frame_rate,
        )

        resolved_config = self._ffmpeg_capability_service.resolve(
            effective_ffmpeg_config
        )

        command_plan, master_plan, warnings, staging_output_file = (
            self._build_command_plan(
                video_timeline=video_timeline,
                audio_timeline=audio_timeline,
                voice_blueprints=voice_blueprints,
                target_output_file=target_output_file,
                resolved_config=resolved_config,
                transition_duration_seconds=transition_duration_seconds,
                letterbox_enabled=letterbox_enabled,
                include_subtitles=include_subtitles,
                audio_selection_is_intentional=audio_selection_is_intentional,
            )
        )

        full_command_length = self._assembled_command_length(command_plan)

        if full_command_length is None or full_command_length <= (
            self._SAFE_COMMAND_LINE_LENGTH
        ):
            # Real-world finding, 2026-09-18: this single-command path
            # never ran the real-boundary audio correction
            # _slice_for_scenes already applies per-chunk - confirmed
            # on a real, single-chunk (never touched the chunked code
            # path at all) render: its video stream measured 66.27s
            # while its audio measured 67.92s, a ~1.66s tail of
            # trailing music/SFX past the real, crossfade-shortened
            # end of the video - the exact same class of bug the
            # chunked path's real_chunk_start/real_chunk_end already
            # fixes, just never applied here because chunking never
            # happens for a short enough video. Treating the whole
            # video as a single chunk (chunk_index=0, every scene
            # mapped to that one chunk) and running it through the
            # same, already-proven _slice_for_scenes reuses that fix
            # instead of duplicating it - every real audio track gets
            # clipped to the video's real length regardless of
            # whether chunking ever happens. Known limitation: this
            # assumes one uniform transition_duration_seconds across
            # every scene boundary, same as every other fix that
            # relies on this parameter - a per-scene transition
            # override that changes an individual boundary's own
            # duration or type is not accounted for.
            if transition_duration_seconds > 0.0:
                scene_numbers = {
                    item.scene_number for item in video_timeline.items if item.enabled
                }

                if scene_numbers:
                    video_timeline, audio_timeline, voice_blueprints = (
                        self._slice_for_scenes(
                            video_timeline=video_timeline,
                            audio_timeline=audio_timeline,
                            voice_blueprints=voice_blueprints,
                            scene_numbers=scene_numbers,
                            chunk_index=0,
                            transition_duration_seconds=(transition_duration_seconds),
                            scene_chunk_indices=dict.fromkeys(scene_numbers, 0),
                        )
                    )

                    duration_seconds = video_timeline.calculate_duration()

                    command_plan, master_plan, warnings, staging_output_file = (
                        self._build_command_plan(
                            video_timeline=video_timeline,
                            audio_timeline=audio_timeline,
                            voice_blueprints=voice_blueprints,
                            target_output_file=target_output_file,
                            resolved_config=resolved_config,
                            transition_duration_seconds=(transition_duration_seconds),
                            letterbox_enabled=letterbox_enabled,
                            include_subtitles=include_subtitles,
                            audio_selection_is_intentional=(
                                audio_selection_is_intentional
                            ),
                        )
                    )

            return self._execute_command_plan(
                command_plan=command_plan,
                master_plan=master_plan,
                warnings=warnings,
                resolved_config=resolved_config,
                duration_seconds=duration_seconds,
                staging_output_file=staging_output_file,
                target_output_file=target_output_file,
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )

        return self._render_chunked(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            voice_blueprints=voice_blueprints,
            target_output_file=target_output_file,
            resolved_config=resolved_config,
            full_command_length=full_command_length,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
            transition_duration_seconds=transition_duration_seconds,
            letterbox_enabled=letterbox_enabled,
            include_subtitles=include_subtitles,
            audio_selection_is_intentional=audio_selection_is_intentional,
        )

    def render_video_only(
        self,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        output_file: str | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
        transition_duration_seconds: float = 0.0,
        letterbox_enabled: bool = False,
        audio_selection_is_intentional: bool = False,
    ) -> RenderResult:
        """
        REQ-00 Stage 1: render scenes/crossfades/transitions/color-
        grade/grain/vignette only - no audio, no subtitles muxed in.
        Narration/music/SFX still generate normally elsewhere in the
        pipeline (Stage 2 mixes them onto this method's own output
        later, via a separate service - not built yet); this method
        never touches them.

        audio_timeline/voice_blueprints are still required, same as
        render() - MasterEditPlanService's duration-compatibility
        validation and SubtitleExecutionService's own plan-readiness
        check both still run unchanged (only the render graph's node
        construction skips AUDIO_TRACK/AUDIO_MIX/SUBTITLE), so this
        method's input contract deliberately matches render() exactly
        rather than inventing a narrower one.

        transition_duration_seconds should be the same value the
        caller resolved for this job (same meaning as render()'s own
        parameter of the same name) - used here only to compute each
        scene's real, crossfade-corrected final position (see
        _compute_real_scene_timings/SceneRenderTiming), never forwarded
        to command-plan construction, since subtitle timing (the only
        other consumer of this value in _build_command_plan) is
        irrelevant when include_subtitles=False.

        Deliberately does not support command-line-length-driven
        chunking yet (see render()'s own _render_chunked) - raises
        rather than silently producing a truncated or malformed
        command for a video long/complex enough to need it. Chunked
        video-only rendering is real follow-up work, not done here.

        letterbox_enabled (REQ-3) is the caller's own already-resolved
        value, same meaning as render()'s own parameter of the same
        name.

        audio_selection_is_intentional defaults to False, matching
        render()'s own parameter of the same name - see MasterEditPlan.
        audio_selection_is_intentional's own docstring. Today's one
        real caller (RenderPipelineStage._execute_staged_render())
        already passes this method the job's real, unfiltered audio
        timeline (this method's own render graph never builds audio
        nodes regardless, per include_audio=False below), so it does
        not need to pass True - kept here for API symmetry with
        render() and any future caller that might.
        """

        duration_seconds = video_timeline.calculate_duration()

        if duration_seconds <= 0.0:
            raise ValueError(
                "Production rendering requires " "positive video duration."
            )

        if not voice_blueprints:
            raise ValueError(
                "Production rendering requires " "resolved voice blueprints."
            )

        target_output_file = self._resolve_output_file(output_file)

        effective_ffmpeg_config = self._with_bounded_keyframe_interval(
            self._ffmpeg_config,
            frame_rate=video_timeline.frame_rate,
        )

        resolved_config = self._ffmpeg_capability_service.resolve(
            effective_ffmpeg_config
        )

        command_plan, master_plan, warnings, staging_output_file = (
            self._build_command_plan(
                video_timeline=video_timeline,
                audio_timeline=audio_timeline,
                voice_blueprints=voice_blueprints,
                target_output_file=target_output_file,
                resolved_config=resolved_config,
                include_audio=False,
                include_subtitles=False,
                letterbox_enabled=letterbox_enabled,
                audio_selection_is_intentional=audio_selection_is_intentional,
            )
        )

        full_command_length = self._assembled_command_length(command_plan)

        if full_command_length is not None and full_command_length > (
            self._SAFE_COMMAND_LINE_LENGTH
        ):
            raise NotImplementedError(
                "This video is long/complex enough to need chunked "
                "rendering, which REQ-00 Stage 1's video-only render "
                "does not support yet - render() (the existing "
                "composite path) still handles this case."
            )

        scene_timings = self._compute_real_scene_timings(
            video_timeline=video_timeline,
            transition_duration_seconds=transition_duration_seconds,
        )

        return self._execute_command_plan(
            command_plan=command_plan,
            master_plan=master_plan,
            warnings=warnings,
            resolved_config=resolved_config,
            duration_seconds=duration_seconds,
            staging_output_file=staging_output_file,
            target_output_file=target_output_file,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
            scene_timings=scene_timings,
        )

    def render_top10_countdown(
        self,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        rank_by_scene_number: dict[int, int],
        rank_card_results: dict[int, RenderResult],
        output_file: str | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
        transition_duration_seconds: float = 0.0,
        letterbox_enabled: bool = False,
        include_subtitles: bool = True,
        audio_selection_is_intentional: bool = False,
    ) -> RenderResult:
        """
        REQ-12 (top10 countdown rank cards): render the main timeline
        as real, independent scene-range segments split at each rank's
        own first scene, splice each rank's standalone card
        (TopTenRankCardRenderService's own already-rendered output -
        picture and "Number N"/whoosh audio already baked into one
        real file) immediately before that rank's segment, then
        losslessly join every segment into one final file - a real
        hard cut at every rank-card boundary, never a crossfade,
        sidestepping this codebase's own documented crossfade-
        arithmetic bug history for a boundary kind
        VoicePipelineStage's positioning was never told about.

        Deliberately reuses three already-proven primitives rather
        than inventing new timing math: _slice_for_scenes (the same
        real, crossfade-corrected scene-range slicing _render_chunked
        already relies on for oversized-command chunking, just driven
        by rank boundaries here instead of command-length ones),
        _build_command_plan/_execute_command_plan (identical to every
        other render path), and _concat_chunks (already re-decodes/
        re-encodes rather than stream-copying, so it tolerates the
        rank cards' own, independently-produced encoder state exactly
        the way it already tolerates one chunked render's own
        independently-produced segments).

        rank_by_scene_number maps a ranked scene's own scene_number to
        its rank (1-10) - typically
        TopTenRankAssignmentResult.rank_by_scene_number(). A scene
        absent from this mapping is treated as unranked (the real
        intro/hook footage that precedes rank 10) and gets no card
        inserted before it.

        rank_card_results maps rank -> that rank's own real,
        already-executed TopTenRankCardRenderService.build() result -
        every rank actually referenced by rank_by_scene_number must
        have a successful entry here, or this method raises rather
        than silently rendering without that rank's card.
        """

        duration_seconds = video_timeline.calculate_duration()

        if duration_seconds <= 0.0:
            raise ValueError(
                "Production rendering requires " "positive video duration."
            )

        if not voice_blueprints:
            raise ValueError(
                "Production rendering requires " "resolved voice blueprints."
            )

        scene_numbers = sorted(
            {item.scene_number for item in video_timeline.items if item.enabled}
        )

        if not scene_numbers:
            raise ValueError(
                "Top10 countdown rendering requires " "at least one enabled scene."
            )

        rank_groups = self._group_scenes_by_rank(
            scene_numbers=scene_numbers,
            rank_by_scene_number=rank_by_scene_number,
        )

        used_ranks = sorted(
            {rank for rank, _group_scene_numbers in rank_groups if rank is not None}
        )

        if not used_ranks:
            raise ValueError(
                "Top10 countdown rendering requires " "at least one ranked scene."
            )

        missing_ranks = [
            rank
            for rank in used_ranks
            if not (
                (result := rank_card_results.get(rank)) is not None
                and result.success
                and result.output_file
            )
        ]

        if missing_ranks:
            missing_text = ", ".join(str(rank) for rank in missing_ranks)

            raise ValueError(
                "Top10 countdown rendering is missing a real, "
                f"successful rank card for rank(s): {missing_text}."
            )

        target_output_file = self._resolve_output_file(output_file)

        effective_ffmpeg_config = self._with_bounded_keyframe_interval(
            self._ffmpeg_config,
            frame_rate=video_timeline.frame_rate,
        )

        resolved_config = self._ffmpeg_capability_service.resolve(
            effective_ffmpeg_config
        )

        scene_chunk_indices = {
            scene_number: group_index
            for group_index, (_rank, group_scene_numbers) in enumerate(rank_groups)
            for scene_number in group_scene_numbers
        }

        target_path = Path(target_output_file)

        segment_output_files: list[str] = []
        chunk_files: list[str] = []
        aggregated_warnings: list[str] = []
        total_render_time_seconds = 0.0

        for group_index, (rank, group_scene_numbers) in enumerate(rank_groups):
            group_video_timeline, group_audio_timeline, group_voice_blueprints = (
                self._slice_for_scenes(
                    video_timeline=video_timeline,
                    audio_timeline=audio_timeline,
                    voice_blueprints=voice_blueprints,
                    scene_numbers=set(group_scene_numbers),
                    chunk_index=group_index,
                    transition_duration_seconds=transition_duration_seconds,
                    scene_chunk_indices=scene_chunk_indices,
                )
            )

            segment_output_file = str(
                target_path.with_name(
                    f"{target_path.stem}.rankchunk{group_index:03d}"
                    f"{target_path.suffix}"
                )
            )

            command_plan, master_plan, warnings, staging_output_file = (
                self._build_command_plan(
                    video_timeline=group_video_timeline,
                    audio_timeline=group_audio_timeline,
                    voice_blueprints=group_voice_blueprints,
                    target_output_file=segment_output_file,
                    resolved_config=resolved_config,
                    include_timeline_in=(group_index == 0),
                    include_timeline_out=(group_index == len(rank_groups) - 1),
                    transition_duration_seconds=transition_duration_seconds,
                    letterbox_enabled=letterbox_enabled,
                    include_subtitles=include_subtitles,
                    audio_selection_is_intentional=audio_selection_is_intentional,
                )
            )

            segment_result = self._execute_command_plan(
                command_plan=command_plan,
                master_plan=master_plan,
                warnings=warnings,
                resolved_config=resolved_config,
                duration_seconds=group_video_timeline.calculate_duration(),
                staging_output_file=staging_output_file,
                target_output_file=segment_output_file,
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )

            if not segment_result.success:
                self._cleanup_chunk_files(segment_output_files)

                return segment_result

            segment_output_files.append(
                segment_result.output_file or segment_output_file
            )

            aggregated_warnings.extend(segment_result.warnings)

            total_render_time_seconds += segment_result.render_time_seconds

            if rank is not None:
                chunk_files.append(str(rank_card_results[rank].output_file))

            chunk_files.append(segment_result.output_file or segment_output_file)

        total_duration_seconds = duration_seconds + sum(
            float(rank_card_results[rank].duration_seconds) for rank in used_ranks
        )

        concat_result = self._concat_chunks(
            chunk_files=chunk_files,
            target_output_file=target_output_file,
            total_duration_seconds=total_duration_seconds,
            resolved_config=resolved_config,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )

        self._cleanup_chunk_files(segment_output_files)

        if not concat_result.success:
            return concat_result

        combined_warnings = self._unique_warnings(
            [
                *aggregated_warnings,
                *concat_result.warnings,
                "Render was split at rank-card boundaries and "
                f"{len(used_ranks)} countdown card(s) were spliced in "
                "as real hard cuts.",
            ]
        )

        return concat_result.model_copy(
            update={
                "render_time_seconds": (
                    total_render_time_seconds + concat_result.render_time_seconds
                ),
                "duration_seconds": int(total_duration_seconds),
                "warnings": combined_warnings,
            }
        )

    @staticmethod
    def _group_scenes_by_rank(
        *,
        scene_numbers: list[int],
        rank_by_scene_number: dict[int, int],
    ) -> list[tuple[int | None, list[int]]]:
        """
        Split ordered scene numbers into contiguous runs sharing the
        same rank (or no rank at all).

        A rank's real coverage is always a contiguous block of the
        script (TopTenRankAssignmentService assigns one rank to one
        contiguous group of scenes), so this never needs to merge two
        separated runs of the same rank back together.
        """

        groups: list[tuple[int | None, list[int]]] = []

        for scene_number in scene_numbers:
            rank = rank_by_scene_number.get(scene_number)

            if groups and groups[-1][0] == rank:
                groups[-1][1].append(scene_number)
            else:
                groups.append((rank, [scene_number]))

        return groups

    @classmethod
    def _with_bounded_keyframe_interval(
        cls,
        config: FFmpegConfig,
        *,
        frame_rate: int,
    ) -> FFmpegConfig:
        """
        Return config with a hard keyframe-interval cap appended,
        unless the caller already customized -g/-keyint_min
        themselves (an explicit override always wins).
        """

        already_customized = any(
            arg in {"-g", "-keyint_min"} for arg in config.extra_video_args
        )

        if already_customized or not isinstance(frame_rate, int) or frame_rate <= 0:
            return config

        interval_frames = max(1, round(frame_rate * cls._MAX_KEYFRAME_INTERVAL_SECONDS))

        return config.model_copy(
            update={
                "extra_video_args": [
                    *config.extra_video_args,
                    "-g",
                    str(interval_frames),
                    "-keyint_min",
                    str(interval_frames),
                ],
            }
        )

    def _build_command_plan(
        self,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        target_output_file: str,
        resolved_config: FFmpegResolvedConfig,
        include_timeline_in: bool = True,
        include_timeline_out: bool = True,
        transition_duration_seconds: float = 0.0,
        include_audio: bool = True,
        include_subtitles: bool = True,
        letterbox_enabled: bool = False,
        audio_selection_is_intentional: bool = False,
    ) -> tuple[FFmpegCommandPlan, MasterEditPlan, list[str], str]:
        """
        Build the deterministic FFmpeg command for one timeline pair
        without executing it.

        Shared by the single-pass render path and every chunk of a
        chunked render, so the plan-building logic (master plan,
        transition/effect/subtitle/camera/animation plans, render
        graph, filter graph, command plan) exists in exactly one
        place.

        transition_duration_seconds is forwarded to
        SubtitleExecutionService.build_plan() - see that method's own
        docstring for why subtitle timing needs it too, not just
        audio: a real crossfade blends two scenes' full frames
        (subtitles already burned in) together for that many seconds
        at every internal boundary.

        include_audio/include_subtitles default to True, reproducing
        this method's exact prior behavior. REQ-00 Stage 1 (video-only
        render, see render_video_only()) passes both False - the
        caller still supplies a real audio_timeline/voice_blueprints
        (master_plan/subtitle_plan construction and duration-
        compatibility validation are unchanged either way), only the
        render graph's own node construction skips AUDIO_TRACK/
        AUDIO_MIX/SUBTITLE nodes.

        audio_selection_is_intentional defaults to False, reproducing
        this method's exact prior strict behavior. REQ-13 real gap,
        found and fixed 2026-09-24: a caller (RenderPipelineStage) that
        has already applied filter_audio_timeline_for_mux() - a real,
        deliberate selection of which generated tracks actually reach
        THIS render, not an incomplete one - passes True so
        MasterEditPlan's own render-readiness computation stops
        treating the resulting reduced/empty audio_timeline as "not
        actually ready yet." See MasterEditPlan.audio_selection_is_
        intentional's own docstring for the full reasoning.
        """

        staging_output_file = self._staging_output_file(target_output_file)

        master_plan = self._master_edit_plan_service.build(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            audio_selection_is_intentional=audio_selection_is_intentional,
        )

        self._master_edit_plan_service.validate_render_ready(
            master_plan,
            refresh_first=True,
        )

        transition_plan = self._transition_execution_service.build_plan(
            video_timeline,
            track_index=0,
            include_timeline_in=include_timeline_in,
            include_timeline_out=include_timeline_out,
            validate_timeline=True,
            mark_ready=True,
        )

        effect_plan = self._effect_execution_service.build_plan(
            video_timeline,
            track_index=None,
            validate_timeline=True,
            mark_ready=True,
        )

        subtitle_plan = self._subtitle_execution_service.build_plan(
            video_timeline,
            voice_blueprints=voice_blueprints,
            mark_ready=True,
            transition_duration_seconds=transition_duration_seconds,
        )

        camera_plan = self._camera_execution_service.build_plan(
            video_timeline,
            track_index=None,
            validate_timeline=True,
            include_static=True,
            mark_ready=True,
        )

        animation_plan = self._animation_execution_service.build_plan(
            video_timeline,
            track_index=None,
            validate_timeline=True,
            mark_ready=True,
        )

        render_graph = self._render_graph_builder_service.build(
            master_plan=master_plan,
            transition_plan=transition_plan,
            effect_plan=effect_plan,
            subtitle_plan=subtitle_plan,
            camera_plan=camera_plan,
            animation_plan=animation_plan,
            mark_ready=True,
            include_audio=include_audio,
            include_subtitles=include_subtitles,
            letterbox_enabled=letterbox_enabled,
        )

        filter_graph = self._filter_graph_builder_service.build(
            render_graph=render_graph,
            resolved_config=resolved_config,
        )

        command_plan = self._ffmpeg_command_builder_service.build(
            render_graph=render_graph,
            filter_graph=filter_graph,
            resolved_config=resolved_config,
            output_file=staging_output_file,
        )

        warnings = self._unique_warnings(
            [
                *master_plan.warnings,
                *render_graph.warnings,
                *resolved_config.warnings,
            ]
        )

        return command_plan, master_plan, warnings, staging_output_file

    def _execute_command_plan(
        self,
        *,
        command_plan: FFmpegCommandPlan,
        master_plan: MasterEditPlan,
        warnings: list[str],
        resolved_config: FFmpegResolvedConfig,
        duration_seconds: float,
        staging_output_file: str,
        target_output_file: str,
        progress_callback: ProgressCallback | None,
        cancellation_check: CancellationCheck | None,
        scene_timings: list[SceneRenderTiming] | None = None,
    ) -> RenderResult:
        """
        Execute one already-built FFmpeg command plan to completion.

        scene_timings defaults to None (empty on the returned
        RenderResult) - only render_video_only() currently computes
        and passes real timings through; every other caller is
        unaffected.
        """

        self._master_edit_plan_service.mark_rendering(master_plan)

        try:
            execution_result = self._ffmpeg_execution_service.execute(
                command_plan,
                total_duration_seconds=(duration_seconds),
                timeout_seconds=(resolved_config.config.timeout_seconds),
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )
        except Exception as error:
            self._cleanup_staging_file(staging_output_file)

            self._master_edit_plan_service.mark_failed(
                master_plan,
                error_message=str(error),
                failure_metadata={
                    "renderer": "ffmpeg",
                    "output_file": (target_output_file),
                },
            )

            raise

        ffmpeg_command = (
            list(execution_result.ffmpeg_command)
            if isinstance(execution_result.ffmpeg_command, list)
            else []
        )

        ffmpeg_version = self._capability_string(resolved_config, "ffmpeg_version")

        selected_video_codec = self._capability_string(
            resolved_config, "selected_video_codec"
        )

        selected_audio_codec = self._capability_string(
            resolved_config, "selected_audio_codec"
        )

        selected_hardware_acceleration = self._capability_string(
            resolved_config, "selected_hardware_acceleration"
        )

        if execution_result.success:
            completed_staging_file = execution_result.output_file

            if completed_staging_file is None:
                raise RuntimeError(
                    "Successful FFmpeg execution " "did not provide an output file."
                )

            promoted_output_file = self._promote_staged_output(
                staging_output_file=completed_staging_file,
                target_output_file=target_output_file,
            )

            self._master_edit_plan_service.mark_completed(
                master_plan,
                output_file=promoted_output_file,
            )

            return RenderResult(
                success=True,
                output_file=promoted_output_file,
                render_engine="ffmpeg",
                render_time_seconds=(execution_result.elapsed_seconds),
                duration_seconds=int(duration_seconds),
                status=RenderStatus.COMPLETED,
                warnings=warnings,
                error_message=None,
                ffmpeg_command=ffmpeg_command,
                exit_code=execution_result.exit_code,
                ffmpeg_version=ffmpeg_version,
                selected_video_codec=selected_video_codec,
                selected_audio_codec=selected_audio_codec,
                selected_hardware_acceleration=(selected_hardware_acceleration),
                scene_timings=list(scene_timings or []),
            )

        error_message = execution_result.error_message or (
            "FFmpeg execution returned " "an unsuccessful result."
        )

        self._cleanup_staging_file(staging_output_file)

        execution_metadata = execution_result.metadata

        failure_stage = (
            execution_metadata.get("failure_stage")
            if isinstance(execution_metadata, dict)
            else None
        )

        failure_category = classify_render_failure(failure_stage)

        self._master_edit_plan_service.mark_failed(
            master_plan,
            error_message=error_message,
            failure_metadata={
                "renderer": "ffmpeg",
                "output_file": (target_output_file),
                "exit_code": (execution_result.exit_code),
                "execution_status": (execution_result.status.value),
            },
        )

        return RenderResult(
            success=False,
            output_file=None,
            render_engine="ffmpeg",
            render_time_seconds=(execution_result.elapsed_seconds),
            duration_seconds=int(duration_seconds),
            status=RenderStatus.FAILED,
            warnings=warnings,
            error_message=error_message,
            ffmpeg_command=ffmpeg_command,
            exit_code=execution_result.exit_code,
            failure_category=failure_category,
            ffmpeg_version=ffmpeg_version,
            selected_video_codec=selected_video_codec,
            selected_audio_codec=selected_audio_codec,
            selected_hardware_acceleration=(selected_hardware_acceleration),
        )

    @staticmethod
    def _assembled_command_length(
        command_plan: FFmpegCommandPlan,
    ) -> int | None:
        """
        Return the length of one command plan's assembled command
        line, or None when it cannot be measured.

        subprocess.list2cmdline reproduces exactly how Python's own
        subprocess module assembles a Windows command line, so this
        is the same length CreateProcess would actually see. A test
        double that does not expose a real list of strings for
        `.command` returns None rather than raising.
        """

        try:
            return len(subprocess.list2cmdline(list(command_plan.command)))
        except TypeError:
            return None

    @classmethod
    def _command_plan_fits_os_limit(
        cls,
        command_plan: FFmpegCommandPlan,
    ) -> bool:
        """
        Return whether one command plan's assembled command line
        stays within the operating system's real length limit.

        A command plan whose length cannot be measured (a loose test
        double) is treated as fitting, reproducing this method's
        exact prior (unconditional single-pass) behavior for it.
        """

        assembled_length = cls._assembled_command_length(command_plan)

        if assembled_length is None:
            return True

        return assembled_length <= cls._SAFE_COMMAND_LINE_LENGTH

    def _render_chunked(
        self,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        target_output_file: str,
        resolved_config: FFmpegResolvedConfig,
        full_command_length: int,
        progress_callback: ProgressCallback | None,
        cancellation_check: CancellationCheck | None,
        transition_duration_seconds: float = 0.0,
        letterbox_enabled: bool = False,
        include_subtitles: bool = True,
        audio_selection_is_intentional: bool = False,
    ) -> RenderResult:
        """
        Render a timeline too large for one FFmpeg command line as
        several smaller FFmpeg passes, then losslessly concatenate
        them.

        Each chunk reuses the exact same plan-building and execution
        path as a normal render (_build_command_plan /
        _execute_command_plan) - only the video/audio timeline given
        to it is a scene-bounded slice, re-based to start at zero.

        letterbox_enabled (REQ-3) is applied identically to every
        chunk (same crop/pad params, same output resolution) so the
        concatenated chunks stay visually consistent at their seams.
        """

        scene_numbers = sorted(
            {item.scene_number for item in video_timeline.items if item.enabled}
        )

        total_duration_seconds = video_timeline.calculate_duration()

        if len(scene_numbers) <= 1:
            command_plan, master_plan, warnings, staging_output_file = (
                self._build_command_plan(
                    video_timeline=video_timeline,
                    audio_timeline=audio_timeline,
                    voice_blueprints=voice_blueprints,
                    target_output_file=target_output_file,
                    resolved_config=resolved_config,
                    transition_duration_seconds=transition_duration_seconds,
                    letterbox_enabled=letterbox_enabled,
                    include_subtitles=include_subtitles,
                    audio_selection_is_intentional=audio_selection_is_intentional,
                )
            )

            return self._execute_command_plan(
                command_plan=command_plan,
                master_plan=master_plan,
                warnings=warnings,
                resolved_config=resolved_config,
                duration_seconds=total_duration_seconds,
                staging_output_file=staging_output_file,
                target_output_file=target_output_file,
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )

        chunk_count = self._determine_chunk_count(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            voice_blueprints=voice_blueprints,
            scene_numbers=scene_numbers,
            resolved_config=resolved_config,
            full_command_length=full_command_length,
            transition_duration_seconds=transition_duration_seconds,
            letterbox_enabled=letterbox_enabled,
            include_subtitles=include_subtitles,
            audio_selection_is_intentional=audio_selection_is_intentional,
        )

        scene_groups = self._split_scene_numbers(scene_numbers, chunk_count)

        scene_chunk_indices = self._scene_chunk_indices(scene_groups)

        target_path = Path(target_output_file)

        chunk_output_files: list[str] = []
        aggregated_warnings: list[str] = []
        total_render_time_seconds = 0.0

        for index, group in enumerate(scene_groups):
            chunk_video_timeline, chunk_audio_timeline, chunk_voice_blueprints = (
                self._slice_for_scenes(
                    video_timeline=video_timeline,
                    audio_timeline=audio_timeline,
                    voice_blueprints=voice_blueprints,
                    scene_numbers=group,
                    chunk_index=index,
                    transition_duration_seconds=transition_duration_seconds,
                    scene_chunk_indices=scene_chunk_indices,
                )
            )

            chunk_output_file = str(
                target_path.with_name(
                    f"{target_path.stem}.chunk{index:03d}{target_path.suffix}"
                )
            )

            command_plan, master_plan, warnings, staging_output_file = (
                self._build_command_plan(
                    video_timeline=chunk_video_timeline,
                    audio_timeline=chunk_audio_timeline,
                    voice_blueprints=chunk_voice_blueprints,
                    target_output_file=chunk_output_file,
                    resolved_config=resolved_config,
                    include_timeline_in=(index == 0),
                    include_timeline_out=(index == len(scene_groups) - 1),
                    transition_duration_seconds=transition_duration_seconds,
                    letterbox_enabled=letterbox_enabled,
                    include_subtitles=include_subtitles,
                    audio_selection_is_intentional=audio_selection_is_intentional,
                )
            )

            chunk_result = self._execute_command_plan(
                command_plan=command_plan,
                master_plan=master_plan,
                warnings=warnings,
                resolved_config=resolved_config,
                duration_seconds=chunk_video_timeline.calculate_duration(),
                staging_output_file=staging_output_file,
                target_output_file=chunk_output_file,
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )

            if not chunk_result.success:
                self._cleanup_chunk_files(chunk_output_files)

                return chunk_result

            chunk_output_files.append(chunk_result.output_file or chunk_output_file)

            aggregated_warnings.extend(chunk_result.warnings)

            total_render_time_seconds += chunk_result.render_time_seconds

        concat_result = self._concat_chunks(
            chunk_files=chunk_output_files,
            target_output_file=target_output_file,
            total_duration_seconds=total_duration_seconds,
            resolved_config=resolved_config,
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )

        self._cleanup_chunk_files(chunk_output_files)

        if not concat_result.success:
            return concat_result

        combined_warnings = self._unique_warnings(
            [
                *aggregated_warnings,
                *concat_result.warnings,
                f"Render was split into {len(scene_groups)} chunks "
                "and concatenated because the full FFmpeg command "
                "exceeded the operating system's command-line "
                "length limit.",
            ]
        )

        return concat_result.model_copy(
            update={
                "render_time_seconds": (
                    total_render_time_seconds + concat_result.render_time_seconds
                ),
                "duration_seconds": int(total_duration_seconds),
                "warnings": combined_warnings,
            }
        )

    def _determine_chunk_count(
        self,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        scene_numbers: list[int],
        resolved_config: FFmpegResolvedConfig,
        full_command_length: int,
        transition_duration_seconds: float = 0.0,
        letterbox_enabled: bool = False,
        include_subtitles: bool = True,
        audio_selection_is_intentional: bool = False,
    ) -> int:
        """
        Return the smallest chunk count whose every chunk's own
        command line fits the safe length limit, capped at
        _MAXIMUM_RENDER_CHUNKS.

        Command length scales roughly linearly with scene count, so
        splitting the unchunked command's own length by the safe
        limit gives a close starting estimate instead of scanning
        every chunk count from 2 upward - important once
        _MAXIMUM_RENDER_CHUNKS is large, since scanning from 2 would
        otherwise rebuild every candidate's full plan for every
        chunk count tried (quadratic in the chunk count) before
        reaching the right answer. More chunks only ever makes each
        chunk's command shorter, so scanning upward from the estimate
        (never below it) cannot skip past the true answer.
        """

        maximum_chunks = min(len(scene_numbers), self._MAXIMUM_RENDER_CHUNKS)

        estimated_chunk_count = math.ceil(
            full_command_length / self._SAFE_COMMAND_LINE_LENGTH
        )

        starting_chunk_count = max(2, min(estimated_chunk_count, maximum_chunks))

        for chunk_count in range(starting_chunk_count, maximum_chunks + 1):
            groups = self._split_scene_numbers(scene_numbers, chunk_count)

            scene_chunk_indices = self._scene_chunk_indices(groups)

            if all(
                self._chunk_command_fits(
                    video_timeline=video_timeline,
                    audio_timeline=audio_timeline,
                    voice_blueprints=voice_blueprints,
                    scene_numbers=group,
                    resolved_config=resolved_config,
                    chunk_index=group_index,
                    transition_duration_seconds=transition_duration_seconds,
                    scene_chunk_indices=scene_chunk_indices,
                    letterbox_enabled=letterbox_enabled,
                    include_subtitles=include_subtitles,
                    audio_selection_is_intentional=audio_selection_is_intentional,
                )
                for group_index, group in enumerate(groups)
            ):
                return chunk_count

        return maximum_chunks

    def _chunk_command_fits(
        self,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        scene_numbers: set[int],
        resolved_config: FFmpegResolvedConfig,
        chunk_index: int = 0,
        transition_duration_seconds: float = 0.0,
        scene_chunk_indices: dict[int, int] | None = None,
        letterbox_enabled: bool = False,
        include_subtitles: bool = True,
        audio_selection_is_intentional: bool = False,
    ) -> bool:
        """Build one candidate chunk's command plan just to measure it."""

        chunk_video_timeline, chunk_audio_timeline, chunk_voice_blueprints = (
            self._slice_for_scenes(
                video_timeline=video_timeline,
                audio_timeline=audio_timeline,
                voice_blueprints=voice_blueprints,
                scene_numbers=scene_numbers,
                chunk_index=chunk_index,
                transition_duration_seconds=transition_duration_seconds,
                scene_chunk_indices=scene_chunk_indices,
            )
        )

        command_plan, _master_plan, _warnings, _staging_output_file = (
            self._build_command_plan(
                video_timeline=chunk_video_timeline,
                audio_timeline=chunk_audio_timeline,
                voice_blueprints=chunk_voice_blueprints,
                target_output_file=self.DEFAULT_OUTPUT_FILE,
                resolved_config=resolved_config,
                transition_duration_seconds=transition_duration_seconds,
                letterbox_enabled=letterbox_enabled,
                include_subtitles=include_subtitles,
                audio_selection_is_intentional=audio_selection_is_intentional,
            )
        )

        return self._command_plan_fits_os_limit(command_plan)

    @staticmethod
    def _split_scene_numbers(
        scene_numbers: list[int],
        chunk_count: int,
    ) -> list[set[int]]:
        """Split ordered scene numbers into contiguous, ordered groups."""

        group_size = math.ceil(len(scene_numbers) / chunk_count)

        return [
            set(scene_numbers[start : start + group_size])
            for start in range(0, len(scene_numbers), group_size)
        ]

    @staticmethod
    def _scene_chunk_indices(
        scene_groups: list[set[int]],
    ) -> dict[int, int]:
        """
        Map every scene number to the index of the chunk it falls in.

        See _slice_for_scenes for why this must be built once across
        the *whole* candidate grouping and reused for every chunk's
        own slice call - a track's correction depends on its own
        scene's chunk membership, not on which chunk is currently
        being sliced.
        """

        return {
            scene_number: chunk_index
            for chunk_index, group in enumerate(scene_groups)
            for scene_number in group
        }

    # Heuristic tolerance for recognizing a background-music track
    # that spans the entire original timeline (a single continuous
    # track) rather than one positioned scene-range segment among
    # several - see _slice_for_scenes. Deliberately looser than the
    # tight tolerances used for real timing validation elsewhere,
    # since this only classifies which slicing rule to apply.
    _WHOLE_TIMELINE_MUSIC_TOLERANCE_SECONDS = 1.0

    # Real-world finding, 2026-09-17: the voiceover chunk-boundary
    # correction in _slice_for_scenes chains several float additions
    # and subtractions (VoicePipelineStage's own cumulative sum, then
    # this method's own correction), which can leave a track that
    # truly ends exactly at its chunk's own boundary a few
    # femtoseconds on the wrong side of an exact equality check -
    # confirmed on the real job: scene 10's real stored position was
    # 50.599999999999994, not the clean 50.6 the math implies, and
    # after correction landed 4e-15s short of chunk 0's own boundary,
    # producing a technically nonzero but meaningless sliver instead
    # of being cleanly excluded. A track shorter than this tolerance
    # carries no real audio content at any sample rate (even 48kHz's
    # own sample period is ~2e-5s, many orders of magnitude larger)
    # and is dropped rather than handed to FFmpeg as an input.
    _MINIMUM_TRACK_OVERLAP_SECONDS = 1e-6

    @staticmethod
    def _cumulative_real_crossfade_counts(
        *,
        video_timeline: VideoTimeline,
        scene_chunk_indices: dict[int, int],
    ) -> dict[UUID, int]:
        """
        For every enabled video timeline item, the number of REAL
        crossfades (never a chunk-boundary hard cut) that occur
        strictly before that item's own start, keyed by the item's own
        id.

        Walks the whole, unchunked timeline once, in playback order.
        The boundary between two consecutive items counts as a real
        crossfade unless the two items fall in different chunks per
        scene_chunk_indices (a genuine hard cut, decided once across
        the whole job by _scene_chunk_indices - chunking only ever
        groups whole scene numbers, so two consecutive items sharing
        one scene_number - Phase 5's own split sub-clips - always fall
        in the same chunk and always count as a real crossfade).

        Replaces the old (scene_number - 1) - chunk_index arithmetic
        _slice_for_scenes used to compute this - see that method's own
        real-world-finding comment for why counting whole scene-number
        increments broke the moment one scene could contribute more
        than one timeline item.
        """

        ordered_items = sorted(
            (item for item in video_timeline.items if item.enabled),
            key=lambda item: item.start_time_seconds,
        )

        counts: dict[UUID, int] = {}
        running_count = 0

        for index, item in enumerate(ordered_items):
            counts[item.id] = running_count

            if index + 1 >= len(ordered_items):
                continue

            next_item = ordered_items[index + 1]

            this_chunk = scene_chunk_indices.get(item.scene_number, 0)
            next_chunk = scene_chunk_indices.get(next_item.scene_number, 0)

            if this_chunk == next_chunk:
                running_count += 1

        return counts

    @classmethod
    def _compute_real_scene_timings(
        cls,
        *,
        video_timeline: VideoTimeline,
        transition_duration_seconds: float,
    ) -> list[SceneRenderTiming]:
        """
        REQ-00 Stage 1: each enabled video clip's real, crossfade-
        corrected position in the rendered video-only output's own
        final timeline - see SceneRenderTiming's own docstring for why
        this exists and who consumes it.

        Reuses _cumulative_real_crossfade_counts rather than
        reimplementing the same correction a second time.
        render_video_only() never chunks (see its own docstring - a
        NotImplementedError is raised instead for a command long
        enough to need it), so every item maps to one single chunk for
        that method's own purposes - every boundary between enabled
        items is a real crossfade, none are chunk hard-cuts. Inherits
        the same documented, known limitation every other consumer of
        this correction has: one uniform transition_duration_seconds
        across every boundary, not a real per-scene override.
        """

        ordered_items = sorted(
            (item for item in video_timeline.items if item.enabled),
            key=lambda item: item.start_time_seconds,
        )

        scene_chunk_indices = {item.scene_number: 0 for item in ordered_items}

        crossfade_counts = cls._cumulative_real_crossfade_counts(
            video_timeline=video_timeline,
            scene_chunk_indices=scene_chunk_indices,
        )

        timings: list[SceneRenderTiming] = []

        for item in ordered_items:
            real_start_seconds = max(
                0.0,
                item.start_time_seconds
                - (crossfade_counts.get(item.id, 0) * transition_duration_seconds),
            )

            timings.append(
                SceneRenderTiming(
                    scene_number=item.scene_number,
                    clip_sequence_index=item.clip_sequence_index,
                    start_seconds=real_start_seconds,
                    end_seconds=(real_start_seconds + item.duration_seconds),
                )
            )

        return timings

    @classmethod
    def _slice_for_scenes(
        cls,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        scene_numbers: set[int],
        chunk_index: int = 0,
        transition_duration_seconds: float = 0.0,
        scene_chunk_indices: dict[int, int] | None = None,
    ) -> tuple[VideoTimeline, AudioTimeline, list[ResolvedVoiceBlueprint]]:
        """
        Return a self-contained, zero-based timeline slice covering
        only the given scene numbers.

        Every audio track partitions by its real overlap with this
        chunk's time range, rebased to start at zero and clipped to
        the chunk's own bounds - a track spanning a chunk boundary
        (voiceover, sound effect, or a content-aware, per-scene-range
        background-music segment - genre sound design can produce
        several of the latter, each positioned at its own scene
        range, not one continuous track) is split, each side keeping
        only its own real content. The one exception is a
        background-music track that spans the *entire original
        timeline* (the single-continuous-track path, rather than a
        positioned segment): pure overlap slicing would leave every
        chunk after the first with no music at all, so that one case
        instead gets its own per-chunk copy, looped to fill the
        chunk, relying on the same loop/atrim mechanism that already
        fills a track shorter than its timeline.

        Real-world finding, 2026-09-17: VoicePipelineStage positions
        every voiceover track assuming a real crossfade "eats"
        transition_duration_seconds at EVERY scene boundary - true for
        every boundary except the one(s) that end up as a chunk split,
        which become hard cuts in the final concatenated video (no
        crossfade actually happens there, since chunking is a decision
        VoicePipelineStage cannot see - it runs long before command
        length, and therefore chunking, is known at all). Every scene
        after a chunk boundary is therefore positioned
        transition_duration_seconds too early per boundary already
        crossed.

        Fixing only the voiceover-position side of this (below) turned
        out to be necessary but not sufficient - confirmed directly on
        a real render, twice. The first pass fixed voiceover
        positioning but the freeze persisted; rendering chunk 0 alone
        and probing its own two streams directly showed why: its real
        video stream measured 51.2s (matching this method's own
        real_chunk_end math exactly) while its audio stream measured
        56.0s - the *chunk's own nominal end*, coming entirely from
        music/SFX tracks still being tested against the nominal
        window. A chunk's own video is genuinely only ever as long as
        real_chunk_end - real_chunk_start (below), full stop,
        regardless of which track type is playing there - the
        distinction between track types is about how a track's own
        *position* needs interpreting, never about which coordinate
        space the *window* being tested against uses - that window is
        a property of the chunk's own real video, the same for every
        track type.

        Real-world finding, 2026-09-18: this method originally assumed
        only voiceover positions needed correction ("music/SFX
        positions come straight from each scene's own nominal
        VideoTimelineItem and are already correct as-is") - confirmed
        WRONG directly against a real job. SoundEffectPipelineStage and
        MusicPipelineStage both now compute their own real,
        crossfade-corrected position upstream (the same way
        VoicePipelineStage always has, for the same reason), so they
        share voice's exact same remaining chunk-boundary blind spot -
        see each stage's own docstring for the full story.

        Two corrections, applied together:

        1. Per-track position (VOICEOVER, SOUND_EFFECT, and
           BACKGROUND_MUSIC - every track type whose position is
           computed upstream in real, crossfade-corrected time): add
           back transition_duration_seconds once for every chunk
           boundary that precedes the *track's own scene* (via
           scene_chunk_indices, built once across the whole job - see
           _scene_chunk_indices), regardless of which chunk is
           currently being sliced. This recovers each track's true,
           boundary-corrected position. A track with no scene_number
           in its metadata (the legacy whole-timeline music track) is
           left uncorrected - it has no single owning scene, and its
           own start_time_seconds is always 0.0 regardless.

        2. Per-chunk window (every track type): this chunk's own
           [start, end) overlap test window must be expressed in the
           same real, crossfade-corrected coordinate space real
           voiceover positions use, not the nominal one a plain
           VideoTimelineItem boundary gives - chunk N's own video
           actually starts/ends transition_duration_seconds earlier
           per *real* crossfade that precedes it, which is every
           preceding scene boundary except the N chunk-boundaries
           themselves (those are hard cuts, not crossfades - see
           crossfades_before_start/crossfades_before_end below).
           Testing any track's position against the wrong coordinate
           space silently drops, duplicates, or - for a track that
           only exceeds the real boundary, never the nominal one -
           lets it overshoot the chunk's own real video length
           exactly the way this whole method exists to prevent.
        """

        scene_chunk_indices = scene_chunk_indices or {}

        selected_items: list[VideoTimelineItem] = sorted(
            (
                item
                for item in video_timeline.items
                if item.enabled and item.scene_number in scene_numbers
            ),
            key=lambda item: item.start_time_seconds,
        )

        if not selected_items:
            raise ValueError("Render chunk contains no timeline items.")

        chunk_start = selected_items[0].start_time_seconds

        chunk_end = max(item.end_time_seconds for item in selected_items)

        # Phase 5 (multi-clip scene splitting), real-world finding,
        # 2026-09-21: the old (first_scene_number - 1) - chunk_index /
        # (last_scene_number - 1) - chunk_index arithmetic assumed
        # exactly one crossfade per scene-number increment - true only
        # while every scene contributes exactly one VideoTimelineItem.
        # A split scene contributes several consecutive items sharing
        # one scene_number, each boundary between them a REAL
        # intra-scene seam crossfade the old formula had no way to
        # count (it only ever counted whole scene-number increments).
        # Replaced (not patched) with a precomputed, walked-once count
        # of every real crossfade preceding each item, keyed by the
        # item's own id - correct regardless of how many items one
        # scene number contributes. chunk_index itself is no longer
        # needed for this - kept as a parameter only for existing call-
        # site compatibility.
        crossfade_counts = cls._cumulative_real_crossfade_counts(
            video_timeline=video_timeline,
            scene_chunk_indices=scene_chunk_indices,
        )

        crossfades_before_start = crossfade_counts.get(selected_items[0].id, 0)

        crossfades_before_end = crossfade_counts.get(selected_items[-1].id, 0)

        real_chunk_start = chunk_start - (
            transition_duration_seconds * crossfades_before_start
        )

        real_chunk_end = chunk_end - (
            transition_duration_seconds * crossfades_before_end
        )

        real_chunk_duration = real_chunk_end - real_chunk_start

        rebased_items = [
            item.model_copy(
                update={
                    "start_time_seconds": (item.start_time_seconds - chunk_start),
                    "end_time_seconds": (item.end_time_seconds - chunk_start),
                }
            )
            for item in selected_items
        ]

        chunk_video_timeline = VideoTimeline(
            items=rebased_items,
            output_resolution=video_timeline.output_resolution,
            frame_rate=video_timeline.frame_rate,
        )

        chunk_video_timeline.calculate_duration()

        total_video_duration = video_timeline.calculate_duration()

        tolerance = cls._WHOLE_TIMELINE_MUSIC_TOLERANCE_SECONDS

        chunk_tracks: list[AudioTrack] = []

        # See this method's docstring: the overlap window is always
        # the chunk's own REAL (crossfade-corrected) boundary,
        # regardless of track type.
        #
        # Real-world finding, 2026-09-18: the per-track position
        # correction below used to be voiceover-only, on the
        # assumption that music/SFX positions came straight from each
        # scene's nominal VideoTimelineItem and needed no correction -
        # confirmed WRONG directly against a real job (SoundEffectPipelineStage
        # and MusicPipelineStage were still using item.start_time_seconds,
        # never crossfade-corrected). Both stages now compute their own
        # real, crossfade-corrected position upstream (assuming every
        # scene boundary is a real crossfade), the same way
        # VoicePipelineStage always has - which means they now share
        # voice's exact same remaining blind spot: whichever boundary
        # ends up as a chunk split is actually a hard cut, not a real
        # crossfade, so a track positioned across one is too early by
        # transition_duration_seconds per chunk boundary crossed. Every
        # stage that does this upstream real-position math needs this
        # same chunk-boundary correction, not just voice.
        window_start = real_chunk_start

        window_end = real_chunk_end

        _CHUNK_CORRECTED_TRACK_TYPES = (
            AudioTrackType.VOICEOVER,
            AudioTrackType.SOUND_EFFECT,
            AudioTrackType.BACKGROUND_MUSIC,
        )

        for track in audio_timeline.tracks:
            if track.track_type in _CHUNK_CORRECTED_TRACK_TYPES:
                track_scene_number = track.metadata.get("scene_number")

                track_chunk_index = (
                    scene_chunk_indices.get(track_scene_number, 0)
                    if track_scene_number is not None
                    else 0
                )

                effective_start = track.start_time_seconds + (
                    transition_duration_seconds * track_chunk_index
                )
            else:
                effective_start = track.start_time_seconds

            track_end = effective_start + track.duration_seconds

            spans_entire_timeline = (
                track.track_type == AudioTrackType.BACKGROUND_MUSIC
                and effective_start <= tolerance
                and track_end >= total_video_duration - tolerance
            )

            if spans_entire_timeline:
                chunk_tracks.append(
                    track.model_copy(
                        update={
                            "start_time_seconds": 0.0,
                            "duration_seconds": real_chunk_duration,
                            "loop_enabled": True,
                        }
                    )
                )

                continue

            # A track is allowed to run slightly past its own scene's
            # boundary in the full timeline (e.g. a sound-effect
            # tail, a voiceover's trailing pause, or a music segment
            # whose own real content needs to loop past its nominal
            # span) - harmless there since it just bleeds into
            # whatever comes next. Inside a chunk there is nothing
            # past the chunk's own last scene to bleed into, so only
            # the portion of the track that actually overlaps this
            # chunk is kept; a track straddling a chunk boundary is
            # split, each side independently clipped to its own
            # chunk (the same disclosed loop-restart trade-off as the
            # whole-timeline case above, just at a finer grain).
            overlap_start = max(effective_start, window_start)

            overlap_end = min(track_end, window_end)

            if overlap_end - overlap_start <= cls._MINIMUM_TRACK_OVERLAP_SECONDS:
                continue

            chunk_tracks.append(
                track.model_copy(
                    update={
                        "start_time_seconds": (overlap_start - window_start),
                        "duration_seconds": (overlap_end - overlap_start),
                    }
                )
            )

        chunk_audio_timeline = AudioTimeline(
            tracks=chunk_tracks,
            sample_rate=audio_timeline.sample_rate,
            channels=audio_timeline.channels,
        )

        chunk_audio_timeline.calculate_duration()

        chunk_voice_blueprints = [
            blueprint
            for blueprint in voice_blueprints
            if blueprint.scene_number in scene_numbers
        ]

        return chunk_video_timeline, chunk_audio_timeline, chunk_voice_blueprints

    def _concat_chunks(
        self,
        *,
        chunk_files: list[str],
        target_output_file: str,
        total_duration_seconds: float,
        resolved_config: FFmpegResolvedConfig,
        progress_callback: ProgressCallback | None,
        cancellation_check: CancellationCheck | None,
    ) -> RenderResult:
        """
        Combine already-rendered chunk files into one final output.

        Real-world finding, 2026-09-16: the previous approach used
        FFmpeg's concat DEMUXER with `-c copy` (stream copy, no
        re-encoding), which requires every segment's streams to be
        byte-identical - each chunk is produced by its own, fully
        independent FFmpeg invocation, and even nominally-matching
        encoder settings can leave small real differences (AAC
        encoder priming/padding, internal timestamp state) that the
        demuxer does not tolerate. Confirmed directly on a real render:
        the concatenated file's video played for the full intended
        duration, but its audio silently stopped at almost exactly the
        first chunk's own duration - no error reported, no warning
        surfaced, audio for every later chunk simply gone. The concat
        FILTER instead genuinely re-decodes and re-encodes every
        segment into one continuous, correct stream - slower (one more
        encode pass) but correct regardless of any encoder-state
        mismatch between chunks. This command only ever references the
        small, fixed number of already-rendered chunk files (never the
        original per-scene filter graph that required chunking in the
        first place), so it stays trivially within the command-length
        limit regardless of how many scenes or audio tracks the source
        video has.
        """

        staging_output_file = self._staging_output_file(target_output_file)

        Path(staging_output_file).parent.mkdir(parents=True, exist_ok=True)

        arguments: list[str] = ["-y"]

        for chunk_file in chunk_files:
            arguments.extend(
                [
                    "-i",
                    Path(chunk_file).resolve().as_posix(),
                ]
            )

        concat_stream_labels = "".join(
            f"[{index}:v:0][{index}:a:0]" for index in range(len(chunk_files))
        )

        filter_complex = (
            f"{concat_stream_labels}concat="
            f"n={len(chunk_files)}:v=1:a=1[concat_v][concat_a]"
        )

        config = resolved_config.config

        arguments.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[concat_v]",
                "-map",
                "[concat_a]",
                "-c:v",
                resolved_config.selected_video_codec,
            ]
        )

        if resolved_config.selected_video_codec in {"libx264", "libx265"}:
            arguments.extend(
                [
                    "-preset",
                    config.preset,
                    "-crf",
                    str(config.crf),
                ]
            )

        arguments.extend(
            [
                "-pix_fmt",
                str(config.pixel_format.value),
            ]
        )

        arguments.extend(config.extra_video_args)

        arguments.extend(
            [
                "-c:a",
                resolved_config.selected_audio_codec,
                "-b:a",
                config.audio_bitrate,
            ]
        )

        arguments.extend(config.extra_audio_args)

        arguments.append(staging_output_file)

        command_plan = FFmpegCommandPlan(
            executable=(
                resolved_config.capabilities.ffmpeg_path
                or self._ffmpeg_config.ffmpeg_path
            ),
            input_plan=FFmpegInputPlan(),
            filter_complex=filter_complex,
            video_output_label="concat_v",
            audio_output_label="concat_a",
            output_file=staging_output_file,
            arguments=arguments,
        )

        try:
            execution_result = self._ffmpeg_execution_service.execute(
                command_plan,
                total_duration_seconds=total_duration_seconds,
                timeout_seconds=(resolved_config.config.timeout_seconds),
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )
        except Exception as error:
            self._cleanup_staging_file(staging_output_file)

            return RenderResult(
                success=False,
                output_file=None,
                render_engine="ffmpeg",
                render_time_seconds=0.0,
                duration_seconds=int(total_duration_seconds),
                status=RenderStatus.FAILED,
                error_message=("Failed to concatenate rendered chunks: " f"{error}"),
                ffmpeg_command=list(command_plan.command),
            )

        ffmpeg_command = (
            list(execution_result.ffmpeg_command)
            if isinstance(execution_result.ffmpeg_command, list)
            else []
        )

        if not execution_result.success:
            self._cleanup_staging_file(staging_output_file)

            error_message = execution_result.error_message or (
                "FFmpeg concatenation returned " "an unsuccessful result."
            )

            return RenderResult(
                success=False,
                output_file=None,
                render_engine="ffmpeg",
                render_time_seconds=(execution_result.elapsed_seconds),
                duration_seconds=int(total_duration_seconds),
                status=RenderStatus.FAILED,
                error_message=error_message,
                ffmpeg_command=ffmpeg_command,
                exit_code=execution_result.exit_code,
            )

        completed_staging_file = execution_result.output_file

        if completed_staging_file is None:
            raise RuntimeError(
                "Successful FFmpeg concatenation " "did not provide an output file."
            )

        promoted_output_file = self._promote_staged_output(
            staging_output_file=completed_staging_file,
            target_output_file=target_output_file,
        )

        return RenderResult(
            success=True,
            output_file=promoted_output_file,
            render_engine="ffmpeg",
            render_time_seconds=(execution_result.elapsed_seconds),
            duration_seconds=int(total_duration_seconds),
            status=RenderStatus.COMPLETED,
            ffmpeg_command=ffmpeg_command,
            exit_code=execution_result.exit_code,
        )

    @staticmethod
    def _cleanup_chunk_files(
        chunk_files: list[str],
    ) -> None:
        """Best-effort removal of intermediate per-chunk render files."""

        for chunk_file in chunk_files:
            try:
                Path(chunk_file).unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _capability_string(
        resolved_config: object,
        attribute_name: str,
    ) -> str | None:
        """
        Read one resolved FFmpeg capability field RenderResult
        persists, tolerating a test double that does not model it as
        a real string.

        A genuine FFmpegResolvedConfig always exposes
        ffmpeg_version/selected_video_codec/selected_audio_codec/
        selected_hardware_acceleration as strings or None; this guard
        only ever activates for a loose test mock, never for a real
        render.
        """

        if attribute_name == "ffmpeg_version":
            value = getattr(
                getattr(resolved_config, "capabilities", None),
                "ffmpeg_version",
                None,
            )
        else:
            value = getattr(resolved_config, attribute_name, None)

        return value if isinstance(value, str) else None

    @staticmethod
    def _staging_output_file(
        target_output_file: str,
    ) -> str:
        """
        Return the staging path FFmpeg actually writes to for one
        target output path.

        The ".part" marker goes *before* the real extension
        ("final_video.mp4" -> "final_video.part.mp4"), not appended
        after it - FFmpegCommandBuilderService validates that the
        output filename's extension matches the configured container
        (e.g. requires ".mp4"), so a naive "final_video.mp4.part"
        staging path would fail that check before FFmpeg ever runs.
        """

        target_path = Path(target_output_file)

        return str(
            target_path.with_name(f"{target_path.stem}.part{target_path.suffix}")
        )

    @staticmethod
    def _promote_staged_output(
        *,
        staging_output_file: str,
        target_output_file: str,
    ) -> str:
        """
        Atomically promote a completed staged render to its final path.

        A genuinely successful FFmpeg execution always creates the
        staged file first - FFmpegExecutionService's own
        output-existence check runs before it ever reports success -
        so the "staging file does not exist" branch below only ever
        activates for a test double that reports success without
        writing a real file, never for a real render.
        """

        staging_path = Path(staging_output_file)

        if not staging_path.exists():
            return staging_output_file

        target_path = Path(target_output_file)

        staging_path.replace(target_path)

        return target_path.as_posix()

    @staticmethod
    def _cleanup_staging_file(
        staging_output_file: str,
    ) -> None:
        """
        Best-effort removal of a staged render file after a failed,
        cancelled, or interrupted render, so a retry never confuses a
        stale partial file for real output and the requested output
        path never briefly shows a corrupt or empty file.
        """

        try:
            Path(staging_output_file).unlink(missing_ok=True)
        except OSError:
            pass

    def _resolve_output_file(
        self,
        output_file: str | None,
    ) -> str:
        """Return a normalized render output path."""

        if output_file is None:
            return self._output_file

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Production render output file " "cannot be empty.")

        return Path(cleaned_output_file).as_posix()

    @staticmethod
    def _unique_warnings(
        warnings: list[str],
    ) -> list[str]:
        """Return normalized unique warnings."""

        result: list[str] = []

        for warning in warnings:
            cleaned_warning = warning.strip()

            if cleaned_warning and cleaned_warning not in result:
                result.append(cleaned_warning)

        return result
