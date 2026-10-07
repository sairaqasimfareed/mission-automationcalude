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

**Stale note, corrected 2026-09-08 (MRA-PRE-4):** this originally said
`run_all()` always restarts from stage one on re-entry, deferring
idempotency as a separate concern. Direct inspection of the current
`ContentIntelligencePipeline.run_all()` shows this was fixed at some
later point in this project's history without this note being
updated: every stage is now guarded (`if job.<artifact> is None:
job = self.run_<stage>(job)`), including the terminal Script Lock
step, whose own comment states the intent directly - *"Guarded on
job.script_lock is None so a second run_all() call on an
already-locked job stays a true no-op, matching this method's own
idempotency guarantee."* No code change made here; this note was
simply describing behavior the code no longer has.

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

## Phase 9 - GUI: project header & recovery UX (Done)

- [x] Persistent cross-tab project header (Project Name / Mode / Current
      Stage / Approval Mode / Next Approval / Quality State / Budget
      State / Automation State / Readiness State) reading only from
      canonical backend state (`VideoJob` + `ProductionReadinessService`)
      via `ProjectHeaderService`, wired into `ProjectWorkspaceView`.
- [x] Recovery UX for voice/music/render/content-intelligence failures:
      `show_recoverable_error()` (`src/desktop/recovery_dialog.py`) offers
      a real Retry action (re-runs the exact handler/stage that failed)
      instead of a dismiss-only `QMessageBox.warning`, across all 6
      workspace views. Deliberately *not* the same per-`AssetFailureReason`
      classified recovery `AssetModuleFailure` offers - these call sites
      only ever have a raw exception message, not a classified reason, so
      per-reason recovery options (choose a different provider, etc.)
      remain a real, larger gap: adding them honestly would require each
      of `MediaGenerationPipeline`/`RenderOrchestratorService`/
      `ContentIntelligencePipeline` to classify its own failures into a
      typed reason first, which none of them do today.

## Phase 10 - CI, pre-commit, and testing gaps (Done)

- [x] `.github/workflows/ci.yml`: ruff → black --check → mypy → pytest on
      every push/PR to `main`, Python 3.13, with ffmpeg + headless Qt
      system libs installed so no test needs to be excluded. Fixing this
      surfaced and fixed two real gaps: `requirements.txt` was missing
      `anthropic`/`openai`/`google-genai`/`google-auth` (the real LLM
      provider SDKs actually imported at runtime); `ruff check .` failed
      repo-wide on 153 pre-existing `UP042` findings for this codebase's
      deliberate `class X(str, Enum)` convention, now formalized as an
      ignored rule in `pyproject.toml` instead of silently red CI.
- [x] `.pre-commit-config.yaml` (ruff --fix, black, trailing-whitespace/
      end-of-file-fixer/check-merge-conflict/large-file-guard hooks).
- [x] Restart tests for content-intelligence stages
      (`tests/test_content_intelligence_pipeline_restart.py`): a real
      `JsonJobStore` round-trip through a *fresh store instance*
      (simulating a process restart, not a same-instance cache hit)
      preserves every artifact, lets a fresh pipeline instance resume the
      next stage, and preserves a pending approval decision.
- [x] Formal invalidation-matrix regression tests
      (`tests/test_invalidation_matrix_wiring.py`): drives the 4 real
      call sites (`ContentIntelligencePipeline.run_revision`,
      `BulkStockAssignmentService`, `BulkClipIngestionService`,
      `MediaGenerationPipeline.run_voice/.run_music/.run_sound_effects`)
      end to end and asserts on `job.stale_artifacts` - proving the
      wiring itself, not just `InvalidationService`'s own matrix logic
      (already covered by `test_invalidation_service.py`).
- [x] One true golden-path end-to-end test: `test_full_pipeline_reaches_final_export`
      (already existed, covering create→research→script→originality→
      scenes→render→assets→SEO→thumbnail→export) extended with Final
      Preview creation and approval, closing the last named step the
      spec's golden-path wording called for. Content-intelligence
      approval gating ("approve") is deliberately not chained into this
      one test - it belongs to a separate pipeline stack
      (`ContentIntelligencePipeline`) with its own dedicated coverage;
      stitching both pipelines into one run would test an integration
      that doesn't exist in the real app.
