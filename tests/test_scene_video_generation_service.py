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
    GoogleFlowReferenceRole,
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
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.providers.external_ui_generation_provider import (
    ExternalUIGenerationProvider,
    ExternalUIOperation,
)
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
from src.services.asset_storage_service import AssetStorageService
from src.services.frame_extraction_service import FrameExtractionService
from src.services.google_flow_account_router_service import (
    GoogleFlowAccountRouterService,
    NoEligibleGoogleFlowAccountError,
)
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)
from src.services.google_flow_generation_orchestrator_service import (
    GoogleFlowAttemptCreditSensitiveError,
    GoogleFlowGenerationOrchestratorService,
)
from src.services.local_asset_search_service import LocalAssetSearchService
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService
from src.services.scene_video_generation_service import (
    SceneVideoGenerationService,
    _extend_last_beat_to_real_duration,
)

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

    def __init__(
        self,
        *,
        observe_sequence: list[GoogleFlowGenerationState],
        profile_health: bool = True,
        auth_required_first: bool = False,
    ) -> None:
        self._observe_sequence = list(observe_sequence)
        self._profile_health = profile_health
        self._auth_required_first = auth_required_first
        self.observe_call_count = 0
        self.check_profile_health_calls: list[str] = []
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
        self.check_profile_health_calls.append(profile_id)
        return self._profile_health

    def submit(
        self,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.submitted_prompts.append(request.prompt)
        self.submitted_requests.append(request)

        if self._auth_required_first and len(self.submitted_requests) == 1:
            return attempt.with_transition(
                GoogleFlowGenerationState.AUTH_REQUIRED,
                detail="Flow shows no sign of an authenticated session.",
            )

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


class _FakeProfileManagementService:
    """
    Minimal stand-in for ProviderProfileManagementService - tracks
    set_health_status() calls and actually applies the update to the
    given registry (the same real effect ProviderProfileManagementService.
    set_health_status() has via registry.register(replace=True), minus
    the real repository persistence), so a test can observe the
    self-heal actually letting a submission through, not just that
    the call happened.
    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry
        self.set_health_status_calls: list[tuple[str, ProviderHealthStatus]] = []

    def set_health_status(self, profile_id: str, status: ProviderHealthStatus) -> None:
        self.set_health_status_calls.append((profile_id, status))
        updated = self._registry.get(profile_id).model_copy(
            update={"health_status": status}
        )
        self._registry.register(updated, replace=True)


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
    self_heal_provider: _ScriptedProvider | None = None,
    profile_management_service: object | None = None,
    frame_extraction_service: FrameExtractionService | None = None,
    asset_storage_service: AssetStorageService | None = None,
    reference_frame_selection_service: object | None = None,
) -> SceneVideoGenerationService:
    return SceneVideoGenerationService(
        orchestrator=_orchestrator(
            provider, probe_output=probe_output, registry=registry
        ),
        asset_workflow_service=_asset_workflow_service(),
        registry=registry,
        provider=self_heal_provider,
        profile_management_service=profile_management_service,  # type: ignore[arg-type]
        poll_interval_seconds=1.0,
        max_poll_attempts=max_poll_attempts,
        sleep_fn=lambda _: None,
        frame_extraction_service=frame_extraction_service,
        asset_storage_service=asset_storage_service,
        reference_frame_selection_service=reference_frame_selection_service,  # type: ignore[arg-type]
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
    assert latest.qc_result is not None
    assert latest.qc_result.accepted

    # Real-world finding, 2026-09-14: with_transition() uses
    # model_copy() internally, which never re-validates - a READY
    # attempt missing qc_result looked fine in memory but failed the
    # very next real reload (a real saved job's own
    # model_validate_json(), exactly what job persistence does) with
    # "A READY attempt requires a passing qc_result." Round-trip the
    # attempt itself through JSON (not the whole job - VideoJob has
    # its own unrelated cross-field rules this minimal fixture never
    # tried to satisfy) so a regression here fails this test, not a
    # real saved job later.
    GoogleFlowGenerationAttempt.model_validate_json(latest.model_dump_json())


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
    assert request.execution_settings.duration_seconds == 8.0


def test_generate_one_uses_real_narration_duration_when_available() -> None:
    """
    Real-world finding, 2026-09-20: estimated_duration_seconds is a
    pre-generation word-count guess. Once VoicePipelineStage has set
    Scene.real_narration_duration_seconds from real, measured voice
    audio, the real Google Flow clip request must be sized from that
    real value instead - confirmed here with a real value (5.5s,
    clamps up to 6s) that deliberately differs from a much larger,
    now-irrelevant estimate (12s, which would have clamped to 8s).
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider)
    scene = _scene(1, duration=12)
    scene.real_narration_duration_seconds = 5.5
    job = _job(scene)

    service.generate_one(job, 1)

    request = job.flow_generation_attempts[0].request
    assert request.execution_settings.duration_seconds == 6.0


def test_generate_one_repatches_the_compiled_prompts_stale_duration_statement() -> None:
    """
    Real-world finding, 2026-09-20: confirmed on a real submission
    (scene 17) - CinematicPromptCompilationService bakes a "Duration:
    Ns seconds." statement into the compiled prompt TEXT far earlier,
    before voice generation has run, so it still states the old
    pre-generation estimate even once the real technical
    duration_seconds parameter (asserted above) reflects the real
    narration length. Left unpatched, the AI generator reads one
    duration in its own instructions and is asked to render a
    different one technically - the submitted prompt text must be
    re-patched to state the same real, final duration actually being
    requested.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider)
    scene = _scene(1, duration=6)
    scene.real_narration_duration_seconds = 6.5  # clamps up to 8
    job = _job(scene)
    job.cinematic_prompt_package = CinematicPromptPackage(
        script_lock_hash="a" * 64,
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash="a" * 64,
                prompt_text=(
                    "Identity: no recurring identity present. "
                    "Environment: a wheat field. Lighting: golden hour. "
                    "Action progression: a farmer surveys the damage. "
                    "Composition: wide shot. Lens/camera: 35mm, medium "
                    "shot, eye level, static movement. Duration: 6 seconds."
                ),
            )
        ],
    )

    service.generate_one(job, 1)

    assert provider.submitted_prompts == [
        "Identity: no recurring identity present. "
        "Environment: a wheat field. Lighting: golden hour. "
        "Shot progression: [0-8s] a farmer surveys the damage. "
        "Composition: wide shot. Lens/camera: 35mm, medium "
        "shot, eye level, static movement. Duration: 8 seconds."
    ]

    request = job.flow_generation_attempts[0].request
    assert request.execution_settings.duration_seconds == 8.0


def test_generate_one_extends_the_last_shot_progression_beat_to_the_real_duration() -> (
    None
):
    """
    Real-world finding, 2026-09-20: confirmed directly on the same
    real submission - patching the trailing "Duration: Ns seconds."
    summary alone was not enough. The shot-by-shot "Shot progression:
    [0-4s] ...; [4-6s] ..." beats are ALSO baked in before voice runs,
    clamped to the old, shorter estimate - when the real duration is
    longer, the beats simply stopped describing anything past their
    own original end, leaving the extra real seconds completely
    unscripted (observed directly: beats covered 0-4s and 4-6s while
    the real clip was 8s, nothing described 6-8s at all). The LAST
    beat's own end time must extend to the real final duration.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider)
    scene = _scene(1, duration=6)
    scene.real_narration_duration_seconds = 6.5  # clamps up to 8
    job = _job(scene)
    job.cinematic_prompt_package = CinematicPromptPackage(
        script_lock_hash="a" * 64,
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash="a" * 64,
                prompt_text=(
                    "Identity: no recurring identity present. "
                    "Environment: a wheat field. Lighting: golden hour. "
                    "Shot progression: [0-4s] a farmer surveys the "
                    "damage; [4-6s] the farmer kneels down. "
                    "Composition: wide shot. Lens/camera: 35mm, medium "
                    "shot, eye level, static movement. Duration: 6 seconds."
                ),
            )
        ],
    )

    service.generate_one(job, 1)

    assert provider.submitted_prompts == [
        "Identity: no recurring identity present. "
        "Environment: a wheat field. Lighting: golden hour. "
        "Shot progression: [0-4s] a farmer surveys the "
        "damage; [4-8s] the farmer kneels down. "
        "Composition: wide shot. Lens/camera: 35mm, medium "
        "shot, eye level, static movement. Duration: 8 seconds."
    ]


