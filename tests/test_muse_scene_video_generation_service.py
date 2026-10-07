from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.asset_index import AssetIndex
from src.models.media_strategy import SceneSourceType
from src.models.muse_generation import (
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
    MuseReferenceRole,
)
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.models.scene import Scene
from src.models.scene_completeness import SceneCompletenessStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.providers.muse_ui_provider import MuseUIOperation, MuseUIProvider
from src.services.asset_decision_service import AssetDecisionService
from src.services.asset_manager import AssetManager
from src.services.asset_search_service import AssetSearchService
from src.services.asset_storage_service import AssetStorageService
from src.services.frame_extraction_service import FrameExtractionService
from src.services.local_asset_search_service import LocalAssetSearchService
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)
from src.services.muse_account_router_service import MuseAccountRouterService
from src.services.muse_generation_ledger_service import MuseGenerationLedgerService
from src.services.muse_generation_orchestrator_service import (
    MuseGenerationOrchestratorService,
)
from src.services.muse_scene_video_generation_service import (
    MuseSceneVideoGenerationService,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.scene_asset_workflow_service import SceneAssetWorkflowService

_GOOD_PROBE = json.dumps(
    {
        "format": {"duration": "10.0"},
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio"},
        ],
    }
)


def _scene(number: int = 1) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=f"Narration for scene {number}.",
        visual_prompt=f"Visual prompt for scene {number}.",
        estimated_duration_seconds=10,
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


def _muse_profile() -> ProviderProfile:
    return ProviderProfile(
        profile_id="muse.primary",
        display_name="muse.primary",
        provider_name="Muse",
        category=ProviderCategory.EXTERNAL_UI_VIDEO,
        enabled=True,
        health_status=ProviderHealthStatus.HEALTHY,
        browser_profile_reference="muse_profiles/muse.primary",
    )


class _ScriptedProvider(MuseUIProvider):
    """Submits straight to SUBMITTED, then replays a fixed queue of
    states from observe() - mirrors test_scene_video_generation_
    service.py's own _ScriptedProvider for Google Flow."""

    def __init__(
        self,
        *,
        observe_sequence: list[MuseGenerationState],
        profile_health: bool = True,
        auth_required_first: bool = False,
    ) -> None:
        self._observe_sequence = list(observe_sequence)
        self._profile_health = profile_health
        self._auth_required_first = auth_required_first
        self.check_profile_health_calls: list[str] = []
        self.submitted_prompts: list[str] = []
        self.submitted_requests: list[MuseGenerationRequest] = []
        self.downloaded_file = "downloads/scene.mp4"
        # Optional: distinct files for consecutive download() calls
        # (e.g. a split scene's own sub-clips, which must never share
        # a checksum) - None (the default) keeps every call returning
        # the single downloaded_file above, unaffected.
        self.downloaded_files: list[str] | None = None

    @property
    def provider_name(self) -> str:
        return "Scripted Muse"

    def health_check(self) -> bool:
        return True

    @property
    def supported_operations(self) -> frozenset[MuseUIOperation]:
        return frozenset(
            {
                MuseUIOperation.SUBMIT,
                MuseUIOperation.OBSERVE,
                MuseUIOperation.DOWNLOAD,
            }
        )

    def check_profile_health(self, profile_id: str) -> bool:
        self.check_profile_health_calls.append(profile_id)
        return self._profile_health

    def submit(
        self,
        request: MuseGenerationRequest,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        self.submitted_prompts.append(request.prompt)
        self.submitted_requests.append(request)

        if self._auth_required_first and len(self.submitted_requests) == 1:
            return attempt.with_transition(
                MuseGenerationState.AUTH_REQUIRED,
                detail="Muse shows no sign of an authenticated session.",
            )

        current = attempt
        for state in (
            MuseGenerationState.SUBMITTING,
            MuseGenerationState.SUBMITTED,
        ):
            current = current.with_transition(state)

        return current

    def observe(self, attempt: MuseGenerationAttempt) -> MuseGenerationAttempt:
        next_state = self._observe_sequence.pop(0)

        if next_state == attempt.state:
            return attempt

        return attempt.with_transition(next_state)

    def download(self, attempt: MuseGenerationAttempt) -> MuseGenerationAttempt:
        file_path = (
            self.downloaded_files.pop(0)
            if self.downloaded_files
            else self.downloaded_file
        )

        return attempt.model_copy(
            update={"downloaded_file": file_path}
        ).with_transition(MuseGenerationState.DOWNLOADED)

    def cancel_or_abandon(
        self, attempt: MuseGenerationAttempt
    ) -> MuseGenerationAttempt:
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
) -> MuseGenerationOrchestratorService:
    router = MuseAccountRouterService(
        registry or ProviderRegistry(profiles=[_muse_profile()])
    )

    return MuseGenerationOrchestratorService(
        provider=provider,
        account_router=router,
        technical_validation_service=MediaTechnicalValidationService(
            runner=lambda command: probe_output
        ),
    )


