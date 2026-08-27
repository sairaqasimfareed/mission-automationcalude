# System Traceability Matrix

For every major capability: Model → Service → Persistence → GUI → Tests.
A row with a gap in any column is presentation-only or backend-only
functionality - see `docs/REMAINING_GAPS.md` for what to do about it.

## Content intelligence pipeline

| Capability | Model | Service | Persistence | GUI | Tests |
|---|---|---|---|---|---|
| Audience promise | `AudiencePromise` | `AudiencePromiseService` | `VideoJob.audience_promise` | Content Studio, "Audience promise" stage | `test_audience_promise_service.py`, `test_audience_promise_model.py` |
| Research plan / research | `ResearchPlan`, `ResearchResult` | `ResearchPlanningService`, `ResearchAgent` | `VideoJob.research_plan`, `.research` | Content Studio, "Research plan"/"Research" stages | `test_research_planning_service.py` |
| Story angles | `StoryAngle`, `StoryAngleEvaluation` | `StoryAngleGenerationService`, `StoryAngleEvaluationService` | `VideoJob.story_angles`, `.selected_story_angle` | Content Studio, "Story angles" stage | `test_story_angle_generation_service.py`, `test_story_angle_evaluation_service.py` |
| Narrative architecture | `StoryBlueprint`, `InformationRevealMap` | `StoryBlueprintGenerationService`, `InformationRevealPlanningService` | `VideoJob.story_blueprint`, `.reveal_map` | Content Studio, "Narrative architecture" stage | `test_story_blueprint_generation_service.py`, `test_information_reveal_planning_service.py` |
| Retention audit | `RetentionAuditReport` | `RetentionAuditService` (rule-based) | `VideoJob.retention_audit` | Content Studio, "Retention audit" stage | `test_retention_audit_service.py` |
| Hooks | `HookCandidate`, `HookEvaluation` | `HookGenerationService`, `HookEvaluationService` | `VideoJob.hook_candidates`, `.selected_hook` | Content Studio, "Hooks" stage | `test_hook_generation_service.py`, `test_hook_evaluation_service.py` |
| Script generation | `GeneratedScript` | `ScriptGenerationService`, `NarrativeCompressionService` | `VideoJob.generated_script` | Content Studio, "Script" stage | `test_script_generation_service.py` |
| Continuity bible | `ContinuityBible`, `ContinuityValidationResult` | `ContinuityBibleExtractionService`, `ContinuityValidationService` | `VideoJob.continuity_bible`, `.continuity_validation` | Content Studio, "Continuity bible" stage | `test_continuity_bible_extraction_service.py`, `test_continuity_validation_service.py` |
| Editorial critique | `EditorialCritique`, `CriticFinding` | `EditorialCritiqueService` | `VideoJob.editorial_critique` | Content Studio, "Editorial critique" stage | `test_editorial_critique_service.py` |
| Script quality gate | `ScriptQualityReport` | `ScriptQualityGateService` (pure aggregation) | `VideoJob.script_quality_report` | Content Studio, "Quality gate" stage | `test_script_quality_gate_service.py` |
| Script revision | (mutates `GeneratedScript`) | `ScriptRevisionService` | `VideoJob.generated_script` (updated) | Content Studio, "Revision" stage | `test_script_revision_service.py` |
| Script versioning | `ScriptVersionHistory`, `ScriptVersion` | `ScriptVersionService` | `VideoJob.script_version_history` | Content Studio, "Revision" panel (lock/unlock) | `test_script_version_service.py`, `test_script_version_model.py` |
| Packaging hypothesis | `PackagingHypothesis` | `PackagingHypothesisService` | `VideoJob.packaging_hypothesis` | Content Studio, "Packaging hypothesis" stage | `test_packaging_hypothesis_service.py` |
| Genre-aware scene planning | `Scene` (with `narrative_function`) | `ScenePlannerAgent.plan_from_generated_script` | `VideoJob.scenes` | Content Studio, "Scene planning" stage | `test_scene_planner_generated_script.py` |
| Scene semantic intent → directives | `SceneEditingDirectives` | `GenreDirectiveGenerationService` (intensity bridge) | (consumed at timeline-build time) | - | `test_genre_directive_scene_intensity_bridge.py` |

## Visual asset acquisition