class TestExtendLastBeatToRealDuration:
    def test_extends_the_last_beats_end_time(self) -> None:
        prompt = "Shot progression: [0-4s] one thing; [4-6s] another thing."

        result = _extend_last_beat_to_real_duration(prompt, 8.0)

        assert result == ("Shot progression: [0-4s] one thing; [4-8s] another thing.")

    def test_only_the_last_beat_is_extended_not_earlier_ones(self) -> None:
        prompt = "Shot progression: [0-2s] a; [2-4s] b; [4-6s] c."

        result = _extend_last_beat_to_real_duration(prompt, 8.0)

        assert result == "Shot progression: [0-2s] a; [2-4s] b; [4-8s] c."

    def test_no_op_when_the_prompt_has_no_beat_ranges(self) -> None:
        prompt = "Action progression: a farmer surveys the damage."

        result = _extend_last_beat_to_real_duration(prompt, 8.0)

        assert result == prompt

    def test_no_op_when_the_last_beat_already_reaches_the_real_duration(self) -> None:
        prompt = "Shot progression: [0-4s] one thing; [4-8s] another thing."

        result = _extend_last_beat_to_real_duration(prompt, 8.0)

        assert result == prompt

    def test_no_op_when_the_last_beat_already_exceeds_the_real_duration(self) -> None:
        """Should never happen in practice (a beat outliving the real
        clip), but must not shrink it either - only extension, never
        the reverse, is this function's job."""

        prompt = "Shot progression: [0-4s] one thing; [4-10s] another thing."

        result = _extend_last_beat_to_real_duration(prompt, 8.0)

        assert result == prompt


def test_generate_one_falls_back_to_estimate_without_a_real_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    A scene somehow submitted before voice ran (real_narration_duration_seconds
    still None, the default) must still fall back to the old estimate-
    based sizing exactly as before - this should never happen in
    normal operation, so it also logs a warning to surface it.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider)
    scene = _scene(1, duration=12)

    assert scene.real_narration_duration_seconds is None

    job = _job(scene)

    with caplog.at_level("WARNING"):
        service.generate_one(job, 1)

    request = job.flow_generation_attempts[0].request
    assert request.execution_settings.duration_seconds == 8.0
    assert any(
        "before its real narration duration was known" in message
        for message in caplog.messages
    )


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


def test_generate_one_resubmits_a_ready_scene_once_its_clip_was_removed(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-28: BulkClipIngestionService.remove_
    scene_clip() clears the scene's SceneAssetState but, by its own
    documented design, deliberately never touches the Google Flow
    ledger - so the scene's latest attempt stayed READY. A later
    Generate click found that same READY attempt here and silently
    re-attached its already-downloaded file, never calling Flow again
    - confirmed live: removing scene 2's clip and clicking Generate
    re-attached the identical old file instead of generating a fresh
    one. Once the scene has no SceneAssetState referencing it, a READY
    attempt is an orphaned record of a past generation, not evidence
    there is nothing left to do - it must be resubmitted exactly like
    a FAILED/QC_FAILED one.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    first_file = tmp_path / "scene_first.mp4"
    first_file.write_bytes(b"fake but present video bytes")
    provider.downloaded_file = str(first_file)

    service = _service(provider)
    job = _job(_scene(1))

    entry = service.generate_one(job, 1)
    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_prompts) == 1

    # Simulate remove_scene_clip(): clear the scene's SceneAssetState,
    # deliberately leaving the Flow ledger's READY attempt untouched -
    # exactly what BulkClipIngestionService.remove_scene_clip() does.
    job.scene_asset_states = [
        state for state in job.scene_asset_states if state.scene_number != 1
    ]

    second_file = tmp_path / "scene_second.mp4"
    second_file.write_bytes(b"a genuinely different fresh clip")
    provider.downloaded_file = str(second_file)
    provider._observe_sequence = [
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
    ]

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_prompts) == 2  # a real, fresh submission happened
    assert len(job.flow_generation_attempts) == 2
    assert job.flow_generation_attempts[-1].downloaded_file == str(second_file)


