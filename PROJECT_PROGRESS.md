# Project Progress

Dated log, newest entry first. See `docs/IMPLEMENTATION_STATE.md` for
current capability status and `docs/REMAINING_GAPS.md` for what's next.

---

## 2026-08-20 - Phase 9: GUI project header & recovery UX

**Persistent cross-tab project header.** `ProjectHeaderService`
(`src/services/project_header_service.py`) computes 8 at-a-glance
fields (Mode, Stage, Approval, Next approval, Quality, Budget,
Automation, Readiness) fresh from `VideoJob` +
`ProductionReadinessService` + `ApprovalGateService` on every call -
no field is cached or tracked separately from the backend state it
reflects, matching `ProductionReadinessService`'s own "never trust a
stale verdict" convention. Two fields are documented narrower proxies
rather than silently misleading: `current_stage` only reflects the
legacy `ContentPipeline`'s stage tracking (`ContentIntelligencePipeline`'s
12 stages never touch `VideoJob.current_stage`); `budget_state` reports
unfulfilled `ManualAudioRequirement` count, since Phase 7's budget
gating tracks spend per `ProviderProfile` globally, not per job.
Wired into `ProjectWorkspaceView`: a header row inserted below the
project-name heading, cleared and rebuilt from scratch on every
`refresh()` (matching this codebase's established clear-and-rebuild
pattern for dynamically refreshed widget rows, rather than mutating
labels in place). `approval_mode_label()`/`APPROVAL_MODE_PRESETS` were
extracted out of `ContentStudioView` into a new shared
`src/desktop/approval_mode_labels.py` so both surfaces describe a
project's approval policy identically instead of duplicating the
preset-matching logic.

**Recovery UX for step failures.** Every workspace view had its own
identical `_record_error(job, message)` helper that appended to
`VideoJob.errors` and showed a dismiss-only `QMessageBox.warning`. All
6 (`ContentStudioView`, `ClipWorkspaceView`, `ProductionAudioView`,
`RenderWorkspaceView`, `QualityCenterView`, `PackagingView`) now route
through a new shared `show_recoverable_error()`
(`src/desktop/recovery_dialog.py`), which adds a real Retry action
button that re-invokes the exact handler/stage that failed (with its
original arguments recaptured via closure) rather than just
dismissing the error. This is deliberately *not* the same
per-classified-reason recovery `AssetModuleFailure` offers elsewhere
(e.g. "search stock" vs. "request manual upload") - these 19 call
sites across the 6 views only ever have a raw exception message, not
a typed failure reason, so "try again" is the one honest recovery
action available without fabricating unsupported choices; documented
as a real, larger remaining gap in `docs/REMAINING_GAPS.md`. The
render-workspace case needed one extra piece of plumbing: retrying a
failed render replays it with its original `user_input` (e.g.
per-scene asset decisions), which required threading `user_input`
through the worker thread's `failed` signal into
`_handle_render_failed()` rather than losing it once the worker
thread's closure went out of scope.

All existing GUI tests that monkeypatched `QMessageBox.warning` per
view module to avoid blocking on a real modal `exec()` call under the
offscreen Qt test platform were updated to patch
`show_recoverable_error` instead (5 test files); a new
`tests/test_recovery_dialog.py` unit-tests the dialog itself (no
retry falls back to plain warning; clicking Retry invokes the
callback; clicking OK does not) by monkeypatching `QMessageBox.exec`/
`.clickedButton` rather than actually blocking on a real dialog.

Caught one ordering bug of its own while wiring this in: every
`_record_error()` initially called `self._on_change()` *before*
showing the dialog, so the error would be visible on screen the
instant it happened. But `on_change()` here is
`ProjectWorkspaceView.refresh()`, which tears down and rebuilds every
workspace's widgets via `deleteLater()` - and `ContentStudioView`'s
settings-save retry closure captures the live `QComboBox`/`QLineEdit`
widgets it needs to re-read. `deleteLater()` is deferred, and the
dialog's `exec()` runs a nested Qt event loop, so those deferred
deletions could fire *during* the dialog, before Retry was even
clicked - a click-Retry-after-refresh would then call into an already
-deleted C++ object. Fixed by showing the dialog (and running any
resulting retry) before calling `on_change()`, matching the original
pre-Phase-9 ordering, so a retry closure's captured widgets are
guaranteed to still be the current build's widgets.

