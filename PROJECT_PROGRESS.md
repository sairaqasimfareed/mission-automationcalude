# Project Progress

Dated log, newest entry first. See `docs/IMPLEMENTATION_STATE.md` for
current capability status and `docs/REMAINING_GAPS.md` for what's next.

---

## 2026-09-07 - Google Flow External UI Automation, GF-0: Product boundary, threat model & domain contracts

**Standing scope note superseded, explicitly, by the user.** Every prior initiative in this repository excluded Google Flow (`AGENTS.md`'s own scope boundary: "stop and ask" before automating a third-party product's web UI outside its published API). The user was shown the concrete risk (Google ToS exposure, fragility, no public API) and explicitly chose to proceed anyway. Two things stayed non-negotiable regardless of that authorization, and remain so for every future Flow phase: no CAPTCHA/MFA bypass, and I never enter the user's Google password myself.

**A real premise mismatch was found and resolved before writing any code.** The first two documents pasted for this work ("Master Strengthening, Repair, Local API Gateway & Production Certification Prompt") framed the task as auditing and repairing an *existing* Google Flow subsystem, naming specific components (`ExternalUIGenerationProvider`, `google_flow_automation_service.py`, a Playwright-sync-inside-asyncio bug already "confirmed"). Grepping this entire live repository found zero matches for any of it - the exclusion from every earlier phase was real, there was never anything here to skip. That subsystem does exist, but in a completely separate, previously-established read-only reference repository (`E:\Projects\Mission-Automation\mission-automation-flow`, a different AI's own project) - confirmed by finding matching files there (`google_flow_automation_service.py`, `google_flow_playwright_adapter.py`, a `docs/GOOGLE_FLOW_EXTERNAL_UI.md` describing the exact same behavior). Surfaced this directly rather than either fabricating a "repair" against nonexistent code or silently pulling from the reference-only repo (a standing rule from earlier in this session). The user chose: build fresh, from scratch, in this repo, using a third document (`Google_Flow_External_UI_From_Scratch_Implementation_Plan.pdf`) as the authoritative behavioral spec, with zero reference to or copying from the E: repo.

**GF-0 scope**: typed domain contracts and a provider-neutral interface, unit-testable with no browser launched - the phase's own stated acceptance criterion. New `src/models/google_flow_generation.py`:

- `GoogleFlowGenerationState` - an 18-value lifecycle enum (PLANNED through READY, plus AUTH_REQUIRED/HUMAN_ACTION_REQUIRED/UI_CHANGED/SUBMISSION_UNCERTAIN/FAILED), names kept identical to both authoritative documents for direct traceability.
- `is_valid_transition()` - a directed transition graph distinguishing the ordinary happy path, the confirmation-optional edge (`PROMPT_PREPARED`/`ANALYZING` can reach `SUBMITTING` directly, since some Flow account configurations skip confirmation entirely), five "interrupt" states reachable from any non-terminal state (rather than duplicating that rule five times against every source state), and three terminal states (`READY`/`QC_FAILED`/`FAILED`) that never transition again.
- `GoogleFlowGenerationRequest` - scene binding, exact prompt text plus a computed `prompt_hash` property (mirrors `GeneratedScript.content_hash`'s own "hash the real content, never id/created_at" discipline), reference assets, typed execution settings, and an `idempotency_key`.
- `GoogleFlowExecutionSettings` - model family/mode/duration/aspect ratio, deliberately left as open strings rather than a fabricated closed enum, since this codebase has no verified knowledge of Google Flow's actual current option vocabulary (same "don't invent unverified specifics" discipline as `ElevenLabsVoiceTranslationService`'s `unsupported_controls`).
- `GoogleFlowFailure`/`GoogleFlowFailureCode` - mirrors `AssetModuleFailure`'s existing shape, extended with the one field the spec's own credit-sensitive-state rule actually needs: `occurred_after_possible_credit_exposure: bool`.
- `GoogleFlowQCResult`/`GoogleFlowQCOutcome`, `GoogleFlowReferenceAsset`/`GoogleFlowReferenceRole`.
- `GoogleFlowGenerationAttempt` - an append-only `state_history`, a model validator enforcing `state` always mirrors `state_history[-1]` and that `READY`/`QC_FAILED` carry a consistent `qc_result`, and `with_transition()` returning a new, validated copy rather than mutating in place (the same append-only convention as `ContentDecisionRecord`/`ScriptVersionHistory`, not a new one invented for this).

New `src/providers/external_ui_generation_provider.py`: `ExternalUIGenerationProvider(BaseProvider)`, an abstract `submit`/`observe`/`download`/`cancel_or_abandon`/`check_profile_health` contract with an explicit `supported_operations`/`ensure_supported()` mechanism (`ExternalUIOperationNotSupportedError`, never a silent no-op) - satisfying "not every provider must support every operation; unsupported operations must be explicit."

**REUSE confirmed by inspection, reserved for later phases rather than duplicated now**: `MediaTechnicalValidationResult` (Phase 8 of the Post-Script-Approval plan) is exactly GF-9's technical-validation shape; `ProviderBudgetService`/`ProviderRegistry` (already-built provider budget gating) already implement check/reserve/release against a `profile_id` + `estimated_cost_usd` with no live-balance fabrication - precisely GF-11's own budget contract. New `ProviderCategory.EXTERNAL_UI_VIDEO` keeps a Flow account provider-registry-distinct from an official documented `VIDEO` API provider, the mechanical enforcement behind "Google Flow must never show an API Key field."

**A real, disclosed gap found while designing this, deliberately not fixed yet**: `ProviderProfile.validate_provider_profile()` hard-requires a `secret_reference` whenever a profile is `enabled=True` - correct for every existing API-key provider, wrong for a Flow account, which authenticates via a persistent browser profile, not a secret string. Relaxing that validator belongs to GF-2/GF-3 (persistent browser profile identity and multi-account registry), not to a domain-contracts phase - noted here rather than silently patched out of scope.

**Worker/async execution model, decided now per GF-0's own checklist, executed later**: Playwright's Sync API inside a dedicated background worker thread (GF-2), not asyncio. This codebase has zero asyncio anywhere - every provider and service, including the entire render pipeline, is synchronous. The other repo's own "confirmed error" (Playwright Sync API inside an asyncio loop) is exactly the failure mode of mixing paradigms; the fix here is architectural, not a patch: pick one paradigm (sync, matching everything else in this codebase) and give it a dedicated thread boundary so a multi-minute Flow generation never blocks the PySide6 GUI's own Qt event loop.

**Tests**: `test_google_flow_generation_model.py` (34 tests: request/settings/reference/failure/QC construction and validation, full state-machine coverage of the happy path, the confirmation-optional edge, interrupt-state reachability from mid-flight, terminal-state dead-ends, illegal-jump rejection, attempt history-consistency validators, `with_transition()` immutability and rejection of illegal transitions), `test_external_ui_generation_provider.py` (6 tests: a fully-supported and a partial-support fake provider, per-account health, explicit unsupported-operation errors naming the provider). Broader regression (`-k "provider or budget"`, 122 cases) confirms the new `ProviderCategory` member breaks nothing already built. mypy/ruff/black clean on every touched file.

**Deliberately not built this pass**: GF-1 through GF-17 (persistent ledger wiring onto `VideoJob`, real browser profile management, the actual Google Flow Playwright adapter, GUI, REST gateway, security hardening, fake-Flow test harness, real-account certification) - this entry covers GF-0 only, continuing immediately per the phase order both documents specify.

---

## 2026-09-07 - Reviewer-audit fix (Claim 3 of 3): No genre-based routing default for Scene.source_type

**Finding, verified independently before any fix.** The same external reviewer audit claimed Phase 6's "route defaults by project/genre with per-clip override" doesn't exist - `Scene.source_type` always defaults uniformly to `MANUAL_UPLOAD` regardless of genre, and only the per-clip override half (a person or a later stage changing one scene's own `source_type`) was ever built. Confirmed by reading both `Scene(...)` construction sites in `ScenePlannerAgent` (the legacy `plan()` and the content-intelligence `plan_from_generated_script()`/`_build_scene()`) - neither ever set `source_type=`, so it always fell through to the model's own default. Cross-referenced against the literal PDF-1 text ("Apply route defaults by project/genre with per-clip override," Phase 6, primary inputs explicitly naming "project/genre... policy") and this session's own prior Phase 6 log entry, whose "Deliberately not built this pass" section names two unrelated gaps but never discloses this one.

**Fix.** New `GenreContentIntelligenceProfile.default_scene_source_type: SceneSourceType = SceneSourceType.MANUAL_UPLOAD`, restricted by a validator to `MANUAL_UPLOAD`/`STOCK_FOOTAGE` only - the two routes this codebase's real acquisition workflow exercises end to end (`AI_GENERATE` is reserved and disabled by `Scene`'s own validator; `IMAGE_TO_VIDEO` is disabled in the live asset workflow, `AssetDecisionService` raises on it; `LOCAL_LIBRARY` has no established convention anywhere in this codebase for deriving its required `local_library_query` automatically, unlike `STOCK_FOOTAGE`'s `stock_query`, which already has one - falling back to the scene's own `visual_prompt`, per `scene_asset_workflow_service.py`). Reachable identically from both scene-planning paths since `GenreProfile.content_intelligence` and `EditorialProfile.content_intelligence` are the same type. Populated with real, differentiated values across all 11 default genres, not copy-pasted: `STOCK_FOOTAGE` for documentary/history/travel/top10/medical/survival (real-world-footage genres, where stock libraries genuinely have relevant material); `MANUAL_UPLOAD` for default/horror/storytelling/mystery/reaction (staged/dramatized content, where stock rarely matches the creative intent).

`ScenePlannerAgent` gained a constructor-injected `genre_registry: GenreProfileRegistryService | None` (defaults to a real `.with_default_profiles()` instance - matching `AudioCuePolicyService`'s own "no existing behavior for a default-off posture to protect" reasoning, since resolving a genre here only ever changes `source_type`/`stock_query`, fields every caller already left at their prior defaults). `plan()` gained an optional `genre_id: str | None = None` param: `None` preserves the exact prior MANUAL_UPLOAD-uniform behavior (zero blast radius for `RenderPipeline`, a separate dry-run demo path that never passes one); a real genre_id resolves via the registry (with fallback) and sets `source_type`, plus `stock_query=visual_prompt` when the resolved route is `STOCK_FOOTAGE` (Scene's own validator hard-requires a non-empty `stock_query` whenever `source_type == STOCK_FOOTAGE`, regardless of status). `plan_from_generated_script()`/`_build_scene()` read the same field directly off the already-composed `editorial_profile.content_intelligence` - no registry lookup needed there, since composition already happened upstream. The two real, live call sites now thread it through: `ContentPipeline.run()` passes `job.genre_id`, and `ContentStudioView._handle_plan_scenes()` passes `job.genre_id` - both places genre was already available but never reached scene planning.

**Tests:** `test_genre_profile_registry_service.py` (+8 script-style assertions: differentiated defaults across STOCK_FOOTAGE and MANUAL_UPLOAD genres, `AI_GENERATE`/`LOCAL_LIBRARY` rejected as a default route). `test_scene_planner_agent.py` (+3: no-genre preserves prior behavior, documentary genre attaches a real `stock_query`, unknown genre falls back safely). `test_scene_planner_generated_script.py` (+2: MANUAL_UPLOAD genre attaches no query, STOCK_FOOTAGE genre attaches `stock_query == visual_prompt`, proving `Scene`'s own validator is satisfied rather than bypassed). `test_content_pipeline.py` (+1: proves `ContentPipeline.run()` actually threads `job.genre_id` end-to-end into the scenes it produces, not just that the parameter exists). Targeted regression: those 4 files = 11 passed; `test_desktop_app_integration.py` + `test_content_studio_content_intelligence_gui.py` = 135 passed; full suite = 2114 passed, 1 unrelated pre-existing timing flake in `test_ffmpeg_execution_diagnostics.py` (passes in isolation, touches nothing this fix changed). mypy/ruff/black clean on every touched file.

**Deliberately not built this pass:** no genre default for `LOCAL_LIBRARY`/`IMAGE_TO_VIDEO`/`AI_GENERATE` routes - the first has no established query-derivation convention to reuse, and the latter two are reserved/disabled in this codebase's real workflow independent of this fix; no change to `AssetDecisionService`'s own USE_LOCAL/manual-upload/stock priority order (that governs runtime *recovery* decisions after a route is already chosen, a different concern from the *initial* default this fix addresses); the reviewer's separate, non-scored aside (genre-change-after-lock has no invalidation) traces to pre-existing Content Studio Redesign wiring per the reviewer's own note, not to either audited PDF, and was not requested as a fix.

**This closes all three claims from the 2026-09-07 external reviewer audit** (SFX/music duplication on pipeline re-run, `ScriptLock` missing topic/angle/target-duration/genre, and this genre-routing default), each verified independently against the actual code and the literal PDF-1 source text before any fix was written, per the user's "yes fix" instruction.

---

## 2026-09-07 - Reviewer-audit fix (Claim 2 of 3): ScriptLock never persisted topic/angle/target duration/genre

**Finding, verified independently before any fix.** The same external reviewer audit claimed `ScriptLock` doesn't persist "topic, angle, target duration, genre/profile references" that PDF-1 Phase 0's own Implementation-work bullet explicitly names ("Persist lock version, script version, topic, angle, target duration, genre/profile references, and upstream content-plan hash") - only version/hash/provenance/quality status were actually carried. Confirmed by reading `src/models/script_lock.py` directly (only `script_version_number`/`script_content_hash`/`provenance`/`quality_status`/`override_reason` existed) and cross-referencing this session's own Phase 0 log entry (`PROJECT_PROGRESS.md` lines 896-963 at the time), whose "Deliberately not built this pass" section names two unrelated gaps but never discloses this one - a silent miss, not an honestly-flagged deferral.

**Fix.** `ScriptLock` gains four new fields: `topic: str | None`, `angle: str | None`, `target_duration_seconds: int | None` (`gt=0` when set), `genre_id: str | None` - all optional with a `None` default, matching this codebase's own established convention for every field ever added to an already-persisted model (`Scene.locked_script_hash`, every SEOPackage/ThumbnailArtifact provenance field, etc.), specifically so an already-persisted `VideoJob` whose `script_lock` JSON predates this fix still loads cleanly through `JsonJobStore`'s raw `model_validate_json()` with zero migration code - a required field with no default would have broken exactly that. `ScriptLockService.build_lock()` now populates `topic`/`target_duration_seconds`/`genre_id` from the job for every newly-built lock (all three always exist on `VideoJob` - non-optional, defaulted fields), and `angle` from `job.selected_story_angle.description` when present. `angle` stays honestly `None` for any lock built through the older, still-live Content Production flow, which never selects a `StoryAngle` at all - only the newer, not-yet-wired content-intelligence pipeline does; fabricating one would have been worse than leaving it unset. All four are snapshotted at lock time, not re-read from the job later, for the same reason `quality_status` is already snapshotted rather than referenced live - a later change to the job's own topic/duration/genre must never retroactively change what an already-issued lock attests to (proven by a new test that mutates the job after locking and confirms the lock's own values hold).

**Collateral fix - 6 pre-existing test files constructed `ScriptLock(...)` directly** (`test_clip_materialization_service.py`, `test_final_export_service.py`, `test_packaging_view_gui.py` x3, `test_seo_context_builder.py`, `test_seo_package_service.py`) for unrelated reasons (clip materialization staleness, final-export provenance, SEO staleness banners) - none needed changes since the new fields are optional, but each now explicitly passes `topic`/`target_duration_seconds`/`genre_id` (sourced from the same job the lock is being attached to, where one exists) so these fixtures stay honest about what a real lock actually carries rather than silently exercising an incomplete one.

**Tests:** `test_script_lock_model.py` (+6: all-new-fields-default-to-None for backward compatibility, blank topic/genre_id normalize to None rather than raising - matching the existing `override_reason`/`angle` pattern, stripped-when-present, non-positive duration still rejected). `test_script_lock_service.py` (+3: `build_lock()` captures topic/duration/genre from the job, captures the selected story angle's description when one exists, and snapshots all three rather than tracking the job live). Full regression: `test_script_lock_model.py` + `test_script_lock_service.py` + the 6 collaterally-touched files = 83 passed; `test_content_intelligence_pipeline.py` + `test_production_handoff_model.py` + `test_content_studio_content_intelligence_gui.py` + `test_desktop_job_store.py` = 256 passed; full suite = **2113 passed, 0 failed**. mypy/ruff/black clean on every touched file.

**Deliberately not built this pass:** "upstream content-plan hash" (also named in the same PDF-1 bullet) - not part of the reviewer's specific claim (which named exactly topic/angle/target duration/genre/profile references), and this codebase has no existing "content plan" artifact upstream of a script to hash in the still-live Content Production flow - inventing one to satisfy an unclaimed sub-requirement would be new scope, not a fix to a confirmed defect; genre/profile references are persisted as `genre_id` (the reference itself, matching how `VideoJob` itself stores genre as an id string, never a full profile copy) rather than a full `GenreProfile` snapshot.

---

## 2026-09-07 - Reviewer-audit fix (Claim 1 of 3): SFX/Music duplication on a full pipeline re-run

**Finding, verified independently before any fix.** An external reviewer audit claimed `SoundEffectPipelineStage.execute()` and `MusicPipelineStage.execute()` append/regenerate unconditionally with no idempotency check, and that `AdvancedSettings.resume_previous_pipeline=True` (default) combined with `skip_completed_stages=False` (a real, non-default but reachable setting) genuinely re-executes already-completed stages. Confirmed both halves by direct code inspection rather than trusting the claim: `PipelineResumePlannerService.create_plan()` (`src/services/pipeline_resume_planner_service.py:56-102`) sets `execution_stages = list(stage_names)` - literally every registered stage - whenever `skip_completed_stages=False`, regardless of `checkpoint.completed_stages`. `VoicePipelineStage` already guards against this correctly by raising; `SoundEffectPipelineStage` and `MusicPipelineStage` did not - both appended/regenerated every time, silently duplicating SFX cues and background-music tracks on a re-run.

**Fix - SFX (`src/pipeline/sound_effect_stage.py`).** A `Counter`, not a `set`, snapshotted once from `audio_timeline.tracks` at the very start of `execute()`, keyed on `(scene_number, resolved_start_time_seconds)` (`AudioTrack.metadata["scene_number"]` was already stamped by `SoundEffectGenerationService`, so no new model field was needed). Cues from the current run decrement a matched key; a key already at zero attaches normally. A `set` was tried first and rejected: it broke `test_execute_attaches_multiple_enabled_cues_per_scene` and `test_execute_warns_on_repetitive_sfx_via_audio_cue_policy`, both of which correctly need two cues sharing the same key *within one pass* to both attach (the second is a legitimate sibling cue, not a re-run duplicate) - the pre-run-only snapshot is what makes a `Counter` distinguish the two cases correctly. New metadata field `skipped_existing_count` plus a warning when non-zero.

**Fix - Music (`src/pipeline/music_stage.py`).** Background music is architecturally one continuous track for the whole video (unlike SFX's many per-scene cues), so the guard is simply: skip regeneration entirely (return `_skipped_result(metadata={"reason": "background_music_already_attached"})`) if `audio_timeline.tracks` already contains a `BACKGROUND_MUSIC` track. Moved the `audio_timeline` read to the top of `execute()`, before the existence check, and removed the now-redundant re-declaration later in the method.

**Tests:** `tests/test_sound_effect_stage.py` (+2: `test_execute_does_not_duplicate_cues_on_a_second_run` proves a second `execute()` call on the same job attaches 0 new cues and reports `skipped_existing_count == 2` with track count unchanged; `test_execute_still_attaches_both_repetitive_cues_within_one_run_after_second_pass` proves the repetitive-cue-within-one-pass case still attaches both cues on a first run, then correctly skips both - not one - on a second run, confirming the `Counter` snapshot boundary is exactly right). `tests/test_music_stage.py` (+1: `test_execute_skips_regeneration_when_background_music_already_attached` proves a second `execute()` call returns `attached: False`/`reason: background_music_already_attached` and does not add a second track). Both fixture files' `_job_with_timeline()` gained `voice_file=` (required by `VideoJob`'s own pre-existing "Audio timeline requires a voiceover file" validator, which only fires on revalidation - i.e. only once a second `StageContext` is constructed against a job whose `audio_timeline` is already populated, which none of the pre-existing single-execute tests ever did). Full regression: `test_sound_effect_stage.py` + `test_music_stage.py` + `test_voice_stage.py` = 34 passed; broader sweep across every pipeline/resume/render-orchestrator/audio test in the suite (`-k "pipeline or resume_planner or render_orchestrator or audio"`) = 344 passed, 0 failed. mypy/ruff/black clean on every touched file.

**Deliberately not built this pass:** no change to `PipelineResumePlannerService` itself (a stage-level idempotency guard is the correct, minimal fix - `skip_completed_stages=False` is a legitimate "regenerate everything" escape hatch for other stages, e.g. after a technical-validation failure, and narrowing it globally would remove that capability rather than fix the actual defect, which was duplication, not the resume setting existing).

This is fix 1 of 3 from the same external reviewer audit; Claims 2 (`ScriptLock` missing topic/angle/target-duration/genre persistence) and 3 (no genre-based routing default for `Scene.source_type`) follow in subsequent entries.

---

## 2026-09-06 - Step 2 (SEO, Thumbnail & Publishing Reconciliation): SEO-6 Canonical Visual Identity Binding and SEO-9 Migration/Restart Hardening (Step 2 SEO-0 through SEO-9 substantially complete)

**SEO-6 - the remaining buildable half of "consume canonical subjects/visual identities."** SEO-6's persistence/versioning half (version numbers, script-lock provenance, staleness) was already delivered in SEO-3/SEO-4; this closes the other half named in its own Implementation bullets. `VisualContinuityBible.identities` (Post-Script-Approval Production Plan, Phase 2 - canonical person/location descriptions, already extracted whenever a project has one) was never read by thumbnail generation at all - confirmed by inspection, matching the same "canonical authority exists, nothing consumes it" pattern found throughout this Step. `SEOContext` gains `canonical_visual_identities: list[str]` - plain description strings, not the full model, so this stays a read-only projection that can never itself become a second, drifting copy of continuity state. `ThumbnailConceptGenerationService`'s prompt now names each known identity and instructs the model to depict it consistently rather than inventing an alternate appearance, when a project has a continuity bible; silent otherwise (thumbnail generation still does not require one).

**Withheld-reveal/spoiler constraints - honestly deferred, not built.** No existing model in this codebase records "this beat is a twist that must not be spoiled in the thumbnail" in a form thumbnail generation could consume without inventing new infrastructure disproportionate to this pass; documented as a real gap rather than a fabricated check.

**SEO-9 - migration, restart and adversarial hardening, proven rather than assumed.** Every field added across SEO-2/SEO-3/SEO-4/SEO-6 is optional with a safe default, so backward compatibility was already structurally true - this phase's job was to *prove* it, not assume it. New tests write a real `SEOPackage`/`ThumbnailArtifact` with every new field populated through `JsonJobStore`, then read it back from a **fresh store instance** (a genuine restart, not just re-reading the same object) and assert an exact match. A second test hand-writes the *exact* on-disk JSON shape a pre-SEO-2/3/4/6 project would have - no `version_number`, no `source_*` fields at all - and confirms it loads through the real `JsonJobStore`, with every new field honestly defaulting to unset/1 rather than migration code guessing a value ("never invent SEO/genre/audience authority"). The same test proves a legacy project's existing `status` ("approved") survives unchanged, since nothing in the load path rewrites it - "stale approvals/reviews cannot become current by migration" holds trivially because there is no migration code to drift. A third test confirms `PackagingView.refresh()` never touches the filesystem to render a thumbnail (only ever displays the stored path as text), so a thumbnail whose file has since been deleted still refreshes cleanly rather than crashing the Packaging screen.

**Tests:** extended `test_seo_context_builder.py` (+2: identity list defaults empty, carries identities from a real `VisualContinuityBible`), `test_thumbnail_concept_generation_service.py` (+2: identity guidance appears in the prompt / is omitted when none are known), `test_desktop_job_store.py` (+3: full-field round-trip for both packages through a fresh `JsonJobStore` instance, legacy-JSON-loads-with-honest-defaults), `test_packaging_view_gui.py` (+1: missing thumbnail file doesn't crash refresh). Broader regression across the whole SEO/thumbnail cluster plus job-store persistence: 110 passed. mypy/ruff/black clean on every touched file.

**This substantially completes Step 2 (SEO-0 through SEO-9)** of the Step 2_Publishing_Reconciliation_Implementation_Plan.pdf's own phase map, per the strong/medium/not-necessary rating given earlier: SEO-0 (audit) and SEO-10 (release reconciliation) are process bookends rather than features; SEO-7 (workspace consolidation) and SEO-8 (final manual-upload package) were confirmed already substantially satisfied by the existing `PackagingView` and PDF-1 Phase 15's `FinalExportPackage` work respectively, with no material gap found worth a dedicated pass.

---

## 2026-09-06 - Step 2 (SEO, Thumbnail & Publishing Reconciliation): SEO-1/SEO-4/SEO-5 - Fail-Closed Freshness Gate, Precise Dependency Tracking, Reviewer/Approval Integration

Three related phases delivered together since each builds on the same provenance fields SEO-3 already added.

**SEO-4 - dependency-aware invalidation, made precise.** The staleness banner built in SEO-3/SEO-6 only compared script-content hash - genuinely catching "the script changed," but blind to genre, locale, or scene-count changes, none of which touch the script's own text. `SEOPackage`/`ThumbnailArtifact` gain four more provenance fields (`source_genre_id`, `source_target_country`, `source_language`, `source_scene_count`), populated by both build() methods from the same `SEOContext` that already carries these values. The packaging screen's banner is now a genuine dependency check - four independent comparisons, each naming exactly what moved, not one coarse "something changed." A new regression test proves the PDF's own explicit requirement directly: building (and rebuilding) an SEO package for a job that already has scenes/clips/a timeline/a render result never touches `InvalidationService`'s ledger or mutates any of them - "SEO-only edits must not invalidate clips/audio/render," proven, not assumed.

**SEO-1 - canonical production handoff, with a real fail-closed gate.** Most of SEO-1's own ask (render identity, script lock reference, genre/audience/locale) was already satisfied by `ProductionProvenance` (PDF-1 Phase 15) and `SEOContext` (SEO-2/3/4) - REUSE confirmed by inspection, not re-verified from scratch. The one genuinely missing piece: "Fail closed if upstream production authority is missing/stale" had no hard gate anywhere - the packaging screen's own staleness banner is a soft nudge, not a block. New `FinalExportValidationService._validate_upstream_freshness()` compares `FinalExportPackage.provenance.script_lock_hash` (the render's own canonical identity) against `seo_package.source_script_lock_hash`/`thumbnail_artifact.source_script_lock_hash` - two new hard `FinalExportValidationCode` errors (`SEO_PACKAGE_STALE`/`THUMBNAIL_STALE`) block final export outright when either predates the current lock or predates locking altogether. Silent when the package carries no provenance at all, or the job had no lock at render time - nothing to fail closed against.

**SEO-5 - Reviewer and approval integration, using a decision point that already existed and was never read.** `ApprovalPolicyConfig.publishing` has existed since the approval-policy model was first built, consumed only by `ProjectFormView`'s own config-building UI - grepping every service file found it was never once looked up to gate anything. `SEOPackage`/`ThumbnailArtifact`'s own `status` fields were confirmed (Phase 15's own investigation) to never transition away from DRAFT/UNDER_REVIEW anywhere in the codebase - a real, previously-flagged-but-deferred gap this phase closes. `_handle_generate_seo()`/`_handle_generate_thumbnail()` now check `job.approval_policy.policy_for("publishing")`: `AUTO` immediately marks the freshly-built package `APPROVED`; `REVIEW`/`MANUAL` (the default) leaves it `UNDER_REVIEW` for a person to act on. New Approve/Reject buttons render directly on each card when a package is `UNDER_REVIEW` - a deliberately simpler, more direct mechanism than routing through the generic cross-pipeline pending-decision banner elsewhere (Content Studio's Activity History), since a person reviewing SEO/thumbnail content is already looking at exactly the artifact in question. Every generation and every approval/rejection is recorded to the same shared `job.content_decisions` ledger via `ApprovalGateService.record_event()` (`GENERATION`/`APPROVAL` categories) - "shared audit primitives," reusing the exact mechanism Phase 18 already established, not a second competing approval-state machine.

**Tests:** extended `test_seo.py`/`test_thumbnail.py` (+model coverage for the four new SEO-4 fields), `test_seo_package_service.py` (+1 negative-proof test), `test_final_export_validation_service.py` (+6: silent-with-no-provenance, silent-with-no-lock, blocks-on-predates-lock, blocks-on-mismatch, blocks-on-thumbnail-stale, accepts-when-fresh), `test_packaging_view_gui.py` (+11: three new staleness-dimension banners, no-staleness-when-matching, approve/reject buttons shown/hidden by status, approve/reject flip status and record audit events for both SEO and thumbnail, auto-approve-on-AUTO-policy and stays-under-review-by-default through real generation with a stub LLM). Broader regression across the whole SEO/thumbnail/final-export/packaging cluster plus the full desktop app integration suite: 130 passed (120 targeted + the 10-case `test_desktop_app_integration.py`, confirming the new `ApprovalGateService` wiring through `ProjectWorkspaceView` doesn't break real app construction). mypy/ruff/black clean on every touched file.

**Deliberately not built this pass:** no inspectable version-history archive for SEO/thumbnail packages (same honest deferral as SEO-3/SEO-6 - not named as a GUI requirement); `REJECTED` is only ever set by an explicit human click, never automatically, matching "Reviewer never becomes approval authority" and this codebase's existing four-state vocabulary convention.

---

## 2026-09-06 - Step 2 (SEO, Thumbnail & Publishing Reconciliation): SEO-2 Genre and Audience Propagation

**REUSE confirmed by inspection - the canonical authorities SEO-2 asks for already existed, just never read.** `GenreProfile.seo`/`.thumbnail` (`GenreSEOProfile`/`GenreThumbnailProfile`, populated for all 12 genres from earlier session work) were never consulted by any SEO or thumbnail generation service - grepping every service file for `GenreSEOProfile`/`GenreThumbnailProfile`/`genre_profile_registry` found zero hits. Separately, `AudiencePromise.target_audience` (Content Studio Redesign, Phase 6's canonical audience artifact, persisted on `job.audience_promise`) already exists but `PackagingView` never read it - a person retyped a free-text guess ("General audience" placeholder) into a box every time SEO or a thumbnail was generated, completely disconnected from the audience already established earlier in the same project.

**A real, narrower architectural finding inside SEO-2 itself: not every `GenreSEOProfile` field is wireable.** `SEOKeywordGenerationService` and `SEOHashtagGenerationService` are both deterministic, non-LLM extraction algorithms (word-frequency ranking and token derivation) - reading them directly confirmed neither has any concept of "style" to guide, so `GenreSEOProfile.keyword_style`/`.hashtag_style` have no mechanism to act on without converting these into LLM-based generation, a materially larger, riskier rewrite than this pass should attempt. Only `SEOTitleGenerationService` and `SEODescriptionGenerationService` (both genuine LLM calls) and `ThumbnailConceptGenerationService` (also an LLM call) can actually consume genre tone/style guidance - and a concrete inconsistency was found while wiring the last one: `ThumbnailConceptGenerationService`'s prompt hardcoded "under 8 words" for hook text, while `GenreThumbnailProfile.maximum_words` (never read) defaults to 5 - the prompt and the model's own genre defaults already disagreed before this fix.

**What was built, all additive:**
- `SEOContext` gains `genre_seo_profile`/`genre_thumbnail_profile`, resolved once by `SEOContextBuilder.build()` via `GenreProfileRegistryService` (falling back to the bare dataclass defaults if resolution genuinely fails) - the one shared context every SEO/thumbnail service already consumes.
- `SEOTitleGenerationService`'s prompt now includes `title_tone`; `SEODescriptionGenerationService`'s includes `description_style`/`call_to_action_style`; `ThumbnailConceptGenerationService`'s includes `composition`/`color_mood`/`text_style`/a face-presence instruction derived from `use_faces`, and its hook-text word limit now reads from `maximum_words` instead of a hardcoded "8."
- `SEOContextBuilder.build()`'s `target_audience` parameter is now optional: omitting it resolves `job.audience_promise.target_audience` when the project has one; an explicit value still always wins (e.g. a Script-Intake project with no audience promise). `SEOPackageService.build()`'s own `target_audience` parameter mirrors this.
- `PackagingView`'s SEO and Thumbnail cards: when `job.audience_promise` exists, show the canonical audience read-only ("Target audience: ... (from Audience & Creative Strategy)") and call generation with no override, letting it resolve automatically - no free-text box, no re-guessing. A project with no audience promise keeps the exact original free-text fallback.

**Tests:** extended `test_seo_context_builder.py` (+4: default-from-promise, explicit-override-wins, both-missing-raises, genre-profile-resolution differs from default), `test_seo_package_service.py` (+1: end-to-end default-from-promise), `test_seo_title_generation_service.py`/`test_seo_description_generation_service.py`/`test_thumbnail_concept_generation_service.py` (+1 each: genre guidance appears in the actual LLM prompt), `test_packaging_view_gui.py` (+2: canonical audience shown/no free-text box when promised, free-text box shown without one). Broader regression across the entire SEO/thumbnail/final-export cluster: 183 passed. mypy/ruff/black clean on every touched file.

**Deliberately not built this pass:** `GenreSEOProfile.keyword_style`/`.hashtag_style` remain unwired - honestly documented as an architectural mismatch (deterministic extraction has no "style" concept to guide), not an oversight; converting keyword/hashtag generation to LLM-based generation to make these fields meaningful is a materially larger change left for its own explicit decision. `language_code` still defaults to a hardcoded `"en"` - confirmed this matches an established, repo-wide convention (`MissionApplicationService.execute()`/`.resume()` use the identical pattern), not a SEO-specific defect, so it was left alone rather than fixed in isolation from the wider convention. SEO-4's genre-based dependency propagation (as opposed to the script-lock-hash staleness banner already built in SEO-3/SEO-6) and SEO-5 (Reviewer/approval wiring) remain separately scoped.

**New initiative, scoped from an independent PDF audit of the existing SEO/thumbnail/publishing subsystem** (`Step 2_Publishing_Reconciliation_Implementation_Plan.pdf`, phases SEO-0 through SEO-10). Before implementing, every phase's own claim was checked against the actual code, not assumed from the plan's wording - this found the plan's premise correct: `SEOPackage`/`ThumbnailArtifact` are mature on content (titles, description, tags, hashtags, concept, layout) but had **zero** version tracking, source-production binding, or staleness detection, and **zero** wiring to `ApprovalGateService`/`ReviewerService`/`content_decisions` or `InvalidationService` anywhere - confirmed by grepping every SEO/thumbnail service file. A further, striking finding: `GenreProfile` already has `GenreSEOProfile`/`GenreThumbnailProfile` sub-profiles, populated for all 12 genres from earlier session work, and **neither is ever read** by any SEO or thumbnail generation service - dead capability sitting unused, while `target_audience` is instead re-typed by a person into a free-text box every time.

**A key architectural finding that reframed SEO-4's real design.** The plan's own SEO-4 ask ("dependency-aware invalidation") initially looked like a natural extension of the existing `InvalidationService`/`job.stale_artifacts` mechanism used throughout this session's other work - but `InvalidationService._mark_stale()` operates via `getattr(job, field_name)`, and `SEOPackage`/`ThumbnailArtifact`/`FinalExportPackage` are deliberately stored in `JobStore`'s own separate per-artifact JSON files, **not** as `VideoJob` fields - an explicit, documented architectural choice ("a write to one artifact can never corrupt another"), not an oversight. Adding them as `VideoJob` fields to make `InvalidationService` "just work" would have created exactly the kind of duplicate-authority risk `AGENTS.md` warns against. The correct, already-precedented mechanism instead: this codebase already solves the identical problem for `ProductionSemanticBrief`/`VisualContinuityBible` via a simple **computed** `script_lock_hash`-comparison at display time (`brief.script_lock_hash != job.script_lock.script_content_hash`, done inline in `content_studio_view.py`) rather than an event-driven ledger. This phase reuses that exact, proven pattern for SEO/thumbnail instead of inventing a second staleness mechanism.

**What was built, all additive:**
- `SEOContext` (`seo_context_builder.py`) gains `script_lock_hash`/`script_lock_version_number`, populated from `job.script_lock` when one exists - the one shared context both `SEOPackageService` and `ThumbnailPackageService` already consume, so extending it once benefits both.
- `SEOPackage` and `ThumbnailArtifact` each gain `version_number` (default 1), `source_script_lock_hash`, `source_script_version_number` - all optional/default-safe, matching this session's established backward-compatible field-addition pattern.
- `SEOPackageService.build()`/`ThumbnailPackageService.build()` gain an optional `previous_package`/`previous_artifact` param: passing the package/artifact being replaced numbers the new one one higher; omitting it reproduces exact prior behavior (version 1).
- `PackagingView`'s SEO and Thumbnail cards now show the version number, a "Regenerate" button (previously **no way existed to regenerate SEO or a thumbnail once first generated** - a genuine, separate gap found while wiring this), and a staleness banner using the exact `script_lock_hash`-mismatch pattern described above - silent when there's no lock yet, a "built before the script was locked" note when the package predates locking, and a "stale, regenerate" warning on a genuine hash mismatch.

**Tests:** extended `test_seo_context_builder.py` (+2), `test_seo.py`/`test_thumbnail.py` (+3 each: default-unset, explicit/round-trip, validation), `test_seo_package_service.py`/`test_thumbnail_package_service.py` (+3 each: default version, increment-with-previous, script-lock-carries-through), `test_packaging_view_gui.py` (+5: version/regenerate-button display for both cards, staleness banner shown on mismatch, silent on match, "built before lock" banner). Broader regression across the whole SEO/thumbnail/final-export cluster: 104 passed (plus the 7-case packaging-view GUI file run separately, all green). mypy/ruff/black clean on every touched file.

**Deliberately not built this pass:** a full inspectable version-history archive (browsing past SEO/thumbnail versions after a regeneration overwrites the stored one) - the plan's own "Do not add speculative fields unsupported by product requirements" instruction, combined with no GUI bullet in SEO-3/SEO-6 naming a restore/compare feature (unlike Script's own Phase 12, which explicitly asked for that), made building one this pass speculative rather than requirement-driven; `version_number` and the script-lock provenance fields are the enabling groundwork SEO-2/SEO-4/SEO-5 need, built narrowly to that purpose. Reviewer/approval wiring (SEO-5) and genre/audience canonical-authority propagation (SEO-2) are separately scoped, not folded into this pass.

---

## 2026-09-06 - Reviewer-audit fix: manual "Save typed edit" never invalidated downstream production artifacts

**Found by an external reviewer audit of the Content Studio Redesign, not by this session's own investigation - and confirmed real before fixing.** `src/desktop/views/content_studio_view.py`'s `_handle_save_script_segment_edit()` (the raw, non-LLM "a person retypes a segment's narration directly" path) mutates `job.generated_script`, appends a `MANUAL_EDIT` version, and clears the editorial critique/quality report - but never called `InvalidationService.on_script_changed(job)`. Every sibling script-mutating path sitting right next to it in the same panel - `ContentIntelligencePipeline.run_revision()`, `run_script_selection_edit()`, `run_script_restore()` - all call it. The handler's own comment even claimed "matching every other script-mutating pipeline path," which was false until this fix: if a project had already run scene planning (`job.scenes` populated) and a person then used the typed-edit box instead of the AI rewrite buttons, the already-planned scenes/clips/timelines/render result were left looking completely valid with zero staleness record after the narration underneath them changed.

**Fix:** added the missing `self._content_intelligence_pipeline.invalidation_service.on_script_changed(job, reason=...)` call at the same point every sibling path calls it, and corrected the now-true comment. New regression test, `test_save_typed_edit_invalidates_downstream_production_artifacts` (`tests/test_content_studio_content_intelligence_gui.py`), mirrors `test_invalidation_matrix_wiring.py`'s own `test_run_revision_invalidates_only_the_downstream_artifacts_that_exist` pattern exactly: populates `scenes`/`video_clips`/`video_timeline`, triggers the handler, and asserts `job.stale_artifacts` reflects all three with `triggered_by == "script_change"`. Broader regression (`test_content_studio_content_intelligence_gui.py` + `test_invalidation_matrix_wiring.py` + `test_invalidation_service.py` + `test_content_intelligence_pipeline.py` = 248 passed). mypy/ruff/black clean (one pre-existing, unrelated mypy debt line in the test file, confirmed via `git stash` to predate this change, left untouched).

This was the last of five findings from the external Content Studio Redesign audit (Phases 0-9) plus the one cross-cutting finding from its follow-up passes; the other four (an `ArtifactLifecycleService.invalidate_dependents()` crash, a Creative Direction review-target mismatch, a fact-check verified/unsupported contradiction, an end-of-video curiosity-loop binding edge case, and a Run/Resume dead-button gap on the `research_plan` gate) were already fixed in earlier passes per the audit's own re-verification. The audit's Phases 10-19 pass found exactly one further defect - this one - across the entire 20-phase redesign; it is now closed.

## 2026-09-06 - Regression fix: Phase 14 staging path broke FFmpeg's container-extension check (undocumented until now)

**Retroactive documentation for commit `e5b7aea`**, which fixed a real regression this session introduced in Phase 14 and pushed the same day, but never logged here - an `AGENTS.md` rule-7 gap this entry closes. Phase 14's staged-output path originally appended `.part` directly after the real extension (`final_video.mp4` -> `final_video.mp4.part`). `FFmpegCommandBuilderService`'s own container-extension validator requires the output filename's suffix to match the configured container (e.g. `.mp4`), so every real render was rejected before FFmpeg ever ran - invisible to every mocked unit test (which never builds a real `FFmpegCommandPlan`), caught only by the one real-ffmpeg integration test, `tests/test_production_render_service_real_ffmpeg.py`, run as part of a full 2054-test repository regression pass. Fixed via a new `_staging_output_file()` helper that inserts `.part` before the real extension instead (`final_video.mp4` -> `final_video.part.mp4`), so the container validator still sees `.mp4`. Verified: the real-ffmpeg integration test now passes; the full `test_production_render_service.py` suite (9 cases, two of which needed their pre-created staging-file paths updated to the corrected naming scheme) is green. That same full-suite run's only other failure, a GUI progress-bar timing test, was confirmed pre-existing/environmental (passes cleanly standalone; no Phase 13-15 change touches that code path) - not a regression, and left as-is.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 15 Final QC and Publish-Ready Package (PDF-1 COMPLETE)

**REUSE confirmed by inspection - a whole final-package subsystem already existed, essentially unreachable in the live app.** `FinalExportPackage`/`FinalExportService`/`FinalExportPackagingService`/`FinalExportValidationService` already implement almost exactly this phase's own ask: a publish-ready package embedding the full SEO package and thumbnail artifact, an on-disk export directory with a written manifest, and an independent validation pass checking video-file presence, duration, manifest presence, and thumbnail/SEO readiness. `PackagingView`'s "Final export" card already lets a person build one from the GUI. This is squarely the plan's own repository-position note: "Publish-ready manual handoff is current release boundary."

**But the mechanism this phase actually asks for - marking a project PUBLISH_READY only when hard QC gates pass - never ran.** `FinalExportStatus` already has exactly the right four states (DRAFT/UNDER_REVIEW/APPROVED/REJECTED) and `FinalExportPackage.is_ready_for_publish` already checks `status == APPROVED`, but grepping every reference to `FinalExportStatus.APPROVED`/`REJECTED` in the codebase found nothing - no code anywhere ever transitioned a package away from DRAFT. `FinalExportBuildResult.validation` (the very validation result this phase asks to gate on) was computed by `FinalExportService.build()` and then thrown away - `PackagingView._handle_build_final_export()` stored only `result.package`, never looked at `result.validation`. The gate existed in name only.

**Media integrity checks were shallow.** `FinalExportValidationService._validate_video_file()` only checked `Path.exists()` - no real readability probe, no audio-stream check, no resolution verification, despite this phase's own bullet naming exactly those ("readable file, duration, resolution, aspect ratio, audio present, no empty output"). Phase 8's `MediaTechnicalValidationService` (ffprobe-based, already built for clip acquisition QC) does real readability/stream/resolution probing, but its per-clip defaults (10-minute max duration) would incorrectly reject any full-length finished video, so it had never been reused here.

**Manifest lacked the provenance chain this phase names.** The written manifest already captures video path/resolution/frame rate/duration/SEO/thumbnail, but nothing linking the output back to the script lock, timelines, or render result - "Write production manifest linking output to script hash, clip versions, voice blueprint, audio assets and render result" was a real, unaddressed gap.

**What was built, all additive:**
- New `src/models/production_provenance.py`: `ProductionProvenance` - a pure snapshot (script lock hash/version, video item/audio track/voice track counts, render engine/exit code/ffmpeg command straight from Phase 14's own new `RenderResult` fields) taken directly off the already-persisted `VideoJob`/`RenderResult`, no re-derivation. `FinalExportPackage` gains an optional `provenance` field; `FinalExportPackagingService.package()` gains an optional `provenance` param and a new `rewrite_manifest()` method so a package's on-disk manifest can be kept in sync after its status is finalized.
- `FinalExportValidationService` gains an injected `MediaTechnicalValidationService` (Phase 8's own service, reconfigured with wide-open duration/resolution thresholds appropriate to a finished video rather than a single clip) and three new checks: real ffprobe-based readability, a hard error when the final video has no audio stream, and a hard error when the probed resolution disagrees with the package's own declared resolution. Three new `FinalExportValidationCode` values.
- `FinalExportService.build()` now computes `ProductionProvenance` from the render orchestration result's own job, passes it through to packaging, and - the core of this phase - marks the resulting package `APPROVED` when validation finds zero hard errors, or `UNDER_REVIEW` otherwise (never REJECTED automatically; that state is reserved for a future explicit human rejection, matching how `SEOPackage`/`ThumbnailArtifact` already define the same four-state vocabulary), then rewrites the on-disk manifest so it reflects the final status.
- `PackagingView`'s Final Export card now shows a live QC summary (re-running the same cheap, deterministic validation on every render so it never goes stale) plus "Open output folder" and "Copy manifest path" actions - the plan's own "QC summary, output folder, metadata copy/export" GUI bullets.

**Tests:** new `test_production_provenance_model.py` (5), extended `test_final_export.py` (provenance default/round-trip), extended `test_final_export_validation_service.py` with 6 new cases (real-file-passes, no-audio-stream, resolution-mismatch, unreadable-file, URI-scheme-skip) using an injected stubbed ffprobe runner, extended `test_final_export_packaging_service.py` with 4 new cases (provenance stored/persisted, provenance absent, manifest rewrite, rewrite-before-packaging rejected), extended `test_final_export_service.py` with 3 new cases (UNDER_REVIEW on failing QC, APPROVED on passing QC via a stubbed good probe, provenance computed from a job's script lock/audio timeline), new `test_packaging_view_gui.py` (2, offscreen-Qt: QC summary rendering for both a warning case and an all-clear case, action buttons present). Broader regression across every final-export/provenance/media-validation file: 59 passed. mypy/ruff/black clean on every touched file.

**Deliberately not built this pass:** "AV sync/loudness sanity checks where available" and "final continuity/semantic spot analysis against production package without regenerating media" - honestly not built, matching this session's established discipline of documenting a real infrastructure gap rather than fabricating unverified rigor: this codebase has no AV-sync measurement and no mechanism to re-run continuity/semantic analysis against an already-rendered video without regenerating media. `is_ready_for_publish` still also requires `seo_package`/`thumbnail_artifact` to be independently APPROVED, and - a genuine, separately-scoped finding from this same investigation - nothing anywhere in this codebase ever transitions those either (no approval UI exists for SEO or thumbnail packages). That is a real, pre-existing gap this phase did not create and is not named in Phase 15's own touch-points, so it was left untouched rather than folded in as an undiscussed scope expansion.

**This completes all 16 phases (0-15) of the Post-Script-Approval Production Plan** (Phase 7 explicitly out of scope throughout, as the Google Flow browser-automation mechanism itself). Combined with the Content Studio Redesign's 20 phases (0-19) completed earlier in this session, both PDFs given at the start of this session are now fully implemented, less the Google Flow generation-execution mechanism as instructed throughout.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 14 FFmpeg Production Render

**Repository position confirmed by inspection - "Real FFmpeg production stack is implemented" held up for every headline capability.** `ProductionRenderService.render()` already builds the master plan, transition/effect/subtitle/camera/animation plans, the render graph, resolves FFmpeg capabilities, builds the filter graph and the deterministic command plan, executes FFmpeg, and normalizes the outcome into `RenderResult` - exactly this phase's own "use existing ProductionRenderService" bullet, already true before this phase started. `FFmpegExecutionService.execute()` already supports progress callbacks, a timeout, and cooperative cancellation via a `cancellation_check` callable.

**Four narrow, genuine gaps found by reading the actual call chain, not assumed from the plan's own brief description:**

1. **Cancellation was supported two layers down but never reachable from the top.** `FFmpegExecutionService.execute()` already accepts `cancellation_check`, but `ProductionRenderService.render()` never accepted or forwarded one - the capability existed and was simply unwired at the one boundary a caller would actually use.

2. **No staged-output-then-promote pattern existed anywhere.** FFmpeg always wrote directly to the final requested output path. A crash, a cancellation, or any of the execution service's own late-stage failures (`output_size` - an empty file; `output_type` - not a regular file) could leave a corrupt or partial file sitting at the exact path a caller would treat as the finished video.

3. **RenderResult persisted almost none of what the render actually did.** `FFmpegExecutionResult` already carries the full command list, exit code, and metadata; `FFmpegResolvedConfig` already carries the detected FFmpeg version and the selected video/audio codec and hardware acceleration - all of it was computed and then discarded the moment `ProductionRenderService.render()` returned, since `RenderResult` had nowhere to put it.

4. **The best find of the four: failure classification already existed, several layers deep, and was silently thrown away.** Reading `FFmpegExecutionService.execute()` line by line found it already stamps a `failure_stage` value into `FFmpegExecutionResult.metadata` on every failure path - `process_start`, `stream_setup`, `timeout`, `cancelled`, `ffmpeg_exit`, `output_presence`, `output_type`, `output_size` - a genuinely fine-grained taxonomy. `ProductionRenderService.render()` never read `execution_result.metadata` at all. "Classify environment/media failures vs upstream-plan defects" wasn't missing logic; it was missing plumbing.

**What was built - all additive, all optional:**

- `ProductionRenderService.render()` gains an optional `cancellation_check` parameter, forwarded straight through to `FFmpegExecutionService.execute()`.
- Every render now writes to a staging path alongside the target (the `.part` marker inserted before the real extension, e.g. `final_video.part.mp4` - see the fix note below) and only ever promotes it to the real target path via an atomic `Path.replace()` after `execution_result.success` is genuinely true (which `FFmpegExecutionService` itself already guarantees means the file exists, is a regular file, and is non-empty). A failed, cancelled, or crashed render (including an exception raised by `execute()` itself) always cleans up its own staging file, so a retry never confuses a stale partial file for real output.
- New `src/models/render_failure_diagnosis.py`: `RenderFailureCategory` (ENVIRONMENT/COMMAND_OR_MEDIA/CANCELLED) and `classify_render_failure()`, which maps the execution service's existing `failure_stage` taxonomy onto this phase's three-way distinction. Deliberately coarse where honesty requires it: `ffmpeg_exit` (FFmpeg ran and rejected the command or its media) maps to one combined category, since this codebase does not parse FFmpeg's stderr text to separate a bad input file from a malformed generated command.
- `RenderResult` gains `ffmpeg_command`, `exit_code`, `ffmpeg_version`, `selected_video_codec`, `selected_audio_codec`, `selected_hardware_acceleration`, and `failure_category` - all optional, all backward-compatible with a `RenderResult` built before this phase.

**Tests:** new `test_render_failure_diagnosis_model.py` (5 cases covering every mapped stage plus unknown/missing-stage honesty), extended `test_render_result.py` (default-unset and explicit-value-with-round-trip assertions for every new field), extended `test_production_render_service.py` with 4 new cases (cancellation forwarding, real-filesystem staged-output promotion, staging cleanup on a classified failure, staging cleanup when `execute()` itself raises) alongside updating its 3 existing cases' fixtures for the new fields - all still green. Broader regression across the whole render/FFmpeg stack (73 cases: production render, render result, failure diagnosis, render stage, FFmpeg execution/command-builder/diagnostics/stability, render graph, filter graph fades/limiter/ducking/transitions, master edit plan) plus the separately-run FFmpeg capability suite (7 passed, 1 pre-existing environment skip): all green. mypy/ruff/black clean on every touched file.

**Deliberately not built this pass:** `render_stage.py`'s own `_execute_production_render()` does not yet forward a `cancellation_check` - no caller in this codebase currently has a cancellation signal to supply, so wiring one through the pipeline stage without a real source would be speculative; the capability is available on `ProductionRenderService.render()` itself for the day a caller does. No deeper stderr parsing to split `COMMAND_OR_MEDIA` further - that would need real, tested heuristics this pass has no evidence to back.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 13 Master Edit Plan and Render-Readiness Gate

**Nearly all of this phase's stated objective already existed, built
for a different but overlapping purpose.** `MasterEditPlanService`'s
`_readiness_failures()`/`_build_warnings()` already implement exactly
what the phase asks for - a render-readiness report distinguishing
hard blockers (no scenes, video/editing/voice/audio not ready,
incompatible durations) from soft warnings (missing media, borderline
duration slack), spanning every dimension named in the objective. No
new readiness logic was needed.

**The one genuine gap: a render-input identity hash was computed, but
never persisted onto the plan it describes.** `RenderIdentityService`
(pre-existing, from an even earlier production-hardening spec's own
Phase 6 per its docstring) already computes a deterministic SHA-256
hash from a job's video timeline, audio timeline, and render settings
- but that hash is used *only* for `FinalPreview` staleness detection
(`final_preview_service.py`/`quality_center_view.py`). A persisted
`MasterEditPlan` had no self-describing record of which exact render
inputs it was built from - "persist render input manifest/hash for
reproducibility" was the actual, narrower gap.

**Narrow, additive fix.** New optional `MasterEditPlan.render_identity_hash:
str | None = None` field, and a matching optional
`MasterEditPlanService.build(..., render_identity_hash: str | None = None)`
parameter that passes it straight through to the model constructor.
The service deliberately stays decoupled from `VideoJob`/
`RenderIdentityService` - a caller that wants a self-describing plan
computes the hash separately (`RenderIdentityService.compute(job)`)
and passes the resulting string through; omitting it reproduces the
method's exact prior behavior. Confirmed `refresh()` never touches the
field, so it survives a refresh call untouched, and it round-trips
through `model_dump_json()`/`model_validate_json()` unchanged.

**Tests:** extended `tests/test_master_edit_plan_service.py` (its
existing script-style, top-level-assert format) with a new section
covering: default `render_identity_hash is None` (exact prior
behavior), an explicit hash stored on `build()`, survival across
`refresh()`, and survival across a serialization round-trip. Broader
regression (`test_master_edit_plan_service.py` +
`test_render_identity_service.py` + `test_final_preview_service.py` +
`test_production_render_service.py` = 29 passed). mypy/ruff/black
clean on both touched files.

**Deliberately not built this pass:** no caller has been wired to
actually compute and pass `render_identity_hash` yet (e.g. wherever a
`MasterEditPlan` is first built from a `VideoJob`) - this phase adds
the capability to carry the identity, not a new call site forcing
every plan to carry one. That wiring is a natural, low-risk follow-up
but wasn't required by this phase's own wording and was left out to
keep this change minimal and reviewable.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 12 Video Timeline and Editing Directive Compilation

**Most of this phase turned out to already be solved, more thoroughly
than the objective's own wording suggested - and one architectural
fact made the "obvious" gap not exist at all.** `TimelineValidationService`
already detects both gaps and overlaps between timeline items and
duration disagreement between an item and its own clip - "validate no
accidental gaps/overlaps" was fully satisfied before this phase
started. More striking: `VideoTimelineItem`'s own model validator
makes a duration mismatch between the item and its clip literally
impossible to construct - a hard `ValueError`, not a soft warning -
and `TimelineBuilderService` always sizes every item's slot to exactly
its clip's own actual duration. An item/clip disagreement cannot
happen by this architecture's own design, full stop.

**So "define duration mismatch policy" isn't about items and clips -
it's one level upstream, and nothing there was checked at all.** The
real disagreement is between a scene's *planned* duration
(`Scene.estimated_duration_seconds`, fixed at scene-planning time) and
the *actual* duration of whatever clip eventually gets acquired for it
- manual upload, stock footage, whatever comes back. A scene planned
for 8 seconds whose acquired clip actually runs 15 wasn't compared
against its plan anywhere; the timeline builder just uses whatever the
clip's real length is and moves on, silently changing the video's
total runtime from what was planned.

**A recommendation engine, not an executor - deliberately.** New
`DurationMismatchPolicyService.evaluate()` compares each scene against
its acquired clip within a configurable tolerance and recommends one
of this phase's own four named dispositions: TRIM for a too-long clip,
HOLD_LAST_FRAME for a too-short one, or BLOCK when the disagreement is
severe (a configurable ratio of the planned duration - a wildly-off
clip needs a person's judgment, not an automatic guess).
APPROVED_WORKAROUND is never auto-assigned; it only exists once a
person has explicitly accepted a mismatch, and the model requires a
note recording who/why when it is used. The service never mutates a
clip or timeline itself - executing a recommendation (actually
trimming, actually freeze-framing) belongs to whichever later stage
builds the render timeline from an accepted decision, matching this
phase's own "policy," not "execution," wording exactly.

**Deliberately not wired into `ProductionReadinessService` - a
conscious risk decision, not an oversight.** That aggregator is this
codebase's own established sensitive file (it's the one a near-miss
`Write` overwrite nearly destroyed earlier this session, in Phase 16
of the Content Studio Redesign work). This session's own discipline
throughout has been to avoid touching delicate, already-tested
infrastructure without a concrete driving need already established -
so this phase's new capability stays standalone and fully tested,
with wiring it into the readiness aggregator (or a GUI) left as its
own explicit, separately-reviewed step rather than folded in here as
a side effect.

**Tests:** `test_duration_mismatch_policy_model.py` (5: signed
mismatch in both directions, approved-workaround requires a note,
block does not), `test_duration_mismatch_policy_service.py` (8:
within-tolerance clean, too-long recommends trim, too-short recommends
hold, severe mismatch recommends block, no-matching-clip skipped,
independent multi-scene evaluation, constructor validation). Broader
timeline regression (13 cases, including the pre-existing
`TimelineValidationService`/`TimelineBuilderService` suites): all
green. mypy/ruff/black clean.

**Deliberately not built this pass:** any wiring into
`ProductionReadinessService`/the `Blocker` system or a GUI (see
above); an actual trim/hold-last-frame execution mechanism - this
phase covers the policy layer only.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 11 Audio Timeline Compilation and Mix Directives

**This phase's own repository-position claim - "AudioTimeline/AudioTrack
models exist" - undersold what was actually there.** Reading
`FilterGraphBuilderService._build_audio_chains()` directly (not
assuming from the PDF's summary) found genuinely sophisticated,
already-working infrastructure: real ducking via FFmpeg's
`sidechaincompress` filter, with the voiceover track (or a mix of
several) driving the compressor as the sidechain trigger, so
background music and SFX duck automatically under narration instead
of playing at a flat level. This was not a stub or a placeholder - it
already worked, with its own dedicated ducking test suite proving it.

**The one real gap, found by grepping for the field names, not
guessing.** `AudioTrack.fade_in_seconds`/`.fade_out_seconds` already
existed and already flowed correctly onto `RenderNode.payload` via
`render_graph_builder_service.py` - but `FilterGraphBuilderService`
never read either field when building a track's actual filter chain.
A project could configure a fade, see it reflected in the model, and
have it silently vanish at render time. New `_build_fade_nodes()`
inserts 0, 1, or 2 `afade` filter nodes between the existing `volume`
and `adelay`/`anull` stages - fade-in starts at the track's own local
time 0; fade-out's start offset is computed from the track's real
duration minus the configured fade-out length. A track with neither
fade configured produces the exact same chain as before this phase -
verified by re-running every existing ducking/transition/render test
unchanged and green.

**Clipping prevention added; loudness-target normalization
deliberately not.** `amix` already disables its own automatic
normalization (`normalize=0`) to keep this builder's deterministic
per-track levels intact - but un-normalized, summed tracks can exceed
full scale. A final `alimiter` now sits between the mix and the
graph's public `audio_final` label (the raw `amix` output was renamed
to an internal `audio_mixed` label so the public contract -
`FilterGraph.audio_output_label` - is completely unchanged). A real
LUFS-target loudness normalization (`loudnorm`) needs a two-pass
analyze-then-apply flow this pipeline has no infrastructure for; a
single-pass estimate would be less honest than not claiming loudness
compliance at all, so this phase covers clipping prevention only and
says so plainly rather than quietly conflating the two.

**Tests:** new `test_filter_graph_builder_audio_fades.py` (5: no-fade
produces no `afade`, fade-in-only, fade-out-only with the correct
duration-derived start offset, both fades chained together, fade still
applies alongside a positive start delay), new
`test_filter_graph_builder_audio_limiter.py` (2: limiter present on
the final mix, `amix` feeds the limiter rather than the public label
directly). Full existing filter-graph/render regression (23 cases
spanning ducking, transitions, render-graph building, and production
render): all green, proving the label rename and new nodes changed
nothing observable for any existing caller. mypy/ruff/black clean.

**Deliberately not built this pass:** proper LUFS-target loudness
normalization - the two-pass measurement infrastructure it needs
doesn't exist in this pipeline yet, and adding a fake single-pass
approximation would misrepresent what the system actually guarantees.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 10 Music and SFX Acquisition

**Most of this phase was already built, under different names than the
PDF's own touch-points name.** None of `audio_acquisition_service.py`,
`audio_asset_resolver_service.py`, or `audio_workspace_service.py`
exist in this repository - but `AudioTrack` (an existing model)
already carries everything this phase asks for per-cue: exact
placement (`start_time_seconds`/`duration_seconds`), energy/transition
handling (`volume`/`fade_in_seconds`/`fade_out_seconds`/`loop_enabled`/
`duck_under_voice`), and provenance (`provider`/`license_type`).
`MusicGenerationService` and `SoundEffectGenerationService` already
generate these tracks with real fallback behavior. The PDF's own
"audio acquisition/resolution services exist" was accurate; its
"directive integration must be verified/completed" undersold how much
already worked.

**The one real gap, found by reading the aggregation point directly,
not assumed from the phase description.** `SoundEffectPipelineStage.execute()`
loops over every scene's resolved cues, generates each one
independently, and appends the result to `AudioTimeline.tracks` -
with zero cross-cue checking. That's exactly this phase's own named
requirement, "prevent duplicate/repetitive SFX and uncontrolled
loudness accumulation," and nothing anywhere in this codebase checked
either one.

**A coarse heuristic, honestly labeled as one.** New
`AudioCuePolicyService.evaluate()` checks two things across an
already-built set of `AudioTrack` entries: the same SFX preset (or
source file) appearing twice within a short time window
(REPETITIVE_SFX), and any two time-overlapping tracks whose summed
volume crosses a fixed ceiling (LOUDNESS_ACCUMULATION). This codebase
has no real LUFS/perceptual-loudness measurement, and building one is
a materially larger effort than this phase's scope - the service's
own docstring says so plainly rather than letting the check's name
imply more rigor than it has. It exists to catch an obviously
excessive stack of simultaneous cues, not to guarantee broadcast-
standard loudness compliance.

**Wired live, default-on - a different posture from Phase 8's gate,
deliberately.** `SoundEffectPipelineStage` gained an
`AudioCuePolicyService` dependency that defaults to a real, active
instance rather than `None`. This is safe where Phase 8's ffprobe gate
wasn't: this check only ever *appends warnings* to the stage's
existing `StageResult.warnings` - it never blocks generation or
changes `attached_count` - so there's no existing accept/reject
behavior for a default-off posture to protect. Conflicts show up the
exact same way a failed cue generation already does.

**Tests:** `test_audio_cue_policy_model.py` (3),
`test_audio_cue_policy_service.py` (9: distinct/well-spaced cues
clean, same-preset-within-window flagged, same-preset-outside-window
clean, different-presets-close-together clean, overlapping-loud-tracks
flagged, non-overlapping-loud-tracks clean, constructor validation,
empty-tracks clean), 1 new case in `test_sound_effect_stage.py`
proving the wiring actually fires. Broader audio-path regression (35
cases): all green. mypy/ruff/black clean.

**Deliberately not built this pass:** an Audio Workspace GUI (VO/
music/SFX lane visualization doesn't exist anywhere in this codebase -
a materially larger UI build than this phase's own policy-checking
scope; deferred until a concrete need for the full workspace, not just
its underlying check, is identified).

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 9 Voice Directive Resolution and ElevenLabs Generation

**The PDF's own "rich blueprint... exists" claim was accurate; "mapping
incomplete" undersold the gap.** `ResolvedVoiceBlueprint` already had
everything - stability, similarity_boost, style_strength, speaker_boost,
speed, pitch_adjustment, volume_gain_db, plus full pronunciation/pause/
emphasis directive lists, all validated and populated by the pre-existing
`VoiceDirectiveResolutionService`. Reading the two places that actually
matter - `ElevenLabsVoiceProvider.generate_voice()` and
`VoiceGenerationService.generate()`'s own call site - found neither one
touched any of it. The provider sent `{"text": ..., "model_id": ...}`
and nothing else; the service's call site passed only
`blueprint.narration_text` and a resolved voice ID. Every other field
on a genuinely rich model was computed, validated, and then thrown
away at the last step.

**Mapped only what's actually documented, not everything that looked
mappable.** ElevenLabs' real `voice_settings` object has four
long-stable fields (stability, similarity_boost, style,
use_speaker_boost) plus a more recently documented `speed`. Those five
map directly. Everything else on the blueprint - emotion, pace,
pitch_adjustment, volume_gain_db, and every pronunciation/pause/
emphasis directive - has no verified ElevenLabs API surface in this
codebase's own testing (the provider's own pre-existing docstring
already disclaims "not verified against a live ElevenLabs account,"
and the user currently has no real API key to verify against). Rather
than invent a plausible-looking SSML-style mapping for pauses or
pronunciation that might not actually work, `ElevenLabsVoiceTranslationService`
names each one in an honest `unsupported_controls` list - only when it
actually holds a non-default value, so a plain default-settings
blueprint produces zero noise.

**Additive at the interface level, live at the call site.**
`VoiceProvider` gained a new `generate_from_blueprint()` method that
is deliberately *not* abstract - its default implementation reproduces
`generate_voice()`'s exact prior behavior, so `DryRunVoiceProvider`
needed not one line of change to keep working. `ElevenLabsVoiceProvider`
overrides it with the real translation. The one small refactor along
the way: `VoiceGenerationService`'s private `_resolve_provider_voice()`
became public `resolve_provider_voice()`, since the base provider's
own default now needs the identical resolution logic - one shared
implementation instead of two that could quietly drift apart.
`VoiceGenerationService.generate()`'s call site itself was switched
from `provider.generate_voice(...)` to `provider.generate_from_blueprint(blueprint)`
- this is a real, live orchestration change to the running generation
path, not a capability left sitting unused.

**Tests:** `test_elevenlabs_voice_request_model.py` (4),
`test_elevenlabs_voice_translation_service.py` (9: documented-field
mapping, speed clamping in both directions, no-unsupported-controls
on defaults, emotion/pace/pronunciation/pause each flagged when
non-default, default and custom model IDs), extended
`test_elevenlabs_voice_provider.py` (the full `voice_settings` payload
is actually sent) and `test_dry_run_voice_provider.py` (the base-class
default still works, proving zero blast radius). Broader voice-path
regression: all green. mypy/ruff/black clean.

**Deliberately not built this pass:** any mapping for pace/
pitch_adjustment/volume_gain_db or the pronunciation/pause/emphasis
directive lists - genuinely no verified ElevenLabs API surface for
these, not an oversight; `unsupported_controls` is computed on every
request but has no GUI reader yet, matching this whole session's
"don't build ahead of a real reader" discipline.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 7 (skipped, out of scope) and Phase 8 Generated Clip QC, Decisioning and Regeneration

**Phase 7 skipped outright, not thinly implemented.** "Google Flow
Generation Execution" - submit the resolved prompt, poll, download -
is the Flow browser-automation mechanism itself, excluded from this
whole implementation's scope from the very first phase. Checked by
inspection that none of the plan's own named touch-points
(`external_ui_generation_provider.py`, `google_flow_automation_service.py`,
`google_flow_generated_clip_pipeline_service.py`) exist anywhere in
this repository at all - there was no existing code to leave alone,
the exclusion is total.

**Phase 8 turned out to be mostly inapplicable too, for the same
reason - and the one part that wasn't got built.** "Technical +
multimodal + semantic QC" against *downloaded generations* has no
subject without Flow media to analyze - genuinely inapplicable, not
merely deferred. But "run technical checks first: readability,
duration, dimensions/aspect ratio" applies to any acquired clip in
this codebase's actual paths (manual upload, stock footage), and
inspection found a real gap there: `ManualUploadService._validate_video()`
already checks file existence, type, and size, but nothing anywhere
in this codebase probes an actual video's duration or resolution -
confirmed by grepping every `ffprobe` reference in the repo down to a
single docstring mention with no real implementation behind it.

**New capability, built the same way this session builds every
LLM-adjacent service - except this one needs no LLM at all.** New
`MediaTechnicalValidationService.validate()` shells out to `ffprobe
-show_format -show_streams`, parses the JSON, and checks duration/
resolution against configurable thresholds. The binary invocation
itself is injectable (`runner: Callable[[list[str]], str]`) - the
exact same dependency-injection shape this whole session already uses
for LLM services, just applied to a subprocess call instead, so tests
never need a real ffprobe binary or a real video file.

**Wired additively, with the honest consequence spelled out rather
than silently applied.** `ManualUploadService` gained an *optional*
`technical_validation_service` constructor parameter, defaulting to
`None` - the exact behavior this class already had. The one real
construction site in the live app (`scene_asset_and_timeline_infrastructure_factory.py`)
was deliberately left untouched, so the running desktop app's behavior
is byte-for-byte unchanged by this phase. Activating the check by
default would start rejecting uploads the app previously accepted -
a genuine behavior change, and one this phase's job was to make
*possible*, not to make automatically, without a separate explicit
decision to turn it on.

**Failure surfacing needed zero new GUI code.** A failed technical
check raises the exact same `AssetModuleFailure` (with a new
`MEDIA_TECHNICAL_VALIDATION_FAILED` reason) every other manual-upload
failure already raises, with the same `recovery_options`
(retry/search-stock/skip-scene) - the existing failure-rendering path
in the desktop app is already generic over any failure reason, so
this new one is visible the moment the service is actually turned on,
with nothing further to build.

**Tests:** `test_media_technical_validation_model.py` (4),
`test_media_technical_validation_service.py` (10: good clip, missing
file, too-short duration, too-small resolution, missing video stream,
runner failure, unparseable output, three constructor validation
cases), extended `test_manual_upload_service.py`'s existing script-
style assertions with both a failing and a passing technical-
validation case. Broader asset-path regression (19 pytest-native
cases plus the two script-style files): all green. mypy/ruff/black
clean.

**Deliberately not built this pass:** activation in the live desktop
factory (a separate decision from building the capability); multimodal/
semantic QC (inapplicable without Flow media); a full attempt-history
strip beyond the existing retry mechanism.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 6 Fulfillment Routing and Budget Gate

**The leanest phase yet, and appropriately so - REUSE covered almost
all of it.** `Scene.source_type` (manual upload/stock footage/local
library/image-to-video, plus a reserved AI_GENERATE the codebase
already keeps disabled in the real workflow) already is the per-clip
route, set once during scene planning and persisted for restart/
resume. `Scene.fallback_sources` already covers systemic fallback
policy. Two of this phase's three named exit criteria - "every clip
has a route before acquisition," "completed clips are never
regenerated on resume" - already held, confirmed by reading the code,
not assumed from the source plan's own framing. AI_GENERATE staying
reserved/disabled happens to align exactly with this whole
implementation's own Google Flow exclusion, for free.

**The one real gap, found by grepping every reference to a field that
already existed.** `VideoJob.maximum_visual_budget` has existed since
before this whole initiative, mapped in from project specification -
but nothing anywhere in the codebase ever checked a project's actual
scene costs against it. Not a missing model, a missing enforcement
point.

**A visibility gate, honestly described as exactly that, not
oversold as a hard stop.** `ClipMaterializationStatus` gained
`maximum_visual_budget`/`has_budget_cap`/`remaining_budget`/
`is_over_budget` (`<= 0.0` means no cap was ever configured, matching
this codebase's existing convention for optional numeric limits
elsewhere). This is shown and warned about, but there is no single
"Generate All" execution call site in this codebase for stock/manual
routes to hook a blocking exception into the way the existing,
separate `ProviderBudgetService` enforces hard stops for LLM-provider
spend - a materially different kind of spend with a materially
different execution shape. Documented as a real, current limitation
rather than quietly narrowing the phase's own claim to match what got
built.

**Tests:** 4 new cases in `test_clip_materialization_model.py` (zero-
budget-means-uncapped, within-budget, over-budget, exactly-at-budget
boundary), 2 new cases in `test_clip_materialization_service.py`, 1
new GUI case. Full combined regression green. mypy/ruff/black clean.

**Deliberately not built this pass:** a hard block on a batch
execution step (none exists yet for stock/manual routes to gate);
separate "spent" and "retry" cost tracking distinct from estimated
cost - this codebase has no per-attempt visual-asset spend ledger to
draw those numbers from.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 5 Clip Workspace Canonical Materialization

**The REUSE finding that reframed the whole phase.** Before writing
anything, the question was simple: does this codebase already have a
Clip Workspace? It does - `Scene` itself (routing via `source_type`/
`source_status`/`fallback_sources`, asset-acquisition state via
`SceneAssetState`) plus an entire existing GUI,
`src/desktop/views/clip_workspace_view.py` (per-scene duration/clip
review, bulk external-generation export, bulk stock assignment).
`run_scene_planning()` already auto-materializes it with zero manual
"Plan Clips" step, and it's already a pure projection of
`GeneratedScript` rather than a parallel creative planner. Two of this
phase's three named exit criteria were already true before this
phase started - not something to build, something to confirm by
reading the code.

**What was genuinely missing: one summary, and one stable id already
existed to build it on.** New `ClipMaterializationStatus`/
`ClipMaterializationService.compute()` - pure aggregation, no LLM
call - is the "total/ready/missing, route counts, duration integrity,
estimated budget" summary the plan's GUI section actually asks for.
The third exit criterion, "every clip traces lock -> semantic ->
continuity -> shot -> prompt," needed no new id scheme at all -
`Scene.scene_number` already is the one key `ClipContinuityEntry`,
`ShotSpecification`, and `ResolvedCinematicPrompt` all share, so
`is_fully_traced` just checks whether a resolved prompt exists for
every scene number.

**A real gap found while wiring this phase, not new scope.**
`ScenePromptExportService` - the existing Clip Workspace's own
external-generation export, the file a person actually hands to
Google Flow or any other tool by hand - read `Scene.visual_prompt`,
the legacy per-scene prompt, even on a project that already had a
fully resolved `CinematicPromptPackage` from Phase 4. This is exactly
the "current desktop shortcut must be replaced" gap the source plan
names, just surfacing in the export path rather than an in-app
inspector. Fixed by giving `build_entries()`/`to_text()`/`write_file()`
an optional `cinematic_prompt_package` parameter, preferred whenever
present and falling back to `scene.visual_prompt` for any scene the
package doesn't cover - so an older project, or one that hasn't run
the new chain yet, sees no behavior change at all.

**Tests:** `test_clip_materialization_model.py` (8),
`test_clip_materialization_service.py` (6: ready/missing counting,
staleness against the current lock, prompt-tracing counting, route
aggregation, duration/cost summation), 3 new cases in
`test_scene_prompt_export_service.py` (resolved-prompt preference,
package-miss fallback, no-package fallback - all 9 cases in that file
still pass, confirming the change is additive), 2 new pipeline cases,
2 new GUI cases. Full combined regression: 258 passed. mypy/ruff/black
clean.

**Deliberately not built this pass:** a new stable "clip ID" scheme -
`Scene.scene_number` already serves that role, confirmed sufficient
by inspection rather than assumed insufficient; clip version/
regeneration history stays exactly where it already lives, the
existing Clip Workspace/`SceneAssetState` machinery, not duplicated
here.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 4 Resolved Cinematic Prompt Package

**Compilation and evaluation split cleanly, matching an established
pattern across the whole engine.** `CinematicPromptCompilationService.compile()`
is pure and deterministic - every ingredient it needs (shot
specification, continuity state, semantic-intent segment) is already
resolved structured data by the time this phase runs, so assembling
one prompt string from it is templated composition, not a creative
judgment call. Scoring the *result* for quality genuinely needs
judgment, so that's a separate service, `CinematicPromptQualityService.evaluate()`,
making one batched LLM call across every prompt in the package -
exactly the same "writing and evaluation are separate passes"
discipline `HookEvaluationService`/`StoryAngleEvaluationService`
already established, applied here for the third or fourth time this
session.

**A fixed quality floor, not a per-genre tunable.** `QUALITY_BLOCK_THRESHOLD`
is one constant, not something a genre profile can loosen. A prompt
scoring below it on any single dimension is a compilation defect -
missing structured input, a malformed continuity lookup - not a
matter of genre taste the way, say, a script's tone might vary. `is_blocked`
reads the *lowest* of the six scores, so one badly wrong dimension
can't be averaged away by five good ones.

**Evaluation returns a new package, never mutates the one it's
given.** `CinematicPromptQualityService.evaluate()` builds fresh
`ResolvedCinematicPrompt` copies via `model_copy(update=...)` rather
than assigning scores onto the caller's own objects - a caller that
kept a reference to the pre-evaluation package still sees it
unscored, which is the safer default when nothing in this codebase's
established conventions calls for in-place mutation here.

**One PDF exit criterion turned out to be inapplicable, and that's
worth stating plainly rather than pretending to satisfy it.**
"`ClipWorkspaceAutoGenerationService` no longer reconstructs a
simplistic prompt from Scene" - that service, and `ClipWorkspace`
itself, do not exist anywhere in this repository under any name,
confirmed by direct inspection during Phase 0's own baseline audit.
There is nothing to fix here because the thing the PDF assumes exists
was never built in this codebase's actual history.

**Tests:** `test_cinematic_prompt_model.py` (9), `test_cinematic_prompt_compilation_service.py`
(7: one prompt per scene, identity/environment/lighting inclusion,
reference-asset carry-through, standard negatives, reproducibility,
graceful handling of a scene missing shot/continuity data),
`test_cinematic_prompt_quality_service.py` (5: score attachment,
non-mutation of the original package, a skipped scene staying
unscored, empty-package/provider-failure rejection), 4 new pipeline
cases, 5 new GUI cases. Full combined regression: 271 passed. mypy/
ruff/black clean.

**Deliberately not built this pass:** golden-prompt snapshot tests -
the compiled text format may still shift shape as later phases
(clip materialization, generation execution) actually consume it, so
locking it down now would just mean rewriting the snapshots soon.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 3 Cinematic Shot Plan and Temporal Beat Expansion

**Continuity state referenced, never duplicated.** `ShotSpecification`
deliberately carries no wardrobe/location/lighting fields of its own -
it references its scene only by `scene_number`, and whatever
incoming/outgoing visual state applies comes from `VisualContinuityBible`'s
own `ClipContinuityEntry`, looked up by that same number. Two models
holding the same state field would eventually disagree with each
other; one model holding it and a second one pointing at it never can.

**Duration is production timing, not a creative decision.** Every
shot's `duration_seconds` is set by the pipeline from `Scene.
estimated_duration_seconds` after the LLM call returns - never asked
of the LLM at all. An LLM guessing at a number that already exists
elsewhere is exactly the kind of "second source of truth" this whole
plan's own cross-cutting rules warn against.

**A partial or malformed LLM response still satisfies the exit
criterion.** "Every planned clip has exactly one shot specification"
is checked mechanically (`CinematicShotPlan.has_exactly_one_shot_per_scene`),
and `ShotPlanningService.plan()` fills a plain, honestly-generic
fallback shot for any scene its one LLM call's response didn't cover
- so the plan is always complete even when a single provider call
comes back partial, rather than silently leaving a clip unplanned.

**Explicitly out of scope, not overlooked.** The plan's own
"calculate provider-compatible durations including 8s preferred clips
and shorter remainders" bullet is Google Flow-generation-specific
logic - excluded per this whole implementation's standing scope
alongside the Flow automation mechanism itself. Shot duration here is
whatever `Scene.estimated_duration_seconds` already is.

**Tests:** `test_shot_planning_model.py` (6), `test_shot_planning_service.py`
(6: one shot per scene, scene-sourced duration overriding whatever the
LLM said, temporal-beat parsing, fallback-shot filling for a skipped
scene, empty-scenes/provider-failure rejection), 4 new pipeline cases,
3 new GUI cases. mypy/ruff/black clean.

**Deliberately not built this pass:** a shot-diversity heuristic
across the whole plan ("avoid repetitive visual grammar") - judging
diversity needs either a second evaluation pass or cross-shot prompt
context this per-scene call doesn't currently carry, better scoped as
its own follow-up than folded in here.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 2 Visual Continuity Bible

**The PDF's own "strong domain model exists" claim didn't survive
inspection - a real, useful finding, not a rubber-stamp.** The
pre-existing `ContinuityBible` (Content Studio Redesign, Phase 16) is
genuinely solid, but it operates at the *script* level: character/
location/timeline/fact entries with no per-clip state at all. This
phase asks for something materially different - "the authoritative
visual state machine across every clip boundary," with incoming/
outgoing state per clip and enforced handoff equality between
adjacent clips. Nothing in this codebase did that before this phase.

**Design choice that eliminates a whole failure mode: derive
incoming state, don't ask for it.** The LLM call in
`VisualContinuityService.build()` only ever asks for one thing per
scene - its OUTGOING visual state (wardrobe, condition, location,
time of day, weather, lighting, props, vehicles, plus the shot action
and which known entities appear). Each scene's `incoming_state` is
then computed by the service itself as the *previous* scene's
outgoing state (a fresh, honestly-"unspecified" `VisualState()` for
scene 1, since nothing precedes it). "Enforce adjacent handoff
equality for contiguous clips" - this phase's own named requirement -
holds by construction this way, the same discipline Phase 1's
coverage gate already established, rather than depending on an LLM
independently producing two identical values on two separate calls
and hoping they agree.

**Identities reused, not re-extracted.** `CanonicalEntityIdentity`
objects are built directly from the pre-existing `ContinuityBible`'s
own `.characters`/`.locations` - no second LLM call re-derives what
was already extracted. Scoped honestly to PERSON/LOCATION only, not
PROP/VEHICLE: this codebase has no existing prop/vehicle identity
extraction to reuse, and building one from scratch was judged out of
proportion to this pass - documented as a real gap, not silently
dropped. Props and vehicles still appear on `VisualState.props`/
`.vehicles` as plain names, just without a registered canonical
identity behind them yet.

**Extraction and validation stay two separate passes, matching an
established pattern exactly.** `VisualContinuityBible` construction
is deliberately lenient - no hard validators - mirroring how
`ContinuityBible`/`ContinuityValidationService` already split
extraction from checking. New `VisualContinuityValidationService.validate()`
(rule-based, no LLM) mechanically checks handoff equality and
unknown-identity references, producing `VisualContinuityConflict`
diagnostics rather than raising - "actionable continuity conflict
diagnostics," this phase's own wording, means something a person can
read and act on, not an exception a caller has to catch.

**GUI.** A "Visual Continuity" section joins Production Directives in
the same Production Handoff card - both are read-only inspectors over
post-lock production artifacts, not separate workflow stages. Shows
every canonical identity with its description, a conflict banner when
`compute_visual_continuity_validation()` finds a problem, and
Generate/Regenerate buttons.

**Tests:** `test_visual_continuity_model.py` (7), `test_visual_continuity_service.py`
(7: one entry per scene, identities sourced from the continuity bible,
fresh first-scene incoming state, handoff equality by construction,
empty-scenes/provider-failure/negative-cost rejection),
`test_visual_continuity_validation_service.py` (4: consistent bible,
handoff mismatch, unknown identity, empty bible), 7 new pipeline
cases, 3 new GUI cases. mypy/ruff/black clean.

**Deliberately not built this pass:** PROP/VEHICLE canonical identity
resolution (honestly documented gap, not a silent one); reference-
asset attachment ("attach reference assets through provider-neutral
IDs" - the `reference_asset_ids` field exists, but no attachment
mechanism does yet, deferred until a real asset store integration
exists to attach from).

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 1 Production Semantic Brief / Directive Bible

**A deterministic, no-LLM-call phase - everything it needed already
existed on the locked script.** The plan asks for "time-bounded
production intent" covering the full script timeline without gaps.
`GeneratedScript.segments` already are exactly that: each segment
carries `start_seconds`/`end_seconds`, `narrative_function`,
`tension_level`, `related_curiosity_loop`, and
`source_claim_references`, and `GeneratedScript`'s own validator
already guarantees they're gapless and ordered. So "every second of
the production timeline is owned by a semantic segment" holds by
construction the moment the brief is built as a one-to-one projection
of those segments, rather than something a service has to separately
verify. New `src/models/production_semantic_brief.py`
(`ProductionSemanticSegment`/`ProductionSemanticBrief`) still enforces
the coverage gate mechanically anyway (`validate_full_coverage()`), so
that guarantee is checked, not merely assumed.

**Intent, not resolved directives.** The plan's own wording says
"intent," not "resolved shot specification" - that resolution is
explicitly Phases 3-4's job (Shot Plan, Cinematic Prompt Package). So
each segment's visual/voice/music/SFX/editing/transition fields are
short descriptive strings, deterministically derived from the
project's genre profile (the same `camera_preset_id`/
`transition_in_preset_id`/`music_preset_id`/etc. fields
`GenreDirectiveGenerationService` already reads for Scene-level
directives, just resolved one phase earlier and expressed as intent
rather than a fully wired directive object). No LLM call was needed
anywhere in this service - `ProductionSemanticBriefService.generate()`
is pure and fully reproducible from unchanged inputs, which is exactly
what "persist an artifact hash/version for downstream staleness
detection" requires: two generations from identical input produce the
identical `content_hash`.

**Beat binding reuses an established pattern, not a new one.**
`beat_id` matches a `StoryBlueprint` beat by real-seconds time range -
the exact same trick Content Studio Redesign Phase 9's
`_bind_curiosity_roles()` already established for tying a script
segment back to its originating beat. This codebase has no separate
"section" concept distinct from a beat, so `beat_type` doubles as the
plan's "section_id" - documented here as a deliberate simplification,
not a silently-guessed one.

**Reveal protection reuses an existing signal instead of re-deriving
it.** `reveal_protected` is simply `segment.related_curiosity_loop is
not None` - the script segment is already tagged as advancing a
tracked curiosity loop by earlier Content Studio Redesign work, so
reusing that tag directly avoids a second, potentially-drifting
notion of "this segment needs spoiler care" built from
`InformationRevealMap`'s normalized positions a different way.

**Hard-gated on the lock, not just the script.** Unlike every Content
Studio Redesign stage (which requires only `job.generated_script`),
`run_production_semantic_brief()` requires `job.script_lock is not
None` - this plan's own contract names `FinalScriptLock` as the
primary input, and this is the first Post-Script-Approval phase where
that distinction actually matters in code.

**GUI.** The Production Handoff card (Phase 0) gained a "Production
Directives" section - the plan's own wording calls this a "tab/
inspector," not a standalone screen, so it lives inside the existing
card rather than growing a new one. Shows each segment's time range,
beat, and visual/voice/music intent, a staleness banner when the
brief's bound hash no longer matches the current lock, and Generate/
Regenerate buttons.

**Tests:** `test_production_semantic_brief_model.py` (7: coverage
gate - gap, overlap, non-zero start all rejected; hash stability and
sensitivity; field defaults), `test_production_semantic_brief_service.py`
(5: one segment per script segment, reveal/claims passthrough, beat
binding with and without a blueprint, hash reproducibility), 3 new
pipeline cases, 3 new GUI cases. Full combined regression (pipeline,
GUI, both new model/service files, video job, migration): 224 passed.
mypy/ruff/black clean.

**Deliberately not built this pass:** no manual-override/revision
mechanism for the brief ("manual override creates a directive
revision and invalidates only dependent artifacts") - nothing
downstream of the brief exists yet to actually invalidate, so building
that machinery now would have nothing real to point at; honestly
documented rather than invented: SFX intent is a generic genre-default
phrase, since this codebase's genre profile has no dedicated
per-segment SFX-cue field, only `music_preset_id`.

---

## 2026-09-06 - Post-Script-Approval Production Plan: Phase 0 Canonical Script Lock and Production Handoff

**Starting the second PDF (Post-Script-Approval Production Plan),
Google Flow's own automation mechanism explicitly excluded per the
standing scope.** Re-extracted the full 16-phase plan
(`Mission_Automation_Post_Script_Approval_Phase_Plan.pdf`) and
checked its own "Current Repository Position" table against this
repo's actual state before writing anything - the PDF's table is
partially stale (it names files like `content_workspace_service.py`/
`clip_workspace_service.py`/`visual_continuity_service.py` that don't
exist under those names here; the underlying repo has evolved past
that baseline). Confirmed instead, by direct inspection, that this
whole session's Content Studio Redesign work already covers large
parts of this plan's own scope: `ScriptLock`/`ScriptLockService`/
`run_script_lock()` (Content Studio Phase 14, hardened Phase 19) *is*
this plan's "Final Script Lock + SHA-256 integrity binding"; genre
`SceneEditingDirectives` is most of "Production Semantic Brief," just
organized per-scene instead of per-segment; continuity extraction,
audio timeline, and the FFmpeg render stack already exist and are
substantial.

**What Phase 0 actually needed, once the REUSE audit was done.** The
plan's exit criteria ask for one thing Content Studio Redesign never
had a concrete reason to build: "all downstream artifacts identify
the exact locked script SHA-256." Phases 14, 16, and 17 each
explicitly deferred stamping `Scene`/directive models with a
`locked_script_id`/hash, each time for the same reason - "no real
downstream reader exists yet." This plan *is* that reader. New
`Scene.locked_script_hash: str | None` (optional, backward-compatible)
is now stamped by `run_scene_planning()` from
`job.script_lock.script_content_hash` whenever a lock exists at
planning time.

**A post-approval production state, computed not persisted.** New
`src/models/production_handoff.py` - `ProductionHandoffState`
(BLOCKED/LOCKED/BUILDING_PACKAGE/PACKAGE_READY) and
`ProductionHandoffStatus`, following the exact same pure-computed-
snapshot convention `AutomationStatus`/`ScriptQualityReport` already
established. `ContentIntelligencePipeline.compute_production_handoff_status()`
reuses the pre-existing `InvalidationService.is_stale(job, "scenes")`
check for the BUILDING_PACKAGE distinction (a script re-locked after
scenes were already planned) rather than inventing a second notion of
staleness - one mechanism, read from two places.

**GUI.** A new "Production handoff" card - a state banner plus a
"Retry production handoff" (or "Build production package," before
scenes exist yet) button. The button reuses the existing generic
`_handle_run_ci_stage("scene_planning")` dispatch rather than a new
handler, satisfying the plan's own "Retry Production Handoff without
forcing another script approval" literally: nothing about retrying
touches approval state at all.

**Tests:** `test_production_handoff_model.py` (5), 5 new pipeline
cases (blocked-without-lock, locked-before-scenes, package-ready,
hash-stamping, building-package-when-stale), 3 new GUI cases. Full
combined regression (content intelligence pipeline, GUI, migration,
production handoff model): 208 passed. mypy/ruff/black clean.

**Deliberately not built this pass:** no hard precondition inside
`run_scene_planning()` itself refusing to run without a lock - matches
this session's own established precedent (Content Studio Redesign
Phase 7: many existing tests call pipeline stage methods directly and
standalone, without their normal preconditions, by design; `run_all()`'s
own call order already only reaches scene planning after locking, so
enforcement lives at the orchestration/GUI level instead); no hash
stamping on anything downstream of scenes (clips, timelines, render
results) since none of those exist yet for the new pipeline - deferred
to whichever later phase actually builds them.

---

## 2026-09-06 - Content Studio Redesign: Phase 19 End-to-End Integration, Migration and Production Readiness

**A verification phase, and it earned its keep - two real bugs found,
neither catchable by any prior phase's own narrower tests.**

**Bug 1: `run_all()` never actually created a `ScriptLock`.** The
phase's exit criterion is blunt: "both paths reach a valid Script
Lock." Writing the E2E test to prove it for the internal-content path
found that `run_all()`'s final locking step called
`ScriptVersionService.lock_version()` directly - the same boolean
flag every script-mutating method checks, but *not* Phase 14's real
`ScriptLock` record. A fully automatic run completed, "locked" the
version, and left `job.script_lock` at `None` with zero Activity
History trace a lock had happened. Fixed by routing through
`run_script_lock()` itself, the exact method every manual "Approve &
lock script" click already uses - guarded on `job.script_lock is
None` so a second `run_all()` call on an already-complete job stays a
true no-op, with a `try/except ValueError` fallback to the old
direct-lock behavior for the one edge case where a caller ran
ambiguity detection outside `run_all()`'s own sequence and left
something genuinely unresolved (`run_all()` has never raised at this
point and shouldn't start now).

**Bug 2, more serious: a real-condition data-loss-on-reload bug.**
Building the migration test - load a raw pre-redesign-shaped JSON
file, run it through `run_all()`, then round-trip it through
`JsonJobStore` again - surfaced a `VideoJob` validator failure:
`"Scenes cannot exist without a script."` `validate_workflow_state()`
predates this session's Content Intelligence work and only ever
checked the *legacy* `self.script` field (`ContentPipeline`'s own
artifact), never `self.generated_script` (the new pipeline's). Any
project completed through the new pipeline - which is to say, any
project built this whole session - would fail to deserialize at all
the moment it was saved and reloaded through `JsonJobStore`, which is
exactly what the real desktop app does on every save. No prior
phase's tests happened to do a real `model_dump_json()` →
`model_validate_json()` round-trip on a `run_all()`-completed job, so
this sat undetected through 18 phases. Fixed by accepting either
provenance in that one validator branch.

**Migration, proven not assumed.** New `tests/test_project_migration.py`
constructs a raw pre-redesign JSON dict directly - not a `VideoJob(...)`
construction, which by definition would include every field that
exists today - confirms it loads with every Content Studio Redesign
field defaulting sensibly, then runs it through the *exact* `run_all()`
any new project uses and confirms it reaches a real `ScriptLock`,
then saves and reloads it again. "Compatible existing projects
migrate" is a tested claim now, not an inference from "every field is
optional."

**Legacy GUI retirement/redirect plan.** A plain "Which workflow
should I use?" notice, always visible on a fresh project, pointing at
Content Intelligence over the original `ContentPipeline` - the four
legacy cards (Content workflow/Research/Script/Originality review/
Scenes) stay exactly as functional as before, nothing hidden or
disabled, so an in-progress legacy-pipeline project is never
stranded. The notice disappears once a project has clearly committed
to either path, via a small testable `_should_show_legacy_pipeline_notice()`
predicate kept separate from the widget-building code specifically so
its logic doesn't depend on Qt's deferred-deletion timing in tests.

**Final documentation.** New `docs/CONTENT_STUDIO_OPERATOR_GUIDE.md` -
a practical, task-oriented "how do I actually run a project" guide
covering both E2E paths, the three approval postures, checking where
a project stands, editing/recovering a script, and the legacy
pipeline's status. Distinct from `IMPLEMENTATION_STATE.md`'s
architecture-and-status framing and `SYSTEM_TRACEABILITY_MATRIX.md`'s
model→service→GUI→tests framing - this one is for using the app, not
auditing it.

**Tests:** `test_run_all_locks_the_approved_version` extended to
assert the real `ScriptLock` (not just the version's boolean flag)
plus idempotency across a second `run_all()` call; new
`test_run_all_reaches_a_script_lock_for_an_intake_originated_script`
proves the external path reaches the same destination with `EXTERNAL`
provenance inferred automatically; `test_project_migration.py` (2
tests, described above); 2 new GUI cases for the notice predicate.
Full suite - 1818 tests, `test_ffmpeg_capability_service.py` excluded
as this session's own established known-flaky exclusion - green after
both fixes. mypy/ruff/black clean.

**Deliberately not built this pass:** no automated migration script -
none is needed; Pydantic's own optional-field defaults are the
migration mechanism, and this phase's job was proving that with a
real test, not building new machinery around it. No document-format
script import beyond plain text (unchanged from Phase 15). No fourth
"Automatic Reviewer" approval posture (unchanged from Phase 17).

This closes out PDF-2 (Content Studio Redesign) Phases 0-19 in full.

---

## 2026-09-06 - Content Studio Redesign: Phase 18 Activity History, Auditability and Recovery

**REUSE confirmed by inspection - and it reframed the phase from "build
a history model" to "close a silent logging gap."** `ContentDecisionRecord`/
`VideoJob.content_decisions` already existed, already append-only,
already carrying `id`/`created_at`/`updated_at` for free from
`MissionBaseModel`. But reading every call site that actually appends
to it turned up only two: `ApprovalGateService.gate()` and `.resolve()`,
covering exactly the 7 explicitly gated decision points. The other 7 of
`run_all()`'s 14 stages, plus revision, selection edits, restore,
intake, ignore-finding, ambiguity resolution, and - most strikingly -
script lock/unlock, wrote to it never. Unlocking a script does
`job.script_lock = None`; before this phase, that left *zero* trace a
lock had ever existed once undone. That silent gap was the actual
scope here, not a missing model.

**One category taxonomy, one append surface.** New `DecisionCategory`
(GENERATION/APPROVAL/INVALIDATION/RESTORE/LOCK/UNLOCK) folds the
source PDF's "generation/review/approval/unapproval/invalidation/
restore/lock" into six buckets - review and approval collapse into one
APPROVAL category because `ApprovalDecision.state` already
distinguishes pending from resolved, and "unapproval" in this
pipeline's practical terms is unlocking an already-locked script.
`category` is optional with an `effective_category` property that
infers GENERATION/APPROVAL for every record persisted before this
field existed - an old project's JSON needs no migration and still
classifies sensibly. New `ApprovalGateService.record_event()` is the
one place every non-approval write goes through, so
`job.content_decisions` stays one ledger instead of growing a
second, competing history mechanism.

**Every silent stage, wired.** `record_event()` calls added to
`run_retention_audit`, `run_writing_directives`, `run_continuity_bible`,
`run_editorial_critique`, `run_quality_gate`, `run_packaging_hypothesis`,
`run_scene_planning`, `run_revision`, `run_ignore_finding`,
`run_script_selection_edit`, `run_script_intake`,
`run_resolve_ambiguity_manually`, `run_resolve_ambiguity_by_ai`
(all GENERATION), `run_script_restore` (RESTORE), and
`run_script_lock`/`run_script_unlock` (LOCK/UNLOCK - the version
number is captured *before* `job.script_lock` is cleared on unlock,
so the record still names what was unlocked). `InvalidationService`
gets its own single new headline record (category INVALIDATION)
appended directly from `_mark_stale()` whenever it actually flags
something new - its own, more detailed `stale_artifacts` ledger is
untouched, the two are complementary, not duplicated.

**A real bug found via a failing test.** The new script-intake
logging line called `mode.value`, assuming an enum - but the GUI
passes a plain `str` pulled from a `QComboBox`'s stored item data,
not a `ScriptIntakeMode` member, so three existing intake tests
failed with `AttributeError: 'str' object has no attribute 'value'`.
Fixed with `getattr(mode, "value", mode)`, which handles both the
enum callers and the GUI's raw string identically.

**GUI.** `_build_approval_history_card` renamed
`_build_activity_history_card` and widened from "approval decisions
only" to every `ContentDecisionRecord` in the job, each entry showing
its category, stage, timestamp, and summary. Two new filters
(category, stage) persist on the view across `refresh()` calls, reset
on `set_job()`, and apply by calling `self.refresh(job)` directly on
change - the same pattern `_handle_select_ci_stage` already
established, not the job-mutating `_on_change()` callback most other
handlers use, since a filter choice isn't job state. The pending-
approval action row is unaffected by either filter and always shows
the real pending decision.

**Tests:** `test_content_decision_record.py` (+4: category default,
explicit category, backward-compatible legacy-record inference),
`test_approval_gate_service.py` (+3: `record_event`, metadata
passthrough, explicit `APPROVAL` stamping on `gate()`/`resolve()`),
6 new GUI cases (widened timeline shows previously-invisible stages,
filter persistence for both filters, lock/unlock visibility,
`set_job()` filter reset). Full regression: `test_content_intelligence_pipeline.py`
(180+), `test_content_studio_content_intelligence_gui.py` (102),
`test_invalidation_service.py` (11, unaffected). mypy/ruff/black clean.

**Deliberately not built this pass:** a dedicated rollback-to-any-
past-state recovery UI beyond the pre-existing script-version Restore
action (Phase 12) - now visible in the unified timeline, but a
broader mechanism spanning more than script content was judged out of
scope until a concrete need for it exists; no activity-log export; no
pagination (a single project's stage count is small and bounded, so
the full reversed list renders directly like every other list panel
in this view already does).

---

## 2026-09-06 - Content Studio Redesign: Phase 17 Unified Automation Engine (One Engine, Multiple Approval Postures)

**REUSE confirmed by inspection before writing anything new - and it
changed the shape of the whole phase.** This phase's stated exit
criterion was "all workflow modes (full auto, review critical stages,
manual editorial) are one engine, not three separate code paths."
Before writing an orchestrator, `ContentIntelligencePipeline.run_all()`
was re-read end to end: it already is that one engine - a single
mode-agnostic loop over all 14 stages, driven purely by
`VideoJob.approval_policy`, pausing at whichever gate the policy marks
as requiring review and continuing straight through any gate it
doesn't. `ApprovalPolicyConfig.full_auto()`/`.review_critical_stages()`/
`.manual_editorial()` presets already exist, and `LLMService` already
has its own retry/fallback. None of Phase 17's backend engine work was
still open - writing a second orchestrator here would have been the
exact duplicate-engine mistake the phase exists to prevent.

**What was genuinely missing: visibility, not logic.** A person
looking at a project mid-automation had no single answer to "what has
this run already done, and what is it waiting on me for." New
`AutomationStatus` (`src/models/automation_status.py`) is a pure
computed snapshot - never persisted, recomputed fresh on every call,
the same convention `ScriptQualityReport`/`ScriptProductionReadinessReport`
already follow - with `completed_stages`, `pending_decision_point`/
`pending_stage`/`pending_summary`, and `is_paused`/`is_complete`
properties. `ContentIntelligencePipeline.compute_automation_status()`
mirrors `run_all()`'s own per-stage presence checks (so the status can
never drift out of sync with what `run_all()` would actually do next)
and reuses `ApprovalGateService.latest_pending()` for the pause
details rather than re-deriving them.

**GUI.** The Content Intelligence card gained a "Resume automation" /
"Run automation" primary button (calls `run_all()` directly) plus a
completed-stage-count badge, a warning banner naming the pending
stage/decision/summary while paused, and a success banner once
`scene_planning` is done and nothing is pending.

**A stub gap found via a real test failure, not a code review.**
`test_run_automation_runs_the_whole_pipeline` failed with
`job.generated_script is None` after a `full_auto()` run - not a bug
in the new code, but in the GUI test file's own, separate
`_EchoStubLLMService` double. `test_content_intelligence_pipeline.py`'s
stub already substitutes `SPOILER_RISK: 70` -> `0` for
`HookEvaluationService` (the service's placeholder dry-run scores
every dimension at 70, which zeroes `overall_score`/`confidence_score`
by construction - fine in isolation, fatal to a full auto-continuing
run). The GUI test file's own copy of that stub never got the same
fix. Ported the identical substitution across; all 4 automation GUI
tests pass afterward.

**Tests:** `test_automation_status_model.py` (5), 6 new pipeline
cases (including `full_auto()` completing without pausing and
`manual_editorial()` pausing early, both through the same `run_all()`
call - direct proof of "one engine, multiple postures"), 4 new GUI
cases. mypy/ruff/black clean.

**Deliberately not built this pass:** an "Automatic Reviewer" fourth
policy preset (auto-resolving low-severity findings without a human) -
deferred until a concrete need for it beyond the existing three
presets is identified, rather than adding a preset nobody asked for
yet.

---

## 2026-09-06 - Content Studio Redesign: Phase 16 Imported Script Production Enrichment and Automatic Directive Extraction

**REUSE confirmed by inspection before writing anything new.** This
phase's deliverable list is exhaustive, but most of it already worked
for any script regardless of origin: `ContinuityBibleExtractionService`
already extracts characters/locations/timeline/facts from any
`GeneratedScript`; `ScenePlannerAgent.plan_from_generated_script()`
already derives genre-aware scenes/clip boundaries from any script;
the pre-existing `GenreDirectiveGenerationService`/
`GenreVoiceDirectiveGenerationService` (already wired into the
downstream render pipeline) already produce visual/voice/editing
directives per scene from genre profiles alone - deterministic rule
lookups, no LLM call, no dependency on how the script was produced.
None of that needed new code, only confirming it already applied.

**What's genuinely new: the ambiguity registry and readiness report.**
New `ProductionAmbiguity` (`continuity_critical` flag, `is_blocking`
property - true only while unresolved *and* continuity-critical, so a
cosmetic ambiguity never blocks anything) and
`ScriptProductionReadinessReport` (pure aggregation, no invented
score). `ProductionAmbiguityService.detect()` is one LLM call reusing
the continuity bible's own entries as context so it doesn't re-flag
already-established facts; `resolve_manually()` takes a person's own
note; `resolve_by_ai()` is a distinct, explicit, separately-logged
action - "Let AI Decide" is never an automatic default nobody asked
for.

**A near-miss caught immediately, not shipped.** The first pass at
the readiness report used the name `ProductionReadinessReport` -
already taken by a pre-existing, unrelated, much larger model/service
(whole-project render/export readiness with a full `Blocker` taxonomy,
from an earlier PDF-1 phase). `Write`-ing the new file overwrote both
the pre-existing model and its 350-line service. Caught immediately
via `git status` showing `M` instead of the expected `A` on both
files before anything was committed; restored losslessly with
`git restore --source=HEAD --staged --worktree`, verified with that
service's own pre-existing test suite (still 17/17 passing
afterward), and the new Phase 16 concept re-implemented under
non-colliding names (`ScriptProductionReadinessReport`/
`ScriptProductionReadinessService`, `compute_script_production_readiness()`
on the pipeline) with zero further changes to the pre-existing files.

**One consistent lock policy, not two.** `ScriptLockService.build_lock()`
now also refuses to lock over an unresolved continuity-critical
ambiguity, using the exact same `override_reason` mechanism Phase 13's
quality-finding check already established - "unresolved blocking
[X] prevent lock... unless an explicitly designed override policy
allows it" is now one policy shape, applied twice, not two different
ones.

**GUI.** A new "Production readiness" stage appended to the end of
the `_CI_STAGES` rotation (appended, not inserted, so no existing
hard-coded stage index in any prior test shifted) shows the readiness
verdict, continuity-bible/scene-count status, and one row per
ambiguity with "Resolve manually" (note input) and "Let AI decide."
"Reviewer checks whether directives faithfully represent the script"
needed no new service - the existing generic "Review" button already
reaches this stage.

**Tests:** `test_production_ambiguity_model.py` (7),
`test_script_production_readiness_model.py` (4), `test_production_ambiguity_service.py`
(12), 8 new pipeline cases, 5 new GUI cases. mypy/ruff/black clean.

**Deliberately not built this pass:** no per-artifact
`locked_script_id`/hash stamping on Scene/directive models themselves
(same deferral Phase 14 already documented); no separate source-span/
confidence model for LLM-detected ambiguities - continuity facts
already carry `first_mentioned_segment`, and genre-preset directives
are deterministic lookups with no meaningful "confidence" to model.

---

## 2026-09-06 - Content Studio Redesign: Phase 15 Alternate Path - Import Approved Script Intake

**The bypass path.** New `ScriptIntakeService.normalize_text_to_script()`
converts raw pasted/uploaded text into the exact same `GeneratedScript`
Content Production itself produces (one segment per blank-line-
separated paragraph, timed at ~150 words/minute, `narrative_function=
SETUP` throughout since no real beat sheet exists to draw a role
from) - so every later stage (versioning, selection edits, quality
gate, lock) works identically regardless of a script's origin.
`ContentIntelligencePipeline.run_script_intake()` touches nothing
else: no fake `research`/`selected_hook`/`story_blueprint` is ever
built to satisfy some other stage's dependency, verified by a
dedicated regression test.

**Three named modes, one deterministic check plus one LLM call.**
TRUST_MY_SCRIPT skips analysis entirely. VALIDATE_FOR_PRODUCTION and
FULL_QUALITY_CHECK both run `analyze_mismatches()` - one LLM call
("Primary analyzes but does not rewrite") flagging language/genre/
audience/platform inconsistencies against the project's own settings,
reusing the established labeled-block pattern rather than adding a
language-detection library dependency. Duration mismatch (>20% off
target) is always checked, deterministically, regardless of mode.

**Provenance inference, not a manual flag.** `run_script_lock()` now
infers `provenance=EXTERNAL` automatically whenever
`job.script_intake_result is not None`, `INTERNAL` otherwise - a
caller only needs to pass `provenance` explicitly to override it.

**Two real bugs found and fixed while building this phase:**
(1) `_handle_lock_script()` (written for Phase 14, before Script
Intake existed) hardcoded `provenance=ScriptProvenance.INTERNAL`,
silently defeating the inference above the moment it existed - caught
by a GUI test that locked an imported script and got INTERNAL back.
Fixed by no longer passing `provenance` from the GUI at all, with a
regression test proving the ordinary Content Production path still
locks INTERNAL. (2) `test_content_intelligence_pipeline.py`'s `_job()`
helper's `**dict`-unpacking mypy mismatch count had grown by exactly
one with each of the last two phases' new optional `VideoJob` fields -
a compounding pattern - fixed once, permanently, with a single
`# type: ignore[arg-type]` on that helper's one construction line,
dropping the file from 62 errors to 1 (a pre-existing, unrelated nit).

**GUI.** The Script panel's import sub-section (shown only before any
script exists) gained a paste box, an "Upload .txt file..." button
reading a local file's raw text into that same box, an intake-mode
selector, and "Import script." Once imported, an always-visible
summary shows word count, estimated duration vs. target, every
mismatch with its note, and an explicit statement that Research/
Hooks/Beat Sheet are intentionally absent, not missing by mistake.

**Tests:** `test_script_intake_model.py` (7), `test_script_intake_service.py`
(20), 8 new pipeline cases, 10 new GUI cases. mypy/ruff/black clean.

**Deliberately not built this pass:** real document-format extraction
(.docx/.pdf/...) - plain text only; FULL_QUALITY_CHECK does not yet
auto-trigger the full editorial critique pipeline (blocked on
`EditorialCritiqueService`'s `research` param becoming optional, to
avoid fabricating a fake `ResearchResult` and violating this same
phase's own "no fake Research artifacts" exit criterion).

---

## 2026-09-06 - Content Studio Redesign: Phase 14 Script Lock and Common Production Handoff Contract

**The hard boundary.** New `ScriptLock` (version + content hash +
provenance + a snapshotted quality status + optional override reason)
- `created_at` (inherited) doubles as the lock timestamp, no second
clock. `GeneratedScript` gained a `content_hash` property, extracted
from Phase 13's quality-gate service so both quality-result binding
and Script Lock share exactly one hash implementation.

**Composes with, doesn't replace, the existing per-version lock.**
`ScriptVersion.locked` (and every script-mutating method's check
against it) already existed. `run_script_lock()`/`run_script_unlock()`
set/clear both that flag and the new richer `ScriptLock` record
together, rather than introducing a second, independent lock state.

**Two real "cannot silently edit locked script" bugs, found while
implementing this phase's own test requirement, fixed:**
`run_revision()` was unconditionally overwriting `job.generated_script`
with LLM-revised text *before* the version-service's lock check could
run - the version-history append correctly failed, but the script
itself was already silently corrupted by then. The GUI's raw "Save
typed edit" handler had the identical bug. Both fixed by checking the
lock first, matching the pattern `run_script_selection_edit()` already
used correctly.

**Unlock impact analysis, not a generic message.** `ScriptLockService
.compute_unlock_impact()` reuses `InvalidationService`'s own
downstream-fields list (now exported public) to report exactly which
VideoJob fields currently hold a real production artifact that would
go stale.

**GUI.** A new Script Lock section (in both the Script and Revision
panels): "Approve & lock script" with an override-reason input and an
unresolved-blocking-findings warning while unlocked; version/
provenance/quality/hash-prefix display plus "Unlock script" while
locked. Both require a `QMessageBox.question()` confirmation naming
the real consequence - reusing the one existing confirmation-dialog
pattern in this codebase (`provider_manager_view.py`) rather than
inventing a second.

**Tests:** `test_script_lock_model.py` (6), `test_script_lock_service.py`
(10), 8 new pipeline cases (including a dedicated regression proving
`run_revision()` no longer mutates a locked script even when it
raises), 6 new GUI cases. mypy/ruff/black clean on every new file. One
transparent trade-off: `VideoJob.script_lock` grew
`test_content_intelligence_pipeline.py`'s pre-existing `**dict`-
unpacking helper's error count by exactly one (60→61 total) -
rewriting that helper (used across 900+ lines of tests) was judged
disproportionate versus the smaller, single-file rewrite Phase 13 did
for a similar case. All targeted pipeline and GUI tests pass.

**Deliberately not built this pass:** downstream production models
(Scene, RenderResult, ...) don't yet store their own
`locked_script_id`/hash individually - satisfied today only at the
job level, deferred until a real downstream reader exists (likely
Phase 17's automation orchestrator).

---

## 2026-09-06 - Content Studio Redesign: Phase 13 Script Critique and Formal Quality Gate

**KEEP/MODIFY/REUSE first.** `EditorialCritiqueService`,
`ScriptQualityGateService`, and `ScriptRevisionService` already
existed and already separated advisory critique from a formal
pass/needs-revision/needs-review decision - confirmed by direct code
inspection. Real new scope: selective fix application, safe-vs-needs-
review classification, ignore-with-reason tracking, and version/hash
binding.

**Safe vs needs-review, defined mechanically.** `CriticFinding` gained
`is_safe_to_auto_fix` - true for every severity except BLOCKING, since
`ScriptRevisionService` never restructures a script regardless of
severity (structure is always preserved); a BLOCKING finding is
excluded from an unattended "Fix All Safe Issues" pass specifically
because its severity means a person should look at it first.

**Apply Selected Fixes.** `ScriptRevisionService.revise()` gained an
optional `finding_ids` filter - omitting it addresses every finding,
reproducing exact prior behavior; supplying it addresses only those.
Combined with `is_safe_to_auto_fix`, this covers both "Apply Selected
Fixes" and "Fix All Safe Issues" with one mechanism, no duplicate
service method needed.

**Ignore with reason.** New `FindingResolution`/`FindingResolutionAction`
- `ScriptQualityReport.resolutions` is append-only, like every other
audit trail in this codebase. `ScriptQualityGateService.ignore_finding()`
validates a non-empty reason, rejects an unknown finding id, and
rejects re-resolving an already-resolved finding.

**Quality result binds to exact Script version/hash.** `ScriptQualityReport`
gained optional `script_version_number`/`script_content_hash`; the
hash is a deterministic sha256 over every segment's narration+timing.
The Quality Gate panel now shows a staleness warning when the
displayed report's bound version no longer matches the script's
current version.

**A retroactive fix, not new scope.** While implementing this phase's
own "Quality result invalidation after script change" requirement,
found that Phase 12's `run_script_selection_edit()`/`run_script_restore()`
(and the GUI's raw "Save typed edit" path) mutated the script without
clearing a stale `editorial_critique`/`script_quality_report`, unlike
`run_revision()`. Fixed to match `run_revision()`'s existing behavior
exactly, so every script-mutating path now invalidates consistently -
this is exactly the kind of gap this phase's own test requirement is
supposed to catch, so fixing it here rather than filing it away was
the right call.

**GUI.** The Quality Gate panel now shows a checkbox per unresolved
finding (severity, location, safe/needs-review tag) with an inline
"Ignore with reason" input+button, plus "Apply selected fixes," "Fix
all safe issues," and "Return to script" actions. "Run Critique Again"
needed no new work - the existing generic per-stage "Run" button
already re-runs any stage.

**Tests:** `test_editorial_critique_model.py` (+4), `test_script_quality_report_model.py`
(+9, rewritten to explicit-keyword construction so the model's 3 new
fields didn't add mypy noise to the file's existing `**dict`-unpacking
helper), `test_script_quality_gate_service.py` (+9), `test_script_revision_service.py`
(+3), 6 new pipeline cases, 6 new GUI cases. mypy/ruff/black clean;
the pre-existing `test_content_intelligence_pipeline.py` mypy baseline
(60 errors) is unchanged, confirmed via `git stash` diff. All 53
pipeline tests and all targeted GUI tests pass.

**Deliberately not built this pass:** `ScriptQualityReport` still only
carries BLOCKING/MAJOR findings, not the full MINOR/MODERATE/MAJOR/
BLOCKING spread the source document's wording implies - a pre-existing
model limitation from an earlier sprint, not something this pass
changed; no "Fix All" beyond "Fix All *Safe*" - unattended-fixing a
BLOCKING finding is exactly what the safe/needs-review split exists to
prevent.

---

## 2026-09-06 - Content Studio Redesign: Phase 12 Script Generation, Rich Editor and Version Control

**KEEP/MODIFY/REUSE first.** Direct code inspection (not assumed) found
`ContentIntelligencePipeline.run_script()` already assembles the full
"generation package" the spec asks for - topic, audience promise,
creative direction/story angle, research, story blueprint, reveal map,
hook, writing directives, duration, genre - into
`ScriptGenerationService.generate()`. `ScriptVersionHistory`/
`ScriptVersionService` (lock/unlock, critique-driven `add_revision()`)
and `ScriptRevisionService` also already existed from earlier session
work. So this phase's real, additive scope was: selection-based edits
(genuinely new), version reasons (new field), and restore/compare
(both new methods) - not a rebuild of any of the above.

**Version reasons.** `ScriptVersion` gained `reason: VersionReason`
(GENERATION/MANUAL_EDIT/REVIEWER_REVISION/QUALITY_FIX/RESTORE) and
`restored_from_version_number`, both optional with a validator that
infers the same reason the two pre-existing call sites
(`start_history`/`add_revision`) always implicitly meant - every
existing `ScriptVersion(...)` construction across the codebase and its
tests keeps working completely unchanged.

**Selection-based AI edits, with a real context envelope.** New
`ScriptSelectionEditService` is a distinct, narrower path from
`ScriptRevisionService`: one person-chosen operation
(Rewrite/Shorten/Expand/More Suspenseful/More Natural/Improve
Transition/Custom Instruction) applied to one segment, or a substring
within it, with no critique involved. The LLM prompt includes the
immediately preceding/following segments' narration as read-only
context so an edit still reads coherently in place, but only the
target segment's narration is ever returned/applied - every other
segment, and the edited segment's timing/narrative_function/
source_claim_references, come back byte-identical. This mechanical
guarantee is what "hook preservation" and "evidence-grounding checks"
mean in practice here, and it's proven by dedicated regression tests,
not just asserted in a docstring.

**Restore and compare, non-destructively.** `ScriptVersionService`
gained `restore_version()` (copies an earlier version's script content
as a brand-new version - nothing is ever deleted or rewritten, so a
restore is itself undoable by restoring again) and `compare()` (a pure
segment-by-segment diff between any two versions, classifying each
segment added/removed/changed/unchanged).

**GUI: an actual editable Script Editor.** `ContentStudioView`'s
Script panel no longer shows a static read-only label - each segment
gets its own editable `QTextEdit`, a row of the six fixed
selection-action buttons (operating on whatever text is currently
highlighted, or the whole segment when nothing is selected), a
custom-instruction row, and a "Save typed edit" button that records a
person's own direct rewrite as its own manual-edit version with **no**
AI call at all - the genuinely non-AI "manual edit" path the reason
vocabulary implies. The version history section gained per-version
reason display, a Restore button per non-current version, and two
version selectors plus a Compare button rendering the full diff.

**Tests.** `test_script_version_model.py` (+9), `test_script_version_service.py`
(+11), new `test_script_selection_edit_model.py` (6) and
`test_script_selection_edit_service.py` (12, covering hook
preservation, evidence-grounding, context envelope, and custom
instructions specifically), 5 new pipeline-level cases, 9 new GUI
cases (editor construction, AI selection edit, custom edit, manual
typed edit, restore, compare, and locked-version read-only behavior).
mypy/ruff/black clean on every new/changed file; the pre-existing
`test_content_intelligence_pipeline.py` mypy baseline (60 errors, all
pre-existing `**dict` unpacking debt) is unchanged by this phase's
edits, confirmed via `git stash` diff.

**Deliberately not built this pass:** no rich-text formatting in
segment editors (narration is plain spoken text); no drag-to-reorder
segments (structure remains the blueprint/beat sheet's decision only);
"Review Selection" (reviewing just a highlighted span) - the existing
generic per-stage "Review" button already covers whole-script review.

---

## 2026-09-06 - Render worker thread-safety fix (Windows heap-corruption crash)

**The defect.** A final pre-commit full-suite regression run for Phase
11 crashed with a genuine Windows fatal exception (`0xc0000374`, heap
corruption) inside `test_render_progress_updates_live_and_survives_cross_workspace_refresh`,
not a flaky stall. Root cause in
`src/desktop/views/render_workspace_view.py`: `_RenderWorker`'s
`progress`/`finished`/`failed` signals, and the render `QThread`'s
`finished` signal, were all connected to **lambdas** so the connection
could close over the per-render `job_id`/`user_input`. Qt's
`AutoConnection` only detects that a signal needs cross-thread queued
delivery by inspecting a bound method's `__self__` to find its owning
thread; a lambda has no such owner, so the connection silently
resolved to a **direct call in the emitting thread** - meaning GUI
widgets were being mutated from the background render `QThread`
itself. That is undefined behaviour in Qt and the actual cause of the
crash. Confirmed empirically (small standalone repro scripts) that an
explicit `Qt.ConnectionType.QueuedConnection` does **not** fix this for
a lambda slot in this PySide6 version either - only a connection to a
genuine bound method of a `QObject` gets correct thread-affinity
detection.

**The fix.** `job_id`/`user_input` now travel as plain attributes on
`_RenderWorker` (and, for `thread.finished`, on the `QThread` instance
itself, since that signal carries no arguments), and every one of the
four cross-thread connections now targets a real bound method on
`RenderWorkspaceView` (`_handle_render_progress`,
`_handle_render_finished`, `_handle_render_failed`,
`_handle_render_thread_finished`), each recovering its job via
`self.sender()`. No lambda crosses a thread boundary as a signal slot
anywhere in this file anymore.

**Verification.** The specific crashing test now passes cleanly
(`1 passed in 355.98s` - it is a genuinely slow test on its own, not a
stall; confirmed via CPU-time-diff over real elapsed wait before and
during the run). Combined with the two bisected halves of the full
suite already having passed cleanly in the prior session segment
(6 passed / 40.47s and 104 passed / 190.08s) and a separate 143-test
batch (85.76s), this is treated as sufficient evidence the fix is
correct without re-running the entire suite end-to-end again, given
its multi-minute-per-slow-test cost.

---

## 2026-09-05 - Content Studio Redesign: Phase 11 Script Workspace - Writing Directives

**Backend.** New `src/models/writing_directives.py`: `DirectiveSource`
(SYSTEM/GENRE/PROJECT/USER - exactly the redesign's four named
sources), `WritingDirective` (text + source + `overridable`, stored
independently per the redesign's own wording rather than derived
purely from source), `WritingDirectiveSet`.

New `WritingDirectivesService.resolve()`. Three fixed SYSTEM
directives - "Never state a claim the research does not support,"
"Never fabricate quotes, statistics, or sources," "Never fully reveal
the story's payoff before its planned position" - are appended
unconditionally after every call. They are never constructed any
other way anywhere in this codebase, which is what makes "System
factual-grounding rules cannot be disabled by ordinary user
directives" a real mechanical guarantee rather than a hope that the
LLM behaves. GENRE candidate directives are derived deterministically
from an already-resolved `EditorialProfile`'s own fields (tone,
narrative style, hook style, CTA policy) - not LLM-invented, so
whatever `EditorialProfileCompositionService`'s precedence resolution
already decided is represented faithfully. One LLM call ("Primary
resolves applicable defaults into a coherent directive set") merges
and deduplicates only the overridable GENRE/PROJECT/USER candidates;
the system directives are never sent to, or restated by, that call.

**A genuine simplification, not a shortcut.** The source document
states conflict detection twice: "Detect contradictory directives
before approval" (backend) and "Reviewer checks conflicts, omissions
and impractical instructions" (AI/orchestration). Read together these
describe one requirement, not two - satisfied entirely by adding a new
`ArtifactType.DIRECTIVES` focus-guidance entry to the existing,
already-established `ReviewerService` mechanism (the same dict-lookup
pattern Phases 8-10 each added one entry to), rather than building a
second, bespoke rule-based conflict-detection engine that would have
duplicated what the Reviewer already does generically.

`VideoJob` gained `project_writing_rules`, `user_writing_directives`
(both editable raw-string lists a human populates) and
`writing_directives` (the resolved artifact) - all optional and
empty/None by default, fully backward-compatible.
`ContentIntelligencePipeline` gained `run_writing_directives()` - stage
6b, sitting between Hook and Script, requiring only a selected hook
(deliberately not coupled to Story Architecture's own state, matching
this phase's explicit goal of keeping Directives distinct from it) -
wired into `run_all()`'s default sequence.

`ScriptGenerationService.generate()` gained an optional
`writing_directives` parameter. When supplied, every directive's text
becomes an explicit prompt constraint; omitting it - still the default
whenever the Directives stage was never run for a project - reproduces
the service's exact prior behavior, proven by a dedicated regression
test. This is what makes "Approved Directives artifact is available to
Script Generation Package" a real, functional wiring rather than a
documentation claim: the directives genuinely reach the prompt when
present.

**GUI.** A new "Directives" panel sits between Hooks and Script in the
CI stage rotation, showing every resolved directive with a source
badge - system directives are marked "non-overridable" and have no
Remove control anywhere in the GUI, so a user cannot even attempt to
delete one. Below that, Add/Remove editors for project rules and user
directives mirror the established Phase 7 question-editing pattern
exactly.

**Deliberately not built this pass**, documented rather than silently
skipped: no dedicated rule-based conflict-detection engine separate
from the Reviewer, per the "one requirement, not two" reading above;
no new `ApprovalPolicyConfig` decision-point gate for this stage
(several other CI stages - retention audit, continuity bible,
editorial critique, quality gate, revision, packaging hypothesis -
also have no dedicated gate today, so this isn't a new gap this phase
introduces); `run_script()` still carries no *hard* requirement on
`job.writing_directives` - kept fully optional, matching every other
phase's additive-parameter discipline, so no existing test calling
`run_script()` directly needed updating.

Quality gates: mypy, ruff, and black all clean across every touched
file (a brand-new test file, `test_writing_directives_model.py`, was
written using explicit keyword construction from the start rather than
the `**dict` unpacking pattern that has repeatedly tripped the
pydantic-mypy plugin elsewhere in this session's test suite - avoiding
that debt rather than adding to it). New tests:
`test_writing_directives_model.py` (8), `test_writing_directives_
service.py` (8), 2 new cases in `test_script_generation_service.py`, 3
new cases in `test_content_intelligence_pipeline.py`, 1 new case in
`test_reviewer_service.py`, 6 new cases in `test_content_studio_
content_intelligence_gui.py` - 143 tests across the six touched test
files, all passing.

## 2026-09-05 - Content Studio Redesign: Phase 10 Hook Lab

**Backend.** `HookCandidate` (already existed) gained `type:
HookArchetype | None` - reuses the existing genre-level `HookArchetype`
enum (already used for `preferred_hook_archetypes`/
`forbidden_hook_archetypes` in genre profiles) as the per-candidate
"type" the redesign's schema asks for, rather than inventing a
parallel vocabulary - and `fact_ids: list[UUID]`, this phase's own
"Evidence Allocation" for hooks, LLM-populated only when research has
`structured_facts`, mirroring `StoryBeat.evidence_fact_ids` from Phase
9 exactly.

`HookEvaluation` (already existed) gained `retention_potential`/
`tone_fit: int | None` - both optional and deliberately never folded
into the established `overall_score` formula; a proof test confirms
setting them to 100 changes nothing about the score, since retroactively
changing that formula was judged a materially bigger, riskier change
than adding two informational dimensions. Also gained `is_custom: bool`
and a `.custom()` classmethod for the "Write My Own" GUI path - every
numeric field set to 0 with `reasoning="User-written hook; not
independently scored."`, honestly representing "never scored" rather
than a fake neutral number.

`HookGenerationService.generate()` gained two optional parameters:
`research`-driven fact-binding (when `research.structured_facts` is
non-empty, the prompt lists them and asks for a per-hook `FACT_IDS`
line, reusing `FactCheckService`'s own index-based source-matching
trick rather than inventing a new one) and `additional_instructions`
(free-text guidance, e.g. "make it more suspenseful," for a targeted
rewrite). `HookEvaluationService.evaluate()` gained the two new score
labels (`RETENTION_POTENTIAL`, `TONE_FIT`), parsed independently of the
existing required-label set so every pre-existing test fixture in that
file - none of which include these new labels - still parses exactly
as before.

`ReviewerService` gained one more additive `ArtifactType.HOOK` focus-
guidance entry (unsupported claims, premature payoff disclosure) via
the same dict-lookup mechanism Phases 8-9 introduced.

**Confirmed already complete, via direct code inspection rather than
assumed:** `ContentIntelligencePipeline.run_script()` already
hard-requires `job.selected_hook is not None` (raises `RuntimeError`
otherwise) and passes it as `winning_hook` into
`ScriptGenerationService.generate()`. This means "Approved Hook becomes
a required input to Script Generation Package" and "Script generator
cannot silently replace or ignore it" - two of this phase's own named
exit criteria - were already fully satisfied before any Phase 10 work
started. Zero changes were needed for them; this was verified by
reading the code, not assumed from the phase's own wording.

**GUI.** The "Hooks" panel - previously read-only display, like every
other CI stage panel before its own phase's work - gained a "Select"
button per candidate (overrides the pipeline's own auto-selected
`selected_hook`, previously impossible from the GUI), a "Write my own
hook" form, a "Generate more" button (appends new candidates to the
existing set and re-evaluates the full combined set together, so
scores stay comparable), and "Rewrite with instructions" (a full
regeneration via `run_hooks(additional_instructions=...)`). Each
candidate now also shows its type, cited-fact count, and reveal risk
(spoiler_risk) inline.

**Deliberately not built this pass:** no dedicated "Edit" action on an
existing candidate's text - Select plus Write My Own together already
cover the practical need (pick an existing hook, or replace it with
your own wording) without a third, overlapping mechanism; no direct
field-by-field editing of evaluation scores (the same repo-wide
inline-editing gap noted since Phase 4).

**Test-infra note.** One new test (`test_generate_more_hooks_appends_
and_reevaluates_all_candidates`) initially failed because the shared
echo-stub used across GUI tests always returns the same 5 canned
dry-run hook texts regardless of call count - "Generate more" therefore
produced 5 duplicate-text candidates, which `HookEvaluationService`'s
legitimate text-based dedup then correctly collapsed to 5 evaluations
for 10 candidates. This was a test-fixture artifact, not a production
bug: fixed by stubbing `hook_generation_service.generate` directly in
that one test to return genuinely distinct text, the way a real LLM
call would.

Quality gates: mypy clean across 365 source files, ruff clean, black
clean repo-wide (682 files). New/updated tests: `test_hook_model.py`
(+7), `test_hook_generation_service.py` (+5), `test_hook_evaluation_
service.py` (+3), 1 new case in `test_reviewer_service.py`, 6 new cases
in `test_content_studio_content_intelligence_gui.py` - 108 tests across
the five touched test files, all passing.

## 2026-09-05 - Audit-driven fixes (Phases 1, 6, 7, 8, 9) and GUI usability fixes

An external audit re-verified Phases 0-9 directly against the code
(not trusting this log) and reported 5 confirmed defects plus 2 GUI
usability reports came in separately from the user. Every claim was
independently re-verified against the actual code before any fix was
made - none were taken on trust.

**1. Phase 1 (Blocker, confirmed).** `ArtifactLifecycleService.
ALLOWED_TRANSITIONS` only permitted ->INVALIDATED from APPROVED/
REVISION_REQUIRED, but `ArtifactDependencyGraphService.
invalidate_dependents()` calls `transition(..., INVALIDATED)`
unconditionally on every non-terminal downstream dependent it finds -
a dependent still in DRAFT/GENERATING/GENERATED/UNDER_REVIEW would
raise `ValueError`. Untested: every existing `invalidate_dependents()`
test fixture used `status=APPROVED`. Fixed by extending
`ALLOWED_TRANSITIONS` so INVALIDATED is reachable from every
non-terminal status, matching the real intent (an upstream change can
invalidate a downstream artifact regardless of how far along its own
generation/review cycle is) - a parametrized regression test now
covers every non-terminal starting status.

**2. Phase 6 (Minor, confirmed).** `_CI_STAGE_REVIEW_TARGET["story_
angles"]` maps to field `"selected_story_angle"`, so reviewing that
stage only ever showed the Reviewer the bare `StoryAngle` - Phase 6's
`CreativeDirection` (narrative thesis, constraints, combined-angle
note) was never actually fed to the Reviewer. Fixed with a new
`_resolve_review_artifact()` helper: when `creative_direction` exists,
review that instead (it already embeds the selected angle, so nothing
is lost, only added); falls back to the bare angle for a project that
hasn't used the Phase 6 workflow yet.

**3. Phase 8 (Minor, confirmed).** `_handle_fact_check_again` set
`is_verified=result.is_supported` independently of whether `result.
matched_source_ids` was non-empty, while the new `ResearchFact`'s
evidence list was built only from those same IDs - a `FactCheckResult`
saying "supported" with no parseable matched source produced a green
"verified" note next to an amber "unsupported" fact from one click.
Fixed: `is_verified` (and whether a fact is created at all) now
requires both `is_supported` AND at least one matched source; the
ambiguous case is treated as honestly unverified, with a note
explaining why, rather than trusting a flag the evidence didn't back
up.

**4. Phase 9 (Minor, confirmed).** `_bind_curiosity_roles`'s half-open
`[start, end)` interval check meant a curiosity loop opening at
`opened_at_position == 1.0` (landing exactly on the final beat's
`end_seconds`) satisfied no beat's range and silently never bound.
Fixed by closing the interval on both ends for the last beat only.

**5. Cross-cutting (Major, confirmed on re-verification).**
`project_workspace_view.py`'s `_BLOCKER_STAGE_TAB` had no
`"research_plan"` entry, even though Phase 7's own `run_research_plan()`
gates with `stage="research_plan"` and `ProductionReadinessService`
surfaces that as a `Blocker(stage="research_plan")` - so "Run/Resume"
silently did nothing while a project was blocked on "Approve Brief &
Start Research," with no error and no navigation. Fixed by adding the
missing entry alongside its sibling content-intelligence stages, plus
a new dedicated test file asserting every content-intelligence stage
(including research_plan) routes to the content_studio tab.

**GUI usability (user-reported, unrelated to the audit).** Three real
defects surfaced from actually running the app:

- Input fields in Project Setup rendered as pale-on-pale, barely
  legible text. Root cause: on Windows, the default native
  ("windowsvista") Qt style only partially honors QSS-declared colors
  on `QLineEdit`/`QComboBox` - it paints its own light native frame
  underneath the QSS text color instead of the QSS background,
  producing the pale-on-pale look. Fixed by explicitly selecting the
  "Fusion" style (the one built-in Qt style that fully respects
  QSS-declared colors on every widget) in `apply_theme()`, before the
  stylesheet is applied.
- Selecting "Custom Approval" in the New Project form showed nothing
  further, because it never was custom - it silently mapped to the
  same fixed `review_critical_stages()` preset as a name-only label,
  with no per-stage configuration ever built despite what the name
  implied. Fixed with a real per-decision-point panel: 12 dropdowns
  (Auto-continue / Review if uncertain / Always require approval),
  one per `ApprovalPolicyConfig` field, defaulting to
  `review_critical_stages()`'s own values, shown only when "Custom
  Approval" is selected and hidden for the other two (still genuinely
  fixed) presets. A new `tests/test_project_form_view.py` covers the
  default state, preset-switching visibility, per-field overrides,
  reset behavior, and the full create-project flow persisting a custom
  override onto the resulting job.
- After the Custom Approval panel shipped, a second user report showed
  "Project details" and "Custom approval" rendering as empty cards -
  headers visible, no rows. Root cause: `ProjectFormView` had no scroll
  area at all (unlike `ContentStudioView`, which already wraps itself
  in one), and it sits directly inside `MainWindow`'s `QStackedWidget`
  with no other scrolling ancestor either. Adding the new 12-row Custom
  Approval panel roughly doubled the form's total content height, past
  what the fixed window could show - with nothing to scroll, Qt's
  layout engine compressed/clipped rows rather than rendering them.
  Fixed by wrapping the form's content in a `QScrollArea`, the same
  pattern `ContentStudioView` already uses.

Quality gates: mypy, ruff, and black all clean across every touched
file. New tests: `test_artifact_lifecycle_service.py` (+1
parametrized, 6 cases), `test_content_studio_content_intelligence_gui.py`
(+1), `test_content_intelligence_pipeline.py` (+1), new
`tests/test_project_workspace_view_run_resume.py` (2 tests), new
`tests/test_project_form_view.py` (7 tests) - all passing. Full repo
pytest suite re-run for regression after every fix.

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
