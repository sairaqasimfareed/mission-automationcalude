from __future__ import annotations

from enum import Enum


class RenderFailureCategory(str, Enum):
    """
    Coarse classification of why a production render did not
    complete successfully.

    Post-Script-Approval Production Plan, Phase 14: "Classify
    environment/media failures vs upstream-plan defects." REUSE
    confirmed by inspection - FFmpegExecutionService already computes
    a much finer-grained `failure_stage` value on every failure
    (process_start/stream_setup/timeout/cancelled/ffmpeg_exit/
    output_presence/output_type/output_size), but that value lives
    only inside FFmpegExecutionResult.metadata and was never read by
    ProductionRenderService or persisted onto RenderResult - the
    classification already existed, it just never reached the
    surface. This enum and classify_render_failure() below map that
    existing taxonomy onto the plan's own three-way distinction.

    Deliberately coarse where honesty requires it: this codebase does
    not parse FFmpeg's stderr text to separate a bad media input from
    a malformed generated command, so both surface as
    COMMAND_OR_MEDIA rather than a finer split this pass cannot back
    with real evidence.
    """

    ENVIRONMENT = "environment"
    COMMAND_OR_MEDIA = "command_or_media"
    CANCELLED = "cancelled"


_FAILURE_STAGE_CATEGORY_MAP: dict[str, RenderFailureCategory] = {
    # The OS/runtime itself could not run FFmpeg or read its streams,
    # or the process never finished within its allotted time, or
    # FFmpeg reported success but the filesystem result it left
    # behind is missing, the wrong type, or empty - all of these are
    # environment/IO problems, not a defect in the generated command
    # or a problem with the source media FFmpeg was asked to read.
    "process_start": RenderFailureCategory.ENVIRONMENT,
    "stream_setup": RenderFailureCategory.ENVIRONMENT,
    "timeout": RenderFailureCategory.ENVIRONMENT,
    "output_presence": RenderFailureCategory.ENVIRONMENT,
    "output_type": RenderFailureCategory.ENVIRONMENT,
    "output_size": RenderFailureCategory.ENVIRONMENT,
    # A deliberate, cooperative stop - not a failure at all.
    "cancelled": RenderFailureCategory.CANCELLED,
    # FFmpeg itself started and ran, then exited with an error. This
    # codebase has no verified way to tell a rejected/corrupt media
    # input apart from a malformed generated command from exit code
    # and stderr text alone, so both are named together.
    "ffmpeg_exit": RenderFailureCategory.COMMAND_OR_MEDIA,
}


def classify_render_failure(
    failure_stage: str | None,
) -> RenderFailureCategory | None:
    """
    Map an FFmpegExecutionResult's own `failure_stage` metadata value
    onto a coarse render-failure category.

    Returns None for a missing or unrecognized stage rather than
    guessing - an unclassifiable failure should surface as "not
    classified," never as a fabricated category.
    """

    if not failure_stage:
        return None

    return _FAILURE_STAGE_CATEGORY_MAP.get(failure_stage)
