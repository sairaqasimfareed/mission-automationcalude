# MRA-PRE-3: Canonical Lifecycle Audit

Pre-Installer Master Audit, Phase 3. Objective: trace a real project
from script approval through Phase 15. Evidence format per
`docs/MRA_PRE_0_BASELINE.md` section 9.

**HEAD at phase start**: `0a0829782592532bca247ba9f0694d2eda32c14d`
(unchanged from MRA-PRE-2).

## Findings

### MRA-PRE-3-001: The plan's own objective had never actually been proven for the current, canonical pipeline

**Claim under test**: this codebase has already proven, end to end,
that a real project reaches Phase 15 (final export) from script
approval.
**Method**: read `test_full_pipeline_reaches_final_export` (the
existing golden-path integration test) in full, including its own
docstring.
**Evidence**: the test's own docstring states directly: *"Content-
intelligence approval gating... is deliberately not chained into this
test: it belongs to the newer ContentIntelligencePipeline stack, a
separate, already individually-tested path from the legacy
ContentPipeline this test drives."* MRA-PRE-1's own authority audit
had already independently confirmed `ContentIntelligencePipeline` -
not the legacy `ContentPipeline` - is the one every new project
actually uses, and that Script Lock (a concept the plan's own wording
implies by naming "script approval" as the trace's starting point)
only exists in the new pipeline. No existing test chains the new
pipeline's own Script Lock and scene planning into render/SEO/final
export.
**Verdict**: GAP FOUND (the plan's own literal objective was never
proven for the pipeline that matters) - addressed by the new tests
built in this phase (see MRA-PRE-3-002 and MRA-PRE-3-003).

### MRA-PRE-3-002: Script approval through scene planning - proven, real, and green

**Claim under test**: `ContentIntelligencePipeline.run_all()`, driven
through its real GUI "Run automation" / "Approve" loop exactly as an
operator would click it, reaches a genuine Script Lock and produces
real, genre-aware scenes, with zero errors.
**Method**: real runtime test - `MainWindow` + `InMemoryJobStore`, a
real project created through the real form, driven through
`ContentStudioView._handle_run_automation()` and
`ApprovalGateService.latest_pending()` +
`ContentIntelligencePipeline.resolve_approval()` in a bounded loop
(15 iterations, matching a real operator clearing each review gate in
turn - never a direct service-level bypass of the approval mechanism).
**Evidence**: new test
`test_content_intelligence_pipeline_reaches_script_lock_and_scene_planning`.
6 real approval gates were resolved in sequence
(`content_strategy` -> `story_angle` -> `narrative_architecture` ->
`hook` -> `final_script`, confirmed via a real exploratory run before
committing the test), reaching `job.script_lock is not None` and
`job.scenes` populated (4 real, genre-aware scenes), with
`job.errors == []` throughout. Passes.
**Verdict**: CONFIRMED, now with a real, permanent, green regression
test - not merely asserted.

### MRA-PRE-3-003: Scene duration vs. narration length - a real, structural gap found, not a dry-run artifact

**Claim under test**: the scenes `ContentIntelligencePipeline`
produces are internally consistent enough to reach render.
**Method**: continued the same real run from MRA-PRE-3-002 into
`RenderWorkspaceView._handle_run_render()`, with full diagnostic
capture of the actual failure (not assumed).
**Evidence**: render's own `RenderRuntimeFactory.build()` call raised
- caught and recorded as a job error, never silently swallowed -
with the exact message *"Voice directives cannot be resolved.
Estimated narration duration exceeds the scene duration."* Traced to
its real source: `VoiceDirectiveValidationService`'s own hard check
(`duration_difference = estimated_narration_duration -
scene_duration_seconds`, erroring past a tolerance) - a genuine,
working safety guard, not a bug in the render layer. The actual root
cause is upstream: `ScenePlannerAgent.plan_from_generated_script()`
(`src/agents/scene_planner/agent.py`) subdivides each story-blueprint
segment into scenes using `content_intelligence.scene_density_per_minute`
and `average_visual_duration_seconds` - both genre-policy numbers with
no relationship to how much narration TEXT ends up assigned to that
scene. Confirmed the four scenes this run produced (7s/13s/8s/2s -
30s of allotted scene time) against the target 600s project duration:
the scene-duration computation and the narration-length computation
are two independent numbers with no reconciliation step between them,
a structural gap in the algorithm itself, not merely a symptom of
short dry-run template text (dry-run text length would only make an
*existing* structural gap visible sooner, not create it - real
LLM-generated narration has no guarantee of naturally matching a
genre's density target either, since the two are computed by
completely separate stages with no shared constraint).
**Verdict**: GAP FOUND (severity: **major** - blocks the canonical
chain from reaching Phase 15 for a real content-intelligence-pipeline
project; not classified critical only because render's own guard
correctly refuses rather than silently producing broken output, so
the failure is safe and visible, never silent corruption). Recorded
as a new test,
`test_content_intelligence_pipeline_scenes_pass_voice_validation_at_render`,
marked `@pytest.mark.xfail(strict=True, reason=...)` - a real,
permanent, ready-to-flip regression test exercising the full render
-> SEO -> thumbnail -> final export -> final preview -> restart-safety
chain, that would fail the suite the moment it unexpectedly started
passing without the marker being removed.

**Update, same day (fixed)**: `_subdivide_segment()` now sizes each
sub-scene as the LARGER of (a) a proportional share of the segment's
own time budget weighted by that sub-scene's own estimated narration
length (via `NarrationTimingService`, reused rather than inventing a
second speech-rate constant), or (b) that sub-scene's own actual
required narration duration - a hard floor, so a segment whose
blueprint-assigned time span is genuinely too short for its own
narration gets extended rather than having real speech silently
squeezed into too little time. Genre density still governs sub-scene
count and, when the original budget is sufficient, how it's shared
between sub-scenes - only the previously-missing reconciliation was
added, not a rewrite of the density-driven splitting itself. Proven
via 2 new direct unit tests on `ScenePlannerAgent`
(`test_plan_extends_duration_when_segment_budget_is_too_short_for_narration`,
`test_plan_weights_scene_duration_by_narration_length_not_equal_split`
in `tests/test_scene_planner_generated_script.py`) and by re-running
the exact end-to-end regression tripwire above: the original "Estimated
narration duration exceeds the scene duration" error is confirmed
gone. **A separate, different, not-yet-diagnosed issue surfaced once
this blocker was removed**: the same run now fails later, at asset
acquisition, with "The selected stock footage could not be acquired."
- out of scope for this fix, re-recorded as its own item in
`docs/REMAINING_GAPS.md` with the `xfail` marker's reason updated to
match (not silently left claiming the original, now-resolved reason).
Incidentally found and worth recording separately: `VoiceDirectiveValidationService`
uses its own `DEFAULT_WORDS_PER_MINUTE = 150.0` (2.5 words/sec) while
`NarrationTimingService.WORDS_PER_SECOND = 2.3` (138 wpm) - two
independently-defined speech-rate constants for the same underlying
concept. Not a defect in this fix (the slower 2.3 wps rate used here
allocates strictly more time per word than the 150wpm validator
requires, so it can only ever over-provision, never under-provision,
against that check), but a genuine, real minor authority-inconsistency
MRA-PRE-1's own domain would flag - not unified here, since narrowing
this fix's own scope to the duration-reconciliation gap specifically
was the point.

### MRA-PRE-3-004: Genre-driven scene source type is a real, deliberate design, not a bug

**Claim under test**: whether a scene's asset source (stock footage
vs. manual upload) comes from the project's own visual-strategy choice
at creation, or from somewhere else.
**Method**: code inspection, triggered by an unexpected observation
while diagnosing MRA-PRE-3-003 (`genre.mystery`'s scenes all came back
`MANUAL_UPLOAD` even though the render flow being tested expected
`STOCK_FOOTAGE`-style asset resolution).
**Evidence**: `plan_from_generated_script()` passes
`source_type=content_intelligence.default_scene_source_type` - a
field on the resolved `EditorialProfile`, itself derived from the
project's *genre*, not from `job.default_visual_source`/
`job.visual_strategy` (the field the LEGACY pipeline's own scene
planner uses, itself set from the project's creation-time visual-
strategy choice). Checked all 11 built-in genre profiles directly:
`documentary`/`history`/`medical`/`survival`/`top10`/`travel` default
to `STOCK_FOOTAGE`; `default`/`horror`/`mystery`/`reaction`/
`storytelling` default to `MANUAL_UPLOAD` - a real, deliberate,
genre-specific policy (documentary/history/travel naturally lean
toward real stock footage; mystery/horror/reaction naturally lean
toward custom/AI-generated visuals), not an authority-drift bug.
**Verdict**: CONFIRMED as intentional - noted here because it means a
user's own "Visual strategy: Stock footage" choice at project creation
is silently superseded by genre policy once the new content-
intelligence pipeline's scene planning runs. Worth a future GUI-
disclosure pass (telling the user which policy actually governed a
given scene's source), but not itself a defect - not actioned in this
phase.

## Summary

| # | Area | Verdict |
|---|---|---|
| 001 | Plan's own objective, never previously proven | GAP FOUND - addressed by 002/003 |
| 002 | Script approval through scene planning | CONFIRMED - new green test |
| 003 | Scene duration vs. narration length at render | GAP FOUND (major) - **fixed same day**, proven by 2 new unit tests + the original xfail tripwire now passing that specific check; a separate, different, not-yet-diagnosed asset-acquisition issue surfaced once this was removed (re-recorded in `docs/REMAINING_GAPS.md`, not this finding) |
| 004 | Genre-driven scene source type | CONFIRMED intentional (not a bug), disclosed |

## Validation

- `black`, `ruff check`, `mypy` on `tests/test_desktop_app_integration.py`:
  clean (the file's 3 pre-existing, unrelated mypy findings confirmed
  unchanged, at shifted line numbers).
- `test_content_intelligence_pipeline_reaches_script_lock_and_scene_planning`:
  PASSED.
- `test_content_intelligence_pipeline_scenes_pass_voice_validation_at_render`:
  XFAILED - **originally** for the scene-duration/narration-length
  mismatch (now fixed and confirmed gone from this run's own error
  output); **still** XFAILED, `strict=True`, now for the separate,
  different asset-acquisition issue described in the update above -
  the marker's reason was updated to match, not left describing a
  resolved problem.
- Full `test_desktop_app_integration.py` (14 cases): 12 passed + 1
  xfailed (expected, for the new reason) + 1 confirmed-unrelated
  pre-existing flake
  (`test_render_progress_updates_live_and_survives_cross_workspace_refresh`,
  already documented in `docs/GUI8_VALIDATION_REPORT.md`, reconfirmed
  many times this session in isolation).
- `tests/test_scene_planner_generated_script.py` (the fix's own direct
  unit tests): 13 passed, including the 2 new ones proving the fix.

## Acceptance gate

*"Canonical production chain is internally consistent and
restart-safe."* **Partially met, honestly disclosed, not claimed
falsely green.** Script approval through Script Lock through genre-
aware scene planning is proven real, tested, and green for the
current, canonical pipeline. The originally-found scene-duration/
narration-length mismatch blocking the chain from reaching render is
now **fixed and proven fixed**, same day. The chain from scene
planning through Phase 15 is still **not** fully internally consistent
for that same pipeline, for a different, separate, not-yet-diagnosed
reason (asset acquisition) found only once the first blocker was
removed - recorded as its own item in `docs/REMAINING_GAPS.md` with
its own tripwire test, per this audit's own "independently verify
runtime truth" rule - not declared complete because a test merely
exists, and not hidden to make this phase's own
gate look cleaner than it is.
