"""
Formal invalidation-matrix regression tests (docs/REMAINING_GAPS.md
Phase 10). tests/test_invalidation_service.py already covers
InvalidationService's own matrix logic exhaustively in isolation -
calling on_script_changed()/on_scene_replaced()/on_audio_regenerated()
directly. What was still untested anywhere is the *wiring*: does each
real production call site actually invoke InvalidationService at all,
with the right trigger, at the right point in its own method? This
file drives the real services (ContentIntelligencePipeline,
BulkStockAssignmentService, BulkClipIngestionService,
MediaGenerationPipeline) end to end and asserts on job.stale_artifacts
afterward, rather than calling InvalidationService directly.
"""

from __future__ import annotations

from pathlib import Path

from src.models.approval import ApprovalPolicyConfig
from src.models.asset_index import AssetIndex
from src.models.bulk_clip_ingestion import BulkClipIngestionEntryStatus
from src.models.bulk_stock_assignment import BulkStockAssignmentEntryStatus
from src.models.invalidation import StaleArtifact
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.render_result import RenderResult
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.models.voice_profile import VoiceProfile
from src.providers.dry_run_music_provider import DryRunMusicProvider
from src.providers.dry_run_sound_effect_provider import DryRunSoundEffectProvider
from src.providers.dry_run_stock_download_opener import dry_run_stock_download_opener
from src.providers.dry_run_voice_provider import DryRunVoiceProvider
from src.providers.stock_footage_provider import StockFootageProvider
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
from src.services.asset_storage_service import AssetStorageService
from src.services.bulk_clip_ingestion_service import BulkClipIngestionService
from src.services.bulk_stock_assignment_service import BulkStockAssignmentService
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.genre_timeline_pipeline_service import GenreTimelinePipelineService
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.invalidation_service import InvalidationService
from src.services.llm.llm_service import LLMServiceResult
from src.services.local_asset_search_service import LocalAssetSearchService
from src.services.manual_upload_service import ManualUploadService
from src.services.media_generation_pipeline import MediaGenerationPipeline
from src.services.music_generation_service import MusicGenerationService
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.sound_effect_generation_service import SoundEffectGenerationService
from src.services.stock_acquisition_service import StockAcquisitionService
from src.services.stock_asset_storage_service import StockAssetStorageService
from src.services.stock_download_service import StockDownloadService
from src.services.stock_search_service import DryRunStockProvider, StockSearchService
from src.services.visual_asset_router import VisualAssetRouter
from src.services.voice_generation_service import VoiceGenerationService
from src.services.voice_resolution_runtime import VoiceResolutionRuntimeFactory
from src.services.voice_timeline_service import VoiceTimelineService
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


class _EchoStubLLMService:
    """Mirrors test_content_intelligence_pipeline.py's stub."""

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        content = request.dry_run_response or ""

        if request.metadata.get("agent") == "AudiencePromiseService":
            content = content.replace(
                "PROMISE_STRENGTH: moderate", "PROMISE_STRENGTH: strong"
            )
        elif request.metadata.get("agent") == "ResearchAgent":
            content = "The Mary Celeste was found adrift, seaworthy, with no crew."

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=content,
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="test-profile",
            all_providers_failed=False,
        )


class _FindingStubLLMService:
    """Mirrors test_content_intelligence_pipeline.py's stub of the same
    name: EditorialCritiqueService's own dry-run response has no
    findings, and ScriptRevisionService requires at least one to act
    on - so revision-focused tests need a critique with a real
    finding attached."""

    def __init__(self) -> None:
        self.echo = _EchoStubLLMService()

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        if request.metadata.get("agent") == "EditorialCritiqueService":
            content = (
                "FACTUAL_CONFIDENCE: 80\n"
                "HOOK_STRENGTH: 80\n"
                "RETENTION_ARCHITECTURE: 80\n"
                "EMOTIONAL_PROGRESSION: 80\n"
                "RESEARCH_GROUNDING: 80\n"
                "NARRATIVE_COHERENCE: 80\n"
                "AUDIENCE_FIT: 80\n"
                "VISUAL_OPPORTUNITY_DENSITY: 80\n"
                "CHARACTER_DEPTH: 80\n"
                "PAYOFF_STRENGTH: 80\n"
                "CONTINUITY: 80\n"
                "---\n"
                "DIMENSION: narrative_coherence\n"
                "SEVERITY: blocking\n"
                "SEGMENT_NUMBER: none\n"
                "PROBLEM: Unsupported claim about the crew's fate.\n"
                "REASON: No source in research backs this claim.\n"
                "RECOMMENDED_CORRECTION: Remove or attribute the claim."
            )

            result = LLMCallResult(
                status=LLMCallStatus.SUCCESS,
                provider=LLMProvider.OPENAI,
                model="test-model",
                content=content,
            )

            return LLMServiceResult(
                result=result,
                selected_profile_id="test-profile",
                all_providers_failed=False,
            )

        return self.echo.generate(
            request,
            estimated_cost_usd=estimated_cost_usd,
            profile_ids=profile_ids,
        )


