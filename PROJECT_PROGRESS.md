# Project Progress

Dated log, newest entry first. See `docs/IMPLEMENTATION_STATE.md` for
current capability status and `docs/REMAINING_GAPS.md` for what's next.

---

## 2026-08-28 - Content Studio Redesign: Phase 9 Story Development (Architecture, Evidence Allocation and Retention)

**Backend.** `StoryBeat` gained `evidence_fact_ids` - "Evidence
Allocation," one of this phase's five named deliverables - which
Phase 8 `ResearchFact` entries a beat draws on, populated by the LLM
only when research with `structured_facts` is actually supplied
(never fabricated). `curiosity_loop_question` - "curiosity/reveal
role" from the beat schema - is bound deterministically instead: a
new `ContentIntelligencePipeline._bind_curiosity_roles()` matches each
tracked `CuriosityLoop`'s normalized `opened_at_position` against
whichever beat's real-seconds time range contains that point, with no
LLM call at all, since both the reveal map's positions and the
blueprint's timings are already-committed facts by the time this runs
- there's nothing left for an LLM to judge. `StoryBlueprint` gained
`research_id` - "Architecture references approved Research version" -
a direct pointer to the `ResearchResult.id` a blueprint was built
from, since Phase 1's artifact-lifecycle ledger remains unwired into
any real stage (true of every phase so far, not new to this one).