- Found and fixed while auditing CI test coverage (not originally
  scoped, but directly blocking a green CI run):
  `tests/test_ffmpeg_capability_service.py` was a 4th instance of this
  session's recurring dead-print-script pattern (module-level code, bare
  asserts at collection time, zero real `pytest` test functions) -
  rewritten into 8 real tests, most gated behind a `skipif` when
  ffmpeg/ffprobe aren't on `PATH`.

## Unified workspace shell (Done - reshape only, one decision deferred)

- [x] Left sidebar nav replacing the top button row + a "Run / Resume"
      header action that jumps to whatever `ProductionReadinessService`
      already says is next (`ProjectWorkspaceView`). The persistent
      header itself was already done in Phase 9.
- [ ] **Deliberately deferred**: whether `ContentIntelligencePipeline`'s
      12 stages get promoted to top-level sidebar items (making it the
      one true content path and demoting the legacy `ContentPipeline`'s
      GUI flow) or the sidebar instead supports both flows per project.
      The user explicitly chose the lowest-risk option (reshape only,
      keep today's 7 destinations) rather than deciding this now - see
      `PROJECT_PROGRESS.md`'s entry for the full options considered.
- [ ] Real per-project budget tracking (a genuine dollar figure like the
      design doc's "$4.20 / $15", not the current `ManualAudioRequirement`
      -count proxy) - blocked on Phase 7's budget gating being extended
      from per-`ProviderProfile` spend to per-job spend, which is new
      backend work, not a GUI change.

## GUI-8 validation finding: monolithic full-suite pytest run hangs (Done)

- [x] Running the entire test suite as one `pytest tests/` process
      reproducibly hung. Reproduced twice independently (a full
      unscoped run stalling at ~24% for 9+ minutes with zero log
      output, confirmed via file-modify-time; a minimal 2-file
      reproduction with `test_desktop_app_integration.py` +
      `test_desktop_theme_and_icons.py`, 48 tests, hanging
      deterministically at the same point both times). See
      `docs/GUI8_VALIDATION_REPORT.md` for the original finding.
      **Root-caused and fixed (MRA-PRE-9 follow-up)**: `py-spy dump`
      against a live, reproduced stall showed the main thread genuinely
      blocked inside `QApplication.setStyleSheet()`/`setStyle()` (called
      by every `apply_theme()` call) - no GUI test anywhere ever
      explicitly closed its `MainWindow`, so top-level widgets
      accumulated without bound on the one shared, process-wide
      `QApplication` singleton every GUI test file's `qapp` fixture
      reuses, and Qt's own style-repolish pass over every current
      top-level widget is what the engine choked on. Fixed with a new
      `autouse` fixture in `tests/conftest.py`
      (`_close_leftover_qt_top_level_widgets`) that closes and deletes
      every leftover top-level widget after each test, using
      `QTest.qWait()` (real wall-clock event-loop pumping, not bare
      `processEvents()`) so the cleanup actually completes. Verified via
      two full, real, non-artificial runs: `test_desktop_app_
      integration.py` alone (15 passed) and the exact original GUI-8
      2-file repro together (52 passed, 0 failed, 0 errors, 2:27) - the
      identical combination GUI-8's own report documented as
      reproducibly hanging now completes cleanly.
      **One disclosed, lower-probability residual risk remains** (not
      reproduced in either real verification run, only under an
      artificially-forced adversarial repro used while developing the
      fix): a deeper, native-code-level Qt/PySide interaction when
      multiple `QThread.finished` signals from earlier tests all become
      deliverable in the same cleanup window - would need a native
      debugger (not just Python-level tooling) to fully diagnose. See
      `docs/MRA_PRE_9_FOLLOWUP_PYTEST_HANG_FIX.md` for the complete
      investigation and evidence.

## MRA-PRE-3 validation finding: scene duration doesn't reconcile against narration length (Done)

- [x] `ScenePlannerAgent.plan_from_generated_script()`/`_subdivide_segment()`
      (`src/agents/scene_planner/agent.py`) - the current, canonical
      content-intelligence pipeline's own scene planner - used to size
      each scene purely from `content_intelligence.scene_density_per_minute`/
      `average_visual_duration_seconds` (genre-policy numbers), with
      zero reconciliation against how long the narration text actually
      assigned to that scene takes to speak. Confirmed real via a real
      end-to-end run: a genre.documentary project produced 4 scenes
      totaling ~30 seconds of allotted scene time for a 600-second
      target project, and render's own `VoiceDirectiveValidationService`
      correctly refused with "Estimated narration duration exceeds the
      scene duration" - a working safety guard, but the canonical
      chain did not reach render (Phase 15 onward) as a result. See
      `docs/MRA_PRE_3_LIFECYCLE_AUDIT.md` for the original finding.
      **Fixed**: `_subdivide_segment()` now sizes each sub-scene as the
      LARGER of (a) a proportional share of the segment's own time
      budget weighted by that sub-scene's own estimated narration
      length (via `NarrationTimingService`, reused rather than a new
      rate constant), or (b) that sub-scene's own actual required
      narration duration - a hard floor, so a segment whose blueprint-
      assigned time span is genuinely too short for its own narration
      gets extended rather than having real speech silently squeezed
      into too little time. Genre density still governs sub-scene
      count and, when the original budget is sufficient, how it's
      shared between sub-scenes. **Proven fixed**: 2 new direct unit
      tests on `ScenePlannerAgent`
      (`test_plan_extends_duration_when_segment_budget_is_too_short_for_narration`,
      `test_plan_weights_scene_duration_by_narration_length_not_equal_split`
      in `tests/test_scene_planner_generated_script.py`), plus the
      original end-to-end regression tripwire
      (`test_content_intelligence_pipeline_scenes_pass_voice_validation_at_render`
      in `tests/test_desktop_app_integration.py`) confirming the exact
      "Estimated narration duration exceeds the scene duration" error
      no longer occurs.

## Follow-on finding: stock footage acquisition fails for a ContentIntelligencePipeline project at render (Done)

- [x] Discovered while confirming the scene-duration fix above: once
      that blocker was removed, the same end-to-end run
      (`test_content_intelligence_pipeline_scenes_pass_voice_validation_at_render`)
      progressed further but then failed at asset acquisition with
      "The selected stock footage could not be acquired." Root cause:
      a content-intelligence-pipeline scene's stock-candidate title is
      built from the scene's full `visual_prompt` text (150-200+
      characters), and `StockAssetStorageService._sanitize_filename()`
      never bounded length - combined with the project/scene path
      prefix this could exceed Windows' `MAX_PATH` (260 characters),
      making `shutil.move()` raise a real `OSError` (confirmed
      reproduction: a 194-character title produced a 278-character
      destination path). Fixed by adding `_MAX_SANITIZED_LENGTH = 80`
      to `_sanitize_filename()` in `stock_asset_storage_service.py`,
      and the identical latent pattern in `asset_storage_service.py`
      (manual uploads, lower real-world risk but same failure mode).
      Proven via a new, teeth-verified test,
      `test_a_long_title_still_produces_a_path_within_windows_max_path`
      in `tests/test_stock_asset_storage_service.py`.

