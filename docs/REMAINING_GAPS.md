# Remaining Gaps

Actionable register, derived from `docs/IMPLEMENTATION_STATE.md`. Ordered
by leverage (cheapest/most-unblocking first within each phase), not by
the master prompt's section numbers. A gap moves out of this file (not
just gets marked done) once its row in `IMPLEMENTATION_STATE.md` says
Done and it has tests.

## Phase 1 - Approval runtime & decision history

- [x] **Approval runtime gating.** Done via `ApprovalGateService`
      (`src/services/approval_gate_service.py`), wired into
      `ContentIntelligencePipeline` for its 6 stages with a matching
      named decision point. `run_all()` stops at the first pending gate
      and the pending state persists on `VideoJob.content_decisions`,
      surviving a restart. `MediaGenerationPipeline` gating is **not**
      included - it has no matching named decision points in
      `ApprovalPolicyConfig` today and was out of scope for this pass.
      Idempotent skip-on-re-run for `run_all()` is a separate, deferred
      concern (see note below).
- [x] **Decision history.** Every gated stage appends a
      `ContentDecisionRecord`; resolving one appends a new record
      rather than mutating the pending one. Approval History GUI card
      added to `ContentStudioView` (newest first, Approve/Reject wired
      to `ContentIntelligencePipeline.resolve_approval()`).