| Capability | Model | Service | Persistence | GUI | Tests |
|---|---|---|---|---|---|
| Manual upload (single scene) | `SceneAssetState` | `SceneAssetWorkflowService.apply_decision` | `VideoJob.scene_asset_states`, `.video_clips` | Render Workspace, per-scene | `test_scene_asset_workflow_service.py` |
| Stock footage (single scene) | `SceneAssetState`, `AssetCandidate` | `SceneAssetWorkflowService.search_stock`/`.apply_decision` | same | Render Workspace, per-scene | `test_scene_asset_workflow_service.py` |
| Bulk stock assignment | `BulkStockAssignmentResult` | `BulkStockAssignmentService` | `VideoJob.scene_asset_states`, `.video_clips` | Clip Workspace, scene checkboxes + bulk button | `test_bulk_stock_assignment_service.py`, `test_clip_workspace_bulk_assignment_gui.py` |
| Bulk manual-file ingestion | `BulkClipIngestionResult` | `BulkClipIngestionService` | same | Clip Workspace, "Ingest clips from folder" | `test_bulk_clip_ingestion_service.py` |
| Bulk external-generation prompt export | `ScenePromptExportEntry` | `ScenePromptExportService` | (writes a file, no job-state change) | Clip Workspace, "Export prompts" | `test_scene_prompt_export_service.py` |
| Asset provenance | `AssetQCStatus` (`src/models/asset_provenance.py`), `VideoClip.scene_id`/`.checksum`/`.qc_status` | `AssetProvenanceService` (`.compute_checksum()`, `.annotate()` - callable on demand, not auto-wired into `build_clips()`); `scene_id` alone is wired into `SceneAssetVideoClipBuilderService.build_clips` | `VideoJob.video_clips[*].scene_id`/`.checksum`/`.qc_status` | - (no dedicated GUI surface yet) | `test_asset_provenance_service.py`, `test_scene_asset_video_clip_builder_service.py` |

## Production audio

| Capability | Model | Service | Persistence | GUI | Tests |
|---|---|---|---|---|---|
| Voice generation | `ResolvedVoiceBlueprint`, `VoiceGenerationResult` | `MediaGenerationPipeline.run_voice` → `VoiceGenerationService` | `VideoJob.voice_status/.voice_file/.voice_provider/.audio_timeline` | Production Audio, "Generate voiceover" | `test_media_generation_pipeline.py`, `test_production_audio_generation_gui.py` |
| Editing timeline | `VideoTimeline` | `MediaGenerationPipeline.run_timeline` → `GenreTimelinePipelineService` | `VideoJob.video_timeline` | Production Audio, "Build editing timeline" | `test_media_generation_pipeline.py` |
| Background music | `AudioTrack` (BACKGROUND_MUSIC) | `MediaGenerationPipeline.run_music` → `MusicGenerationService` | `VideoJob.audio_timeline` | Production Audio, "Generate background music" | `test_media_generation_pipeline.py` |
| Sound effects | `AudioTrack` (SOUND_EFFECT) | `MediaGenerationPipeline.run_sound_effects` → `SoundEffectGenerationService` | `VideoJob.audio_timeline` | Production Audio, "Generate sound effects" | `test_media_generation_pipeline.py` |
| Generate all audio | `AudioGenerationSummary`, `AudioComponentResult`, `AudioComponentStatus` (`src/models/audio_generation_summary.py`) | `MediaGenerationPipeline.run_all_audio` | `VideoJob.voice_script_version` (binds voice to script version); summary itself is transient, not persisted | Production Audio, "Generate all audio" + last-run summary card | `test_media_generation_pipeline.py`, `test_production_audio_generation_gui.py` |
| Manual audio requirement | `ManualAudioRequirement`, `ManualAudioRequirementType` (`src/models/manual_audio_requirement.py`) | recorded by `MediaGenerationPipeline.run_all_audio` when no provider is configured | `VideoJob.manual_audio_requirements` | surfaced via Quality Center's readiness card (`BlockerCode.MANUAL_AUDIO_REQUIRED`) - no GUI to mark one `fulfilled` yet | `test_media_generation_pipeline.py`, `test_production_readiness_service.py` |

## Approval

