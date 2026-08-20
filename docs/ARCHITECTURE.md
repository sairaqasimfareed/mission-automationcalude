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
| Audio regenerated | `render_result` only | `MediaGenerationPipeline.run_voice`/`.run_music`/`.run_sound_effects` |

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
- **`video_timeline` is excluded from the audio-regeneration row.**
  `GenreTimelinePipelineService.build()` takes only `scenes`, `clips`,
  and `genre_id` - it embeds no audio data at all
  (`VideoTimelineItem` carries a `clip: VideoClip`, never an audio
  reference), so regenerating voice/music/SFX never actually makes an
  already-built timeline stale. Only `render_result` (which does mix
  the audio in) is affected. An earlier version of this matrix marked
  `video_timeline` stale here too; `MediaGenerationPipeline.run_all_audio`'s
  reuse-detection surfaced the bug immediately - a second call marked
  a just-built timeline stale as a side effect of the music/SFX stages
  that ran after it, forcing an unnecessary rebuild every time.

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

## Render identity & Final Preview (Phase 5/6)

`RenderIdentityService` (`src/services/render_identity_service.py`)
computes a deterministic SHA-256 over one job's current render inputs:
video timeline identity (per-item scene number, track index, timing,
and clip source - order-independent, sorted before hashing), audio
timeline identity (per-track type, source file, timing, and volume -
also order-independent), and render settings (production mode,
resolution, frame rate). It is pure and stateless: never mutates the
job, never caches a result, recomputable at any time from
`VideoJob.video_timeline`/`.audio_timeline`/`.production_mode` alone.

**The produced output file is deliberately not part of the hash.** The
identity has to be computable from inputs *before* a render exists -
that is what makes "would a fresh render still match this preview?"
answerable without re-rendering. Hashing the actual output file's bytes
would also require file I/O this service has no reason to do. The
`output_file` a render actually produced is recorded separately,
alongside the identity, on whichever `FinalPreview` was created from
it - it identifies what got produced, without being an input to what
identity that production has.

`FinalPreviewService` (`src/services/final_preview_service.py`) is the
one consumer: `create_preview(job)` requires a successful
`render_result` and computes+stores the current identity on a new
`FinalPreview` (`src/models/final_preview.py`), append-only on
`VideoJob.final_previews` - same pattern as `content_decisions`/
`script_version_history`/`stale_artifacts` elsewhere in this codebase.
`resolve(job, action)` applies one of the four spec'd actions:

- `APPROVE_FINAL` -> `FinalPreviewStatus.APPROVED`
- `RETURN_TO_EDITING` -> `FinalPreviewStatus.RETURNED_TO_EDITING`
- `REPLACE_SCENE` / `REGENERATE_AUDIO` -> also `RETURNED_TO_EDITING`,
  recorded as the human's *stated intent* only. The actual scene
  replacement or audio regeneration happens through Clip Workspace's
  bulk asset services or `MediaGenerationPipeline` - both already call
  `InvalidationService` themselves, so nothing here needs to duplicate
  that.

**Why a separate action vocabulary instead of reusing
`ApprovalGateService`'s `HumanApprovalAction`** (APPROVE/EDIT/REJECT/
REGENERATE/SELECT_ALTERNATIVE/REQUEST_MORE_OPTIONS/RETURN_TO_PREVIOUS,
Phase 1): that vocabulary is deliberately generic across every content-
intelligence decision point. REPLACE_SCENE and REGENERATE_AUDIO are
workflow re-entry commands specific to reviewing a finished render, not
an approve/reject/changes-requested outcome - stretching the shared
vocabulary to cover them would have made it less generic for every
other decision point that actually does fit the approve/reject shape.
`ApprovalPolicyConfig`'s existing named `final_preview` slot remains
unused by this mechanism as a result; revisit if a future decision
point turns out to need this same shape.

`is_current(job)` is the live check a stored `FinalPreview` never
performs on itself: it recomputes the identity fresh and also checks
`InvalidationService.is_stale(job, "render_result")` - either signal
means the preview no longer reflects the job's current render.
`ProductionReadinessService` surfaces an approved-but-no-longer-current
preview as a `BLOCKING` `BlockerCode.FINAL_PREVIEW_STALE`, the same
pattern `ARTIFACT_STALE`/`MANUAL_AUDIO_REQUIRED` already use - one
blocker code, one shared read, no new GUI surface needed beyond Quality
Center's existing readiness card.

Render identity was built as part of Phase 5, not a standalone Phase 6
pass, because Final Preview cannot function without something to bind
to. The other half of Phase 6 - asset provenance - is covered next.

## Asset provenance (Phase 6)

The spec asks for a unified provenance model with `asset_id`,
`asset_type`, `source`, `provider`, `original_request`, `project_id`,
`scene_id`, `created_at`, `source_version`, `checksum`, `qc_status`.
Building a second model with that shape would have duplicated most of
it: `asset_id`/`created_at` already exist on every model via
`MissionBaseModel.id`/`.created_at` (including `VideoClip` itself);
`provider`/`source` already exist as `VideoClip.provider`/
`.source_type`; `original_request` is already covered by
`VideoClip.prompt` (generation-based flows) and
`SceneAssetState.local_search_query`/`.stock_search_query`
(search-based flows); `project_id` isn't meaningful per-asset since
assets are never referenced outside their containing `VideoJob`.

Only three fields were genuinely missing, so those three were added
directly to `VideoClip` rather than wrapping everything in a
competing model:

- **`scene_id: str | None`** - links a clip back to the `Scene` it was
  produced for. Wired into `SceneAssetVideoClipBuilderService.build_clips`
  (`state.scene_id` is already in scope there - free to thread through,
  no new lookups needed).
- **`checksum: str | None`** - SHA-256 of the local file, via the new
  `AssetProvenanceService.compute_checksum()` (`src/services/asset_provenance_service.py`).
  Returns `None` for a clip with no local file yet (URL-only, or not
  yet downloaded) rather than raising - checksumming only applies to
  content that actually exists on disk.
- **`qc_status: AssetQCStatus`** - `PENDING`/`PASSED`/`FLAGGED`/
  `REJECTED` (`src/models/asset_provenance.py`). Defaults `PENDING`;
  nothing advances it further, since no automated QC pipeline exists
  yet to set it - the field exists so a future QC pass has somewhere
  real to write its result, not because QC itself is built.

**`source_version` was deliberately not added.** It would need to
track how many times a scene's asset has been *replaced* over the
project's lifetime - state that has to persist across rebuilds. It
can't live on `VideoClip` itself, because `build_clips()` reconstructs
the entire clip list from scratch on every call (bulk reassignment,
scene replacement, ingestion) rather than mutating existing clips in
place - a freshly-built `VideoClip` has no memory of its own history.
The natural home would be `SceneAssetState`, which does persist across
rebuilds, but adding it there was judged separate, additional scope
rather than something render identity or Final Preview required.

**Checksum computation is deliberately not automatic.** Wiring
`AssetProvenanceService.annotate()` directly into `build_clips()` was
considered and rejected: that method rebuilds the *entire* clip list
from scratch on every bulk reassignment (not just the scene that
changed), and this desktop app has no background-threading anywhere
today (every button handler runs synchronously on the GUI thread, see
Phase 9's project-header/recovery-UX gap) - hashing every ready video
file on every such call would risk real, noticeable freezes as an
asset library grows. `AssetProvenanceService` is real and fully tested,
just not auto-wired into that specific hot path; a future "verify
asset integrity" action, or a background-threaded rebuild, would be
the right place to call it from.
