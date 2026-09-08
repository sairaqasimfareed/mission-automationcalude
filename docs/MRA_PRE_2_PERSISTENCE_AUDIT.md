# MRA-PRE-2: Persistence/Restart/Migration Audit

Pre-Installer Master Audit, Phase 2. Objective: prove state survives
interruption and historical data remains safe. Evidence format per
`docs/MRA_PRE_0_BASELINE.md` section 9.

**HEAD at phase start**: `649b6e5bb1139153496444247015f0052600cf78`
(unchanged from MRA-PRE-1).

## Findings

### MRA-PRE-2-001: Repository write atomicity

**Claim under test**: a crash mid-write to `data/projects/*.json`
cannot corrupt a project file - either the old complete file or the
new complete file survives, never a partial one.
**Method**: code inspection of `JsonJobStore._write()` and
`PipelineCheckpointStorageService._atomic_write_json()`.
**Evidence**: both use the identical, sound pattern: write to a
`NamedTemporaryFile` in the SAME directory as the destination (a
same-volume requirement for atomic rename), `flush()` +
`os.fsync(handle.fileno())` before closing, then `Path.replace()`
(atomic on both POSIX rename semantics and Windows `MoveFileEx` with
`MOVEFILE_REPLACE_EXISTING` for a same-volume target) - with a
`finally` block that removes the temp file if it's still present
after a failure. A grep across `src/services/*.py` and `src/desktop/*.py`
for any other direct `.write_text()`/`.write_bytes()`/`json.dump()`
call touching persisted application state found only two: a one-shot,
user-triggered scene-prompt text export (`scene_prompt_export_service.py`)
and the theme-preference file (`theme_preference_store.py`) - neither
is state the app reloads to resume a restart-critical operation; a
corrupted write to either is a low-consequence, self-correcting
inconvenience (re-export the prompts; the preference already falls
back to SYSTEM on read failure), not a restart-safety risk.
**Verdict**: CONFIRMED.

### MRA-PRE-2-002: Schema upgrade - proven directly for VideoJob, not just individual artifacts

**Claim under test**: "new optional fields absorb via Pydantic
defaults, no migration script needed" - repeatedly asserted throughout
this project's history for individual artifacts (a pre-existing test
already proves this for `SEOPackage`), but never proven directly for
`VideoJob` itself, the one model every other artifact is keyed
against.
**Method**: real runtime test - hand-wrote the on-disk JSON shape a
project saved before content-intelligence/Google-Flow sprints existed
would have (17 real fields genuinely absent:
`editorial_profile_snapshot`, `flow_generation_attempts`,
`content_decisions`, `script_version_history`,
`production_ambiguities`, `stale_artifacts`, `audience_promise`,
`research_plan`, `generated_script`, `story_angles`,
`selected_story_angle`, `narrative_architecture`, `hook_candidates`,
`selected_hook`, `editorial_critique`, `script_quality_report`,
`packaging_hypothesis`, `approval_policy`, `content_strategy`) and
loaded it through the real `JsonJobStore`.
**Evidence**: new test
`test_json_store_loads_a_legacy_video_job_json_missing_new_fields` in
`tests/test_desktop_job_store.py` - passes, with every stripped field
resolving to its own honest default (`None`/`[]`), except
`approval_policy`, which has always had a real `default_factory`
(`ApprovalPolicyConfig.review_critical_stages`) rather than `None` -
confirmed as the correct, intended default, not a gap.
**Verdict**: CONFIRMED, now with direct evidence rather than an
assumption carried over from a different model's own test.

### MRA-PRE-2-003: Stale approval/Reviewer cannot be promoted by persistence