| Capability | Model | Service | Persistence | GUI | Tests |
|---|---|---|---|---|---|
| Approval policy selection | `ApprovalPolicyConfig` | (none - pure config) | `VideoJob.approval_policy` | Content Studio settings, "Approval mode" | `test_approval_policy_presets.py`, `test_video_job_approval_policy.py` |
| Approval runtime gating | `ApprovalDecision` | `ApprovalGateService` (wraps `ApprovalService`), called from `ContentIntelligencePipeline`'s 6 gated stages + `run_all()` | `VideoJob.content_decisions` (pending state survives restart) | Content Studio, "Approval history" card - Approve/Reject buttons | `test_approval_gate_service.py`, `test_approval_service.py`, `test_content_intelligence_pipeline.py` (gating tests), `test_content_studio_content_intelligence_gui.py` |
| Decision history | `ContentDecisionRecord` | `ApprovalGateService` (append-only: a resolution adds a new record) | `VideoJob.content_decisions` | Content Studio, "Approval history" card, newest first | `test_approval_gate_service.py` |

## Render pipeline (restart-safe)

| Capability | Model | Service | Persistence | GUI | Tests |
|---|---|---|---|---|---|
| Checkpointing | `PipelineCheckpoint` | `PipelineCheckpointService`, `PipelineCheckpointStorageService` | disk-backed checkpoint store | Render Workspace (implicit) | `test_pipeline_checkpoint*.py` |
| Resume planning | `PipelineResumePlan` | `PipelineResumePlannerService` | derived from checkpoint | Render Workspace (implicit) | `test_pipeline_resume_*.py`, `test_pipeline_engine_resume.py` |
| Render orchestration | `RenderOrchestrationResult` | `RenderOrchestratorService` | `VideoJob.render_result` | Render Workspace, "Run render" | `test_render_orchestrator_*.py` |

## Readiness

| Capability | Model | Service | Persistence | GUI | Tests |
|---|---|---|---|---|---|
| Production readiness | `Blocker`, `BlockerCode`, `BlockerSeverity`, `ProductionReadinessReport`, `ReadinessState` (`src/models/blocker.py`, `src/models/production_readiness.py`) | `ProductionReadinessService` (read-only, recomputed each call - not persisted) | - (derived fresh from `VideoJob` state) | Quality Center, "Production readiness" card | `test_production_readiness_service.py`, `test_quality_center_readiness_gui.py` |
| Selective invalidation | `StaleArtifact` (`src/models/invalidation.py`) | `InvalidationService`, called from `ContentIntelligencePipeline.run_revision`, `MediaGenerationPipeline.run_voice/.run_music/.run_sound_effects`, `BulkStockAssignmentService`, `BulkClipIngestionService` | `VideoJob.stale_artifacts` | Quality Center, "Production readiness" card (surfaced as `BlockerCode.ARTIFACT_STALE`) | `test_invalidation_service.py` |
| Render identity | (raw `str` hash, not a model) | `RenderIdentityService` | - (recomputed fresh, not persisted; recorded on `FinalPreview.render_identity` when a preview is created) | - (consumed by Final Preview, not shown directly) | `test_render_identity_service.py` |
| Final preview | `FinalPreview`, `FinalPreviewAction`, `FinalPreviewStatus` (`src/models/final_preview.py`) | `FinalPreviewService` (append-only: `.resolve()` adds a new record) | `VideoJob.final_previews` | Quality Center, "Final preview" card | `test_final_preview_service.py`, `test_quality_center_final_preview_gui.py`, `test_production_readiness_service.py` (`BlockerCode.FINAL_PREVIEW_STALE` cases) |

## Cost control

| Capability | Model | Service | Persistence | GUI | Tests | Gap |
|---|---|---|---|---|---|---|
| LLM call budget gating | `ProviderBudgetCheckResult` | `ProviderBudgetService` (called from `LLMService`) | `ProviderProfile.daily_spent_usd/.monthly_spent_usd` | Provider Manager | (covered indirectly via LLM service tests) | - |
| Voice/music/SFX/stock budget gating | `ProviderBudgetCheckResult` | `ProviderBudgetService`, called (opt-in) from `MediaGenerationPipeline.run_voice/.run_music/.run_sound_effects` and `StockAcquisitionService.acquire()` | `ProviderProfile.daily_spent_usd/.monthly_spent_usd` (same as LLM) | - (no dedicated GUI surface for gating status yet) | `test_media_generation_pipeline.py`, `test_stock_acquisition_service.py` | No cost-estimation source exists yet to feed a real `estimated_cost_usd`; no `ProviderRegistry` resolution from a job's configured provider to its `profile_id` |

## Execution mode

