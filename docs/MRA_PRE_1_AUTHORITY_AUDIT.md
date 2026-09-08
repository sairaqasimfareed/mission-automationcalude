# MRA-PRE-1: Authority and Architecture Audit

Pre-Installer Master Audit, Phase 1. Objective: prove there is one
authority for each critical concept. Every finding below follows the
evidence format defined in `docs/MRA_PRE_0_BASELINE.md` section 9
(claim under test / method / evidence / verdict / HEAD).

**HEAD at phase start**: `fb0f6ac49647709c71766151ec5d2d144bba823b`
(unchanged from the MRA-PRE-0 baseline).

## Findings

### MRA-PRE-1-001: Project

**Claim under test**: `VideoJob` is the sole persisted, reloadable
representation of a project; `ProjectSpecification` is not a
competing authority.
**Method**: code inspection (`src/services/project_specification_job_mapper.py`,
every call site of `ProjectSpecification`).
**Evidence**: `ProjectSpecificationJobMapper.map()` is a pure function
- takes a `ProjectSpecification`, returns a brand-new `VideoJob`, never
mutates or stores the specification itself. The only three consumers
of `ProjectSpecification` in the codebase are the mapper itself, the
desktop `ProjectFormView` (creation-time only), and
`mission_application_service.py`, whose own `resume()` path docstring
states directly: *"Resume deliberately bypasses ProjectSpecification
mapping"* - a documented, one-way, one-time translation, not a second
live authority.
**Verdict**: CONFIRMED.

### MRA-PRE-1-002: Genre - real bug found and fixed

**Claim under test**: `job.genre_id` is the single authority for which
genre profile every content-intelligence stage uses.
**Method**: code inspection of every writer of `job.genre_id` and
`job.editorial_profile_snapshot`, tracing the actual resolution
pattern used by every stage in `content_intelligence_pipeline.py`.
**Evidence**: `resolve_editorial_profile()`'s own docstring says
*"Re-resolves every call rather than trusting a stale snapshot, but
callers should generally read job.editorial_profile_snapshot after a
stage runs"* - and every stage from `run_research_plan()` onward
does exactly that: `editorial_profile = job.editorial_profile_snapshot
or (self.resolve_editorial_profile(job))`. This is correct *within* a
single, unbroken pipeline run - but `content_studio_view.py`'s
`_handle_save_settings()` (the Content Studio "Project settings" card,
reachable at any point after a project is created) allowed changing
`job.genre_id` directly with no corresponding invalidation of
`job.editorial_profile_snapshot`. Once any stage had already run and
populated the snapshot, a later genre change via Settings left
`job.genre_id` reporting the NEW genre while every downstream stage
kept silently using the OLD genre's resolved profile - a genuine,
silent authority split between two fields that are supposed to agree.
**Verdict**: GAP FOUND (severity: major - requires a specific but
real sequence: run a stage, then change genre, then run more stages;
non-destructive and recoverable, not classified critical). **Fixed**
in this phase: `_handle_save_settings()` now clears
`editorial_profile_snapshot` when the saved genre differs from the
job's current one, so the next stage correctly re-resolves against
the genre that is actually current. New adversarial tests:
`test_changing_genre_in_settings_invalidates_the_stale_editorial_profile`
(proves the fix) and
`test_saving_settings_with_the_same_genre_does_not_invalidate_the_profile`
(proves the fix isn't overzealous - re-saving without an actual genre
change must not discard a still-correct snapshot). Both pass; full
`test_content_studio_content_intelligence_gui.py` file re-run clean
alongside them (see section "Validation" below).

### MRA-PRE-1-003: Audience

**Claim under test**: audience-related fields have exactly one writer
each.
**Method**: code inspection - every writer of `job.target_audience`
and `job.audience_promise`.
**Evidence**: `target_audience` is set once at project creation
(`ProjectSpecificationJobMapper`/`ProjectFormView`) and is not among
the fields `_handle_save_settings()` allows changing post-creation -
confirmed by reading that method's own parameter list (genre/platform/
production_mode/approval_mode/language/target_country only).
`job.audience_promise` has exactly one write site in the entire
codebase: `content_intelligence_pipeline.py`'s `run_audience_promise()`
(Stage 1). Every other reference is a read (`if job.audience_promise is
None`-style gating).
**Verdict**: CONFIRMED.

