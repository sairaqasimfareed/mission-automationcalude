"""How long the opening title card at the start of a finished video is.

The card-free render is kept on the job (`VideoJob.render_result`). A video made after
the card was added is that render plus the card, so the card's length is the difference
between the two files' real lengths. Used wherever something must start AFTER the card:
the uploaded watermark and the subtitles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.models.media_technical_validation import MediaTechnicalValidationResult
from src.models.video_job import VideoJob

# A title card the operator added is shorter than this; a bigger difference between the
# finished render and the card-free one means something else (a different render), so
# it is not treated as a title card.
MAX_TITLE_CARD_SECONDS = 30.0
MIN_TITLE_CARD_SECONDS = 0.5


class _Probe(Protocol):
    def validate(self, file_path: Path) -> MediaTechnicalValidationResult: ...


def title_card_seconds(
    job: VideoJob,
    source_file: str,
    source_duration_seconds: float,
    media_validation_service: _Probe,
) -> float:
    """The title card's length at the start of `source_file`, or 0 if it has none."""

    base = job.render_result

    if base is None or not base.success or not base.output_file:
        return 0.0

    if Path(base.output_file).resolve() == Path(source_file).resolve():
        return 0.0

    try:
        probed = media_validation_service.validate(Path(base.output_file))
    except Exception:  # noqa: BLE001 - an unreadable base render means "no card"
        return 0.0

    if probed.duration_seconds is None:
        return 0.0

    extra = source_duration_seconds - float(probed.duration_seconds)

    if MIN_TITLE_CARD_SECONDS <= extra <= MAX_TITLE_CARD_SECONDS:
        return float(extra)

    return 0.0