## 2026-08-20 - Phase 8: Dry-run as an explicit execution mode

Added `ExecutionMode` (`DRY_RUN`/`LIVE`/`MIXED`,
`src/models/advanced_settings.py`), wrapping rather than replacing
`AdvancedSettings.dry_run: bool` for backward compatibility. A
`model_validator` uses `model_fields_set` to detect which of the two
fields a caller explicitly set and derives the other; contradictory
explicit values are rejected (except under `MIXED`, which has no
boolean equivalent so no match is enforced). Old serialized project
files that only ever wrote `dry_run` load correctly and derive
`execution_mode` from it - proven by a dedicated backward-compatibility
test using a hand-written old-shape JSON string.

`MIXED` mode supports a genuine per-provider live/dry-run mix via
`provider_execution_overrides: dict[ProviderCategory, ExecutionMode]`
and `resolve_execution_mode(category)`: an explicit per-category
override always beats the global mode; an unlisted category under a
global `MIXED` mode resolves to `DRY_RUN`, not the literal `MIXED`
value - this was a real bug in the first implementation, caught by its
own test (`resolve_execution_mode`'s dict `.get()` fallback returned
`self.execution_mode` directly, which could literally be `MIXED`,
before being fixed to explicitly check for and substitute `DRY_RUN`).

Wired into `ProductionApplicationFactory` - the one place in the
codebase that actually constructs real-vs-dry-run provider instances -
for its music/sound-effect dry-run-provider fallback, with a test
proving MIXED mode resolves the two categories independently (one
overridden to LIVE, the other falling through to the DRY_RUN default).
Deliberately not wired further: `render_orchestrator_service.py`,
`runtime_configuration_loader.py`, `startup_diagnostics.py`, and
`settings_view.py` all still read the plain `dry_run` boolean, which
stays correctly synced - none of those are genuinely "one provider
among several categories" the way music/SFX are, so wiring them
carried less leverage for this pass.

Also found while touching this area: `tests/test_advanced_settings.py`
was another module-level print-script with zero real pytest test
functions (the third one found this session, after
`test_provider_budget_service.py` and the stock-acquisition suite) -
rewritten into 17 real, isolated tests since it directly covers the
model being modified.

## 2026-08-20 - Phase 7: Budget gating beyond LLM calls

Extended `ProviderBudgetService` gating - previously LLM-only - to
voice/music/SFX (`MediaGenerationPipeline.run_voice/.run_music/
.run_sound_effects`) and stock footage (`StockAcquisitionService.acquire()`).
Opt-in by design: a `budget_service` plus a `*_profile_id`/`profile_id`
at construction, and `estimated_cost_usd` on the call itself (defaults
`0.0`, which never blocks and never reserves) - none of these four
providers has a native per-call cost estimate today, unlike LLM
requests, so gating only actually engages once a caller supplies a
real number. Every pre-Phase-7 caller and test is unaffected. Check→
reserve happens before the provider call; release happens on any
failure path; a successful call leaves the reservation in place (the
estimate stands as the recorded spend, since none of these providers
reports back an actual cost to reconcile against). `StockAcquisitionService`
reports a budget block as a structured `AssetModuleFailure` (new
`AssetFailureReason.BUDGET_EXCEEDED`) rather than raising, matching
that service's existing typed-result convention rather than importing
`MediaGenerationPipeline`'s exception-based one.

This was flagged earlier in the session (alongside secret encryption)
as one of the two gaps that actually matter before real API keys get
added - a misconfigured or runaway voice/music/SFX/stock call
previously had zero budget safety net, unlike LLM calls.

