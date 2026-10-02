from __future__ import annotations

from uuid import UUID

from src.desktop.job_store import JobStore
from src.models.video_job import VideoJob

RERENDER_NOTICE = (
    "The video was re-rendered, so the previous export variants and final "
    "export (made from the old video) were cleared. Generate them again "
    "from the new render."
)


def invalidate_render_dependents(
    job_store: JobStore,
    job: VideoJob | None,
    job_id: UUID,
) -> list[str]:
    """
    A new successful render makes everything built FROM the previous
    render stale: export variants (reformatted/branded copies of it) and
    the final export package (which packages it). Left in place, the
    Packaging tab keeps presenting them as current - e.g. variants that
    still have subtitles burned in after the operator re-rendered with
    subtitles off.

    Only the records are cleared; the files on disk are never deleted
    (they may be the operator's own deliverables, and regenerating
    overwrites the same names anyway). The SEO package and thumbnail do
    not depend on the rendered video and are kept. The title card needs
    no clearing - it is applied onto the stored render result, which the
    new render replaces.

    Returns what was cleared (empty when there was nothing stale), and
    records a one-line notice on the job so the operator can see why.
    """

    cleared: list[str] = []

    variants = job_store.get_export_variants(job_id)

    if variants is not None and variants.variants:
        job_store.clear_export_variants(job_id)
        cleared.append("export variants")

    if job_store.get_final_export(job_id) is not None:
        job_store.clear_final_export(job_id)
        cleared.append("final export")

    if cleared and job is not None and RERENDER_NOTICE not in job.warnings:
        job.warnings.append(RERENDER_NOTICE)

    return cleared
