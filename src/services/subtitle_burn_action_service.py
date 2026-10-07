"""Burn the project's subtitles onto any finished video, at any stage.

Subtitles used to be burned in only inside the main render (the Render tab's toggle), so
wanting them later - on the render, on the render with its title card, on an export
variant - meant re-rendering. The render now keeps its subtitle lines
(`RenderResult.subtitle_cues`); this shifts them past the opening title card, if the video
has one, and burns them onto a COPY of the chosen video. The original is never touched.
"""

from __future__ import annotations

from pathlib import Path

from src.models.absolute_subtitle_cue import AbsoluteSubtitleCue
from src.models.render_result import RenderResult
from src.models.video_job import VideoJob
from src.services.ffmpeg_execution_service import (
    CancellationCheck,
    ProgressCallback,
)
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)
from src.services.post_render_subtitle_burn_service import (
    PostRenderSubtitleBurnService,
)
from src.services.title_card_offset import title_card_seconds


class SubtitleBurnActionService:
    def __init__(
        self,
        *,
        burn_service: PostRenderSubtitleBurnService | None = None,
        media_validation_service: MediaTechnicalValidationService | None = None,
    ) -> None:
        self._burn_service = burn_service or PostRenderSubtitleBurnService()
        self._media_validation_service = (
            media_validation_service or MediaTechnicalValidationService()
        )

    @staticmethod
    def unavailable_reason(job: VideoJob) -> str | None:
        """Why subtitles cannot be burned for this project, or None when they can."""

        render = job.render_result

        if render is None or not render.success:
            return "Render the video first."

        if not render.subtitle_cues:
            return (
                "No subtitle lines are stored for this render (it was made before "
                "they were kept) - render it once more to enable this."
            )

        return None

    def offset_seconds(self, job: VideoJob, effective_render_file: str) -> float:
        """The length of the title card at the front of `effective_render_file` (the
        render a title card was added to), or 0 when it has none. A video made from it
        - an export variant - uses the same offset."""

        probed = self._media_validation_service.validate(Path(effective_render_file))

        if probed.duration_seconds is None:
            return 0.0

        return title_card_seconds(
            job,
            effective_render_file,
            float(probed.duration_seconds),
            self._media_validation_service,
        )

    def burn(
        self,
        *,
        job: VideoJob,
        source_file: str,
        output_file: str,
        offset_seconds: float = 0.0,
        progress_callback: ProgressCallback | None = None,
        cancellation_check: CancellationCheck | None = None,
    ) -> RenderResult:
        reason = self.unavailable_reason(job)

        if reason is not None:
            raise ValueError(reason)

        assert job.render_result is not None

        probed = self._media_validation_service.validate(Path(source_file))

        if not probed.is_readable or probed.duration_seconds is None:
            raise ValueError(f"The video could not be read: {Path(source_file).name}")

        duration = float(probed.duration_seconds)
        cues = _shifted_within(
            job.render_result.subtitle_cues, offset_seconds, duration
        )

        if not cues:
            raise ValueError("None of the subtitle lines fall inside this video.")

        return self._burn_service.burn(
            input_video_file=source_file,
            cues=cues,
            output_file=output_file,
            video_duration_seconds=duration,
            has_audio=bool(probed.has_audio_stream),
            progress_callback=progress_callback,
            cancellation_check=cancellation_check,
        )

    @staticmethod
    def output_file_for(source_file: str) -> str:
        """Where the copy with subtitles is written: next to the original."""

        path = Path(source_file)

        return path.with_name(f"{path.stem}_subtitled{path.suffix}").as_posix()


def _shifted_within(
    cues: list[AbsoluteSubtitleCue], offset_seconds: float, duration_seconds: float
) -> list[AbsoluteSubtitleCue]:
    """The cues moved `offset_seconds` later, those that start inside the video kept
    and the last one trimmed to the video's end."""

    shifted: list[AbsoluteSubtitleCue] = []

    for cue in cues:
        start = cue.start_seconds + offset_seconds

        if start >= duration_seconds:
            continue

        shifted.append(
            AbsoluteSubtitleCue(
                text=cue.text,
                start_seconds=start,
                end_seconds=min(cue.end_seconds + offset_seconds, duration_seconds),
            )
        )

    return shifted
