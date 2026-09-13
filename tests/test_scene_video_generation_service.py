from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.asset_index import AssetIndex
from src.models.cinematic_prompt import CinematicPromptPackage, ResolvedCinematicPrompt
from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.models.media_strategy import SceneSourceType
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.models.scene import Scene
from src.models.scene_completeness import SceneCompletenessStatus
from src.models.video_job import VideoJob
from src.providers.external_ui_generation_provider import (
    ExternalUIGenerationProvider,
    ExternalUIOperation,
)
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
from src.services.google_flow_account_router_service import (
    GoogleFlowAccountRouterService,
)
from src.services.google_flow_generation_orchestrator_service import (
    GoogleFlowGenerationOrchestratorService,
)
from src.services.local_asset_search_service import LocalAssetSearchService
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_video_generation_service import SceneVideoGenerationService

_GOOD_PROBE = json.dumps(
    {
        "format": {"duration": "8.0"},
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio"},
        ],
    }
)

_TOO_SHORT_PROBE = json.dumps(
    {
        "format": {"duration": "0.1"},
        "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
    }
)


def _scene(number: int = 1, duration: int = 8) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=f"Narration for scene {number}.",
        visual_prompt=f"Visual prompt for scene {number}.",
        estimated_duration_seconds=duration,
    )


def _job(*scenes: Scene) -> VideoJob:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.horror",
    )
    job.scenes = list(scenes)
    return job


def _flow_profile() -> ProviderProfile:
    return ProviderProfile(
        profile_id="flow.primary",
        display_name="flow.primary",
        provider_name="Google Flow",
        category=ProviderCategory.EXTERNAL_UI_VIDEO,
        enabled=True,
        health_status=ProviderHealthStatus.HEALTHY,
        browser_profile_reference="flow_profiles/flow.primary",
    )


