from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_config import FFmpegConfig, FFmpegResolvedConfig
from src.models.ffmpeg_input import FFmpegInputPlan
from src.models.master_edit_plan import MasterEditPlan
from src.models.render_failure_diagnosis import classify_render_failure
from src.models.render_result import RenderResult, RenderStatus
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

        resolved_config = self._ffmpeg_capability_service.resolve(self._ffmpeg_config)

        command_plan, master_plan, warnings, staging_output_file = (
            self._build_command_plan(
                video_timeline=video_timeline,
                audio_timeline=audio_timeline,
                voice_blueprints=voice_blueprints,
                target_output_file=target_output_file,
                resolved_config=resolved_config,
            )
        )

        full_command_length = self._assembled_command_length(command_plan)

        if full_command_length is None or full_command_length <= (
            self._SAFE_COMMAND_LINE_LENGTH
        ):
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
    ) -> tuple[FFmpegCommandPlan, MasterEditPlan, list[str], str]:
        """
        Build the deterministic FFmpeg command for one timeline pair
        without executing it.

        Shared by the single-pass render path and every chunk of a
        chunked render, so the plan-building logic (master plan,
        transition/effect/subtitle/camera/animation plans, render
        graph, filter graph, command plan) exists in exactly one
        place.
        """

        staging_output_file = self._staging_output_file(target_output_file)

        master_plan = self._master_edit_plan_service.build(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
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
    ) -> RenderResult:
        """Execute one already-built FFmpeg command plan to completion."""

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
    ) -> RenderResult:
        """
        Render a timeline too large for one FFmpeg command line as
        several smaller FFmpeg passes, then losslessly concatenate
        them.

        Each chunk reuses the exact same plan-building and execution
        path as a normal render (_build_command_plan /
        _execute_command_plan) - only the video/audio timeline given
        to it is a scene-bounded slice, re-based to start at zero.
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
        )

        scene_groups = self._split_scene_numbers(scene_numbers, chunk_count)

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

            if all(
                self._chunk_command_fits(
                    video_timeline=video_timeline,
                    audio_timeline=audio_timeline,
                    voice_blueprints=voice_blueprints,
                    scene_numbers=group,
                    resolved_config=resolved_config,
                )
                for group in groups
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
    ) -> bool:
        """Build one candidate chunk's command plan just to measure it."""

        chunk_video_timeline, chunk_audio_timeline, chunk_voice_blueprints = (
            self._slice_for_scenes(
                video_timeline=video_timeline,
                audio_timeline=audio_timeline,
                voice_blueprints=voice_blueprints,
                scene_numbers=scene_numbers,
            )
        )

        command_plan, _master_plan, _warnings, _staging_output_file = (
            self._build_command_plan(
                video_timeline=chunk_video_timeline,
                audio_timeline=chunk_audio_timeline,
                voice_blueprints=chunk_voice_blueprints,
                target_output_file=self.DEFAULT_OUTPUT_FILE,
                resolved_config=resolved_config,
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
    def _slice_for_scenes(
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        voice_blueprints: list[ResolvedVoiceBlueprint],
        scene_numbers: set[int],
    ) -> tuple[VideoTimeline, AudioTimeline, list[ResolvedVoiceBlueprint]]:
        """
        Return a self-contained, zero-based timeline slice covering
        only the given scene numbers.

        Video items and voiceover/sound-effect tracks partition
        cleanly by their original scene-aligned time window, re-based
        to start at zero. Background music has no natural per-scene
        boundary, so each chunk instead gets its own copy re-based to
        fill exactly that chunk's duration, relying on the same
        loop/atrim mechanism that already fills a track shorter than
        its timeline.
        """

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

        chunk_duration = chunk_end - chunk_start

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

        chunk_tracks: list[AudioTrack] = []

        for track in audio_timeline.tracks:
            if track.track_type == AudioTrackType.BACKGROUND_MUSIC:
                continue

            if chunk_start <= track.start_time_seconds < chunk_end:
                rebased_start = track.start_time_seconds - chunk_start

                # A track is allowed to run slightly past its own
                # scene's boundary in the full timeline (e.g. a
                # sound-effect tail, or a voiceover's trailing pause) -
                # harmless there since it just bleeds into whatever
                # comes next. Inside a chunk there is nothing after the
                # chunk's own last scene to bleed into, so a track
                # belonging to that last scene must be clipped to the
                # chunk's own duration or it fails the same
                # audio-vs-video duration tolerance check the full
                # timeline already passed.
                clipped_duration = min(
                    track.duration_seconds,
                    max(chunk_duration - rebased_start, 0.0),
                )

                chunk_tracks.append(
                    track.model_copy(
                        update={
                            "start_time_seconds": rebased_start,
                            "duration_seconds": clipped_duration,
                        }
                    )
                )

        for track in audio_timeline.tracks:
            if track.track_type != AudioTrackType.BACKGROUND_MUSIC:
                continue

            chunk_tracks.append(
                track.model_copy(
                    update={
                        "start_time_seconds": 0.0,
                        "duration_seconds": chunk_duration,
                        "loop_enabled": True,
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
        """Losslessly concatenate already-rendered chunk files via FFmpeg."""

        staging_output_file = self._staging_output_file(target_output_file)

        concat_list_file = f"{staging_output_file}.concat_list.txt"

        Path(staging_output_file).parent.mkdir(parents=True, exist_ok=True)

        Path(concat_list_file).write_text(
            "\n".join(self._concat_file_line(chunk_file) for chunk_file in chunk_files)
            + "\n",
            encoding="utf-8",
        )

        command_plan = FFmpegCommandPlan(
            executable=(
                resolved_config.capabilities.ffmpeg_path
                or self._ffmpeg_config.ffmpeg_path
            ),
            input_plan=FFmpegInputPlan(),
            filter_complex="concat_demuxer_passthrough",
            video_output_label="v",
            audio_output_label="a",
            output_file=staging_output_file,
            arguments=[
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list_file,
                "-c",
                "copy",
                staging_output_file,
            ],
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

            Path(concat_list_file).unlink(missing_ok=True)

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

        Path(concat_list_file).unlink(missing_ok=True)

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
    def _concat_file_line(
        chunk_file: str,
    ) -> str:
        """Return one escaped FFmpeg concat-demuxer file-list line."""

        absolute_path = Path(chunk_file).resolve().as_posix()

        escaped_path = absolute_path.replace("'", "'\\''")

        return f"file '{escaped_path}'"

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