## Follow-on finding: SEO/thumbnail generation unreachable for a ContentIntelligencePipeline project (Done)

- [x] Discovered immediately after the stock-footage fix above, in the
      same end-to-end run: render now succeeded, but
      `workspace.packaging._handle_generate_seo(...)` returned no
      package (`window._job_store.get_seo_package(job.id) is None`).
      Root cause: `SEOContextBuilder.build()` (shared by both SEO and
      thumbnail generation) only ever checked the legacy `job.script`
      field - `ContentIntelligencePipeline` never populates it, only
      `job.generated_script` (+ `job.script_lock` once locked) - so it
      unconditionally raised `ValueError`, caught and recorded to
      `job.errors` by `PackagingView._handle_generate_seo()`/
      `_handle_generate_thumbnail()`, never surfaced as a crash. Worse,
      **the Packaging workspace's own "Generate SEO package"/"Generate
      thumbnail" buttons were permanently hidden** behind "Requires an
      approved script." for every such project, since
      `PackagingView`'s own `script_approved` gate checked the same
      legacy field directly - not just an SEO-specific bug but a
      whole-workspace dead end for the pipeline real projects use
      (MRA-PRE-1 already confirmed this). Fixed by making
      `SEOContextBuilder.build()` accept either provenance (deriving
      `script_title`/`script_content`/`estimated_duration_seconds`
      from `job.generated_script.full_narration` and
      `target_duration_seconds` when present, requiring
      `job.script_lock is not None` as that pipeline's own "approved
      and frozen" equivalent), and factoring `PackagingView`'s gate
      into a shared `_script_is_approved()` helper with the same
      reconciliation. Proven via 2 new tests in
      `tests/test_seo_context_builder.py`
      (`test_build_returns_seo_context_for_a_content_intelligence_pipeline_job`,
      `test_build_raises_for_an_unlocked_content_intelligence_pipeline_script`)
      and by the full end-to-end regression tripwire now reaching SEO,
      thumbnail, and final export with zero errors.

## Follow-on finding: most test files use module-level `assert` instead of `def test_*` functions (MRA-PRE-5)

- [ ] Found while auditing provider/runtime failure-handling test
      coverage: **142 of 367** files matching `tests/test_*.py`
      (~39%) have zero pytest-discoverable `def test_` functions -
      real logic and real `assert` statements execute as a side
      effect of module import instead (the same pattern MRA-PRE-3
      first found in isolation for `test_stock_asset_storage_
      service.py`/`test_asset_storage_service.py`, now confirmed far
      more widespread via a full scan). A live teeth-check (deliberately
      broke a real assertion in `test_voice_generation_service.py`,
      ran pytest against just that file) confirmed this is **not
      silently invisible** - it correctly produces a collection error
      and nonzero pytest exit code, caught by this project's own
      already-established per-file/small-batch validation practice
      (see the GUI-8 full-suite-hang workaround). The real, disclosed
      cost: no individual test selection/filtering within these
      files, one early failing assertion masks every later assertion
      in the same file (Python's `assert` unwinds immediately, unlike
      independent `def test_*` functions), and any tooling that
      counts "collected test items" undercounts real coverage. A full
      `pytest tests/ --collect-only` confirmed 2449 real items and
      zero collection errors at the HEAD this was found on - a clean,
      directly-verified current baseline. Not fixed - a large,
      cross-cutting, mechanical migration across 142 files with real
      regression risk if rushed, correctly out of scope for a
      same-day patch. See `docs/MRA_PRE_5_PROVIDER_RUNTIME_FAILURE_
      AUDIT.md` finding 003 for the full evidence.

## Follow-on: broader GUI sweep for "long content" and "disabled/loading/error states" (MRA-PRE-7)

- [ ] MRA-PRE-7's own working scope named "long content" and
      "disabled/loading/error states" as real remaining gaps - neither
      was in GUI-6's own scoped slices (contrast, keyboard focus, tab
      order, high-DPI, minimum-size). MRA-PRE-7's actual pass this
      session targeted only the two concrete, already-diagnosed
      carry-forwards from MRA-PRE-2 (Google Flow attempt visibility,
      fixed; stale-artifact visibility, found to already work). This
      broader sweep - checking every workspace view handles very long
      text/lists gracefully and every async action has a real
      disabled/loading/error state, not just a happy-path render - was
      not attempted; it needs its own exploratory pass across each
      view, not a same-segment extension. See
      `docs/MRA_PRE_7_GUI_OPERATOR_WORKFLOW_AUDIT.md`'s own
      "Explicitly not covered in this pass" section.

