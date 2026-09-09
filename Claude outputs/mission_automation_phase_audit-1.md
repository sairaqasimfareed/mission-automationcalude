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

---

# Part 2 — Post-Script-Approval Production Plan Audit

**Scope:** Read-only audit of `F:\mission-automation` against `Mission_Automation_Post_Script_Approval_Phase_Plan.pdf` (16 phases, 0–15: canonical script lock/handoff through final QC and publish-ready packaging). `PROJECT_PROGRESS.md` documents all 16 phases as complete, dated 2026-09-06, ending "PDF-1 COMPLETE."

**Method:** Same as Part 1 — for every phase I staged and read the actual named model/service/GUI files directly (not the log's description of them), cross-checked every claim, and specifically hunted for undisclosed gaps. Where the log already disclosed a limitation, I verified it's real and note it below as **Clean (disclosed limitation confirmed real)**, not as a new finding.

**Headline result: no undisclosed defects found anywhere across all 16 phases.** This log's self-reporting is, if anything, more rigorous than Part 1's — several entries (Phases 8, 13, 15) read as genuine "found a real gap by reading the call chain, not the phase description" investigations, and every one of those self-disclosed gaps checked out as real and accurately scoped when I independently verified the code. I did not find a single case where the log understated a problem.

## Phase 0 — Canonical Script Lock and Production Handoff State
**Status: Clean.**

`ProductionHandoffState`/`ProductionHandoffStatus` (BLOCKED/LOCKED/BUILDING_PACKAGE/PACKAGE_READY) is a computed-not-persisted snapshot, matching the codebase's established `AutomationStatus` convention. Read `compute_production_handoff_status()` in `content_intelligence_pipeline.py` directly: the BLOCKED/LOCKED/BUILDING_PACKAGE/PACKAGE_READY logic exactly matches the claim, correctly reusing the existing `InvalidationService.is_stale(job, "scenes")` to distinguish BUILDING_PACKAGE from PACKAGE_READY. Also verified `run_scene_planning()` stamps `Scene.locked_script_hash = job.script_lock.script_content_hash` on every scene (only when a lock exists) — this is the actual mechanism that lets every downstream artifact identify which locked script it was built from. No defects found.

## Phase 1 — Production Semantic Brief
**Status: Clean.**

`ProductionSemanticBrief`/`ProductionSemanticSegment` and `ProductionSemanticBriefService.generate()` are exactly what's claimed: a deterministic, no-LLM-call, one-to-one projection of each script segment into time-bounded production intent, gated by a hard `RuntimeError` if the script isn't locked yet, with a mechanical `validate_full_coverage()` model validator and a `content_hash` property for staleness detection. Read both files in full; no gap between claim and code.

## Phase 2 — Visual Continuity Bible
**Status: Clean (disclosed scope limit confirmed real).**

Read `VisualContinuityService` (299 lines) and `VisualContinuityValidationService` in full. The claimed "handoff equality holds by construction" is genuinely true, not just hoped for: `_build_clip_entries()` computes each clip's `incoming_state` directly from the previous clip's own `outgoing_state` in the same loop, so the two literally cannot disagree — this isn't validated after the fact, it's structurally impossible to build otherwise. The separate, rule-based `VisualContinuityValidationService` (checking `HANDOFF_MISMATCH`/`UNKNOWN_IDENTITY`) is legitimate defense-in-depth consistent with this codebase's established "extraction and validation are separate passes" pattern, not a check that can never fire. The disclosed scope limit — canonical identities only tracked for PERSON/LOCATION, with PROP/VEHICLE left as plain names — is confirmed real by reading `_identities_from_continuity_bible()`.

## Phase 3 — Cinematic Shot Plan
**Status: Clean.**

Read `ShotPlanningService` (321 lines) and `shot_planning.py` in full. Confirmed shot duration is always overridden from `Scene.estimated_duration_seconds` (never LLM-guessed) and every scene missing from the LLM's output gets a fallback shot via `_fallback_shot()` — so full scene coverage cannot silently fail. Noted but did not flag as a defect: `CinematicShotPlan.has_exactly_one_shot_per_scene` only checks for duplicate scene numbers, not missing coverage; confirmed via grep this validator is never relied on to catch missing scenes anywhere it's actually used (GUI warning label, one test assertion) — the real coverage guarantee comes from the fallback-shot mechanism above, not this property.

## Phase 4 — Resolved Cinematic Prompt Package
**Status: Clean.**

`CinematicPromptCompilationService` (deterministic compiler) and `CinematicPromptQualityService` (one LLM scoring call) are cleanly separated, and the quality service genuinely never mutates its input — it returns a fresh `CinematicPromptPackage` built via `prompt.model_copy(update=...)` per prompt. Verified `QUALITY_BLOCK_THRESHOLD = 50` and `is_blocked` (true when the *lowest* of six 0–100 dimension scores falls under threshold) match the model exactly, and confirmed via grep that `is_ready`/`blocked_prompts` are consumed for display/logging only — there's no hard generation-blocking gate, which is correct given Phase 7 (the only place that would actually spend generation budget) is out of scope.

## Phase 5 — Clip Workspace Materialization
**Status: Clean.**

`ClipMaterializationService.compute()` is pure aggregation over pre-existing `Scene` fields plus `CinematicPromptPackage.prompt_for_scene()` for full-trace checking. Read the full 77-line service; every claimed field (ready/missing/stale/traced-to-prompt counts, route counts, planned/target duration, total cost) is computed exactly as described, with `stale_clips` correctly comparing each scene's `locked_script_hash` against the current `script_lock.script_content_hash`.

## Phase 6 — Fulfillment Routing and Budget Gate
**Status: Clean (disclosed limitation confirmed real).**

`maximum_visual_budget`/`has_budget_cap`/`remaining_budget`/`is_over_budget` are present on `ClipMaterializationStatus` exactly as claimed, and confirmed (via the same service read as Phase 5) this is visibility-only — nothing blocks generation or acquisition when over budget, matching the log's own disclosure that this is a non-blocking gate.

## Phase 7 — Google Flow Generation Execution
**Status: Clean — justified skip, not a hidden gap.**

Verified this against `AGENTS.md`'s own "Scope boundary" section, which explicitly excludes Google Flow browser automation from this codebase's scope. Confirmed via grep that none of the PDF's named touch-point files (`external_ui_generation_provider.py`, `google_flow_automation_service.py`, `google_flow_generated_clip_pipeline_service.py`) exist anywhere in the repo — this is a consistent, disclosed, architecturally-mandated skip, not an undisclosed gap dressed up as one.

## Phase 8 — Generated Clip Quality Control
**Status: Clean (disclosed limitation confirmed real — and confirmed still real at the one live call site).**

`MediaTechnicalValidationService` (ffprobe-based, injectable runner) is wired as an *optional* constructor parameter on `ManualUploadService`. I independently checked the one real construction site — `SceneAssetAndTimelineInfrastructureFactory.build_scene_asset_workflow_service()` — and confirmed `ManualUploadService(storage_service=...)` is built there **without** passing `technical_validation_service=`. This means the live desktop app never actually runs this ffprobe check on a manual upload today, exactly as the log discloses. This is the one place across both documents where I'd flag it's worth closing the loop (pass the service at that one construction site) if the check is meant to protect real uploads rather than exist only for direct unit tests — but it's honestly disclosed, not a hidden gap.

## Phase 9 — Voice Directive Resolution and ElevenLabs Generation
**Status: Clean.**

This is a real, live orchestration change, not a capability left sitting unused. Read `VoiceGenerationService.run_job()` directly and confirmed line 148's call site (`provider.generate_from_blueprint(blueprint)`) genuinely replaced the old `generate_voice(text, voice)` call on the path every real generation goes through. Traced the full chain: `ElevenLabsVoiceProvider.generate_from_blueprint()` → `ElevenLabsVoiceTranslationService.translate()` → a real POST body with `voice_settings`. The translation service only maps the 5 genuinely-documented ElevenLabs fields (stability, similarity_boost, style, use_speaker_boost, speed clamped to [0.7, 1.2]) and honestly names everything else (emotion, pace, pitch, volume, pronunciation/pause/emphasis directives) in an `unsupported_controls` list rather than fabricating a mapping. No gap between claim and code anywhere in this chain.

## Phase 10 — Music and SFX Acquisition (Audio Cue Policy)
**Status: Clean.**

Found the actual wiring point at `src/pipeline/sound_effect_stage.py` (not colocated with the other Phase 9–11 service files). Confirmed `SoundEffectPipelineStage.__init__` defaults `cue_policy_service` to a real, active `AudioCuePolicyService()` instance (not `None`), and `execute()` genuinely calls `self._cue_policy_service.evaluate(audio_timeline.tracks)` after building the timeline, appending each conflict as a stage warning — never blocking generation or changing `attached_count`, exactly as claimed. `AudioCuePolicyService.evaluate()`'s REPETITIVE_SFX (same preset/file within a time window) and LOUDNESS_ACCUMULATION (overlapping tracks' combined volume over a fixed ceiling) checks are correctly implemented and honestly documented as a coarse heuristic, not real LUFS measurement.