| Capability | Model | Service | Persistence | GUI | Tests | Gap |
|---|---|---|---|---|---|---|
| DRY_RUN/LIVE/MIXED execution mode | `ExecutionMode` (`src/models/advanced_settings.py`) | `AdvancedSettings.resolve_execution_mode()` (pure method, no separate service) | `VideoJob`'s advanced settings / `AdvancedSettings.execution_mode`+`.provider_execution_overrides` | Settings view still only displays the legacy `dry_run` boolean | `test_advanced_settings.py`, `test_production_application_factory.py` (MIXED-mode provider-selection cases) | Only wired into `ProductionApplicationFactory`'s music/SFX provider selection; `render_orchestrator_service.py`/`runtime_configuration_loader.py`/`startup_diagnostics.py`/`settings_view.py` still read the plain `dry_run` boolean |

## GUI shell

| Capability | Model | Service | Persistence | GUI | Tests | Gap |
|---|---|---|---|---|---|---|
| Persistent cross-tab project header | `ProjectHeaderSummary` (`src/services/project_header_service.py`, plain data holder - not a `MissionBaseModel`, never persisted) | `ProjectHeaderService.summarize()` (pure, recomputes fresh each call from `VideoJob` + `ProductionReadinessService` + `ApprovalGateService`) | - (derived fresh, nothing new persisted) | `ProjectWorkspaceView`'s header row, rebuilt on every `refresh()` | `test_project_header_service.py`, `test_desktop_app_integration.py::test_project_header_row_reflects_summary_and_rebuilds_on_refresh` | `current_stage` only reflects the legacy `ContentPipeline`'s stage tracking, not `ContentIntelligencePipeline`'s 12 stages; `budget_state` reports unfulfilled `ManualAudioRequirement` count as a proxy, since Phase 7's budget gating tracks spend per `ProviderProfile`, not per job |
| Step-failure recovery dialog | - (no new model; wraps a raw exception message) | `show_recoverable_error()` (`src/desktop/recovery_dialog.py`) | - | All 6 workspace views' `_record_error()` (Content Studio, Clip Workspace, Production Audio, Render Workspace, Quality Center, Packaging) | `test_recovery_dialog.py`, plus each view's own GUI test file (`no_blocking_dialogs` fixture) | Only offers "Retry the same operation" - no per-classified-reason recovery options like `AssetModuleFailure` offers, since these callers only have a raw exception message, not a typed failure reason |
| Unified workspace shell (sidebar nav + Run/Resume) | - (no new model) | `ProjectWorkspaceView._handle_run_resume()` reuses `ProductionReadinessService.evaluate()` (no new service) | - | `ProjectWorkspaceView`'s left sidebar (replacing the prior top nav row) + a "Run / Resume" button in the persistent header | `test_desktop_app_integration.py` (`test_workspace_views_refresh_without_crashing_on_a_fresh_project`, `test_full_pipeline_reaches_final_export`, and the rest of the suite exercising `_show_workspace`/`_workspaces`) | `ContentIntelligencePipeline`'s 12 stages remain nested inside the Content tab, not flattened to top-level sidebar items - deliberately deferred, see `docs/IMPLEMENTATION_STATE.md`; "Run / Resume" is navigational only (jumps to the right tab), not an auto-executor - each tab still owns deciding what action to actually run |

## Engineering practice

| Capability | Model | Service | Persistence | GUI | Tests |
|---|---|---|---|---|---|
| CI pipeline | - | `.github/workflows/ci.yml` (ruff → black --check → mypy → pytest, Python 3.13, ffmpeg + headless Qt libs installed) | - | - | Self-verifying (the workflow itself running green is the test) |
| Pre-commit hooks | - | `.pre-commit-config.yaml` (ruff --fix, black, hygiene hooks) | - | - | Not independently tested - pre-commit's own hook implementations are trusted upstream code |
| Content-intelligence restart safety | - | proven against `ContentIntelligencePipeline` + `JsonJobStore` (no new service) | `VideoJob` fields (no checkpoint model - state lives on the job itself) | - | `test_content_intelligence_pipeline_restart.py` |
| Invalidation-matrix wiring | - | proven against `ContentIntelligencePipeline.run_revision`, `BulkStockAssignmentService`, `BulkClipIngestionService`, `MediaGenerationPipeline.run_voice/.run_music/.run_sound_effects` (no new service) | `VideoJob.stale_artifacts` | - | `test_invalidation_matrix_wiring.py` |
| Golden-path end-to-end | - | drives `ContentPipeline` + `RenderOrchestratorService` + `FinalExportService` + `FinalPreviewService` through the real GUI handlers (no new service) | `VideoJob` + every downstream artifact store | `ProjectWorkspaceView` (all 7 tabs) | `test_desktop_app_integration.py::test_full_pipeline_reaches_final_export` |

