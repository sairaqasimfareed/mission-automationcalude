from __future__ import annotations

import time

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrackType
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import PipelineStageName, PipelineStageStatus
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.native_clip_audio_extraction_service import (
    NativeClipAudioExtractionService,
)
from src.services.production_render_service import ProductionRenderService

_NATIVE_CLIP_AUDIO_OUTPUT_DIRECTORY = "assets/audio/native_clips"


class NativeClipAudioPipelineStage(BasePipelineStage):
    """
    REQ-10(a) "Use native clip audio": extract each AI-generated
    clip's own embedded audio into real NATIVE_CLIP AudioTrack
    entries, so a job whose scenes carry real lip-synced/ambient
    dialogue (confirmed real, see character-oriented-video-mode
    memory) can actually include it in the final mux - the one
    REQ-10(a) toggle that had a real UI checkbox but no real effect
    (NativeClipAudioExtractionService itself was already real and
    tested, just never called from anywhere in real generation).

    Runs after TimelinePipelineStage (needs the real, built
    video_timeline) and reuses ProductionRenderService.
    _compute_real_scene_timings() directly - the same real,
    crossfade-corrected positioning REQ-00 Stage 1 already computes,
    confirmed standalone-callable (a pure classmethod over
    video_timeline + transition_duration_seconds, no dependency on
    Stage 1 actually being wired into the live render path).

    A missing/failed extraction never fails the render - native clip
    audio is an enhancement layered onto an already-complete audio
    mix, the same "don't let an enhancement's failure block the real
    deliverable" reasoning MusicPipelineStage/OpeningTitleCardService
    already established. Per-item skip-on-no-audio-stream is already
    handled inside NativeClipAudioExtractionService itself; only a
    genuinely broken ffmpeg/ffprobe install would raise here, and even
    that degrades to a warning rather than a failed stage.
    """

    def __init__(
        self,
        *,
        extraction_service: NativeClipAudioExtractionService | None = None,
        transition_duration_seconds: float = 0.0,
        output_directory: str = _NATIVE_CLIP_AUDIO_OUTPUT_DIRECTORY,
    ) -> None:
        self._extraction_service = (
            extraction_service or NativeClipAudioExtractionService()
        )

        self._transition_duration_seconds = transition_duration_seconds

        self._output_directory = output_directory

    @property
    def stage_name(self) -> PipelineStageName:
        return PipelineStageName.AUDIO_TIMELINE

    def execute(self, context: StageContext) -> StageResult:
        started_at = time.perf_counter()

        if not context.job.audio_inclusion_preferences.include_native_clip_audio:
            return self._skipped_result(
                started_at=started_at,
                warning=None,
                metadata={"reason": "native_clip_audio_toggle_off"},
            )

        timeline = context.job.video_timeline

        if timeline is None:
            return self._skipped_result(
                started_at=started_at,
                warning=None,
                metadata={"reason": "no_video_timeline_yet"},
            )

        audio_timeline = context.job.audio_timeline or AudioTimeline()

        # Real-world finding, matching MusicPipelineStage's own
        # idempotency guard: a full pipeline re-run
        # (resume_previous_pipeline=True + skip_completed_stages=False)
        # would otherwise re-extract and duplicate every native-clip
        # track on each pass.
        if any(
            track.track_type == AudioTrackType.NATIVE_CLIP
            for track in audio_timeline.tracks
        ):
            return self._skipped_result(
                started_at=started_at,
                warning=None,
                metadata={"reason": "native_clip_audio_already_attached"},
            )

        scene_timings = ProductionRenderService._compute_real_scene_timings(
            video_timeline=timeline,
            transition_duration_seconds=self._transition_duration_seconds,
        )

        try:
            tracks = self._extraction_service.extract_native_clip_audio_tracks(
                video_timeline=timeline,
                scene_timings=scene_timings,
                output_directory=self._output_directory,
            )
        except Exception as error:  # noqa: BLE001 - degrade, don't fail the render
            return self._skipped_result(
                started_at=started_at,
                warning=f"Native clip audio extraction failed: {error}",
                metadata={"reason": "extraction_failed"},
            )

        if not tracks:
            return self._skipped_result(
                started_at=started_at,
                warning=None,
                metadata={"reason": "no_scene_carries_real_native_audio"},
            )

        audio_timeline.tracks.extend(tracks)
        context.job.audio_timeline = audio_timeline

        return StageResult(
            stage=self.stage_name,
            status=PipelineStageStatus.COMPLETED,
            duration_seconds=time.perf_counter() - started_at,
            progress_percent=100,
            warnings=[],
            errors=[],
            metadata={
                "attached": True,
                "track_count": len(tracks),
            },
        )

    def _skipped_result(
        self,
        *,
        started_at: float,
        warning: str | None,
        metadata: dict[str, object] | None = None,
    ) -> StageResult:
        """
        Build a non-fatal COMPLETED result for every "nothing to
        extract" path - native clip audio is an enhancement, never a
        hard requirement.
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
