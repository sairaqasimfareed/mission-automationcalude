# Mission Automation — Content Studio Redesign Audit

**Scope:** Read-only audit of `F:\mission-automation` against `Mission_Automation_Content_Studio_Detailed_Implementation_Phases.pdf`. No files were modified.

**Phases covered:** `PROJECT_PROGRESS.md` documents Phases 0–9 of the redesign as complete (10 dated entries in total). Phase 0 is documentation/baseline only, with no new capability, so if that one isn't counted, "9 phases" lines up exactly — I audited all ten entries either way.

**Method:** For each phase, I pulled the actual model/service/GUI files the phase's own log entry names, read them directly, and checked the log's claims against the code and against the corresponding pages of your PDF, rather than trusting the log's own wording. Where the log already disclosed a gap ("deliberately not built this pass"), I verified the gap is real and marked it **Partial**, but did not re-flag it as a new finding. The findings below are things the log did *not* disclose, plus one already-disclosed area I traced to a concrete crash.

One general observation before the findings: this codebase's own `PROJECT_PROGRESS.md` is unusually disciplined — it names exactly what wasn't built, explains why, and calls out several of its own pre-existing bugs (dead print-script test files, a discarded `provider_preferences` field, a `dry_run`/`MIXED` resolution bug) as it goes. Most of what I checked matched the log exactly. The issues below are the ones that didn't.

---

## Phase 0 — Repository Reconciliation and Redesign Baseline
**Status: Clean.**

Verified directly: `requirements.txt` genuinely includes `anthropic`, `openai`, `google-genai`, `google-auth`; `pyproject.toml` ignores `UP042` with the stated rationale; `.github/workflows/ci.yml` runs ruff → black → mypy → pytest with ffmpeg and headless-Qt system packages installed, matching the log word for word. No defects found.

## Phase 1 — Canonical Artifact Lifecycle, Versioning, Lineage and Dependency Graph
**Status: 1 Blocker.**

- **BLOCKER — `invalidate_dependents()` crashes for most real artifact states.**
  `src/services/artifact_lifecycle_service.py`: `ArtifactLifecycleService.ALLOWED_TRANSITIONS` only permits a move to `INVALIDATED` from `APPROVED` or `REVISION_REQUIRED`. But `ArtifactDependencyGraphService.invalidate_dependents()` unconditionally calls `transition(record, INVALIDATED, ...)` on *every* non-terminal downstream record — including ones in `DRAFT`, `GENERATING`, `GENERATED`, or `UNDER_REVIEW`. Any of those four states will raise `ValueError: Cannot transition artifact from <status> to invalidated.`
  Confirmed by the test suite itself: every case in `tests/test_artifact_lifecycle_service.py` that exercises `invalidate_dependents()` constructs its downstream fixtures with `status=ArtifactLifecycleStatus.APPROVED` — none uses `DRAFT`/`GENERATING`/`GENERATED`/`UNDER_REVIEW`, so this path has no coverage.
  Impact today is zero, because (as the log itself notes across every later phase) nothing in production code calls `ArtifactLifecycleService.create_version()` yet — the whole engine sits unused. But this is a real defect in Phase 1's own deliverable, not a documented gap, and it will surface the first time anything wires up the spec's "Unapprove & Invalidate Dependents" dialog (Phase 1's own named GUI deliverable) against a real, in-progress (non-approved) artifact.

## Phase 2 — Project Setup, Starting Point and AI Configuration
**Status: Clean.**

Verified: `ProjectFormView` genuinely has Platform, Approval mode, and a Primary/Reviewer/Fallback "AI configuration" card, all defaulting to "System default." Verified the claimed bug fix — `ProjectSpecificationJobMapper.map()` does now pass `provider_preferences=specification.providers` to `VideoJob`. No new defects found.

*(Partial, as disclosed: the "Starting Point" selector doesn't exist yet — correctly deferred, since Phase 15 it depends on hasn't been built.)*

## Phase 3 — Projects Dashboard and Content Studio Command Center
**Status: Clean.**

`ContentStudioJourneyService.compute()` correctly reflects the pipeline's real execution order and gate state; its checkpoint logic for Quality and Script Lock is internally consistent. No defects found.

## Phase 4 — Shared AI Inspector, Reviewer Workflow and Standard Action Bar
**Status: Partial (as disclosed).**

Verified the log's own list of what's missing is accurate: no persistent AI Inspector panel, no "Review All," and — I confirmed directly — no real dependency-graph-based context package, since `ArtifactLifecycleService.create_version()` is never called anywhere I found in GUI or service code. (See Phase 6 below for one review-wiring defect that lives in this phase's mechanism but only becomes visible once Phase 6's data exists.)

## Phase 5 — Topic Intelligence Workspace
**Status: Clean.**

`TopicCandidate`'s scoring model and the GUI card match the spec and the log. No defects found. *(Partial, as disclosed: Topic selection doesn't gate `run_all()`; no Reviewer comparison/ranking wired yet.)*

