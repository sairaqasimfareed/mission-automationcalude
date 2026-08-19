# Implementation State

Living document. Update this as part of the same change that closes a
gap - see `AGENTS.md` rule 7. Last reconciled: see the most recent entry
in `PROJECT_PROGRESS.md`.

Status legend: **Done** / **Partial** / **Missing**.

## Core architecture & state

| Capability | Status | Notes |
|---|---|---|
| GUI is not the source of truth | Done | Every workspace reads/mutates a persisted `VideoJob` (`src/models/video_job.py`) directly via `JsonJobStore`; no view keeps parallel workflow state. |
| Canonical state, identity & versioning | Partial | Strong for scripts (`ScriptVersionHistory`/`ScriptVersion`, `src/models/script_version.py`: lineage, lock/unlock, change-class tags). Every other artifact (research, audience promise, scene plan, assets, audio, timeline, render) is a single optional field on `VideoJob` with no version number or "produced from" identity binding. |
| Restart safety | Partial | Real and tested for the render pipeline (`PipelineCheckpointService`/`PipelineCheckpointStorageService`/`PipelineResumePlannerService`). Content-intelligence stages (`ContentIntelligencePipeline`) are restart-safe only because state lives on the persisted `VideoJob` - there is no checkpoint concept and no idempotency guard against re-running an already-completed stage. |

## Approval & content intelligence

| Capability | Status | Notes |
|---|---|---|
| Approval policy runtime | Partial | `ApprovalPolicyConfig` (3 modes: `full_auto`/`review_critical_stages`/`manual_editorial`) is real, persisted on `VideoJob`, and GUI-selectable in Content Studio settings. Nothing in either pipeline consults it to decide CONTINUE vs. WAITING_FOR_APPROVAL - `ApprovalService` exists (`src/services/approval_service.py`) but has zero production call sites. |
| Approval / decision history | Missing | `ContentDecisionRecord`/`VideoJob.content_decisions` (`src/models/content_decision_record.py`) is defined but never appended to anywhere in `src/`. No GUI history surface. |
| Content Intelligence artifacts | Done | Audience strategy → `AudiencePromise`; story architecture/beat sheet → `StoryBlueprint`/`StoryBeat`; reveal map + curiosity loops → `InformationRevealMap`; narrative curve → `GenreContentIntelligenceProfile.pacing_curve`; continuity → `ContinuityBible`. |
| Downstream consumption of planning artifacts | Done | `EditorialProfileCompositionService` flattens genre+format+audience+channel into what every generation service reads; genre changes are proven (by test) to change script generation, hook scoring, and quality thresholds. |
| Selective invalidation | Partial | `ScriptVersionService` classifies a script revision (STYLE_ONLY/FACTUAL/NARRATIVE/TIMING/STRUCTURAL) and can lock a version. No dependency matrix or cascade exists across the other eight artifact types (research → scene plan → assets → audio → timeline → render → export). |

## Production operations

| Capability | Status | Notes |
|---|---|---|
| Unified production audio + "Generate All" | Partial | `MediaGenerationPipeline` (`src/services/media_generation_pipeline.py`) runs voice/timeline/music/SFX as four real standalone stages on ElevenLabs-backed services, wired into Production Audio's GUI. No single "Generate All Audio" action; narration is not bound to a pinned script identity/version; no `ManualAudioRequirement` concept. |
| Production readiness + typed blocker model | Missing | No centralized readiness service, no shared typed `Blocker` model. Failure reporting is ad hoc per domain - `AssetModuleFailure` (has `recovery_options`) is the closest analog; everything else is a bare exception message. |
| Pause & resume | Partial | Real for the render pipeline via checkpoint services. No equivalent for content-intelligence stages. |
| Formal final preview | Missing | Only a named `final_preview` slot inside `ApprovalPolicyConfig`. No `FinalPreview` model, no APPROVE_FINAL/RETURN_TO_EDITING/REPLACE_SCENE/REGENERATE_AUDIO actions. |
| Deterministic render identity | Missing | Checksums exist for individual assets; nothing hashes a render's inputs (timeline + audio + settings) into one content-addressed identity. |
| Asset provenance | Partial | `Scene`/`VideoClip`/`AssetCandidate` carry `source_type`/`provider`/`license_type`/free-form `metadata`. No unified provenance model with `asset_id` + `checksum` + `qc_status`. |

## Providers, budget & reliability

| Capability | Status | Notes |
|---|---|---|
| Provider-independent architecture | Done | `VoiceProvider`/`MusicProvider`/`SoundEffectProvider` each have a real ElevenLabs adapter and a dry-run adapter; stock footage follows the same pattern via `VisualAssetRouter`/`StockFootageProvider`. |
| Budget gating | Done (scoped to LLM calls) | `LLMService` calls `ProviderBudgetService.check_request()`/`.reserve()`/`.release()` around every real LLM call (`src/services/llm/llm_service.py`). No equivalent gate in front of voice/music/SFX/stock provider calls. A duplicate, empty `src/services/provider_budget_service.py` file exists alongside the real implementation in `src/services/budget/` - dead weight, should be removed. |
| Dry-run as a first-class mode | Partial | `AdvancedSettings.dry_run` is a single boolean gating provider selection throughout the factory layer. No `DRY_RUN`/`LIVE`/`MIXED` enum - a per-provider live/dry-run mix isn't expressible. |
| Recovery UX | Partial | `AssetModuleFailure` has real structured recovery options. Voice/music/render/content-intelligence failures surface as a single `QMessageBox.warning` string with no structured retry/choose-provider affordance. |
| Quality gates | Partial | `ScriptQualityGateService` formalizes script quality (DRAFT/NEEDS_REVISION/EDITORIAL_REVIEW/APPROVED_FOR_PRODUCTION). `PolicyService` covers a separate content-policy check. Asset/audio/timeline/render/export have no equivalent typed gate. |

## GUI shell, docs & engineering practice

| Capability | Status | Notes |
|---|---|---|
| Workspace shell + persistent project header | Partial | `ProjectWorkspaceView`'s 7-tab shell (Content/Clips/Audio/Timeline/Render/Quality/Packaging) is close to the spec's suggested nav. No shared cross-tab header showing mode/stage/approval/quality/budget/readiness. |
| Documentation control layer | Missing (being closed - see below) | `docs/` had 16 older files but none of the specifically-named ones; `PROJECT_PROGRESS.md` and `docs/ROADMAP.md` were both empty; no `AGENTS.md`. This gap is being closed as part of the same change that added this document. |
| CI & pre-commit | Missing | ruff/black/mypy are configured in `pyproject.toml` and run manually every session. No `.github/workflows/`, no `.pre-commit-config.yaml`. |
| Testing strategy | Partial | Deep unit/integration coverage (1000+ tests). Restart tests exist only where checkpoint machinery exists (render pipeline). No restart tests for content-intelligence stages, no formal invalidation-matrix tests beyond script versioning, no single golden-path test spanning create→export. |
| Backward compatibility | Done | New optional `VideoJob` fields with sensible defaults absorb into old project files with no migration code - proven via `JsonJobStore`'s raw `model_dump_json`/`model_validate_json` round-trip, used consistently all session. |

## How this document is maintained

Every phase of the production-hardening work (see `docs/ARCHITECTURE.md`
for the phase sequence) updates the rows it touches in this file as part
of the same commit that does the work - not as a follow-up. A row that
still says "Missing" or "Partial" after a phase claims to have addressed
it is a bug in that phase's completion, not in this document.