class _ScriptedProvider(ExternalUIGenerationProvider):
    """
    Submits straight to SUBMITTED, then replays a fixed queue of
    states from observe() (simulating real Flow polling, without a
    real wait) before finally settling.
    """

    def __init__(self, *, observe_sequence: list[GoogleFlowGenerationState]) -> None:
        self._observe_sequence = list(observe_sequence)
        self.observe_call_count = 0
        self.submitted_prompts: list[str] = []
        self.submitted_requests: list[GoogleFlowGenerationRequest] = []
        self.downloaded_file = "downloads/scene.mp4"

    @property
    def provider_name(self) -> str:
        return "Scripted Flow"

    def health_check(self) -> bool:
        return True

    @property
    def supported_operations(self) -> frozenset[ExternalUIOperation]:
        return frozenset(
            {
                ExternalUIOperation.SUBMIT,
                ExternalUIOperation.OBSERVE,
                ExternalUIOperation.DOWNLOAD,
            }
        )

    def check_profile_health(self, profile_id: str) -> bool:
        return True

    def submit(
        self,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.submitted_prompts.append(request.prompt)
        self.submitted_requests.append(request)

        current = attempt
        for state in (
            GoogleFlowGenerationState.SETTINGS_VERIFIED,
            GoogleFlowGenerationState.PROMPT_PREPARED,
            GoogleFlowGenerationState.SUBMITTING,
            GoogleFlowGenerationState.SUBMITTED,
        ):
            current = current.with_transition(state)

        return current

    def observe(
        self, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        self.observe_call_count += 1
        next_state = self._observe_sequence.pop(0)

        # A real Flow adapter only records a transition when the
        # state actually changed - "still generating" on this poll is
        # simply no change at all, not a same-state transition (which
        # the real state machine correctly rejects as illegal).
        if next_state == attempt.state:
            return attempt

        return attempt.with_transition(next_state)

    def download(
        self, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        return attempt.model_copy(
            update={"downloaded_file": self.downloaded_file}
        ).with_transition(GoogleFlowGenerationState.DOWNLOADED)

    def cancel_or_abandon(
        self, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        raise AssertionError("unreachable")


def _asset_workflow_service() -> SceneAssetWorkflowService:
    return SceneAssetWorkflowService(
        asset_manager=AssetManager(
            local_search_service=LocalAssetSearchService(asset_source=AssetIndex())
        ),
        decision_service=AssetDecisionService(),
        asset_search_service=AssetSearchService(),
    )


def _orchestrator(
    provider: _ScriptedProvider,
    *,
    probe_output: str = _GOOD_PROBE,
    registry: ProviderRegistry | None = None,
) -> GoogleFlowGenerationOrchestratorService:
    router = GoogleFlowAccountRouterService(
        registry or ProviderRegistry(profiles=[_flow_profile()])
    )

    return GoogleFlowGenerationOrchestratorService(
        provider=provider,
        account_router=router,
        technical_validation_service=MediaTechnicalValidationService(
            runner=lambda command: probe_output
        ),
    )


def _service(
    provider: _ScriptedProvider,
    *,
    probe_output: str = _GOOD_PROBE,
    max_poll_attempts: int = 10,
    registry: ProviderRegistry | None = None,
) -> SceneVideoGenerationService:
    return SceneVideoGenerationService(
        orchestrator=_orchestrator(
            provider, probe_output=probe_output, registry=registry
        ),
        asset_workflow_service=_asset_workflow_service(),
        registry=registry,
        poll_interval_seconds=1.0,
        max_poll_attempts=max_poll_attempts,
        sleep_fn=lambda _: None,
    )


def test_generate_one_submits_polls_downloads_validates_and_attaches(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    real_file = tmp_path / "scene.mp4"
    real_file.write_bytes(b"fake but present video bytes")
    provider.downloaded_file = str(real_file)

    service = _service(provider)
    job = _job(_scene(1))

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert provider.observe_call_count == 3
    assert job.video_clips
    assert job.video_clips[0].scene_number == 1
    assert job.video_clips[0].source_type == SceneSourceType.AI_GENERATE
    assert job.video_clips[0].local_file == str(real_file)

    latest = job.flow_generation_attempts[-1]
    assert latest.state == GoogleFlowGenerationState.READY


def test_generate_one_uses_the_compiled_cinematic_prompt_when_available() -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider)
    job = _job(_scene(1))
    job.cinematic_prompt_package = CinematicPromptPackage(
        script_lock_hash="a" * 64,
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash="a" * 64,
                prompt_text="A rich, continuity-aware cinematic prompt.",
            )
        ],
    )

    service.generate_one(job, 1)

    assert provider.submitted_prompts == ["A rich, continuity-aware cinematic prompt."]


def test_generate_one_falls_back_to_visual_prompt_without_a_compiled_package() -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider)
    job = _job(_scene(1))

    service.generate_one(job, 1)

    assert provider.submitted_prompts == ["Visual prompt for scene 1."]


def test_generate_one_clamps_duration_to_a_verified_flow_value() -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider)
    job = _job(_scene(1, duration=12))

    service.generate_one(job, 1)

    request = job.flow_generation_attempts[0].request
    assert request.execution_settings.duration_seconds == 10.0


def test_generate_one_passes_the_profiles_configured_model_family() -> None:
    """
    Real-world finding, 2026-09-13: a submission used to leave
    model_family unset entirely, so it silently used whatever model
    happened to already be selected in Flow's UI - a real generation
    failed on duration because the active model wasn't the one the
    operator configured on the profile. Confirm the service now reads
    it back from the one configured EXTERNAL_UI_VIDEO profile.
    """

    profile = _flow_profile().model_copy(
        update={"metadata": {"model_family": "Veo 3.1 - Lite [Lower Priority]"}}
    )
    registry = ProviderRegistry(profiles=[profile])

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider, registry=registry)
    job = _job(_scene(1))

    service.generate_one(job, 1)

    request = job.flow_generation_attempts[0].request
    assert request.execution_settings.model_family == "Veo 3.1 - Lite [Lower Priority]"