**Deferred out of this phase, deliberately:** skip-already-completed-stage
idempotency for `run_all()` re-entry after a restart. Today, calling
`run_all()` again always restarts from stage one rather than resuming
where it left off - correct artifacts already on `VideoJob` are simply
regenerated. This is a real gap (see Phase 2/10's restart-test items)
but is a separate, larger concern from "does an approval gate actually
stop the pipeline," which is what this phase delivers.

## Phase 2 - Readiness & typed blockers

- [x] **Typed `Blocker` model.** `src/models/blocker.py`: `Blocker`
      (`code`, `stage`, `severity`, `message`, `affected_artifact`,
      `retryable`, `recovery_action`), `BlockerCode`, `BlockerSeverity`.
- [x] **`ProductionReadinessService`.** `src/services/production_readiness_service.py`
      evaluates one `VideoJob` into a `ProductionReadinessReport`
      (`BLOCKED`/`READY_FOR_RENDER`/`READY_FOR_FINAL_EXPORT`/`COMPLETED`
      + a list of `Blocker`s), covering script/scenes/pending approval
      gates (reuses `ApprovalGateService.all_pending`)/per-scene asset
      readiness/audio timeline/video timeline/render result/policy
      report. Wired into Quality Center's new "Production readiness"
      card (`src/desktop/views/quality_center_view.py`) - the existing
      "Post-render checklist" card is left as-is since it covers
      genuinely different downstream artifacts (SEO/thumbnail/final
      export) the readiness service doesn't model.
- [x] **Retrofit `AssetModuleFailure`.** `ProductionReadinessService.
      _asset_blockers` converts a scene's `active_failure` into a
      `Blocker` (recoverable → WARNING, unrecoverable → BLOCKING),
      reusing `AssetModuleFailure.message`/`.recoverable` rather than
      replacing the model.
- [ ] **Retrofit `MediaGenerationPipeline`/`ContentIntelligencePipeline`'s
      bare `RuntimeError` messages onto `Blocker`.** Deliberately not
      done in this pass - both pipelines' `run_*` methods raise on
      missing prerequisites and the GUI already catches
      `(RuntimeError, ValueError)` and displays the message
      (`_handle_run_ci_stage`, `_run_stage`), with real test coverage
      of that behavior. Converting these to return/raise `Blocker`-
      shaped errors touches every stage method in both pipelines plus
      their GUI call sites and error-path tests - a larger, riskier
      change than fits this phase. `ProductionReadinessService` already
      reports the same "missing prerequisite" conditions independently
      (e.g. `SCRIPT_NOT_GENERATED`, `TIMELINE_NOT_BUILT`) via its own
      inspection of `VideoJob` state, so the readiness signal exists
      today even though the exceptions themselves aren't yet
      `Blocker`-typed.
- [ ] **Wire `ProductionReadinessService` into Render/Clip workspace
      readiness indicators**, not just Quality Center - those views
      currently derive their own "is this scene/render ready" logic
      locally.

## Phase 3 - Selective invalidation

- [x] **Formalize the invalidation matrix** (in both code and
      `docs/ARCHITECTURE.md`) for: script change, scene replacement,
      audio regeneration - the three examples in the master prompt.
      `InvalidationService` (`src/services/invalidation_service.py`),
      matrix documented in `docs/ARCHITECTURE.md`.
- [x] **Extend the pattern to scene plan / asset / audio / timeline /
      render.** Wired into `ContentIntelligencePipeline.run_revision`
      (script change), `BulkStockAssignmentService`/
      `BulkClipIngestionService` (scene replacement), and
      `MediaGenerationPipeline.run_voice/.run_music/.run_sound_effects`
      (audio regeneration). `StaleArtifact` records feed
      `ProductionReadinessService` as `BLOCKING` blockers, so staleness
      is visible in Quality Center without a separate GUI surface.
- [x] Regression tests per dependency path. `tests/test_invalidation_service.py`
      (10 tests: one per trigger's marking behavior, the `video_clips`/
      `audio_timeline` same-call exclusions, no-op/dedup cases,
      `is_stale`/`clear_stale`).
- [ ] **`render_result` staleness is never cleared.** Every other
      wired field (`scenes`, `scene_asset_states`, `video_clips`,
      `video_timeline`, `audio_timeline`) has a `clear_stale()` call at
      the point it's regenerated; the render pipeline
      (`RenderOrchestratorService` and friends) does not, so a
      `render_result` marked stale by a scene replacement or audio
      regeneration stays flagged stale even after a successful
      re-render. Deliberately deferred - the render pipeline is the
      one subsystem with real checkpoint/resume machinery and higher-
      risk to touch without a focused pass of its own.
- [ ] **`AssetPipelineStage` (the render pipeline's own asset-
      resolution stage, `src/pipeline/asset_stage.py`) does not call
      `InvalidationService`.** It's the *initial* asset-resolution
      path for a fresh render run, not a "replace an existing scene"
      path, so in practice it rarely has anything downstream to
      invalidate yet - but this hasn't been verified with a test, and
      the exclusion is a judgment call, not a proven-safe one.

## Phase 4 - Unified production audio hardening

- [x] **"Generate All Audio"** - `MediaGenerationPipeline.run_all_audio()`
      coordinates voice/timeline/music/SFX as one action, reusing
      whatever is still valid and reporting each component's outcome
      individually (`AudioGenerationSummary`) rather than failing
      atomically. Wired into Production Audio's GUI.
- [x] **Bind narration to the exact approved script identity/version.**
      `VideoJob.voice_script_version` is set from
      `ScriptVersionHistory.current_version.version_number` whenever
      `run_voice` succeeds; `run_all_audio`'s voice-reuse check compares
      it against the job's *current* version, so a script revision
      correctly forces a voice regeneration even though `run_revision`
      doesn't touch `job.voice_status` directly.
- [x] **`ManualAudioRequirement`** (`src/models/manual_audio_requirement.py`)
      - an unconfigured music/SFX provider now produces an explicit,
      persisted requirement (deduplicated across repeat calls) instead
      of only a transient exception message, and unfulfilled ones
      surface as `BLOCKING` blockers via `ProductionReadinessService`.
      **Not implemented:** any GUI affordance to mark a requirement
      `fulfilled` with a `provided_file` - the model and readiness
      wiring exist, but nothing in the app sets those fields today, so
      a manually-supplied file has no way to actually clear the
      blocker short of editing the project JSON by hand.

**Bugs found and fixed while building this** (not part of the original
Phase 4 scope, but directly blocked it): `run_voice` called
`VoiceTimelineService.attach_many(..., replace=False)`, which raises
`ValueError` if called a second time on a job that already has voice
tracks - meaning simply clicking "Generate voiceover" twice already
crashed, before any Phase 4 code existed. `run_music`/
`run_sound_effects` had no duplicate-guard at all and would silently
accumulate a second music track / duplicate SFX cues on a second call.
Fixed by making all three replace their own prior output for the same
scope (per-scene for voice, whole-timeline for music/SFX) instead of
only ever appending. Also: an earlier version of the Phase 3
invalidation matrix incorrectly marked `video_timeline` stale on audio
regeneration; `run_all_audio`'s reuse-detection surfaced this
immediately (a second call would never reuse the timeline). Fixed in
`docs/ARCHITECTURE.md`'s matrix and `invalidation_service.py` - see
that file's audio-regeneration row.

## Phase 5 - Final Preview

- [ ] `FinalPreview` model bound to an exact render identity (depends on
      Phase 6's render identity).
- [ ] APPROVE_FINAL / RETURN_TO_EDITING / REPLACE_SCENE /
      REGENERATE_AUDIO actions, each persisted, each able to invalidate
      the current approval when the render changes.

## Phase 6 - Render identity & asset provenance

- [ ] **Deterministic render identity**: SHA-256 (or equivalent) over
      video timeline identity + audio timeline identity + render
      settings + output identity.
- [ ] **Unified asset provenance model** (`asset_id`, `asset_type`,
      `source`, `provider`, `original_request`, `project_id`,
      `scene_id`, `created_at`, `source_version`, `checksum`,
      `qc_status`) - reconcile with the fields `Scene`/`VideoClip`/
      `AssetCandidate` already carry rather than duplicating them.

## Phase 7 - Budget gating beyond LLM calls

- [ ] Extend `ProviderBudgetService.check_request()`/`.reserve()` gating
      to voice/music/SFX/stock provider calls, matching the existing
      LLM-call pattern in `src/services/llm/llm_service.py`.
- [x] ~~Delete the dead empty file `src/services/provider_budget_service.py`~~
      Done in Phase 0 - it was genuinely empty and unimported; the real
      implementation lives in `src/services/budget/`.

## Phase 8 - Dry-run as an explicit execution mode

- [ ] Introduce a `DRY_RUN`/`LIVE`/`MIXED` enum replacing (or wrapping,
      for backward compatibility) `AdvancedSettings.dry_run: bool`.
- [ ] `MIXED` should allow a per-provider live/dry-run mix - decide the
      resolution rule (explicit per-provider override beats the global
      mode) before implementing.

## Phase 9 - GUI: project header & recovery UX

- [ ] Persistent cross-tab project header (Project Name / Mode / Current
      Stage / Approval Mode / Next Approval / Quality State / Budget
      State / Automation State / Readiness State) reading only from
      canonical backend state (`VideoJob` + the new readiness service).
- [ ] Structured recovery UX for voice/music/render/content-intelligence
      failures, matching the asset workflow's existing recovery-option
      pattern instead of a bare `QMessageBox.warning` string.

## Phase 10 - CI, pre-commit, and testing gaps

- [ ] `.github/workflows/` running ruff → black --check → mypy → pytest
      on every push/PR.
- [ ] `.pre-commit-config.yaml` (ruff, black, basic whitespace checks).
- [ ] Restart tests for content-intelligence stages (once Phase 1's
      waiting-state persistence exists to test against).
- [ ] Formal invalidation-matrix regression tests (Phase 3).
- [ ] One true golden-path end-to-end test: create project → research →
      content plan → script → approve → assets → audio → timeline →
      render → final preview → export.

## Explicitly out of scope

- Google Flow, or any browser automation targeting Google Flow's web UI.
  See `AGENTS.md`.
