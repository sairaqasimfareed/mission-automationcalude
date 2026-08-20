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
| Approval policy runtime | Done | `ApprovalGateService` (`src/services/approval_gate_service.py`) resolves a stage's configured policy via `ApprovalService.open_decision()` and records the outcome. `ContentIntelligencePipeline` gates 6 of its 12 stages against their matching named decision points (`content_strategy`, `research`, `story_angle`, `narrative_architecture`, `hook`, `final_script`); `run_all()` checks `is_blocked()` after each gated stage and stops early on a pending decision, surviving a restart since the pending state lives on `VideoJob.content_decisions`. Individual stage buttons in the GUI remain always-runnable regardless of gate state - only `run_all()`'s auto-chaining respects the gate. Idempotent skip-if-already-run on `run_all()` re-entry is explicitly deferred, see `docs/REMAINING_GAPS.md`. |
| Approval / decision history | Done | Every gated stage appends a `ContentDecisionRecord` to `VideoJob.content_decisions` (append-only - a resolution adds a new record rather than mutating the pending one). Content Studio's "Approval history" card (`src/desktop/views/content_studio_view.py`) lists it newest-first with Approve/Reject buttons wired to `ContentIntelligencePipeline.resolve_approval()` when a decision is pending. |
| Content Intelligence artifacts | Done | Audience strategy → `AudiencePromise`; story architecture/beat sheet → `StoryBlueprint`/`StoryBeat`; reveal map + curiosity loops → `InformationRevealMap`; narrative curve → `GenreContentIntelligenceProfile.pacing_curve`; continuity → `ContinuityBible`. |
| Downstream consumption of planning artifacts | Done | `EditorialProfileCompositionService` flattens genre+format+audience+channel into what every generation service reads; genre changes are proven (by test) to change script generation, hook scoring, and quality thresholds. |
| Selective invalidation | Partial | `InvalidationService` (`src/services/invalidation_service.py`) formalizes the 3 dependency rows the spec names (script change, scene replacement, audio regeneration - see `docs/ARCHITECTURE.md`), marking `VideoJob.stale_artifacts` non-destructively and feeding `ProductionReadinessService` as `BLOCKING` blockers. Wired into `ContentIntelligencePipeline.run_revision`, `MediaGenerationPipeline.run_voice/.run_music/.run_sound_effects`, `BulkStockAssignmentService`, `BulkClipIngestionService`. Clearing is wired for `scenes`/`video_timeline`/`audio_timeline`/`scene_asset_states`/`video_clips`; **not** wired for `render_result` (nothing in the render pipeline calls `clear_stale` on a fresh render) - a stale render stays flagged stale even after re-rendering. `ScriptVersionService`'s own change-class tagging is unrelated and still the only classification of *what kind* of change happened. |

## Production operations

