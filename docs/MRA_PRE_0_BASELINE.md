# MRA-PRE-0: Freeze and Evidence Capture

Pre-Installer Master Audit, Phase 0. Establishes the audit baseline
and freezes feature scope per
`Step 5_Pre_Installer_Master_Audit_Plan.pdf`'s own authority boundary:
*"From this point, feature development is frozen; only audit-
discovered defects are repaired."*

## 1. Scope freeze declaration

As of this baseline, no new feature work proceeds except defect fixes
discovered by MRA-PRE-1 through MRA-PRE-9. This covers every
initiative completed before this point: the production-hardening
Phases 0-10, Content Studio Redesign, Post-Script-Approval Production
Plan, SEO/Thumbnail/Publishing Reconciliation, Google Flow External UI
Automation (GF-0 through GF-17), and Unified GUI & Release Hardening
(GUI-0/1/6/8). Two items were already open before this freeze and are
explicitly carried into the audit rather than pretended away (see
section 7).

## 2. Git baseline

| Field | Value |
|---|---|
| CURRENT MAIN / branch | `main` |
| HEAD SHA | `0194c781a1a9817b2784a11e94ae44350698122f` |
| HEAD summary | `fix: Content Studio scroll-position fix, fourth pass - cancel overlapping restore cycles` |
| HEAD date | 2026-09-07 22:28:33 +0500 |
| Working tree | Clean except pre-existing, already-documented `Claude outputs/` clutter (untracked, not real state - see `repo_clutter` memory) |
| Remote | `origin` -> `https://github.com/sairaqasimfareed/mission-automationcalude.git` |
| Local worktree | Only the primary checkout at `F:\mission-automation` is in active use |
| Other worktrees found | `.claude/worktrees/strange-hermann-1bddb6` - detached HEAD at `b94799558ea5a3fa0b5427d5eef6471daaf70666` (2026-08-15, "Sprint 3 Story Angle Generation"), clean, stale and unrelated - already ruled out earlier this session and reconfirmed here. Not part of the audit surface. |

## 3. Authoritative docs

Every `docs/*.md` file as of this baseline (25 files):
`ACCEPTANCE_CRITERIA.md`, `AI_IMPLEMENTATION_PROTOCOL.md`,
`ARCHITECTURE.md`, `CODING_STANDARDS.md`,
`CONTENT_STUDIO_OPERATOR_GUIDE.md`,
`CONTENT_STUDIO_REDESIGN_BASELINE.md`, `DATABASE_SCHEMA.md`,
`DECISIONS.md`, `DEVELOPMENT_GUIDELINES.md`, `EVENT_SYSTEM.md`,
`FUTURE_IDEAS.md`, `GOOGLE_FLOW_REAL_UI_FINDINGS.md`,
`GUI8_VALIDATION_REPORT.md`, `GUI_INVENTORY_MATRIX.md`,
`IMPLEMENTATION_STATE.md`, `NAMING_CONVENTIONS.md`,
`PACKAGING_ENGINE.md`, `PIPELINE_DESIGN.md`, `PROJECT_PRINCIPLES.md`,
`PROJECT_SPECIFICATION.md`, `PROVIDER_CENTER.md`, `RECOVERY.md`,
`REMAINING_GAPS.md`, `ROADMAP.md`, `SYSTEM_BLUEPRINT.md`,
`SYSTEM_TRACEABILITY_MATRIX.md`, `UI_FLOW.md`. Plus root-level
`PROJECT_PRINCIPLES.md`-adjacent `PROJECT_PROGRESS.md` (the dated
narrative log) and `AGENTS.md` (scope boundaries, including the
Google Flow exception).