**Claim under test**: a `PENDING` `ApprovalDecision` cannot be silently
turned into `APPROVED` by a restart, a reload, or any validator logic.
**Method**: code inspection of `ApprovalDecision`/`ApprovalState` and
`ContentDecisionRecord`'s persistence shape.
**Evidence**: `ApprovalDecision` has exactly one `@field_validator`,
on `decision_point` (a normalization/non-empty check, not state
logic) - no validator anywhere touches `ApprovalState`. Approval state
lives embedded in `ContentDecisionRecord.approval`, itself a plain
field on `job.content_decisions: list[ContentDecisionRecord]` -
persisted through the exact same atomic-write mechanism already
confirmed in MRA-PRE-2-001 for the rest of `VideoJob`. No separate,
riskier persistence path exists for approval state to drift through.
**Verdict**: CONFIRMED.

### MRA-PRE-2-004: Google Flow restart reconciliation - real gap found and fixed

**Claim under test**: a Google Flow generation attempt interrupted
mid-submission (the application closed or crashed while an attempt
sat at `SUBMITTING`) is reconciled to the honest `SUBMISSION_UNCERTAIN`
state when the project is reopened, per the credit-sensitive-state
rule this codebase has held since GF-1.
**Method**: repository-wide search for every caller of
`GoogleFlowGenerationLedgerService.reconcile_on_restart()`.
**Evidence**: the method has existed and been unit-tested in isolation
since GF-1 (`test_google_flow_generation_ledger_service.py`), but a
grep across the entire `src/` tree found **zero real callers** -
nothing in the actual application ever invoked it. A project reopened
after an interruption would show that attempt stuck at `SUBMITTING`
forever, an inaccurate state with no path to self-correct. This
matches a gap GF-1's own `docs/IMPLEMENTATION_STATE.md` entry already
disclosed ("No orchestrator/GUI call site yet uses this service") -
this audit is what closes it, not a new discovery from nothing.
**Verdict**: GAP FOUND (severity: major - a real, restart-triggered
inaccurate state with no self-correction path, though not data
corruption or an incorrect promotion). **Fixed** in this phase: new
`ProjectWorkspaceView._reconcile_flow_attempts_on_open()`, called from
`set_job()` - the real "a project is being (re)opened" moment, run
once per open rather than on every `refresh()` (this view refreshes
far more often than once per user action, and
`reconcile_on_restart()` is already a no-op once nothing is left at
`SUBMITTING`, so repeating it on every refresh would be wasted work,
not a correctness requirement). New end-to-end test
`test_reopening_a_project_reconciles_a_flow_attempt_stuck_at_submitting`
drives this through the real `MainWindow -> _open_project ->
ProjectWorkspaceView.set_job()` path, not just the ledger service in
isolation - confirms an attempt advanced to `SUBMITTING`, saved to the
store, and then reopened via `_open_project()` is correctly reconciled
to `SUBMISSION_UNCERTAIN` in the store.

### MRA-PRE-2-005: Missing/corrupt asset handling

**Claim under test**: a scene referencing a media file that no longer
exists on disk is detected and reported, not silently ignored or
crashed on.
**Method**: code inspection of `MediaTechnicalValidationService.validate()`.
**Evidence**: the very first check is `if not file_path.exists() or
not file_path.is_file()`, returning a structured
`MediaTechnicalValidationResult(is_readable=False, issues=[...])`
rather than raising or crashing. `test_render_orchestrator_service.py`
and `test_scene_asset_workflow_service.py` both carry real coverage
for this path.
**Verdict**: CONFIRMED.

### MRA-PRE-2-006: Recovery state visibility - two real gaps found, not fixed here

