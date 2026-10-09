"""
Auto-generated suggestions (2026-10-07): the project look and the recurring characters
and places are proposed by the app, and the operator accepts or discards each one -
the two Content Studio forms are no longer blank (the operator cannot fill them by
hand).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.models.media_strategy import SceneSourceType  # noqa: E402
from src.models.project_look import ProjectLook  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.suggestions import (  # noqa: E402
    IdentitySuggestion,
    LookSuggestion,
    SuggestionStatus,
)
from src.models.video_clip import VideoClip  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.models.visual_continuity import (  # noqa: E402
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.genre_profile_registry_service import (  # noqa: E402
    GenreProfileRegistryService,
)
from src.services.identity_suggestion_service import (  # noqa: E402
    IdentitySuggestionService,
)
from src.services.llm.llm_service import LLMServiceResult  # noqa: E402
from src.services.project_look_suggestion_service import (  # noqa: E402
    ProjectLookSuggestionService,
)
from src.services.reference_frame_selection_service import SampledFrame  # noqa: E402
from src.shared.llm.models import (  # noqa: E402
    LLMCallResult,
    LLMCallStatus,
    LLMProvider,
)
from src.shared.llm.request import LLMRequest  # noqa: E402


def _job(genre: str = "genre.medical", scenes: int = 6) -> VideoJob:
    job = VideoJob(
        project_name="Remedy",
        channel_name="Channel",
        niche="health",
        topic="Honey for coughs",
        genre_id=genre,
    )
    job.scenes = [
        Scene(
            scene_number=n,
            title=f"Scene {n}",
            narration=f"Narration {n}.",
            visual_prompt=f"Visual {n}.",
            estimated_duration_seconds=8,
        )
        for n in range(1, scenes + 1)
    ]
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=[
            CanonicalEntityIdentity(
                entity_type=CanonicalEntityType.LOCATION,
                name="Kitchen",
                canonical_description="A warm family kitchen.",
            )
        ],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=n,
                incoming_state=VisualState(),
                shot_action=f"Shot {n}.",
                outgoing_state=VisualState(),
            )
            for n in range(1, scenes + 1)
        ],
    )

    return job


# ------------------------------------------------------------------- models


def test_a_suggestion_starts_pending_and_cleans_its_text() -> None:
    look = LookSuggestion(label=" Warm  home ", lighting="warm   light")
    identity = IdentitySuggestion(
        name=" Grandmother ",
        kind=CanonicalEntityType.PERSON,
        description="An elderly   woman.",
        scene_numbers=[1, 2],
    )

    assert look.status == SuggestionStatus.PENDING
    assert look.label == "Warm home"
    assert look.lighting == "warm light"
    assert identity.name == "Grandmother"
    assert identity.description == "An elderly woman."
    assert identity.key == "grandmother"


def test_suggestions_and_their_status_survive_saving_the_project() -> None:
    job = _job(scenes=0)  # a project with scenes needs a script to reload
    job.look_suggestions = [LookSuggestion(label="A", lighting="x")]
    job.look_suggestions[0].status = SuggestionStatus.DISCARDED
    job.identity_suggestions = [
        IdentitySuggestion(
            name="Nana",
            kind=CanonicalEntityType.PERSON,
            description="Grey hair.",
            scene_numbers=[1, 2],
        )
    ]

    reloaded = VideoJob.model_validate_json(job.model_dump_json())

    assert reloaded.look_suggestions[0].status == SuggestionStatus.DISCARDED
    assert reloaded.identity_suggestions[0].name == "Nana"


def test_a_project_saved_before_suggestions_existed_still_loads() -> None:
    data = _job(scenes=0).model_dump(mode="json")
    data.pop("look_suggestions")
    data.pop("identity_suggestions")

    job = VideoJob.model_validate(data)

    assert job.look_suggestions == []
    assert job.identity_suggestions == []


# ------------------------------------------------------------ look: by genre


def test_every_genre_has_looks_that_fit_the_project_look_fields() -> None:
    """Each suggested look must be usable as a ProjectLook (200-character fields)."""

    service = ProjectLookSuggestionService()

    for profile in GenreProfileRegistryService.with_default_profiles().list_all():
        looks = service.genre_suggestions(_job(genre=profile.genre_id))

        assert len(looks) >= 2, profile.genre_id

        for look in looks:
            assert look.source == "genre"
            ProjectLook(
                lighting=look.lighting,
                color_palette=look.color_palette,
                camera_feel=look.camera_feel,
            )


def test_an_unknown_genre_falls_back_to_the_default_looks() -> None:
    looks = ProjectLookSuggestionService().genre_suggestions(_job(genre="genre.nope"))

    assert [look.label for look in looks] == ["Natural daylight", "Warm and cinematic"]


def test_the_medical_looks_are_the_medical_ones() -> None:
    looks = ProjectLookSuggestionService().genre_suggestions(_job())

    assert [look.label for look in looks] == ["Clean and clinical", "Warm home care"]


# ----------------------------------------------------------- look: from clips


def _frame(blue: int, green: int, red: int) -> SampledFrame:
    image = np.zeros((90, 160, 3), dtype=np.uint8)
    image[:, :] = (blue, green, red)

    return SampledFrame(index=0, time_seconds=0.0, image=image)


def _job_with_clip(tmp_path: Path) -> VideoJob:
    job = _job()
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    job.video_clips.append(
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.AI_GENERATE,
            duration_seconds=8,
            local_file=str(path),
        )
    )

    return job


def test_a_dim_warm_clip_is_described_as_dim_and_warm(tmp_path: Path) -> None:
    service = ProjectLookSuggestionService(
        frame_sampler=lambda _path, _count: [_frame(25, 45, 70)] * 3
    )

    look = service.clips_suggestion(_job_with_clip(tmp_path))

    assert look is not None
    assert look.source == "clips"
    assert look.lighting == "dim, low-key, warm light"
    assert look.color_palette == "vivid warm amber tones"
    assert look.label == "From your clips (1)"


def test_a_bright_cool_clip_is_described_as_bright_and_cool(tmp_path: Path) -> None:
    service = ProjectLookSuggestionService(
        frame_sampler=lambda _path, _count: [_frame(200, 170, 150)] * 3
    )

    look = service.clips_suggestion(_job_with_clip(tmp_path))

    assert look is not None
    assert look.lighting == "bright, airy, cool light"
    assert look.color_palette == "muted cool blue tones"


def test_no_generated_clips_means_no_measured_look() -> None:
    service = ProjectLookSuggestionService(
        frame_sampler=lambda _path, _count: [_frame(25, 45, 70)]
    )

    assert service.clips_suggestion(_job()) is None


def test_an_unreadable_clip_is_skipped_not_fatal(tmp_path: Path) -> None:
    def failing(_path: str, _count: int) -> list[SampledFrame]:
        raise RuntimeError("cannot read")

    service = ProjectLookSuggestionService(frame_sampler=failing)

    assert service.clips_suggestion(_job_with_clip(tmp_path)) is None


def test_a_look_the_operator_already_saw_is_not_proposed_again() -> None:
    job = _job()
    service = ProjectLookSuggestionService()
    job.look_suggestions = service.genre_suggestions(job)
    job.look_suggestions[0].status = SuggestionStatus.DISCARDED

    assert service.suggest(job) == []


# ------------------------------------------------------- characters and places


class _StubLLM:
    def __init__(self, content: str, *, success: bool = True) -> None:
        self._content = content
        self._success = success
        self.requests: list[LLMRequest] = []

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        self.requests.append(request)
        status = (
            LLMCallStatus.SUCCESS if self._success else LLMCallStatus.PROVIDER_ERROR
        )
        result = LLMCallResult(
            status=status,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=self._content if self._success else None,
            error_message=None if self._success else "Provider unavailable.",
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="openai-main" if self._success else None,
            all_providers_failed=not self._success,
        )


_ANSWER = """NAME: Grandmother
KIND: person
DESCRIPTION: An elderly woman with grey hair, in a dark floral robe.
SCENES: 1-3, 5
---
NAME: The village
KIND: place
DESCRIPTION: A hillside village of thatched huts.
SCENES: 2, 4
"""


def _suggest(answer: str, *, already_seen: set[str] | None = None, job=None):  # type: ignore[no-untyped-def]
    job = job or _job()
    service = IdentitySuggestionService(llm_service=_StubLLM(answer))  # type: ignore[arg-type]

    return service.suggest(
        scenes=job.scenes,
        visual_continuity_bible=job.visual_continuity_bible,  # type: ignore[arg-type]
        topic=job.topic,
        already_seen=already_seen or set(),
    )


def test_the_answer_becomes_pending_candidates_with_their_scenes() -> None:
    suggestions = _suggest(_ANSWER)

    assert [s.name for s in suggestions] == ["Grandmother", "The village"]
    assert suggestions[0].kind == CanonicalEntityType.PERSON
    assert suggestions[0].scene_numbers == [1, 2, 3, 5]
    assert suggestions[1].kind == CanonicalEntityType.LOCATION
    assert all(s.status == SuggestionStatus.PENDING for s in suggestions)


def test_none_means_no_candidates() -> None:
    assert _suggest("NONE") == []
    assert _suggest("") == []


def test_the_prompt_lists_every_scene_and_who_is_already_known() -> None:
    job = _job()
    llm = _StubLLM("NONE")
    IdentitySuggestionService(llm_service=llm).suggest(  # type: ignore[arg-type]
        scenes=job.scenes,
        visual_continuity_bible=job.visual_continuity_bible,  # type: ignore[arg-type]
        topic=job.topic,
        already_seen=set(),
    )

    prompt = llm.requests[0].prompt
    assert "SCENE 1: Narration 1." in prompt
    assert "SCENE 6: Narration 6." in prompt
    assert "Kitchen (location)" in prompt
    assert "do NOT repeat" in prompt


@pytest.mark.parametrize(
    "block",
    [
        "NAME: Solo\nKIND: person\nDESCRIPTION: One scene only.\nSCENES: 3",
        "NAME: Robot\nKIND: machine\nDESCRIPTION: Not a person or place.\nSCENES: 1-2",
        "NAME: Ghost\nKIND: person\nDESCRIPTION: Bad scenes.\nSCENES: 90-91",
        "NAME: NoScenes\nKIND: person\nDESCRIPTION: Missing scenes line.",
        "NAME: Kitchen\nKIND: place\nDESCRIPTION: Already known.\nSCENES: 1-2",
    ],
)
def test_unusable_candidates_are_dropped(block: str) -> None:
    assert _suggest(block) == []


def test_a_name_already_pending_accepted_or_discarded_is_not_proposed_again() -> None:
    suggestions = _suggest(_ANSWER, already_seen={"grandmother"})

    assert [s.name for s in suggestions] == ["The village"]


def test_a_failed_call_raises_with_the_reason() -> None:
    service = IdentitySuggestionService(
        llm_service=_StubLLM("", success=False)  # type: ignore[arg-type]
    )
    job = _job()

    with pytest.raises(RuntimeError, match="Provider unavailable"):
        service.suggest(
            scenes=job.scenes,
            visual_continuity_bible=job.visual_continuity_bible,  # type: ignore[arg-type]
            topic="x",
            already_seen=set(),
        )


# ---------------------------------------------------------- the pipeline stage


def _pipeline(answer: str):  # type: ignore[no-untyped-def]
    from src.services.content_intelligence_pipeline import ContentIntelligencePipeline

    pipeline = ContentIntelligencePipeline.__new__(ContentIntelligencePipeline)
    pipeline.identity_suggestion_service = IdentitySuggestionService(
        llm_service=_StubLLM(answer)  # type: ignore[arg-type]
    )

    return pipeline


def test_the_stage_adds_new_candidates_and_never_duplicates_them() -> None:
    job = _job()
    pipeline = _pipeline(_ANSWER)

    pipeline.run_identity_suggestions(job)
    pipeline.run_identity_suggestions(job)

    assert [s.name for s in job.identity_suggestions] == ["Grandmother", "The village"]


def test_a_discarded_candidate_is_not_brought_back() -> None:
    job = _job()
    pipeline = _pipeline(_ANSWER)
    pipeline.run_identity_suggestions(job)
    job.identity_suggestions[0].status = SuggestionStatus.DISCARDED

    pipeline.run_identity_suggestions(job)

    assert [s.name for s in job.identity_suggestions] == ["Grandmother", "The village"]
    assert job.identity_suggestions[0].status == SuggestionStatus.DISCARDED


def test_the_stage_needs_a_bible() -> None:
    job = _job()
    job.visual_continuity_bible = None

    with pytest.raises(RuntimeError, match="continuity bible"):
        _pipeline(_ANSWER).run_identity_suggestions(job)


# ------------------------------------------------------------ Content Studio


def _studio(job: VideoJob):  # type: ignore[no-untyped-def]
    from src.desktop.job_store import InMemoryJobStore
    from tests.test_content_studio_content_intelligence_gui import _job as studio_job
    from tests.test_content_studio_content_intelligence_gui import _view as studio_view

    store = InMemoryJobStore()
    base = studio_job()
    base.genre_id = job.genre_id
    base.scenes = job.scenes
    base.visual_continuity_bible = job.visual_continuity_bible
    base.identity_suggestions = job.identity_suggestions
    store.add(base)
    view = studio_view(store)
    view.set_job(base.id)
    errors: list[str] = []
    view._record_error = (  # type: ignore[method-assign]  # noqa: SLF001
        lambda j, message, **kwargs: errors.append(message)
    )

    return view, base, errors


def _texts(widget) -> list[str]:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel, QPushButton

    return [w.text() for w in widget.findChildren(QLabel)] + [
        b.text() for b in widget.findChildren(QPushButton)
    ]


def test_the_look_section_proposes_the_genres_looks_on_first_view(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    view, job, _errors = _studio(_job())
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._render_project_look_section(layout, job)  # noqa: SLF001

    texts = _texts(holder)
    assert "Clean and clinical" in texts
    assert "Warm home care" in texts
    assert texts.count("Use this look") == 2
    assert "Suggest a look from my clips" in texts
    assert len(job.look_suggestions) == 2  # saved on the project, not only shown


def test_using_a_look_fills_and_saves_it_and_marks_it_accepted(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio(_job())
    view._ensure_look_suggestions(job)  # noqa: SLF001
    chosen = job.look_suggestions[1]

    view._handle_use_look(chosen.id)  # noqa: SLF001

    assert errors == []
    assert job.project_look is not None
    assert job.project_look.lighting == chosen.lighting
    assert chosen.status == SuggestionStatus.ACCEPTED
    assert job.look_suggestions[0].status == SuggestionStatus.PENDING


def test_discarding_a_look_hides_it_for_good(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, _errors = _studio(_job())
    view._ensure_look_suggestions(job)  # noqa: SLF001
    first = job.look_suggestions[0]

    view._handle_discard_look(first.id)  # noqa: SLF001
    view._ensure_look_suggestions(job)  # noqa: SLF001

    assert first.status == SuggestionStatus.DISCARDED
    assert len(job.look_suggestions) == 2  # not regenerated


def test_pending_characters_are_listed_with_accept_edit_and_discard(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    job = _job()
    job.identity_suggestions = _suggest(_ANSWER)
    view, studio_job, _errors = _studio(job)
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._render_recurring_identities_section(layout, studio_job)  # noqa: SLF001

    texts = " ".join(_texts(holder))
    assert "Grandmother" in texts
    assert "Scenes: 1-3, 5" in texts
    assert _texts(holder).count("Accept") == 2
    assert _texts(holder).count("Edit first") == 2
    assert _texts(holder).count("Discard") == 2


def test_accepting_a_character_adds_it_and_marks_the_suggestion(qapp) -> None:  # type: ignore[no-untyped-def]
    job = _job()
    job.identity_suggestions = _suggest(_ANSWER)
    view, studio_job, errors = _studio(job)
    suggestion = studio_job.identity_suggestions[0]

    view._handle_accept_identity_suggestion(suggestion.id)  # noqa: SLF001

    assert errors == []
    bible = studio_job.visual_continuity_bible
    assert bible is not None
    added = next(i for i in bible.identities if i.name == "Grandmother")
    assert added.is_manual is True
    assert suggestion.status == SuggestionStatus.ACCEPTED
    entry = bible.entry_for_scene(5)
    assert entry is not None
    assert "Grandmother" in entry.on_screen_entity_names


def test_edit_first_fills_the_form_without_adding(qapp) -> None:  # type: ignore[no-untyped-def]
    job = _job()
    job.identity_suggestions = _suggest(_ANSWER)
    view, studio_job, _errors = _studio(job)
    suggestion = studio_job.identity_suggestions[1]

    view._handle_edit_identity_suggestion(suggestion.id)  # noqa: SLF001

    assert view._recurring_form["name"] == "The village"  # noqa: SLF001
    assert view._recurring_form["kind"] == "location"  # noqa: SLF001
    assert view._recurring_form["scenes"] == "2, 4"  # noqa: SLF001
    assert suggestion.status == SuggestionStatus.PENDING
    assert [i.name for i in studio_job.visual_continuity_bible.identities] == ["Kitchen"]  # type: ignore[union-attr]


def test_discarding_a_character_suggestion_keeps_it_out(qapp) -> None:  # type: ignore[no-untyped-def]
    job = _job()
    job.identity_suggestions = _suggest(_ANSWER)
    view, studio_job, _errors = _studio(job)
    suggestion = studio_job.identity_suggestions[0]

    view._handle_discard_identity_suggestion(suggestion.id)  # noqa: SLF001

    assert suggestion.status == SuggestionStatus.DISCARDED
    assert [i.name for i in studio_job.visual_continuity_bible.identities] == ["Kitchen"]  # type: ignore[union-attr]


from tests.test_content_studio_content_intelligence_gui import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)

# ----------------------------------------- recurring places are added by themselves


def _pipeline_that_adds_places(tmp_path: Path, answer: str):  # type: ignore[no-untyped-def]
    from src.services.recurring_identity_service import RecurringIdentityService
    from tests.test_recurring_identity_service import _Selector

    pipeline = _pipeline(answer)
    pipeline.recurring_identity_service = RecurringIdentityService(
        selection_service=_Selector(tmp_path),  # type: ignore[arg-type]
        storage_root=tmp_path / "frames",
    )

    return pipeline


def test_a_found_place_is_added_to_the_project_without_asking(tmp_path: Path) -> None:
    from src.services.recurring_identity_service import RecurringIdentityService

    job = _job()
    pipeline = _pipeline_that_adds_places(tmp_path, _ANSWER)

    pipeline.run_identity_suggestions(job)

    village = next(
        i
        for i in job.visual_continuity_bible.identities  # type: ignore[union-attr]
        if i.name == "The village"
    )
    assert village.is_manual is True
    assert village.entity_type == CanonicalEntityType.LOCATION
    assert village.canonical_description == "A hillside village of thatched huts."
    service = pipeline.recurring_identity_service
    assert isinstance(service, RecurringIdentityService)
    assert service.scenes_of(job, "The village") == [2, 4]  # marked on its scenes
    by_name = {s.name: s.status for s in job.identity_suggestions}
    assert by_name["The village"] == SuggestionStatus.ACCEPTED


def test_a_found_character_is_still_only_suggested(tmp_path: Path) -> None:
    job = _job()
    pipeline = _pipeline_that_adds_places(tmp_path, _ANSWER)

    pipeline.run_identity_suggestions(job)

    names = [
        i.name
        for i in job.visual_continuity_bible.identities  # type: ignore[union-attr]
    ]
    by_name = {s.name: s.status for s in job.identity_suggestions}
    assert "Grandmother" not in names
    assert by_name["Grandmother"] == SuggestionStatus.PENDING


def test_a_found_place_takes_its_reference_from_a_clip_that_already_exists(
    tmp_path: Path,
) -> None:
    job = _job()
    clip = tmp_path / "clip_2.mp4"
    clip.write_bytes(b"x")
    job.video_clips.append(
        VideoClip(
            scene_number=2,
            source_type=SceneSourceType.AI_GENERATE,
            duration_seconds=8,
            local_file=str(clip),
        )
    )
    pipeline = _pipeline_that_adds_places(tmp_path, _ANSWER)

    pipeline.run_identity_suggestions(job)

    village = next(
        i
        for i in job.visual_continuity_bible.identities  # type: ignore[union-attr]
        if i.name == "The village"
    )
    assert len(village.reference_asset_ids) == 1


def test_a_place_that_cannot_be_added_stays_a_pending_suggestion(
    tmp_path: Path,
) -> None:
    class _Refusing:
        def scenes_of(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return []

        def add(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise ValueError("That name is taken.")

    job = _job()
    pipeline = _pipeline(_ANSWER)
    pipeline.recurring_identity_service = _Refusing()  # type: ignore[assignment]

    pipeline.run_identity_suggestions(job)  # must not raise

    by_name = {s.name: s.status for s in job.identity_suggestions}
    assert by_name["The village"] == SuggestionStatus.PENDING


def test_a_failing_reference_pick_does_not_undo_the_added_place(tmp_path: Path) -> None:
    from src.services.recurring_identity_service import RecurringIdentityService
    from tests.test_recurring_identity_service import _Selector

    class _Service(RecurringIdentityService):
        def fill_reference(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("cannot read the clip")

    job = _job()
    pipeline = _pipeline(_ANSWER)
    pipeline.recurring_identity_service = _Service(
        selection_service=_Selector(tmp_path),  # type: ignore[arg-type]
        storage_root=tmp_path / "frames",
    )

    pipeline.run_identity_suggestions(job)

    names = [
        i.name
        for i in job.visual_continuity_bible.identities  # type: ignore[union-attr]
    ]
    assert "The village" in names


def test_the_prompt_asks_for_unnamed_settings_with_concrete_descriptions() -> None:
    job = _job()
    assert job.visual_continuity_bible is not None
    job.visual_continuity_bible.clip_entries[0].incoming_state = VisualState(
        location="A rural village near Lake Nyos"
    )
    llm = _StubLLM("NONE")
    IdentitySuggestionService(llm_service=llm).suggest(  # type: ignore[arg-type]
        scenes=job.scenes,
        visual_continuity_bible=job.visual_continuity_bible,
        topic="Lake Nyos",
        already_seen=set(),
    )

    prompt = llm.requests[0].prompt

    assert "| set in: A rural village near Lake Nyos" in prompt
    assert "UNNAMED recurring setting" in prompt
    assert "3 or 4 sentences" in prompt
    assert "never the words 'same'" in prompt


_BOLD_ANSWER = """**NAME:** The village
**KIND:** place
**DESCRIPTION:** A hillside village of thatched huts.
**SCENES:** 2, 4
"""


def test_a_reply_with_markdown_bold_labels_is_still_read() -> None:
    found = _suggest(_BOLD_ANSWER)

    assert [s.name for s in found] == ["The village"]
    assert found[0].scene_numbers == [2, 4]


def test_a_real_reply_that_gives_nothing_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        found = _suggest("I could not find any people or places that repeat.")

    assert found == []
    assert "gave no candidates" in caplog.text
    assert "could not find any people" in caplog.text


def test_none_reply_is_not_logged_as_a_problem(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        _suggest("NONE")

    assert "gave no candidates" not in caplog.text


def test_a_full_length_place_description_is_not_dropped() -> None:
    """Live 2026-10-09: the prompt asks for a 60-90 word description (~550 characters)
    but the suggestion model capped it at 400, so Claude's well-formed reply was dropped
    without a trace."""

    description = (
        "A cluster of modest rural homes with mud-brick walls and thatched or tin roofs, "
        "standing intact under open sky. Dirt paths and small garden plots run between "
        "the houses, with scattered trees and low vegetation typical of a highland "
        "African setting. The ground nearby is uneven, dotted with motionless forms. "
        "Light is flat and pale, as on an overcast early morning with a faint mist. "
        "A narrow stream of grey water crosses the foreground and the hills behind "
        "the huts are green and rounded."
    )
    assert 400 < len(description) < 1200

    found = _suggest(
        f"NAME: The Village\nKIND: place\nDESCRIPTION: {description}\nSCENES: 2, 4\n"
    )

    assert [s.name for s in found] == ["The Village"]
    assert found[0].description == description


def _reply_with_scenes(scenes: str) -> str:
    return (
        "NAME: The Village\nKIND: place\n"
        "DESCRIPTION: A hillside village of thatched huts.\n"
        f"SCENES: {scenes}\n"
    )


@pytest.mark.parametrize(
    "scenes",
    ["2, 4", "2-4", "Scenes 2-4", "scenes 2 – 4", "2—4", "2 and 4", "2; 4", "4, 2"],
)
def test_the_scenes_line_is_read_however_the_model_writes_it(scenes: str) -> None:
    found = _suggest(_reply_with_scenes(scenes))

    assert len(found) == 1
    assert len(found[0].scene_numbers) >= 2


def test_scene_numbers_the_project_does_not_have_are_dropped_not_the_candidate() -> (
    None
):
    found = _suggest(_reply_with_scenes("2, 4, 99"))

    assert [s.scene_numbers for s in found] == [[2, 4]]


def test_a_dropped_candidate_says_why(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        _suggest(_reply_with_scenes("2"))

    assert "fewer than 2 scenes" in caplog.text


# ------------------------------------------ graphics are not places; overlaps are merged


def _place_block(
    name: str, scenes: str, description: str = "A hillside village."
) -> str:
    return f"NAME: {name}\nKIND: place\nDESCRIPTION: {description}\nSCENES: {scenes}\n"


@pytest.mark.parametrize(
    ("name", "description"),
    [
        ("Regional terrain map", "A muted map of the countryside."),
        ("Cross-section diagram of the lake", "A scientific diagram of the water."),
        ("The data wall", "An animated infographic showing the rise."),
        ("Chart room", "A room with charts."),
    ],
)
def test_a_graphic_is_not_taken_for_a_place(name: str, description: str) -> None:
    assert _suggest(_place_block(name, "2, 4", description)) == []


def test_a_real_place_that_mentions_a_map_later_in_its_description_is_kept() -> None:
    found = _suggest(
        _place_block(
            "The hut", "2, 4", "A thatched hut. A faded map is pinned to the wall."
        )
    )

    assert [s.name for s in found] == ["The hut"]


def test_the_prompt_rules_out_graphics_and_views_of_a_listed_place() -> None:
    job = _job()
    llm = _StubLLM("NONE")
    IdentitySuggestionService(llm_service=llm).suggest(  # type: ignore[arg-type]
        scenes=job.scenes,
        visual_continuity_bible=job.visual_continuity_bible,  # type: ignore[arg-type]
        topic="x",
        already_seen=set(),
    )

    prompt = llm.requests[0].prompt

    assert "NOT a map, diagram, chart" in prompt
    assert "is NOT a new place" in prompt


def test_a_place_on_the_same_scenes_as_one_already_in_the_bible_is_not_added(
    tmp_path: Path,
) -> None:
    job = _job()
    bible = job.visual_continuity_bible
    assert bible is not None

    for entry in bible.clip_entries:
        if entry.scene_number in (2, 3, 4, 5):
            entry.entity_names = ["Kitchen"]
            entry.on_screen_entity_names = ["Kitchen"]

    pipeline = _pipeline_that_adds_places(
        tmp_path, _place_block("The kitchen table", "2-4")
    )

    pipeline.run_identity_suggestions(job)

    names = [i.name for i in bible.identities]
    by_name = {s.name: s.status for s in job.identity_suggestions}
    assert "The kitchen table" not in names
    assert by_name["The kitchen table"] == SuggestionStatus.DISCARDED


def test_a_place_on_other_scenes_is_still_added(tmp_path: Path) -> None:
    job = _job()
    bible = job.visual_continuity_bible
    assert bible is not None

    for entry in bible.clip_entries:
        if entry.scene_number in (2, 3):
            entry.entity_names = ["Kitchen"]
            entry.on_screen_entity_names = ["Kitchen"]

    pipeline = _pipeline_that_adds_places(
        tmp_path, _place_block("The village", "2, 4, 5, 6")
    )

    pipeline.run_identity_suggestions(job)

    assert "The village" in [i.name for i in bible.identities]
