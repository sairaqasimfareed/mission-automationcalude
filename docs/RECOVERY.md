# Recovery

What actually happens today if the application stops or crashes at each
stage boundary, and what changes once the phases in
`docs/REMAINING_GAPS.md` land. This describes real, verified behavior -
not aspiration. Where current behavior has a real gap, it says so
plainly rather than describing the target state as if it already exists.

## How persistence works (the mechanism everything else relies on)

`VideoJob` is serialized to disk by `JsonJobStore` on every mutation the
GUI triggers (`model_dump_json`/`model_validate_json`, atomic
write-then-replace). Re-opening a project after any crash reloads
exactly the `VideoJob` state that was last written - there is no
in-memory-only state that can be lost except whatever hasn't been
written back to the store yet (a GUI action in progress when the crash
happens).

## Content-intelligence stages (research through packaging hypothesis)

**Current behavior:** Restart-safe in the sense that reopening the
project shows exactly what completed - each stage writes directly to a
`VideoJob` field, and that field is either populated or it isn't. There
is **no checkpoint/resume machinery** for this pipeline and **no
idempotency guard**: if you restart mid-way and click "Run script"
again, it re-calls the LLM even if `job.generated_script` is already
set from before the crash (which it wouldn't be, since the crash
happened before that stage completed - but the same is true if you
simply click a completed stage's button again by mistake after
restart). See `docs/REMAINING_GAPS.md` Phase 1/2 for the approval-state
and readiness-service work that will make "should this re-run" an
explicit, checkable question instead of implicit trust in the operator.

**Practical effect of a crash mid-stage:** the field that stage was
about to write stays `None`; every prior stage's output is intact and
reusable, since each is a separate persisted field.

## Asset acquisition (manual upload / stock footage)

**Current behavior:** Real, tested restart safety via
`SceneAssetState` (persisted per scene on `VideoJob.scene_asset_states`)
and `SceneAssetWorkflowService`. A scene's acquisition state is fully
reconstructible from disk; `SceneAssetVideoClipBuilderService` rebuilds
`VideoJob.video_clips` deterministically from whatever states are
`READY`. Bulk assignment (`BulkStockAssignmentService`,
`BulkClipIngestionService`) goes through the same underlying calls, so
the same guarantee applies.

## Narration / music / SFX

**Current behavior:** Each `MediaGenerationPipeline` stage writes
directly to `VideoJob.audio_timeline`/`.voice_status`/`.voice_file`/
`.video_timeline`. A crash mid-stage leaves the target field unset;
already-completed stages are untouched. Like content-intelligence
stages, there is no idempotency guard against accidentally re-running a
completed stage and regenerating (and paying for, on a live provider)
audio that already exists and is still valid. Phase 4's "reuse valid
READY artifacts" work addresses this specifically for audio.

## Editing / timeline / render

**Current behavior:** This is the one part of the system with real,
purpose-built restart machinery: `PipelineCheckpointService` +
`PipelineCheckpointStorageService` persist checkpoints during render
execution, and `PipelineResumePlannerService` determines the correct
resume point on restart, verified by
`test_render_orchestrator_checkpoint_resume.py`,
`test_pipeline_engine_resume.py`, and
`test_pipeline_resume_execution.py`. This is the reference
implementation the content-intelligence and audio pipelines should
eventually match.

## Final preview / export

**Current behavior:** No formal final-preview stage exists yet (see
`docs/REMAINING_GAPS.md` Phase 5), so there's nothing stage-specific to
say about its recovery behavior beyond the general `VideoJob`
persistence guarantee. `FinalExportService`/export packaging follows the
same "writes to a persisted field, reloadable on restart" pattern as
everything else that isn't the render pipeline.

## Summary table

| Stage | Restart-safe via persistence | Checkpoint/resume machinery | Idempotent re-run guard |
|---|---|---|---|
| Content intelligence (research → packaging) | Yes | No | No |
| Asset acquisition | Yes | Yes (`SceneAssetState`) | Yes (state-based) |
| Narration / music / SFX | Yes | No | No |
| Editing / timeline / render | Yes | Yes | Yes |
| Final preview / export | Yes (no dedicated stage yet) | No | N/A |

Closing the "No" cells in the last two columns for content intelligence
and audio is Phase 1/2/4's job, not a documentation exercise - update
this table in the same change that does it.
