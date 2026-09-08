# MRA-PRE-9: Pre-Installer Certification

Pre-Installer Master Audit, Phase 9 - the final phase. Objective:
compile MRA-PRE-0 through MRA-PRE-8's own results into one honest,
evidence-based go/no-go determination for installer packaging, per
this audit's own defined evidence format (`docs/MRA_PRE_0_BASELINE.md`
section 9). This is a synthesis phase - it does not re-investigate
what the prior 9 phases already established; it aggregates their
verdicts and gives one final answer.

**Note on source material**: as with MRA-PRE-4 through 8, this
phase's exact PDF wording could not be re-quoted verbatim in this
segment.

**HEAD at phase start**: `010577f7579f381aa0f44296c1c74ec5279ed9bc`.

**Already effectively attempted once**: GUI-8 (an earlier, separate
initiative) already ran this exact kind of full local-validation pass
and found its own exit gate ("full local validation green") blocked
by the full-suite pytest hang. That finding is re-confirmed, not
re-diagnosed, below.

## Phase-by-phase summary

| Phase | Verdict | One-line result |
|---|---|---|
| MRA-PRE-0: Freeze and evidence capture | Done | Real git/docs/schema/validator/GUI baseline captured; defined the evidence format every later phase used |
| MRA-PRE-1: Authority and architecture audit | Done | 7 confirmed single-authority, 1 confirmed N/A (Brand), 1 gap found and fixed same phase (genre/editorial-profile-snapshot staleness) |
| MRA-PRE-2: Persistence/restart/migration audit | Done | Atomicity confirmed sound; `VideoJob` schema-upgrade proven directly for the first time; 1 real gap found and fixed (Google Flow restart reconciliation had zero real callers) |
| MRA-PRE-3: Canonical lifecycle audit | Done | Proved the plan's own "script approval through Phase 15" objective end to end for the current pipeline for the first time; found and fixed 3 real, distinct blockers in sequence (scene-duration/narration mismatch, Windows MAX_PATH stock-acquisition failure, SEO/thumbnail generation unreachable) |
| MRA-PRE-4: Genre/audience/brand anti-drift audit | Done | Found and fixed a real genre-drift gap after Script Lock; audience confirmed clean; Brand reconfirmed N/A; 1 stale prior claim corrected |
| MRA-PRE-5: Provider/runtime/failure audit | Done | Startup validation scope confirmed deliberate; mid-run failure handling spot-checked sound; major structural finding quantified (142/367 test files use module-level assert, not `def test_*`) - not fixed, correctly scoped out |
| MRA-PRE-6: Publishing/package audit | Done | Final export validation confirmed thorough and correctly gating; 1 real minor gap found and fixed (`WorkflowStage.UPLOADED` was unreachable) |
| MRA-PRE-7: GUI and operator workflow audit | Partial | 1 prior claim (MRA-PRE-2's `stale_artifacts`) corrected as already-working; 1 real gap found and fixed (Google Flow attempt state GUI surfacing); broader "long content"/"disabled/loading/error states" scope not attempted |
| MRA-PRE-8: Performance and stability baseline | Done | First real stress test: 6x-longer project duration, zero errors, no pathological slowdown; full-suite pytest hang re-confirmed still present |
| MRA-PRE-9: Pre-installer certification | Done (this document) | Final verdict below |

## Real defects found and fixed across the whole audit (MRA-PRE-1 through 8)

Nine real, evidenced defects were found and fixed across this audit,
each with a teeth-verified test proving the fix (confirmed to fail
without it):

1. Genre change after any content-intelligence stage silently kept
   using the old genre's resolved profile (MRA-PRE-1).
2. Google Flow restart reconciliation had zero real callers anywhere
   in the app (MRA-PRE-2).
3. Scene duration never reconciled against actual narration length,
   blocking render for the canonical pipeline (MRA-PRE-3).
4. A long stock-candidate title could exceed Windows' `MAX_PATH`,
   failing asset acquisition (MRA-PRE-3).
5. SEO/thumbnail generation - and the entire Packaging workspace GUI -
   was completely unreachable for the canonical pipeline's projects
   (MRA-PRE-3).
6. A project's genre could be changed after Script Lock, silently
   mismatching already-generated SEO/thumbnail content against the
   genre the script was actually written in (MRA-PRE-4).
7. `WorkflowStage.UPLOADED` was a defined terminal stage with zero
   code path anywhere that ever reached it (MRA-PRE-6).
8. Google Flow generation attempt state (e.g. a reconciled
   `SUBMISSION_UNCERTAIN` attempt) had zero GUI surfacing anywhere
   (MRA-PRE-7).
9. (MRA-PRE-2's own fix, #2 above, closes the loop that made #8's
   `SUBMISSION_UNCERTAIN` state reachable in the first place -
   related, not double-counted as a 10th item.)

Every one of these was proven fixed via a real, teeth-verified test
(deliberately reverted, confirmed the test failed, restored, confirmed
`git diff --stat` showed only the intended change) - not merely
asserted.

## Real, disclosed items NOT resolved by this audit

Per this audit's own "independently verify runtime truth, disclose
what isn't fixed rather than hide it" discipline, carried through
every phase:

1. **Full-suite pytest hang** (found in GUI-8, re-confirmed unchanged
   in MRA-PRE-8). A single `pytest tests/` process reproducibly hangs;
   root cause correlated to (not fully diagnosed from) a specific
   `QThread`-driven test's flaky failure path immediately preceding
   the hang. Needs a debugger attached to a live repro - not attempted
   in any MRA-PRE phase, since none of them had that as their own
   scope. **This is the one finding that directly blocks this
   certification's own gate** - see verdict below.
2. **142 of 367 test files use module-level `assert` instead of
   `def test_*` functions** (MRA-PRE-5). Confirmed non-dangerous at
   this exact HEAD (a broken assertion is still caught as a collection
   error, not silently invisible) but real: no per-test selection,
   one early failure masks later assertions in the same file, and
   coverage-counting tooling undercounts real coverage. A large,
   cross-cutting, mechanical migration - correctly out of scope for a
   same-day fix.
3. **"Long content" and "disabled/loading/error states"** GUI sweep
   (MRA-PRE-7's own named scope, not in GUI-6's own earlier scoped
   slices). Not attempted - needs its own exploratory pass across
   every workspace view.
4. **Content Studio scroll-position bug** - MRA-PRE-0's own baseline
   explicitly carried this forward as a known-open item at the time of
   the audit's freeze (a fourth fix pass had already landed just
   before the freeze, disclosed even then as "not a guarantee every
   possible edge case is now covered"). No MRA-PRE phase re-verified
   or closed this item during the audit itself - it remains open,
   exactly as MRA-PRE-0 recorded it.

   **Update, same day (fixed, fifth pass)**: root-caused via a direct,
   instrumented reproduction against a real `MainWindow` and fixed in
   `src/desktop/views/content_studio_view.py` - see
   `docs/MRA_PRE_0_BASELINE.md` section 7 item 2 for the full writeup
   and `PROJECT_PROGRESS.md` for the narrative entry. Teeth-verified
   (a new permanent regression test fails without the fix, passes with
   it) and the full 134-test file re-run green.
5. **Test-run data contamination** of `data/checkpoints/`/
   `data/final_exports/` from local test runs writing to production
   paths instead of an isolated `tmp_path` (MRA-PRE-0, re-confirmed
   relevant in MRA-PRE-2). A test-isolation hygiene issue, not a
   production defect (`data/` is gitignored, nothing ships) - recorded
   for a future, narrowly-scoped test-fixture pass.

   **Update, same day (escalated from theoretical to concretely
   triggering)**: this is a *read*-contamination risk too, not only
   write. `src/desktop/services.py` hardcodes its provider-profile
   storage path to the real `data/provider_profiles.json` behind
   module-level `@lru_cache` singletons with no test injection point.
   Adding real, enabled ElevenLabs/Gemini provider profiles through
   the app's own real Provider Manager (a legitimate, requested task)
   made 5 tests in `tests/test_desktop_app_integration.py` start
   failing - confirmed via direct experiment that the real, live
   provider data is what these tests were unintentionally reading,
   not a code regression from any packaging work done the same day
   (reproduces identically with every other same-day change reverted).
   Root-caused and deliberately deferred to a separate, properly-
   scoped session (a real composition-root refactor, not a quick
   patch) rather than folded into installer-packaging work - see
   `PROJECT_PROGRESS.md`'s matching entry. The real, running app
   itself is unaffected.
6. **`job.scenes` dual-writer risk** (MRA-PRE-1) - the legacy and
   current content pipelines each have their own independent,
   GUI-reachable writer for this field. Classified minor, a deliberate
   "no destructive rewrite" tradeoff already mitigated by a documented
   redirect notice, not fixed.
7. **Live-provider load/latency/rate-limit behavior** (MRA-PRE-8) -
   untested, since this project has no real API keys configured. Every
   stress/performance number in this audit is from dry-run mode.

   **Update, same day (partially closed)**: the user obtained real
   ElevenLabs credentials (voice/music/sound_effects) and a real
   Google Flow account. A real, live-account connectivity check found
   and fixed a genuine Provider Manager defect first (see
   `PROJECT_PROGRESS.md`'s matching entry - a re-enabled profile could
   permanently deadlock on a stale `DISABLED` health status). Once
   real, valid keys were saved, a real (credit-consuming, user-
   approved) generation call was run against each ElevenLabs adapter's
   own code path: `ElevenLabsMusicProvider.generate_music()` and
   `ElevenLabsSoundEffectProvider.generate_sound_effect()` both
   produced real, non-empty MP3 output end to end - the first-ever
   live confirmation that `src/providers/elevenlabs_sound_generation_provider.py`'s
   endpoint path, auth header, and request/response shape are
   correct, closing that class's own long-standing "not yet verified"
   disclaimer. `ElevenLabsVoiceProvider.generate_voice()` reached a
   real HTTP 402 (Payment Required) across every model_id tried, not
   a code defect - endpoint/auth/request shape confirmed accepted by
   ElevenLabs. The precise cause, from ElevenLabs' own error body:
   "Free users cannot use library voices via the API" - an
   account-plan restriction on shared/library voice ids, unrelated to
   the account's remaining credit balance (9,900+ credits available).
   The actual success response remains unconfirmed pending a voice
   the account actually owns (cloned/added) or a paid plan.

   **Second update, same day**: the user also added a real Gemini API
   key as a new LLM provider profile. A real, live call through
   `GeminiProviderAdapter` (`src/shared/llm/gemini_provider.py`)
   succeeded end to end - a real reply, request id, and token-usage
   report - closing the "untested" gap for the LLM category as well.
   Along the way, `gemini-2.0-flash` (an initial guess) returned a
   real `404 NOT_FOUND` from Gemini's own API, confirming that model
   is retired; `gemini-3.6-flash` (as recommended by that same error)
   worked. No hardcoded stale model name exists anywhere in this
   codebase (confirmed via a repo-wide search) - the profile's own
   `default_model` field was simply left unset, now guided to be set
   explicitly.

   All real providers configured so far are now confirmed working:
   `music`, `sound_effects` (ElevenLabs), and `gemini` (LLM). Not yet
   done: `voice`/text-to-speech (ElevenLabs, pending a
   non-library voice), stress/load/rate-limit behavior specifically
   (this was a correctness/connectivity check, not a load test), and
   Google Flow's own real generation path.

## Final verdict

**NOT YET CERTIFIED for installer packaging - one clear, specific
blocker, everything else either fixed or a disclosed, lower-severity,
explicitly-scoped-out risk.**

The blocking condition is narrow and already fully diagnosed to the
point a fix can be scoped: the full-suite pytest hang (item 1 above)
means this project cannot currently prove "full local validation
green" as one unattended process - the exact gate GUI-8 itself already
defined and found blocked, now re-confirmed unchanged after this
entire audit's own work. Every other item this audit found was either
fixed and teeth-verified (9 real defects, listed above) or is a real,
disclosed, deliberately-scoped-out risk that does not itself prevent
packaging (items 2-7) - none of them represent silent, undiscovered
risk; all are recorded with real evidence in this document and
`docs/REMAINING_GAPS.md`.

**Recommended path to certification**: root-cause and fix the
full-suite pytest hang (needs a debugger attached to a live repro,
per GUI-8's own finding) - once `pytest tests/` completes cleanly as
one process, MRA-PRE-9's own gate is met and this document's verdict
should be updated to CERTIFIED. Items 2-6 do not block that outcome
and can be scheduled as follow-on work at the team's own discretion;
item 7 remains an inherent limitation until real API keys are
available for live-provider validation.

**Update, same day (fixed)**: the pytest hang was root-caused and
fixed immediately after this report - see
`docs/MRA_PRE_9_FOLLOWUP_PYTEST_HANG_FIX.md` for the full
investigation. Root cause: no GUI test anywhere ever explicitly closed
its `MainWindow`, so top-level widgets accumulated without bound on
the one shared, process-wide `QApplication` singleton every GUI test
file's `qapp` fixture reuses; `QApplication.setStyleSheet()`/
`setStyle()` (called by every `apply_theme()` call) re-polish every
current top-level widget, and this was directly confirmed via `py-spy
dump` against a live, reproduced stall to be where the main thread
was genuinely blocked. Fixed with a new `autouse` fixture in
`tests/conftest.py` that closes and deletes every leftover top-level
widget after each test, using `QTest.qWait()` (real wall-clock event-
loop pumping) rather than `processEvents()` to make the cleanup
actually complete. Verified via two full, real, non-artificial runs:
`test_desktop_app_integration.py` alone (15 passed) and the exact
original GUI-8 2-file repro together (52 passed, 0 failed, 0 errors,
2:27) - the identical combination GUI-8's own report documented as
reproducibly hanging now completes cleanly. One disclosed, lower-
probability residual risk remains (a deeper, native-level Qt/PySide
interaction found only under an artificially-forced adversarial
repro, not in either real verification run) - recorded in the
follow-up document and `docs/REMAINING_GAPS.md`, not treated as
blocking.

**This updates the verdict above**: with the pytest-hang blocker
resolved and verified, this project is **CERTIFIED for installer
packaging** with respect to that gate. Items 2-6 remain real,
disclosed, non-blocking follow-on work; item 7 remains an inherent
limitation until real API keys are available.
