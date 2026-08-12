from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from src.config.settings import Settings
from src.entrypoint import build_production_runtime, main
from src.models.advanced_settings import AdvancedSettings
from src.models.audience_settings import AudienceSettings
from src.models.budget_settings import BudgetSettings
from src.models.duration_config import DurationConfig, DurationMode
from src.models.general_settings import GeneralSettings
from src.models.music_settings import MusicSettings
from src.models.packaging_settings import PackagingSettings
from src.models.project_specification import ProjectSpecification
from src.models.provider_preferences import ProviderPreferences
from src.models.upload_settings import UploadSettings
from src.models.video_settings import VideoSettings
from src.models.visual_settings import VisualSettings
from src.models.voice_settings import VoiceSettings
from src.services.genre_timeline_pipeline_service import (
    GenreTimelinePipelineService,
)
from src.services.mission_application_service import (
    MissionApplicationService,
)
from src.services.production_application_factory import (
    ProductionApplicationRuntime,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "OPENAI_API_KEY": "",
        "CLAUDE_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "ELEVENLABS_API_KEY": "",
        "MISSION_AUTOMATION_DRY_RUN": True,
    }

    defaults.update(overrides)

    return Settings(**defaults)  # type: ignore[arg-type]


def _fake_asset_workflow_service() -> SceneAssetWorkflowService:
    return cast(SceneAssetWorkflowService, object())


def _fake_genre_timeline_service() -> GenreTimelinePipelineService:
    return cast(GenreTimelinePipelineService, object())


def test_build_production_runtime_returns_complete_runtime() -> None:
    runtime = build_production_runtime(
        asset_workflow_service=_fake_asset_workflow_service(),
        genre_timeline_service=_fake_genre_timeline_service(),
        settings=_settings(),
    )

    assert isinstance(runtime, ProductionApplicationRuntime)
    assert isinstance(runtime.application, MissionApplicationService)


def test_build_production_runtime_propagates_loader_errors() -> None:
    with pytest.raises(ValueError, match="No LLM provider API key"):
        build_production_runtime(
            asset_workflow_service=_fake_asset_workflow_service(),
            genre_timeline_service=_fake_genre_timeline_service(),
            settings=_settings(MISSION_AUTOMATION_DRY_RUN=False),
        )


def test_main_succeeds_in_dry_run_with_no_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(settings=_settings())

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "startup check passed" in output
    assert "provider.llm.dry_run" in output


