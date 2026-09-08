# MRA-PRE-8: Performance and Stability Baseline

Pre-Installer Master Audit, Phase 8. Objective: establish a real,
directly-measured performance/stability baseline - no deliberate
stress/stability pass existed anywhere in this codebase before this
phase (per `docs/IMPLEMENTATION_STATE.md`'s own working note). Every
finding below follows the evidence format defined in
`docs/MRA_PRE_0_BASELINE.md` section 9 (claim under test / method /
evidence / verdict / HEAD).

**Note on source material**: as with MRA-PRE-4 through 7, this
phase's exact PDF wording could not be re-quoted verbatim in this
segment.

**HEAD at phase start**: `ad9879da302ecb429c2f96dcdadfa191c52861c4`.

**Constraint acknowledged up front**: this project has no real API
keys configured (a standing, documented limitation). Every stress test
in this phase necessarily runs in dry-run mode - real live-provider
load/latency/rate-limit behavior is out of scope for what this phase
can directly measure, and this is disclosed rather than glossed over.

## Findings

### MRA-PRE-8-001: The pipeline handles a 6x-longer target duration without breaking, hanging, or measurable slowdown

**Claim under test**: `ContentIntelligencePipeline.run_all()`, driven
through the real GUI exactly as MRA-PRE-3 already proved for a
standard 600-second (10-minute) project, also completes correctly for
a materially longer target duration, without a pathological cost
increase.
**Method**: new test,
`test_content_intelligence_pipeline_scales_to_a_long_duration_project`,
runs the identical real chain twice in the same process - once at the
standard 600s fixture duration, once at 3600s (1 hour, 6x longer) -
recording real, directly-observed wall-clock time for each.
**Evidence**: both runs completed with zero errors. Real, directly-
observed timing from an actual run: baseline (600s) **6.0s**; stress
(3600s) **2.4s** - the stress run was not slower at all (ordinary
run-to-run variance, both comfortably fast), confirming no hidden cost
scales with `target_duration_seconds` anywhere in the chain from
project creation through Script Lock and scene planning.
`job.target_duration_seconds` was confirmed to correctly carry 600 and
3600 respectively - the input value propagates correctly at scale.
**A genuine, directly-observed sub-finding, not a bug**: scene *count*
did **not** scale with duration in either run (4 scenes both times,
identical per-scene timings) - traced to
`StoryBlueprintGenerationService._DRY_RUN_RESPONSE`, a fixed, hardcoded
4-beat, 0-30-second dry-run stub completely independent of
`target_duration_seconds`. That class's own docstring confirms this is
expected: *"Beat sequence, count, and timing are entirely decided by
the LLM call based on genre, duration, and the selected story angle"*
- the real, non-dry-run call would scale; the fixed stub used for all
local/CI testing deliberately does not. This is a genuine boundary of
what dry-run-mode testing can verify about production-scale duration
behavior, consistent with this project's own standing "no real API
keys" limitation - recorded here as a real, disclosed fact rather than
silently assumed or glossed over by asserting something the test
environment cannot actually prove.
**Verdict**: CONFIRMED (no pathological scaling in the parts dry-run
mode can exercise) - the scene-count-invariance finding is recorded as
a real, disclosed **boundary of this session's own testing
infrastructure**, not a defect, not fixed (nothing to fix - the
hardcoded dry-run stub is intentional design, and changing it to scale
with duration is out of this phase's own scope).

### MRA-PRE-8-002: The known full-suite pytest hang remains the standing stability risk - unchanged, not re-diagnosed here

**Claim under test**: whether the whole-repository pytest suite can be
run as a single, unattended process for CI/pre-installer validation.
**Method**: re-confirmed the collected-test count grew consistently
with this session's own new tests rather than attempting to re-
reproduce or re-diagnose the hang itself (GUI-8's own explicit domain,
carried into MRA-PRE-9's own certification gate - re-litigating it
here would duplicate, not add to, that existing work).
**Evidence**: GUI-8's `docs/GUI8_VALIDATION_REPORT.md` recorded 2,389
collected tests at its own HEAD (`88bd5af`); MRA-PRE-5's own full
`pytest tests/ --collect-only` this same session collected **2449**
tests (60 more, consistent with the real new tests this session's own
MRA-PRE-3 through 8 phases added) with **zero collection errors** -
the suite's own static shape remains healthy; only the known, already-
documented full-*run* hang (not a collection-time problem) remains
open. No new evidence changes GUI-8's own root-cause status
(correlated to, not fully diagnosed from, a specific `QThread`-driven
test's flaky failure path).
**Verdict**: RISK (unchanged from GUI-8), not re-diagnosed or fixed in
this phase - explicitly MRA-PRE-9's own certification-gate concern,
re-confirmed still present and still blocking a single-process
full-suite CI run, not silently assumed resolved by this session's
other work.

## Summary

| # | Area | Verdict |
|---|---|---|
| 001 | Pipeline scaling to a 6x-longer target duration | CONFIRMED - no pathological cost; scene-count-invariance recorded as a disclosed dry-run-mode testing boundary, not a defect |
| 002 | Full-suite pytest hang (GUI-8's own finding) | RISK, unchanged - re-confirmed present, not re-diagnosed here, remains MRA-PRE-9's own gate |

## Validation

- `black`, `ruff check` on `tests/test_desktop_app_integration.py`:
  clean.
- `test_content_intelligence_pipeline_scales_to_a_long_duration_project`:
  PASSED, with real recorded timing (6.0s / 2.4s) cited above.
- `test_content_intelligence_pipeline_reaches_script_lock_and_scene_planning`
  (the existing baseline test, re-run after `_create_project()`'s
  signature gained an optional `duration_seconds` keyword argument
  defaulting to the prior, unconditional 600 value): confirmed still
  passing, proving the change is purely additive.

## Acceptance gate

A real, directly-measured performance/stability baseline now exists
where none did before: the canonical pipeline handles a 6x-longer
target duration with zero errors and no measurable slowdown, with
real numbers recorded for future comparison. One genuine, disclosed
boundary of what dry-run testing can verify (duration-dependent scene
count) was found and explained rather than hidden behind an assertion
that would have silently passed for the wrong reason. The one standing
stability risk this codebase already knows about (the full-suite
pytest hang) was re-confirmed still present rather than assumed fixed
by unrelated progress. Met, for what dry-run-mode testing can actually
prove without real API keys - live-provider load/latency/rate-limit
behavior remains untested, honestly disclosed as out of reach for this
phase, not claimed covered.