## Deferred by user decision (2026-10-02)

- Render tab: separate "render video without audio" / "render with
  audio" actions (the staged video-only render and audio mux already exist
  in code, nothing calls them) and a chunk-length control. Open design
  question: display-only chunk count plus chunk-capable video-only render
  (recommended) versus a manual "scenes per chunk" setting.
- Removing subtitles from an already-rendered video is not possible;
  re-rendering is required. A subtitle-free master alongside the
  subtitled one was considered and not built.
- Stop/progress UI for the main Render button (needs cancellation support
  in `RenderOrchestratorService`).

## Open findings from the 2026-10-03 render pipeline audit

The audit's four findings (shared output path, stale variants after a
re-render, leftover stage files, stored duration) and the broad
`NotImplementedError` fallback are all fixed - see
`docs/IMPLEMENTATION_STATE.md`. Still open:

- Muse now has a 3s minimum single-clip length (2026-10-04, see
  `docs/IMPLEMENTATION_STATE.md`), so a one-word scene no longer yields a clip
  shorter than two 0.6s crossfades. Clips generated before that keep their
  length until regenerated. The editing rules'
  "transitions exceed the scene" check compares against the script's estimate,
  not the real clip length.
  Clip durations are stored as whole seconds, so Muse's exact trims are rounded.
- Chunk-split renders re-align Audio-tab audio with the same all-crossfade
  assumption as the unchunked path; the downstream chunk logic corrects the
  chunk-boundary hard cuts exactly as it does for the render's own audio.
