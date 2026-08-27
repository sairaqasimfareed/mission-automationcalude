# Content Studio Redesign — Phase 0 Baseline

Deliverable for "Content Studio Redesign — Detailed Phase-wise
Implementation Plan," Phase 0 (Repository Reconciliation and Redesign
Baseline). Produced by inspecting the actual current codebase directly
(`Grep`/`Read` against every model and service listed below) rather
than trusting the redesign plan's own repository-position claims,
which were written against a different clone/branch of this repo (see
"A note on provenance" below) and do not reliably describe what
`F:\mission-automation` actually contains today.

## A note on provenance

The companion "Post-Script-Approval Production Plan" document states
its own baseline as `sairaqasimfareed/mission-automation,
phase10-production-gui-polish` — a branch that does not correspond to
anything in this repository's actual history. Several of its
"Implemented" / "Architecture exists" claims (a `FinalScriptLock`
model with SHA-256 binding, `ProductionSemanticBrief`,
`CinematicShotPlan`/`ShotSpecification`, `ResolvedCinematicPrompt`) do
not exist under those names anywhere in `src/`. This document only
records what was independently verified in the real repository - it
does not carry forward either PDF's own "repository position" claims.

## KEEP / MODIFY / REUSE / REPLACE / MISSING matrix

| Redesign target | Current reality | Classification | Notes |
|---|---|---|---|
| Topic (candidates, scoring, selection) | `VideoJob.topic: str` - a plain free-text field, no candidate generation, scoring, or selection workflow anywhere | **MISSING** | Genuinely new: candidate schema, scoring fields, `Generate More`/`Regenerate All`/custom-topic flow, approval artifact. |
| Audience Strategy | `AudiencePromise` (`src/models/audience_promise.py`): topic, target_audience, platform, genre_id, duration, intended_emotion, central_curiosity, primary_question, viewer_benefit, expected_payoff, promise_strength | **REUSE + MODIFY** | Real overlap (central curiosity, viewer promise) but missing persona, viewer intent (as distinct from promise), tone/treatment, platform strategy, pain/desire, knowledge assumption. Extend rather than replace. |
| Creative Direction (angle, narrative thesis) | No dedicated model. Closest partial relatives: `StoryAngle`/`StoryAngleEvaluation` (angle generation+scoring already exist), `EditorialProfile.narrative_architecture_hint` (free-text structural guidance) | **PARTIAL REUSE + MISSING** | Angle generation/scoring machinery is real and reusable; "Creative Direction" as its own approved, versioned artifact with combined-angle logic and a stored Narrative Thesis is new. |
| Research Brief (questions + retrieval policy) | `ResearchPlan` (`src/models/research_plan.py`): topic + `research_questions: list[str]` + prompt_version only | **REUSE + MODIFY** | Question generation exists; source-type policy, exclusion list, freshness/geographic-scope/depth config, stable per-question IDs, and the "no retrieval until brief approval" gate are all missing. |
| Research (retrieval + evidence ledger) | `ResearchResult`/`ResearchAgent` (legacy) produce prose research summaries. **Zero** Evidence/Claim/source-span-binding models exist anywhere in `src/models`. | **MISSING (evidence layer)** / REUSE (retrieval agent) | The retrieval agent itself is reusable; claim-to-source binding, confidence/support-type/contradiction tracking, and a Key Facts registry are genuinely new - this is one of the largest net-new pieces in either plan. |
| Story Architecture (blueprint, beats, reveals, retention) | `StoryBlueprint`/`StoryBeat`, `InformationRevealMap`, `RetentionAuditReport` (all real, already wired into `ContentIntelligencePipeline`) | **KEEP + REUSE** | Closest match to an existing PDF2 target of any artifact in either document. Already timed, already beat-structured, already has a rule-based retention audit. Needs Fact-ID references added once the evidence layer exists. |
| Hook | `HookCandidate`/`HookEvaluation`, `select_winning_hook()` (real, already scored on retention/clarity/originality/factual grounding/tone fit) | **KEEP + REUSE** | Already close to PDF2's target shape. Missing: explicit `reveal_risk` field and fact-ID binding (depends on the evidence layer above). |
| Directives (writing rules for script generation) | **Zero** models named `Directive`/`WritingDirective` exist. `SceneEditingDirectives`/`GenreDirectiveGenerationService` are visual/production editing directives (camera, transitions), an unrelated concept. | **MISSING** | Genuinely new: directive source/precedence model (system/genre/project/user), conflict detection. |
| Script | `Script` (legacy, has `ScriptStatus`: DRAFT/UNDER_REVIEW/REVISION_REQUIRED/APPROVED/REJECTED) and `GeneratedScript` (CI pipeline, richer segment structure) - two parallel models for two parallel pipelines | **KEEP both + REUSE** | `GeneratedScript` is the stronger foundation (already segment-structured, already has `NarrativeCompressionService`/`ScriptRevisionService`). No rich text editor with selection-based AI edits exists in the GUI for either. |
| Quality Gate | `ScriptQualityReport`/`ScriptQualityGateService` (CI pipeline): aggregates `EditorialCritique` findings into DRAFT/NEEDS_REVISION/EDITORIAL_REVIEW/APPROVED_FOR_PRODUCTION | **KEEP + REUSE** | Already separates critique (advisory) from gate (authoritative decision) - exactly PDF2's Phase 13 principle. Missing: user-facing "ignore finding with reason" audit trail, "Fix All Safe Issues" batch action. |
| Script Lock | `ScriptVersion.locked: bool` + `ScriptVersionHistory.is_locked` (`src/models/script_version.py`) - a plain boolean flag on the current version, with real lineage (`parent_version_number`, `change_class`, sequential version numbering already validated) | **REUSE + MODIFY** | This is the real, closest-existing thing to "Script Lock" in this repo - not a `FinalScriptLock` architecture (that doesn't exist). Missing: content hash, quality-result binding, provenance (internal vs. external origin), and any downstream artifact actually storing "locked_script_id/hash." Extend `ScriptVersion`, don't build a parallel lock model. |
| Canonical artifact lifecycle (Draft/Generating/.../Superseded/Invalidated across every artifact type) | **~40 independent, per-artifact-type status enums** exist (`ScriptStatus`, `ResearchStatus`, `SceneStatus`, `VideoClipStatus`, `RenderStatus`, ... - see full list below). Each was designed for its own artifact, none share a vocabulary. | **MISSING (as a unifying concept)** | This is Phase 1 of the redesign plan and the single largest, most consequential net-new piece: no dependency graph, no lineage-across-artifact-types, no generic "impact calculation before Unapprove" exists anywhere. Every existing per-artifact status enum stays (they're not wrong, just not unified) - the new engine sits above them or replaces them one artifact at a time, not overnight. |
| Reviewer LLM (distinct role from Primary) | **Zero** matches for `Reviewer`/`reviewer_llm`/`reviewer_provider` anywhere in `src/`. `EditorialCritiqueService` does implement "critique without authoring" for scripts specifically, but as a fixed, single-purpose service, not a configurable per-project LLM role usable across every artifact type. | **MISSING (as a general role)** / REUSE (the *pattern*) | `EditorialCritiqueService`/`ScriptRevisionService`'s existing split (one service critiques, a different one revises, revision never bypasses the critique step) is the right template to generalize, not to throw away. |
| Fallback LLM | `LLMService.generate(profile_ids=[...])` already implements a real ordered fallback chain (`LLMServiceAttempt` records each attempt, provider/model/status/cost) - see `src/services/llm/llm_service.py`. | **KEEP + REUSE** | This is already exactly what PDF2 asks for mechanically. The gap is purely at the project-configuration layer: there is no single named "Fallback provider/model" project setting that maps to a specific slot in `profile_ids` - today every caller passes its own list. |
| GUI entry points | Exactly one `ContentStudioView` (`src/desktop/views/content_studio_view.py`) contains **both** the legacy 4-stage workflow (`_build_workflow_card`: research/script/originality/scenes) **and** the 14-stage `ContentIntelligencePipeline` workflow (`_build_ci_stage_panel`/`_CI_STAGES`) as two button rows in one view. | **No competing launcher exists** | There is no "legacy Content Studio vs. new Content Studio" ambiguity at the entry-point level to resolve - both workflows already live in one file. The redesign's 8-workspace split (Topic Intelligence / Audience & Creative Strategy / Research Center / Story Development / Script Workspace / Script Intake) is a decomposition of this *one* view's CI-stage panel, not a migration away from a second competing screen. |

Full status-enum inventory (for reference, not reproduced per-field):
`AssetQCStatus`, `AssetWorkflowStatus`, `AnimationExecutionStatus`,
`AudioComponentStatus`, `AudioTrackStatus`,
`BulkClipIngestionEntryStatus`, `BulkStockAssignmentEntryStatus`,
`CameraExecutionStatus`, `EditingDirectiveStatus`,
`EffectPresetStatus`, `JobStatus`, `FFmpegExecutionStatus`,
`EffectExecutionStatus`, `FinalExportStatus`, `FinalPreviewStatus`,
`GenreProfileStatus`, `GenreTimelinePipelineStatus`,
`SceneSourceStatus`, `VoiceStatus`, `MasterEditPlanStatus`,
`MusicGenerationStatus`, `OriginalityStatus`, `ProviderHealthStatus`,
`RenderNodeStatus`, `RenderGraphStatus`, `RenderProgressStatus`,
`ResearchStatus`, `VoiceBlueprintResolutionStatus`, `RenderStatus`,
`BlueprintResolutionStatus`, `SceneStatus`, `ScriptQualityStatus`,
`ScriptStatus`, `ScriptReviewStatus`, `SEOStatus`,
`SoundEffectGenerationStatus`, `ThumbnailArtifactStatus`,
`SubtitleExecutionStatus`, `VideoClipStatus`,
`TransitionExecutionStatus`, `VoiceDirectiveStatus`,
`VoiceGenerationStatus`, `VoiceProfileStatus`.

## LLM routing / provider abstraction (current state)

- `LLMService` (`src/services/llm/llm_service.py`) is the one central
  entry point every content-intelligence service already calls
  through - no service talks to a provider adapter directly.
- Model/provider selection is a `profile_ids: list[str]` ordered list
  resolved against `ProviderRegistry`/`ProviderProfile`, gated by
  `ProviderBudgetService` before each attempt. This is a real,
  reusable fallback-chain mechanism, not duplicated per-service.
- No project-level "Primary provider" / "Reviewer provider" /
  "Fallback provider" named configuration exists - `profile_ids` is
  currently constructed ad hoc per call site (see
  `ContentIntelligencePipeline.__init__`'s `profile_ids` parameter,
  threaded uniformly into every sprint-2-7 service).
- `EditorialCritiqueService` is the one place a "reviews without
  authoring" pattern already exists, scoped only to scripts.

## Backward-compatibility requirements

- `VideoJob` follows a single-slot-per-artifact pattern with
  Pydantic-default absorption on load - confirmed working precedent
  all prior session work relied on (`JsonJobStore`'s raw
  `model_dump_json`/`model_validate_json` round-trip). Any new
  artifact-lifecycle field must follow the same pattern: new optional
  fields with safe defaults, never a required field retrofitted onto
  an existing model.
- None of the ~40 existing per-artifact status enums should be renamed
  or removed as part of adopting a canonical lifecycle - old project
  JSON files reference these values by name; a unifying engine must
  layer on top or migrate one artifact type at a time with an explicit
  compatibility test, not a single flag-day rename.
- `ScriptVersion.locked` is already relied upon by
  `ContentIntelligencePipeline.run_all()`'s `lock_version()` call
  (Phase 8 of the earlier revised roadmap work, this session) - any
  extension to a richer lock record must keep this boolean meaningful
  for existing callers rather than replacing it outright.

## Redesign terminology → existing model glossary

| Redesign term | Existing equivalent (if any) |
|---|---|
| Topic candidate | none (new) |
| Audience Strategy | `AudiencePromise` |
| Creative Direction / Narrative Thesis | `StoryAngle` + `EditorialProfile.narrative_architecture_hint` (partial) |
| Research Brief | `ResearchPlan` |
| Evidence Ledger / Key Facts | none (new) |
| Story Blueprint / Beat Sheet | `StoryBlueprint` / `StoryBeat` |
| Curiosity & Reveal Plan | `InformationRevealMap` |
| Retention Plan | `RetentionAuditReport` |
| Hook | `HookCandidate` / `HookEvaluation` |
| Writing Directives | none (new; not the same as `SceneEditingDirectives`) |
| Script | `Script` (legacy) / `GeneratedScript` (CI pipeline) |
| Quality Gate | `ScriptQualityReport` / `ScriptQualityGateService` |
| Script Lock | `ScriptVersion.locked` (extend, don't replace) |
| Reviewer LLM | none as a general role (pattern exists in `EditorialCritiqueService`) |
| Fallback LLM | `LLMService`'s `profile_ids` ordered attempt chain |

## Baseline test-suite status

Full `ruff check .` / `black --check .` / `mypy` / `pytest -q` run
against the current `main` branch (commit `86bdc69` at time of
writing) - see the accompanying quality-gate output recorded in this
same work session. All four are green with no exclusions. This is the
"baseline suite green" exit criterion for Phase 0.

## Exit criteria check

- [x] Baseline suite green (ruff/black/mypy/pytest all pass repo-wide).
- [x] Every redesign target artifact/workspace above has an identified
      implementation location or is explicitly marked MISSING.
- [x] No undocumented competing GUI path remains - confirmed exactly
      one `ContentStudioView` entry point contains both existing
      content-generation workflows.