def test_generate_one_submits_a_fresh_attempt_after_the_prior_one_failed(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-28: a scene whose latest attempt
    already failed (e.g. abandoned via abandon_stuck_attempt() after
    getting stuck at UI_CHANGED with no automated recovery path) used
    to make every later Generate click a silent no-op - the same
    is-not-None-and-not-pollable gap READY's own test above locks in
    on purpose, but wrongly also caught FAILED, which has no reason to
    stay untouched. A real click must submit a genuinely new attempt.
    """

    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    planned = _planned_attempt(job)
    stuck = planned.with_transition(GoogleFlowGenerationState.UI_CHANGED)
    GoogleFlowGenerationLedgerService.replace_attempt(job, stuck)

    service.abandon_stuck_attempt(job, 1)
    assert job.flow_generation_attempts[0].state == GoogleFlowGenerationState.FAILED

    real_file = tmp_path / "scene.mp4"
    real_file.write_bytes(b"fake but present video bytes")
    provider.downloaded_file = str(real_file)
    provider._observe_sequence = [
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
    ]

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_prompts) == 1  # a real, fresh submission happened
    assert len(job.flow_generation_attempts) == 2
    assert job.flow_generation_attempts[-1].profile_id == "flow.primary"


def test_generate_one_submits_a_fresh_attempt_after_a_qc_failure(
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

    service.generate_one(job, 1)
    assert job.flow_generation_attempts[-1].state == GoogleFlowGenerationState.QC_FAILED
    assert len(provider.submitted_prompts) == 1

    provider._observe_sequence = [
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
    ]

    service.generate_one(job, 1)

    assert len(provider.submitted_prompts) == 2  # a real, fresh submission happened
    assert len(job.flow_generation_attempts) == 2


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


def test_generate_one_polls_an_existing_submission_uncertain_attempt() -> None:
    """
    Real-world finding, 2026-09-14: SUBMISSION_UNCERTAIN used to stop
    generate_one() outright - a human had to notice and manually
    reconcile it, even though the real adapter can now resolve it
    automatically given real evidence (see
    test_google_flow_real_adapter.py's own reconciliation tests).
    Confirm this service actually polls (observes) a
    SUBMISSION_UNCERTAIN attempt instead of leaving it untouched, so
    that reconciliation gets a chance to run at all.
    """

    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    seed_provider = _ScriptedProvider(observe_sequence=[])
    seed_orchestrator = _orchestrator(seed_provider)
    seeded = seed_orchestrator.submit_new_attempt(
        job,
        scene_number=1,
        prompt="seed",
        prompt_version="v1",
        idempotency_key="seed-key",
    )
    uncertain = seeded.with_transition(
        GoogleFlowGenerationState.SUBMISSION_UNCERTAIN, detail="test setup"
    )
    GoogleFlowGenerationLedgerService.replace_attempt(job, uncertain)

    provider._observe_sequence = [GoogleFlowGenerationState.FAILED]

    service.generate_one(job, 1)

    assert provider.submitted_prompts == []  # never resubmitted
    assert provider.observe_call_count == 1  # but it WAS polled
    assert job.flow_generation_attempts[-1].state == GoogleFlowGenerationState.FAILED


def test_retry_scene_after_auth_resumes_and_continues_to_ready(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ],
        auth_required_first=True,
    )
    real_file = tmp_path / "scene.mp4"
    real_file.write_bytes(b"fake but present video bytes")
    provider.downloaded_file = str(real_file)

    service = _service(provider)
    job = _job(_scene(1))

    stuck = service.generate_one(job, 1)
    assert stuck.status == SceneCompletenessStatus.NEEDS_ATTENTION
    assert job.flow_generation_attempts[0].state == (
        GoogleFlowGenerationState.AUTH_REQUIRED
    )
    assert len(provider.submitted_prompts) == 1

    entry = service.retry_scene_after_auth(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_prompts) == 2  # resumed, not a fresh attempt
    assert provider.check_profile_health_calls == ["flow.primary"]


def test_retry_scene_after_auth_raises_when_scene_has_no_stuck_attempt() -> None:
    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    with pytest.raises(ValueError, match="no attempt waiting on authentication"):
        service.retry_scene_after_auth(job, 1)


def test_retry_scene_after_auth_raises_for_an_unknown_scene_number() -> None:
    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    with pytest.raises(ValueError, match="no scene numbered"):
        service.retry_scene_after_auth(job, 99)


def test_retry_scene_after_auth_still_refuses_while_unhealthy() -> None:
    provider = _ScriptedProvider(
        observe_sequence=[],
        auth_required_first=True,
        profile_health=False,
    )
    service = _service(provider)
    job = _job(_scene(1))

    stuck = service.generate_one(job, 1)
    assert stuck.status == SceneCompletenessStatus.NEEDS_ATTENTION

    with pytest.raises(RuntimeError, match="no sign of an authenticated session"):
        service.retry_scene_after_auth(job, 1)

    assert len(provider.submitted_prompts) == 1  # never resubmitted
    assert job.flow_generation_attempts[0].state == (
        GoogleFlowGenerationState.AUTH_REQUIRED
    )


def _planned_attempt(
    job: VideoJob, *, scene_number: int = 1
) -> GoogleFlowGenerationAttempt:
    """
    A bare PLANNED attempt, never submitted - built directly via the
    ledger rather than through any provider, so its state_history is
    guaranteed to contain nothing past the credit-sensitive SUBMITTING
    boundary. Matches the real live bug this was built for: a scene
    whose attempt went straight planned -> ui_changed, never through
    submit()'s own advancing logic at all.
    """

    request = GoogleFlowGenerationRequest(
        scene_number=scene_number,
        prompt="seed",
        prompt_version="v1",
        profile_id="flow.primary",
        idempotency_key=f"seed-key-{scene_number}",
    )

    return GoogleFlowGenerationLedgerService.create_attempt(job, request)


def test_abandon_stuck_attempt_marks_a_ui_changed_attempt_failed() -> None:
    """Real-world finding, 2026-09-28: a scene stuck at UI_CHANGED (or
    any non-terminal state with no automated recovery path) has no way
    to unstick short of this - AUTH_REQUIRED's own retry path doesn't
    apply, and Remove deliberately never touches the ledger."""

    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    planned = _planned_attempt(job)
    stuck = planned.with_transition(
        GoogleFlowGenerationState.UI_CHANGED, detail="test setup"
    )
    GoogleFlowGenerationLedgerService.replace_attempt(job, stuck)

    abandoned = service.abandon_stuck_attempt(job, 1)

    assert abandoned.state == GoogleFlowGenerationState.FAILED
    assert job.flow_generation_attempts[0].state == GoogleFlowGenerationState.FAILED


def test_abandon_stuck_attempt_allows_a_fresh_attempt_afterwards() -> None:
    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    planned = _planned_attempt(job)
    stuck = planned.with_transition(GoogleFlowGenerationState.UI_CHANGED)
    GoogleFlowGenerationLedgerService.replace_attempt(job, stuck)

    service.abandon_stuck_attempt(job, 1)

    # create_attempt()'s in-flight guard no longer blocks scene 1 -
    # a fresh attempt can be submitted through the exact same
    # orchestrator this service uses internally.
    fresh = service._orchestrator.submit_new_attempt(
        job,
        scene_number=1,
        prompt="fresh",
        prompt_version="v1",
        idempotency_key="fresh-key",
    )

    # The point: this didn't raise "already has an in-flight attempt" -
    # the in-flight guard genuinely no longer blocks scene 1.
    assert fresh.state != GoogleFlowGenerationState.UI_CHANGED
    assert len(job.flow_generation_attempts) == 2


def test_abandon_stuck_attempt_raises_when_scene_has_no_non_terminal_attempt() -> None:
    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    with pytest.raises(ValueError, match="no non-terminal attempt"):
        service.abandon_stuck_attempt(job, 1)


def test_abandon_stuck_attempt_force_forwards_to_the_orchestrator() -> None:
    """A stuck attempt whose history already reached GENERATING is
    credit-sensitive - abandon_stuck_attempt must surface the
    orchestrator's own refusal, and only override it when force=True
    is passed through explicitly."""

    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    seed_provider = _ScriptedProvider(observe_sequence=[])
    seed_orchestrator = _orchestrator(seed_provider)
    seeded = seed_orchestrator.submit_new_attempt(
        job,
        scene_number=1,
        prompt="seed",
        prompt_version="v1",
        idempotency_key="seed-key",
    )
    generating = seeded.with_transition(GoogleFlowGenerationState.GENERATING)
    stuck = generating.with_transition(GoogleFlowGenerationState.UI_CHANGED)
    GoogleFlowGenerationLedgerService.replace_attempt(job, stuck)

    with pytest.raises(GoogleFlowAttemptCreditSensitiveError):
        service.abandon_stuck_attempt(job, 1)

    abandoned = service.abandon_stuck_attempt(job, 1, force=True)
    assert abandoned.state == GoogleFlowGenerationState.FAILED


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


# --- self-healing Flow account health ---


def test_generate_one_self_heals_an_unhealthy_profile_before_submitting(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-14: this account's health_status kept
    reverting to UNHEALTHY between runs for reasons outside the
    generation code's own control, which meant "No usable Google Flow
    account is configured" on the very next submission unless a human
    ran a separate health check first - unacceptable for anything
    meant to run unattended across many scenes. Confirm a real,
    passing health check heals the profile and lets the submission
    that triggered it succeed in the same call.
    """

    unhealthy_profile = _flow_profile().model_copy(
        update={"health_status": ProviderHealthStatus.UNHEALTHY}
    )
    registry = ProviderRegistry(profiles=[unhealthy_profile])

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ],
        profile_health=True,
    )
    real_file = tmp_path / "scene.mp4"
    real_file.write_bytes(b"fake but present video bytes")
    provider.downloaded_file = str(real_file)

    management_service = _FakeProfileManagementService(registry)
    service = _service(
        provider,
        registry=registry,
        self_heal_provider=provider,
        profile_management_service=management_service,
    )
    job = _job(_scene(1))

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert provider.check_profile_health_calls == ["flow.primary"]
    assert management_service.set_health_status_calls == [
        ("flow.primary", ProviderHealthStatus.HEALTHY)
    ]