## Phase 11 — Audio Timeline Compilation and Mix Directives
**Status: Clean.**

Read the relevant sections of `FilterGraphBuilderService` directly. `_build_fade_nodes()` returns an empty list when neither fade is configured, so a track with no fades produces the exact same filter chain as before this phase — genuinely backward-compatible, not just claimed to be. The `amix`→`alimiter` rewiring is correct: the mixer now outputs an internal `audio_mixed` label (with `normalize=0`, preserving per-track deterministic levels), a new `alimiter` node consumes that and outputs `audio_final`, and `FilterGraph.audio_output_label` still points at `audio_final` — so the graph's public contract is genuinely unchanged even though what feeds it now includes a brick-wall limiter against clipping.

## Phase 12 — Video Timeline and Editing Directive Compilation (Duration Mismatch Policy)
**Status: Clean (disclosed limitation confirmed real).**

Read `DurationMismatchPolicyService` and its model in full. Confirmed it's genuinely advisory-only: `evaluate()` never mutates a `Scene` or `VideoClip`, `APPROVED_WORKAROUND` is never assigned by the service itself (the model's own validator requires a note whenever it's used, enforcing that it can only come from an explicit human decision), and TRIM/HOLD_LAST_FRAME/BLOCK recommendations are computed purely from comparing planned vs. actual clip duration. Confirmed via grep it is not referenced anywhere outside its own model/service files — genuinely standalone, matching the log's disclosed "deliberately not wired into `ProductionReadinessService`" note.