def test_generate_one_leaves_model_family_unset_without_a_registry() -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider)
    job = _job(_scene(1))

    service.generate_one(job, 1)

    request = job.flow_generation_attempts[0].request
    assert request.execution_settings.model_family is None


def test_generate_one_marks_a_failing_download_qc_failed_and_does_not_attach(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    real_file = tmp_path / "too_short.mp4"
    real_file.write_bytes(b"short")
    provider.downloaded_file = str(real_file)

    service = _service(provider, probe_output=_TOO_SHORT_PROBE)
    job = _job(_scene(1))

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.NEEDS_ATTENTION
    assert not job.video_clips
    assert job.flow_generation_attempts[-1].state == GoogleFlowGenerationState.QC_FAILED


def test_generate_one_does_not_resubmit_a_scene_already_at_ready(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    real_file = tmp_path / "scene.mp4"
    real_file.write_bytes(b"fake but present video bytes")
    provider.downloaded_file = str(real_file)

    service = _service(provider)
    job = _job(_scene(1))

    entry = service.generate_one(job, 1)
    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_prompts) == 1

    # Calling again for the same, now-READY scene must not resubmit -
    # create_attempt()'s own in-flight/idempotency guard aside, a
    # terminal READY attempt has nothing left for this service to do.
    service.generate_one(job, 1)
    assert len(provider.submitted_prompts) == 1


def test_generate_one_polls_an_existing_in_flight_attempt_without_resubmitting(
    tmp_path: Path,
) -> None:
    """
    A scene left GENERATING by an earlier call (or a previous process)
    must be observed/polled to completion, never resubmitted as a
    fresh attempt - Google Flow generation is real, metered work, and
    GoogleFlowGenerationLedgerService.create_attempt() would reject a
    genuine second submission for the same in-flight scene anyway.
    """

    provider = _ScriptedProvider(observe_sequence=[])
    real_file = tmp_path / "scene.mp4"
    real_file.write_bytes(b"fake but present video bytes")
    provider.downloaded_file = str(real_file)

    service = _service(provider)
    job = _job(_scene(1))

    # Seed an already-in-flight attempt directly, simulating a prior
    # call that left this scene mid-generation.
    seed_provider = _ScriptedProvider(observe_sequence=[])
    seed_orchestrator = _orchestrator(seed_provider)
    seed_orchestrator.submit_new_attempt(
        job,
        scene_number=1,
        prompt="seed",
        prompt_version="v1",
        idempotency_key="seed-key",
    )

    provider._observe_sequence = [
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
    ]

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert provider.submitted_prompts == []  # never resubmitted
    assert provider.observe_call_count == 2


def test_generate_one_raises_for_an_unknown_scene_number() -> None:
    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    with pytest.raises(ValueError, match="no scene numbered"):
        service.generate_one(job, 99)


def test_generate_all_processes_every_scene(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    real_file = tmp_path / "scene.mp4"
    real_file.write_bytes(b"fake but present video bytes")
    provider.downloaded_file = str(real_file)

    service = _service(provider)
    job = _job(_scene(1), _scene(2))

    report = service.generate_all(job)

    assert report.all_ready is True
    assert len(job.video_clips) == 2


def test_constructor_rejects_non_positive_poll_interval() -> None:
    provider = _ScriptedProvider(observe_sequence=[])

    with pytest.raises(ValueError, match="Poll interval"):
        SceneVideoGenerationService(
            orchestrator=_orchestrator(provider),
            asset_workflow_service=_asset_workflow_service(),
            poll_interval_seconds=0.0,
        )


def test_constructor_rejects_non_positive_max_poll_attempts() -> None:
    provider = _ScriptedProvider(observe_sequence=[])

    with pytest.raises(ValueError, match="Max poll attempts"):
        SceneVideoGenerationService(
            orchestrator=_orchestrator(provider),
            asset_workflow_service=_asset_workflow_service(),
            max_poll_attempts=0,
        )
