# Remaining Gaps

Actionable register, derived from `docs/IMPLEMENTATION_STATE.md`. Ordered
by leverage (cheapest/most-unblocking first within each phase), not by
the master prompt's section numbers. A gap moves out of this file (not
just gets marked done) once its row in `IMPLEMENTATION_STATE.md` says
Done and it has tests.

## Phase 1 - Approval runtime & decision history

- [ ] **Approval runtime gating.** `ApprovalPolicyConfig` and
      `ApprovalService` both exist and are unused together. Wire
      `ContentIntelligencePipeline` (and, where relevant,
      `MediaGenerationPipeline`) so a stage completion resolves the
      configured policy into CONTINUE or WAITING_FOR_APPROVAL, and
      persist that waiting state on `VideoJob` so it survives a restart.
- [ ] **Decision history.** Make every stage that resolves an approval
      decision append a `ContentDecisionRecord` to
      `VideoJob.content_decisions`. Add an Approval History GUI surface
      (read-only list, newest first, never mutated in place).

## Phase 2 - Readiness & typed blockers

- [ ] **Typed `Blocker` model.** One shared model (`code`, `stage`,
      `severity`, `message`, `affected_artifact`, `retryable`,
      `recovery_action`) usable by orchestration, GUI, logs, and tests.
- [ ] **`ProductionReadinessService`.** One centralized service answering
      "is this project ready" with `BLOCKED`/`READY_FOR_RENDER`/
      `READY_FOR_FINAL_EXPORT`/`COMPLETED` and a list of typed blockers.
      Every GUI readiness indicator must consume this service, not
      duplicate its logic.
- [ ] **Retrofit existing failure paths onto `Blocker`.** Start with
      `AssetModuleFailure` (closest existing analog) and the bare
      `RuntimeError` messages in `MediaGenerationPipeline`/
      `ContentIntelligencePipeline`.

## Phase 3 - Selective invalidation

- [ ] **Formalize the invalidation matrix** (in both code and
      `docs/ARCHITECTURE.md`) for: script change, scene replacement,
      audio regeneration - the three examples in the master prompt.
- [ ] **Extend `ScriptVersionService`'s pattern** (or a sibling service)
      to scene plan / asset / audio / timeline / render invalidation.
- [ ] Regression tests per dependency path.

## Phase 4 - Unified production audio hardening

- [ ] **"Generate All Audio"** - one action coordinating
      `MediaGenerationPipeline.run_voice/run_music/run_sound_effects`,
      reusing valid READY artifacts, reporting failed/missing components
      individually rather than failing atomically.
- [ ] **Bind narration to the exact approved script identity/version**
      (needs Phase 1's decision history and the script version already
      on `ScriptVersionHistory`).
- [ ] **`ManualAudioRequirement`** model for audio a human must supply
      manually, so it's an explicit requirement rather than an ambiguous
      failure.

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
