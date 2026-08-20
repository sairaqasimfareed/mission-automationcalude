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

- [x] `FinalPreview` model bound to an exact render identity.
      `src/models/final_preview.py` + `FinalPreviewService`
      (`src/services/final_preview_service.py`), bound via the
      `RenderIdentityService` built for this phase (see Phase 6 below -
      done early, out of order, because Final Preview cannot function
      without it).
- [x] APPROVE_FINAL / RETURN_TO_EDITING / REPLACE_SCENE /
      REGENERATE_AUDIO actions, each persisted (append-only on
      `VideoJob.final_previews`, matching `content_decisions`/
      `script_version_history`), each able to invalidate the current
      approval when the render changes - `FinalPreviewService.is_current()`
      recomputes the identity fresh and also checks
      `InvalidationService.is_stale(job, "render_result")`; an
      approved-but-stale preview surfaces as a `BLOCKING` blocker via
      `ProductionReadinessService`. REPLACE_SCENE/REGENERATE_AUDIO are
      recorded as stated intent only - the actual work happens through
      Clip Workspace/Production Audio, which already call
      `InvalidationService` themselves.
- [ ] **Deliberate design gap, not yet resolved**: `FinalPreviewAction`
      is its own vocabulary, separate from `ApprovalGateService`'s
      `HumanApprovalAction`. Reusing Phase 1's approval infrastructure
      was considered and rejected - REPLACE_SCENE/REGENERATE_AUDIO are
      workflow re-entry commands, not approve/reject/changes-requested
      outcomes, and forcing them into that vocabulary would have blurred
      its generality across every other decision point. Worth revisiting
      if a future decision point needs the same shape.

## Phase 6 - Render identity & asset provenance

- [x] **Deterministic render identity**: `RenderIdentityService`
      (`src/services/render_identity_service.py`) - SHA-256 over video
      timeline identity + audio timeline identity + render settings.
      **Output identity is deliberately not hashed** - the identity
      must be computable from inputs alone (before a render exists), and
      hashing the actual output file's bytes would require file I/O this
      service has no need for; the produced `output_file` is recorded
      separately on `FinalPreview` instead of folded into the hash.
- [x] **Unified asset provenance, reconciled rather than duplicated.**
      Audited every field the spec's provenance model asks for against
      what already exists: `asset_id`/`created_at` already exist on
      every model (`MissionBaseModel`); `provider`/`source` already
      exist as `VideoClip.provider`/`.source_type`; `original_request`
      is already covered by `VideoClip.prompt` and
      `SceneAssetState.local_search_query`/`.stock_search_query`.
      `project_id` isn't needed per-asset (assets aren't referenced
      outside their containing job). Only 3 fields were genuinely
      missing, added to `VideoClip`: `scene_id` (wired into
      `SceneAssetVideoClipBuilderService.build_clips`), `checksum`
      (`AssetProvenanceService.compute_checksum()`, SHA-256), `qc_status`
      (`AssetQCStatus`, `src/models/asset_provenance.py` - defaults
      `PENDING`, nothing sets it further since no automated QC pipeline
      exists yet). No separate `AssetProvenance` model was built - once
      the 3 gaps were filled, a second model would only have duplicated
      fields that already exist, which is exactly what this item asked
      *not* to do.
- [ ] **`source_version` was deliberately not added.** Tracking how
      many times a scene's asset has been replaced needs
      session-spanning state (it can't live on a freshly-rebuilt
      `VideoClip`, since `build_clips()` reconstructs the whole list
      from scratch every call) - it would belong on `SceneAssetState`
      instead, which already persists across rebuilds. Not built this
      pass; flagged rather than silently dropped.
- [ ] **Checksum computation is not automatic.** `build_clips()`
      rebuilds the *entire* clip list from scratch on every bulk
      reassignment (not just the changed scene); hashing every ready
      video file synchronously on the GUI thread on every such call
      risked real, noticeable freezes for larger asset libraries -
      there is no background-threading in this desktop app today (see
      Phase 9). `AssetProvenanceService.compute_checksum()`/`.annotate()`
      are real and tested but only callable on demand, not wired into
      the hot path.

## Phase 7 - Budget gating beyond LLM calls

- [x] Extend `ProviderBudgetService.check_request()`/`.reserve()`/`.release()`
      gating to voice/music/SFX/stock provider calls.
      `MediaGenerationPipeline.run_voice/.run_music/.run_sound_effects`
      and `StockAcquisitionService.acquire()` all gate the same way:
      opt-in `budget_service` + a `*_profile_id`/`profile_id` at
      construction, `estimated_cost_usd` on the call (defaults `0.0` -
      never blocks, never reserves, so every pre-Phase-7 caller and
      test is unaffected). Check→reserve before the provider call,
      release on any failure path, left reserved on success.
      `StockAcquisitionService` reports a block as a structured
      `AssetModuleFailure` (new `AssetFailureReason.BUDGET_EXCEEDED`)
      rather than raising, matching that service's existing
      typed-result convention; `MediaGenerationPipeline` raises
      `RuntimeError`, matching its existing convention.
