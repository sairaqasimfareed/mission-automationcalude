# Architecture

This file is being built up incrementally as part of the production-
hardening effort (see `docs/AI_IMPLEMENTATION_PROTOCOL.md` for the
phase sequence and `docs/IMPLEMENTATION_STATE.md` for what exists
today). It does not yet attempt a full system architecture write-up -
that already lives, informally, across `docs/SYSTEM_BLUEPRINT.md`,
`docs/PIPELINE_DESIGN.md`, and `docs/PROJECT_SPECIFICATION.md`. What
follows is the one section the phase plan calls for explicitly.

## Selective invalidation matrix (Phase 3)

`VideoJob` stores each pipeline artifact as its own optional field
(`generated_script`, `scenes`, `scene_asset_states`, `video_clips`,
`audio_timeline`, `video_timeline`, `render_result`, ...). Nothing
enforces that an artifact still reflects the *current* state of the
artifacts it was produced from - if the script changes after scenes
were already planned from it, the old scenes just sit there, silently
stale, with no signal that they no longer match the current script.

`InvalidationService` (`src/services/invalidation_service.py`) makes
that relationship explicit for the three trigger categories the spec
names. Reading this as "if the row's trigger fires, the listed fields
no longer reflect current truth":

| Trigger | Downstream fields marked stale | Fires from |
|---|---|---|
| Script changed | `scenes`, `scene_asset_states`, `video_clips`, `audio_timeline`, `video_timeline`, `render_result` | `ContentIntelligencePipeline.run_revision` |
| Scene replaced | `video_timeline`, `render_result` | `BulkStockAssignmentService.assign`, `BulkClipIngestionService.ingest` (per successfully-reassigned scene) |
| Audio regenerated | `video_timeline`, `render_result` | `MediaGenerationPipeline.run_voice`/`.run_music`/`.run_sound_effects` |

Two things keep this matrix honest rather than just aspirational:

- **A field is never marked stale unless it already holds something.**
  `InvalidationService._mark_stale` skips any field that is
  `None`/empty - there is nothing to invalidate before it exists.
- **`video_clips` is deliberately excluded from the scene-replacement
  row.** `SceneAssetVideoClipBuilderService.build_clips` rebuilds it
  synchronously inside the very call that triggers this invalidation,
  so by the time `on_scene_replaced()` runs, `video_clips` already
  reflects the new state - marking it stale would be wrong, not just
  redundant. This is the kind of ordering subtlety a formal matrix is
  meant to catch instead of leaving to per-call-site judgment.
- **`audio_timeline` is excluded from the audio-regeneration row** for
  the same reason: `run_voice`/`.run_music`/`.run_sound_effects` write
  it directly as part of the same call.

Marking is non-destructive: a stale artifact stays exactly where it
was (`VideoJob.stale_artifacts` records *that* it's stale and *why*,
via `StaleArtifact.artifact`/`.reason`/`.triggered_by`), matching the
append-only pattern `content_decisions` and `script_version_history`
already use elsewhere. Nothing is deleted or reset out from under the
operator.

Clearing is explicit, not automatic: the stage that actually
regenerates a field calls `InvalidationService.clear_stale(job, field)`
once it has produced a fresh value. Wired today: `run_scene_planning`
clears `scenes`; `MediaGenerationPipeline.run_timeline` clears
`video_timeline`; `run_voice` clears `audio_timeline`; the two bulk
asset services clear `scene_asset_states`/`video_clips` after
rebuilding them. **Not yet wired: clearing `render_result`** - nothing
in the render pipeline calls `clear_stale` when a fresh render
completes, so a `render_result` marked stale by a scene replacement or
audio regeneration stays flagged stale even after a successful
re-render. This is a known, deliberate gap (touching the render
orchestrator was judged out of scope for this pass - see
`docs/REMAINING_GAPS.md` Phase 3) rather than an oversight.

`ProductionReadinessService` (`src/services/production_readiness_service.py`)
surfaces every `StaleArtifact` on the job as a `BLOCKING` `Blocker`
(`BlockerCode.ARTIFACT_STALE`), so staleness is visible in Quality
Center's "Production readiness" card without either system needing to
know about the other beyond that one shared read.

## Extending the matrix

Adding a new trigger or downstream field is additive: extend the
relevant tuple in `invalidation_service.py`, wire one `on_*` call at
the point the trigger actually fires, and wire one `clear_stale` call
at the point the field is actually regenerated. No new orchestration
or generic "invalidation engine" is needed - the matrix is intentionally
just a lookup table plus two explicit call sites per row, not a
framework.