def _service(
    provider: _ScriptedProvider,
    *,
    registry: ProviderRegistry | None = None,
    frame_extraction_service: FrameExtractionService | None = None,
    asset_storage_service: AssetStorageService | None = None,
    reference_frame_selection_service: object | None = None,
) -> MuseSceneVideoGenerationService:
    return MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider, registry=registry),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=lambda _: None,
        frame_extraction_service=frame_extraction_service,
        asset_storage_service=asset_storage_service,
        reference_frame_selection_service=reference_frame_selection_service,  # type: ignore[arg-type]
    )


def _real_video_file(tmp_path: Path, *, name: str = "scene.mp4") -> Path:
    real_file = tmp_path / name
    real_file.write_bytes(b"fake but present video bytes")

    return real_file


def _frame_extraction_service(
    tmp_path: Path,
) -> tuple[FrameExtractionService, list[list[str]]]:
    received_commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        received_commands.append(command)
        output_path = command[-1]
        # Content derived from the real INPUT path (after "-i"), not a
        # single fixed value - two genuinely different source videos
        # (e.g. a split scene's own distinct sub-clips) must never
        # collapse onto the same output bytes/checksum after a trim or
        # extraction, matching real ffmpeg behavior.
        input_path = command[command.index("-i") + 1]
        Path(output_path).write_bytes(f"fake-output-for-{input_path}".encode())

    return FrameExtractionService(runner=runner), received_commands


# --- generate_one: submit/poll/download/validate/attach ---


def test_generate_one_submits_polls_downloads_validates_and_attaches(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    real_file = _real_video_file(tmp_path)
    provider.downloaded_file = str(real_file)

    service = _service(provider)
    job = _job(_scene(1))

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_prompts) == 1
    assert job.video_clips
    assert job.muse_generation_attempts[0].state == MuseGenerationState.READY


# --- duplicate-download detection (real Generate All finding) ---