## Phase 13 — Master Edit Plan and Render-Readiness Gate
**Status: Clean (disclosed limitation confirmed real).**

`MasterEditPlan.render_identity_hash` is a purely additive optional field, and `MasterEditPlanService.build(..., render_identity_hash: str | None = None)` passes it straight through with no other behavior change — confirmed omitting it reproduces prior behavior exactly. Confirmed via grep that no caller anywhere in the codebase actually computes and passes a hash yet, exactly as disclosed — this phase added the capability to carry a render-identity hash, not a live caller that populates it.

## Phase 14 — FFmpeg Production Render
**Status: Clean.**

Read `ProductionRenderService.render()` in full. All four of the log's claimed additions check out exactly: `cancellation_check` is a genuine optional parameter forwarded straight to `FFmpegExecutionService.execute()`; the staged-output-then-promote pattern is real (`_staging_output_file()` correctly inserts `.part` before the extension, not after, so the command builder's extension check still passes; `_promote_staged_output()` does an atomic `Path.replace()` only after genuine success; `_cleanup_staging_file()` runs on both the exception path and the unsuccessful-but-non-exception path, so a crashed, cancelled, or rejected render never leaves a partial file at the real output path); `RenderResult` genuinely carries the new command/codec/version fields through from `execution_result` and `resolved_config`; and `classify_render_failure()` is genuinely wired — `render()` reads `execution_metadata.get("failure_stage")` and passes it through, rather than the classification existing unused.

## Phase 15 — Final QC and Publish-Ready Package
**Status: Clean.**

This is the highest-stakes claim in the whole document ("mark PUBLISH_READY only when hard QC gates pass"), so I verified it end to end. Read `FinalExportService.build()` directly: it computes `ProductionProvenance` from the render orchestration result's own `VideoJob`/`RenderResult` (pure snapshot, no re-derivation), builds the package, runs `FinalExportValidationService.validate()`, and sets `status = APPROVED if validation.is_valid else UNDER_REVIEW` — this is real, not decorative. Read `FinalExportValidationService` in full and confirmed the three new ffprobe-based checks (readability, no-audio-stream, resolution-mismatch) genuinely use an injected `MediaTechnicalValidationService` reconfigured with wide-open duration/resolution thresholds appropriate to a finished video rather than a single clip. Also checked `PackagingView`: `_handle_build_final_export()` stores `result.package` (whose `.status` already carries the correct APPROVED/UNDER_REVIEW value from the service, so nothing is lost by not separately reading `result.validation`), and a separate `_build_qc_summary()` method re-runs the same validation live on every render to show an always-current QC summary in the GUI — this matches the log's claim precisely and isn't a leftover of the bug the log describes fixing. The one thing genuinely still open — `is_ready_for_publish` also requires `seo_package`/`thumbnail_artifact` to be independently APPROVED, and nothing anywhere in this codebase ever transitions those statuses (no SEO/thumbnail approval UI exists) — is explicitly disclosed by the log itself as a separate, pre-existing gap this phase didn't create.

