"""
Project-level video provider, 2026-10-03: the Project settings selector, and
the Content tab's prompt section showing scenes as they would actually be
generated (split into clips, sized and worded for the chosen provider).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.content_studio_view import ContentStudioView  # noqa: E402
from src.models.cinematic_prompt import (  # noqa: E402
    CinematicPromptPackage,
    ResolvedCinematicPrompt,
)
from src.models.scene import Scene  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.models.video_provider import VideoProvider  # noqa: E402
from src.services.content_intelligence_pipeline import (  # noqa: E402
    ContentIntelligencePipeline,
)
from src.services.content_pipeline import ContentPipeline  # noqa: E402
from src.services.enriched_scene_prompt_service import (  # noqa: E402
    EnrichedScenePromptService,
)
from src.services.fact_check_service import FactCheckService  # noqa: E402
from src.services.reviewer_service import ReviewerService  # noqa: E402
from src.services.topic_candidate_generation_service import (  # noqa: E402
    TopicCandidateGenerationService,
)
from tests.test_content_studio_content_intelligence_gui import (  # noqa: E402
    _EchoStubLLMService,
)
from tests.test_enriched_scene_prompt_service import (  # noqa: E402
    _SCRIPT_LOCK_HASH,
    _FakeSceneVideoGenerationService,
    _split_bible,
    _split_script_lock,
    _split_shot_plan,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _view(
    store: InMemoryJobStore,
    *,
    enriched: EnrichedScenePromptService | None = None,
) -> ContentStudioView:
    stub = _EchoStubLLMService()

    return ContentStudioView(
        job_store=store,
        content_pipeline=ContentPipeline(llm_service=stub),  # type: ignore[arg-type]
        content_intelligence_pipeline=ContentIntelligencePipeline(
            llm_service=stub  # type: ignore[arg-type]
        ),
        reviewer_service=ReviewerService(llm_service=stub),  # type: ignore[arg-type]
        topic_candidate_generation_service=TopicCandidateGenerationService(
            llm_service=stub  # type: ignore[arg-type]
        ),
        fact_check_service=FactCheckService(llm_service=stub),  # type: ignore[arg-type]
        on_change=lambda: None,
        enriched_scene_prompt_service=enriched,
    )


def _job(provider: VideoProvider = VideoProvider.GOOGLE_FLOW) -> VideoJob:
    job = VideoJob(
        project_name="Remedy video",
        channel_name="Health Channel",
        niche="health",
        topic="Does honey stop a cough?",
        genre_id="genre.mystery",
    )
    job.video_provider = provider

    return job


def _provider_combo(view: ContentStudioView) -> QComboBox:
    return next(
        combo
        for combo in view.findChildren(QComboBox)
        if any(
            combo.itemData(index) in list(VideoProvider)
            for index in range(combo.count())
        )
    )


def _button(view: ContentStudioView, text: str) -> QPushButton:
    return next(b for b in view.findChildren(QPushButton) if b.text() == text)


def test_the_provider_selector_defaults_to_google_flow(qapp: QApplication) -> None:
    store = InMemoryJobStore()
    job = _job()
    store.add(job)
    view = _view(store)
    view.set_job(job.id)
    view.refresh(job)

    combo = _provider_combo(view)

    assert combo.currentData() == VideoProvider.GOOGLE_FLOW
    assert "Google Flow" in combo.currentText()


def test_the_selector_lists_both_providers_with_their_clip_rules(
    qapp: QApplication,
) -> None:
    store = InMemoryJobStore()
    job = _job()
    store.add(job)
    view = _view(store)
    view.set_job(job.id)
    view.refresh(job)

    texts = [
        _provider_combo(view).itemText(i) for i in range(_provider_combo(view).count())
    ]

    assert any("Muse" in text and "10s" in text for text in texts)
    assert any("Google Flow" in text and "4/6/8s" in text for text in texts)


def test_the_selector_shows_a_projects_saved_provider(qapp: QApplication) -> None:
    store = InMemoryJobStore()
    job = _job(VideoProvider.MUSE)
    store.add(job)
    view = _view(store)
    view.set_job(job.id)
    view.refresh(job)

    assert _provider_combo(view).currentData() == VideoProvider.MUSE


def test_choosing_muse_and_saving_persists_it_on_the_job(qapp: QApplication) -> None:
    store = InMemoryJobStore()
    job = _job()
    store.add(job)
    view = _view(store)
    view.set_job(job.id)
    view.refresh(job)

    combo = _provider_combo(view)
    combo.setCurrentIndex(combo.findData(VideoProvider.MUSE))

    # Not saved until the button is pressed - same as every other setting.
    assert job.video_provider == VideoProvider.GOOGLE_FLOW

    _button(view, "Save settings").click()

    assert job.video_provider == VideoProvider.MUSE
    # Qt hands back a plain str for a str-enum; the job must hold the enum
    # (a bare 'muse' triggered a Pydantic serializer warning on save).
    assert isinstance(job.video_provider, VideoProvider)


def test_switching_back_to_flow_and_saving_persists_too(qapp: QApplication) -> None:
    store = InMemoryJobStore()
    job = _job(VideoProvider.MUSE)
    store.add(job)
    view = _view(store)
    view.set_job(job.id)
    view.refresh(job)

    combo = _provider_combo(view)
    combo.setCurrentIndex(combo.findData(VideoProvider.GOOGLE_FLOW))
    _button(view, "Save settings").click()

    assert job.video_provider == VideoProvider.GOOGLE_FLOW


# --------------------- Content tab prompt section ---------------------


def _job_with_prompts(provider: VideoProvider, narration_seconds: float) -> VideoJob:
    job = _job(provider)
    scene = Scene(
        scene_number=1,
        title="Scene 1",
        narration="Honey may soothe a cough.",
        visual_prompt="Honey in a kitchen.",
        estimated_duration_seconds=8,
    )
    scene.real_narration_duration_seconds = narration_seconds
    job.scenes = [scene]
    job.cinematic_shot_plan = _split_shot_plan()
    job.visual_continuity_bible = _split_bible()
    job.script_lock = _split_script_lock()
    job.cinematic_prompt_package = CinematicPromptPackage(
        script_lock_hash=_SCRIPT_LOCK_HASH,
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash=_SCRIPT_LOCK_HASH,
                prompt_text="Honey in a kitchen. Duration: 8 seconds.",
                negative_constraints=["no on-screen text"],
            )
        ],
    )

    return job


def _section_text(view: ContentStudioView, job: VideoJob) -> str:
    host = QWidget()
    layout = QVBoxLayout(host)

    view._render_cinematic_prompt_section(layout, job)

    return "\n".join(label.text() for label in host.findChildren(QLabel))


def _enriched() -> EnrichedScenePromptService:
    return EnrichedScenePromptService(
        scene_video_generation_service=_FakeSceneVideoGenerationService(),  # type: ignore[arg-type]
    )


def test_the_content_tab_shows_a_nine_second_scene_as_two_clips_on_flow(
    qapp: QApplication,
) -> None:
    job = _job_with_prompts(VideoProvider.GOOGLE_FLOW, 9.0)
    view = _view(InMemoryJobStore(), enriched=_enriched())

    text = _section_text(view, job)

    assert "part 1 of 2" in text
    assert "part 2 of 2" in text
    assert "trim the generated" not in text


def test_the_content_tab_shows_the_same_scene_as_one_trimmed_clip_on_muse(
    qapp: QApplication,
) -> None:
    job = _job_with_prompts(VideoProvider.MUSE, 9.0)
    view = _view(InMemoryJobStore(), enriched=_enriched())

    text = _section_text(view, job)

    assert "part 1 of" not in text
    assert "9s" in text
    assert "Duration: 9 seconds." in text
    assert "trim the generated" not in text


def test_the_content_tab_duration_line_matches_the_chosen_provider(
    qapp: QApplication,
) -> None:
    """The raw package says "Duration: 8 seconds." (compiled before the
    voice existed); the tab now shows the real, provider-specific one."""

    flow = _section_text(
        _view(InMemoryJobStore(), enriched=_enriched()),
        _job_with_prompts(VideoProvider.GOOGLE_FLOW, 5.0),
    )
    muse = _section_text(
        _view(InMemoryJobStore(), enriched=_enriched()),
        _job_with_prompts(VideoProvider.MUSE, 5.0),
    )

    assert "Duration: 6 seconds." in flow  # Flow rounds up to its 4/6/8 grid
    assert "Duration: 5 seconds." in muse  # Muse trims to the exact length


def test_the_content_tab_falls_back_to_the_raw_package_without_the_service(
    qapp: QApplication,
) -> None:
    job = _job_with_prompts(VideoProvider.MUSE, 9.0)
    view = _view(InMemoryJobStore(), enriched=None)

    text = _section_text(view, job)

    assert "Honey in a kitchen. Duration: 8 seconds." in text
    assert "part 1 of" not in text


def test_the_content_tab_still_lists_negatives_and_the_action_buttons(
    qapp: QApplication,
) -> None:
    job = _job_with_prompts(VideoProvider.GOOGLE_FLOW, 5.0)
    view = _view(InMemoryJobStore(), enriched=_enriched())
    host = QWidget()
    layout = QVBoxLayout(host)

    view._render_cinematic_prompt_section(layout, job)

    texts = [label.text() for label in host.findChildren(QLabel)]
    button_texts = [b.text() for b in host.findChildren(QPushButton)]

    assert any("no on-screen text" in text for text in texts)
    assert "Recompile prompts" in button_texts
    assert "Score prompt quality" in button_texts


def test_saving_settings_stores_real_enums_not_plain_strings(
    qapp: QApplication,
) -> None:
    from src.models.enums import ScriptOrigin

    store = InMemoryJobStore()
    job = _job()
    store.add(job)
    view = _view(store)
    view.set_job(job.id)
    view.refresh(job)

    combo = _provider_combo(view)
    combo.setCurrentIndex(combo.findData(VideoProvider.MUSE))
    content_mode = next(
        c
        for c in view.findChildren(QComboBox)
        if any(c.itemData(i) in list(ScriptOrigin) for i in range(c.count()))
    )
    content_mode.setCurrentIndex(content_mode.findData(ScriptOrigin.EXTERNAL))
    _button(view, "Save settings").click()

    assert isinstance(job.video_provider, VideoProvider)
    assert isinstance(job.script_origin, ScriptOrigin)
    # And it serializes without Pydantic's "unexpected value" warning.
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        job.model_dump_json()