Two real gaps found while building this, both left open rather than
expanded into: (1) no cost-estimation source exists yet for any of
these four providers - gating is wired but dormant until a pricing
layer is built on top; (2) `ProviderRegistry`/`ProviderProfile` aren't
wired to these services' actual provider objects - a caller must know
and pass the right `profile_id` by hand, there's no automatic
resolution from "the voice provider this job uses" to its budget
profile.

Also found and partially fixed, unrelated to this phase's own scope
but directly in the files touched: the entire pre-existing
stock-acquisition test suite (`test_stock_acquisition_service.py`,
`test_scene_stock_acquisition_workflow.py`,
`test_stock_acquisition_request.py`, ~716 lines) and
`test_provider_budget_service.py` were module-level print-scripts with
zero real pytest test functions - they "pass" regardless of whether
their own assertions hold. Rewrote `test_stock_acquisition_service.py`
into 12 real, isolated tests (needed genuine coverage of the exact
service being modified); flagged `test_provider_budget_service.py` as
a separate task; left the other two stock-acquisition files as a known,
documented gap rather than scope-creeping this phase further.

## 2026-08-20 - Phase 6: Asset provenance (reconciled, not duplicated)

Closed the second half of Phase 6 (render identity was already pulled
forward into Phase 5). Audited every field the spec's unified asset
provenance model asks for against what already exists, rather than
building a second model by default: `asset_id`/`created_at` already
exist on every model via `MissionBaseModel`; `provider`/`source`
already exist as `VideoClip.provider`/`.source_type`;
`original_request` is already covered by `VideoClip.prompt` and
`SceneAssetState.local_search_query`/`.stock_search_query`;
`project_id` isn't meaningful per-asset. Only three fields were
genuinely missing - added directly to `VideoClip` instead of a
competing model that would have duplicated the rest: `scene_id`
(wired into `SceneAssetVideoClipBuilderService.build_clips`),
`checksum` (SHA-256 via the new `AssetProvenanceService`), `qc_status`
(`AssetQCStatus`, `src/models/asset_provenance.py` - defaults
`PENDING`, no automated QC pipeline exists yet to advance it further).

Deliberately not built: `source_version` (needs session-spanning state
that would belong on `SceneAssetState`, not a freshly-rebuilt
`VideoClip` - out of scope for this pass) and automatic checksum
computation inside `build_clips()` itself (that method rebuilds the
*entire* clip list from scratch on every bulk reassignment, and this
desktop app has no background threading anywhere - hashing every ready
video file synchronously on the GUI thread on every such call risked
real UI freezes for larger asset libraries). `AssetProvenanceService`
is real and tested, just callable on demand rather than auto-wired
into that specific hot path.

Adding `scene_id` as a field `build_clips()` now reads surfaced a
pre-existing test-fixture gap across 3 files (`test_asset_stage.py`,
`test_pipeline_adapter_integration.py`,
`test_scene_asset_video_clip_builder_service.py`): each used
`SceneAssetState.model_construct()` (which bypasses required-field
validation) without ever setting `scene_id`, which the real
constructor has always required. Fixed by adding `scene_id=...` to
each fixture rather than making the new code defensive - real
construction paths always provide it; only the fast-construction test
escape hatch didn't.

## 2026-08-20 - Phase 5: Final Preview (with render identity pulled forward from Phase 6)

Added `FinalPreview`/`FinalPreviewAction`/`FinalPreviewStatus`
(`src/models/final_preview.py`, append-only on
`VideoJob.final_previews`) and `FinalPreviewService`
(`src/services/final_preview_service.py`) implementing the four spec'd
actions - APPROVE_FINAL, RETURN_TO_EDITING, REPLACE_SCENE,
REGENERATE_AUDIO. The spec explicitly requires binding a preview to
"an exact render identity," which didn't exist yet (that was Phase 6's
job) - rather than build a loose placeholder, built the real thing:
`RenderIdentityService` (`src/services/render_identity_service.py`), a
deterministic SHA-256 over video timeline + audio timeline + render
settings, order-independent and computable from inputs alone (the
produced output file is recorded separately, not hashed - identity has
to be answerable before a render exists, not just after). This is the
first half of Phase 6, done two phases early because Final Preview
had no way to function without it; the second half (unified asset
provenance model) stayed out of scope since nothing in Phase 5 needed
it.