## Summary table — Post-Script-Approval Production Plan (Phases 0–15)

| Phase | Topic | Status |
|---|---|---|
| 0 | Canonical Script Lock/Handoff | Clean |
| 1 | Production Semantic Brief | Clean |
| 2 | Visual Continuity Bible | Clean (disclosed: PROP/VEHICLE not tracked as identities) |
| 3 | Cinematic Shot Plan | Clean |
| 4 | Resolved Cinematic Prompt Package | Clean |
| 5 | Clip Workspace Materialization | Clean |
| 6 | Fulfillment Routing/Budget Gate | Clean (disclosed: budget gate is visibility-only) |
| 7 | Google Flow Generation Execution | Clean (justified out-of-scope skip) |
| 8 | Generated Clip QC | Clean (disclosed: ffprobe check never wired into the live upload path) |
| 9 | Voice/ElevenLabs Generation | Clean |
| 10 | Music/SFX Acquisition (Audio Cue Policy) | Clean |
| 11 | Audio Timeline Compilation | Clean |
| 12 | Video Timeline/Duration Mismatch Policy | Clean (disclosed: standalone, not wired to readiness gate) |
| 13 | Master Edit Plan/Render-Readiness Gate | Clean (disclosed: render_identity_hash has no live caller yet) |
| 14 | FFmpeg Production Render | Clean |
| 15 | Final QC/Publish-Ready Package | Clean |

**No undisclosed Blocker, Major, Minor, or Partial defects were found anywhere in the Post-Script-Approval Production Plan's 16 phases.** Every limitation named above was already disclosed in `PROJECT_PROGRESS.md` and I independently confirmed each one is real and accurately scoped — none understate the gap. The only item worth your attention going forward is Phase 8's ffprobe validation service sitting unused at its one real construction site (`SceneAssetAndTimelineInfrastructureFactory`) — not a bug, but a check that currently protects nothing in the live app until someone passes it in.

---

# Verification pass — the Save-typed-edit fix

`PROJECT_PROGRESS.md` gained a new entry: "Reviewer-audit fix: manual 'Save typed edit' never invalidated downstream production artifacts." Verified directly: `content_studio_view.py`'s `_handle_save_script_segment_edit()` now calls `self._content_intelligence_pipeline.invalidation_service.on_script_changed(job, reason=...)` at the same point every sibling script-mutating path already does, the call matches `InvalidationService.on_script_changed()`'s real signature, and the new regression test (`test_save_typed_edit_invalidates_downstream_production_artifacts`) genuinely populates `scenes`/`video_clips`/`video_timeline`, triggers the handler, and asserts the resulting `stale_artifacts` set and `triggered_by` value — not a rubber-stamp test. File-mtime comparison across every `src/services`, `src/models`, `src/pipeline`, and `src/desktop/views` file confirmed this was the *only* code change since the prior audit pass (plus retroactive documentation of an older, already-existing fix). **This closes the one open defect from the first pass.**

---

# Part 3 — Anti-drift and genre-aware propagation

A follow-up pass specifically targeting two properties both PDFs assume throughout: the Post-Script-Approval plan's own cross-cutting requirement ("rerunning a completed phase with unchanged upstream hashes must not duplicate or drift artifacts") and "genre-aware" propagation (genre profile settings threading correctly through every stage that claims to be genre-driven, without silently going stale or inconsistent). Three real, previously unflagged gaps surfaced — all **Minor**, none blocking normal use, but worth knowing about.

## Finding 1 (Minor) — SFX cues can duplicate on a full pipeline re-run

`SoundEffectPipelineStage.execute()` (`src/pipeline/sound_effect_stage.py`) reuses `context.job.audio_timeline` across runs and appends each generated cue's `AudioTrack` with no check for whether that scene's cue was already attached (`audio_timeline.tracks.append(result.audio_track)`, unconditional). `PipelineRunner`/`PipelineResumePlannerService` genuinely re-executes every registered stage — including already-completed ones — whenever `AdvancedSettings.resume_previous_pipeline=True` and `skip_completed_stages=False` (both real, user-facing settings; `skip_completed_stages` defaults to `True`, so this needs a deliberate non-default choice to trigger). Under that combination, re-running the pipeline would silently double-generate and double-attach every sound-effect cue — real provider cost paid twice, and a second copy of every SFX track in the final mix. Phase 10's own `AudioCuePolicyService` would likely flag the resulting duplicates as `REPETITIVE_SFX` warnings after the fact, but nothing prevents the duplication itself. `MusicPipelineStage` has the identical unguarded-append pattern, but that file predates both audited PDFs, so it's flagged here as related context rather than an in-scope Phase 10 finding. `VoicePipelineStage`, by contrast, guards this correctly — `VoiceTimelineService.attach_many(replace=False)` raises rather than silently duplicating.

