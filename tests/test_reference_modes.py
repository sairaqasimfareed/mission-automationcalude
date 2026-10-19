"""
Reference pictures, automatic or manual (2026-10-19). Automatic is the long-standing behaviour. In manual mode the
app takes no reference frame by itself and attaches only pictures the operator supplied (uploaded for a character
or place, or chosen for one scene), to the scenes each is marked in. The References tab lists every character and
place with its scenes, its picture and an image-generator prompt written in the series style.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.asset_index import AssetIndex
from src.models.google_flow_generation import GoogleFlowGenerationState
from src.models.reference_mode import ReferenceMode
from src.models.specification_enums import AspectRatio
from src.services.asset_storage_service import AssetStorageService
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.reference_picture_service import (
    clear_picture,
    has_operator_picture,
    is_operator_picture,
    missing_pictures,
    picture_is_attachable,
    reference_image_prompt,
    scenes_of,
    set_scenes_of,
)
from tests.test_scene_video_generation_service import (
    _continuity_bible,
    _job,
    _real_video_file,
    _scene,
    _ScriptedProvider,
    _service,
    _stored_reference_asset,
)
from tests.test_suggestions import qapp as qapp  # noqa: PLC0414 - fixture


def _provider(tmp_path: Path) -> _ScriptedProvider:
    provider = _ScriptedProvider(
        observe_sequence=[
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))

    return provider


def _job_with_reference(tmp_path: Path, *, mode: ReferenceMode, operator: bool):  # type: ignore[no-untyped-def]
    scene = _scene(2)
    scene.real_narration_duration_seconds = 5.0
    job = _job(scene)
    job.reference_mode = mode
    asset_id = _stored_reference_asset(job, tmp_path)
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[asset_id], scene_numbers=[2]
    )

    if operator:
        asset = job.extracted_frame_asset_index.get(asset_id)
        assert asset is not None
        asset.metadata["uploaded_by_operator"] = True

    return job


def _generate(tmp_path: Path, job):  # type: ignore[no-untyped-def]
    provider = _provider(tmp_path)
    storage = AssetStorageService(
        storage_root=tmp_path / "storage", asset_index=AssetIndex()
    )
    _service(provider, asset_storage_service=storage).generate_one(job, 2)

    return provider.submitted_requests[0]


# ------------------------------------------------------------------ the mode and the rules


def test_a_new_project_gets_references_automatically() -> None:
    assert _job().reference_mode == ReferenceMode.AUTO


def test_the_mode_is_saved_on_the_job() -> None:
    job = _job()

    ContentIntelligencePipeline.set_reference_mode(job, ReferenceMode.MANUAL)
    assert job.reference_mode == ReferenceMode.MANUAL

    ContentIntelligencePipeline.set_reference_mode(job, ReferenceMode.AUTO)
    assert job.reference_mode == ReferenceMode.AUTO


def test_only_pictures_the_operator_supplied_count_in_manual_mode(
    tmp_path: Path,
) -> None:
    job = _job_with_reference(tmp_path, mode=ReferenceMode.AUTO, operator=False)
    identity = job.visual_continuity_bible.identities[0]  # type: ignore[union-attr]
    asset = job.extracted_frame_asset_index.get(identity.reference_asset_ids[0])
    assert asset is not None

    assert is_operator_picture(asset) is False
    assert picture_is_attachable(job, asset) is True  # automatic: any picture

    job.reference_mode = ReferenceMode.MANUAL
    assert picture_is_attachable(job, asset) is False

    asset.metadata["chosen_by_operator"] = True
    assert picture_is_attachable(job, asset) is True
    assert has_operator_picture(job, identity) is True


# ------------------------------------------------------------------ scenes and missing pictures


def test_a_characters_scenes_can_be_added_and_removed() -> None:
    job = _job(_scene(1), _scene(2), _scene(3))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1, 2, 3]
    )
    name = job.visual_continuity_bible.identities[0].name

    set_scenes_of(job, name, [1, 2])
    assert scenes_of(job, name) == [1, 2]

    set_scenes_of(job, name, [2, 3])
    assert scenes_of(job, name) == [2, 3]

    set_scenes_of(job, name, [])
    assert scenes_of(job, name) == []


def test_marking_an_unknown_scene_is_refused_with_a_clear_message() -> None:
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1]
    )
    name = job.visual_continuity_bible.identities[0].name

    with pytest.raises(ValueError, match="Scene 9"):
        set_scenes_of(job, name, [9])


def test_missing_pictures_lists_who_is_marked_in_a_scene_but_has_no_operator_picture(
    tmp_path: Path,
) -> None:
    job = _job_with_reference(tmp_path, mode=ReferenceMode.MANUAL, operator=False)

    missing = missing_pictures(job)
    assert [m.scenes for m in missing] == [[2]]

    identity = job.visual_continuity_bible.identities[0]  # type: ignore[union-attr]
    asset = job.extracted_frame_asset_index.get(identity.reference_asset_ids[0])
    assert asset is not None
    asset.metadata["uploaded_by_operator"] = True

    assert missing_pictures(job) == []


def test_removing_a_picture_clears_it_from_the_character(tmp_path: Path) -> None:
    job = _job_with_reference(tmp_path, mode=ReferenceMode.MANUAL, operator=True)
    identity = job.visual_continuity_bible.identities[0]  # type: ignore[union-attr]

    clear_picture(job, identity.name)

    assert identity.reference_asset_ids == []


# ------------------------------------------------------------------ the image prompt carries the style


def test_the_image_prompt_carries_the_series_style_and_the_description() -> None:
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1]
    )
    job.style_brief = (
        "Anime courtroom, stark noir. Ink-heavy linework. Deep teal for defense."
    )
    identity = job.visual_continuity_bible.identities[0]

    text = reference_image_prompt(job, identity)

    assert identity.name in text
    assert identity.canonical_description.rstrip(".") in text
    assert "Anime courtroom, stark noir" in text
    assert "exactly the style of the series" in text
    assert "no text" in text


def test_the_image_prompt_follows_the_project_look_and_the_frame_shape() -> None:
    from src.models.project_look import ProjectLook

    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1]
    )
    job.project_look = ProjectLook(color_palette="cold slate and ink")
    identity = job.visual_continuity_bible.identities[0]

    job.aspect_ratio = AspectRatio.PORTRAIT
    assert "vertical portrait (9:16)" in reference_image_prompt(job, identity)
    assert "cold slate and ink" in reference_image_prompt(job, identity)

    job.aspect_ratio = AspectRatio.LANDSCAPE
    assert "horizontal landscape (16:9)" in reference_image_prompt(job, identity)


def test_a_very_long_brief_is_cut_in_the_image_prompt() -> None:
    job = _job(_scene(1))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1]
    )
    job.style_brief = "x " * 4000
    identity = job.visual_continuity_bible.identities[0]

    assert len(reference_image_prompt(job, identity)) < 2600


# ------------------------------------------------------------------ what a submission attaches


def test_automatic_mode_still_attaches_the_apps_own_picture(tmp_path: Path) -> None:
    job = _job_with_reference(tmp_path, mode=ReferenceMode.AUTO, operator=False)

    request = _generate(tmp_path, job)

    assert len(request.reference_assets) == 1


def test_manual_mode_does_not_attach_a_picture_the_app_picked(tmp_path: Path) -> None:
    job = _job_with_reference(tmp_path, mode=ReferenceMode.MANUAL, operator=False)

    request = _generate(tmp_path, job)

    assert request.reference_assets == []


def test_manual_mode_attaches_the_picture_the_operator_uploaded(tmp_path: Path) -> None:
    job = _job_with_reference(tmp_path, mode=ReferenceMode.MANUAL, operator=True)

    request = _generate(tmp_path, job)

    assert len(request.reference_assets) == 1


def test_manual_mode_takes_no_reference_frame_from_a_finished_clip(
    tmp_path: Path,
) -> None:
    job = _job_with_reference(tmp_path, mode=ReferenceMode.MANUAL, operator=False)
    before = len(job.extracted_frame_asset_index.assets)

    _generate(tmp_path, job)

    assert len(job.extracted_frame_asset_index.assets) == before


# ------------------------------------------------------------------ the screen


def test_the_references_tab_sits_after_scene_visuals_and_has_no_run_button() -> None:
    from src.desktop.views.content_studio_view import _CI_STAGES, _PANEL_ONLY_STAGES

    keys = [key for key, _label in _CI_STAGES]

    assert keys.index("references") == keys.index("scene_visuals") + 1
    assert "references" in _PANEL_ONLY_STAGES


def test_manual_mode_shows_a_row_prompt_and_upload_for_every_character(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton, QTextEdit, QVBoxLayout, QWidget

    from tests.test_scene_detail import _job as scene_job
    from tests.test_suggestions import _studio, _texts

    view, job, _errors = _studio(scene_job(3))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1]
    )
    job.reference_mode = ReferenceMode.MANUAL
    job.style_brief = "Anime courtroom, stark noir."
    holder = QWidget()
    view._render_references_panel(QVBoxLayout(holder), job)  # noqa: SLF001
    buttons = [b.text() for b in holder.findChildren(QPushButton)]
    prompts = [e.toPlainText() for e in holder.findChildren(QTextEdit)]
    texts = _texts(holder)

    assert "Upload picture" in buttons
    assert "Copy prompt" in buttons
    assert "Apply scenes" in buttons
    assert prompts and all("Anime courtroom, stark noir." in p for p in prompts)
    assert any("No picture yet for" in t for t in texts)


def test_automatic_mode_lists_the_status_without_manual_controls(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    from tests.test_scene_detail import _job as scene_job
    from tests.test_suggestions import _studio, _texts

    view, job, _errors = _studio(scene_job(3))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1]
    )
    holder = QWidget()
    view._render_references_panel(QVBoxLayout(holder), job)  # noqa: SLF001
    buttons = [b.text() for b in holder.findChildren(QPushButton)]

    assert "Upload picture" not in buttons
    assert any("Automatic:" in t for t in _texts(holder))


def test_switching_the_mode_is_saved_and_changing_scenes_applies(qapp) -> None:  # type: ignore[no-untyped-def]
    from tests.test_scene_detail import _job as scene_job
    from tests.test_suggestions import _studio

    view, job, _errors = _studio(scene_job(3))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1]
    )
    view._handle_reference_mode_changed(ReferenceMode.MANUAL)  # noqa: SLF001
    saved = view._current_job()  # noqa: SLF001
    assert saved is not None and saved.reference_mode == ReferenceMode.MANUAL


# ------------------------------------------------------------------ one place for characters and places


def _bible_job():  # type: ignore[no-untyped-def]
    from tests.test_scene_detail import _job as scene_job

    job = scene_job(3)
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1, 2]
    )

    return job


def test_the_tab_is_called_characters_and_places() -> None:
    from src.desktop.views.content_studio_view import _CI_STAGES

    assert dict(_CI_STAGES)["references"] == "Characters and places"


def test_the_continuity_bible_tab_only_summarises_them_and_points_to_the_new_tab(
    qapp,
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    from tests.test_suggestions import _studio, _texts

    view, job, _errors = _studio(_bible_job())
    holder = QWidget()
    view._render_visual_continuity_section(QVBoxLayout(holder), job)  # noqa: SLF001
    texts = _texts(holder)
    buttons = [b.text() for b in holder.findChildren(QPushButton)]

    assert any(
        "characters and places" in t and "with a reference picture" in t for t in texts
    )
    assert "Open Characters and places" in buttons
    # none of the management moved to the new tab is repeated here
    assert not any(t.startswith("Your characters and places") for t in texts)
    for gone in (
        "Upload a picture",
        "Choose a reference frame",
        "Suggest characters and places",
    ):
        assert gone not in buttons


def test_the_open_button_goes_to_the_new_tab(qapp) -> None:  # type: ignore[no-untyped-def]
    from src.desktop.views.content_studio_view import _CI_STAGES
    from tests.test_suggestions import _studio

    view, _job, _errors = _studio(_bible_job())

    view._handle_open_characters_and_places()  # noqa: SLF001

    assert _CI_STAGES[view._selected_ci_stage_index][0] == "references"  # noqa: SLF001


def test_automatic_mode_shows_the_list_suggestions_and_the_add_form_in_the_new_tab(
    qapp,
) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from tests.test_suggestions import _studio, _texts

    view, job, _errors = _studio(_bible_job())
    holder = QWidget()
    view._render_references_panel(QVBoxLayout(holder), job)  # noqa: SLF001
    texts = _texts(holder)

    assert any(t.startswith("Automatic:") for t in texts)
    assert "Your characters and places" in texts
    assert "Or add one yourself:" in texts


def test_manual_mode_shows_each_character_once_plus_the_add_form(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from tests.test_suggestions import _studio, _texts

    view, job, _errors = _studio(_bible_job())
    job.reference_mode = ReferenceMode.MANUAL
    name = job.visual_continuity_bible.identities[0].name  # type: ignore[union-attr]
    holder = QWidget()
    view._render_references_panel(QVBoxLayout(holder), job)  # noqa: SLF001
    texts = _texts(holder)

    assert (
        sum(1 for t in texts if t.endswith(f": {name}")) == 1
    )  # one card, not two lists
    assert "Or add one yourself:" in texts


# ------------------------------------------------------------------ found live: Joan arc (2026-10-19)


def _picture(tmp_path: Path, name: str, red: int = 200) -> Path:
    from PIL import Image

    path = tmp_path / name
    Image.new("RGB", (64, 64), (red, 30, 30)).save(path)

    return path


def _service_for(tmp_path: Path):  # type: ignore[no-untyped-def]
    from src.services.recurring_identity_service import RecurringIdentityService

    return RecurringIdentityService(storage_root=tmp_path / "store")


def test_a_picture_uploaded_before_any_scene_is_attached_once_scenes_are_given(
    tmp_path: Path,
) -> None:
    """Upload first, then type the scenes: the picture must go to those scenes."""

    job = _job(_scene(1), _scene(2), _scene(3))
    job.reference_mode = ReferenceMode.MANUAL
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1, 2, 3]
    )
    name = job.visual_continuity_bible.identities[0].name
    set_scenes_of(job, name, [])
    assert scenes_of(job, name) == []

    _service_for(tmp_path).set_reference_from_file(
        job, name, str(_picture(tmp_path, "a.png"))
    )
    set_scenes_of(job, name, [2])

    identity = job.visual_continuity_bible.identities[0]
    asset = job.extracted_frame_asset_index.get(identity.reference_asset_ids[0])
    assert asset is not None and picture_is_attachable(job, asset)
    assert scenes_of(job, name) == [2]


def test_leaving_the_scenes_field_applies_it_without_pressing_the_button(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

    from tests.test_scene_detail import _job as scene_job
    from tests.test_suggestions import _studio

    view, job, _errors = _studio(scene_job(3))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1, 2, 3]
    )
    name = job.visual_continuity_bible.identities[0].name
    set_scenes_of(job, name, [])
    job.reference_mode = ReferenceMode.MANUAL
    holder2 = QWidget()
    view._render_references_panel(QVBoxLayout(holder2), job)  # noqa: SLF001
    field = next(
        f
        for f in holder2.findChildren(QLineEdit)
        if f.placeholderText() == "e.g. 1-3, 7"
    )

    field.setText("2")
    field.editingFinished.emit()

    saved = view._current_job()  # noqa: SLF001
    assert saved is not None
    assert scenes_of(saved, name) == [2]


def test_the_clips_tab_shows_every_picture_of_a_scene_not_only_the_first(
    tmp_path: Path,
) -> None:
    from src.services.scene_reference_service import SceneReferenceService

    job = _job(_scene(1), _scene(2))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1, 2]
    )
    service = _service_for(tmp_path)
    identity = job.visual_continuity_bible.identities[0]
    service.set_reference_from_file(
        job, identity.name, str(_picture(tmp_path, "one.png"))
    )

    from src.models.visual_continuity import (
        CanonicalEntityIdentity,
        CanonicalEntityType,
    )

    second = CanonicalEntityIdentity(
        entity_type=CanonicalEntityType.LOCATION,
        name="The courtroom",
        canonical_description="A dark-wood courtroom.",
    )
    job.visual_continuity_bible.identities.append(second)
    for entry in job.visual_continuity_bible.clip_entries:
        entry.entity_names.append(second.name)
        entry.on_screen_entity_names.append(second.name)
    service.set_reference_from_file(
        job, second.name, str(_picture(tmp_path, "two.png", red=20))
    )

    status = SceneReferenceService(
        selection_service=object(),  # type: ignore[arg-type]
        storage_root=tmp_path / "scene_store",
    ).status(job, job.scenes[0])

    assert len(status.image_paths) == 2
    assert status.image_path == status.image_paths[0]
    assert "Marked here:" in status.text and status.text.count("(reference") == 2


def test_removing_one_picture_from_a_scene_keeps_the_other_and_other_scenes() -> None:
    from src.services.reference_picture_service import remove_from_scene

    job = _job(_scene(1), _scene(2))
    job.visual_continuity_bible = _continuity_bible(
        reference_asset_ids=[], scene_numbers=[1, 2]
    )
    name = job.visual_continuity_bible.identities[0].name

    remove_from_scene(job, name, 1)

    entries = {e.scene_number: e for e in job.visual_continuity_bible.clip_entries}
    assert name not in entries[1].entity_names
    assert name not in entries[1].on_screen_entity_names
    assert name in entries[2].on_screen_entity_names
