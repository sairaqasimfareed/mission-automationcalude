# MRA-PRE-4: Genre/Audience/Brand Anti-Drift Audit

Pre-Installer Master Audit, Phase 4. Objective: confirm genre,
audience, and brand identity stay consistent across a project's
lifecycle rather than merely having a single writer (MRA-PRE-1's own
scope) - drift can happen even with a single writer if a downstream
consumer reads a live, mutable field instead of the value that was
actually in effect when the artifact it's describing was produced.
Every finding below follows the evidence format defined in
`docs/MRA_PRE_0_BASELINE.md` section 9 (claim under test / method /
evidence / verdict / HEAD).

**Note on source material**: this phase's exact PDF wording could not
be re-quoted verbatim in this segment (the source document was not
available to re-read at this point in the session). This phase is
executed against the working title and scope already recorded in
`docs/IMPLEMENTATION_STATE.md` from when the plan was originally
reviewed ("Genre/audience/brand anti-drift audit"), using this audit's
own established evidence-based methodology rather than a guessed
acceptance criterion presented as a quote.

**HEAD at phase start**: `f91189ff23765a1ee800fbd6fd00fa6a8f97c6dd`.

## Findings

### MRA-PRE-4-001: Genre identity can silently drift after Script Lock

**Claim under test**: once a script is locked, every artifact
generated from it (SEO package, thumbnail) consistently reflects the
genre the script was actually written in.
**Method**: code inspection, starting from `ScriptLock`'s own
docstring (*"topic, angle, target duration, genre/profile
references"* among what a lock must persist) - checked whether
anything actually reads `ScriptLock.genre_id` (`grep -rn
"script_lock\.genre_id" src/`), then checked whether `job.genre_id`
(the live field) has any guard preventing a change after
`job.script_lock is not None`.
**Evidence**: `ScriptLock.genre_id` had **zero readers anywhere in the
codebase** - `ScriptLockService.build_lock()` populates it correctly
at lock time (`genre_id=job.genre_id`), but nothing downstream ever
consulted the snapshot. Meanwhile `ContentStudioView._handle_save_
settings()` (Content Studio's "Project settings" card) writes
`job.genre_id = new_genre_id` with no check against `job.script_lock`
at all - a project's genre can be changed freely after the script is
already frozen. `PackagingView._handle_generate_seo()` and
`_handle_generate_thumbnail()` both called `SEOContextBuilder().build(
job, genre_id=job.genre_id, ...)` - the LIVE field - so a script
locked in `genre.documentary` whose genre was later changed to
`genre.horror` would get an SEO package and thumbnail generated using
`genre.horror`'s tone/style guidance, describing content that was
actually written in `genre.documentary`'s voice. Confirmed via a real,
teeth-verified test that reproduces exactly this sequence.
**Verdict**: GAP FOUND (severity: **moderate** - narrower blast radius
than MRA-PRE-1's genre finding since it only affects a project whose
genre is changed after locking, a less common but real operator
action with no warning against it) - **fixed same day**. Added
`_resolved_genre_id(job)` in `packaging_view.py`: prefers
`job.script_lock.genre_id` once a lock exists (the actual genre the
locked script was written in), falling back to the live `job.genre_id`
for an unlocked project or a lock built before this field existed
(honestly absent, matching every other optional-snapshot field's
convention in this codebase). Both SEO and thumbnail generation call
sites updated. Proven via a new test,
`test_generate_seo_uses_the_locked_genre_not_a_later_changed_one`,
verified to genuinely fail without the fix (asserts `genre.horror`
when the fix is reverted) and pass with it.

### MRA-PRE-4-002: Audience identity - no equivalent drift risk found

**Claim under test**: whether `job.audience_promise.target_audience`
(consumed the same way genre_id is, by the same `SEOContextBuilder`)
has the same post-lock drift exposure as genre_id.
**Method**: code inspection - checked whether anything in the desktop
GUI lets a person directly edit `job.audience_promise` after it's set,
and whether `ContentIntelligencePipeline.run_all()` could regenerate
it on a later re-entry.
**Evidence**: MRA-PRE-1 already confirmed `audience_promise` has
exactly one writer and `job.target_audience` (the project-creation-time
field, distinct from the promise) is immutable post-creation - no
Settings-card equivalent exists for editing the promise directly.
`run_all()`'s own re-entry guard (`if job.audience_promise is None:
job = self.run_audience_promise(job)`) means a second `run_all()` call
on an already-promised job is a structural no-op for this field, not
just a convention - confirmed directly in code, not merely inferred
from a docstring.
**Verdict**: CONFIRMED - no drift path exists for audience identity;
genre_id's exposure comes specifically from Content Studio's own
free-editing Settings card, which has no audience-promise equivalent.

### MRA-PRE-4-003: Brand - reconfirmed still not present in this codebase

**Claim under test**: whether a "Brand" feature has been added to this
repository since MRA-PRE-1's own check (Sep 8, same day, earlier
phase).
**Method**: re-ran the identical check - `grep -rln "class.*Brand"
src/` and a direct string search for any `"Brand"` reference in
`src/models/`/`src/services/`.
**Evidence**: zero matches, identical to MRA-PRE-1's result. Worth
noting: `Mission_Automation_Brand_Advertising_Phase_Implementation_
Plan.pdf` exists as a local planning document (dated before this
audit's Phase 0 freeze), but nothing from it has been implemented in
this repository - consistent with "do all work in those repos, none
other than these" never having included that plan as an active task
this session.
**Verdict**: CONFIRMED N/A (re-confirmed, not merely carried forward
from MRA-PRE-1).

### MRA-PRE-4-004: Incidental finding - a stale claim in `docs/REMAINING_GAPS.md`

**Claim under test**: none directly in this phase's scope - found
while reading `ContentIntelligencePipeline.run_all()` for finding 002
above.
**Method**: `docs/REMAINING_GAPS.md`'s Phase 1 section stated
`run_all()` "always restarts from stage one rather than resuming
where it left off," deferring idempotency as a separate, unfixed
concern. Direct inspection of the current method shows every stage
guarded (`if job.<artifact> is None: job = self.run_<stage>(job)`),
including a Phase-19-era comment on the Script Lock step stating the
intent explicitly: *"Guarded on job.script_lock is None so a second
run_all() call on an already-locked job stays a true no-op, matching
this method's own idempotency guarantee."*
**Evidence**: the code was evidently fixed at some later point in this
project's long history without this specific note being updated -
this doc's own "no fabricated/stale claims" discipline means a
demonstrably false claim should be corrected on discovery, not left
standing because it's outside the current phase's primary scope.
**Verdict**: RISK (documentation-only, no code defect) - corrected in
`docs/REMAINING_GAPS.md` with the real evidence cited; no code change
made, since none was needed.

## Summary

| # | Area | Verdict |
|---|---|---|
| 001 | Genre identity drift after Script Lock | GAP FOUND (moderate) - **fixed same day**, teeth-verified test |
| 002 | Audience identity drift | CONFIRMED - no drift path exists |
| 003 | Brand | CONFIRMED N/A (reconfirmed) |
| 004 | Stale `run_all()` idempotency claim in `REMAINING_GAPS.md` | RISK (docs-only) - corrected |

## Validation

- `black`, `ruff check`, `mypy` on `packaging_view.py` and
  `tests/test_packaging_view_gui.py`: clean.
- `test_generate_seo_uses_the_locked_genre_not_a_later_changed_one`:
  PASSED - verified to genuinely FAIL without the fix (reverted the
  call sites to `genre_id=job.genre_id`, confirmed the test caught
  `genre.horror` instead of the expected `genre.documentary`), then
  restored and re-confirmed green, with `git diff --stat` showing only
  the intended change remained.
- Full `tests/test_packaging_view_gui.py` (23 cases, including the new
  one): all passed.

## Acceptance gate

Genre, audience, and brand identity are now confirmed consistent
across the pipeline's lifecycle for the current, canonical pipeline: a
real, evidenced drift path was found and fixed (genre after Script
Lock), a parallel risk was checked and found not to exist (audience),
and Brand's absence was reconfirmed rather than assumed carried
forward. One documentation-only staleness finding was corrected as an
incidental discovery. Met.