def _ci_job() -> VideoJob:
    return VideoJob(
        project_name="Mary Celeste Documentary",
        channel_name="Maritime Mysteries",
        niche="unsolved maritime disappearances",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
        target_audience="mystery enthusiasts",
        approval_policy=ApprovalPolicyConfig.full_auto(),
    )


def test_run_revision_invalidates_only_the_downstream_artifacts_that_exist() -> None:
    pipeline = ContentIntelligencePipeline(
        llm_service=_FindingStubLLMService()  # type: ignore[arg-type]
    )

    job = pipeline.run_audience_promise(_ci_job())
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)
    job = pipeline.run_hooks(job)
    job = pipeline.run_script(job)
    job = pipeline.run_editorial_critique(job)

    assert job.generated_script is not None
    assert job.editorial_critique is not None

    # Simulate a user who already ran scene planning and clip
    # resolution before going back for another revision pass - the
    # exact re-entry scenario on_script_changed() exists to catch.
    job.scenes = [
        Scene(
            scene_number=1,
            title="Scene one",
            narration="Something happens.",
            visual_prompt="A dark hallway.",
            estimated_duration_seconds=8,
        )
    ]
    job.video_clips = [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=5,
            local_file="clip.mp4",
        )
    ]
    job.video_timeline = VideoTimeline()

    pipeline.run_revision(job)

    stale_names = {record.artifact for record in job.stale_artifacts}
    assert stale_names == {"scenes", "video_clips", "video_timeline"}
    assert all(record.triggered_by == "script_change" for record in job.stale_artifacts)


def _scene(number: int) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration="Narration.",
        visual_prompt="A cinematic visual.",
        estimated_duration_seconds=8,
        status=SceneStatus.READY,
    )


def _stock_workflow_service(tmp_path: Path) -> SceneAssetWorkflowService:
    asset_search_service = AssetSearchService(
        stock_search_service=StockSearchService(providers=[DryRunStockProvider()])
    )
    router = VisualAssetRouter(
        providers=[
            StockFootageProvider(
                asset_search_service=asset_search_service,
                stock_acquisition_service=StockAcquisitionService(
                    download_service=StockDownloadService(
                        temporary_directory=tmp_path / "downloads",
                        opener=dry_run_stock_download_opener,
                    ),
                    storage_service=StockAssetStorageService(
                        storage_root=tmp_path / "storage",
                        asset_index=AssetIndex(),
                    ),
                ),
            ),
        ],
    )

    return SceneAssetWorkflowService(
        asset_manager=AssetManager(LocalAssetSearchService(AssetIndex())),
        decision_service=AssetDecisionService(),
        asset_search_service=asset_search_service,
        visual_asset_router=router,
    )