## Phase 6 — Audience & Creative Strategy Workspace
**Status: 1 Minor (undisclosed).**

- **MINOR — "Review" on Creative Direction never sees the actual Creative Direction.**
  `src/desktop/views/content_studio_view.py`'s `_CI_STAGE_REVIEW_TARGET` maps the `story_angles` stage to `(ArtifactType.CREATIVE_DIRECTION, "selected_story_angle")`. This mapping predates Phase 6 (it was wired in Phase 4, before the `CreativeDirection` model existed) and was never updated once Phase 6 introduced the real `CreativeDirection` artifact (`narrative_thesis`, `constraints`, `combined_angle_note`). The result: clicking "Review" on this stage tells the Reviewer LLM it is "evaluating one creative_direction artifact" (via `ReviewerService._build_prompt`), but the content it actually receives is the bare `StoryAngle` — the narrative thesis and constraints a user enters in Phase 6's own "Creative direction" section are never shown to the reviewer at all. Phase 6's own "Deliberately not built this pass" list calls out inline editing, incremental "Generate More," and a dedicated version/approval trail, but doesn't mention this — so unlike the rest of the codebase's gaps, this one wasn't caught and disclosed.

## Phase 7 — Research Center (Research Brief and Retrieval Foundation)
**Status: Clean.**

Verified: `_handle_add/edit/remove_research_question` keep `structured_questions` and the flat `research_questions` list in sync in every code path, including the "can't remove the last question" guard. Verified the Research panel's Run button really is disabled with "Waiting on Research Brief approval." while `research_plan` is gated. No defects found.

## Phase 8 — Research Execution, Evidence Ledger and Fact Integrity
**Status: 1 Minor (undisclosed).**

- **MINOR — a "verified" note can produce a fact that displays as "unsupported."**
  `_handle_fact_check_again()` (`content_studio_view.py`) marks the `ManualResearchEdit` verified based on `FactCheckResult.is_supported`, and — in the same action, when that's `True` — appends a new `ResearchFact` built from `result.matched_source_ids`. If the LLM answers `IS_SUPPORTED: yes` but its `MATCHED_SOURCES` line doesn't parse to any real source index (empty, `"none"`, or a malformed number), the new fact is created with `evidence=[]`. The Evidence Ledger list then renders that same fact's badge via `ResearchFact.is_supported` (a *different*, evidence-count-based property: `len(self.evidence) > 0`), which is `False` — so the UI shows the note as "verified" (green) and its resulting fact as unsupported (amber) from one single user click. Low severity, but a visible internal contradiction a user would reasonably read as a bug.

## Phase 9 — Story Development (Architecture, Evidence Allocation and Retention)
**Status: 1 Minor (undisclosed edge case).**

- **MINOR — a curiosity loop opened at the very end of the video never binds to a beat.**
  `ContentIntelligencePipeline._bind_curiosity_roles()` matches a loop to a beat with `beat.start_seconds <= loop_seconds < beat.end_seconds` (half-open interval). A loop whose `opened_at_position` is `1.0` computes `loop_seconds == target_duration_seconds`, which can never be `< end_seconds` for the last beat (whose `end_seconds` is at most `target_duration_seconds`) — so that loop's `curiosity_loop_question` silently stays unset. It fails quietly rather than erroring, so it would likely go unnoticed, but a loop opening right before the payoff (arguably the highest-stakes moment for "which curiosity question does this beat advance") is exactly the case this drops.