def test_generate_one_skips_the_real_health_check_when_already_healthy() -> None:
    """The self-heal check must be cheap in the common case - never
    make a real (slow) check against a profile that's already usable."""

    registry = ProviderRegistry(profiles=[_flow_profile()])  # already HEALTHY

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    management_service = _FakeProfileManagementService(registry)
    service = _service(
        provider,
        registry=registry,
        self_heal_provider=provider,
        profile_management_service=management_service,
    )
    job = _job(_scene(1))

    service.generate_one(job, 1)

    assert provider.check_profile_health_calls == []
    assert management_service.set_health_status_calls == []


def test_generate_one_leaves_a_still_unhealthy_profile_alone() -> None:
    """
    A real health check that genuinely fails must not be papered
    over - the account stays unhealthy, and the real, informative
    router error ("No usable Google Flow account is configured")
    still surfaces rather than being silently swallowed.
    """

    unhealthy_profile = _flow_profile().model_copy(
        update={"health_status": ProviderHealthStatus.UNHEALTHY}
    )
    registry = ProviderRegistry(profiles=[unhealthy_profile])

    provider = _ScriptedProvider(observe_sequence=[], profile_health=False)
    management_service = _FakeProfileManagementService(registry)
    service = _service(
        provider,
        registry=registry,
        self_heal_provider=provider,
        profile_management_service=management_service,
    )
    job = _job(_scene(1))

    with pytest.raises(NoEligibleGoogleFlowAccountError):
        service.generate_one(job, 1)

    assert provider.check_profile_health_calls == ["flow.primary"]
    assert management_service.set_health_status_calls == []


def _continuity_bible(
    *,
    identity_name: str = "Jack Reid",
    reference_asset_ids: list[str] | None = None,
    scene_numbers: list[int] | None = None,
) -> VisualContinuityBible:
    scenes = scene_numbers or [1]

    return VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name=identity_name,
                canonical_description="A weathered farmer in work clothes.",
                reference_asset_ids=list(reference_asset_ids or []),
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=scene_number,
                incoming_state=VisualState(),
                shot_action="Surveys the field.",
                outgoing_state=VisualState(),
                entity_names=[identity_name],
                on_screen_entity_names=[identity_name],
            )
            for scene_number in scenes
        ],
    )


def _frame_extraction_service(
    *, raise_error: Exception | None = None
) -> tuple[FrameExtractionService, list[list[str]]]:
    """Real FrameExtractionService with a fake, recording runner that
    writes a real (tiny) output file - matching this suite's own
    ffmpeg-stubbing convention elsewhere (_GOOD_PROBE)."""

    received_commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        received_commands.append(command)

        if raise_error is not None:
            raise raise_error

        output_path = command[-1]
        Path(output_path).write_bytes(b"fake-extracted-frame-bytes")

    return FrameExtractionService(runner=runner), received_commands


def _real_video_file(tmp_path: Path, *, name: str = "scene.mp4") -> Path:
    real_file = tmp_path / name
    real_file.write_bytes(b"fake but present video bytes")

    return real_file


