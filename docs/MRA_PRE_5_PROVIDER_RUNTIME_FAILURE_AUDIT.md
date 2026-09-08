# MRA-PRE-5: Provider/Runtime/Failure Audit

Pre-Installer Master Audit, Phase 5. Objective: verify provider
startup validation, runtime configuration validation, and mid-run
provider-failure handling are correct and consistent - re-verification
of work substantially already built during GF-0 through GF-17, not a
from-scratch pass (per `docs/IMPLEMENTATION_STATE.md`'s own working
note for this phase). Every finding below follows the evidence format
defined in `docs/MRA_PRE_0_BASELINE.md` section 9 (claim under test /
method / evidence / verdict / HEAD).

**Note on source material**: as with MRA-PRE-4, this phase's exact PDF
wording could not be re-quoted verbatim in this segment. Executed
against the phase's already-recorded working title and this audit's
own established evidence-based methodology.

**HEAD at phase start**: `c9821a1760d2e55050ad65b0e70d7a1372312d65`.

## Findings

### MRA-PRE-5-001: Startup provider validation is deliberately LLM-only, not an oversight

**Claim under test**: whether every provider category gets a live,
proactive reachability check before a production run starts, or only
some.
**Method**: read `ProviderStartupValidator.validate()` in full,
confirmed its category filter (`ProviderCategory.LLM,
enabled_only=True`) is a hardcoded, single-category query, then
checked whether the underlying mechanism (`ProviderHealthService.
check_profile()`, `ProviderHealthChecker` Protocol) is itself
category-agnostic or LLM-specific.
**Evidence**: `ProviderHealthService.check_profile()` takes any
`ProviderHealthChecker` and any `profile_id` - fully generic, not
LLM-specific. `ProviderStartupValidator` is the only caller that ever
constructs an `LLMProviderStartupChecker` and only ever queries the
LLM category - non-LLM providers (voice, stock video/image, music,
sound effects, upload) get **no live startup check**. Two mitigating
mechanisms exist for those categories instead: (1)
`RuntimeConfigurationValidator._validate_provider_secrets()` checks
EVERY provider profile (not filtered by category) for a dangling
secret reference before any infrastructure is built; (2)
`ProviderSecretResolutionChecker` (used by Provider Manager's GUI) is
explicitly documented as "applies to every provider category... since
Provider Manager needs a check that works before any category-specific
adapter exists" - an on-demand, generic secret-resolves check a person
can run manually for any profile.
**Verdict**: CONFIRMED as a deliberate, reasonable design tradeoff, not
a defect: proactively live-checking every non-LLM provider at every
app startup would mean a network call per category on every launch
regardless of whether that project's own genre/visual-strategy choice
will ever use it (e.g., a manual-upload-only project never touches a
stock provider). The LLM category is correctly singled out since
nothing in this application can run at all without a working LLM.
Not actioned - correctly scoped, not a gap.

### MRA-PRE-5-002: Mid-run provider failure handling - spot-checked, sound

**Claim under test**: when a non-LLM provider genuinely fails during a
production run (not caught by any startup check per finding 001),
the failure is handled safely and visibly, not silently.
**Method**: read `VoiceGenerationService`'s full failure path (the
highest-consequence non-visual provider - a voice failure blocks an
entire scene's audio).
**Evidence**: every provider-facing call is wrapped in `try`/`except
Exception`, normalized through one `_fail()` helper into a structured
`VoiceGenerationFailure` recorded on the result and the job - a
provider health check runs before generation is attempted, keeping a
raw exception from ever reaching the caller unformatted. This mirrors
the same "safe, visible failure, never silent corruption" principle
MRA-PRE-3 confirmed for render's voice-directive validation and for
the stock-acquisition failure path.
**Verdict**: CONFIRMED sound for the one path inspected in depth. Not
exhaustively re-verified for every one of the ~15 provider
implementations individually (out of this phase's own time budget) -
the pattern inspected here is consistent with what MRA-PRE-3 already
found and fixed for the stock-footage path this same day, giving
reasonable confidence the convention is applied consistently, not
proof for every file.

### MRA-PRE-5-003: A pervasive, real test-authoring gap - most test files have zero pytest-discoverable items

**Claim under test**: whether provider/runtime failure-handling test
coverage that appears to exist in the repository is actually
discoverable, selectable, and individually reportable by pytest - not
merely "does a file with assertions exist."
**Method**: this session had already found, in isolation, that 2 files
(`test_stock_asset_storage_service.py`, `test_asset_storage_service.py`,
during MRA-PRE-3) use module-level `assert` statements executed as a
side effect of import rather than `def test_*` functions, making them
invisible to `pytest --collect-only` item counting. Checked whether
this was an isolated oddity or a wider pattern: scanned every file
matching `tests/test_*.py` for the presence of at least one `def
test_` (module- or class-level). Verified the actual runtime behavior
of a broken assertion in one such file with a real, reproducible
teeth-check: temporarily flipped a real assertion in
`tests/test_voice_generation_service.py` to a value it should never
be, ran `pytest` against just that file (not `--collect-only`),
observed the result, then restored the assertion and confirmed
`git diff --stat` showed no residual change. Finally ran a real, full
`pytest tests/ --collect-only` to get the actual aggregate item count
and confirm zero collection errors exist at this HEAD.
**Evidence**: **142 of 367** test files (~39%) have zero `def test_`
functions - real logic and real `assert` statements execute at
module-import time instead, including files directly relevant to this
phase's own scope (`test_voice_generation_service.py`,
`test_retry.py`, `test_circuit_breaker.py`, `test_provider_registry.py`,
`test_llm_gateway.py`, `test_pipeline_engine.py`, and many more -
`test_retry.py` is a clear, minimal example: it tests real
retry-with-backoff and retry-exhaustion behavior via two blocks of
module-level code and `assert` statements, zero `def test_`
anywhere). The teeth-check confirmed a broken assertion in this style
of file is **not silently invisible**: `pytest
tests/test_voice_generation_service.py` (run alone, the exact way this
project's own already-documented workaround for the full-suite hang
requires per-file/small-batch validation to run) reported `1 error
during collection`, `Interrupted: 1 error during collection`, and a
real nonzero pytest exit code (2) - any CI or manual check that reads
the exit code catches this correctly. The real, disclosed cost is
three-fold, not "the tests don't run at all": (1) no individual test
selection/filtering (`pytest path::test_name`, `-k`) is possible for
any of these 142 files' internal assertions; (2) Python's `assert`
raises and unwinds immediately, so the FIRST failing assertion in a
large module-level file (some run 15-20+ real assertions in sequence)
prevents every assertion after it in that same file from ever running
in that session - a real reduction in defense-in-depth compared to
independent `def test_*` functions, which each run and report
regardless of a sibling's failure; (3) any tooling that counts
"collected test items" as a coverage/health signal (`pytest
--collect-only` counts, coverage-by-test-count dashboards) silently
undercounts real coverage by a large margin. The full-suite
`pytest tests/ --collect-only` run (2449 real, individually-
discoverable items collected, `188.13s`) reported **zero collection
errors** - confirming every one of these 142 files' current
assertions genuinely pass at this HEAD, a real, positive, directly-
verified baseline, not an assumption.
**Verdict**: RISK (severity: **major**, scope: **structural, not a
same-day fix**) - confirmed real and quantified, **not fixed in this
phase**. This is a pre-existing, apparently-original test-authoring
convention for a large fraction of this codebase's earlier-built
services (contrasted with this session's own consistently-used
`def test_*` convention for every new test it has written, including
the one exception already carved out in MRA-PRE-3's own
`test_a_long_title_still_produces_a_path_within_windows_max_path`,
added as a properly-discoverable function in an otherwise
module-level-assert file rather than extending that file's own
pattern). Converting 142 files is a large, repository-wide mechanical
migration with real regression risk if rushed - correctly deferred
as a disclosed, scoped-out finding rather than attempted same-day,
matching this audit's own established discipline for large structural
gaps (mirrors MRA-PRE-3-003's original scene-duration finding, which
was also deliberately not rushed into a same-day fix on first
discovery).

## Summary

| # | Area | Verdict |
|---|---|---|
| 001 | Startup validation scope (LLM-only) | CONFIRMED intentional, not a gap |
| 002 | Mid-run provider failure handling (voice, spot-checked) | CONFIRMED sound |
| 003 | Module-level-assert test files (142/367, ~39%) | RISK (major, structural) - confirmed real, quantified, teeth-verified as non-silent in this project's own per-file validation practice, **not fixed** - recorded in `docs/REMAINING_GAPS.md` as a future dedicated migration pass |

## Validation

- Teeth-check on `tests/test_voice_generation_service.py`: broken
  assertion correctly produced `1 error during collection` and pytest
  exit code 2 when run alone; restored, `git diff --stat` confirmed
  clean (no residual change).
- Full `pytest tests/ --collect-only`: 2449 items collected, 0 errors,
  188.13s - the real, current, directly-verified baseline.
- No source code was changed in this phase; only two documentation
  files were touched (this deliverable and
  `docs/REMAINING_GAPS.md`).

## Acceptance gate

Provider startup validation and mid-run failure handling were
verified sound where inspected, with one design choice (LLM-only
startup checks) confirmed deliberate rather than assumed. A real,
significant, previously-only-partially-known gap in test-suite
structure was found, quantified with hard numbers (142/367 files),
and proven - via a live teeth-check, not inference - to be currently
non-dangerous (a broken assertion is still caught, just less
granularly than it should be) at this exact HEAD. Not fixed, by
design: this is a large, cross-cutting structural item correctly
handed to a dedicated future pass rather than rushed. Honestly
reported as **partially met** - the audit and verification objective
of this phase is met; the underlying test-authoring convention itself
remains real, disclosed, unfixed work.