### MRA-PRE-1-004: Approval

**Claim under test**: every approval/human-in-the-loop decision in the
codebase resolves through one shared mechanism, with no independent,
ad-hoc "should this proceed automatically" logic elsewhere.
**Method**: code inspection of `ApprovalService`/`ApprovalGateService`
plus a repository-wide search for confidence-threshold-style
auto-continue logic outside those two files.
**Evidence**: `ApprovalGateService` explicitly composes
`ApprovalService` as a dependency (`self.approval_service =
approval_service or ApprovalService()`) rather than reimplementing
decision logic - a layered design, not a duplicate. A grep across
every `src/services/*.py` file for `confidence_threshold`,
`DEFAULT_CONFIDENCE_THRESHOLD`, `requires_human_review`, and
`needs_approval` outside `approval_service.py`/`approval_gate_service.py`
returned zero matches. Google Flow's Agent-mode confirmation gate
(`google_flow_generation_orchestrator_service.py`) calls
`ApprovalService().open_decision()` directly rather than any separate
mechanism.
**Verdict**: CONFIRMED.

### MRA-PRE-1-005: Reviewer - cannot become the author

**Claim under test**: Reviewer/critique output can never be written
back into an authoritative content field, at the service level (not
just visually distinguished in the GUI, which GUI-0 already confirmed
separately).
**Method**: code inspection - every writer of `job.generated_script`
in the entire codebase.
**Evidence**: `ReviewerService`'s own docstring states *"The Reviewer
never authors an alternative... Applying a suggestion is always a
separate action that goes through Primary"*. A grep for every
`job.generated_script = ...` assignment across all of `src/services/`
found exactly five write sites, all inside
`content_intelligence_pipeline.py` itself, and all backed by a
legitimate producer/revision service (script generation, narrative
compression, `ScriptRevisionService`, or a version-history rollback) -
none inside `reviewer_service.py` or `editorial_critique_service.py`.
The separation is structural (no code path exists for the Reviewer to
write this field), not merely a naming convention.
**Verdict**: CONFIRMED.

### MRA-PRE-1-006: Script Lock

**Claim under test**: exactly one service builds/validates a Script
Lock record, and the lock/unlock state itself is never independently
flipped elsewhere.
**Method**: code inspection of `ScriptLockService` and its own
documented division of responsibility with
`ContentIntelligencePipeline`.
**Evidence**: `ScriptLockService`'s own docstring: *"Deliberately does
not itself flip ScriptVersion.locked... that's orchestration
ContentIntelligencePipeline.run_script_lock()/run_script_unlock()
perform."* `build_lock()` refuses to build a lock at all when
unresolved blocking quality findings or continuity-critical production
ambiguities exist, unless an explicit, non-empty `override_reason` is
supplied - a real hard blocker, not a soft warning. The lock record
snapshots `genre_id`/`topic`/`target_duration_seconds`/`angle` at lock
time, which is correct provenance behavior (a lock should freeze what
was true when it was created, not drift with later edits) rather than
a duplicate-authority risk.
**Verdict**: CONFIRMED.

### MRA-PRE-1-007: Phase 0-15 artifacts - a real, deliberate duplicate found (minor, not blocking)

