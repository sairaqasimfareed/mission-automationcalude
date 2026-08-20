# Project Progress

Dated log, newest entry first. See `docs/IMPLEMENTATION_STATE.md` for
current capability status and `docs/REMAINING_GAPS.md` for what's next.

---

## 2026-08-20 - Phase 3: Selective invalidation

Added `InvalidationService` (`src/services/invalidation_service.py`)
and `StaleArtifact` (`src/models/invalidation.py`, on the new
`VideoJob.stale_artifacts` field), formalizing the three dependency
rows the master prompt names explicitly - script change, scene
replacement, audio regeneration - as an actual lookup table (see the
new invalidation-matrix section in `docs/ARCHITECTURE.md`), not just a
description. Wired into the real trigger points:
`ContentIntelligencePipeline.run_revision` (script change),
`BulkStockAssignmentService`/`BulkClipIngestionService` (scene
replacement), and `MediaGenerationPipeline.run_voice/.run_music/
.run_sound_effects` (audio regeneration). Marking is non-destructive
(same append-only philosophy as `content_decisions`/
`script_version_history`); clearing is explicit, wired at every stage
that actually regenerates one of the affected fields
(`run_scene_planning` for `scenes`, `run_timeline` for
`video_timeline`, `run_voice` for `audio_timeline`, the two bulk
services for `scene_asset_states`/`video_clips`). Staleness feeds
`ProductionReadinessService` directly as a new `BLOCKING`
`BlockerCode.ARTIFACT_STALE`, so it's visible in Quality Center without
a second GUI surface.

Two matrix subtleties worth naming: `video_clips` is deliberately
excluded from the scene-replacement row (rebuilt synchronously in the
same call) and `audio_timeline` from the audio-regeneration row (same
reason) - marking either stale would have been actively wrong, not
just redundant.

Deliberately incomplete: `render_result` staleness is marked but never
cleared (nothing in the render pipeline calls `clear_stale()` on a
fresh render - touching that subsystem was judged out of scope for
this pass), and `AssetPipelineStage` (the render pipeline's own,
first-run asset resolution stage) doesn't call `InvalidationService`
at all, on the judgment that a fresh pipeline run rarely has anything
downstream yet to invalidate - untested, so treated as a judgment call
rather than a proven-safe one. Both tracked in `docs/REMAINING_GAPS.md`.

## 2026-08-20 - Phase 2: Readiness service & typed blockers

Added a typed `Blocker` model (`src/models/blocker.py`: `code`,
`stage`, `severity`, `message`, `affected_artifact`, `retryable`,
`recovery_action`) and `ProductionReadinessService`
(`src/services/production_readiness_service.py`), the first
centralized answer to "is this project ready" - `BLOCKED`/
`READY_FOR_RENDER`/`READY_FOR_FINAL_EXPORT`/`COMPLETED`, backed by a
list of typed blockers rather than a boolean. It inspects script/scene
planning, every pending approval gate (reusing Phase 1's
`ApprovalGateService.all_pending`), per-scene asset readiness
(converting a scene's `AssetModuleFailure` into a `Blocker` - the
Phase 2 "retrofit an existing failure path" item), the audio timeline,
the video timeline, the render result, and the policy report. Quality
Center gets a new "Production readiness" card consuming it directly,
so that indicator no longer duplicates its own readiness logic; the
existing "Post-render checklist" card was left alone since it tracks
genuinely different downstream artifacts (SEO/thumbnail/final export)
outside this service's scope.

Deliberately not done this phase: converting `MediaGenerationPipeline`'s
and `ContentIntelligencePipeline`'s bare `RuntimeError` messages into
`Blocker`-typed errors (would touch every stage method in both
pipelines plus their GUI call sites and existing error-path tests -
too large for this pass, and `ProductionReadinessService` already
surfaces the same "missing prerequisite" conditions independently by
inspecting `VideoJob` state directly); wiring the readiness service
into Render/Clip workspace indicators specifically, which still derive
their own local notions of "ready." Both tracked in
`docs/REMAINING_GAPS.md`.

## 2026-08-20 - Phase 1: Approval runtime gating & decision history

