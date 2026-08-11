from __future__ import annotations

from typing import cast

import pytest

from src.config.settings import Settings
from src.entrypoint import build_production_runtime, main
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
