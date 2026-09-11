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
from src.models.provider_profile import ProviderCategory, ProviderProfile
from src.models.upload_settings import UploadSettings
from src.models.video_settings import VideoSettings
from src.models.visual_settings import VisualSettings
from src.models.voice_settings import VoiceSettings
from src.providers.dry_run_voice_provider import DryRunVoiceProvider
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
from src.services.secrets.provider_secret_manager import InMemorySecretStore


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


def test_build_production_runtime_no_override_behavior_unchanged() -> None:
    """
    Regression guard for the ProviderAdapterFactory wiring restructure.

    With no voice_providers/music_providers/sound_effect_providers
    override (today's common case - no real provider profiles
    configured), build_production_runtime() must fall back to exactly
    the same providers RuntimeConfigurationLoader would have produced
    on its own: a single DryRunVoiceProvider in dry-run mode, and no
    music/sound-effect providers at all (those stages are skipped,
    matching the existing non-fatal design for optional stages).
    """

    runtime = build_production_runtime(
        asset_workflow_service=_fake_asset_workflow_service(),
        genre_timeline_service=_fake_genre_timeline_service(),
        settings=_settings(),
    )

    assert len(runtime.voice_generation_service.providers) == 1
    assert isinstance(
        runtime.voice_generation_service.providers[0], DryRunVoiceProvider
    )


def test_build_production_runtime_voice_providers_override_is_used() -> None:
    """A given voice_providers override must reach VoiceGenerationService."""

    class _FakeVoiceProvider(DryRunVoiceProvider):
        @property
        def provider_name(self) -> str:
            return "fake_override_voice"

    fake_provider = _FakeVoiceProvider()

    runtime = build_production_runtime(
        asset_workflow_service=_fake_asset_workflow_service(),
        genre_timeline_service=_fake_genre_timeline_service(),
        settings=_settings(),
        voice_providers=[fake_provider],
    )

    assert runtime.voice_generation_service.providers == [fake_provider]


def test_build_production_runtime_no_voice_profiles_override_stays_minimal() -> None:
    """
    Regression guard: with no voice_profiles override,
    build_production_runtime() must reproduce RuntimeConfigurationLoader's
    own deliberately-minimal default exactly (see
    test_load_includes_default_voice_profile) - this is a documented,
    tested characteristic of the loader itself, not something this
    function should silently widen on its own.
    """

    runtime = build_production_runtime(
        asset_workflow_service=_fake_asset_workflow_service(),
        genre_timeline_service=_fake_genre_timeline_service(),
        settings=_settings(),
    )

    profile_ids = [
        profile.profile_id
        for profile in runtime.voice_resolution_runtime.voice_profile_registry.list_all()
    ]

    assert profile_ids == ["voice.neutral_narrator"]


def test_build_production_runtime_voice_profiles_override_is_used() -> None:
    """
    2026-09-11 real fix, found live while verifying dynamic voice
    selection: a real caller (the desktop app) must be able to supply
    the full genre-linked voice-profile set, or every genre-specific
    voice_profile_id silently falls back to voice.neutral_narrator in
    real generation before any pin or dynamic search is ever consulted.
    """

    from src.models.voice_profile import VoiceProfile

    override_profile = VoiceProfile(
        profile_id="voice.test_override",
        display_name="Test Override",
        fallback_profile_id=None,
    )

    runtime = build_production_runtime(
        asset_workflow_service=_fake_asset_workflow_service(),
        genre_timeline_service=_fake_genre_timeline_service(),
        settings=_settings(),
        voice_profiles=[override_profile],
    )

    profile_ids = [
        profile.profile_id
        for profile in runtime.voice_resolution_runtime.voice_profile_registry.list_all()
    ]

    assert profile_ids == ["voice.test_override"]


_FAKE_CLAUDE_SECRET_REFERENCE = "secret://providers/claude/fake"


def _fake_llm_provider_profile() -> ProviderProfile:
    return ProviderProfile(
        profile_id="claude",
        display_name="Claude",
        provider_name="anthropic",
        category=ProviderCategory.LLM,
        enabled=True,
        secret_reference=_FAKE_CLAUDE_SECRET_REFERENCE,
    )


def _secret_store_with_fake_claude_secret() -> InMemorySecretStore:
    store = InMemorySecretStore()
    store.save(_FAKE_CLAUDE_SECRET_REFERENCE, "fake-anthropic-key")

    return store


def test_build_production_runtime_require_llm_key_false_avoids_the_raise() -> None:
    """
    2026-09-11 real fix, found live running the first real non-dry-run
    end-to-end test: a caller with its own real, keyring-backed LLM
    profiles (not env-var keys) must not be forced through the
    loader's "no key configured" raise, and must be able to supply
    those real profiles directly via the new provider_profiles
    override rather than only via post-construction registry mutation
    (ProductionApplicationFactory itself requires at least one
    non-empty provider profile at construction time).
    """

    fake_voice_provider = DryRunVoiceProvider()

    runtime = build_production_runtime(
        asset_workflow_service=_fake_asset_workflow_service(),
        genre_timeline_service=_fake_genre_timeline_service(),
        settings=_settings(MISSION_AUTOMATION_DRY_RUN=False),
        secret_store=_secret_store_with_fake_claude_secret(),
        provider_profiles=[_fake_llm_provider_profile()],
        voice_providers=[fake_voice_provider],
        require_llm_key=False,
        require_voice_provider=False,
    )

    assert isinstance(runtime, ProductionApplicationRuntime)
    assert [
        profile.profile_id
        for profile in runtime.infrastructure.provider_registry.list_all()
    ] == ["claude"]
    assert runtime.voice_generation_service.providers == [fake_voice_provider]


def test_build_production_runtime_no_provider_profiles_override_stays_the_loader_default() -> (
    None
):
    """
    Regression guard, mirroring voice_profiles' own equivalent test:
    with no provider_profiles override, this function must reproduce
    RuntimeConfigurationLoader's own default exactly (the harmless
    dry-run placeholder in dry-run mode).
    """

    runtime = build_production_runtime(
        asset_workflow_service=_fake_asset_workflow_service(),
        genre_timeline_service=_fake_genre_timeline_service(),
        settings=_settings(),
    )

    profile_ids = [
        profile.profile_id
        for profile in runtime.infrastructure.provider_registry.list_all()
    ]

    assert profile_ids == ["provider.llm.dry_run"]


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
    the Render Workspace: a first execute() call populates scene asset
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