`StoryBlueprintGenerationService.generate()` gained two optional
parameters: `research` (when supplied with facts, the prompt lists
them and asks for a per-beat `EVIDENCE_FACT_IDS` line, reusing
`FactCheckService`'s own index-based source-matching trick rather than
inventing a new one; omitting `research` entirely reproduces this
service's exact prior behavior, proven by a dedicated regression test)
and `additional_instructions` (free-text guidance appended to the
prompt - this phase's own example is literally "compress the slow
middle section," so that's the example a new test checks for
verbatim). `ContentIntelligencePipeline.run_narrative_architecture()`
now threads `job.research` through to the generator and gained its own
`additional_instructions` passthrough - and is proven, via a dedicated
test that regenerates twice (once plain, once with instructions), to
never mutate `job.research`'s object identity, directly satisfying
"Architecture-only regeneration must not mutate Research."

`ReviewerService` gained one more additive `ArtifactType.
STORY_ARCHITECTURE` focus-guidance entry - pacing, evidence use,
premature reveals, weak escalation, missing payoffs, duration
mismatch, and redundancy - via the exact same dict-lookup mechanism
Phase 8 introduced for research, extended without touching any other
artifact type's prompt.

**What already existed and needed no changes**, confirmed by directly
inspecting the code rather than assumed: `RetentionAuditReport`/
`RetentionAuditService` (this phase's "Retention Plan" deliverable -
already a rule-based audit of reveal spacing and tension variation)
and `InformationRevealMap`/`CuriosityLoop`/`InformationReveal` (the
"Curiosity & Reveal Plan" deliverable - already tracks open/
partial-answer/resolved states and payoff positions) both predate this
session's Phase 9 work entirely and already satisfy their named
deliverables as-is.

**GUI.** The "Narrative architecture" panel now shows, per beat, how
many facts it cites and which curiosity question it advances (when
either is set), plus the blueprint's grounding research id when
present. A new "AI instruction" text input and "Regenerate with
instructions" button sit below the beat list - implemented as a
dedicated handler outside the generic `_handle_run_ci_stage` dispatch,
since that dispatch has no mechanism for passing stage-specific
keyword arguments through to a specific stage's runner.

**Deliberately not built this pass**, documented rather than silently
skipped: no timeline-aware drag-based beat editing - a real custom
timeline widget is a materially larger UI engineering effort than
every other addition in this phase combined, and was scoped out
rather than attempted partially; no direct field-by-field editing of
individual beat properties (the same pre-existing, repo-wide gap
already noted in Phase 4 and Phase 6 - no CI stage panel supports
inline editing yet); "Single Review Story Architecture action" needed
zero new work - the existing generic per-stage "Review" button has
targeted this stage's `story_blueprint` via `_CI_STAGE_REVIEW_TARGET`
since Phase 4, so this exit criterion was already met before this
phase began.

Quality gates: mypy clean across 365 source files, ruff clean, black
clean repo-wide (680 files). New/updated tests: `test_story_blueprint_
model.py` (+6), `test_story_blueprint_generation_service.py` (+5), 2
new cases in `test_content_intelligence_pipeline.py` (curiosity-role
binding including the never-overwrite guarantee, and the
no-research-mutation regression across two regenerations), 1 new case
in `test_reviewer_service.py`, 2 new cases in
`test_content_studio_content_intelligence_gui.py` - 127 tests across
the five touched test files, all passing.

## 2026-08-28 - Content Studio Redesign: Phase 8 Research Execution, Evidence Ledger and Fact Integrity

**Backend.** New `src/models/research_evidence.py`: `EvidenceRecord`
(source_id + confidence + support type + contradiction status) binds
one piece of evidence to the source that backs it; `ResearchFact`
wraps `text` + a list of `EvidenceRecord`s, using one stable `id`
(inherited from `MissionBaseModel`) as both "Claim ID" and "Fact ID" -
a deliberate simplification over the spec's two-ID wording, since this
codebase has no existing two-stage claim-then-fact promotion concept
to build on and inventing one would be materially more machinery than
the actual requirement (a stable identifier downstream Story
Development can reference) needs; `ManualResearchEdit.is_verified`
only ever becomes `True` via an explicit fact-check pass, never
automatically on creation or edit - "Manual research edits do not
automatically become verified facts."

`ResearchSource` gained `date`, `retrieved_at`, and a new
`SourceStatus` (ACCEPTED/REJECTED) - rejecting a source flips its
status rather than removing it from the list, so "User can add/reject
sources without deleting audit history" falls out of the model for
free, no separate rejected-sources list needed. `ResearchResult`
gained `structured_facts`, `research_gaps`, `manual_edits` - all
additive alongside the existing flat `key_facts: list[str]`, which 6
production services (`ScriptAgent`, `ResearchReviewService`,
`ScriptGenerationService`, SEO context/keyword generation,
`StoryAngleGenerationService`) keep reading completely unmodified -
the exact same "add a parallel structured field, never touch the
broadly-consumed flat one" pattern Phase 7 already established for
`ResearchPlan.research_questions`.

New `FactCheckService` (`src/services/fact_check_service.py`) mirrors
every other content service's batched-call/labeled-block pattern.
Deliberately checks a claim against a project's *already-gathered,
accepted* sources only - never performs new retrieval - matching
"Research retrieval/search and LLM analysis/synthesis are separate
layers." Rejected sources are excluded from what the LLM sees, so a
rejected source can't silently keep backing a claim. "LLM is forbidden
from treating pretrained memory as evidence" is enforced via an
explicit system-prompt instruction - documented honestly here as a
prompt-level safeguard, not a technically-enforced guarantee, since
this is an LLM-based system without a real retrieval-grounding
infrastructure layer that could verify the model actually complied.

`ReviewerService` gained one additive dict entry mapping
`ArtifactType.RESEARCH` to extra focus guidance injected into the
existing generic review prompt - "Reviewer findings highlight
unsupported claims, weak sources, contradictions, unanswered
questions and missing perspectives" - reusing the exact same
mechanism every other artifact type already uses rather than building
a second, bespoke research critic. Zero risk to any other artifact
type's review prompt, proven by a test asserting the guidance text is
absent when reviewing a script.

**GUI.** The "Research" CI stage panel gained an Evidence Ledger
section beneath the existing summary display: sources shown with an
accepted/rejected status badge and a Reject/Restore toggle, plus an
"Add source" form; evidence-bound facts shown read-only (support type,
confidence, contradiction status per evidence record); manual research
notes with a verified/unverified badge, an "Add note" form, and a
"Fact Check Again" button on every unverified note that calls
`FactCheckService` and either promotes the note to a verified
`ResearchFact` (on a supported result) or records the reviewer's
reasoning as `verification_notes` (on an unsupported one, leaving the
note unverified); and a research-gaps Add/Remove list mirroring Phase
7's question-editing pattern.

**Deliberately not built this pass**, documented rather than silently
skipped: no separate multi-tab shell - Evidence/Facts/Gaps live as
sections within the existing single "Research" panel, the same
honest-scoping call Phase 7 made for the Research Brief; no GUI-side
direct authoring of `EvidenceRecord`/`ResearchFact` - facts are only
ever created through "Fact Check Again," never hand-entered, so a fact
in the ledger always has a real (even if unsupported) fact-check
behind it; "Regenerate Section" and "Edit Research" (in-place rewrites
of `research_summary` itself) are out of scope this pass - only
additive Evidence Ledger actions exist.

Quality gates: mypy clean across 365 source files, ruff clean, black
clean repo-wide (680 files). `tests/test_research_model.py` was
rewritten from a dead print-script (the session's 7th such fix) into
11 real tests covering both the pre-existing fields and the new Phase
8 additions. New/updated tests: `test_research_model.py` (11),
`test_fact_check_service.py` (10 new), 2 new cases in
`test_reviewer_service.py` (research-focus guidance present for
RESEARCH, absent for SCRIPT), 7 new cases in
`test_content_studio_content_intelligence_gui.py` (add/reject source,
manual-edit add, fact-check-again both supported and unsupported
paths, research-gap add/remove).

## 2026-08-28 - Content Studio Redesign: Phase 7 Research Center (Research Brief and Retrieval Foundation)

**Backend.** New `ResearchQuestion` (`src/models/research_plan.py`)
gives each research question a stable identity - `id` is inherited
from `MissionBaseModel` and never changes across an edit, only across
a removal, exactly what the spec's "Research questions have stable
IDs" asks for. `ResearchPlan` gained `structured_questions` (the new
stable-ID list the GUI edits), `research_policy_override:
ResearchPolicy | None` (a per-brief override of the genre's default),
and `user_constraints` - all additive; the existing flat
`research_questions: list[str]` field is untouched and every existing
caller/test that reads it keeps working unmodified.
`ResearchPolicy` (`src/models/genre_profile.py`, already existed as a
genre-level rigor policy - depth/minimum sources/primary-source
requirement/etc.) gained `preferred_source_types`, `excluded_sources`,
`freshness_requirement`, `geographic_scope` - the brief-level policy
fields the redesign's spec asks for, layered onto the same model
rather than inventing a second "research policy" concept.

New `ApprovalPolicyConfig.research_plan` decision point, defaulting to
AUTO like `topic`/`research`/`hook` (cheap, reversible, no retrieval
has happened yet). `ContentIntelligencePipeline.run_research_plan()`
now gates on this point right after generating the plan;
`run_all()` checks `is_blocked(job, "research_plan")` before calling
`run_research()`. Under AUTO, `confidence=None` resolves immediately
to APPROVED, so this is a complete no-op for every existing AUTO/
full_auto()/review_critical_stages() project - proven by a new test
mirroring the existing `test_run_all_stops_at_the_first_review_gated_
stage`. Setting `research_plan` to REVIEW or MANUAL makes "Approve
Brief & Start Research" a real, required action - this is the redesign's
"No retrieval job starts until brief approval/start action" exit
criterion, genuinely enforced for the automated `run_all()` path.

**GUI.** The "Research plan" panel - previously a bare read-only list
of question strings - gained a Save/Remove button per question, an
"Add question" row, an approval-status badge ("Pending brief approval"
/ "Brief approved"), and an "Approve Brief & Start Research" button
that appears only while the decision is actually pending. The
"Research" panel's Run button is now disabled while the brief's
approval is pending, showing "Waiting on Research Brief approval."
instead. A research plan saved before this phase (empty
`structured_questions`, non-empty `research_questions`) is lazily
backfilled with fresh stable-ID `ResearchQuestion` objects the first
time its panel renders - text and order stay identical, only the IDs
are new.

**Deliberately not built this pass**, documented rather than silently
skipped: `run_research()` itself carries no defensive precondition
requiring an approved (or even present) `research_plan` - the hard
gate lives entirely in `run_all()`'s orchestration and the GUI's
disabled Run button, not inside the method. This was a deliberate
choice, not an oversight: 13 existing unit tests call `run_research()`
directly and standalone, by design, to test it in isolation without
ever setting a research plan first (one of them explicitly resumes a
job straight from `run_audience_promise()` into `run_research()` to
prove restart-safety) - retrofitting a hard requirement into the
method itself would have broken that established, intentional testing
contract for no production benefit, since nothing outside `run_all()`
or the GUI button calls it in practice. Also deferred: the full
multi-tab "Research Center" shell (Brief / Research Document /
Evidence Ledger / Key Facts / Gaps tabs) - Evidence Ledger, Key Facts,
and Gaps are Phase 8's own deliverables and don't exist yet, so
building empty placeholder tabs now would be premature scaffolding
with nothing real to show; "Research plan" and "Research" remain two
panels in the existing `_CI_STAGES` rotation, which already covers
"Brief" and part of "Research Document." No dedicated settings UI yet
for `research_policy_override`/`user_constraints` - backend-only this
pass, tested for persistence rather than exposed for editing.

Quality gates: mypy, ruff, and black all clean across every touched
file (verified zero new mypy errors introduced into the two test files
that already carried 59 pre-existing, unrelated typing issues - fully
diffed against the pre-change baseline to confirm). New/updated tests:
`test_research_plan_model.py` (+7), `test_research_policy.py` (5 new),
`test_research_planning_service.py` (+1), 3 new cases in
`test_content_intelligence_pipeline.py` (auto-approval, REVIEW-mode
blocking, resolving unblocks research), 7 new cases in
`test_content_studio_content_intelligence_gui.py` (add/edit/remove
questions including the last-question-rejected guard, brief
auto-approval, and the Approve Brief button unblocking Research).

## 2026-08-28 - Content Studio Redesign: Phase 6 Audience & Creative Strategy Workspace

**Backend.** `AudiencePromise` extended with 7 new optional fields the
redesign's Audience artifact schema calls for and the existing model
didn't yet have: `persona`, `viewer_intent`, `viewer_promise`,
`tone_treatment`, `platform_strategy`, `audience_pain_or_desire`,
`knowledge_assumption` (target_audience and central_curiosity already
covered "primary audience" and "central curiosity"). All optional,
defaulting to `None` - every existing `AudiencePromise` construction
site across the pipeline and its tests is untouched. New
`CreativeDirection` (`src/models/creative_direction.py`) - a genuinely
new artifact, not a StoryAngle extension: Phase 0's own baseline
classified Creative Direction as "PARTIAL REUSE + MISSING" precisely
because nothing today captures a *combined* framing, an explicit
Narrative Thesis, or production constraints. Wraps
`selected_angle: StoryAngle` so the artifact stays self-contained,
plus an optional `combined_angle_note`, `narrative_thesis`, and
`constraints`. Versioned and approved independently of `AudiencePromise`
even though both are edited in one GUI workspace, per the redesign's
explicit requirement - `CreativeDirection` carries no reference back
to the audience artifact at all. `VideoJob.creative_direction` is new
and optional.

**GUI.** The existing "Story angles" CI stage panel - previously pure
read-only display, like every other CI stage panel - gained real
interactivity: a "Select" button per candidate that overrides the
pipeline's own auto-selected `selected_story_angle` (this was
previously impossible from the GUI at all; `run_story_angles()` always
auto-picks the highest-scoring evaluation), a "Combine with selected"
button that merges the currently selected angle with another candidate
into a `combined_angle_note`, a "Write my own angle" form (style +
title + description), and a "Creative direction" section below all of
that where a narrative thesis and comma-separated constraints can be
entered and saved. The "Audience promise" panel now displays the 7 new
Phase 6 fields inline whenever they're present.

**Deliberately not built this pass**, documented rather than silently
skipped: inline field-by-field editing of `AudiencePromise` itself -
this is a pre-existing, repo-wide gap already flagged in Phase 4's own
entry (no CI stage panel supports inline editing yet, not something
this phase introduces); a distinct "Review Strategy" action separate
from the existing generic per-stage "Review" button (which already
covers `audience_promise`); an incremental "Generate More" for angles
that adds candidates without discarding the existing set (today,
re-running the "Story angles" stage regenerates the whole candidate
set from scratch); and a dedicated `ArtifactLifecycleService`-backed
version/approval trail specifically for Creative Direction - it rides
the same generic `ContentDecisionRecord`/`ApprovalGateService` gate
every other CI stage uses today, since Phase 1's parallel ledger
remains unwired into any real stage (true of every phase so far).

Quality gates: mypy, ruff, and black all clean across the touched
files. New tests: `test_audience_promise_model.py` (+4),
`test_creative_direction.py` (8 new), and 9 new cases in
`test_content_studio_content_intelligence_gui.py` covering Select
(overriding auto-selection), Write My Own (including the blank-title
error path), Combine (including the no-selection no-op), and Save
Creative Direction (including the no-selection no-op) - all passing.

## 2026-08-28 - Content Studio Redesign: Phase 5 Topic Intelligence Workspace

**Backend.** New `TopicCandidate` (`src/models/topic_candidate.py`) -
title plus six 0-100 scored dimensions (audience potential,
specificity, novelty, story potential, researchability, platform fit)
and an `ai_recommendation`, all bundled onto one model in a single
generation call, per the redesign's own Topic schema - unlike
`StoryAngle`/`StoryAngleEvaluation`, which are generated and scored in
two separate passes. A user-authored topic (`TopicCandidate.custom()`,
the "Enter My Own Topic" path) leaves every score `None` rather than
faking a number the AI never produced; `overall_score` returns `None`
whenever any dimension is unset, instead of averaging over a partial
set. New `TopicCandidateGenerationService` mirrors
`StoryAngleGenerationService`'s batched-call/labeled-block pattern, but
deliberately takes only a raw seed idea plus genre/platform - Topic is
the first real stage in the redesign's own pipeline order, before an
`AudienceProfile`/`ChannelStyleProfile` exists for a project, so there
is nothing yet to compose a full `EditorialProfile` from. `VideoJob`
gained `topic_candidates: list[TopicCandidate]` and
`selected_topic_candidate: TopicCandidate | None`, both new and
backward-compatible (an old project JSON missing these keys loads with
empty/`None` defaults).

**GUI.** A new standalone "Topic intelligence" card in Content Studio,
above the existing settings card: shows the project's free-text seed
idea, lets a user Generate more (append) or Regenerate all (replace)
scored candidates, Select any candidate, or type and select a custom
topic. Each candidate's scores and AI recommendation render inline.
Wired via `get_topic_candidate_generation_service()`
(`src/desktop/services.py`), threaded through
`main_window.py`→`ProjectWorkspaceView`→`ContentStudioView` the same
way `reviewer_service` was threaded through in Phase 4.

**Deliberately not built this pass.** This card is intentionally *not*
one of the `_CI_STAGES` rotation, and selecting a candidate does not
change `job.topic` itself or feed
`ContentIntelligencePipeline.run_all()` - the redesign's own pipeline-
sequencing question of exactly where Topic selection should gate the
rest of the pipeline is a materially larger design decision than this
phase's own scope. Also deferred: adding Topic to the Phase 3 journey
strip (it still shows no checkpoint, as noted in that phase's own
entry below), and Reviewer-driven comparison/ranking of candidates
(the redesign's "Reviewer compares candidates, recommends
improvements" deliverable) - `ArtifactType.TOPIC` already exists from
Phase 1 for exactly this, but wiring it in is left to a later pass.

Quality gates: mypy (362 source files), ruff, and black all clean
across the full repo; new tests - `test_topic_candidate.py` (6),
`test_topic_candidate_generation_service.py` (12), and 7 new cases in
`test_content_studio_content_intelligence_gui.py` - all passing, full
suite re-run for regression.

## 2026-08-20 - Content Studio Redesign: Phase 0 baseline + Phase 1 artifact engine

New, separate initiative from the production-hardening phases above -
started after reviewing two design documents ("Content Studio Redesign"
and "Post-Script-Approval Production Plan") the user provided. Both
were reviewed critically rather than accepted at face value: the
Post-Script-Approval document's own stated baseline
(`phase10-production-gui-polish`) doesn't correspond to anything in
this repo's actual git history, and several of its "Implemented"
claims (a `FinalScriptLock` model, `ProductionSemanticBrief`,
`CinematicShotPlan`) don't exist anywhere in `src/` - flagged before
any work started rather than trusted. Google Flow mechanism explicitly
excluded from scope per the user's instruction. The two documents were
also sequenced correctly rather than worked in parallel: the Content
Studio Redesign builds up to Script Lock, which the Post-Script-
Approval plan explicitly assumes already exists - so Content Studio
comes first.

**Phase 0 (Repository Reconciliation and Redesign Baseline).**
`docs/CONTENT_STUDIO_REDESIGN_BASELINE.md` - independently verified
(via direct `Grep`/`Read` against every model and service, not the
plan's own claims) a KEEP/MODIFY/REUSE/REPLACE/MISSING matrix for
every redesign target artifact and workspace. Key findings: no
competing GUI entry point exists (`ContentStudioView` already contains
both the legacy and `ContentIntelligencePipeline` workflows in one
file); ~40 independent per-artifact status enums exist with no shared
vocabulary - the single largest missing piece is a unifying lifecycle
engine; Script Lock's real existing equivalent is
`ScriptVersion.locked` (a plain boolean with real lineage), not a
`FinalScriptLock` architecture, which was never real; Story
Architecture and Hook are both close, reusable matches to the
redesign's target shape already; Reviewer LLM as a general role
doesn't exist anywhere, but Fallback LLM's mechanical shape already
does (`LLMService`'s ordered `profile_ids` attempt chain). Baseline
suite confirmed green with no exclusions: ruff, black, mypy, and the
full pytest suite (1359 passed, 1 skipped, 0 failed).

**Phase 1 (Canonical Artifact Lifecycle, Versioning, Lineage and
Dependency Graph).** New `src/models/artifact_lifecycle.py`
(`ArtifactType`, `ArtifactLifecycleStatus`, `ArtifactProvenance`,
`ArtifactVersionRecord` with a static SHA-256 `compute_content_hash()`)
and `src/services/artifact_lifecycle_service.py`
(`ArtifactLifecycleService.create_version()`/`.transition()`/`.approve()`;
`ArtifactDependencyGraphService.compute_downstream_impact()`/`.invalidate_dependents()`).
The state machine enforces DRAFT→GENERATING→GENERATED→(UNDER_REVIEW/
APPROVED/REVISION_REQUIRED)→...→SUPERSEDED/INVALIDATED, with both
terminal states final and every transition returning a new record
rather than mutating the original - matching "revisions never mutate
approved/reviewed history": a version stuck at REVISION_REQUIRED can
never transition back to GENERATING, only to SUPERSEDED (once a new
version supersedes it) or INVALIDATED. `ArtifactDependencyGraphService`
walks `input_version_ids` edges breadth-first so branching dependencies
(one upstream version feeding two different downstream artifacts, both
feeding a third) are all found once, not missed or double-counted, and
`invalidate_dependents()` is idempotent - an already-SUPERSEDED/
INVALIDATED dependent is left untouched rather than re-stamped with a
new reason. Persisted as a new `VideoJob.artifact_versions` field - an
append-only ledger following the exact convention
`content_decisions`/`stale_artifacts` already established, deliberately
kept separate from the ~40 existing per-artifact status enums rather
than replacing any of them. 27 new tests
(`tests/test_artifact_lifecycle_service.py`) cover hash immutability,
version-numbering-per-artifact-id, every legal and illegal state
transition, the branching-dependency case explicitly, invalidation
idempotency, and old-JSON backward compatibility (a project file saved
before this field existed loads with an empty ledger). Deliberately not
wired into any real content-intelligence stage yet - this phase's own
exit criteria (an engine "stable and independent of GUI") don't require
that; migration happens one workspace at a time in later phases.

## 2026-08-28 - Content Studio Redesign: Phase 4 Reviewer LLM

**Backend.** New `ReviewerService` (`src/services/reviewer_service.py`)
generalizes `EditorialCritiqueService`'s established "one batched LLM
call, labeled-block parsing, critique-never-authors" pattern to work
across *any* artifact type, not just scripts. `ReviewerResult`/
`ReviewerIssue` (`src/models/reviewer_result.py`) deliberately reuse
`FindingSeverity` from `EditorialCritique` (already a generic 4-level
vocabulary, not script-specific) and `ArtifactType` from Phase 1's
artifact-lifecycle engine, rather than inventing parallel models.
`reviewer_profile_id=None` is a first-class, fully supported input -
`review()` returns `None` immediately with zero LLM calls, matching
the redesign's own "Reviewer provider/model or None" wording.

**GUI.** A generic "Review" button now sits next to every CI stage's
existing "Run" button in Content Studio - one wiring point
(`_CI_STAGE_REVIEW_TARGET`, mapping all 14 granular pipeline stages
onto the 9 canonical `ArtifactType`s plus the `VideoJob` field holding
that stage's current content) instead of bespoke reviewer code per
stage. Results (strengths, issues, an optional suggested revision
direction) render inline and are kept in a small transient,
per-stage-keyed dict - never persisted to `VideoJob`, since a review is
read-only critique, not authorship. Reusing `job.provider_preferences.
reviewer.reviewer_profile_id` (Phase 2) means a project with no
Reviewer configured shows the button disabled with an explanatory
label, rather than failing when clicked.

**Deliberately not built this pass** - and worth being explicit about
the gap rather than letting Phase 4 read as fully done: the redesign's
persistent right-side "AI Inspector" panel and its reusable "Standard
Action Bar" (Return/Regenerate/Save Draft/Review/Approve & Continue)
applied uniformly across every workspace; "Review All" (only
"Review [the currently selected stage]" exists); and a real
context-package builder that walks Phase 1's dependency graph to
assemble upstream-approved-artifact context - that graph has nothing
in it yet, since nothing in production code calls
`ArtifactLifecycleService.create_version()`, so today's "context" is
just topic/genre/target-audience, not dependency-aware. These are a
materially larger, higher-risk visual rework touching every workspace
uniformly; scoping them out here avoided risking Content Studio's
existing, well-tested layout in the same change that added the
Reviewer capability itself.

## 2026-08-20 - Content Studio Redesign: Phase 3 Dashboard + Command Center

**Projects Dashboard.** `DashboardView`'s table gained Platform,
Current stage, Readiness, Progress, Last modified, and Automation
columns (previously just Project/Topic/Stage/Status), plus the "Open
selected" action renamed to "Continue Production." Every new column
is computed via `ProjectHeaderService.summarize()` - the exact same
service `ProjectWorkspaceView`'s own persistent header already uses -
so the dashboard's answer to "what's next" can never drift from what a
user sees once they actually open the project. Progress is a
deliberately coarse, honest 4-step proxy over
`ProductionReadinessService`'s own states (blocked/ready-for-render/
ready-for-final-export/completed → 10/55/80/100%) rather than a
fabricated fine-grained percentage nothing in the backend actually
tracks.

**Content Studio production journey.** New
`ContentStudioJourneyService` (`src/services/content_studio_journey_service.py`)
condenses `ContentIntelligencePipeline`'s 14 granular stages into an
8-checkpoint strip (Audience→Research→Angle→Story→Hook→Script→
Quality→Script Lock), each showing Not started/Waiting/Needs
revision/Approved, wired as a new "Production journey" card at the top
of Content Studio. Two deliberate departures from the redesign
document worth recording: the checkpoints are ordered to match the
pipeline's *actual* execution order, not the document's own listed
order - research genuinely runs before angle selection in this
pipeline (angles are generated from research findings), so showing
Angle before Research would misrepresent what really happens; and
Topic has no checkpoint at all, since there's no real per-project
topic-approval concept yet (Topic Intelligence is Phase 5, not built)
- showing a permanently-"done" checkmark for state that doesn't
genuinely exist would be dishonest rather than just incomplete.

**Deliberately not built this pass**: a dashboard-level "Run/Resume
Automation" control for Fully Automatic projects. The existing
workspace-level Run/Resume button (built during the earlier Unified
Workspace Shell work) already covers this once a project is opened;
promoting it to the dashboard row itself would need real background
execution with live progress reporting from a screen that currently
has none, meaningfully more scope than this phase's other pieces.

## 2026-08-20 - Content Studio Redesign: Phase 2 Project Setup + AI configuration

**Backend.** `ProviderPreferences` gains `ReviewerConfiguration`/
`ReviewerMode` (ON_DEMAND / AUTOMATIC_AT_APPROVAL_GATES) - the one
genuinely new AI role the redesign asks for; Primary and Fallback
already existed as `ProviderPreference.preferred_profile_id`/
`.fallback_profile_ids` on the `llm` category and needed no new model.
Found and fixed a real pre-existing bug while wiring this up:
`ProjectSpecificationJobMapper` never read `ProjectSpecification.
providers` at all - a project's provider preferences were silently
discarded at creation time, and `VideoJob` had no field to hold them
even if it had. Added `VideoJob.provider_preferences: ProviderPreferences`
and fixed the mapper to actually copy `specification.providers` onto
it. Also added `ScriptOrigin` (INTERNAL/EXTERNAL,
`src/models/enums.py`) as `VideoJob.script_origin`, defaulting
INTERNAL until the alternate Import Approved Script path (Phase 15)
exists to ever set it to EXTERNAL.

**GUI.** `ProjectFormView` gains a Platform selector (previously
entirely absent from project creation despite `VideoJob.platform`
existing since early in this project), an Approval mode selector
(reusing the existing `APPROVAL_MODE_PRESETS`/`approval_mode_label()`
extracted during Phase 9's workspace-shell work, so project creation
and Content Studio's settings panel describe approval policy
identically), and a new "AI configuration" card with Primary/Reviewer/
Fallback LLM pickers populated from `ProviderProfileManagementService.
list_profiles()` filtered to the LLM category. Every role defaults to
"System default" (unconfigured) - matching the redesign's own explicit
"Reviewer provider/model or None, Fallback provider/model or None"
wording, so a project remains creatable with zero provider
configuration, consistent with this project having no real API keys
configured yet.

**Deliberately not built this pass**: the "Starting Point" selector
(Create from Idea / Import Approved Script) with its dynamic form-swap
- building it now would be premature since the Script Intake path
itself doesn't exist until Phase 15; finer per-decision-point gate
configuration in the creation form beyond the 3 named presets, since
that already exists later in Content Studio's own settings panel.

**Also fixed while touching this area**: `tests/test_provider_preferences.py`
was another dead print-script (5th this session) directly in scope
since `ProviderPreferences` was being modified - rewritten into 9 real
tests. `tests/test_video_job.py` was a 6th instance, flagged via a
background task the user then started independently in a separate
session - fixed directly in this session before that task's result
arrived (7 real tests); the user was told about the duplication so
they can discard the other session's now-redundant work.

## 2026-08-20 - Unified workspace shell: sidebar nav + Run/Resume

Reshaped `ProjectWorkspaceView`'s top nav row into a left sidebar that
stays visible beside the working panel, matching the user's "Unified
Workspace Shell" design doc's framing (an IDE's or video editor's shell,
not separate windows per function). Before implementing, reviewed the
doc against the actual codebase and found the persistent header
(Mode/Stage/Approval/Quality/Automation/Readiness) was already built in
Phase 9; the two genuine gaps were the sidebar layout itself and a
"Run / Resume" header action. Also flagged two mismatches between the
doc's mockup and what's actually buildable: a literal per-project dollar
budget figure (no per-job spend tracking exists - Phase 7's budget
gating is per-`ProviderProfile`, global) and the doc's flattened
12-stage sidebar (that's `ContentIntelligencePipeline`'s own stage list,
today nested inside one Content Studio tab rather than the legacy
`ContentPipeline`'s primary flow) - the user picked the lowest-risk
option: reshape only, keep the current 7 destinations, defer the
pipeline-unification decision.

`_handle_run_resume()` deliberately reuses `ProductionReadinessService.
evaluate()` rather than inventing a second "what's next" concept: it
maps the first blocker's `.stage` (or the readiness state itself, when
there are no blockers) to the corresponding sidebar tab and switches to
it. It's navigational only, not an auto-executor - the destination tab
still owns deciding exactly what to run there, matching the doc's own
framing that the shell is "primarily the professional GUI/orchestration
layer," not a new automation layer over existing controllers.

Verification note: one pre-existing timing-sensitive test
(`test_render_progress_updates_live_and_survives_cross_workspace_refresh`,
a real-QThread test with two short real `time.sleep()` calls) failed
once in a full-file run under heavy machine load from this session's own
background test processes, then passed cleanly in isolation (444s
wall-clock for ~2s of actual test logic, confirming severe contention at
that moment) - a pre-existing flakiness class already documented in this
codebase's own test comments, not a regression from this change; the
other 9 tests in the same file passed in both runs.

## 2026-08-20 - Phase 10: CI, pre-commit, and testing gaps

**CI workflow and dependency-list fix.** Added `.github/workflows/ci.yml`
running ruff → black --check → mypy → pytest on every push/PR to `main`,
against Python 3.13 (matching `pyproject.toml`'s declared target), with
system ffmpeg and headless Qt libraries (`libegl1`/`libgl1`/
`libxkbcommon0`/`libdbus-1-3`) installed via apt so no test needs to be
excluded from CI. Setting this up surfaced two real, pre-existing
correctness gaps rather than just wiring automation around them:
`requirements.txt` was missing `anthropic`, `openai`, `google-genai`,
and `google-auth` - the real LLM provider SDKs `src/shared/llm/
anthropic_provider.py`/`openai_provider.py`/`gemini_provider.py` actually
import at runtime - meaning a fresh `pip install -r requirements.txt`
could not have run the app or its test suite at all; fixed by adding
them to `requirements.txt` and splitting out a new `requirements-dev.txt`
(`-r requirements.txt` plus pytest/mypy/ruff/black) for CI and local dev
installs. Separately, `ruff check .` failed repo-wide on 153 pre-existing
`UP042` findings - this codebase's deliberate, pervasive convention of
`class X(str, Enum)` for every Pydantic-serializable enum - which would
have made every CI run red from the first commit; formalized as an
ignored rule in `pyproject.toml` with a comment explaining why, rather
than either leaving CI permanently red or mass-renaming ~150 enum
classes to `enum.StrEnum` for a purely cosmetic, non-functional change.

**Pre-commit hooks.** Added `.pre-commit-config.yaml`: ruff (`--fix`) +
black + the standard hygiene hooks (trailing-whitespace, end-of-file-
fixer, check-merge-conflict, a 5MB large-file guard).

**Restart tests for content-intelligence stages.** New
`tests/test_content_intelligence_pipeline_restart.py` (3 tests) proves
what `docs/IMPLEMENTATION_STATE.md` had only claimed: that content-
intelligence stages are restart-safe because their state lives entirely
on the persisted `VideoJob`. Each test round-trips a job through a real
`JsonJobStore` via a genuinely separate store instance pointed at the
same directory (not the same instance's warm in-memory cache - see the
existing `JsonJobStore` caching lesson this session already learned the
hard way once), then continues the pipeline with a fresh
`ContentIntelligencePipeline` instance too, proving a new process, not
just the same one, can pick up where a prior run left off - including a
pending approval decision still being resolvable after the round-trip.

**Formal invalidation-matrix regression tests.** New
`tests/test_invalidation_matrix_wiring.py` (7 tests) closes a gap the
existing `test_invalidation_service.py` left open: that file proves
`InvalidationService`'s own matrix logic exhaustively in isolation, but
nothing anywhere proved the 4 real production call sites
(`ContentIntelligencePipeline.run_revision`, `BulkStockAssignmentService`,
`BulkClipIngestionService`, `MediaGenerationPipeline.run_voice/.run_music/
.run_sound_effects`) actually invoke it correctly. This file drives each
real service end to end (a job with a revised script, a bulk stock
assignment, a bulk clip ingestion, each of voice/music/sound-effect
generation) and asserts on `job.stale_artifacts` afterward, including
one test confirming a stale flag genuinely gets cleared, not just added.

**Golden-path end-to-end test.** `test_full_pipeline_reaches_final_export`
(`tests/test_desktop_app_integration.py`) already drove create→research→
script→originality→scenes→render→assets→SEO→thumbnail→export through the
real GUI; extended it with Final Preview creation and approval, closing
the last named step ("final preview") the production-hardening spec's
golden-path wording called for. Content-intelligence approval gating
("approve") is deliberately left out of this one test - documented in
its own docstring as belonging to a separate pipeline stack with its own
dedicated coverage, since a project uses one content pipeline or the
other, never both in the same run.

**A 4th dead print-script test file, found and fixed.** While auditing
what CI would actually run, `tests/test_ffmpeg_capability_service.py`
turned out to be another instance of this session's recurring pattern
(after `test_provider_budget_service.py`, `test_stock_acquisition_service.py`,
and `test_advanced_settings.py`): module-level code with bare `assert`
statements executed once at collection time, zero real `def test_`
functions - meaning it provided no real regression protection, and would
have either silently passed (masking the absence of coverage) or failed
CI outright depending on whether ffmpeg happened to be detected. Rewritten
into 8 real pytest tests, most gated behind `@pytest.mark.skipif` when
ffmpeg/ffprobe aren't on `PATH`, so it behaves correctly both locally and
in CI (where ffmpeg is now installed via apt specifically so these tests
run for real rather than being skipped).

## 2026-08-20 - Phase 9: GUI project header & recovery UX

**Persistent cross-tab project header.** `ProjectHeaderService`
(`src/services/project_header_service.py`) computes 8 at-a-glance
fields (Mode, Stage, Approval, Next approval, Quality, Budget,
Automation, Readiness) fresh from `VideoJob` +
`ProductionReadinessService` + `ApprovalGateService` on every call -
no field is cached or tracked separately from the backend state it
reflects, matching `ProductionReadinessService`'s own "never trust a
stale verdict" convention. Two fields are documented narrower proxies
rather than silently misleading: `current_stage` only reflects the
legacy `ContentPipeline`'s stage tracking (`ContentIntelligencePipeline`'s
12 stages never touch `VideoJob.current_stage`); `budget_state` reports
unfulfilled `ManualAudioRequirement` count, since Phase 7's budget
gating tracks spend per `ProviderProfile` globally, not per job.
Wired into `ProjectWorkspaceView`: a header row inserted below the
project-name heading, cleared and rebuilt from scratch on every
`refresh()` (matching this codebase's established clear-and-rebuild
pattern for dynamically refreshed widget rows, rather than mutating
labels in place). `approval_mode_label()`/`APPROVAL_MODE_PRESETS` were
extracted out of `ContentStudioView` into a new shared
`src/desktop/approval_mode_labels.py` so both surfaces describe a
project's approval policy identically instead of duplicating the
preset-matching logic.

**Recovery UX for step failures.** Every workspace view had its own
identical `_record_error(job, message)` helper that appended to
`VideoJob.errors` and showed a dismiss-only `QMessageBox.warning`. All
6 (`ContentStudioView`, `ClipWorkspaceView`, `ProductionAudioView`,
`RenderWorkspaceView`, `QualityCenterView`, `PackagingView`) now route
through a new shared `show_recoverable_error()`
(`src/desktop/recovery_dialog.py`), which adds a real Retry action
button that re-invokes the exact handler/stage that failed (with its
original arguments recaptured via closure) rather than just
dismissing the error. This is deliberately *not* the same
per-classified-reason recovery `AssetModuleFailure` offers elsewhere
(e.g. "search stock" vs. "request manual upload") - these 19 call
sites across the 6 views only ever have a raw exception message, not
a typed failure reason, so "try again" is the one honest recovery
action available without fabricating unsupported choices; documented
as a real, larger remaining gap in `docs/REMAINING_GAPS.md`. The
render-workspace case needed one extra piece of plumbing: retrying a
failed render replays it with its original `user_input` (e.g.
per-scene asset decisions), which required threading `user_input`
through the worker thread's `failed` signal into
`_handle_render_failed()` rather than losing it once the worker
thread's closure went out of scope.

All existing GUI tests that monkeypatched `QMessageBox.warning` per
view module to avoid blocking on a real modal `exec()` call under the
offscreen Qt test platform were updated to patch
`show_recoverable_error` instead (5 test files); a new
`tests/test_recovery_dialog.py` unit-tests the dialog itself (no
retry falls back to plain warning; clicking Retry invokes the
callback; clicking OK does not) by monkeypatching `QMessageBox.exec`/
`.clickedButton` rather than actually blocking on a real dialog.

Caught one ordering bug of its own while wiring this in: every
`_record_error()` initially called `self._on_change()` *before*
showing the dialog, so the error would be visible on screen the
instant it happened. But `on_change()` here is
`ProjectWorkspaceView.refresh()`, which tears down and rebuilds every
workspace's widgets via `deleteLater()` - and `ContentStudioView`'s
settings-save retry closure captures the live `QComboBox`/`QLineEdit`
widgets it needs to re-read. `deleteLater()` is deferred, and the
dialog's `exec()` runs a nested Qt event loop, so those deferred
deletions could fire *during* the dialog, before Retry was even
clicked - a click-Retry-after-refresh would then call into an already
-deleted C++ object. Fixed by showing the dialog (and running any
resulting retry) before calling `on_change()`, matching the original
pre-Phase-9 ordering, so a retry closure's captured widgets are
guaranteed to still be the current build's widgets.

## 2026-08-20 - Phase 8: Dry-run as an explicit execution mode

Added `ExecutionMode` (`DRY_RUN`/`LIVE`/`MIXED`,
`src/models/advanced_settings.py`), wrapping rather than replacing
`AdvancedSettings.dry_run: bool` for backward compatibility. A
`model_validator` uses `model_fields_set` to detect which of the two
fields a caller explicitly set and derives the other; contradictory
explicit values are rejected (except under `MIXED`, which has no
boolean equivalent so no match is enforced). Old serialized project
files that only ever wrote `dry_run` load correctly and derive
`execution_mode` from it - proven by a dedicated backward-compatibility
test using a hand-written old-shape JSON string.

`MIXED` mode supports a genuine per-provider live/dry-run mix via
`provider_execution_overrides: dict[ProviderCategory, ExecutionMode]`
and `resolve_execution_mode(category)`: an explicit per-category
override always beats the global mode; an unlisted category under a
global `MIXED` mode resolves to `DRY_RUN`, not the literal `MIXED`
value - this was a real bug in the first implementation, caught by its
own test (`resolve_execution_mode`'s dict `.get()` fallback returned
`self.execution_mode` directly, which could literally be `MIXED`,
before being fixed to explicitly check for and substitute `DRY_RUN`).

Wired into `ProductionApplicationFactory` - the one place in the
codebase that actually constructs real-vs-dry-run provider instances -
for its music/sound-effect dry-run-provider fallback, with a test
proving MIXED mode resolves the two categories independently (one
overridden to LIVE, the other falling through to the DRY_RUN default).
Deliberately not wired further: `render_orchestrator_service.py`,
`runtime_configuration_loader.py`, `startup_diagnostics.py`, and
`settings_view.py` all still read the plain `dry_run` boolean, which
stays correctly synced - none of those are genuinely "one provider
among several categories" the way music/SFX are, so wiring them
carried less leverage for this pass.

Also found while touching this area: `tests/test_advanced_settings.py`
was another module-level print-script with zero real pytest test
functions (the third one found this session, after
`test_provider_budget_service.py` and the stock-acquisition suite) -
rewritten into 17 real, isolated tests since it directly covers the
model being modified.

## 2026-08-20 - Phase 7: Budget gating beyond LLM calls

Extended `ProviderBudgetService` gating - previously LLM-only - to
voice/music/SFX (`MediaGenerationPipeline.run_voice/.run_music/
.run_sound_effects`) and stock footage (`StockAcquisitionService.acquire()`).
Opt-in by design: a `budget_service` plus a `*_profile_id`/`profile_id`
at construction, and `estimated_cost_usd` on the call itself (defaults
`0.0`, which never blocks and never reserves) - none of these four
providers has a native per-call cost estimate today, unlike LLM
requests, so gating only actually engages once a caller supplies a
real number. Every pre-Phase-7 caller and test is unaffected. Check→
reserve happens before the provider call; release happens on any
failure path; a successful call leaves the reservation in place (the
estimate stands as the recorded spend, since none of these providers
reports back an actual cost to reconcile against). `StockAcquisitionService`
reports a budget block as a structured `AssetModuleFailure` (new
`AssetFailureReason.BUDGET_EXCEEDED`) rather than raising, matching
that service's existing typed-result convention rather than importing
`MediaGenerationPipeline`'s exception-based one.

This was flagged earlier in the session (alongside secret encryption)
as one of the two gaps that actually matter before real API keys get
added - a misconfigured or runaway voice/music/SFX/stock call
previously had zero budget safety net, unlike LLM calls.

Two real gaps found while building this, both left open rather than
expanded into: (1) no cost-estimation source exists yet for any of
these four providers - gating is wired but dormant until a pricing
layer is built on top; (2) `ProviderRegistry`/`ProviderProfile` aren't
wired to these services' actual provider objects - a caller must know
and pass the right `profile_id` by hand, there's no automatic
resolution from "the voice provider this job uses" to its budget
profile.

Also found and partially fixed, unrelated to this phase's own scope
but directly in the files touched: the entire pre-existing
stock-acquisition test suite (`test_stock_acquisition_service.py`,
`test_scene_stock_acquisition_workflow.py`,
`test_stock_acquisition_request.py`, ~716 lines) and
`test_provider_budget_service.py` were module-level print-scripts with
zero real pytest test functions - they "pass" regardless of whether
their own assertions hold. Rewrote `test_stock_acquisition_service.py`
into 12 real, isolated tests (needed genuine coverage of the exact
service being modified); flagged `test_provider_budget_service.py` as
a separate task; left the other two stock-acquisition files as a known,
documented gap rather than scope-creeping this phase further.

## 2026-08-20 - Phase 6: Asset provenance (reconciled, not duplicated)

Closed the second half of Phase 6 (render identity was already pulled
forward into Phase 5). Audited every field the spec's unified asset
provenance model asks for against what already exists, rather than
building a second model by default: `asset_id`/`created_at` already
exist on every model via `MissionBaseModel`; `provider`/`source`
already exist as `VideoClip.provider`/`.source_type`;
`original_request` is already covered by `VideoClip.prompt` and
`SceneAssetState.local_search_query`/`.stock_search_query`;
`project_id` isn't meaningful per-asset. Only three fields were
genuinely missing - added directly to `VideoClip` instead of a
competing model that would have duplicated the rest: `scene_id`
(wired into `SceneAssetVideoClipBuilderService.build_clips`),
`checksum` (SHA-256 via the new `AssetProvenanceService`), `qc_status`
(`AssetQCStatus`, `src/models/asset_provenance.py` - defaults
`PENDING`, no automated QC pipeline exists yet to advance it further).

Deliberately not built: `source_version` (needs session-spanning state
that would belong on `SceneAssetState`, not a freshly-rebuilt
`VideoClip` - out of scope for this pass) and automatic checksum
computation inside `build_clips()` itself (that method rebuilds the
*entire* clip list from scratch on every bulk reassignment, and this
desktop app has no background threading anywhere - hashing every ready
video file synchronously on the GUI thread on every such call risked
real UI freezes for larger asset libraries). `AssetProvenanceService`
is real and tested, just callable on demand rather than auto-wired
into that specific hot path.

Adding `scene_id` as a field `build_clips()` now reads surfaced a
pre-existing test-fixture gap across 3 files (`test_asset_stage.py`,
`test_pipeline_adapter_integration.py`,
`test_scene_asset_video_clip_builder_service.py`): each used
`SceneAssetState.model_construct()` (which bypasses required-field
validation) without ever setting `scene_id`, which the real
constructor has always required. Fixed by adding `scene_id=...` to
each fixture rather than making the new code defensive - real
construction paths always provide it; only the fast-construction test
escape hatch didn't.

## 2026-08-20 - Phase 5: Final Preview (with render identity pulled forward from Phase 6)

Added `FinalPreview`/`FinalPreviewAction`/`FinalPreviewStatus`
(`src/models/final_preview.py`, append-only on
`VideoJob.final_previews`) and `FinalPreviewService`
(`src/services/final_preview_service.py`) implementing the four spec'd
actions - APPROVE_FINAL, RETURN_TO_EDITING, REPLACE_SCENE,
REGENERATE_AUDIO. The spec explicitly requires binding a preview to
"an exact render identity," which didn't exist yet (that was Phase 6's
job) - rather than build a loose placeholder, built the real thing:
`RenderIdentityService` (`src/services/render_identity_service.py`), a
deterministic SHA-256 over video timeline + audio timeline + render
settings, order-independent and computable from inputs alone (the
produced output file is recorded separately, not hashed - identity has
to be answerable before a render exists, not just after). This is the
first half of Phase 6, done two phases early because Final Preview
had no way to function without it; the second half (unified asset
provenance model) stayed out of scope since nothing in Phase 5 needed
it.

`FinalPreviewService.is_current(job)` never trusts a stored verdict -
it recomputes the identity fresh and also checks
`InvalidationService.is_stale(job, "render_result")` on every call, so
an approved preview that no longer matches the current render surfaces
immediately as a new `BLOCKING` `BlockerCode.FINAL_PREVIEW_STALE` via
`ProductionReadinessService`, not just silently stays "approved."
Wired into Quality Center as a new "Final preview" card.

Deliberate design choice, not a shortcut: `FinalPreviewAction` is its
own vocabulary rather than reusing Phase 1's `HumanApprovalAction` -
REPLACE_SCENE/REGENERATE_AUDIO are workflow re-entry commands, not
approve/reject outcomes, and forcing them into the shared approval
vocabulary would have blurred it for every other decision point.
REPLACE_SCENE/REGENERATE_AUDIO themselves only record the human's
stated intent; the actual work already happens through Clip
Workspace/Production Audio, which already invalidate correctly on
their own.

Building this surfaced one real bug: `FinalPreviewService.create_preview()`
originally let `RenderIdentityService`'s `ValueError` (missing
timeline) propagate raw, while the GUI handler only caught
`RuntimeError` - a render marked successful without both timelines set
would have crashed the "Create final preview" button instead of
showing an error. Fixed by having `create_preview()` present a single
`RuntimeError` contract for every precondition failure, plus widening
the GUI handler's catch to match this codebase's established
`(RuntimeError, ValueError)` convention as defense in depth.

## 2026-08-20 - Phase 4: Unified production audio hardening

Added `MediaGenerationPipeline.run_all_audio()`, coordinating voice,
timeline, music, and sound-effect generation as one action: reuses
whatever is already valid, regenerates whatever is missing or stale,
and reports every component's outcome individually
(`AudioGenerationSummary`/`AudioComponentResult`/`AudioComponentStatus`
- REUSED/GENERATED/FAILED/SKIPPED/MANUAL_REQUIRED) instead of failing
atomically on the first problem. Voice reuse is checked against a new
`VideoJob.voice_script_version` field, set from
`ScriptVersionHistory.current_version.version_number` whenever voice
generation succeeds - so a script revision correctly forces voice to
regenerate even though `run_revision` never touches `voice_status`
directly. An unconfigured music/SFX provider now produces an explicit
`ManualAudioRequirement` (`src/models/manual_audio_requirement.py`,
deduplicated across repeat calls) instead of only a transient
exception, surfacing as a `BLOCKING` blocker via
`ProductionReadinessService`. Wired into Production Audio's GUI as a
"Generate all audio" button plus a last-run summary card.

Building the reuse-detection logic surfaced two real, pre-existing
bugs that had nothing to do with Phase 4 directly but blocked it:
`run_voice` called `attach_many(..., replace=False)`, which raises
`ValueError` the second time voice is generated for a job that already
has voice tracks - simply clicking "Generate voiceover" twice already
crashed, before any of this phase's code existed. `run_music`/
`run_sound_effects` had no duplicate-guard at all and would silently
accumulate a second music track or duplicate SFX cues on a second
call. Fixed by having all three replace their own prior output for the
same scope instead of only ever appending. Also caught and fixed: an
earlier version of Phase 3's invalidation matrix incorrectly marked
`video_timeline` stale whenever audio was regenerated - `run_all_audio`
calling the same job twice immediately exposed this (the timeline
never got reused, since it was marked stale by the very audio stages
that ran right after it was built). `GenreTimelinePipelineService`
takes only `scenes`/`clips`/`genre_id` and embeds no audio data, so
this was simply wrong; corrected in both `invalidation_service.py` and
`docs/ARCHITECTURE.md`'s matrix table.

Known gap: `ManualAudioRequirement.fulfilled`/`.provided_file` exist on
the model and `ProductionReadinessService` already respects them, but
nothing in the GUI sets them - a human who manually supplies a music
file today has no way to clear the resulting blocker short of editing
the project JSON directly.

## 2026-08-20 - Phase 3: Selective invalidation

Added `InvalidationService` (`src/services/invalidation_service.py`)
and `StaleArtifact` (`src/models/invalidation.py`, on the new
`VideoJob.stale_artifacts` field), formalizing the three dependency
rows the master prompt names explicitly - script change, scene
replacement, audio regeneration - as an actual lookup table (see the
new invalidation-matrix section in `docs/ARCHITECTURE.md`), not just a
description. Wired into the real trigger points:
`ContentIntelligencePipeline.run_revision` (script change),
`BulkStockAssignmentService`/`BulkClipIngestionService` (scene
replacement), and `MediaGenerationPipeline.run_voice/.run_music/
.run_sound_effects` (audio regeneration). Marking is non-destructive
(same append-only philosophy as `content_decisions`/
`script_version_history`); clearing is explicit, wired at every stage
that actually regenerates one of the affected fields
(`run_scene_planning` for `scenes`, `run_timeline` for
`video_timeline`, `run_voice` for `audio_timeline`, the two bulk
services for `scene_asset_states`/`video_clips`). Staleness feeds
`ProductionReadinessService` directly as a new `BLOCKING`
`BlockerCode.ARTIFACT_STALE`, so it's visible in Quality Center without
a second GUI surface.

Two matrix subtleties worth naming: `video_clips` is deliberately
excluded from the scene-replacement row (rebuilt synchronously in the
same call) and `audio_timeline` from the audio-regeneration row (same
reason) - marking either stale would have been actively wrong, not
just redundant.

Deliberately incomplete: `render_result` staleness is marked but never
cleared (nothing in the render pipeline calls `clear_stale()` on a
fresh render - touching that subsystem was judged out of scope for
this pass), and `AssetPipelineStage` (the render pipeline's own,
first-run asset resolution stage) doesn't call `InvalidationService`
at all, on the judgment that a fresh pipeline run rarely has anything
downstream yet to invalidate - untested, so treated as a judgment call
rather than a proven-safe one. Both tracked in `docs/REMAINING_GAPS.md`.

## 2026-08-20 - Phase 2: Readiness service & typed blockers

Added a typed `Blocker` model (`src/models/blocker.py`: `code`,
`stage`, `severity`, `message`, `affected_artifact`, `retryable`,
`recovery_action`) and `ProductionReadinessService`
(`src/services/production_readiness_service.py`), the first
centralized answer to "is this project ready" - `BLOCKED`/
`READY_FOR_RENDER`/`READY_FOR_FINAL_EXPORT`/`COMPLETED`, backed by a
list of typed blockers rather than a boolean. It inspects script/scene
planning, every pending approval gate (reusing Phase 1's
`ApprovalGateService.all_pending`), per-scene asset readiness
(converting a scene's `AssetModuleFailure` into a `Blocker` - the
Phase 2 "retrofit an existing failure path" item), the audio timeline,
the video timeline, the render result, and the policy report. Quality
Center gets a new "Production readiness" card consuming it directly,
so that indicator no longer duplicates its own readiness logic; the
existing "Post-render checklist" card was left alone since it tracks
genuinely different downstream artifacts (SEO/thumbnail/final export)
outside this service's scope.

Deliberately not done this phase: converting `MediaGenerationPipeline`'s
and `ContentIntelligencePipeline`'s bare `RuntimeError` messages into
`Blocker`-typed errors (would touch every stage method in both
pipelines plus their GUI call sites and existing error-path tests -
too large for this pass, and `ProductionReadinessService` already
surfaces the same "missing prerequisite" conditions independently by
inspecting `VideoJob` state directly); wiring the readiness service
into Render/Clip workspace indicators specifically, which still derive
their own local notions of "ready." Both tracked in
`docs/REMAINING_GAPS.md`.

## 2026-08-20 - Phase 1: Approval runtime gating & decision history

`ApprovalPolicyConfig` and `ApprovalService` existed but had never been
wired together, and `VideoJob.content_decisions` had zero append call
sites anywhere - both pre-existing gaps this phase closes. Added
`ApprovalGateService` (`src/services/approval_gate_service.py`),
resolving one stage's completion against the job's configured policy
via `ApprovalService.open_decision()` and recording the outcome as an
append-only `ContentDecisionRecord`. Wired it into
`ContentIntelligencePipeline` for the 6 stages that map onto an
existing named decision point (`content_strategy`, `research`,
`story_angle`, `narrative_architecture`, `hook`, `final_script`), each
gate fed a real confidence signal where one exists
(`AudiencePromise.confidence_score`, `ResearchResult.fact_confidence_score`,
`StoryAngleEvaluation.confidence_score`, `HookEvaluation.confidence_score`)
so `ApprovalService`'s existing confidence-based escalation (spec
section 56: an AUTO policy still pends on a low-confidence result) is
real, not decorative. `run_all()` now checks `is_blocked()` after each
gated stage and stops early, with the pending state persisted on
`VideoJob.content_decisions` so it survives a restart; a human resolves
it via the new "Approval history" card in Content Studio
(`src/desktop/views/content_studio_view.py`, Approve/Reject buttons) or
`ContentIntelligencePipeline.resolve_approval()` directly. Individual
stage buttons remain always-runnable regardless of gate state - only
`run_all()`'s auto-chaining respects it.