`FinalPreviewService.is_current(job)` never trusts a stored verdict -
it recomputes the identity fresh and also checks
`InvalidationService.is_stale(job, "render_result")` on every call, so
an approved preview that no longer matches the current render surfaces
immediately as a new `BLOCKING` `BlockerCode.FINAL_PREVIEW_STALE` via
`ProductionReadinessService`, not just silently stays "approved."
Wired into Quality Center as a new "Final preview" card.

Deliberate design choice, not a shortcut: `FinalPreviewAction` is its
own vocabulary rather than reusing Phase 1's `HumanApprovalAction` -
REPLACE_SCENE/REGENERATE_AUDIO are workflow re-entry commands, not
approve/reject outcomes, and forcing them into the shared approval
vocabulary would have blurred it for every other decision point.
REPLACE_SCENE/REGENERATE_AUDIO themselves only record the human's
stated intent; the actual work already happens through Clip
Workspace/Production Audio, which already invalidate correctly on
their own.

Building this surfaced one real bug: `FinalPreviewService.create_preview()`
originally let `RenderIdentityService`'s `ValueError` (missing
timeline) propagate raw, while the GUI handler only caught
`RuntimeError` - a render marked successful without both timelines set
would have crashed the "Create final preview" button instead of
showing an error. Fixed by having `create_preview()` present a single
`RuntimeError` contract for every precondition failure, plus widening
the GUI handler's catch to match this codebase's established
`(RuntimeError, ValueError)` convention as defense in depth.

## 2026-08-20 - Phase 4: Unified production audio hardening

Added `MediaGenerationPipeline.run_all_audio()`, coordinating voice,
timeline, music, and sound-effect generation as one action: reuses
whatever is already valid, regenerates whatever is missing or stale,
and reports every component's outcome individually
(`AudioGenerationSummary`/`AudioComponentResult`/`AudioComponentStatus`
- REUSED/GENERATED/FAILED/SKIPPED/MANUAL_REQUIRED) instead of failing
atomically on the first problem. Voice reuse is checked against a new
`VideoJob.voice_script_version` field, set from
`ScriptVersionHistory.current_version.version_number` whenever voice
generation succeeds - so a script revision correctly forces voice to
regenerate even though `run_revision` never touches `voice_status`
directly. An unconfigured music/SFX provider now produces an explicit
`ManualAudioRequirement` (`src/models/manual_audio_requirement.py`,
deduplicated across repeat calls) instead of only a transient
exception, surfacing as a `BLOCKING` blocker via
`ProductionReadinessService`. Wired into Production Audio's GUI as a
"Generate all audio" button plus a last-run summary card.

Building the reuse-detection logic surfaced two real, pre-existing
bugs that had nothing to do with Phase 4 directly but blocked it:
`run_voice` called `attach_many(..., replace=False)`, which raises
`ValueError` the second time voice is generated for a job that already
has voice tracks - simply clicking "Generate voiceover" twice already
crashed, before any of this phase's code existed. `run_music`/
`run_sound_effects` had no duplicate-guard at all and would silently
accumulate a second music track or duplicate SFX cues on a second
call. Fixed by having all three replace their own prior output for the
same scope instead of only ever appending. Also caught and fixed: an
earlier version of Phase 3's invalidation matrix incorrectly marked
`video_timeline` stale whenever audio was regenerated - `run_all_audio`
calling the same job twice immediately exposed this (the timeline
never got reused, since it was marked stale by the very audio stages
that ran right after it was built). `GenreTimelinePipelineService`
takes only `scenes`/`clips`/`genre_id` and embeds no audio data, so
this was simply wrong; corrected in both `invalidation_service.py` and
`docs/ARCHITECTURE.md`'s matrix table.

Known gap: `ManualAudioRequirement.fulfilled`/`.provided_file` exist on
the model and `ProductionReadinessService` already respects them, but
nothing in the GUI sets them - a human who manually supplies a music
file today has no way to clear the resulting blocker short of editing
the project JSON directly.

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