def test_generate_one_extracts_and_stores_a_reference_for_a_first_appearance(
    tmp_path: Path,
) -> None:
    """
    Real-world design, 2026-09-20: visual continuity is self-
    consistency only, no manual upload - whatever an identity looks
    like in its own first real clip becomes its reference, fully
    automatically. Scene 1 introduces "Jack Reid" with no existing
    reference - after generation, a frame must be extracted from
    scene 1's own real downloaded clip and stored as that identity's
    first reference.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    real_file = _real_video_file(tmp_path)
    provider.downloaded_file = str(real_file)

    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(scene_numbers=[1])

    service.generate_one(job, 1)

    assert len(commands) == 1

    identity = job.visual_continuity_bible.identities[0]

    assert len(identity.reference_asset_ids) == 1

    stored_asset = asset_storage.asset_index.get(identity.reference_asset_ids[0])

    assert stored_asset is not None
    assert Path(stored_asset.file_path).exists()


def test_generate_one_does_not_extract_a_reference_for_an_off_screen_identity(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29: a first-person narrator "present"
    (mentioned) in a purely-narrated graphic scene, but never actually
    shown on screen, must not have a "reference" frame extracted from
    that scene's own clip - it would show whatever the graphic/b-roll
    actually was, poisoning every later scene's reference. Gated on
    on_screen_entity_names, not entity_names (see ClipContinuityEntry's
    own docstring).
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="The narrator",
                canonical_description="An unnamed first-person narrator.",
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(),
                shot_action="A graphic animation of a ladder numbered 0 to 10.",
                outgoing_state=VisualState(),
                entity_names=["The narrator"],
                on_screen_entity_names=[],
            )
        ],
    )

    service.generate_one(job, 1)

    assert commands == []
    assert job.visual_continuity_bible.identities[0].reference_asset_ids == []


def test_generate_one_does_not_attach_a_reference_for_an_off_screen_identity(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(provider, asset_storage_service=asset_storage)

    scene = _scene(2)
    job = _job(scene)

    job_scoped_storage = AssetStorageService(
        storage_root=tmp_path / "storage",
        asset_index=job.extracted_frame_asset_index,
    )
    source = tmp_path / "pre_existing_reference.jpg"
    source.write_bytes(b"real reference frame bytes")
    result = job_scoped_storage.store_extracted_frame(
        source_path=source,
        project_id="test-project",
        scene_number=1,
        title="Pre-existing reference",
    )
    assert result.success and result.asset is not None
    asset_id = str(result.asset.id)

    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="The narrator",
                canonical_description="An unnamed first-person narrator.",
                reference_asset_ids=[asset_id],
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=2,
                incoming_state=VisualState(),
                shot_action="A graphic animation of a ladder numbered 0 to 10.",
                outgoing_state=VisualState(),
                entity_names=["The narrator"],
                on_screen_entity_names=[],
            )
        ],
    )

    service.generate_one(job, 2)

    assert len(provider.submitted_requests) == 1
    assert provider.submitted_requests[0].reference_assets == []


def test_generate_one_resolves_a_reference_recorded_before_a_restart(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-28: a reference frame extracted and
    stored in an earlier session used to become unresolvable the
    moment the app restarted - get_extracted_frame_asset_storage_
    service() rebuilt a brand-new, empty AssetIndex on every process
    start, even though the real file and VisualContinuityBible's
    reference_asset_ids both still pointed at it correctly. Confirmed
    live: a scene's reference image attached correctly on the first
    two real generations, then silently stopped on the third attempt
    (a restart happened in between). Simulates exactly that: a job
    whose extracted_frame_asset_index already has the reference (as
    if just loaded from a persisted job), passed to a service wired
    with a freshly constructed, otherwise-EMPTY AssetStorageService
    (as if freshly built by a just-restarted process) - resolution
    must still succeed, purely from the job's own persisted index.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    scene = _scene(2)
    scene.real_narration_duration_seconds = 2.5
    job = _job(scene)
    asset_id = _stored_reference_asset(job, tmp_path)
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[asset_id], scene_numbers=[2]
    )

    # A brand-new AssetStorageService with its own empty AssetIndex -
    # exactly what get_extracted_frame_asset_storage_service() builds
    # on every fresh process start, unrelated to job.
    # extracted_frame_asset_index above.
    fresh_process_asset_storage = AssetStorageService(
        storage_root=tmp_path / "fresh_process_storage", asset_index=AssetIndex()
    )
    assert fresh_process_asset_storage.asset_index.get(asset_id) is None

    service = _service(provider, asset_storage_service=fresh_process_asset_storage)

    service.generate_one(job, 2)

    request = provider.submitted_requests[0]
    assert len(request.reference_assets) == 1
    assert request.reference_assets[0].role == GoogleFlowReferenceRole.CHARACTER


def test_generate_one_does_not_re_extract_for_an_identity_with_a_valid_reference(
    tmp_path: Path,
) -> None:
    """An identity that already has a reference which still resolves
    to a real, existing file (from an earlier scene) must be left
    alone - later scenes just keep reusing it, never re-extracting or
    overwriting it."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )
    job = _job(_scene(2))
    asset_id = _stored_reference_asset(job, tmp_path)
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[asset_id],
        scene_numbers=[2],
    )

    service.generate_one(job, 2)

    assert commands == []
    assert job.visual_continuity_bible.identities[0].reference_asset_ids == [asset_id]


def test_generate_one_re_extracts_for_an_identity_whose_reference_has_gone_stale(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29: a job created before VideoJob.
    extracted_frame_asset_index existed had its identities' reference_
    asset_ids already populated with an id from the OLD, process-
    lifetime-only index - that id can never resolve again once the
    real, persisted index starts life empty, but the "only extract for
    an identity with no reference_asset_ids at all" guard used to treat
    "has a (now-dangling) id" as "already has a reference" and refused
    to ever extract a fresh one. Confirmed live: a real job stuck
    permanently reusing a dangling reference id across several real
    regenerations, with the index staying empty (0 assets) the entire
    time. An identity whose EVERY reference_asset_id is dangling (never
    stored, or its file no longer exists) must be treated the same as
    an identity with no reference at all - re-extracted, and its stale
    id(s) replaced with the fresh, valid one.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )
    job = _job(_scene(2))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=["11111111-1111-1111-1111-111111111111"],
        scene_numbers=[2],
    )

    service.generate_one(job, 2)

    assert len(commands) == 1

    identity = job.visual_continuity_bible.identities[0]
    assert identity.reference_asset_ids != ["11111111-1111-1111-1111-111111111111"]
    assert len(identity.reference_asset_ids) == 1

    stored_asset = job.extracted_frame_asset_index.get(identity.reference_asset_ids[0])
    assert stored_asset is not None
    assert Path(stored_asset.file_path).exists()


def test_generate_one_skips_reference_extraction_without_a_continuity_bible(
    tmp_path: Path,
) -> None:
    """No VisualContinuityBible at all (job.visual_continuity_bible is
    None, the default) - generation must still succeed normally, just
    with no reference-extraction step to run."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )
    job = _job(_scene(1))

    assert job.visual_continuity_bible is None

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert commands == []


def test_generate_one_skips_reference_extraction_when_scene_has_no_entities(
    tmp_path: Path,
) -> None:
    """A continuity bible exists, but this scene's own entry lists no
    entity_names at all (a generic shot, no recurring identity) - no
    reference work to do."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(),
                shot_action="An empty wheat field at dawn.",
                outgoing_state=VisualState(),
                entity_names=[],
            )
        ],
    )

    service.generate_one(job, 1)

    assert commands == []


