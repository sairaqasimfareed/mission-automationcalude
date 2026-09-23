from __future__ import annotations

from pathlib import Path

from src.models.audio_timeline import AudioTimeline
from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_input import (
    FFmpegInputBinding,
    FFmpegInputMediaType,
    FFmpegInputPlan,
)
from src.models.render_failure_diagnosis import classify_render_failure
from src.models.render_result import RenderResult, RenderStatus
from src.services.ffmpeg_capability_service import FFmpegCapabilityService
from src.services.ffmpeg_execution_service import (
    CancellationCheck,
    FFmpegExecutionService,
    ProgressCallback,
)
from src.services.filter_graph_builder_service import FilterGraphBuilderService
from src.services.production_render_service import ProductionRenderService
from src.services.render_graph_builder_service import RenderGraphBuilderService


class AudioMuxRenderService:
    """
    REQ-00 Stage 2: mux narration/music/SFX onto Stage 1's already-
    encoded video-only output via stream-copy - no video re-encode.

    Deliberately NOT built on the RenderGraph/FilterGraph/
    FFmpegCommandBuilderService pipeline Stage 1 uses - that machinery
    exists to translate scene/camera/effect/animation/subtitle
    execution plans into a video filter chain, none of which applies
    here (the video stream passes through untouched). Instead mirrors
    ExportVariantRenderService's own proven shape: build an
    FFmpegCommandPlan by hand, execute it directly through
    FFmpegExecutionService - the same pattern already used for the
    other real post-render pass in this codebase (CTA/watermark/export
    variants).

    Reuses, rather than reimplements, two pieces of already-proven
    logic instead of building a third: RenderGraphBuilderService's own
    AudioTrack -> RenderNode conversion, and FilterGraphBuilderService's
    own audio-mix/ducking filter-chain construction - the exact same
    code path the old composite render still uses for its own audio
    mixing. Every AudioTrack the caller passes in gets muxed
    unconditionally - REQ-10(a)'s own toggles are a thin filter over
    which tracks are IN that list before calling mux(), not something
    this service needs to know about.
    """

    def __init__(
        self,
        *,
        capability_service: FFmpegCapabilityService | None = None,
        execution_service: FFmpegExecutionService | None = None,
        filter_graph_builder_service: FilterGraphBuilderService | None = None,
    ) -> None:
        self._capability_service = capability_service or FFmpegCapabilityService()

        self._execution_service = execution_service or FFmpegExecutionService()

        self._filter_graph_builder_service = (
            filter_graph_builder_service or FilterGraphBuilderService()
        )

    def mux(
        self,
        *,
        video_only_render_result: RenderResult,
        audio_timeline: AudioTimeline,
        output_file: str,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> RenderResult:
        """
        Mux every track in audio_timeline onto video_only_render_result's
        own output file, producing one new, complete file at output_file.

        video_only_render_result must be a real, successful Stage 1
        result (render_video_only()'s own return value) - this service
        never renders video itself, only muxes audio onto an already-
        finished video file.
        """

        if not video_only_render_result.success:
            raise ValueError(
                "Stage 2 mux requires a successful Stage 1 " "video-only render result."
            )

        video_file = video_only_render_result.output_file

        if video_file is None:
            raise ValueError(
                "Stage 2 mux requires a Stage 1 render result " "with an output file."
            )

        if not audio_timeline.tracks:
            raise ValueError("Stage 2 mux requires at least one audio track.")

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError("Stage 2 mux output file cannot be empty.")

        target_output_file = Path(cleaned_output_file).as_posix()

        staging_output_file = ProductionRenderService._staging_output_file(
            target_output_file
        )

        resolved_config = self._capability_service.resolve()

        audio_nodes = [
            RenderGraphBuilderService._audio_node(track)
            for track in audio_timeline.tracks
        ]

        audio_chains = self._filter_graph_builder_service._build_audio_chains(
            audio_nodes=audio_nodes,
            first_input_index=1,
        )

        filter_complex = ";".join(
            expression
            for chain in audio_chains
            for expression in chain.render_expressions()
        )

        bindings = [
            FFmpegInputBinding(
                input_index=0,
                render_node_id="stage2_video_source",
                media_type=FFmpegInputMediaType.VIDEO,
                source_file=video_file,
                stream_label="0:v",
            ),
        ]

        for offset, track in enumerate(audio_timeline.tracks):
            bindings.append(
                FFmpegInputBinding(
                    input_index=1 + offset,
                    render_node_id=f"stage2_audio_{offset}",
                    media_type=FFmpegInputMediaType.AUDIO,
                    source_file=track.source_file,
                    stream_label=f"{1 + offset}:a",
                )
            )

        input_plan = FFmpegInputPlan(
            bindings=bindings,
            input_count=len(bindings),
            video_input_count=1,
            audio_input_count=len(audio_timeline.tracks),
        )

        arguments: list[str] = ["-y"]

        for binding in bindings:
            arguments.extend(["-i", binding.source_file])

        arguments.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "0:v",
                "-map",
                "[audio_final]",
                "-c:v",
                "copy",
                "-c:a",
                resolved_config.selected_audio_codec,
                "-b:a",
                resolved_config.config.audio_bitrate,
                staging_output_file,
            ]
        )

        command_plan = FFmpegCommandPlan(
            executable=resolved_config.capabilities.ffmpeg_path or "ffmpeg",
            input_plan=input_plan,
            filter_complex=filter_complex,
            video_output_label="video_passthrough",
            audio_output_label="audio_final",
            output_file=staging_output_file,
            arguments=arguments,
        )

        duration_seconds = float(max(1, video_only_render_result.duration_seconds))

        try:
            execution_result = self._execution_service.execute(
                command_plan,
                total_duration_seconds=duration_seconds,
                timeout_seconds=resolved_config.config.timeout_seconds,
                progress_callback=progress_callback,
                cancellation_check=cancellation_check,
            )
        except Exception:
            ProductionRenderService._cleanup_staging_file(staging_output_file)

            raise

        ffmpeg_command = (
            list(execution_result.ffmpeg_command)
            if isinstance(execution_result.ffmpeg_command, list)
            else []
        )

        if execution_result.success:
            completed_staging_file = execution_result.output_file

            if completed_staging_file is None:
                raise RuntimeError(
                    "Successful FFmpeg execution " "did not provide an output file."
                )

            promoted_output_file = ProductionRenderService._promote_staged_output(
                staging_output_file=completed_staging_file,
                target_output_file=target_output_file,
            )

            return RenderResult(
                success=True,
                output_file=promoted_output_file,
                render_engine="ffmpeg",
                render_time_seconds=execution_result.elapsed_seconds,
                duration_seconds=video_only_render_result.duration_seconds,
                status=RenderStatus.COMPLETED,
                ffmpeg_command=ffmpeg_command,
                exit_code=execution_result.exit_code,
                selected_audio_codec=resolved_config.selected_audio_codec,
                scene_timings=list(video_only_render_result.scene_timings),
            )

        error_message = execution_result.error_message or (
            "FFmpeg execution returned " "an unsuccessful result."
        )

        ProductionRenderService._cleanup_staging_file(staging_output_file)

        execution_metadata = execution_result.metadata

        failure_stage = (
            execution_metadata.get("failure_stage")
            if isinstance(execution_metadata, dict)
            else None
        )

        return RenderResult(
            success=False,
            output_file=None,
            render_engine="ffmpeg",
            render_time_seconds=execution_result.elapsed_seconds,
            duration_seconds=video_only_render_result.duration_seconds,
            status=RenderStatus.FAILED,
            error_message=error_message,
            ffmpeg_command=ffmpeg_command,
            exit_code=execution_result.exit_code,
            failure_category=classify_render_failure(failure_stage),
            selected_audio_codec=resolved_config.selected_audio_codec,
        )