def test_generate_one_rejects_a_download_identical_to_another_scenes_video(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29: a real Generate All run submitted
    several scenes to Muse in quick succession, and Muse's own chat
    assistant admitted - unprompted - that it stacked the rapid-fire
    prompts and delivered results as a batch rather than generating
    each independently. Confirmed directly against the real job: 3
    consecutive scenes' downloaded files were byte-for-byte identical
    (same SHA-256). A download that exactly matches another scene's
    own already-recorded video must never be silently promoted to
    READY and attached - it is not this scene's own distinct video.
    """

    shared_file = _real_video_file(tmp_path, name="shared.mp4")

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(shared_file)

    service = _service(provider)
    job = _job(_scene(1))

    first_entry = service.generate_one(job, 1)
    assert first_entry.status == SceneCompletenessStatus.READY

    # Scene 2's own download happens to produce the exact same file
    # Muse already delivered for scene 1 - simulating the confirmed
    # real batching/reuse behavior.
    job.scenes.append(_scene(2))
    provider._observe_sequence = [  # noqa: SLF001
        MuseGenerationState.GENERATING,
        MuseGenerationState.READY_TO_DOWNLOAD,
    ]

    second_entry = service.generate_one(job, 2)

    assert second_entry.status != SceneCompletenessStatus.READY

    scene_2_attempt = next(
        attempt
        for attempt in job.muse_generation_attempts
        if attempt.request.scene_number == 2
    )
    assert scene_2_attempt.state == MuseGenerationState.UI_CHANGED
    assert scene_2_attempt.state_history[-1].detail is not None
    assert "scene 1" in scene_2_attempt.state_history[-1].detail

    # Scene 1's own already-successful attempt/attachment is untouched.
    assert job.muse_generation_attempts[0].state == MuseGenerationState.READY
    clips_by_scene = {clip.scene_number: clip for clip in job.video_clips}
    assert 1 in clips_by_scene
    assert 2 not in clips_by_scene


def test_generate_one_accepts_a_genuinely_distinct_download(tmp_path: Path) -> None:
    """Sanity check: two scenes with real, distinct videos are never
    falsely flagged as duplicates of each other."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path, name="scene_1.mp4"))

    service = _service(provider)
    job = _job(_scene(1))

    first_entry = service.generate_one(job, 1)
    assert first_entry.status == SceneCompletenessStatus.READY

    job.scenes.append(_scene(2))
    scene_2_file = _real_video_file(tmp_path, name="scene_2.mp4")
    scene_2_file.write_bytes(b"genuinely different scene 2 video bytes")
    provider.downloaded_file = str(scene_2_file)
    provider._observe_sequence = [  # noqa: SLF001
        MuseGenerationState.GENERATING,
        MuseGenerationState.READY_TO_DOWNLOAD,
    ]

    second_entry = service.generate_one(job, 2)

    assert second_entry.status == SceneCompletenessStatus.READY


# --- fixed ~10s duration: prompt trim instruction + safety-net trim ---


def test_submit_asks_muse_to_trim_when_narration_is_shorter_than_its_fixed_length(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29: Muse's own agent can execute an
    explicit trim instruction embedded in the prompt itself (confirmed
    live - a real "trim 10 seconds video to only 7 seconds video"
    instruction produced a genuinely ~7s clip). A scene whose real
    narration is shorter than Muse's fixed ~10s clip length must get
    this instruction appended to its prompt.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    service = _service(provider)
    scene = _scene(1)
    scene.real_narration_duration_seconds = 4.0
    job = _job(scene)

    service.generate_one(job, 1)

    prompt = provider.submitted_prompts[0]
    assert "Duration: 4 seconds" in prompt
    assert "trim the generated" not in prompt


def test_submit_does_not_ask_for_a_trim_when_narration_fills_the_fixed_length(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    service = _service(provider)
    scene = _scene(1)
    scene.real_narration_duration_seconds = 10.0
    job = _job(scene)

    service.generate_one(job, 1)

    assert "Also trim" not in provider.submitted_prompts[0]


def test_safety_net_trims_a_clip_whose_real_duration_exceeds_the_target(
    tmp_path: Path,
) -> None:
    """
    Verified fallback for whenever Muse's own prompt-instructed trim
    wasn't exact - a downloaded clip whose real, measured duration
    (per technical validation) is still longer than the scene's real
    target must be trimmed locally before being attached.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    real_file = _real_video_file(tmp_path)
    provider.downloaded_file = str(real_file)

    # Reports the RAW, untrimmed ~10s duration on every validation
    # call (both the initial one and the re-validation after
    # trimming) - a fixed fake, but sufficient to prove the trim
    # mechanism itself fires and the trimmed file is what gets
    # attached, which is what this test targets.
    ten_second_probe = json.dumps(
        {
            "format": {"duration": "10.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        }
    )

    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider, probe_output=ten_second_probe),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=lambda _: None,
        frame_extraction_service=frame_extraction,
    )

    scene = _scene(1)
    scene.real_narration_duration_seconds = 4.0
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(commands) == 1
    trim_command = commands[0]
    assert "-t" in trim_command
    duration_index = trim_command.index("-t") + 1
    assert float(trim_command[duration_index]) == pytest.approx(4.0)

    final_attempt = job.muse_generation_attempts[-1]
    assert final_attempt.downloaded_file is not None
    assert "_trimmed" in final_attempt.downloaded_file


def test_safety_net_does_not_trim_when_already_within_tolerance(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    real_file = _real_video_file(tmp_path)
    provider.downloaded_file = str(real_file)

    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = _service(provider, frame_extraction_service=frame_extraction)

    scene = _scene(1)
    scene.real_narration_duration_seconds = 9.8  # within tolerance of 10.0
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert commands == []  # never trimmed
    final_attempt = job.muse_generation_attempts[-1]
    assert final_attempt.downloaded_file == str(real_file)


def test_generate_one_does_not_resubmit_a_scene_already_at_ready(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    service = _service(provider)
    job = _job(_scene(1))

    service.generate_one(job, 1)
    assert len(provider.submitted_prompts) == 1

    service.generate_one(job, 1)
    assert len(provider.submitted_prompts) == 1


def test_generate_one_submits_a_fresh_attempt_after_the_prior_one_failed(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    request = MuseGenerationRequest(
        scene_number=1,
        prompt="A lighthouse at dusk.",
        prompt_version="v1",
        profile_id="muse.primary",
        idempotency_key="req-1",
    )
    planned = MuseGenerationLedgerService.create_attempt(job, request)
    stuck = planned.with_transition(MuseGenerationState.UI_CHANGED)
    MuseGenerationLedgerService.replace_attempt(job, stuck)

    service.abandon_stuck_attempt(job, 1)
    assert job.muse_generation_attempts[0].state == MuseGenerationState.FAILED

    real_file = _real_video_file(tmp_path)
    provider.downloaded_file = str(real_file)
    provider._observe_sequence = [
        MuseGenerationState.GENERATING,
        MuseGenerationState.READY_TO_DOWNLOAD,
    ]

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_prompts) == 1
    assert len(job.muse_generation_attempts) == 2


def test_generate_one_resubmits_a_ready_scene_once_its_clip_was_removed(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    first_file = _real_video_file(tmp_path, name="first.mp4")
    provider.downloaded_file = str(first_file)

    service = _service(provider)
    job = _job(_scene(1))

    entry = service.generate_one(job, 1)
    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_prompts) == 1

    # Simulate remove_scene_clip(): clear the scene's SceneAssetState,
    # leaving the Muse ledger's READY attempt untouched.
    job.scene_asset_states = [
        state for state in job.scene_asset_states if state.scene_number != 1
    ]

    second_file = _real_video_file(tmp_path, name="second.mp4")
    provider.downloaded_file = str(second_file)
    provider._observe_sequence = [
        MuseGenerationState.GENERATING,
        MuseGenerationState.READY_TO_DOWNLOAD,
    ]

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_prompts) == 2
    assert job.muse_generation_attempts[-1].downloaded_file == str(second_file)


# --- retry_scene_after_auth / abandon_stuck_attempt ---


def test_retry_scene_after_auth_resumes_and_completes(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ],
        auth_required_first=True,
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    service = _service(provider)
    job = _job(_scene(1))

    service.generate_one(job, 1)
    assert job.muse_generation_attempts[0].state == MuseGenerationState.AUTH_REQUIRED

    entry = service.retry_scene_after_auth(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert provider.check_profile_health_calls == ["muse.primary"]


def test_abandon_stuck_attempt_raises_without_a_non_terminal_attempt() -> None:
    provider = _ScriptedProvider(observe_sequence=[])
    service = _service(provider)
    job = _job(_scene(1))

    try:
        service.abandon_stuck_attempt(job, 1)
        raise AssertionError("expected ValueError")
    except ValueError as error:
        assert "no non-terminal attempt" in str(error)


# --- visual continuity: extract / reuse / self-heal a stale reference ---


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


def test_generate_one_extracts_and_stores_a_reference_for_a_first_appearance(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service(tmp_path)
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

    stored_asset = job.extracted_frame_asset_index.get(identity.reference_asset_ids[0])
    assert stored_asset is not None
    assert Path(stored_asset.file_path).exists()


def test_generate_one_re_extracts_for_an_identity_whose_reference_has_gone_stale(
    tmp_path: Path,
) -> None:
    """Same self-healing behavior as Google Flow's own equivalent
    fix: a dangling reference_asset_id (never stored, or whose file no
    longer exists) must be treated as no reference at all."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service(tmp_path)
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=["11111111-1111-1111-1111-111111111111"],
        scene_numbers=[1],
    )

    service.generate_one(job, 1)

    assert len(commands) == 1
    identity = job.visual_continuity_bible.identities[0]
    assert identity.reference_asset_ids != ["11111111-1111-1111-1111-111111111111"]


def test_generate_one_attaches_a_resolved_reference_for_a_later_scene(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(provider, asset_storage_service=asset_storage)

    scene = _scene(2)
    job = _job(scene)

    # Store the pre-existing reference onto the JOB's own persisted
    # index (not a separately-constructed one) - matches how
    # _sync_extracted_frame_asset_index() actually resolves references
    # in production: against job.extracted_frame_asset_index, which
    # this repoints the shared asset_storage at before resolving.
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

    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[asset_id], scene_numbers=[2]
    )

    service.generate_one(job, 2)

    assert len(provider.submitted_requests) == 1
    request = provider.submitted_requests[0]
    assert len(request.reference_assets) == 1
    assert request.reference_assets[0].source_path == result.asset.file_path
    assert request.reference_assets[0].identity_name == "Jack Reid"


def test_generate_one_does_not_attach_a_reference_for_an_off_screen_identity(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29: a first-person narrator "present"
    (mentioned) in a purely-narrated graphic scene, but never actually
    shown on screen, must not get her reference photo attached - Muse
    itself reasonably prioritized an attached photo over the described
    graphic, rendering the wrong content entirely. Gated on
    on_screen_entity_names, not entity_names.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
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
                entity_names=["The narrator"],  # present (narrating)
                on_screen_entity_names=[],  # never actually shown
            )
        ],
    )

    service.generate_one(job, 2)

    assert len(provider.submitted_requests) == 1
    assert provider.submitted_requests[0].reference_assets == []