- Not audited: filter-graph / chunk-boundary / audio-timing math
  (historically the most desync-prone area) - needs real-FFmpeg
  experiments, not code reading.
- `RenderPipelineStage.execute_video_only()` and the chunked-render
  composite path were not given the per-project output directory or the
  real-duration probe; nothing calls the former, and the latter shares
  `render()`'s own output handling.
- Reference-image continuity: identical references are not de-duplicated
  before attaching (subjects that first appear in one scene share one
  extracted frame), and the attach check uses `.first`, so it cannot
  confirm the Nth attachment. Not yet changed - needs a live Flow check.

## Known limits of the 2026-10-06 live findings

- Places' references are never refreshed automatically and the first-extraction location
  picker still cannot tell a place from an object or an overlay: the Remedy Kitchen reference
  is a jar close-up and every Kitchen scene came out as that jar. A better pick needs object or
  text-overlay detection, or an optional manual choice.
- Characters seen only together (Adults and Children share one frame) still share a
  reference; telling people apart in a frame is not built.
- Wardrobe is not carried: the reference carries a face, so an adult wore different clothes
  in scene 9 than in scene 3. Prompts do not yet state the wardrobe.
- Muse text overlays: the generator added an unwanted text panel (scene 5) and an infographic
  with AI-written text including a claim not in the script (scene 6). There is no check for
  on-screen text in generated clips. (2026-10-07: graphic scenes are now prompted with an
  exact-text-only rule and can be switched to live footage, but the generator may still
  ignore either; the generated text is still not checked.)
- Project look (lighting / colour palette / camera feel) is only as good as the generator's
  obedience to it; it is repeated word-for-word in every prompt but nothing verifies the
  clip matched it. Projects compiled before it existed need "Save project look" (or a
  prompt recompile) to pick it up.
- "Show as live footage" uses the project's main place (a LOCATION with a reference); a
  project with no place reference gets live-action framing and the look but no picture.
- Scroll preservation covers the seven job tabs only. Providers, Voices, Settings,
  Dashboard and the Flow/Muse panels rebuild lists rather than card stacks and were
  not changed; if one of them jumps to the top it needs `keep_scroll_on_refresh`.
  Confirmed in the offscreen tests, not yet re-checked by hand in the running app.
