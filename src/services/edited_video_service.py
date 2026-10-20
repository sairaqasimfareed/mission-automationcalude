"""Use a video edited outside the app (CapCut, ...) as the project's finished video.

Packaging (title card, watermark, end CTA, export variants) all work on the project's render output file. To
add the app's CTA to a video edited elsewhere, the edited file takes that file's place:

    final_video.mp4                   <- the edited video (what the rest of the app now sees)
    final_video_edited.mp4            <- a kept copy of it (a new render overwrites final_video.mp4)
    final_video_app_original.mp4      <- the app's own render, kept so it can be brought back

The app knows the edited video is in use when the render file is the same file as the kept copy (same size and
modification time); after a new render it no longer is, and nothing is lost: the kept copy is still there.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from src.models.render_result import RenderResult
from src.models.video_job import VideoJob
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)

ORIGINAL_SUFFIX = "_app_original"
EDITED_SUFFIX = "_edited"


def _sibling(path: Path, suffix: str) -> Path:
    return path.with_name(f"{path.stem}{suffix}{path.suffix}")


def _same_file(first: Path, second: Path) -> bool:
    if not first.is_file() or not second.is_file():
        return False

    a, b = first.stat(), second.stat()

    return a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns


def edited_video_in_use(job: VideoJob) -> bool:
    """Whether the project's render output is currently the operator's edited video."""

    render = job.render_result

    if render is None or not render.success or not render.output_file:
        return False

    if not job.edited_video_path:
        return False

    return _same_file(Path(render.output_file), Path(job.edited_video_path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


class EditedVideoService:
    def __init__(
        self, *, media_validation_service: MediaTechnicalValidationService | None = None
    ) -> None:
        self._media = media_validation_service or MediaTechnicalValidationService()

    def use_edited_video(self, job: VideoJob, source_file: str) -> RenderResult:
        """Make `source_file` the project's finished video. Returns the updated render result."""

        render = job.render_result

        if render is None or not render.success or not render.output_file:
            raise ValueError(
                "Render the video first - the edited video takes its place."
            )

        source = Path(source_file)

        if not source.is_file():
            raise ValueError("That video file could not be found.")

        probed = self._media.validate(source)

        if not probed.is_readable or not probed.has_video_stream:
            raise ValueError("That file could not be read as a video.")

        output = Path(render.output_file)
        original = _sibling(output, ORIGINAL_SUFFIX)
        edited = _sibling(output, EDITED_SUFFIX)

        # Keep the app's own render the first time only (a second edited video must not replace it
        # with the first edited one).
        if output.is_file() and not original.exists() and not edited_video_in_use(job):
            shutil.copy2(output, original)

        shutil.copy2(source, edited)
        # Replace the render file in one step so a failed copy never leaves half a video there.
        temporary = _sibling(output, ".incoming")
        shutil.copy2(edited, temporary)
        temporary.replace(output)

        job.edited_video_path = str(edited)
        job.edited_video_checksum = _sha256(edited)
        updated = render.model_copy(
            update={
                "duration_seconds": int(round(probed.duration_seconds or 0))
                or render.duration_seconds
            }
        )
        job.render_result = updated

        return updated

    def restore_app_render(self, job: VideoJob) -> RenderResult:
        """Bring the app's own render back in place of the edited video. The edited copy is kept."""

        render = job.render_result

        if render is None or not render.output_file:
            raise ValueError("There is no render to restore.")

        output = Path(render.output_file)
        original = _sibling(output, ORIGINAL_SUFFIX)

        if not original.is_file():
            raise ValueError(
                "The app's own render was not kept, so it cannot be brought back."
            )

        probed = self._media.validate(original)
        temporary = _sibling(output, ".incoming")
        shutil.copy2(original, temporary)
        temporary.replace(output)

        job.edited_video_path = None
        job.edited_video_checksum = None
        updated = render.model_copy(
            update={
                "duration_seconds": int(round(probed.duration_seconds or 0))
                or render.duration_seconds
            }
        )
        job.render_result = updated

        return updated