Deliberately deferred: `run_all()` always restarts from stage one
rather than resuming mid-pipeline after a gate clears (no
skip-already-completed-stage idempotency yet); `MediaGenerationPipeline`
is not gated (no matching named decision points exist for it today).
Both are separate, explicitly out-of-scope-for-this-phase concerns
tracked in `docs/REMAINING_GAPS.md`.

## 2026-08-20 - Phase 0: Documentation & control layer

Added the documentation set the production-hardening master prompt
calls for: `AGENTS.md`, `docs/IMPLEMENTATION_STATE.md`,
`docs/REMAINING_GAPS.md`, `docs/SYSTEM_TRACEABILITY_MATRIX.md`,
`docs/ACCEPTANCE_CRITERIA.md`, `docs/AI_IMPLEMENTATION_PROTOCOL.md`,
`docs/RECOVERY.md`, and this file (previously empty). Content is based
on a direct code audit, not the master prompt's own claims - every
Done/Partial/Missing verdict in `IMPLEMENTATION_STATE.md` traces to a
specific file.

Net new capability: none - this phase is entirely documentation,
establishing the baseline the remaining phases work against.

## Earlier work (this repository's history through Sprint B2)

The entries below summarize what already existed before the
documentation phase above, for context. Going forward, each phase gets
its own dated entry above this line.

