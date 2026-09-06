from __future__ import annotations

from pathlib import Path

from src.models.cinematic_prompt import CinematicPromptPackage, ResolvedCinematicPrompt
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


# --- Post-Script-Approval Production Plan, Phase 4/5: resolved-prompt preference ---


def test_build_entries_prefers_the_resolved_cinematic_prompt() -> None:
    service = ScenePromptExportService()
    package = CinematicPromptPackage(
        script_lock_hash="hash123",
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash="hash123",
                prompt_text="Identity: Captain Briggs. Environment: the deck.",
            )
        ],
    )

    entries = service.build_entries(
        [_scene(scene_number=1)], cinematic_prompt_package=package
    )

    assert entries[0].prompt == "Identity: Captain Briggs. Environment: the deck."


def test_build_entries_falls_back_to_visual_prompt_when_scene_not_in_package() -> None:
    service = ScenePromptExportService()
    package = CinematicPromptPackage(script_lock_hash="hash123")  # no entries

    entries = service.build_entries(
        [_scene(scene_number=1)], cinematic_prompt_package=package
    )

    assert entries[0].prompt == _scene(scene_number=1).visual_prompt


def test_build_entries_falls_back_to_visual_prompt_without_a_package() -> None:
    service = ScenePromptExportService()

    entries = service.build_entries([_scene(scene_number=1)])

    assert entries[0].prompt == _scene(scene_number=1).visual_prompt