*(Partial, as disclosed: no timeline-aware drag editing, no field-level beat editing — both correctly called out already.)*

---

## Summary table

| Phase | Topic | Status |
|---|---|---|
| 0 | Repository Reconciliation & Baseline | Clean |
| 1 | Canonical Artifact Lifecycle | **Blocker** (`invalidate_dependents` crash) + disclosed-partial |
| 2 | Project Setup & AI Configuration | Clean |
| 3 | Dashboard & Command Center | Clean |
| 4 | Reviewer LLM / AI Inspector | Disclosed-partial only |
| 5 | Topic Intelligence | Clean (disclosed-partial) |
| 6 | Audience & Creative Strategy | **Minor** (Creative Direction never actually reviewed) |
| 7 | Research Center | Clean |
| 8 | Research Execution & Evidence Ledger | **Minor** (verified note / unsupported fact contradiction) |
| 9 | Story Development | **Minor** (end-of-video curiosity loop never binds) |

The one **Blocker** is currently inert only because the artifact-lifecycle engine it lives in isn't wired into any real workflow yet; it will crash the instant that wiring happens unless fixed first.

---

## Re-audit — verifying the claimed repairs

Re-pulled the live files from the repo and checked each finding against the current code, not against the claim that it was fixed.

| # | Finding | Status |
|---|---|---|
| 1 | Phase 1 Blocker — `invalidate_dependents()` crash | **Fixed and verified.** `ALLOWED_TRANSITIONS` now permits →`INVALIDATED` from every non-terminal status (`DRAFT`/`GENERATING`/`GENERATED`/`UNDER_REVIEW` added, in addition to the two that already worked). A new parametrized regression test, `test_invalidate_dependents_works_regardless_of_the_dependents_own_status`, exercises all six non-terminal statuses explicitly. Correct fix. |
| 2 | Phase 6 Minor — Creative Direction never actually reviewed | **Fixed and verified.** A new `_resolve_review_artifact()` now returns `job.creative_direction` (when it exists) instead of the bare `selected_story_angle` for the `story_angles` review target, so the Reviewer finally sees the narrative thesis/constraints/combined-angle note it was already being told it was reviewing. |
| 3 | Phase 8 Minor — "verified" note vs. "unsupported" fact contradiction | **Fixed and verified.** `_handle_fact_check_again()` now requires both `result.is_supported` *and* at least one parsed `matched_source_ids` entry before marking a note verified or creating a fact, with the ambiguous case now recorded honestly in `verification_notes` instead of silently trusting an unbacked `is_supported` flag. |
| 4 | Phase 9 Minor — end-of-video curiosity loop never binds | **Fixed and verified.** `_bind_curiosity_roles()` now closes the interval on both ends for the last beat only (`at_final_edge` check), so a loop at `opened_at_position == 1.0` binds to the final beat instead of silently going unbound. |
| 5 | Cross-cutting Major — Run/Resume silently no-ops on the Research Brief gate | **Not fixed.** I re-pulled `project_workspace_view.py` directly (mtime unchanged from my original check) and `_BLOCKER_STAGE_TAB` still has no `"research_plan"` entry — the button will still silently do nothing when a project is blocked on that gate. This one was not addressed. |

One process note: `PROJECT_PROGRESS.md` has no new dated entry for any of these four repairs — the fixes themselves are good and are commented in-code as "found via external audit," but per the repo's own `AGENTS.md` rule 7 ("reconcile documentation... in the same change"), this pass didn't do that part.

**Net: 4 of 5 findings genuinely repaired and correctly re-verified against the code and tests. The Run/Resume `research_plan` gap is still open.**

---

## Second re-audit — the last finding