## Finding 2 (Minor) — ScriptLock doesn't persist the fields Phase 0's own spec names

The PDF's Phase 0 implementation-work bullets explicitly say: "Persist lock version, script version, topic, angle, target duration, genre/profile references, and upstream content-plan hash." The actual `ScriptLock` model (`src/models/script_lock.py`) only carries `script_version_number`, `script_content_hash`, `provenance`, `quality_status`, and `override_reason` — no topic, angle, target duration, or genre/profile reference is snapshotted onto the lock record, and `ProductionHandoffStatus` doesn't carry them either. The Phase 0 log entry is transparent that the PDF's own "Repository Position" table is stale and reframes the phase around hash-stamping and handoff status, which is legitimate — but it never mentions or disclaims this specific sub-requirement, so its absence isn't a documented "deliberately not built," just a silent gap against the spec's literal wording.

## Finding 3 (Minor) — Phase 6's "route defaults by project/genre" doesn't exist

The PDF's Phase 6 bullet: "Apply route defaults by project/genre with per-clip override." In the actual code, every `Scene.source_type` defaults uniformly to `MANUAL_UPLOAD` regardless of genre (`src/models/scene.py`), and the only place a scene's route actually changes is `AssetDecisionService.apply_decision()`, which is driven entirely by explicit human choices in the GUI (`USE_LOCAL`/`MANUAL_UPLOAD`/`USE_STOCK`/etc.) — there is no genre-based default pre-selection anywhere. The Phase 6 log entry's REUSE claim ("`Scene.source_type`... already is the per-clip route, set once during scene planning") is true as far as it goes, but glosses over the fact that the "by project/genre" half of the requirement was never built; the per-clip override half is what actually works. Functionally this doesn't block anything — a person can still route every scene manually — but it's a real, undisclosed gap against the spec's own wording.

## Related observation (not a defect) — genre can be edited on an already-locked job

`content_studio_view.py`'s "Project settings" card (`_build_settings_card`/`_handle_save_settings`) lets a person change `job.genre_id` (and platform/production mode/language) at any time, with no check on `job.script_lock`/`is_locked` and no call into `InvalidationService` — none of its three hooks (`on_script_changed`/`on_scene_replaced`/`on_audio_regenerated`) cover a genre change at all. In isolation this looks like a real anti-drift hole. Investigating further, though, the actual blast radius is small: every stage from `run_audience_promise()` (Stage 1) through `run_scene_planning()` (Stage 12) reads `job.editorial_profile_snapshot or resolve_editorial_profile(job)` — and the snapshot is set once, early, and reused thereafter — so a genre change after that point does not retroactively change how the script, hooks, or scenes were actually generated. None of the five Post-Script-Approval services that are genuinely genre-adjacent in spirit (`ProductionSemanticBriefService`, `VisualContinuityService`, `ShotPlanningService`, `CinematicPromptCompilationService`, `ClipMaterializationService`) reference `genre_id` at all — they all operate purely off already-locked script/scene/continuity data. The exposure that remains (older `TimelinePipelineStage`/`GenreDirectiveGenerationService` wiring, and jobs where a snapshot was never set) is legacy Content Studio Redesign architecture, not something introduced or left unaddressed by either audited PDF's own phases — so it's noted here for completeness rather than scored as a phase defect.

---

# Combined result across both documents

Across all 36 phases audited (20 in the Content Studio Redesign, 16 in the Post-Script-Approval Production Plan), the one open, undisclosed defect found in the first pass — the Content Studio Redesign's Phase 12 invalidation gap — is now fixed and verified. The follow-up anti-drift/genre-propagation pass surfaced three further **Minor**, previously unflagged gaps (above), none of which block normal use or corrupt output on their own. Everything else — including several dozen claims independently traced through actual code rather than trusted from the log — held up exactly as `PROJECT_PROGRESS.md` describes it, disclosed limitations included.
