"""
Muse refusals (2026-10-08, live: Lake Nyos village). Muse's video tool can refuse a request and
Muse says so in chat instead of sending a video; the adapter used to wait for a video until the poll
limit and then fail vaguely, which would stop a "Generate all" run. A refusal is now recognised, a
request that carried a reference picture is sent once more without it, and a refusal that remains is
reported with Muse's own words. The "use the attached image" sentence is no longer sent to Muse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.asset_index import AssetIndex
from src.models.muse_generation import (
    MuseFailure,
    MuseFailureCode,
    MuseGenerationAttempt,
    MuseGenerationState,
)
from src.models.scene_completeness import SceneCompletenessStatus
from src.providers.muse.refusal import looks_like_refusal, refusal_message
from src.services.asset_storage_service import AssetStorageService
from src.services.muse_generation_ledger_service import MuseGenerationLedgerService
from src.services.scene_reference_override import (
    OVERRIDE_LABEL,
    OVERRIDE_PROMPT_SENTENCE,
)
from tests.test_muse_scene_video_generation_service import (
    _job as muse_job,
)
from tests.test_muse_scene_video_generation_service import (
    _real_video_file,
    _ScriptedProvider,
)
from tests.test_muse_scene_video_generation_service import (
    _scene as muse_scene,
)
from tests.test_muse_scene_video_generation_service import (
    _service as muse_service,
)
from tests.test_scene_reference import _store_frame

_THE_LIVE_REFUSAL = (
    "The tool refused that specific combination — the prompt plus that image "
    "together. It judges each request on its own and doesn't give me a detailed "
    "reason, and I can't override it. The text-only version of the same shot is "
    "still available if you want it."
)


# ------------------------------------------------------------------ recognising it


def test_the_live_refusal_is_recognised() -> None:
    assert looks_like_refusal(_THE_LIVE_REFUSAL) is True


@pytest.mark.parametrize(
    "reply",
    [
        "I can't generate that scene.",
        "Sorry, I cannot create this video.",
        "I'm unable to make that one.",
        "That request was declined by the video tool.",
        "This breaks the content policy, so I won't be able to make it.",
        "It didn't go through.",
        "The tool refuses requests like this one.",
    ],
)
def test_other_refusal_wordings_are_recognised(reply: str) -> None:
    assert looks_like_refusal(reply) is True


@pytest.mark.parametrize(
    "reply",
    [
        None,
        "",
        "   ",
        "Generating your video now - this can take a minute.",
        "Here is your clip!",
        "Working on it.",
        "A 4 second pan across the village, as requested.",
    ],
)
def test_normal_replies_are_not_taken_for_a_refusal(reply: str | None) -> None:
    assert looks_like_refusal(reply) is False


def test_the_failure_message_carries_muses_own_words_shortened() -> None:
    message = refusal_message("  The tool refused   this. " + "x" * 800)

    assert message.startswith("Muse refused this request: The tool refused this.")
    assert len(message) < 600
    assert message.endswith("...")


# ------------------------------------------------------- the retry without the picture


class _RefusingProvider(_ScriptedProvider):
    """Refuses a request that carries a reference picture (or every request, when
    `refuse_everything`), exactly as the adapter now reports a refusal: FAILED with a
    REFUSED failure. Otherwise it behaves like the scripted provider."""

    def __init__(self, *, refuse_everything: bool = False, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        self._refuse_everything = refuse_everything

    def observe(self, attempt: MuseGenerationAttempt) -> MuseGenerationAttempt:
        if self._refuse_everything or attempt.request.reference_assets:
            refused = attempt.model_copy(
                update={
                    "failure": MuseFailure(
                        code=MuseFailureCode.REFUSED,
                        message=refusal_message(_THE_LIVE_REFUSAL),
                    )
                }
            )

            return refused.with_transition(
                MuseGenerationState.FAILED, detail="Muse refused this request."
            )

        return super().observe(attempt)


def _setup(tmp_path: Path, *, with_pick: bool, refuse_everything: bool = False):  # type: ignore[no-untyped-def]
    provider = _RefusingProvider(
        refuse_everything=refuse_everything,
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ],
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    scene = muse_scene(2)
    scene.real_narration_duration_seconds = 3.0
    job = muse_job(scene)
    service = muse_service(
        provider,
        asset_storage_service=AssetStorageService(
            storage_root=tmp_path / "svc", asset_index=AssetIndex()
        ),
    )

    if with_pick:
        scene.reference_override_asset_id = _store_frame(job, tmp_path, scene_number=1)

    return service, job, scene, provider


def test_a_refusal_with_a_picture_is_retried_once_without_it(tmp_path: Path) -> None:
    service, job, _scene, provider = _setup(tmp_path, with_pick=True)

    entry = service.generate_one(job, 2)

    assert len(provider.submitted_requests) == 2
    assert len(provider.submitted_requests[0].reference_assets) == 1
    assert provider.submitted_requests[1].reference_assets == []
    assert entry.status == SceneCompletenessStatus.READY
    latest = MuseGenerationLedgerService.latest_attempt_for_scene(job, 2)
    assert latest is not None and latest.state == MuseGenerationState.READY
    assert any(
        "refused the prompt together with its reference picture" in w
        for w in job.warnings
    )


def test_a_second_refusal_is_reported_not_retried_again(tmp_path: Path) -> None:
    service, job, _scene, provider = _setup(
        tmp_path, with_pick=True, refuse_everything=True
    )

    entry = service.generate_one(job, 2)
    attempt = MuseGenerationLedgerService.latest_attempt_for_scene(job, 2)

    assert len(provider.submitted_requests) == 2  # the first try and ONE retry
    assert entry.status != SceneCompletenessStatus.READY
    assert attempt is not None
    assert attempt.state == MuseGenerationState.FAILED
    assert attempt.failure is not None
    assert attempt.failure.code == MuseFailureCode.REFUSED
    assert "Muse refused this request" in attempt.failure.message


def test_a_refusal_of_a_request_with_no_picture_is_not_retried(tmp_path: Path) -> None:
    service, job, _scene, provider = _setup(
        tmp_path, with_pick=False, refuse_everything=True
    )

    entry = service.generate_one(job, 2)
    attempt = MuseGenerationLedgerService.latest_attempt_for_scene(job, 2)

    assert len(provider.submitted_requests) == 1
    assert entry.status != SceneCompletenessStatus.READY
    assert attempt is not None
    assert attempt.state == MuseGenerationState.FAILED
    assert attempt.failure is not None
    assert attempt.failure.code == MuseFailureCode.REFUSED
    assert job.warnings == []


def test_a_request_that_was_not_refused_is_left_alone(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    scene = muse_scene(2)
    scene.real_narration_duration_seconds = 3.0
    job = muse_job(scene)
    service = muse_service(
        provider,
        asset_storage_service=AssetStorageService(
            storage_root=tmp_path / "svc", asset_index=AssetIndex()
        ),
    )
    scene.reference_override_asset_id = _store_frame(job, tmp_path, scene_number=1)

    service.generate_one(job, 2)

    assert len(provider.submitted_requests) == 1
    assert len(provider.submitted_requests[0].reference_assets) == 1


# ------------------------------------------------- no "use the attached image" sentence


def test_muse_gets_the_picked_picture_but_not_the_use_it_sentence(
    tmp_path: Path,
) -> None:
    """Live: Muse ignores an attached picture unless told to use it, and the sentence sent
    the picture to the video tool, which refused it. For Muse the written description carries
    the look; the picture stays attached (harmless)."""

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    scene = muse_scene(2)
    scene.real_narration_duration_seconds = 3.0
    job = muse_job(scene)
    service = muse_service(
        provider,
        asset_storage_service=AssetStorageService(
            storage_root=tmp_path / "svc", asset_index=AssetIndex()
        ),
    )
    scene.reference_override_asset_id = _store_frame(job, tmp_path, scene_number=1)

    service.generate_one(job, 2)

    request = provider.submitted_requests[0]

    assert [r.identity_name for r in request.reference_assets] == [OVERRIDE_LABEL]
    assert OVERRIDE_PROMPT_SENTENCE not in request.prompt