Re-pulled `project_workspace_view.py` again: `_BLOCKER_STAGE_TAB` now has `"research_plan": "content_studio"`, with an in-code comment crediting the external audit. A new test file, `tests/test_project_workspace_view_run_resume.py`, directly asserts `_BLOCKER_STAGE_TAB.get("research_plan") == "content_studio"` and that every content-intelligence stage (including `research_plan`) routes consistently to the same tab. Fixed and verified.

**All 5 findings are now genuinely repaired.**

Two smaller notes, unchanged from before:

- `PROJECT_PROGRESS.md` still has no new dated entry documenting any of these five fixes (still just Phase 9 as the newest entry) - a `AGENTS.md` rule-7 gap across all three repair passes, not just this one.
- This same pass also touched `hook.py`, `hook_generation_service.py`, `test_hook_evaluation_service.py`, `test_hook_generation_service.py`, `test_hook_model.py`, and `test_reviewer_service.py` - none of which were part of the original 5 findings. I haven't audited that work; say the word if you want it checked too.

---

## Addendum — Anti-drift protocol / genre propagation / unified workspace GUI

You asked me to check these three specifically. Short answers, each backed by what I actually found in the code:

**Anti-drift protocol.** There's no file literally named that, but `AGENTS.md` is exactly this: "don't build a duplicate subsystem, extend what exists," "VideoJob is the single source of truth," "reconcile documentation in the same change." Every model change I traced across Phases 2, 6, 7, 8, 9 followed it — new fields added *alongside* existing ones (`structured_questions` next to `research_questions`, `structured_facts` next to `key_facts`, the 7 new `AudiencePromise` fields), never a silent replacement. Phase 1's artifact-lifecycle ledger is the one place this gets into tension with itself: it's a second, parallel status-tracking system living beside ~40 existing per-artifact enums — disclosed and deliberate, not an accident, but still real duplication risk to watch as more phases wire into it.

More importantly, I found one **Major, undisclosed** case where the protocol's own rule 7 ("reconcile documentation/consumers in the same change") was missed:

- **MAJOR — Run/Resume silently does nothing when blocked on Research Brief approval.** `src/desktop/views/project_workspace_view.py`'s `_BLOCKER_STAGE_TAB` maps every `ContentIntelligencePipeline` gate stage to a sidebar tab (`"research"`, `"story_angles"`, `"narrative_architecture"`, `"hooks"`, `"script"`, etc.) so the shell's "Run / Resume Automation" button can jump straight to what's blocking a project. Phase 7 added a new gate, `stage="research_plan"` (the "Approve Brief & Start Research" gate) — but never added `"research_plan"` to this dict. When a project's approval policy sets `research_plan` to REVIEW or MANUAL (this happens under the "Approve Every Step" preset, or any hand-configured override — not the default "Custom Approval" preset, which leaves `research_plan` at AUTO) and the pipeline is actually blocked there, `_handle_run_resume()` looks up `_BLOCKER_STAGE_TAB.get("research_plan")` → `None`, falls through to the readiness-state fallback (also `None`, since the project is `BLOCKED`), and returns without navigating anywhere. The button does nothing, with no error — the user has to already know to click "Content Studio" themselves. This is a direct instance of unified-workspace-GUI code drifting out of sync with a content-pipeline change made three weeks later, exactly the failure mode `AGENTS.md` rule 7 exists to prevent.

**Genre-aware propagation.** Confirmed intact through every redesign artifact I checked. `AudiencePromise.genre_id` and `StoryBlueprint.genre_id` both validate the `"genre."` prefix (rejecting anything else), and `TopicCandidateGenerationService` takes genre/platform as explicit inputs rather than routing around the pre-existing genre engine (11 genre profiles, hook/pacing/reveal-density/quality-threshold policies from the earlier Sprints A1–A11 work). Genre is set once at Project Setup (Phase 2) and threads through as a required field rather than being re-derived per artifact — I found no place in the redesign phases where a new artifact bypasses or duplicates genre logic.