def test_main_fails_outside_dry_run_even_with_a_real_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # RuntimeConfigurationLoader.load() builds the entire
    # RuntimeConfiguration eagerly, including voice_providers, even
    # though main() never uses that field. Outside dry-run this still
    # fails today because of the voice-provider gap documented in
    # RuntimeConfigurationLoader - see
    # test_load_outside_dry_run_raises_for_voice_provider.
    exit_code = main(
        settings=_settings(
            OPENAI_API_KEY="sk-real-openai-key",
            MISSION_AUTOMATION_DRY_RUN=False,
        ),
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "voice-provider adapter" in captured.err


def test_main_fails_outside_dry_run_with_no_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        settings=_settings(MISSION_AUTOMATION_DRY_RUN=False),
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "startup check failed" in captured.err
    assert "No LLM provider API key" in captured.err


def test_build_production_runtime_default_infrastructure_completes_execute() -> None:
    """
    Proves the render-pipeline composition gap is genuinely closed.

    build_production_runtime() is called with no asset_workflow_service
    or genre_timeline_service override, so it must build its own
    default local-first infrastructure via
    SceneAssetAndTimelineInfrastructureFactory. The resulting
    MissionApplicationService.execute() is then run end to end in
    dry-run mode, exercising research, script, originality review,
    scene planning, voice, asset selection, timeline, and render - the
    full path that had no production construction path before.
    """

    runtime = build_production_runtime(settings=_settings())

    specification = ProjectSpecification(
        general=GeneralSettings(
            project_name="Deep Sea Documentary",
            channel_name="Ocean Channel",
            topic="Deep sea creatures",
            video_type="long-form documentary",
        ),
        duration=DurationConfig(
            mode=DurationMode.EXACT,
            target_duration_seconds=600,
        ),
        audience=AudienceSettings(
            language="English",
            target_country="United States",
            target_audience="General audience",
        ),
        video=VideoSettings(),
        visual=VisualSettings(),
        voice=VoiceSettings(),
        music=MusicSettings(),
        providers=ProviderPreferences(),
        upload=UploadSettings(),
        packaging=PackagingSettings(),
        budget=BudgetSettings(),
        advanced=AdvancedSettings(),
    )

    result = runtime.application.execute(
        specification,
        niche="ocean-life",
        genre_id="genre.default",
        dry_run=True,
    )

    assert result.job.research is not None
    assert result.job.script is not None
    assert result.job.scenes


def test_dry_run_render_succeeds_end_to_end_with_manual_upload() -> None:
    """
    Proves every render-pipeline gap closed this session actually adds
    up to a genuinely successful render, not just "gets further than
    before": composition (SceneAssetAndTimelineInfrastructureFactory),
    the asset-to-timeline bridge (SceneAssetVideoClipBuilderService),
    the transition.cut no-op fix, and dry-run rendering using the
    legacy RenderService instead of real FFmpeg (which would otherwise
    fail trying to read dry-run voice generation's placeholder
    "dry-run://voice/..." paths as real audio).

    Mirrors the exact manual round trip a desktop user drives through
    ProjectDetailView: a first execute() call populates scene asset
    states and pauses waiting for upload decisions; a second execute()
    call on the same VideoJob, with those decisions attached as
    user_input, resumes from the paused stage instead of restarting
    the whole pipeline.
    """

    runtime = build_production_runtime(
        settings=_settings(),
        checkpoint_storage_root=(
            Path(__file__).resolve().parent
            / ".pytest_checkpoints"
            / "dry_run_render_manual_upload"
        ),
    )

    specification = ProjectSpecification(
        general=GeneralSettings(
            project_name="Deep Sea Documentary",
            channel_name="Ocean Channel",
            topic="Deep sea creatures",
            video_type="long-form documentary",
        ),
        duration=DurationConfig(
            mode=DurationMode.EXACT,
            target_duration_seconds=600,
        ),
        audience=AudienceSettings(
            language="English",
            target_country="United States",
            target_audience="General audience",
        ),
        video=VideoSettings(),
        visual=VisualSettings(),
        voice=VoiceSettings(),
        music=MusicSettings(),
        providers=ProviderPreferences(),
        upload=UploadSettings(),
        packaging=PackagingSettings(),
        budget=BudgetSettings(),
        advanced=AdvancedSettings(),
    )

    job = runtime.application.job_mapper.map(
        specification,
        niche="ocean-life",
    )
    job = runtime.application.content_pipeline.run(job)

    first_result = runtime.application.render_runtime_factory.build(
        job=job,
        genre_id="genre.default",
    ).execute(job, dry_run=True)

    assert first_result.success is False

    waiting_scene_numbers = [
        state.scene_number
        for state in job.scene_asset_states
        if state.requires_user_decision
    ]

    assert waiting_scene_numbers

    manual_upload_file = str(
        Path(__file__).resolve().parent.parent
        / "assets"
        / "videos"
        / "manual"
        / "scene_001.mp4"
    )

    asset_decisions = [
        {
            "scene_number": scene_number,
            "decision": "manual_upload",
            "manual_upload_path": manual_upload_file,
            "project_id": "deep-sea-documentary",
        }
        for scene_number in waiting_scene_numbers
    ]

    second_result = runtime.application.render_runtime_factory.build(
        job=job,
        genre_id="genre.default",
    ).execute(
        job,
        dry_run=True,
        user_input={"asset_decisions": asset_decisions},
    )

    assert second_result.success is True
    assert second_result.status.value == "completed"
    assert second_result.render_result is not None
    assert second_result.render_result.success is True
    assert second_result.render_result.output_file is not None