def test_generate_one_does_not_extract_a_reference_for_an_off_screen_identity(
    tmp_path: Path,
) -> None:
    """Same reasoning as the attachment-side test above, but for the
    OTHER consumer: a scene must not extract a "reference" frame for
    an identity that never appears in its own generated clip either -
    that frame would show whatever the graphic/b-roll actually was,
    not the identity, poisoning every later scene's reference."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    frame_extraction, commands = _frame_extraction_service(tmp_path)
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


def test_generate_one_routes_to_the_scenes_preferred_profile_id(
    tmp_path: Path,
) -> None:
    """Same real-world finding as Google Flow's own equivalent test -
    Scene.preferred_profile_id must route to that EXACT Muse account,
    not whichever one auto-priority would otherwise pick."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    def _profile(profile_id: str, *, priority: int) -> ProviderProfile:
        return ProviderProfile(
            profile_id=profile_id,
            display_name=profile_id,
            provider_name="Muse",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=True,
            priority=priority,
            health_status=ProviderHealthStatus.HEALTHY,
            browser_profile_reference=f"muse_profiles/{profile_id}",
        )

    registry = ProviderRegistry(
        profiles=[
            _profile("muse.primary", priority=1),
            _profile("muse.backup", priority=2),
        ]
    )
    service = _service(provider, registry=registry)

    scene = _scene(1)
    scene.preferred_profile_id = "muse.backup"
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert provider.submitted_requests[0].profile_id == "muse.backup"