| Capability | Status | Notes |
|---|---|---|
| Unified production audio + "Generate All" | Done | `MediaGenerationPipeline.run_all_audio()` coordinates voice/timeline/music/SFX as one action: reuses whatever is still valid (voice checked against `VideoJob.voice_script_version` == the current `ScriptVersionHistory` version; timeline/music/SFX checked against `InvalidationService.is_stale`), regenerates whatever is missing or stale, and reports each component's outcome individually (`AudioGenerationSummary`/`AudioComponentStatus`: REUSED/GENERATED/FAILED/SKIPPED/MANUAL_REQUIRED) rather than failing atomically. An unconfigured music/SFX provider becomes an explicit `ManualAudioRequirement` (`src/models/manual_audio_requirement.py`) instead of an ambiguous exception, surfaced as a `Blocker` in Quality Center. Wired into Production Audio's GUI as "Generate all audio". Building this surfaced and fixed two pre-existing latent bugs: `run_voice`/`run_music`/`run_sound_effects` previously duplicated tracks (or raised `ValueError`) if called a second time on the same job, since none of them replaced their own prior output. |
| Production readiness + typed blocker model | Partial | `Blocker`/`BlockerCode`/`BlockerSeverity` (`src/models/blocker.py`) and `ProductionReadinessService` (`src/services/production_readiness_service.py`) give one BLOCKED/READY_FOR_RENDER/READY_FOR_FINAL_EXPORT/COMPLETED answer, inspecting script/scenes/pending approvals/per-scene asset state (including converting `AssetModuleFailure` into a `Blocker`)/audio timeline/video timeline/render result/policy report. Wired into Quality Center's new "Production readiness" card. Not yet wired into `MediaGenerationPipeline`'s or `ContentIntelligencePipeline`'s bare `RuntimeError` failure paths, nor into the Render/Clip workspace readiness indicators - see `docs/REMAINING_GAPS.md` Phase 2. |
| Pause & resume | Partial | Real for the render pipeline via checkpoint services. No equivalent for content-intelligence stages. |
| Formal final preview | Done | `FinalPreview`/`FinalPreviewAction`/`FinalPreviewStatus` (`src/models/final_preview.py`), append-only on `VideoJob.final_previews`. `FinalPreviewService.create_preview()` binds a preview to an exact `RenderIdentityService` hash; `.resolve()` applies APPROVE_FINAL/RETURN_TO_EDITING/REPLACE_SCENE/REGENERATE_AUDIO (the latter two recorded as stated intent, not executed - the actual work happens through Clip Workspace/Production Audio, which already invalidate correctly). `.is_current()` recomputes the identity fresh rather than trusting a cached verdict; an approved-but-no-longer-current preview surfaces as a `BLOCKING` `BlockerCode.FINAL_PREVIEW_STALE` via `ProductionReadinessService`. Wired into Quality Center's new "Final preview" card. Uses its own action vocabulary rather than `ApprovalGateService`'s `HumanApprovalAction`, since REPLACE_SCENE/REGENERATE_AUDIO are workflow re-entry commands, not approve/reject outcomes - see `docs/ARCHITECTURE.md`. |
| Deterministic render identity | Done | `RenderIdentityService` (`src/services/render_identity_service.py`): SHA-256 over video timeline identity (per-item scene/track/timing/clip source, order-independent) + audio timeline identity (per-track type/source/timing/volume, order-independent) + render settings (production mode, resolution, frame rate). Deliberately excludes the produced output file's own bytes from the hash - identity must be computable from inputs alone, before a render exists, so "would a fresh render still match?" is answerable without re-rendering. Built as part of Phase 5 rather than a separate Phase 6 pass, since Final Preview cannot function without it. |
| Asset provenance | Partial | `asset_id`/`created_at` already exist on every model via `MissionBaseModel`; `provider`/`source` already exist via `VideoClip.provider`/`.source_type`. `VideoClip` gained the three genuinely missing fields: `scene_id` (linked back to the originating `Scene`, wired into `SceneAssetVideoClipBuilderService`), `checksum` (SHA-256, computed via `AssetProvenanceService.compute_checksum()`), and `qc_status` (`AssetQCStatus`, defaults `PENDING` - no automated QC pipeline exists to set it beyond that). Deliberately not wired: automatic checksum computation inside `build_clips()` itself - that method rebuilds the *entire* clip list from scratch on every bulk reassignment, and hashing every ready video file synchronously on the GUI thread on every such call would risk real, noticeable UI freezes. `AssetProvenanceService.annotate()`/`.compute_checksum()` exist as real, tested, callable-on-demand utilities instead. No separate competing `AssetProvenance` model was built - the spec's provenance fields, once the 3 genuinely-missing ones were added, are already satisfied by fields that already existed. |

## Providers, budget & reliability

| Capability | Status | Notes |
|---|---|---|
| Provider-independent architecture | Done | `VoiceProvider`/`MusicProvider`/`SoundEffectProvider` each have a real ElevenLabs adapter and a dry-run adapter; stock footage follows the same pattern via `VisualAssetRouter`/`StockFootageProvider`. |
| Budget gating | Done | `LLMService` gates every real LLM call as before. `MediaGenerationPipeline.run_voice/.run_music/.run_sound_effects` and `StockAcquisitionService.acquire()` now gate the same way (opt-in `budget_service` + `*_profile_id`/`profile_id` constructor params, `estimated_cost_usd` on the call) - check→reserve before the provider call, release on any failure, left reserved on success. Off by default (`estimated_cost_usd=0.0`) since none of these providers has a native per-call cost estimate today, unlike LLM requests - existing callers are unaffected until a caller opts in with a real estimate and a configured profile. New `AssetFailureReason.BUDGET_EXCEEDED` normalizes a stock budget block into the same structured-recovery shape (`AssetModuleFailure`) every other stock failure already uses. |
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