**Claim under test**: no two independent code paths can write the same
production artifact for the same project.
**Method**: code inspection - every writer of `job.scenes`, cross-
referenced against `content_studio_view.py`'s own GUI-reachability.
**Evidence**: `job.scenes` has two independent, GUI-reachable writers:
the legacy `ContentPipeline.scene_planner.plan()` (via
`_handle_plan_scenes()`, reading the OLD `job.script` field) and the
new `ContentIntelligencePipeline`'s
`scene_planner.plan_from_generated_script()` (reading the NEW
`job.generated_script` field). Both are reachable from the same live
`ContentStudioView` for the same project. This is a **known,
documented, deliberate design tradeoff**, not an oversight -
`_build_legacy_pipeline_notice()`'s own docstring explains the legacy
pipeline is *"still fully functional and deliberately left in place
(no destructive rewrite)... superseded by the Content Intelligence
card above for any project using it"*, with a visible notice steering
new projects toward the current path. The notice is suppressed once
either pipeline has produced something, but the legacy panels
themselves stay fully functional below it - the old "Plan scenes"
button only becomes reachable after a user has *also* run the full
legacy research -> script -> originality-review sequence, a
deliberate, multi-step path a user would not reach by accident.
**Verdict**: RISK, classified **minor** (real, but requires a
specific, unlikely multi-step user action; an existing, working
mitigation - the redirect notice - is already in place; matches this
project's own explicit "no destructive rewrite" design philosophy).
**Not fixed in this phase** - disabling the legacy scene-planning
button once new-pipeline fields exist would be a reasonable follow-up
but is scoped as GUI/UX work, not a pure audit-discovered defect fix,
and risks stranding an in-progress legacy-pipeline project the way the
existing docstring already explains this design deliberately avoids.
Recorded for a future GUI/UX pass, not blocking this phase's gate.
Full Phase 0-15 tracing through a real project is MRA-PRE-3's own,
separate job - this finding is scoped to the one duplicate-authority
risk found in passing, not a substitute for that phase.

### MRA-PRE-1-008: Brand

**Claim under test**: N/A check - does a "Brand" concept exist in this
codebase at all.
**Method**: repository-wide case-insensitive class-name search across
`src/models/*.py` and `src/services/*.py`.
**Evidence**: zero matches for any `class .*Brand.*` definition
anywhere in the codebase.
**Verdict**: CONFIRMED N/A - "Brand if enabled" resolves to "not
enabled, not built." No authority question to audit until/unless this
feature is ever added.

### MRA-PRE-1-009: Publishing and final package

**Claim under test**: SEO/thumbnail/final-export packages are each
written through exactly one repository interface, from exactly one
GUI location, with no service bypassing the store to write these
artifacts directly elsewhere.
**Method**: code inspection - `JobStore`'s own interface plus every
real call site of `set_seo_package`/`set_thumbnail`/`set_final_export`.
**Evidence**: `JobStore` (both `InMemoryJobStore` and `JsonJobStore`)
each declare exactly one `set_seo_package()`/`get_seo_package()`,
`set_thumbnail()`/`get_thumbnail()`, `set_render_result()`/
`get_render_result()`, and `set_final_export()`/`get_final_export()`
pair. Every real call site of the three `set_*` methods across the
entire codebase is in `src/desktop/views/packaging_view.py` - the one
canonical GUI location for packaging actions. No service writes these
artifacts to disk or anywhere else outside this store-mediated path.
**Verdict**: CONFIRMED.

## Summary

| # | Concept | Verdict |
|---|---|---|
| 001 | Project | CONFIRMED |
| 002 | Genre | GAP FOUND (major) - **fixed this phase** |
| 003 | Audience | CONFIRMED |
| 004 | Approval | CONFIRMED |
| 005 | Reviewer | CONFIRMED |
| 006 | Script Lock | CONFIRMED |
| 007 | Phase 0-15 (scene-planning duplicate) | RISK (minor) - recorded, not fixed |
| 008 | Brand | CONFIRMED N/A |
| 009 | Publishing / final package | CONFIRMED |

## Validation

- `black`, `ruff check`, `mypy` on `src/desktop/views/content_studio_view.py`: all clean.
- New tests `test_changing_genre_in_settings_invalidates_the_stale_editorial_profile`
  and `test_saving_settings_with_the_same_genre_does_not_invalidate_the_profile`:
  both passed.
- Full `tests/test_content_studio_content_intelligence_gui.py`: 133
  passed (including the 2 new ones), 0 failed, in 263.58s. mypy's one
  finding at line 3225 is the same pre-existing, unrelated
  `job.generated_script.segments` union-attr issue confirmed elsewhere
  in this project's history - not introduced by this phase.

## Acceptance gate

*"No unresolved critical duplicate authority or bypass remains."* Met:
the one confirmed GAP (genre/editorial-profile drift) has been fixed
and tested in this same phase; the one remaining RISK (scene-planning
dual-writer) is classified minor, not critical, per its own real,
documented mitigating factors, and is recorded rather than hidden for
a future GUI/UX pass. No other critical duplicate authority or bypass
was found across Project, audience, approval, Reviewer, Script Lock,
Brand, or publishing/final package.