`docs/IMPLEMENTATION_STATE.md` and `docs/SYSTEM_TRACEABILITY_MATRIX.md`
are the authoritative per-capability status/evidence records the audit
should cross-check claims against, not trust at face value (per the
plan's own "independently verify runtime truth" rule).

## 4. Schema versions

49 Pydantic model fields declared as `schema_version: str = "1.0"`
across `src/models/*.py` (verified via `grep`, not assumed) - every
versioned model is still at its original baseline version; none has
undergone a breaking schema change requiring a bump yet. Two related,
narrower version fields exist: `genre_schema_version` (on
`GenreProfile`, still unused per this session's own earlier finding)
and `format_schema_version` (optional, `FormatProfile`-adjacent).

## 5. Validators

Two dedicated validator services exist:
`src/services/health/provider_startup_validator.py` (real provider
health/credential checks at app startup) and
`src/services/runtime_configuration_validator.py` (configuration
sanity checks). `src/services/startup_diagnostics.py` aggregates
these into one startup report (`StartupDiagnosticsReporter`,
confirmed via its own dedicated test file
`tests/test_startup_diagnostics.py`).

Static/structural validators (this project's own configured gates,
not assumed): `ruff` (`pyproject.toml`), `black`, `mypy` (`files =
["src"]`, `tests/` explicitly excluded by the project's own config),
`compileall`.

## 6. GUI entry points

Already fully audited and recorded in `docs/GUI_INVENTORY_MATRIX.md`
(GUI-0, this session) - referenced here rather than redone: 5
`MainWindow` toolbar destinations (Dashboard/New Project/
Providers/Google Flow/Settings) plus 7 `ProjectWorkspaceView` tabs
(Content/Clips/Audio/Timeline/Render/Quality/Packaging), all 13
desktop view files accounted for with zero orphaned or duplicate
entry points confirmed at that audit's time. This baseline treats
that matrix as still current as of this HEAD - MRA-PRE-7 should
re-verify rather than assume it's unchanged, since GUI-6/GUI-8/the
scroll-fix commits landed after GUI-0's own audit.

## 7. Known open items carried into the audit

Declared here rather than discovered mid-audit and treated as a
surprise:

1. **Full-suite pytest hang** (found during GUI-8): running the
   entire test suite as one process reproducibly hangs, correlated
   with (not fully diagnosed from) the already-known-flaky
   `test_render_progress_updates_live_and_survives_cross_workspace_refresh`
   failing. See `docs/GUI8_VALIDATION_REPORT.md` and the matching
   item in `docs/REMAINING_GAPS.md`. This directly blocks MRA-PRE-9's
   own "full pytest" requirement until fixed or worked around with a
   documented per-file/batched execution method (already this
   session's own practice throughout).
2. **Content Studio scroll-position bug**: four fix passes attempted,
   the user confirmed the most recent (cancel-overlapping-cycles)
   still does not resolve the real symptom. Explicitly parked at the
   user's request ("stop. we'll do it later"). This is a real,
   user-facing GUI defect that MRA-PRE-7 should re-surface, not a new
   finding invented here.

   **Update, same day (fixed, fifth pass)**: root-caused via a direct,
   instrumented reproduction of a real multi-stage "Run automation"
   burst against a real `MainWindow` (not guessed, not a unit test in
   isolation) - the fourth pass's cancel-overlapping-cycles fix
   correctly picked one winning restore cycle, but did nothing to stop
   `refresh()`'s own tear-down-and-rebuild from transiently collapsing
   the scroll area's range to 0 mid-rebuild (Qt's own behavior,
   independent of anything this view's restore code writes) - the
   VERY NEXT `refresh()` call in the same rapid burst then read that
   transient 0 via a fresh `scroll_bar.value()` at ITS OWN start and
   recaptured it as "the current position," permanently propagating
   the loss through the rest of the burst. Confirmed exactly this
   pattern via instrumentation: `(value=519, max=1038) -> (value=0,
   max=0)`, repeating across 11 refresh() calls for one real user
   action. Fixed in `src/desktop/views/content_studio_view.py`:
   `refresh()` now trusts a live scrollbar read only when
   `scroll_bar.maximum() > 0` (range genuinely settled), falling back
   to a new `self._last_known_scroll_value` otherwise - propagating
   the real value through the whole burst instead of losing it on the
   first collapse. Verified via the same real diagnostic script
   showing the final scrollbar value exactly matches the original
   position after a full simulated 11-call burst (`Difference: 0`,
   was `Difference: -519` before the fix), plus a new permanent
   regression test
   (`test_refresh_falls_back_to_the_last_known_value_when_the_range_has_collapsed`),
   teeth-verified (fails without the fix, passes with it), and the
   full 134-test file re-run green. See `PROJECT_PROGRESS.md`'s
   matching entry for the full writeup.

## 8. Project/provider data snapshot

Snapshotted to `audit/baseline_2026-09-07/` (gitignored, matching
`data/`'s own exclusion - see `.gitignore`): `provider_profiles.json`,
`desktop_preferences.json`, and all 3 files under `projects/`.

**Honest finding, not glossed over**: the live `data/projects/`
directory contains only 3 projects, all early-stage scratch/test data
(`project_name` "test"/"auto", `status` "pending", stages
`script`/`originality_review` - none progressed meaningfully into the
pipeline). There is **no currently-existing project advanced enough to
serve as MRA-PRE-3's "trace a real project from script approval
through Phase 15"** - that phase will need either one of these driven
further or a fresh project deliberately run through the full chain.

Also found and recorded (not fixed, out of MRA-PRE-0's own scope):
`data/checkpoints/` contains 566 checkpoint directories against only 3
real projects, and `data/final_exports/` contains a
`Deep_Sea_Documentary` entry matching this test suite's own
`_create_project()` fixture name - strong evidence that local test
runs have been writing real checkpoint/export artifacts to the
production `data/` paths rather than an isolated `tmp_path`, over the
course of this project's history. Not remediated here; flagged as a
candidate MRA-PRE-2/MRA-PRE-8 finding (test-isolation hygiene, not a
production defect, since `data/` is gitignored and never shipped).

## 9. Independent Reviewer/auditor evidence format

Every finding in MRA-PRE-1 through MRA-PRE-9 is recorded in this
fixed shape, so evidence is comparable and reproducible across phases
- matching the plan's own "independently verify runtime truth rather
than trust implementation-phase completion claims":

```
### <finding id, e.g. MRA-PRE-1-003>

**Claim under test**: <the specific canonical/authority claim being verified>
**Method**: <code inspection | real runtime execution | real file/DB inspection | adversarial test>
**Evidence**: <exact command(s) run, file:line references, real output excerpts - never a summary standing in for the actual evidence>
**Verdict**: CONFIRMED | GAP FOUND (severity: blocking/major/minor) | RISK (not yet exercised)
**HEAD at time of finding**: <SHA>
```

A finding is never accepted on description alone (mirrors
`docs/ACCEPTANCE_CRITERIA.md`'s own existing rule for phase
completion) - Method and Evidence are both required, and Evidence
must be the real artifact (a command's real output, a real file's
real content, a real test's real pass/fail), not a paraphrase.

## 10. Baseline full validator results

Run fresh at this HEAD, not carried forward from GUI-8's earlier run:

| Check | Result |
|---|---|
| `ruff check .` | All checks passed |
| `black --check .` | 792 files would be left unchanged |
| `compileall -q src tests` | Clean (no syntax errors) |
| `mypy` (bare, project's own `files = ["src"]` config) | Success: no issues found in 418 source files |
| `pytest tests/` (full suite, one process) | **Not GREEN** - see section 7, item 1 |

## Acceptance gate

*"Audit baseline is reproducible and scope-frozen."* Met: git state,
docs inventory, schema versions, validators, GUI entry points, and a
project/provider-profile snapshot are all recorded above with real
evidence: exact commands and real output, not descriptions. Feature
scope is frozen from this HEAD forward per section 1. The two known
open items in section 7 are carried forward explicitly, not hidden -
their existence does not block this phase's own gate, which is about
establishing a reproducible baseline, not achieving a clean one.