# --- Phase 5 (multi-clip scene splitting), 2026-09-29 ---


def test_generate_one_does_not_split_a_muse_scene_within_its_fixed_length(
    tmp_path: Path,
) -> None:
    """A scene whose real narration fits within Muse's fixed ~10s
    single-clip length must take the normal single-clip path - one
    submission, one clip, same as before this feature existed."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    service = _service(provider)

    scene = _scene(1)
    scene.real_narration_duration_seconds = 9.0
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_requests) == 1
    assert provider.submitted_requests[0].clip_sequence_index == 0

    clips = [c for c in job.video_clips if c.scene_number == 1]
    assert len(clips) == 1
    assert clips[0].clip_sequence_index == 0


def test_generate_one_splits_a_muse_scene_whose_narration_exceeds_its_fixed_length(
    tmp_path: Path,
) -> None:
    """
    Phase 5, Muse's own version: a scene whose real narration exceeds
    Muse's fixed ~10s single-clip length (13s here - matches the real
    scene 10 that prompted this feature; plan() splits it evenly into
    two 6.5s sub-clips with no rounding, unlike Flow's bucket-clamped
    split) must submit TWO consecutive requests sharing one
    scene_number, distinguished by clip_sequence_index, and attach both
    as separate VideoClips. The second sub-clip's own request must
    carry a FIRST_FRAME seam reference extracted from the first sub-
    clip's real downloaded file.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    # Two sub-clips must never share a checksum (see
    # _duplicate_scene_number's own real-world finding) - distinct
    # content per sub-clip, not the shared single-file default.
    provider.downloaded_files = [
        str(_real_video_file(tmp_path, name="sub_clip_0.mp4")),
        str(_real_video_file(tmp_path, name="sub_clip_1.mp4")),
    ]
    Path(provider.downloaded_files[1]).write_bytes(b"different sub-clip 1 bytes")

    frame_extraction, commands = _frame_extraction_service(tmp_path)
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )

    service = _service(
        provider,
        frame_extraction_service=frame_extraction,
        asset_storage_service=asset_storage,
    )

    scene = _scene(1)
    scene.real_narration_duration_seconds = 13.0
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert len(provider.submitted_requests) == 2

    first_request, second_request = provider.submitted_requests
    assert first_request.clip_sequence_index == 0
    assert second_request.clip_sequence_index == 1

    assert first_request.reference_assets == []
    assert len(second_request.reference_assets) == 1
    assert second_request.reference_assets[0].role == MuseReferenceRole.FIRST_FRAME

    # A frame-extraction command for the seam between the two sub-clips
    # must have actually run (on top of whatever the fixed 10.0s fake
    # probe's safety-net trims also triggered).
    assert any("-vframes" in command for command in commands)

    clips = sorted(
        (c for c in job.video_clips if c.scene_number == 1),
        key=lambda c: c.clip_sequence_index,
    )
    assert [c.clip_sequence_index for c in clips] == [0, 1]