`ApprovalPolicyConfig` and `ApprovalService` existed but had never been
wired together, and `VideoJob.content_decisions` had zero append call
sites anywhere - both pre-existing gaps this phase closes. Added
`ApprovalGateService` (`src/services/approval_gate_service.py`),
resolving one stage's completion against the job's configured policy
via `ApprovalService.open_decision()` and recording the outcome as an
append-only `ContentDecisionRecord`. Wired it into
`ContentIntelligencePipeline` for the 6 stages that map onto an
existing named decision point (`content_strategy`, `research`,
`story_angle`, `narrative_architecture`, `hook`, `final_script`), each
gate fed a real confidence signal where one exists
(`AudiencePromise.confidence_score`, `ResearchResult.fact_confidence_score`,
`StoryAngleEvaluation.confidence_score`, `HookEvaluation.confidence_score`)
so `ApprovalService`'s existing confidence-based escalation (spec
section 56: an AUTO policy still pends on a low-confidence result) is
real, not decorative. `run_all()` now checks `is_blocked()` after each
gated stage and stops early, with the pending state persisted on
`VideoJob.content_decisions` so it survives a restart; a human resolves
it via the new "Approval history" card in Content Studio
(`src/desktop/views/content_studio_view.py`, Approve/Reject buttons) or
`ContentIntelligencePipeline.resolve_approval()` directly. Individual
stage buttons remain always-runnable regardless of gate state - only
`run_all()`'s auto-chaining respects it.

Deliberately deferred: `run_all()` always restarts from stage one
rather than resuming mid-pipeline after a gate clears (no
skip-already-completed-stage idempotency yet); `MediaGenerationPipeline`
is not gated (no matching named decision points exist for it today).
Both are separate, explicitly out-of-scope-for-this-phase concerns
tracked in `docs/REMAINING_GAPS.md`.

## 2026-08-20 - Phase 0: Documentation & control layer

Added the documentation set the production-hardening master prompt
calls for: `AGENTS.md`, `docs/IMPLEMENTATION_STATE.md`,
`docs/REMAINING_GAPS.md`, `docs/SYSTEM_TRACEABILITY_MATRIX.md`,
`docs/ACCEPTANCE_CRITERIA.md`, `docs/AI_IMPLEMENTATION_PROTOCOL.md`,
`docs/RECOVERY.md`, and this file (previously empty). Content is based
on a direct code audit, not the master prompt's own claims - every
Done/Partial/Missing verdict in `IMPLEMENTATION_STATE.md` traces to a
specific file.

Net new capability: none - this phase is entirely documentation,
establishing the baseline the remaining phases work against.

## Earlier work (this repository's history through Sprint B2)

The entries below summarize what already existed before the
documentation phase above, for context. Going forward, each phase gets
its own dated entry above this line.

**Genre-aware editorial intelligence engine (Sprints A1-A11).** Built
the full content-intelligence pipeline: genre-specific hook patterns,
pacing curves, reveal density, research policy, and quality thresholds
across 11 genres; Format/Audience/ChannelStyle profile composition;
research → story angles → narrative blueprint → retention audit → hooks
→ script → continuity bible → editorial critique → quality gate →
optional revision → packaging hypothesis → genre-aware scene planning,
each a separately GUI-triggered stage; three approval-mode presets;
script version lineage with lock/unlock and change-impact
classification. This made a previously-inert, sophisticated backend
(built in sprints 0-7, never reachable from the GUI) into the live
Content Studio experience.

**Bulk clip source assignment (Sprint B1).** Multi-select scenes in
Clip Workspace and bulk-assign stock footage (auto-selecting the
top-ranked search result) through the same real workflow the Render
Workspace already used one scene at a time. Combined with the earlier
bulk external-generation prompt-export/ingestion workflow, this covers
manual upload, stock footage, and externally-generated clips for bulk
assignment.

**Standalone voice/timeline/music/SFX generation (Sprint B2).** Turned
Production Audio from a read-only review panel into a real generation
screen, calling the same ElevenLabs-backed services the render pipeline
already used internally, just triggerable one stage at a time.

**Scope note, all of the above and going forward:** Google Flow, and
any browser automation targeting it, is explicitly out of scope. See
`AGENTS.md`.