## Content Studio Redesign

| Capability | Model | Service | Persistence | GUI | Tests | Gap |
|---|---|---|---|---|---|---|
| Repository baseline | - | - | `docs/CONTENT_STUDIO_REDESIGN_BASELINE.md` (KEEP/MODIFY/REUSE/REPLACE/MISSING matrix, terminology glossary) | - | Baseline suite confirmed green (ruff/black/mypy/full pytest) | Documentation only, by Phase 0's own design - no behavior change |
| Canonical artifact lifecycle | `ArtifactType`, `ArtifactLifecycleStatus`, `ArtifactProvenance`, `ArtifactVersionRecord` (`src/models/artifact_lifecycle.py`) | `ArtifactLifecycleService` (state machine: create_version/transition/approve), `ArtifactDependencyGraphService` (compute_downstream_impact/invalidate_dependents) (`src/services/artifact_lifecycle_service.py`) | `VideoJob.artifact_versions: list[ArtifactVersionRecord]` (append-only ledger) | - (not yet wired into any workspace) | `test_artifact_lifecycle_service.py` (27 tests: hash immutability, version numbering, state-transition legality including terminal states, branching dependency traversal, invalidation idempotency, backward-compat round-trip) | Deliberately not yet wired into any real content-intelligence stage - this phase's own exit criteria only require the engine to be "stable and independent of GUI." The ~40 existing per-artifact status enums are untouched and continue governing their own models; this is a second, parallel ledger new artifact types register into as each workspace is migrated, one at a time, in later phases. |
| Project Setup AI configuration | `ReviewerConfiguration`, `ReviewerMode` (`src/models/provider_preferences.py`), `ScriptOrigin` (`src/models/enums.py`) | `ProjectSpecificationJobMapper` (fixed to actually copy `specification.providers` onto the job - previously silently discarded) | `VideoJob.provider_preferences: ProviderPreferences`, `VideoJob.script_origin: ScriptOrigin` (both new fields) | `ProjectFormView`: Platform selector, Approval mode selector (reuses `APPROVAL_MODE_PRESETS`), Primary/Reviewer/Fallback LLM pickers sourced from `ProviderProfileManagementService.list_profiles()` | `test_provider_preferences.py` (rewritten from a dead print-script; 9 tests), `test_video_job_ai_configuration.py` (4 tests, backward-compat), `test_project_specification_job_mapper.py` (+2 tests proving the mapper fix) | "Starting Point" selector (Create from Idea / Import Approved Script) and its dynamic form-swap not built yet - premature before the Script Intake path (Phase 15) exists; workflow-mode gate selection is still only the 3 named presets, no finer per-decision-point UI in the creation form itself (that already exists later, in Content Studio's own settings panel) |
| Projects Dashboard | - (no new model) | `ProjectHeaderService.summarize()` reused (no new service) | - (derived fresh from each job every `refresh()`) | `DashboardView`: Platform/Current stage/Readiness/Progress/Last modified/Automation columns, "Continue Production" action | `test_dashboard_view.py` (6 tests: row count, field display, readiness/progress for a fresh project, agreement with `ProjectHeaderService`, empty state, double-click routing) | No dashboard-level "Run/Resume Automation" control - deliberately deferred, see `docs/IMPLEMENTATION_STATE.md`; the existing workspace-level Run/Resume (Phase 9's Unified Workspace Shell) already covers this once a project is opened |
| Content Studio production journey | `JourneyCheckpoint`, `JourneyCheckpointStatus` (`src/services/content_studio_journey_service.py`, plain classes - not persisted) | `ContentStudioJourneyService.compute()` (pure, recomputes fresh from `VideoJob` + `ApprovalGateService` every call) | - | `ContentStudioView`'s new "Production journey" card, an 8-checkpoint status strip above the existing stage panels | `test_content_studio_journey_service.py` (9 tests: bare-job defaults, approved/waiting/needs-revision distinctions, Script Lock's 3 states, execution-order assertion) | Topic has no checkpoint (no real per-project approval concept exists yet - Phase 5, not built); ordered to match the pipeline's actual execution order, which differs from the redesign document's own listed order (research runs before angle selection here) |

---

Maintenance: add a row here in the same change that adds a new
Model/Service/Persistence/GUI/Tests combination. A capability that only
has some of these columns filled in is not done - see
`docs/ACCEPTANCE_CRITERIA.md`.