def test_generate_one_survives_a_frame_extraction_failure(tmp_path: Path) -> None:
    """
    A real frame-extraction failure (e.g. ffmpeg genuinely fails) must
    not fail this scene's own generation - this is a continuity
    enhancement, not a correctness requirement. Matches this class's
    established resilience pattern elsewhere (e.g.
    _self_heal_flow_account_health).
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service(
        raise_error=RuntimeError("Simulated ffmpeg failure.")
    )
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(scene_numbers=[1])

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(commands) == 1
    assert job.visual_continuity_bible.identities[0].reference_asset_ids == []


def test_generate_one_reproduces_exact_prior_behavior_without_the_new_services(
    tmp_path: Path,
) -> None:
    """Without frame_extraction_service/asset_storage_service wired
    (both None, the default), generation must behave exactly as
    before this feature existed - even with a real continuity bible
    present, nothing new happens."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    service = _service(provider)
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(scene_numbers=[1])

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert job.visual_continuity_bible.identities[0].reference_asset_ids == []


def _stored_reference_asset(job: VideoJob, tmp_path: Path) -> str:
    """
    Pre-store one real reference asset (a real file on disk,
    registered in the JOB's own persisted asset index) - simulating a
    reference an earlier scene's own extraction already produced,
    whether earlier in this same run or in an earlier session before a
    real app restart. Storing onto job.extracted_frame_asset_index
    (rather than some separately-constructed AssetStorageService's own
    index) matches the real 2026-09-28 fix: that field, not the
    process-lifetime service singleton, is what actually survives a
    restart - see SceneVideoGenerationService._sync_extracted_frame_
    asset_index()'s own docstring. Returns its asset id.
    """

    storage = AssetStorageService(
        storage_root=tmp_path / "storage",
        asset_index=job.extracted_frame_asset_index,
    )

    source = tmp_path / "pre_existing_reference.jpg"
    source.write_bytes(b"real reference frame bytes")

    result = storage.store_extracted_frame(
        source_path=source,
        project_id="test-project",
        scene_number=1,
        title="Pre-existing reference",
    )

    assert result.success and result.asset is not None

    return str(result.asset.id)


def test_generate_one_attaches_a_resolved_reference_and_forces_max_duration(
    tmp_path: Path,
) -> None:
    """
    Phase 4: a scene whose featured identity already has a reference
    (from an earlier scene's own extraction) must have that reference
    resolved fresh and attached to the real submitted request - and,
    since Flow refuses image ingredients below its max verified
    duration, the request must ask for that max duration even though
    this scene's own real narration is much shorter.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(provider, asset_storage_service=asset_storage)

    scene = _scene(2)
    scene.real_narration_duration_seconds = 2.5
    job = _job(scene)
    asset_id = _stored_reference_asset(job, tmp_path)
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[asset_id], scene_numbers=[2]
    )

    service.generate_one(job, 2)

    assert len(provider.submitted_requests) == 1

    request = provider.submitted_requests[0]
    stored_asset = job.extracted_frame_asset_index.get(asset_id)
    assert stored_asset is not None

    assert len(request.reference_assets) == 1
    reference = request.reference_assets[0]
    assert reference.source_path == stored_asset.file_path
    assert reference.checksum == stored_asset.content_hash
    assert reference.role == GoogleFlowReferenceRole.CHARACTER
    assert reference.identity_name == "Jack Reid"  # who it stands for

    # Real narration was only 2.5s (would normally clamp to 4s) - but
    # a resolved reference forces the max verified duration (8s),
    # since Flow refuses image ingredients below it.
    assert request.execution_settings.duration_seconds == 8.0


def test_generate_one_does_not_force_duration_without_a_resolved_reference(
    tmp_path: Path,
) -> None:
    """A scene whose featured identity has NO reference yet (its own
    first appearance) must submit with no reference_assets and must
    NOT have its duration forced - the normal real-narration clamp
    applies exactly as before Phase 4."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(provider, asset_storage_service=asset_storage)

    scene = _scene(1)
    scene.real_narration_duration_seconds = 2.5
    job = _job(scene)
    job.visual_continuity_bible = _continuity_bible(scene_numbers=[1])

    service.generate_one(job, 1)

    request = provider.submitted_requests[0]
    assert request.reference_assets == []
    assert request.execution_settings.duration_seconds == 4.0


def test_generate_one_skips_a_reference_whose_file_no_longer_exists(
    tmp_path: Path,
) -> None:
    """A reference asset id that still resolves in the index, but
    whose real file has since been deleted from disk, must be skipped
    rather than attaching a source_path that can't actually be
    uploaded - a resolution-time data problem, not a live UI failure,
    so this scene's own submission still proceeds without it."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(provider, asset_storage_service=asset_storage)

    scene = _scene(2)
    scene.real_narration_duration_seconds = 2.5
    job = _job(scene)
    asset_id = _stored_reference_asset(job, tmp_path)
    stored_asset = job.extracted_frame_asset_index.get(asset_id)
    assert stored_asset is not None
    Path(stored_asset.file_path).unlink()

    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[asset_id], scene_numbers=[2]
    )

    service.generate_one(job, 2)

    request = provider.submitted_requests[0]
    assert request.reference_assets == []
    assert request.execution_settings.duration_seconds == 4.0


def test_generate_one_skips_a_dangling_reference_asset_id(tmp_path: Path) -> None:
    """A reference_asset_id that no longer resolves in the asset index
    at all (e.g. the index was rebuilt) must be skipped gracefully,
    never raising and never blocking this scene's own submission."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(provider, asset_storage_service=asset_storage)

    scene = _scene(2)
    scene.real_narration_duration_seconds = 2.5
    job = _job(scene)
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=["11111111-1111-1111-1111-111111111111"],
        scene_numbers=[2],
    )

    entry = service.generate_one(job, 2)

    assert entry.status == SceneCompletenessStatus.READY
    request = provider.submitted_requests[0]
    assert request.reference_assets == []
    assert request.execution_settings.duration_seconds == 4.0


def test_generate_one_resolves_a_location_identity_as_location_role(
    tmp_path: Path,
) -> None:
    """A LOCATION identity's resolved reference must be attached with
    role=LOCATION, not the CHARACTER default a PERSON identity gets."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(provider, asset_storage_service=asset_storage)

    scene = _scene(2)
    job = _job(scene)
    asset_id = _stored_reference_asset(job, tmp_path)
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="The old farmhouse",
                canonical_description="A weathered stone farmhouse.",
                reference_asset_ids=[asset_id],
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=2,
                incoming_state=VisualState(),
                shot_action="Establishing shot of the farmhouse.",
                outgoing_state=VisualState(),
                entity_names=["The old farmhouse"],
                on_screen_entity_names=["The old farmhouse"],
            )
        ],
    )

    service.generate_one(job, 2)

    request = provider.submitted_requests[0]
    assert len(request.reference_assets) == 1
    assert request.reference_assets[0].role == GoogleFlowReferenceRole.LOCATION


def test_generate_one_does_not_split_a_short_scene(tmp_path: Path) -> None:
    """A scene whose real narration fits within the max verified
    duration must take the normal single-clip path exactly as before
    Phase 5 existed - one submission, one clip."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    service = _service(provider)

    scene = _scene(1)
    scene.real_narration_duration_seconds = 5.0
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_requests) == 1
    assert provider.submitted_requests[0].clip_sequence_index == 0

    clips = [c for c in job.video_clips if c.scene_number == 1]
    assert len(clips) == 1
    assert clips[0].clip_sequence_index == 0