def _job_with_a_stale_render_result(*scenes: Scene) -> VideoJob:
    job = VideoJob(
        project_name="ocean-project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )
    job.scenes = list(scenes)
    job.video_timeline = VideoTimeline()
    job.render_result = RenderResult(render_engine="ffmpeg")

    return job


def test_bulk_stock_assignment_invalidates_video_timeline_and_render_result(
    tmp_path: Path,
) -> None:
    job = _job_with_a_stale_render_result(_scene(1), _scene(2))
    service = BulkStockAssignmentService(
        asset_workflow_service=_stock_workflow_service(tmp_path)
    )

    result = service.assign(job=job, scene_numbers=[1, 2])

    assert all(
        entry.status == BulkStockAssignmentEntryStatus.ASSIGNED
        for entry in result.entries
    )
    stale_names = {record.artifact for record in job.stale_artifacts}
    assert "video_timeline" in stale_names
    assert "render_result" in stale_names
    # scene_asset_states/video_clips are cleared, not marked, since
    # this same call just rebuilt them fresh.
    assert "scene_asset_states" not in stale_names
    assert "video_clips" not in stale_names


def test_bulk_stock_assignment_clears_a_previously_stale_video_clips_flag(
    tmp_path: Path,
) -> None:
    job = _job_with_a_stale_render_result(_scene(1))
    job.stale_artifacts = [
        StaleArtifact(
            artifact="video_clips",
            reason="Pre-existing staleness from a prior script change.",
            triggered_by="script_change",
        )
    ]
    service = BulkStockAssignmentService(
        asset_workflow_service=_stock_workflow_service(tmp_path)
    )

    service.assign(job=job, scene_numbers=[1])

    assert InvalidationService.is_stale(job, "video_clips") is False


def _manual_upload_workflow_service(tmp_path: Path) -> SceneAssetWorkflowService:
    asset_search_service = AssetSearchService(
        stock_search_service=StockSearchService(providers=[DryRunStockProvider()])
    )
    index = AssetIndex()
    storage_service = AssetStorageService(
        storage_root=tmp_path / "project-assets", asset_index=index
    )
    manual_upload_service = ManualUploadService(
        storage_service=storage_service, maximum_file_size_bytes=10_000
    )

    return SceneAssetWorkflowService(
        asset_manager=AssetManager(LocalAssetSearchService(index)),
        decision_service=AssetDecisionService(),
        asset_search_service=asset_search_service,
        manual_upload_service=manual_upload_service,
    )


def test_bulk_clip_ingestion_invalidates_video_timeline_and_render_result(
    tmp_path: Path,
) -> None:
    source_directory = tmp_path / "inbox"
    source_directory.mkdir()
    (source_directory / "001_scene-1.mp4").write_bytes(b"clip-bytes")

    job = _job_with_a_stale_render_result(_scene(1))
    service = BulkClipIngestionService(
        asset_workflow_service=_manual_upload_workflow_service(tmp_path)
    )

    result = service.ingest(job=job, source_directory=source_directory)

    assert result.entries[0].status == BulkClipIngestionEntryStatus.ASSIGNED
    stale_names = {record.artifact for record in job.stale_artifacts}
    assert "video_timeline" in stale_names
    assert "render_result" in stale_names


def _neutral_voice_profile() -> VoiceProfile:
    return VoiceProfile(
        profile_id="voice.neutral_narrator",
        display_name="Neutral Narrator",
        fallback_profile_id=None,
    )


def _audio_pipeline() -> MediaGenerationPipeline:
    genre_registry = GenreProfileRegistryService.with_default_profiles()
    voice_resolution_runtime = VoiceResolutionRuntimeFactory().build(
        profiles=[_neutral_voice_profile()]
    )

    return MediaGenerationPipeline(
        voice_directive_generation_service=GenreVoiceDirectiveGenerationService(
            genre_registry=genre_registry,
            voice_profile_registry=voice_resolution_runtime.voice_profile_registry,
        ),
        voice_resolution_runtime=voice_resolution_runtime,
        voice_generation_service=VoiceGenerationService(
            providers=[DryRunVoiceProvider()]
        ),
        voice_timeline_service=VoiceTimelineService(),
        genre_timeline_service=GenreTimelinePipelineService(
            genre_directive_service=GenreDirectiveGenerationService(
                genre_registry=genre_registry
            ),
            directive_resolution_service=EditingDirectiveResolutionService(
                effect_registry=EffectRegistryService.with_default_presets()
            ),
        ),
        music_generation_service=MusicGenerationService(
            providers=[DryRunMusicProvider()]
        ),
        sound_effect_generation_service=SoundEffectGenerationService(
            providers=[DryRunSoundEffectProvider()]
        ),
    )


def _clip(number: int) -> VideoClip:
    return VideoClip(
        scene_number=number,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=8,
        prompt=f"Scene {number}",
        provider="Manual Upload",
        local_file=f"assets/videos/manual/scene_{number:03}.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


def _audio_job(*scenes: Scene) -> VideoJob:
    job = VideoJob(
        project_name="ocean-project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
        genre_id="genre.mystery",
    )
    job.scenes = list(scenes)

    return job


def test_run_voice_invalidates_render_result_via_audio_regeneration() -> None:
    job = _audio_job(_scene(1))
    job.render_result = RenderResult(render_engine="ffmpeg")

    _audio_pipeline().run_voice(job)

    assert InvalidationService.is_stale(job, "render_result") is True


def test_run_music_invalidates_render_result_via_audio_regeneration() -> None:
    job = _audio_job(_scene(1))
    job.video_clips = [_clip(1)]
    pipeline = _audio_pipeline()
    pipeline.run_timeline(job)
    job.render_result = RenderResult(render_engine="ffmpeg")

    pipeline.run_music(job)

    assert InvalidationService.is_stale(job, "render_result") is True


def test_run_sound_effects_invalidates_render_result_via_audio_regeneration() -> None:
    job = _audio_job(_scene(1))
    job.video_clips = [_clip(1)]
    pipeline = _audio_pipeline()
    pipeline.run_timeline(job)
    job.render_result = RenderResult(render_engine="ffmpeg")

    pipeline.run_sound_effects(job)

    assert InvalidationService.is_stale(job, "render_result") is True
