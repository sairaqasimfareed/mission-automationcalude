"""
Clip check - references (2026-10-05): for every character and place the
continuity bible puts on screen in a scene, did it have a reference picture, and
did the request that made the clip actually carry it?

No ffmpeg here: the media probe and still extractor are stubbed, since only the
reference logic is under test.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.models.clip_attachment_verification import (  # noqa: E402
    ClipAttachmentVerificationReport,
    ClipVerificationIssueCode,
    ClipVerificationSeverity,
    ReferenceUse,
    SceneClipVerification,
    SceneReferenceStatus,
)
from src.models.google_flow_generation import (  # noqa: E402
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
    GoogleFlowQCOutcome,
    GoogleFlowQCResult,
    GoogleFlowReferenceAsset,
    GoogleFlowReferenceRole,
    GoogleFlowStateTransition,
)
from src.models.media_strategy import SceneSourceStatus, SceneSourceType  # noqa: E402
from src.models.media_technical_validation import (  # noqa: E402
    MediaTechnicalValidationResult,
)
from src.models.muse_generation import (  # noqa: E402
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
    MuseQCOutcome,
    MuseQCResult,
    MuseReferenceAsset,
    MuseReferenceRole,
    MuseStateTransition,
)
from src.models.research import ResearchResult, ResearchStatus  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.script import Script, ScriptStatus  # noqa: E402
from src.models.video_clip import VideoClip, VideoClipStatus  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.models.visual_continuity import (  # noqa: E402
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.asset_storage_service import AssetStorageService  # noqa: E402
from src.services.clip_attachment_verification_service import (  # noqa: E402
    ClipAttachmentVerificationService,
    clip_signature,
)
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    _build_view,
    _FakeSceneVideoGenerationService,
)
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)


class _Probe:
    """Every clip is a readable 4s video."""

    def validate(self, path: Path) -> MediaTechnicalValidationResult:
        return MediaTechnicalValidationResult(
            is_readable=True, duration_seconds=4.0, has_video_stream=True
        )


class _NoStills:
    def extract_frame_at(self, **_kwargs: object) -> str:
        raise RuntimeError("no stills in this test")


def _service(tmp_path: Path) -> ClipAttachmentVerificationService:
    return ClipAttachmentVerificationService(
        thumbnails_root=tmp_path / "thumbs",
        media_validator=_Probe(),  # type: ignore[arg-type]
        frame_extractor=_NoStills(),  # type: ignore[arg-type]
        file_hasher=lambda path: f"hash-of-{path.name}",
    )


def _bible(scene_numbers: list[int]) -> VisualContinuityBible:
    return VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.PERSON,
                name="Mara",
                canonical_description="A beekeeper in a grey coat.",
            ),
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="The Apiary",
                canonical_description="A hillside bee yard.",
            ),
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=n,
                incoming_state=VisualState(),
                shot_action="Works.",
                outgoing_state=VisualState(),
                entity_names=["Mara", "The Apiary"],
                on_screen_entity_names=["Mara", "The Apiary"],
            )
            for n in scene_numbers
        ],
    )


def _job(tmp_path: Path, scenes: int = 4) -> VideoJob:
    job = VideoJob(
        project_name="Refs",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.comedy",
    )
    job.research = ResearchResult(
        topic="A topic",
        research_summary="Summary.",
        prompt_version="t",
        status=ResearchStatus.APPROVED,
    )
    job.script = Script(
        title="S",
        content="Synthetic narration.",
        prompt_version="t",
        word_count=2,
        estimated_duration_seconds=10,
        status=ScriptStatus.APPROVED,
    )
    job.scenes = []
    job.video_clips = []

    for number in range(1, scenes + 1):
        scene = Scene(
            scene_number=number,
            title=f"Scene {number}",
            narration=f"Narration {number}.",
            visual_prompt=f"Visual {number}.",
            estimated_duration_seconds=4,
        )
        scene.real_narration_duration_seconds = 4.0
        job.scenes.append(scene)

        clip_file = tmp_path / "clips" / f"{number}.mp4"
        clip_file.parent.mkdir(parents=True, exist_ok=True)
        clip_file.write_bytes(f"video {number}".encode())
        job.video_clips.append(
            VideoClip(
                scene_number=number,
                source_type=SceneSourceType.AI_GENERATE,
                duration_seconds=4,
                prompt="p",
                provider="Muse",
                local_file=clip_file.as_posix(),
                source_status=SceneSourceStatus.READY,
                status=VideoClipStatus.READY,
            )
        )

    job.visual_continuity_bible = _bible(list(range(1, scenes + 1)))

    return job


def _store_reference(
    job: VideoJob, tmp_path: Path, identity_name: str, *, from_scene: int
) -> str:
    """Store a real reference picture on the job's own index, as extraction does,
    and point the identity at it. Returns its content hash."""

    storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=job.extracted_frame_asset_index
    )
    source = tmp_path / f"{identity_name}-{from_scene}.jpg"
    source.write_bytes(f"picture of {identity_name}".encode())
    result = storage.store_extracted_frame(
        source_path=source,
        project_id="p",
        scene_number=from_scene,
        title=f"Reference - scene {from_scene}",
    )
    assert result.success and result.asset is not None

    identity = next(
        i for i in job.visual_continuity_bible.identities if i.name == identity_name  # type: ignore[union-attr]
    )
    identity.reference_asset_ids = [str(result.asset.id)]

    return result.asset.content_hash or ""


def _muse_attempt(
    scene_number: int,
    *,
    references: list[MuseReferenceAsset] | None = None,
    state: MuseGenerationState = MuseGenerationState.READY,
    attempt_number: int = 1,
    sequence: int = 0,
) -> MuseGenerationAttempt:
    request = MuseGenerationRequest(
        scene_number=scene_number,
        clip_sequence_index=sequence,
        prompt=f"prompt {scene_number}",
        prompt_version="v1",
        profile_id="muse.primary",
        idempotency_key=f"k-{scene_number}-{attempt_number}-{sequence}",
        reference_assets=references or [],
    )
    ready = state == MuseGenerationState.READY

    return MuseGenerationAttempt(
        request=request,
        profile_id="muse.primary",
        attempt_number=attempt_number,
        state=state,
        state_history=[
            MuseStateTransition(state=MuseGenerationState.PLANNED),
            MuseStateTransition(state=state),
        ],
        checksum=f"c-{scene_number}-{attempt_number}",
        qc_result=MuseQCResult(outcome=MuseQCOutcome.PASS) if ready else None,
    )


def _ref(
    name: str | None,
    checksum: str = "x",
    role: MuseReferenceRole = MuseReferenceRole.CHARACTER,
) -> MuseReferenceAsset:
    return MuseReferenceAsset(
        source_path="ref.jpg", checksum=checksum, role=role, identity_name=name
    )


def _result(report, scene_number: int) -> SceneClipVerification:  # type: ignore[no-untyped-def]
    return next(s for s in report.scenes if s.scene_number == scene_number)


def _states(result: SceneClipVerification) -> dict[str, ReferenceUse]:
    return {r.name: r.state for r in result.references}


def _codes(result: SceneClipVerification) -> set[ClipVerificationIssueCode]:
    return {issue.code for issue in result.issues}


# ---- the identity name on a request ------------------------------------


def test_a_reference_remembers_who_it_stands_for() -> None:
    assert _ref("Mara").identity_name == "Mara"


def test_a_reference_without_a_name_still_loads_for_older_requests() -> None:
    asset = MuseReferenceAsset.model_validate(
        {"source_path": "a.jpg", "checksum": "c", "role": "character"}
    )

    assert asset.identity_name is None

    flow = GoogleFlowReferenceAsset.model_validate(
        {"source_path": "a.jpg", "checksum": "c", "role": "character"}
    )

    assert flow.identity_name is None


# ---- what the check reports -------------------------------------------


def test_an_attached_reference_is_reported_attached_with_no_warning(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=2)
    _store_reference(job, tmp_path, "The Apiary", from_scene=2)
    job.muse_generation_attempts = [
        _muse_attempt(
            3,
            references=[
                _ref("Mara"),
                _ref("The Apiary", role=MuseReferenceRole.LOCATION),
            ],
        )
    ]

    scene = _result(_service(tmp_path).verify(job), 3)

    assert _states(scene) == {
        "Mara": ReferenceUse.ATTACHED,
        "The Apiary": ReferenceUse.ATTACHED,
    }
    assert not (
        _codes(scene)
        & {
            ClipVerificationIssueCode.REFERENCE_NOT_ATTACHED,
            ClipVerificationIssueCode.CHARACTER_WITHOUT_REFERENCE,
        }
    )


def test_a_reference_that_existed_but_was_not_sent_is_flagged(tmp_path: Path) -> None:
    """The failure this exists to catch: scene 3 came after Mara's reference but
    its request carried nothing."""

    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=2)
    job.muse_generation_attempts = [_muse_attempt(3, references=[])]

    scene = _result(_service(tmp_path).verify(job), 3)

    assert _states(scene)["Mara"] == ReferenceUse.NOT_ATTACHED
    assert ClipVerificationIssueCode.REFERENCE_NOT_ATTACHED in _codes(scene)
    assert scene.severity == ClipVerificationSeverity.WARNING
    issue = next(
        i
        for i in scene.issues
        if i.code == ClipVerificationIssueCode.REFERENCE_NOT_ATTACHED
    )
    assert "Mara" in issue.message and "scene 2" in issue.message


def test_the_scene_a_reference_came_from_is_not_flagged(tmp_path: Path) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=2)
    job.muse_generation_attempts = [_muse_attempt(2, references=[])]

    scene = _result(_service(tmp_path).verify(job), 2)

    assert _states(scene)["Mara"] == ReferenceUse.SOURCE_SCENE
    assert ClipVerificationIssueCode.REFERENCE_NOT_ATTACHED not in _codes(scene)


def test_a_scene_made_before_the_reference_existed_is_not_flagged(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=3)
    job.muse_generation_attempts = [_muse_attempt(1, references=[])]

    scene = _result(_service(tmp_path).verify(job), 1)

    assert _states(scene)["Mara"] == ReferenceUse.BEFORE_REFERENCE
    assert ClipVerificationIssueCode.REFERENCE_NOT_ATTACHED not in _codes(scene)


def test_a_character_with_no_reference_anywhere_is_flagged(tmp_path: Path) -> None:
    job = _job(tmp_path)
    job.muse_generation_attempts = [_muse_attempt(2, references=[])]

    scene = _result(_service(tmp_path).verify(job), 2)

    assert _states(scene)["Mara"] == ReferenceUse.NO_REFERENCE
    assert ClipVerificationIssueCode.CHARACTER_WITHOUT_REFERENCE in _codes(scene)
    messages = {i.message for i in scene.issues}
    assert any("Mara is on screen" in m and "character" in m for m in messages)
    assert any("The Apiary is on screen" in m and "place" in m for m in messages)


def test_a_reference_whose_file_is_gone_counts_as_no_reference(tmp_path: Path) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    asset_id = job.visual_continuity_bible.identities[0].reference_asset_ids[0]  # type: ignore[union-attr]
    Path(job.extracted_frame_asset_index.get(asset_id).file_path).unlink()  # type: ignore[union-attr]
    job.muse_generation_attempts = [_muse_attempt(3, references=[])]

    scene = _result(_service(tmp_path).verify(job), 3)

    assert _states(scene)["Mara"] == ReferenceUse.NO_REFERENCE


def test_an_older_request_with_no_names_is_matched_by_the_pictures_checksum(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    mara_hash = _store_reference(job, tmp_path, "Mara", from_scene=1)
    job.muse_generation_attempts = [
        _muse_attempt(3, references=[_ref(None, checksum=mara_hash)])
    ]

    scene = _result(_service(tmp_path).verify(job), 3)

    assert _states(scene)["Mara"] == ReferenceUse.ATTACHED


def test_stock_footage_with_no_generation_attempt_is_not_checked(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    # scene 3 has no attempt at all: a stock/manual clip is never sent a reference

    scene = _result(_service(tmp_path).verify(job), 3)

    assert scene.references == []
    assert not (_codes(scene) & {ClipVerificationIssueCode.REFERENCE_NOT_ATTACHED})


def test_an_identity_off_screen_in_the_scene_is_not_listed(tmp_path: Path) -> None:
    job = _job(tmp_path)
    job.visual_continuity_bible.clip_entries[2].on_screen_entity_names = ["Mara"]  # type: ignore[union-attr]
    job.muse_generation_attempts = [_muse_attempt(3, references=[])]

    scene = _result(_service(tmp_path).verify(job), 3)

    assert list(_states(scene)) == ["Mara"]


def test_the_attempt_that_made_the_clip_decides_not_a_later_failed_one(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    job.muse_generation_attempts = [
        _muse_attempt(3, references=[_ref("Mara")], attempt_number=1),
        _muse_attempt(
            3, references=[], attempt_number=2, state=MuseGenerationState.FAILED
        ),
    ]

    scene = _result(_service(tmp_path).verify(job), 3)

    assert _states(scene)["Mara"] == ReferenceUse.ATTACHED


def test_a_split_scene_counts_a_reference_attached_to_any_of_its_clips(
    tmp_path: Path,
) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    job.muse_generation_attempts = [
        _muse_attempt(3, references=[_ref("Mara")], sequence=0),
        _muse_attempt(3, references=[], sequence=1),
    ]

    scene = _result(_service(tmp_path).verify(job), 3)

    assert _states(scene)["Mara"] == ReferenceUse.ATTACHED


def test_a_google_flow_scene_is_checked_the_same_way(tmp_path: Path) -> None:
    job = _job(tmp_path)
    _store_reference(job, tmp_path, "Mara", from_scene=1)
    request = GoogleFlowGenerationRequest(
        scene_number=3,
        prompt="p",
        prompt_version="v1",
        profile_id="flow.primary",
        idempotency_key="flow-3",
        reference_assets=[
            GoogleFlowReferenceAsset(
                source_path="r.jpg",
                checksum="x",
                role=GoogleFlowReferenceRole.CHARACTER,
                identity_name="Mara",
            )
        ],
    )
    job.flow_generation_attempts = [
        GoogleFlowGenerationAttempt(
            request=request,
            profile_id="flow.primary",
            state=GoogleFlowGenerationState.READY,
            state_history=[
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.PLANNED),
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.READY),
            ],
            qc_result=GoogleFlowQCResult(outcome=GoogleFlowQCOutcome.PASS),
        )
    ]

    scene = _result(_service(tmp_path).verify(job), 3)

    assert _states(scene)["Mara"] == ReferenceUse.ATTACHED


def test_a_job_without_a_continuity_bible_is_unaffected(tmp_path: Path) -> None:
    job = _job(tmp_path)
    job.visual_continuity_bible = None
    job.muse_generation_attempts = [_muse_attempt(2)]

    scene = _result(_service(tmp_path).verify(job), 2)

    assert scene.references == []


def test_a_report_saved_before_references_existed_still_loads() -> None:
    report = ClipAttachmentVerificationReport.model_validate(
        {"scenes": [{"scene_number": 1, "scene_title": "Old"}]}
    )

    assert report.scenes[0].references == []


# ---- the Clip check row -----------------------------------------------


def _texts(view) -> list[str]:  # type: ignore[no-untyped-def]
    job = view._current_job()  # noqa: SLF001

    if job is not None:
        view.refresh(job)

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    return [label.text() for label in view.findChildren(QLabel)]


def _view_for(statuses: list[SceneReferenceStatus], tmp_path: Path):  # type: ignore[no-untyped-def]
    from tests.test_clip_workspace_view_scene_generation import _job as view_job

    job = view_job(1)
    issues = []

    for status in statuses:
        if status.state == ReferenceUse.NOT_ATTACHED:
            issues.append(
                _issue(ClipVerificationIssueCode.REFERENCE_NOT_ATTACHED, status.name)
            )
        elif status.state == ReferenceUse.NO_REFERENCE:
            issues.append(
                _issue(
                    ClipVerificationIssueCode.CHARACTER_WITHOUT_REFERENCE, status.name
                )
            )

    job.clip_verification_report = ClipAttachmentVerificationReport(
        clip_signature=clip_signature(job),
        scenes=[
            SceneClipVerification(
                scene_number=1,
                scene_title="Scene 1",
                references=statuses,
                issues=issues,
            )
        ],
    )

    return _build_view(job, service=_FakeSceneVideoGenerationService())


def _issue(code: ClipVerificationIssueCode, name: str):  # type: ignore[no-untyped-def]
    from src.models.clip_attachment_verification import ClipVerificationIssue

    return ClipVerificationIssue(
        code=code,
        severity=ClipVerificationSeverity.WARNING,
        message=f"{name} issue message",
    )


def test_each_reference_state_reads_in_plain_words(
    qapp: QApplication, tmp_path: Path  # noqa: F811
) -> None:
    view = _view_for(
        [
            SceneReferenceStatus(name="Mara", state=ReferenceUse.ATTACHED),
            SceneReferenceStatus(name="Jack", state=ReferenceUse.SOURCE_SCENE),
            SceneReferenceStatus(name="Ola", state=ReferenceUse.BEFORE_REFERENCE),
            SceneReferenceStatus(
                name="Pia",
                state=ReferenceUse.NOT_ATTACHED,
                reference_scene=2,
            ),
            SceneReferenceStatus(
                name="The Apiary", is_person=False, state=ReferenceUse.NO_REFERENCE
            ),
        ],
        tmp_path,
    )

    texts = _texts(view)

    assert "Mara (character) - reference attached" in texts
    assert any("Jack" in t and "taken from" in t for t in texts)
    assert any("Ola" in t and "before a reference existed" in t for t in texts)
    assert any("Pia has a reference (from scene 2)" in t for t in texts)
    assert any("The Apiary is on screen" in t and "place" in t for t in texts)


def test_a_reference_problem_is_shown_once_not_twice(
    qapp: QApplication, tmp_path: Path  # noqa: F811
) -> None:
    view = _view_for(
        [
            SceneReferenceStatus(
                name="Pia", state=ReferenceUse.NOT_ATTACHED, reference_scene=2
            )
        ],
        tmp_path,
    )

    texts = _texts(view)

    assert not any("Pia issue message" in t for t in texts)  # the raw issue is hidden
    assert sum(1 for t in texts if "Pia has a reference" in t) == 1


def test_the_reference_picture_is_shown_beside_its_line(
    qapp: QApplication, tmp_path: Path  # noqa: F811
) -> None:
    picture = tmp_path / "ref.png"
    image = QImage(200, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("blue"))
    assert image.save(str(picture))

    view = _view_for(
        [
            SceneReferenceStatus(
                name="Mara", state=ReferenceUse.ATTACHED, reference_file=str(picture)
            )
        ],
        tmp_path,
    )
    _texts(view)  # refresh + flush

    thumbs = [
        label
        for label in view.findChildren(QLabel)
        if label.pixmap() is not None
        and not label.pixmap().isNull()
        and label.maximumWidth() == 44  # the reference thumbnail, not a card icon
    ]

    assert len(thumbs) == 1


def test_a_graphic_scene_on_live_footage_is_checked_for_the_main_places_reference(
    tmp_path: Path,
) -> None:
    """The switch makes the main place count as on screen, so the Clip check holds
    the scene to having that place's reference attached."""

    job = _job(tmp_path)
    _store_reference(job, tmp_path, "The Apiary", from_scene=1)
    for entry in job.visual_continuity_bible.clip_entries:  # type: ignore[union-attr]
        entry.on_screen_entity_names = []

    job.muse_generation_attempts = [_muse_attempt(3, references=[])]

    before = _result(_service(tmp_path).verify(job), 3)
    assert before.references == []  # nobody on screen: nothing to hold it to

    next(s for s in job.scenes if s.scene_number == 3).treat_as_live_footage = True

    after = _result(_service(tmp_path).verify(job), 3)

    assert _states(after) == {"The Apiary": ReferenceUse.NOT_ATTACHED}