**Unified workspace GUI.** Real, not just described in the log — `ProjectWorkspaceView` genuinely reshapes navigation into a persistent sidebar (Content Studio / Clip Workspace / Production Audio / Editing Timeline / Render Workspace / Quality Center / Packaging) with one shared "Run / Resume Automation" action driven by `ProductionReadinessService`, not a second GUI-invented notion of "what's next" (matching `AGENTS.md` rule 4). The gap above is the one place I found where a newer content-pipeline stage wasn't reconciled into it.

---

# Phases 10–19: full Content Studio Redesign completion audit

You told me the complete PDF (all 20 phases, 0–19) is now implemented, so this round covers everything I hadn't yet independently verified: Phases 10–19. Same method as before — pulled the actual named files from the repo and checked them against the log's claims and the PDF, not against the claim itself. Phases 0–9 were already covered above across three rounds and all five findings there are confirmed fixed; I didn't re-check them again this round.

## Phase 10 — Hook Lab
**Status: Clean.**

Verified `HookCandidate.type`/`fact_ids`, `HookEvaluation.retention_potential`/`tone_fit`/`is_custom`/`.custom()` all match the spec and are correctly kept out of `overall_score`. `HookGenerationService`/`HookEvaluationService` parse the two new optional labels independently of the required set, exactly as claimed — a pre-existing dry-run fixture without `RETENTION_POTENTIAL`/`TONE_FIT` still parses. Confirmed `run_script()` genuinely hard-requires `job.selected_hook`. GUI Select/Write-my-own/Generate-more/Rewrite-with-instructions handlers all present and correctly wired. No defects found.

## Phase 11 — Script Workspace: Writing Directives
**Status: Clean.**

`WritingDirective`/`WritingDirectiveSet`/`DirectiveSource` match the spec. Verified the actual mechanical guarantee: `_SYSTEM_DIRECTIVES` in `WritingDirectivesService` is a fixed tuple constructed only via `_system_directives()`, always `overridable=False`, never passed to or restated by the LLM call — "system rules can't be overridden by user directives" is a real code guarantee here, not a prompt request. GUI directives panel with non-removable system directives confirmed. No defects found.

## Phase 12 — Script Generation, Rich Editor and Version Control
**Status: 1 Major (undisclosed).**

- **MAJOR — the manual "Save typed edit" path never invalidates downstream production artifacts.**
  `src/desktop/views/content_studio_view.py`, `_handle_save_script_segment_edit()` (~line 3722): when a person directly retypes a segment's narration and clicks "Save typed edit," this handler mutates `job.generated_script` in place, appends a `MANUAL_EDIT` version via `ScriptVersionService`, and clears `job.editorial_critique`/`job.script_quality_report` — but it never calls `InvalidationService.on_script_changed(job)`. Every other script-mutating path in this codebase does: `ContentIntelligencePipeline.run_revision()`, `run_script_selection_edit()` (the AI-driven selection-edit buttons sitting right next to this one in the same panel), and `run_script_restore()` all call `self.invalidation_service.on_script_changed(job)` at the end, which marks `scenes`, `scene_asset_states`, `video_clips`, `audio_timeline`, `video_timeline`, and `render_result` stale (via `SCRIPT_CHANGE_DOWNSTREAM_FIELDS`) whenever any of them currently hold a value.
  Concretely: if a project has already run scene planning (so `job.scenes` is populated) and a person then uses the raw typed-edit box — not the AI rewrite buttons — to change a segment's narration, the already-planned scenes (and any downstream clips/timelines/render result) are left looking completely valid with zero staleness record, even though the narration underneath them just changed. This directly contradicts `AGENTS.md` rule 5 ("Follow selective invalidation rules... don't silently leave a stale downstream artifact looking valid") and the Phase 13 log entry's own claim that "every script-mutating path now invalidates consistently" — this GUI-only, non-LLM path was missed by that fix.
  The existing test for this handler, `test_save_typed_edit_records_a_manual_edit_version`, only asserts the narration text and version number changed; it never asserts anything about `job.stale_artifacts`, so this gap has no test coverage in either direction.

