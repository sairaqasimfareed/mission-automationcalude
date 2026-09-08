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
gone. **A separate, different issue surfaced once this blocker was
removed**: the same run then failed later, at asset acquisition, with
"The selected stock footage could not be acquired." Root cause: a
content-intelligence-pipeline scene's stock-candidate title is built
from the scene's full `visual_prompt` text (150-200+ characters), and
`StockAssetStorageService._sanitize_filename()` never bounded length -
combined with the project/scene path prefix this could exceed
Windows' `MAX_PATH` (260 characters), making `shutil.move()` raise a
real `OSError` (confirmed reproduction: a 194-character title produced
a 278-character destination path). **Fixed, same day**: added
`_MAX_SANITIZED_LENGTH = 80` to `_sanitize_filename()` in both
`stock_asset_storage_service.py` and the identical latent pattern in
`asset_storage_service.py` (manual uploads). Proven via a new,
teeth-verified test,
`test_a_long_title_still_produces_a_path_within_windows_max_path`.

**A third, separate issue then surfaced once THAT blocker was
removed**: the same run progressed through render successfully but
then `PackagingView._handle_generate_seo()` produced no SEO package.
Root cause: `SEOContextBuilder.build()` (shared by SEO and thumbnail
generation) only ever checked the legacy `job.script` field -
`ContentIntelligencePipeline` never populates it, only
`job.generated_script`/`job.script_lock` - so it always raised
`ValueError`, silently caught and recorded to `job.errors` rather than
crashing. Worse: `PackagingView`'s own "Generate SEO package"/
"Generate thumbnail" buttons were gated on the same legacy field, so
the entire Packaging workspace was a dead end - not reachable through
the real GUI at all - for every project the current, canonical
pipeline produces. **Fixed, same day**: `SEOContextBuilder.build()`
now accepts either provenance (legacy approved `job.script`, or
`job.generated_script` + `job.script_lock` as that pipeline's own
"approved and frozen" equivalent), and `PackagingView`'s gate was
factored into a shared `_script_is_approved()` helper applying the
same reconciliation. Proven via 2 new tests in
`tests/test_seo_context_builder.py` and by the full end-to-end
regression tripwire now reaching SEO, thumbnail, and final export with
zero errors - see MRA-PRE-3-005 below.

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

### MRA-PRE-3-005: SEO/thumbnail generation unreachable for a ContentIntelligencePipeline project

**Claim under test**: once render succeeds, the same project can reach
SEO package generation, thumbnail generation, and final export through
the real GUI.
**Method**: continued the same real run from MRA-PRE-3-003 (post-fix)
into `PackagingView._handle_generate_seo()`, with full diagnostic
capture of the actual result (not assumed).
**Evidence**: `window._job_store.get_seo_package(job.id)` returned
`None` after the call - no exception surfaced to the test, because
`PackagingView._handle_generate_seo()` catches `ValueError`/
`RuntimeError` and records it to `job.errors` rather than raising.
Traced to the real source: `SEOContextBuilder.build()` (shared by both
SEO and thumbnail generation) unconditionally required `job.script is
not None`, a field `ContentIntelligencePipeline` never populates (it
only ever writes `job.generated_script` + `job.script_lock`) - so the
build always raised `ValueError("SEO context requires a VideoJob with
a script.")`. A second, more severe instance of the same defect:
`PackagingView`'s own `script_approved` gate for both the SEO card and
the thumbnail card checked the identical legacy field directly, so
both "Generate" buttons stayed permanently hidden behind "Requires an
approved script." for this pipeline - not merely an SEO data gap but a
whole-workspace dead end, unreachable through the real GUI at all, for
every project the pipeline real projects actually use produces.
**Verdict**: GAP FOUND (severity: **major** - same authority-drift
shape MRA-PRE-1 already found in the genre/editorial-profile-snapshot
finding, here blocking an entire workspace rather than one field) -
**fixed same day**. `SEOContextBuilder.build()` now accepts either
provenance: legacy approved `job.script`, or `job.generated_script` +
`job.script_lock` (Script Lock is that pipeline's own hard "approved
and frozen" boundary - the direct structural equivalent of
`ScriptStatus.APPROVED` on the legacy field), deriving
`script_title`/`script_content`/`estimated_duration_seconds` from
`job.topic`/`GeneratedScript.full_narration`/
`target_duration_seconds` respectively. `PackagingView`'s duplicated
gate was factored into one shared `_script_is_approved()` helper
applying the same reconciliation. Proven via 2 new tests in
`tests/test_seo_context_builder.py`
(`test_build_returns_seo_context_for_a_content_intelligence_pipeline_job`,
`test_build_raises_for_an_unlocked_content_intelligence_pipeline_script`),
each verified to genuinely fail without the fix (teeth-checked via a
temporary revert-and-restore), and by re-running the full end-to-end
regression tripwire: it now passes completely, with no `xfail` marker
remaining.