**Claim under test**: recovery-relevant state (per MRA-PRE-2's own
GUI/runtime checklist item, "Recovery state must be visible") is
surfaced somewhere in the GUI, not only correct in the data layer.
**Method**: repository-wide search for any desktop view referencing
`flow_generation_attempts` or `stale_artifacts`.
**Evidence**: `job.flow_generation_attempts` (including the now-
correctly-reconciled `SUBMISSION_UNCERTAIN` state from
MRA-PRE-2-004) has **zero GUI surfacing anywhere** - matches GF-13's
own already-disclosed scope ("no bulk queue UI... GF-12's own queue/
worker loop isn't built either"), confirmed still true. Separately,
`job.stale_artifacts` (`InvalidationService`'s own append-only record
of what a script/scene/audio change has invalidated) also has **zero
GUI surfacing anywhere** - a real, not-previously-disclosed gap: the
invalidation mechanism is confirmed correct at the data level, but an
operator has no way to see "this render is stale because the script
changed" through the GUI at all.
**Verdict**: RISK (both), not fixed in this phase - building GUI
surfaces for either is real feature/UX work (a new panel or indicator
design), not a scoped, quick defect patch, and squarely overlaps
MRA-PRE-7's own "GUI and operator workflow audit" domain. Recorded
here (where the plan's own checklist places the requirement) and
flagged for MRA-PRE-7 to address as GUI work, not re-audited from
scratch there.

### MRA-PRE-2-007: Test-run data contamination (carried forward from MRA-PRE-0)

**Claim under test**: local `data/` paths are not accidentally
receiving real application writes as a side effect of running the
test suite.
**Method**: already recorded in `docs/MRA_PRE_0_BASELINE.md` section
8; re-confirmed here as squarely in this phase's own scope
(repositories/migrations/stale propagation).
**Evidence**: `data/checkpoints/` holds 566 directories against only 3
real projects; `data/final_exports/Deep_Sea_Documentary` matches this
test suite's own fixture project name.
**Verdict**: RISK, not fixed in this phase - a test-isolation hygiene
issue (tests should write to `tmp_path`, not production `data/`
paths), not a production defect (`data/` is gitignored, nothing
ships), but genuinely relevant to "historical data remains safe" if
left unaddressed indefinitely. Recorded as a candidate for a future,
narrowly-scoped test-fixture audit, not attempted here to avoid a
large, unbounded change to test infrastructure under audit-phase time
pressure.

## Summary

| # | Area | Verdict |
|---|---|---|
| 001 | Repository write atomicity | CONFIRMED |
| 002 | Schema upgrade (VideoJob) | CONFIRMED (newly proven directly) |
| 003 | Stale approval cannot be promoted | CONFIRMED |
| 004 | Google Flow restart reconciliation | GAP FOUND - **fixed this phase** |
| 005 | Missing/corrupt asset handling | CONFIRMED |
| 006 | Recovery state visibility (Flow attempts, stale artifacts) | RISK (both) - recorded for MRA-PRE-7 |
| 007 | Test-run data contamination | RISK - recorded, not fixed |

## Validation

- `black`, `ruff check`, `mypy` on `src/desktop/views/project_workspace_view.py`: all clean.
- New test `test_json_store_loads_a_legacy_video_job_json_missing_new_fields`
  in `tests/test_desktop_job_store.py`: full file re-run, 23 passed.
- New test `test_reopening_a_project_reconciles_a_flow_attempt_stuck_at_submitting`
  in `tests/test_desktop_app_integration.py`: passed in isolation and as
  part of the full file (12 tests: 11 passed + 1 confirmed-unrelated,
  isolation-reconfirmed pre-existing flake -
  `test_render_progress_updates_live_and_survives_cross_workspace_refresh`,
  already documented in `docs/GUI8_VALIDATION_REPORT.md`).

## Acceptance gate

*"Restart/migration behavior is deterministic and history-preserving."*
Met: repository writes are atomic, schema migration behavior is now
directly proven for `VideoJob` itself, stale approval state cannot be
silently promoted, missing/corrupt assets are handled gracefully, and
the one real restart-correctness gap found (Google Flow attempt
reconciliation never being called) is fixed and tested end-to-end in
this same phase. Two recovery-visibility gaps and one test-hygiene
risk are recorded, not hidden, and explicitly handed to the phases
better scoped to address them (MRA-PRE-7 for GUI visibility; a future
narrow pass for test-fixture isolation) rather than expanded into
unbounded work under this phase's own time budget.