- [x] ~~Delete the dead empty file `src/services/provider_budget_service.py`~~
      Done in Phase 0 - it was genuinely empty and unimported; the real
      implementation lives in `src/services/budget/`.
- [ ] **No real cost-estimation source exists yet for any of these four
      providers.** Gating is real and tested, but it only actually
      engages when a caller supplies a genuine `estimated_cost_usd` -
      today, nothing in the codebase computes one (no ElevenLabs
      character-count pricing, no stock-provider per-download cost).
      `run_all_audio()` and the GUI's "Generate all audio"/Clip
      Workspace call sites all still call these methods with the
      default `0.0`, so budget gating is wired but dormant until a
      real pricing/estimation layer is built on top - a separate,
      larger feature this phase didn't attempt.
- [ ] **`ProviderRegistry`/`ProviderProfile` are not wired to these
      four services' actual provider objects at all today.** Gating
      requires a caller to explicitly pass a `profile_id` string; there
      is no `ProviderSelectionService`-driven resolution from "the
      voice provider this job is configured to use" to "the matching
      `ProviderProfile` in the registry" for these categories - that
      bridge (between the Provider Center's profile system and the
      simpler `providers: list[...]` abstraction `VoiceGenerationService`/
      `MusicGenerationService`/`SoundEffectGenerationService`/
      `StockAcquisitionService` use) doesn't exist. Building it would
      let a configured budget apply automatically instead of requiring
      a caller to know and pass the right profile id by hand.
- [ ] **Found while auditing this area, unrelated to Phase 7's own
      scope but directly in the files touched:** `tests/test_provider_budget_service.py`
      and the entire pre-existing stock-acquisition test suite
      (`tests/test_stock_acquisition_service.py`,
      `tests/test_scene_stock_acquisition_workflow.py`,
      `tests/test_stock_acquisition_request.py` - ~716 lines total)
      were module-level print-scripts with zero `def test_` functions,
      not real pytest tests - pytest imports and "passes" them
      trivially regardless of whether their assertions hold, since a
      failed `assert` during import surfaces as a collection error,
      not a normal test failure, and nothing distinguishes one
      scenario from another. `test_stock_acquisition_service.py` was
      rewritten into 12 real, isolated pytest tests as part of this
      phase (needed real coverage of the exact service being changed);
      the other three files are unchanged - `test_provider_budget_service.py`
      is flagged as a separate task, the two `test_scene_*`/
      `test_stock_acquisition_request.py` files are not.

## Phase 8 - Dry-run as an explicit execution mode

- [x] Introduce a `DRY_RUN`/`LIVE`/`MIXED` enum (`ExecutionMode`,
      `src/models/advanced_settings.py`), wrapping (not replacing)
      `AdvancedSettings.dry_run: bool` for backward compatibility. A
      `model_validator` reconciles whichever field a caller explicitly
      set (via `model_fields_set`) and derives the other; setting both
      to contradictory values (outside `MIXED`, which has no boolean
      equivalent) is rejected. Old serialized project files with only
      `dry_run` load correctly and derive `execution_mode`.
- [x] `MIXED` allows a per-provider live/dry-run mix.
      `provider_execution_overrides: dict[ProviderCategory, ExecutionMode]`
      + `resolve_execution_mode(category)`: explicit per-category
      override beats the global mode; an unlisted category under
      global `MIXED` resolves to `DRY_RUN` (safe by default - this was
      a real bug caught by its own test during development, where the
      first implementation returned the literal `MIXED` value instead).
      Wired into `ProductionApplicationFactory`'s music/sound-effect
      dry-run-provider fallback - the one place in the codebase that
      actually constructs real-vs-dry-run provider instances - with
      tests proving MIXED mode resolves the two categories
      independently (`test_mixed_mode_resolves_music_and_sound_effects_independently`).
- [ ] **Not wired beyond the provider factory.** `render_orchestrator_service.py`,
      `runtime_configuration_loader.py`, `startup_diagnostics.py`, and
      `settings_view.py` all still read the plain `dry_run` boolean
      directly rather than `execution_mode`/`resolve_execution_mode()`.
      This is safe (the field stays correctly synced) but means MIXED
      mode's per-category granularity is only visible to
      `ProductionApplicationFactory` - the render engine selection,
      LLM-provider bootstrapping, and GUI settings display all still
      only see the collapsed boolean. Deliberately scoped out: none of
      those are genuinely "one provider among several categories" the
      way music/SFX are, so the leverage of wiring them was lower.

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
