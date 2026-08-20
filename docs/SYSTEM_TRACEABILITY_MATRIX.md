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

---

Maintenance: add a row here in the same change that adds a new
Model/Service/Persistence/GUI/Tests combination. A capability that only
has some of these columns filled in is not done - see
`docs/ACCEPTANCE_CRITERIA.md`.