## Summary

| # | Area | Verdict |
|---|---|---|
| 001 | Plan's own objective, never previously proven | GAP FOUND - addressed by 002/003/005 |
| 002 | Script approval through scene planning | CONFIRMED - new green test |
| 003 | Scene duration vs. narration length at render | GAP FOUND (major) - **fixed same day**, proven by 2 new unit tests |
| 004 | Genre-driven scene source type | CONFIRMED intentional (not a bug), disclosed |
| 005 | SEO/thumbnail generation unreachable for the current pipeline | GAP FOUND (major) - **fixed same day**, proven by 2 new unit tests |

Three real, distinct blockers were found and fixed while proving the
plan's own "script approval through Phase 15" objective for the
current, canonical pipeline: (1) scene duration never reconciled
against narration length (003); (2) a long stock-candidate title could
exceed Windows' `MAX_PATH` and fail asset acquisition (recorded in
`docs/REMAINING_GAPS.md`, discovered here, not itself a lifecycle-
authority finding so not numbered in this doc); (3) SEO/thumbnail
generation - and the entire Packaging workspace GUI - unreachable for
this pipeline (005). Each was found only because fixing the previous
one let the same real end-to-end run advance far enough to hit the
next one - exactly the layered-discovery process this audit's own
"independently verify runtime truth" rule is meant to produce.

## Validation

- `black`, `ruff check`, `mypy` on every touched file (`seo_context_builder.py`,
  `packaging_view.py`, `scene_planner/agent.py`,
  `stock_asset_storage_service.py`, `asset_storage_service.py`,
  `tests/test_desktop_app_integration.py`,
  `tests/test_seo_context_builder.py`,
  `tests/test_scene_planner_generated_script.py`,
  `tests/test_stock_asset_storage_service.py`): clean (the integration
  test file's 3 pre-existing, unrelated mypy findings confirmed
  unchanged, at shifted line numbers).
- `test_content_intelligence_pipeline_reaches_script_lock_and_scene_planning`:
  PASSED.
- `test_content_intelligence_pipeline_scenes_pass_voice_validation_at_render`:
  **PASSED, in full** - render, asset-decision resolution, SEO
  generation, thumbnail generation, final export, quality-center
  policy check, final-preview approval, and a genuinely fresh
  restart-safety reload all confirmed. No `xfail` marker remains -
  this is a real, permanent, green regression test, not a documented
  gap.
- `tests/test_seo_context_builder.py` (12 cases, including the 2 new
  ones proving finding 005's fix): all passed.
- `tests/test_scene_planner_generated_script.py` (14 cases, including
  the 2 proving finding 003's fix): all passed.
- `tests/test_stock_asset_storage_service.py` (the one pytest-
  discoverable test, proving the MAX_PATH fix): passed.
- Full `test_desktop_app_integration.py`: re-run after all three fixes
  landed together to confirm no regressions (see this file's own
  commit for the final count).

## Acceptance gate

*"Canonical production chain is internally consistent and
restart-safe."* **Met, for the current, canonical pipeline - proven,
not merely asserted.** Script approval through Script Lock through
genre-aware scene planning through render through asset resolution
through SEO/thumbnail generation through final export through quality-
center policy check through final-preview approval through a genuinely
fresh restart-safety reload is now a single, real, green, permanent
regression test with zero `xfail` markers. Three real, distinct
blockers were found and fixed in the course of reaching this state
(003, the stock-acquisition MAX_PATH issue, 005) - each is documented
above and in `docs/REMAINING_GAPS.md` with its own evidence, proof, and
teeth-verified test, per this audit's own "independently verify
runtime truth" rule. Not hidden, not rushed past, and not declared done
before the runtime proof existed.