- **Aspect ratio (16:9 / 9:16) chosen when a project is created - BUILT 2026-10-07 (see
  IMPLEMENTATION_STATE); what is left is listed at the end of this item.** (Original
  request and findings follow.) The New Project form has only a
  Platform dropdown; output is fixed at 1920x1080 and prompts say nothing about the shape.
  Wanted: after choosing the platform, offer 16:9 or 9:16 (stored on the project, default
  16:9); for 9:16 every clip prompt gets an explicit vertical sentence, for 16:9 nothing is
  added (it is Muse's default).
  *Muse findings (operator's own tests, files inspected 2026-10-07):* a bare "Resolution
  9:16." tag at the end of a prompt came back as a 16:9 picture with blurred bars top and
  bottom. Asking explicitly, in words, for no crop / no letterbox / no blurred bars returned
  a true native vertical clip: 720x1280 (Muse's normal clips are 1280x720), 8.0 s, full
  frame, sharp; the 8 s duration was obeyed. Three clips so far (a close-up, a regenerated
  close-up, an infographic) with the sentence AT THE END of the prompt:
  `Vertical 9:16 portrait video, true full-frame vertical composition, no crop, no letterbox,
  no blurred bars. Compose natively for vertical: main subject centered and fully inside the
  frame.` (operator confirmed this exact sentence works in Muse.) What the operator called "cropped" was composition (a face cut by the frame edge),
  fixed by the "centered and fully inside the frame" half. Muse's own chat claims about its
  output are not reliable (it said "nothing cut at the edges" while a hand still ran off the
  frame) - judge the file. Not yet known: whether it holds in a fresh chat (the app returns
  to the same long Muse chat before each submit, so Muse may remember the instruction).
  *Also needed:* shot planning told the ratio so compositions suit a tall frame ("balanced
  two-shot", "symmetrical" are 16:9 words); a 1080x1920 timeline, portrait title card and CTA
  end card, subtitle placement, portrait thumbnail; Flow should set its own aspect-ratio
  control (its automation can already click it) instead of using prompt wording; the
  export-variant card stays exactly as it is, offering both resolutions (operator
  decision 2026-10-07); changing the ratio after clips exist must warn and invalidate them. Related: the
  graphic-scene text rule is still not sent, and the 9:16 infographic repeated the problem
  (added "safely", dropped "modestly", an invented "Source:" line and a "Trusted Info" badge).
  *Left to do after the build:* a warning (and invalidation of existing clips) when the shape
  is changed after clips exist - today it is chosen at creation only; subtitle placement and
  the thumbnail have not been checked/adapted for a portrait frame; Flow's "9:16" click is
  unverified against the live product; the sentence is unproven in a fresh Muse chat; stock
  or manually uploaded 16:9 clips in a 9:16 project are not letterboxed.
- **AI-written claims on infographic (graphic) scenes** (found 2026-10-07; plan step 1 BUILT
  the same day - the text rule is now in the prompt - steps 2 and 3 not built). The graphic-scene text rule exists on the stored
  prompt but is never sent, so Muse writes its own text. Remedy and the 9:16 test infographic
  both showed it: "safely" where the narration said "can be given", "modestly" dropped from
  "modestly reduce nighttime coughing", "Strongest clinical evidence" for "most of the
  stronger evidence", an invented "Source: Pediatric medical guidelines & clinical trials"
  line and a "Trusted Info" badge, "5ml" labels on icons - on medical content. Plan, in order:
  (1) send an explicit text rule for graphic scenes at the end of the prompt, next to the 9:16
  sentence, e.g. `On-screen text rule: use only the words of this narration: "<narration>".
  You may arrange them as a headline and short points, but add no other words: no sources,
  citations, badges, "trusted" labels, numbers, labels on icons, or stronger wording. Keep the
  narration's own qualifiers such as "can", "may" and "modestly".` - test it first on the
  9:16 infographic scene and compare; (2) flag graphic scenes in the Clip check as "check the
  on-screen text yourself" (human check, no new software); (3) only if Muse still adds
  claims: OCR the generated clip and compare it with the narration (needs an OCR tool bundled
  in the installer), or, for medical topics, draw the infographic text ourselves and use Muse
  for the background only (safest, biggest build). Scenes that are not graphics are left
  alone - the operator likes on-screen text there.
- **To build - from the 2026-10-07 Remedy render review** (operator asked for these to be
  tracked here; none is built):
  1. "Choose another frame" picker for a character's or place's reference: show several
     candidate frames and let the operator pick one. Today "Pick reference again" only
     re-runs the automatic choice.
  2. One continuous music track per video instead of several separately generated pieces
     joined with 1 s fades (a piece can decay to near-silence before its slot ends).
  3. A shared colour grade / shot-to-shot colour matching across scenes (see the locked
     editing list).
  4. Regenerate the clips with picture problems: scene 5's leaked "Evidence-Based Benefits"
     panel, scene 15's mother and baby (different look, no baby reference), the woman who
     changes between scenes. Needs credits and the characters-and-places form.
  5. Fast title-card join. `TitleCardPrependService` joins the title card with FFmpeg's concat
     FILTER, which re-encodes the whole finished render (libx264 medium, crf 20) to add a few
     seconds at the front - slow on this machine (the video pass alone took 28 min). It was
     chosen because a stream-copy join of mismatched files once silently cut the audio short.
     Planned: re-encode only the title clip to the main video's real settings (read with
     ffprobe: size, frame rate, pixel format, profile, audio rate/channels), join with the
     concat demuxer and `-c copy` (+faststart), then verify - total length, audio and video
     stream lengths, and a decode of a few seconds around the seam - and fall back to today's
     full re-encode if any check fails. Risks discussed: a join that passes the length check
     but glitches at the seam or in some hardware players, a small audio click where two copied
     AAC streams meet; the main render is never touched and the fallback keeps today's quality.
     Needs real-FFmpeg tests. The export-variant end-clip join could reuse it later. Not built.
  6. Room between scenes - a per-genre hold after each narrated line. Clips are sized to the
     narration (rounded up to the provider's lengths), so there is no designed pause between
     scenes, only accidental slack (the trailing silence in each voice file, the round-up,
     Muse's 3 s floor); genre only changes the pause style inside a line. Planned: the clip
     runs a little longer than the line before the next scene - about 0.3-0.5 s for
     medical/reaction/comedy, 0.8-1.2 s for horror/storytelling/survival, longer after reveal
     lines, dropped when the line already fills a clip to the provider maximum - plus an
     optional 0.2-0.3 s voice lead-in after the cut. No extra credits (Muse always generates
     10 s and trims; Flow clips are already 4/6/8 s); a Remedy-sized video grows by roughly
     5-10 s. Open: fixed numbers or settable per project. Touches clip sizing for both Flow
     and Muse and the audio timeline offsets; needs tests across both providers. Not built.
  7. BUILT 2026-10-07 (see IMPLEMENTATION_STATE) - uploaded watermark image looks like a
     picture overlay and starts at the wrong moment
     (reported 2026-10-07 on Remedy's export variant). Cause in `ExportVariantRenderService.
     _watermark_image_clause`: the image is overlaid at full opacity at a fixed share of the
     frame width, and the overlay is enabled `between(t,0,...)` - by design "visible from the
     first frame" (the text watermark's 4 s hook-skipping delay was deliberately not applied to
     an uploaded image). When the variant is made from a render that already has the opening
     title card, the watermark therefore shows over the title card. Wanted: it should look
     like a watermark (semi-transparent, small, in a corner - an opacity setting) and start
     when the title card ends (title-card length known from the title-card clip/service), not
     at t=0. Not built.
  8. Subtitle burning option on all three renders (requested 2026-10-07; the earlier "run
     combinations / one button for everything" wish was dropped - the renders stay separate
     buttons as they are). Today subtitles are burned only inside the main render
     (`render_stage` -> `PostRenderSubtitleBurnService`, the Render tab's subtitle toggle), so
     the title-card render and the CTA/watermark (export-variant) render have no subtitle
     option, and wanting subtitles on a video that is already rendered means re-rendering it.
     Wanted: a subtitle burn option on each of the three - main render, title-card render and
     CTA render - that burns the project's subtitles (current caption style) at that point,
     without touching the original file. Interacts with item 5 (each pass re-encodes today) and
     item 7 (the watermark must start after the title card). Not built.
  9. **Auto-generated project look and characters/places, picked or discarded by the
     operator - BUILT 2026-10-07 (see IMPLEMENTATION_STATE); still to do: the face-based
     detector below, and trying it on a real project.** Original request: (raised 2026-10-07; the operator cannot fill the two forms in Content
     Studio > Production handoff by hand, so they must not start blank; not built). Behaviour
     wanted: the app proposes entries on its own and each one can be accepted or discarded;
     typing one by hand stays possible but is no longer the main route.
     - Project look: candidate looks (lighting / colour palette / camera feel) shown as cards
       with Use / Discard - from the genre's ready-made looks and, once clips exist, measured
       from the generated footage (brightness, colour warmth, saturation written as words).
       Deterministic, free. Using one fills and saves the look and recompiles the prompts.
     - Characters and places: after the continuity bible and shot plan exist, one Claude call
       over ALL scenes at once proposes the recurring people and places, each as an entry with
       name, kind, description and scenes, with Accept / Discard (and edit before accepting).
       Accepted entries become identities exactly as the manual form creates them (reference
       picked from the generated clips of their scenes). Candidates and the accept/discard
       state live on the VideoJob (not only in the window) so they survive a restart and a
       discarded one is not proposed again. Later, the stronger detector: recurring faces
       found in the generated clips (the already-downloaded, not yet used SFace model - it
       would also tell people apart in a shared frame), offered as "Person A appears in scenes
       3, 9, 12, 16" with a thumbnail; needs the model bundled in the installer.
     Costs one small Claude call per suggestion run for characters; none for the look.
- Negative constraints are stored on every compiled prompt but never sent to Muse or Flow
  (see IMPLEMENTATION_STATE, 2026-10-07). Needs a decision on what to send: an "Avoid:" line
  with the identity/subject/continuity rules and "no logos or watermarks", the exact-text rule
  for graphic scenes, and "no extra captions" instead of "no on-screen text" elsewhere.
  Whether Muse follows a negative instruction is untested.
- The characters-and-places form is built, but the optional "choose another frame" picker
  (showing several candidate frames) is not: "Pick reference again" re-runs the automatic
  choice only. A regenerated bible keeps manual identities but not their on-screen marks in
  scenes that no longer exist.
- Music is still several separately generated pieces stitched with 1 s fades; a piece can
  decay to near-silence before its slot ends (Remedy's first one is quiet from about 8 s of
  11). One continuous track per video is not built.
- No shared colour grade across scenes (the filter is `clean_neutral`, a faint lift only):
  the bright daylight clip still sits next to dark kitchen ones. Shot-to-shot colour
  matching is on the locked editing list, not built.
- The 1080p video pass took 1,695 s (28 min) for an 84 s video on this machine; the audio
  re-mix is about 33 s. Not changed: needs a measurement on an idle machine first.
- Pacing: clips are sized to the narration (rounded up to the provider's lengths), so
  there is no pause between scenes - only accidental slack (the trailing silence in each
  voice file, the round-up, Muse's 3 s floor). Genre only changes the pause style inside a
  line. Locked for later, NOT built: a per-genre hold after each line (about 0.3-0.5 s
  medical/reaction/comedy, 0.8-1.2 s horror/storytelling/survival, longer after reveals,
  dropped when the line already fills a clip), and an optional 0.2-0.3 s voice lead-in after
  the cut. Touches clip sizing for both Flow and Muse and the audio timeline offsets.
- Not code: clip content (a panel leaking into scene 5's clip, scene 15's different-looking
  mother and baby, the woman changing between scenes, AI-written infographic claims) needs
  regenerating those clips. (The 1:24 length against the 2:00 target was dropped as a gap
  on 2026-10-07 - left as it is.)
- A Muse download that times out leaves an unfinished (UI_CHANGED) attempt that counts as
  in-flight and blocks the account; resuming the download of an already-generated video is
  not built, so it costs a regeneration.
- Single-call Content Studio handlers other than the production stages (script intake/lock,
  revision, hooks, narrative architecture, resolving ambiguities) still run on the window thread.
- Project video provider defaults to Google Flow for every new project; a default per
  channel or genre is not built.

## Known limits of the 2026-10-05 reference frame selection

- The score does not check open eyes: in the test a clip's best frame (score 0.94)
  had the character's eyes closed. A usable frame is not guaranteed a good one.
- A scene introducing several NEW PEOPLE still gives them all the same frame (the
  best face in it); telling two people apart in one frame is not built. (A person
  and a place in one scene do get separate frames.)
- A location frame is the sharpest one with no face dominating - it cannot tell a
  place from an object, so a detail-rich close-up can win (a gun's mechanism was
  chosen over a wider shot in the test). Props and vehicles are not identities in
  the bible yet, so they get no reference at all.
- A split scene still takes its reference from the last sub-clip only, not the best
  frame across all of them.
- `REFERENCE_MIN_SCORE` 0.5 and the size/frontal weights come from one test on 60
  clips (about 20 with a person) - confirm on more footage.
- Not built yet from the continuity plan: replacing a weak reference when a later
  scene gives a clearly better frame (the score is stored for it), checking that the
  reference chip is really attached before submit (count the chips; Muse is not
  checked at all today and Flow only checks that some chip is visible), clearing
  stale chips, the per-project continuity level, and the SFace similarity check.
  (Showing the reference used in the Clip check is built.)
- Muse: whether a reference actually changes what Muse draws is unmeasured.

## Known limits of the 2026-10-03 clip check

- It cannot judge whether a clip's picture matches its narration - that is what
  the per-scene still is for; a person still has to glance at them.
- Repeated footage is caught by file bytes and, for Muse, the provider's untrimmed
  source identity. Two separately generated Flow clips that merely look alike are
  different files and are not flagged (no perceptual comparison).
- The length check compares against the real narration length when known, else the
  planned length; it does not check against a trimmed Muse target of a different
  value, and treats a sub-clip scene's crossfade overlap as a flat allowance.
- The verdict is not a gate: Render is not blocked by an ERROR finding.
- Only the first clip of a split scene gets a still.

## Known limits of the 2026-10-02 branding uploads

- The watermark image, CTA clip and title clip are one value per project,
  not per platform: to brand TikTok differently from YouTube, swap the
  file, save, then generate that variant. Already-generated variants keep
  the files they were made with and are not flagged as out of date.
- Uploads only apply to export variants made for a platform; a plain
  (platform "None") export stays unbranded.
- An uploaded title/CTA clip is letterboxed into the frame, never
  cropped, and re-encoded to 30 fps stereo audio so it joins cleanly.

## Explicitly out of scope

- Google Flow, or any browser automation targeting Google Flow's web UI.
  See `AGENTS.md`.