def test_generate_one_stops_a_muse_split_scene_when_a_sub_clip_never_reaches_ready(
    tmp_path: Path,
) -> None:
    """If an earlier sub-clip never reaches READY (e.g. stuck at an
    interrupt state), the whole split scene stops there rather than
    generating further sub-clips or attaching a partial result - same
    reasoning as Google Flow's own equivalent test."""

    class _RefusingSubmitProvider(_ScriptedProvider):
        def submit(
            self,
            request: MuseGenerationRequest,
            attempt: MuseGenerationAttempt,
        ) -> MuseGenerationAttempt:
            self.submitted_prompts.append(request.prompt)
            self.submitted_requests.append(request)

            return attempt.with_transition(
                MuseGenerationState.UI_CHANGED,
                detail="Simulated real UI change - refuses to proceed.",
            )

    refusing_provider = _RefusingSubmitProvider(observe_sequence=[])

    service = _service(refusing_provider)

    scene = _scene(1)
    scene.real_narration_duration_seconds = 13.0
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status != SceneCompletenessStatus.READY
    assert len(refusing_provider.submitted_requests) == 1
    assert job.video_clips == []


# --- generate_all: settle cooldown between scenes (real Generate All finding) ---


def test_generate_all_sleeps_the_settle_duration_between_scenes(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29: a real Generate All run submitted
    consecutive scenes to Muse with only a few seconds between them -
    Muse's own chat assistant admitted it stacked the rapid-fire
    prompts rather than generating each independently, producing
    duplicate downloads (see _duplicate_scene_number's own docstring).
    generate_all() must sleep generate_all_settle_seconds BETWEEN
    scenes (never before the first one), giving Muse real time to
    finish before the next prompt is sent.
    """

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_files = [
        str(_real_video_file(tmp_path, name=f"scene_{n}.mp4")) for n in (1, 2, 3)
    ]
    for index, path in enumerate(provider.downloaded_files):
        Path(path).write_bytes(f"distinct bytes for scene {index}".encode())

    sleep_calls: list[float] = []

    service = MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=sleep_calls.append,
        generate_all_settle_seconds=20.0,
    )
    job = _job(_scene(1), _scene(2), _scene(3))

    service.generate_all(job)

    assert len(provider.submitted_requests) == 3
    # 2 settle sleeps between 3 scenes (never before the first), plus
    # the real poll sleeps (1.0s each, one per scene here) mixed in -
    # exactly 2 calls at the configured settle duration.
    assert sleep_calls.count(20.0) == 2


def test_generate_all_does_not_sleep_the_settle_duration_for_a_lone_scene(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    sleep_calls: list[float] = []

    service = MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=sleep_calls.append,
        generate_all_settle_seconds=20.0,
    )
    job = _job(_scene(1))

    service.generate_all(job)

    assert 20.0 not in sleep_calls


def test_generate_all_skips_the_settle_sleep_for_an_already_ready_scene(
    tmp_path: Path,
) -> None:
    """A scene already READY is skipped entirely by generate_all() -
    it must not consume a settle-sleep slot before the next real scene
    that actually needs generating."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    sleep_calls: list[float] = []

    service = MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=sleep_calls.append,
        generate_all_settle_seconds=20.0,
    )
    job = _job(_scene(1), _scene(2))
    job.video_clips = [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.AI_GENERATE,
            duration_seconds=8.0,
            local_file=str(_real_video_file(tmp_path, name="already_ready.mp4")),
            status=VideoClipStatus.READY,
        )
    ]

    service.generate_all(job)

    assert len(provider.submitted_requests) == 1  # only scene 2
    assert 20.0 not in sleep_calls


def test_negative_settle_seconds_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        MuseSceneVideoGenerationService(
            orchestrator=_orchestrator(_ScriptedProvider(observe_sequence=[])),
            asset_workflow_service=_asset_workflow_service(),
            generate_all_settle_seconds=-1.0,
        )