def test_generate_one_splits_a_scene_whose_narration_exceeds_the_max_duration(
    tmp_path: Path,
) -> None:
    """
    Phase 5: a scene whose real narration exceeds Flow's max single-
    clip duration (14s here - plan() splits it into two 8s sub-clips)
    must submit TWO consecutive requests sharing one scene_number,
    distinguished by clip_sequence_index, and attach both as separate
    VideoClips. The second sub-clip's own request must carry a
    FIRST_FRAME seam reference extracted from the first sub-clip's
    real downloaded file, forcing its duration to the max verified
    bucket.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )

    scene = _scene(1)
    scene.real_narration_duration_seconds = 14.0
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_requests) == 2

    first_request, second_request = provider.submitted_requests
    assert first_request.clip_sequence_index == 0
    assert second_request.clip_sequence_index == 1
    assert first_request.execution_settings.duration_seconds == 8.0
    assert second_request.execution_settings.duration_seconds == 8.0

    # The seam reference (extracted between the two sub-clips) must
    # have actually run - one extraction command for the seam, on top
    # of whatever this test's own fixtures already exercised.
    assert len(commands) == 1

    assert first_request.reference_assets == []
    assert len(second_request.reference_assets) == 1
    assert (
        second_request.reference_assets[0].role == GoogleFlowReferenceRole.FIRST_FRAME
    )

    clips = sorted(
        (c for c in job.video_clips if c.scene_number == 1),
        key=lambda c: c.clip_sequence_index,
    )
    assert [c.clip_sequence_index for c in clips] == [0, 1]


def test_generate_one_stops_a_split_scene_when_a_sub_clip_never_reaches_ready(
    tmp_path: Path,
) -> None:
    """If an earlier sub-clip never reaches READY (e.g. stuck at an
    interrupt state), the whole split scene stops there rather than
    generating further sub-clips or attaching a partial result -
    matching this class's own "interrupt state means call the
    operator, never auto-retry" rule."""

    provider = _ScriptedProvider(observe_sequence=[])
    provider.downloaded_file = str(_real_video_file(tmp_path))

    class _RefusingSubmitProvider(_ScriptedProvider):
        def submit(
            self,
            request: GoogleFlowGenerationRequest,
            attempt: GoogleFlowGenerationAttempt,
        ) -> GoogleFlowGenerationAttempt:
            self.submitted_prompts.append(request.prompt)
            self.submitted_requests.append(request)

            return attempt.with_transition(
                GoogleFlowGenerationState.UI_CHANGED,
                detail="Simulated real UI change - refuses to proceed.",
            )

    refusing_provider = _RefusingSubmitProvider(observe_sequence=[])

    service = _service(refusing_provider)

    scene = _scene(1)
    scene.real_narration_duration_seconds = 14.0
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status != SceneCompletenessStatus.READY
    assert len(refusing_provider.submitted_requests) == 1
    assert job.video_clips == []


def test_generate_one_routes_to_the_scenes_preferred_profile_id(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29 (per-scene account picker): a scene
    with Scene.preferred_profile_id set must route to that EXACT
    account, not whichever one auto-priority would otherwise pick -
    the whole point of an explicit per-scene override.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    def _profile(profile_id: str, *, priority: int) -> ProviderProfile:
        return ProviderProfile(
            profile_id=profile_id,
            display_name=profile_id,
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=True,
            priority=priority,
            health_status=ProviderHealthStatus.HEALTHY,
            browser_profile_reference=f"flow_profiles/{profile_id}",
        )

    registry = ProviderRegistry(
        profiles=[
            _profile("flow.primary", priority=1),
            _profile("flow.backup", priority=2),
        ]
    )
    service = _service(provider, registry=registry)

    scene = _scene(1)
    scene.preferred_profile_id = "flow.backup"
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert provider.submitted_requests[0].profile_id == "flow.backup"


def test_generate_one_sizes_the_clip_from_the_voice_track_when_the_scene_field_is_empty() -> (
    None
):
    """
    Real-world finding, 2026-10-03: a voiceover generated from the Audio tab
    left Scene.real_narration_duration_seconds empty, so clips were sized from
    the script's estimate. generate_one now fills it from the scene's voice
    track first - here a 12s estimate for a scene that really runs 5.5s.
    """

    from src.models.audio_timeline import AudioTimeline
    from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    service = _service(provider)
    scene = _scene(1, duration=12)
    job = _job(scene)
    job.audio_timeline = AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file="voice/1.mp3",
                duration_seconds=5.5,
                status=AudioTrackStatus.READY,
                metadata={"scene_number": 1},
            )
        ]
    )

    assert scene.real_narration_duration_seconds is None

    service.generate_one(job, 1)

    assert scene.real_narration_duration_seconds == 5.5
    request = job.flow_generation_attempts[0].request
    assert request.execution_settings.duration_seconds == 6.0


# --- reference frame chosen by face quality (2026-10-05) ---


def _selection_service(*, faces_by_frame):  # type: ignore[no-untyped-def]
    """A real ReferenceFrameSelectionService with a stub detector and fake frames,
    so the wiring is exercised without OpenCV or a real face."""

    from src.services.reference_frame_selection_service import (
        ReferenceFrameSelectionService,
        SampledFrame,
    )

    class _Detector:
        def detect(self, frame):  # type: ignore[no-untyped-def]
            return faces_by_frame[frame]

    frames = [
        SampledFrame(index=i, time_seconds=float(i), image=i)
        for i in range(len(faces_by_frame))
    ]

    return ReferenceFrameSelectionService(
        detector=_Detector(),
        availability_check=lambda: True,
        frame_reader=lambda _path, _count: frames,
        image_writer=lambda image, path: Path(path).write_bytes(
            f"frame-{image}".encode()
        )
        > 0,
    )


def _good_face():  # type: ignore[no-untyped-def]
    from src.services.reference_frame_selection_service import DetectedFace

    return DetectedFace(
        width=120,
        frame_width=640,
        detection_score=0.95,
        right_eye_x=300,
        left_eye_x=340,
        nose_x=320,
    )