**Genre-aware editorial intelligence engine (Sprints A1-A11).** Built
the full content-intelligence pipeline: genre-specific hook patterns,
pacing curves, reveal density, research policy, and quality thresholds
across 11 genres; Format/Audience/ChannelStyle profile composition;
research → story angles → narrative blueprint → retention audit → hooks
→ script → continuity bible → editorial critique → quality gate →
optional revision → packaging hypothesis → genre-aware scene planning,
each a separately GUI-triggered stage; three approval-mode presets;
script version lineage with lock/unlock and change-impact
classification. This made a previously-inert, sophisticated backend
(built in sprints 0-7, never reachable from the GUI) into the live
Content Studio experience.

**Bulk clip source assignment (Sprint B1).** Multi-select scenes in
Clip Workspace and bulk-assign stock footage (auto-selecting the
top-ranked search result) through the same real workflow the Render
Workspace already used one scene at a time. Combined with the earlier
bulk external-generation prompt-export/ingestion workflow, this covers
manual upload, stock footage, and externally-generated clips for bulk
assignment.

**Standalone voice/timeline/music/SFX generation (Sprint B2).** Turned
Production Audio from a read-only review panel into a real generation
screen, calling the same ElevenLabs-backed services the render pipeline
already used internally, just triggerable one stage at a time.

**Scope note, all of the above and going forward:** Google Flow, and
any browser automation targeting it, is explicitly out of scope. See
`AGENTS.md`.
