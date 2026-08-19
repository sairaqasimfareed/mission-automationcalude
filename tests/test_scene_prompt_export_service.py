from __future__ import annotations

from pathlib import Path

from src.models.scene import Scene, SceneStatus
from src.services.scene_prompt_export_service import ScenePromptExportService


def _scene(**overrides: object) -> Scene:
    base: dict[str, object] = dict(
        scene_number=1,
        title="Captain Briggs' Final Log",
        narration="The crew vanished without a trace.",
        visual_prompt="A striking, attention-grabbing opening image for: ...",
        estimated_duration_seconds=8,
        camera_direction="Quick push-in, urgent handheld energy",
        status=SceneStatus.READY,
    )
    base.update(overrides)
    return Scene(**base)


def test_build_entries_orders_by_scene_number() -> None:
    service = ScenePromptExportService()

    entries = service.build_entries([_scene(scene_number=2), _scene(scene_number=1)])

    assert [entry.scene_number for entry in entries] == [1, 2]


def test_suggested_filename_is_zero_padded_and_slugified() -> None:
    service = ScenePromptExportService()

    entries = service.build_entries([_scene(scene_number=3, title="The Mary Celeste!")])

    assert entries[0].suggested_filename == "003_the-mary-celeste.mp4"


def test_suggested_filename_falls_back_when_title_has_no_alphanumerics() -> None:
    service = ScenePromptExportService()

    entries = service.build_entries([_scene(scene_number=1, title="---")])

    assert entries[0].suggested_filename == "001_scene.mp4"


def test_to_text_includes_prompt_and_suggested_filename() -> None:
    service = ScenePromptExportService()

    text = service.to_text([_scene()])

    assert "001_captain-briggs-final-log.mp4" in text
    assert "A striking, attention-grabbing opening image" in text
    assert "Target duration: 8s" in text


def test_to_text_with_no_scenes_says_so() -> None:
    service = ScenePromptExportService()

    assert service.to_text([]) == "No scenes to export."


def test_write_file_writes_the_same_text(tmp_path: Path) -> None:
    service = ScenePromptExportService()
    destination = tmp_path / "prompts.txt"

    service.write_file([_scene()], destination)

    assert destination.read_text(encoding="utf-8") == service.to_text([_scene()])