def test_generate_one_trims_to_the_real_voice_length_when_the_scene_field_is_empty(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-10-03: a voiceover generated from the Audio tab
    left Scene.real_narration_duration_seconds empty, so Muse was asked to trim
    to the script's estimate. generate_one fills it from the voice track first.
    """

    from src.models.audio_timeline import AudioTimeline
    from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    service = _service(provider)
    scene = _scene(1)
    job = _job(scene)
    job.audio_timeline = AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file="voice/1.mp3",
                duration_seconds=4.0,
                status=AudioTrackStatus.READY,
                metadata={"scene_number": 1},
            )
        ]
    )

    assert scene.real_narration_duration_seconds is None

    service.generate_one(job, 1)

    assert scene.real_narration_duration_seconds == 4.0
    assert "Duration: 4 seconds" in provider.submitted_prompts[0]
    assert "trim the generated" not in provider.submitted_prompts[0]


def test_a_repeat_of_another_scenes_video_is_caught_even_after_it_is_trimmed(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-10-03 (live Remedy project): scene 2 downloaded
    scene 1's Muse video again - the raw files were byte-identical (same
    SHA-256) - but the duplicate guard compared checksums AFTER the local
    safety-net trim, and the same video trimmed to a different scene length is
    a different file. Scene 2 silently got scene 1's footage. The guard must
    compare the untrimmed downloads.
    """

    shared_file = _real_video_file(tmp_path, name="honey-kitchen.mp4")
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(shared_file)

    ten_second_probe = json.dumps(
        {
            "format": {"duration": "10.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        }
    )
    frame_extraction, _commands = _frame_extraction_service(tmp_path)
    service = MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider, probe_output=ten_second_probe),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=lambda _: None,
        frame_extraction_service=frame_extraction,
    )

    scene_one = _scene(1)
    scene_one.real_narration_duration_seconds = 10.0  # no trim needed
    job = _job(scene_one)
    assert service.generate_one(job, 1).status == SceneCompletenessStatus.READY

    scene_two = _scene(2)
    scene_two.real_narration_duration_seconds = 1.0  # same video, trimmed to 1s
    job.scenes.append(scene_two)
    provider._observe_sequence = [  # noqa: SLF001
        MuseGenerationState.GENERATING,
        MuseGenerationState.READY_TO_DOWNLOAD,
    ]

    second = service.generate_one(job, 2)

    assert second.status != SceneCompletenessStatus.READY

    attempt_two = next(
        a for a in job.muse_generation_attempts if a.request.scene_number == 2
    )
    assert attempt_two.state == MuseGenerationState.UI_CHANGED
    assert "scene 1" in (attempt_two.state_history[-1].detail or "")
    # Its post-trim file really did differ - the old guard compared these.
    first_attempt = job.muse_generation_attempts[0]
    assert attempt_two.checksum != first_attempt.checksum
    # ...while the untrimmed downloads are the same video.
    assert attempt_two.source_checksum == first_attempt.source_checksum
    assert 2 not in {clip.scene_number for clip in job.video_clips}


def test_the_source_checksum_survives_a_trim_and_is_set_once(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    ten_second_probe = json.dumps(
        {
            "format": {"duration": "10.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        }
    )
    frame_extraction, _commands = _frame_extraction_service(tmp_path)
    service = MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider, probe_output=ten_second_probe),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=lambda _: None,
        frame_extraction_service=frame_extraction,
    )
    scene = _scene(1)
    scene.real_narration_duration_seconds = 4.0
    job = _job(scene)

    service.generate_one(job, 1)

    attempt = job.muse_generation_attempts[-1]

    assert attempt.source_checksum is not None
    # The trim changed the attached file's checksum, not the source one.
    assert attempt.checksum != attempt.source_checksum


# --- minimum clip length (2026-10-04) ---


def test_a_one_second_scene_is_generated_and_trimmed_to_three_seconds(
    tmp_path: Path,
) -> None:
    """A one-word scene must not become a ~1s clip: the prompt asks Muse for 3s
    and the safety-net trim - which uses the same target - cuts to 3s, not 1s
    (the two sizing places must agree, or the floor would be undone)."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    ten_second_probe = json.dumps(
        {
            "format": {"duration": "10.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        }
    )
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider, probe_output=ten_second_probe),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=lambda _: None,
        frame_extraction_service=frame_extraction,
    )
    scene = _scene(1)
    scene.real_narration_duration_seconds = 1.0
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY

    prompt = provider.submitted_prompts[0]
    assert "Duration: 3 seconds" in prompt
    assert "trim the generated" not in prompt
    assert len(commands) == 1
    trim_command = commands[0]
    assert float(trim_command[trim_command.index("-t") + 1]) == pytest.approx(3.0)


def test_a_scene_at_or_above_the_floor_is_sized_exactly_as_before(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    service = _service(provider)
    scene = _scene(1)
    scene.real_narration_duration_seconds = 4.0
    job = _job(scene)

    service.generate_one(job, 1)

    assert "Duration: 4 seconds" in provider.submitted_prompts[0]
    assert "to only" not in provider.submitted_prompts[0]


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


def test_muse_reference_is_the_best_face_frame_not_the_last_frame(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
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

    assert commands == []
    identity = job.visual_continuity_bible.identities[0]
    asset = job.extracted_frame_asset_index.get(identity.reference_asset_ids[0])
    assert asset is not None
    assert Path(asset.file_path).read_bytes() == b"frame-1"
    assert asset.metadata["selection_method"] == "best_face"


def test_muse_stores_no_reference_when_no_frame_shows_a_clear_face(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, commands = _frame_extraction_service(tmp_path)
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

    assert job.visual_continuity_bible.identities[0].reference_asset_ids == []
    assert commands == []
    assert any("no usable reference frame" in w for w in job.warnings)


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


def test_muse_person_and_place_in_one_scene_get_their_own_frames(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, commands = _frame_extraction_service(tmp_path)
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
    person_asset = job.extracted_frame_asset_index.get(person.reference_asset_ids[0])
    place_asset = job.extracted_frame_asset_index.get(place.reference_asset_ids[0])

    assert person_asset is not None and place_asset is not None
    assert Path(person_asset.file_path).read_bytes() == b"frame-1"
    assert Path(place_asset.file_path).read_bytes() == b"frame-0"
    assert commands == []


def test_muse_location_still_gets_a_reference_when_nobody_is_in_the_scene(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    frame_extraction, _ = _frame_extraction_service(tmp_path)
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
    assert person.reference_asset_ids == []
    assert len(place.reference_asset_ids) == 1


def test_a_muse_clip_is_labelled_as_muse_not_google_flow(tmp_path: Path) -> None:
    """The single-clip attach left the workflow's default provider label
    ("google_flow") on Muse's clips, so the Clip check and any report called a
    Muse clip a Google Flow one (seen live, 2026-10-06)."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    service = _service(provider)
    scene = _scene(1)
    job = _job(scene)

    service.generate_one(job, 1)

    clips = [c for c in job.video_clips if c.scene_number == 1]
    assert clips
    assert {c.provider for c in clips} == {"muse"}


def test_a_narration_with_a_fraction_gets_a_clip_rounded_up_not_down(
    tmp_path: Path,
) -> None:
    """Live, 2026-10-06: 7.38s of narration got a 7s clip and 4.32s got 4s, so the
    voice ran past the picture. The prompt asks for the next whole second and the
    safety-net trim - which uses the same target - cuts to it, not back to 7.38."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    ten_second_probe = json.dumps(
        {
            "format": {"duration": "10.0"},
            "streams": [
                {"codec_type": "video", "width": 1920, "height": 1080},
                {"codec_type": "audio"},
            ],
        }
    )
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = MuseSceneVideoGenerationService(
        orchestrator=_orchestrator(provider, probe_output=ten_second_probe),
        asset_workflow_service=_asset_workflow_service(),
        poll_interval_seconds=1.0,
        max_poll_attempts=10,
        sleep_fn=lambda _: None,
        frame_extraction_service=frame_extraction,
    )
    scene = _scene(1)
    scene.real_narration_duration_seconds = 7.38
    job = _job(scene)

    entry = service.generate_one(job, 1)

    assert entry.status == SceneCompletenessStatus.READY
    assert "Duration: 8 seconds" in provider.submitted_prompts[0]
    assert "to only" not in provider.submitted_prompts[0]
    trim = commands[0]
    assert float(trim[trim.index("-t") + 1]) == pytest.approx(8.0)


def _place_only_bible(asset_id: str, scene_number: int) -> VisualContinuityBible:
    """One place with a reference, and a scene the plan draws as a graphic: nobody
    and nothing is listed on screen in it."""

    return VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="Kitchen",
                canonical_description="A warm family kitchen.",
                reference_asset_ids=[asset_id],
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=scene_number,
                incoming_state=VisualState(),
                shot_action="An infographic.",
                outgoing_state=VisualState(location="informational graphic/overlay"),
                entity_names=[],
                on_screen_entity_names=[],
            )
        ],
    )


def _muse_job_with_place_reference(tmp_path: Path, scene):  # type: ignore[no-untyped-def]
    job = _job(scene)
    storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=job.extracted_frame_asset_index
    )
    source = tmp_path / "place_reference.jpg"
    source.write_bytes(b"a kitchen")
    stored = storage.store_extracted_frame(
        source_path=source, project_id="p", scene_number=1, title="Reference"
    )
    assert stored.success and stored.asset is not None
    job.visual_continuity_bible = _place_only_bible(
        str(stored.asset.id), scene.scene_number
    )

    return job


def test_muse_graphic_scene_gets_no_reference_by_default(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(provider, asset_storage_service=asset_storage)
    job = _muse_job_with_place_reference(tmp_path, _scene(2))

    service.generate_one(job, 2)

    assert provider.submitted_requests[0].reference_assets == []


def test_muse_graphic_scene_on_live_footage_attaches_the_main_places_reference(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    asset_storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    service = _service(provider, asset_storage_service=asset_storage)
    scene = _scene(2)
    scene.treat_as_live_footage = True
    job = _muse_job_with_place_reference(tmp_path, scene)

    service.generate_one(job, 2)

    references = provider.submitted_requests[0].reference_assets
    assert len(references) == 1
    assert references[0].identity_name == "Kitchen"
