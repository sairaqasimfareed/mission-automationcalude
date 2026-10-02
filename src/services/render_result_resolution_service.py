from __future__ import annotations

from pydantic import ValidationError

from src.models.render_orchestration_result import RenderOrchestrationResult
from src.models.render_result import RenderResult
from src.models.video_job import VideoJob


def resolve_effective_render_result(
    job: VideoJob,
    job_store_result: RenderOrchestrationResult | None,
) -> RenderResult | None:
    """
    The RenderResult to trust for "did this project's render actually
    succeed."

    Real-world finding, 2026-09-30: JobStore.set_render_result() is
    only ever called from inside RenderWorkspaceView's and
    PackagingView's own GUI button handlers - never from the render
    engine/orchestrator itself. VideoJob.render_result, by contrast,
    is set directly by RenderPipelineStage regardless of what drove
    the render. A real project whose render happened through a
    standalone script rather than clicking "Run render" in the GUI
    (confirmed live: a genuinely completed render, real output file on
    disk, VideoJob.render_result.success=True) showed "Not rendered
    yet" across the Render tab, Quality Center's post-render
    checklist, and every render-gated action in Packaging, because all
    of them read only the GUI-only cache.

    job_store_result (when its own nested render_result is present) is
    preferred over the fallback, not replaced by it - a render
    genuinely triggered through the GUI keeps showing that richer,
    orchestration-level result (completed_stages, failed_stage, its
    own errors/warnings lists) exactly as before. The fallback to
    job.render_result only engages when the GUI-level cache has
    nothing to offer, so this is purely additive: every job that
    already worked continues to behave identically.
    """

    if job_store_result is not None and job_store_result.render_result is not None:
        return job_store_result.render_result

    return job.render_result


def resolve_effective_render_orchestration_result(
    job: VideoJob,
    job_store_result: RenderOrchestrationResult | None,
) -> RenderOrchestrationResult | None:
    """
    The RenderOrchestrationResult to trust for an action that genuinely
    needs the full wrapper (title card generation's own model_copy(),
    final export building's own required job/render_result pairing) -
    same real gap as resolve_effective_render_result(), but for a
    caller that cannot settle for the plain RenderResult alone.

    Synthesized via RenderOrchestrationResult.succeeded() - the same
    factory the real orchestrator itself uses - built from VideoJob's
    own already-persisted current_stage/status/render_result, never
    fabricated. Only ever synthesizes a SUCCESSFUL result: a failed
    job.render_result is the same "nothing usable to build from" state
    as no render result at all for every caller of this function, and
    RenderOrchestrationResult.failed() requires a failed_stage/
    error_message this function has no honest value for - so that case
    is reported as None rather than invented.

    succeeded() itself cross-validates job.status (must be COMPLETED)
    and job.current_stage (must be READY_FOR_UPLOAD/UPLOADED) against
    the orchestration-level fields it derives from them - true for a
    job whose render fully completed the real orchestrator's own
    stage sequence, but not guaranteed for a render that happened
    through some other path entirely (e.g. one that succeeded but
    where downstream packaging never ran, leaving job.status at
    something other than COMPLETED). This must never crash the caller
    over that mismatch - it's a display/gating decision, not a
    correctness one - so a real ValidationError here is treated the
    same as "nothing to synthesize from" rather than propagated.
    """

    if job_store_result is not None:
        return job_store_result

    if job.render_result is None or not job.render_result.success:
        return None

    try:
        return RenderOrchestrationResult.succeeded(
            job=job,
            completed_stages=[job.current_stage],
            elapsed_seconds=job.render_result.render_time_seconds,
        )
    except ValidationError:
        return None


def replace_orchestration_render_result(
    orchestration_result: RenderOrchestrationResult,
    new_render_result: RenderResult,
) -> RenderOrchestrationResult:
    """
    Return a copy of orchestration_result whose render_result is
    new_render_result, keeping RenderOrchestrationResult's own
    invariant ("Orchestration render result must match VideoJob render
    result") intact.

    Real-world finding, 2026-10-02: title card generation saved
    `orchestration_result.model_copy(update={"render_result": new})`.
    model_copy() skips validation, so the nested render_result moved to
    the new, with-title-card file while the embedded job snapshot's own
    render_result stayed on the old render. JsonJobStore's in-memory
    cache hid the mismatch for as long as the app stayed open; on the
    next launch the file was re-validated from disk, failed, and every
    attempt to open that project crashed. Both fields are updated
    together here so what gets persisted always loads back.
    """

    return orchestration_result.model_copy(
        update={
            "render_result": new_render_result,
            "job": orchestration_result.job.model_copy(
                update={"render_result": new_render_result}
            ),
        }
    )