Everything else in this phase checks out: `ScriptVersion.reason`/`restored_from_version_number` validators are correct (RESTORE requires the back-reference, version 1 can't have one), `ScriptVersionService.restore_version()`/`compare()` are non-destructive and correctly check the lock before restoring, and `ScriptSelectionEditService.edit()` genuinely returns every other segment byte-identical (verified the substring-replace and full-segment-replace paths both preserve `timing`/`narrative_function`/`source_claim_references` by construction — only `narration` is ever touched).

## Phase 13 — Script Critique and Formal Quality Gate
**Status: Clean.**

`CriticFinding.is_safe_to_auto_fix` correctly excludes only `BLOCKING`. `ScriptRevisionService.revise(finding_ids=...)` correctly filters to just the requested findings, or all of them when omitted, reproducing prior behavior exactly. `ScriptQualityGateService.ignore_finding()` correctly rejects an unknown finding id, an empty reason, and a double-resolution. `ScriptQualityReport.unresolved_blocking_findings` (used by the Script Lock gate in Phase 14) correctly excludes anything with a resolution. No defects found.

## Phase 14 — Script Lock and Common Production Handoff Contract
**Status: Clean (both disclosed bugs verified fixed).**

Verified both self-disclosed bugs directly: `ContentIntelligencePipeline.run_revision()` now checks `job.script_version_history.is_locked` and raises *before* calling `ScriptRevisionService.revise()`, so a locked script's `generated_script` field is never touched at all on a rejected attempt. The GUI's `_handle_save_script_segment_edit()` (see Phase 12 finding above) has the identical lock check before its own mutation. `ScriptLockService.build_lock()` is a pure function — it validates unresolved blocking findings and blocking production ambiguities and raises before constructing anything, never partially mutating `job` — so `ContentIntelligencePipeline.run_script_lock()`'s all-or-nothing update (`job.script_version_history` and `job.script_lock` set together, only after `build_lock()` succeeds) is genuinely atomic. No defects found beyond the one carried over from Phase 12.

## Phase 15 — Alternate Path: Import Approved Script Intake
**Status: Clean (both disclosed bugs verified fixed).**

Verified: `_handle_lock_script()` in the GUI no longer passes `provenance` at all (confirmed by direct code read, with an in-code comment explaining the inference is now left to `run_script_lock()`), so the EXTERNAL/INTERNAL inference from `job.script_intake_result is not None` is no longer defeated. `run_script_intake()`'s activity-history logging uses `getattr(mode, "value", mode)`, correctly handling both a real `ScriptIntakeMode` enum and a plain GUI-supplied string. `ScriptIntakeService.normalize_text_to_script()` genuinely builds no fake `research`/`selected_hook`/`story_blueprint`. No defects found.

## Phase 16 — Imported Script Production Enrichment and Automatic Directive Extraction
**Status: Clean (near-miss confirmed non-issue).**

Verified the claimed name collision was avoided cleanly: `src/models/production_readiness.py` still defines only the original, broader `ProductionReadinessReport`/`ReadinessState` (whole-project render/export readiness), while the new Phase 16 artifact lives in a separate file, `src/models/script_production_readiness.py`, as `ScriptProductionReadinessReport` — no field or class was overwritten, and the new file's own docstring explains the distinction. `ProductionAmbiguity.is_blocking` correctly requires both `continuity_critical` and `UNRESOLVED`. `ScriptLockService.build_lock()` correctly also blocks on unresolved blocking ambiguities (verified in the Phase 14 read above), using the same `override_reason` mechanism as the quality-findings check. No defects found.

## Phase 17 — Unified Automation Engine
**Status: Clean.**

Verified `compute_automation_status()`'s 14-entry `stage_presence` tuple matches `run_all()`'s own per-stage presence checks field-for-field, so the two genuinely cannot drift apart silently. `AutomationStatus.is_complete`/`is_paused` are simple, correct derived properties. No defects found.

## Phase 18 — Activity History, Auditability and Recovery
**Status: Clean (disclosed bug verified fixed, wiring verified thorough).**

This is the phase I checked most literally, since its own claim ("every silent stage now writes to the ledger") is a claim about *completeness*, not just correctness. Grepped every `run_*` method in `ContentIntelligencePipeline` (25 call sites) and confirmed `record_event()`/`gate()` calls exist for all of them, with the right `DecisionCategory` in each case — including `run_script_unlock()` capturing `unlocked_version_number` from `job.script_lock.script_version_number` *before* `job.script_lock = None` clears it, exactly as claimed. `ApprovalGateService.record_event()` is the single shared append surface, and `ContentDecisionRecord.effective_category` correctly back-infers a category for pre-Phase-18 records. No defects found beyond confirming the disclosed `mode.value` AttributeError is genuinely fixed (see Phase 15).

## Phase 19 — End-to-End Integration, Migration and Production Readiness
**Status: Clean (both disclosed bugs verified fixed with real tests).**

Both of this phase's own self-reported bugs check out as genuinely fixed:

- **Bug 1 (missing `ScriptLock` from `run_all()`).** `run_all()` now calls `self.run_script_lock(job)` (not the old direct `ScriptVersionService.lock_version()` call) once a script is `APPROVED_FOR_PRODUCTION`, guarded on `job.script_lock is None` for idempotency, with a `try/except ValueError` fallback to the old version-only lock behavior for the documented edge case. Verified `ScriptLockService.build_lock()` never mutates `job` before it can raise, so that fallback path can't leave inconsistent state.
- **Bug 2 (deserialization failure on any new-pipeline project).** `VideoJob.validate_workflow_state()`'s scenes-require-a-script check now reads `self.script is None and self.generated_script is None` (previously only checked the legacy `self.script` field). Verified with the actual failing case in mind: a `run_all()`-completed job has `generated_script` set and `self.script` (the legacy `ContentPipeline` field) as `None` — before the fix this would have unconditionally raised "Scenes cannot exist without a script."

`tests/test_project_migration.py` is a genuine, non-trivial regression test — it hand-writes a raw pre-redesign JSON dict (not a `VideoJob(...)` construction, which would trivially include every current field), loads it through `JsonJobStore`, runs it through the real `run_all()` with a stub LLM service, asserts a real `ScriptLock` is reached, then round-trips the completed job through the store again. This is a legitimate test of the claimed migration story, not a rubber stamp.

---

## Summary table — Phases 10–19

| Phase | Topic | Status |
|---|---|---|
| 10 | Hook Lab | Clean |
| 11 | Writing Directives | Clean |
| 12 | Script Generation, Editor & Version Control | **Major** (manual "Save typed edit" never invalidates downstream scenes/clips/timelines/render) |
| 13 | Script Critique & Quality Gate | Clean |
| 14 | Script Lock & Production Handoff | Clean (2 disclosed bugs verified fixed) |
| 15 | Import Approved Script Intake | Clean (2 disclosed bugs verified fixed) |
| 16 | Production Enrichment & Ambiguity Registry | Clean (near-miss confirmed avoided) |
| 17 | Unified Automation Engine | Clean |
| 18 | Activity History & Auditability | Clean (1 disclosed bug verified fixed) |
| 19 | E2E Integration, Migration & Readiness | Clean (2 disclosed bugs verified fixed) |

**Combined with Phases 0–9 (all 5 earlier findings now fixed): across all 20 phases of the Content Studio Redesign, there is exactly one open, undisclosed defect — the Phase 12 invalidation gap above.** Everything the log described as "deliberately not built" checked out as genuinely not built (and genuinely disclosed, not hidden). Every self-disclosed bug across Phases 14/15/18/19 checked out as genuinely fixed, with real regression tests behind each one, not just log text.

## Out of scope: the second document

`PROJECT_PROGRESS.md` also documents a *separate* 16-phase document — "Post-Script-Approval Production Plan" (Phases 0–15, its own dated entries from 2026-09-06, covering canonical script lock/production handoff through final QC and publish-ready packaging) — as fully complete ("PDF-1 COMPLETE"). I have never been given that PDF and have not audited any of its claims. If you want it checked, I'll need the actual document — I'm not willing to audit code against a spec I haven't read, since "does the code do what the spec says" is the entire point of this exercise.