def _profile_face():  # type: ignore[no-untyped-def]
    from src.services.reference_frame_selection_service import DetectedFace

    return DetectedFace(
        width=120,
        frame_width=640,
        detection_score=0.95,
        right_eye_x=300,
        left_eye_x=340,
        nose_x=372,
    )


def test_a_reference_is_the_best_face_frame_not_the_last_frame(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    # frame 0 profile, frame 1 clean front-on, frame 2 (the last) profile
    selection = _selection_service(
        faces_by_frame={0: [_profile_face()], 1: [_good_face()], 2: [_profile_face()]}
    )
    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
        reference_frame_selection_service=selection,
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(scene_numbers=[1])

    service.generate_one(job, 1)

    assert commands == []  # the blind last-frame grab was NOT used
    identity = job.visual_continuity_bible.identities[0]
    asset = asset_storage.asset_index.get(identity.reference_asset_ids[0])
    assert asset is not None
    assert Path(asset.file_path).read_bytes() == b"frame-1"
    assert asset.metadata["selection_method"] == "best_face"
    assert asset.metadata["reference_score"] >= 0.5


def test_no_reference_is_stored_when_no_frame_shows_a_clear_face(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    selection = _selection_service(faces_by_frame={0: [_profile_face()], 1: []})
    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
        reference_frame_selection_service=selection,
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(scene_numbers=[1])

    service.generate_one(job, 1)

    identity = job.visual_continuity_bible.identities[0]
    assert identity.reference_asset_ids == []  # a bad reference is worse than none
    assert commands == []  # and it did not fall back to the last frame
    assert any("no usable reference frame" in w for w in job.warnings)
    assert [
        c for c in job.video_clips if c.scene_number == 1
    ]  # the clip itself is fine


def test_an_identity_with_no_reference_gets_another_chance_next_scene(
    tmp_path: Path,
) -> None:
    """A scene that gave no usable face leaves the identity eligible, so the next
    scene featuring them tries again."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, _ = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    bad = _selection_service(faces_by_frame={0: []})
    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
        reference_frame_selection_service=bad,
    )
    job = _job(_scene(1), _scene(2))
    job.visual_continuity_bible = _continuity_bible(scene_numbers=[1, 2])

    service.generate_one(job, 1)
    identity = job.visual_continuity_bible.identities[0]
    assert identity.reference_asset_ids == []

    provider._observe_sequence = [  # noqa: SLF001
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
    ]
    service._reference_frame_selection_service = _selection_service(  # noqa: SLF001
        faces_by_frame={0: [_good_face()]}
    )
    service.generate_one(job, 2)

    assert len(identity.reference_asset_ids) == 1


def test_without_a_selection_service_the_last_frame_is_still_used(
    tmp_path: Path,
) -> None:
    """An install with no OpenCV behaves exactly as before."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(scene_numbers=[1])

    service.generate_one(job, 1)

    assert len(commands) == 1
    identity = job.visual_continuity_bible.identities[0]
    asset = asset_storage.asset_index.get(identity.reference_asset_ids[0])
    assert asset is not None
    assert asset.metadata["selection_method"] == "last_frame"


def _bible_with_a_person_and_a_place(scene_number: int = 1):  # type: ignore[no-untyped-def]
    from src.models.visual_continuity import (
        CanonicalEntityIdentity,
        CanonicalEntityType,
        ClipContinuityEntry,
        VisualContinuityBible,
        VisualState,
    )

    return VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="Jack Reid",
                canonical_description="A weathered farmer.",
            ),
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="Reid Farm",
                canonical_description="A dusty wheat farm.",
            ),
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=scene_number,
                incoming_state=VisualState(),
                shot_action="Surveys the field.",
                outgoing_state=VisualState(),
                entity_names=["Jack Reid", "Reid Farm"],
                on_screen_entity_names=["Jack Reid", "Reid Farm"],
            )
        ],
    )


def _person_and_place_selection(*, person_visible: bool):  # type: ignore[no-untyped-def]
    """Frame 0 is a sharp wide shot of the place with nobody in it; frame 1 is a
    softer close-up of the person (when they are visible)."""

    from src.services.reference_frame_selection_service import (
        ReferenceFrameSelectionService,
        SampledFrame,
    )

    class _Detector:
        def detect(self, frame):  # type: ignore[no-untyped-def]
            return [_good_face()] if frame == 1 and person_visible else []

    sharp = {0: 220.0, 1: 90.0}
    frames = [SampledFrame(index=i, time_seconds=float(i), image=i) for i in (0, 1)]

    return ReferenceFrameSelectionService(
        detector=_Detector(),
        availability_check=lambda: True,
        frame_reader=lambda _p, _c: frames,
        image_writer=lambda image, path: Path(path).write_bytes(
            f"frame-{image}".encode()
        )
        > 0,
        sharpness_scorer=lambda image: sharp[image],
        spread_scorer=lambda image: 1.0,
    )


def test_a_person_and_a_place_in_one_scene_get_their_own_frames(tmp_path: Path) -> None:
    """The reference follows the continuity bible's identity, not the clip: the
    person from the frame showing their face, the farm from the frame showing the
    farm."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, commands = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
        reference_frame_selection_service=_person_and_place_selection(
            person_visible=True
        ),
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = _bible_with_a_person_and_a_place()

    service.generate_one(job, 1)

    person, place = job.visual_continuity_bible.identities
    person_asset = asset_storage.asset_index.get(person.reference_asset_ids[0])
    place_asset = asset_storage.asset_index.get(place.reference_asset_ids[0])

    assert person_asset is not None and place_asset is not None
    assert Path(person_asset.file_path).read_bytes() == b"frame-1"  # the face
    assert Path(place_asset.file_path).read_bytes() == b"frame-0"  # the place
    assert person_asset.metadata["reference_kind"] == "person"
    assert place_asset.metadata["reference_kind"] == "environment"
    assert commands == []


def test_a_location_still_gets_a_reference_when_nobody_is_in_the_scene(
    tmp_path: Path,
) -> None:
    """Regression guard for the face gate: a place has no face, and must not be
    left without a reference because of it."""

    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, _ = _frame_extraction_service()
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
        reference_frame_selection_service=_person_and_place_selection(
            person_visible=False
        ),
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = _bible_with_a_person_and_a_place()

    service.generate_one(job, 1)

    person, place = job.visual_continuity_bible.identities
    assert person.reference_asset_ids == []  # no face anywhere: none, with a warning
    assert len(place.reference_asset_ids) == 1  # the place does not need one
    assert any("Jack Reid" in w for w in job.warnings)
    assert not any("Reid Farm" in w for w in job.warnings)
