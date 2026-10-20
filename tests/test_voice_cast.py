"""
Voice cast (2026-10-18): a script whose lines are read by different voices (the narrator, a judge, Joan).
One line per beat; `JUDGE: ...` / `VOICE (Joan of Arc): ...` name a reader, everything else is the narrator's,
`[VISUAL 4s] ...` is a shot with no voice. Each scene is still ONE voice track (its lines are read with their own
voices and joined), so the clip sizing, voice positions and render timing are unchanged.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.agents.scene_planner.agent import MergeSettings, ScenePlannerAgent
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_generation import (
    VoiceGenerationFailure,
    VoiceGenerationFailureReason,
    VoiceGenerationResult,
    VoiceGenerationStatus,
)
from src.services.audio_join_service import (
    LINE_GAP_SECONDS,
    build_join_command,
    join_audio_files,
)
from src.services.cast_script_parser import (
    CastLine,
    canonical_speaker,
    parse_cast_line,
    parse_cast_script,
    speakers_of_cast,
)
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.multi_voice_generation_service import MultiVoiceGenerationService
from src.services.script_intake_service import ScriptIntakeService
from src.services.visual_scene_marker import VisualMarker
from src.services.voice_cast_service import (
    cast_speakers,
    speaker_profile_id,
    unassigned_speakers,
)
from src.services.voice_generation_service import VoiceGenerationService
from tests.test_scene_detail import _job
from tests.test_scene_planner_generated_script import _editorial_profile
from tests.test_suggestions import qapp as qapp  # noqa: PLC0414 - fixture

_JOAN_SCRIPT = """\
JUDGE: The court will hear the evidence.
Charge: heresy. May 24th, 1431: life in prison. Six days later: death.
JUDGE: Exhibit A. The articles of accusation.
The charges: men's dress, refusing the Church, certainty of heaven.
[VISUAL 4s] The screen darkens; a candle flame shivers.
Of the abjuration, she said:
VOICE (Joan of Arc): All I said and revoked, I said for fear of the fire.
Why she wore them again is disputed.
JUDGE: The court asks: was justice done?
"""


def _intake(text: str):  # type: ignore[no-untyped-def]
    return ScriptIntakeService.__new__(ScriptIntakeService).normalize_text_to_script(
        raw_text=text,
        topic="Joan of Arc",
        genre_id="genre.mystery",
        target_duration_seconds=80,
        voice_cast=True,
    )


# ------------------------------------------------------------------ reading the script


def test_the_users_own_script_is_read_beat_by_beat_with_its_speakers() -> None:
    script = _intake(_JOAN_SCRIPT)
    speakers = [[line.speaker for line in s.voice_lines] for s in script.segments]

    assert len(script.segments) == 9
    assert speakers == [
        ["Judge"],
        [],
        ["Judge"],
        [],
        [],
        [],
        ["Joan of Arc"],
        [],
        ["Judge"],
    ]
    assert script.segments[4].silent_seconds == 4.0


def test_a_narration_line_with_a_colon_is_not_mistaken_for_a_speaker() -> None:
    for line in (
        "Charge: heresy. May 24th, 1431: life in prison.",
        "The charges: men's dress, refusing the Church.",
        "Of the abjuration, she said:",
    ):
        item = parse_cast_line(line)

        assert isinstance(item, CastLine) and item.speaker is None
        assert item.text == line


def test_the_speaker_forms_are_all_read() -> None:
    assert parse_cast_line("JUDGE: Do you swear?") == CastLine("Judge", "Do you swear?")
    assert parse_cast_line("JOAN OF ARC: I was sent.") == CastLine(
        "Joan Of Arc", "I was sent."
    )
    assert parse_cast_line("voice (Joan of Arc): I was sent.") == CastLine(
        "Joan of Arc", "I was sent."
    )
    assert parse_cast_line('JUDGE: "Do you swear?"') == CastLine(
        "Judge", "Do you swear?"
    )
    assert parse_cast_line("NARRATOR: And so it ended.") == CastLine(
        None, "And so it ended."
    )
    assert canonical_speaker("JUDGE") == "Judge"


def test_a_visual_line_and_blank_lines_are_handled() -> None:
    items = parse_cast_script("A line.\n\n\n[VISUAL 5s] A door.\n   \nJUDGE: Order.")

    assert isinstance(items[1], VisualMarker) and items[1].seconds == 5.0
    assert [type(i).__name__ for i in items] == ["CastLine", "VisualMarker", "CastLine"]
    assert speakers_of_cast(items) == ["Judge"]


def test_an_empty_script_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_cast_script("  \n\n ")


def test_without_the_cast_switch_the_old_paragraph_reading_is_unchanged() -> None:
    script = ScriptIntakeService.__new__(ScriptIntakeService).normalize_text_to_script(
        raw_text=_JOAN_SCRIPT,
        topic="t",
        genre_id="genre.mystery",
        target_duration_seconds=80,
    )

    assert len(script.segments) == 1
    assert all(not s.voice_lines for s in script.segments)


# ------------------------------------------------------------------ planning


def _scenes(text: str = _JOAN_SCRIPT, **kwargs):  # type: ignore[no-untyped-def]
    return ScenePlannerAgent().plan_from_generated_script(
        _intake(text), _editorial_profile(), **kwargs
    )


def test_a_line_read_by_a_named_voice_is_one_whole_scene_carrying_its_speaker() -> None:
    scenes = _scenes()
    judge = [s for s in scenes if s.voice_lines and s.voice_lines[0].speaker == "Judge"]

    assert len(judge) == 3
    assert judge[0].narration == "The court will hear the evidence."
    assert [(line.speaker, line.text) for line in judge[0].voice_lines] == [
        ("Judge", "The court will hear the evidence.")
    ]
    assert not any(s.silent and s.voice_lines for s in scenes)


def test_narrator_scenes_carry_no_voice_lines_and_text_is_unchanged() -> None:
    scenes = _scenes()

    assert [s.narration for s in scenes if not s.voice_lines and not s.silent][
        0
    ].startswith("Charge: heresy.")
    assert all(not s.dialogue for s in scenes)  # never character-mode dialogue


def test_merging_keeps_each_line_with_its_reader() -> None:
    scenes = _scenes(merge=MergeSettings(target_seconds=9.0, keep_beats=False))
    mixed = [s for s in scenes if s.voice_lines and len(s.voice_lines) > 1]

    assert mixed, "a judge line and its narrator neighbour should have joined"

    for scene in mixed:
        assert " ".join(line.text for line in scene.voice_lines) == scene.narration
        assert {line.speaker for line in scene.voice_lines} <= {
            "Judge",
            "Joan of Arc",
            "Narrator",
        }
    assert all(not (s.silent and s.voice_lines) for s in scenes)


# ------------------------------------------------------------------ the cast


def test_the_cast_lists_speakers_and_what_is_unassigned() -> None:
    job = _job(2)
    job.scenes = _scenes()

    assert cast_speakers(job) == ["Judge", "Joan of Arc"]
    assert unassigned_speakers(job) == ["Judge", "Joan of Arc"]

    ContentIntelligencePipeline.set_voice_cast(
        job, enabled=True, cast={"judge": "voice.tense_suspense"}
    )

    assert speaker_profile_id(job, "Judge") == "voice.tense_suspense"
    assert speaker_profile_id(job, "JUDGE") == "voice.tense_suspense"
    assert speaker_profile_id(job, "Narrator") is None
    assert unassigned_speakers(job) == ["Joan of Arc"]


def test_clearing_a_speakers_voice_returns_it_to_the_narrator() -> None:
    job = _job(2)
    ContentIntelligencePipeline.set_voice_cast(
        job, enabled=True, cast={"judge": "voice.tense_suspense"}
    )
    ContentIntelligencePipeline.set_voice_cast(job, enabled=True, cast={"judge": ""})

    assert job.voice_cast == {}


# ------------------------------------------------------------------ joining audio

_needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="Needs ffmpeg and ffprobe.",
)


def test_the_join_command_pads_every_line_but_the_last() -> None:
    command = build_join_command(["a.mp3", "b.mp3", "c.mp3"], "out.mp3")
    graph = command[command.index("-filter_complex") + 1]

    assert graph.count("apad") == 2
    assert "concat=n=3:v=0:a=1" in graph
    assert command[-1] == "out.mp3"
    with pytest.raises(ValueError):
        build_join_command(["only.mp3"], "out.mp3")


def _tone(path: Path, seconds: float, frequency: int = 440) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:duration={seconds}",
            "-ar",
            "44100",
            str(path),
        ],
        check=True,
    )


def _duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    return float(out.strip())


@_needs_ffmpeg
def test_joining_lines_makes_one_file_as_long_as_the_lines_plus_the_pauses(
    tmp_path: Path,
) -> None:
    first, second, third = (tmp_path / f"{n}.wav" for n in "abc")
    _tone(first, 1.0, 300)
    _tone(second, 2.0, 500)
    _tone(third, 1.5, 700)
    joined = tmp_path / "scene.wav"

    join_audio_files([str(first), str(second), str(third)], str(joined))

    assert _duration(joined) == pytest.approx(
        1.0 + 2.0 + 1.5 + 2 * LINE_GAP_SECONDS, abs=0.15
    )


# ------------------------------------------------------------------ generating a cast scene


def _blueprint(
    scene_number: int, text: str, speaker: str | None
) -> ResolvedVoiceBlueprint:
    blueprint = ResolvedVoiceBlueprint(
        scene_number=scene_number,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.test",
            resolved_profile_id="voice.test",
            display_name="Test Voice",
            found_exact_match=True,
            used_fallback=False,
        ),
        narration_text=text,
        estimated_speech_duration_seconds=2.0,
    )

    if speaker:
        blueprint.metadata["speaker"] = speaker

    return blueprint


class _RecordingGenerator(MultiVoiceGenerationService):
    """The parent's single-voice generation replaced by real tone files, recording who was read."""

    def __init__(self, folder: Path) -> None:
        super().__init__(providers=[])
        self.folder = folder
        self.read: list[tuple[str, float]] = []


@_needs_ffmpeg
def test_a_cast_scene_comes_out_as_one_track_with_every_line_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _RecordingGenerator(tmp_path)
    lengths = {"The court will hear.": 1.0, "Order in court.": 1.5}

    def fake_generate(  # type: ignore[no-untyped-def]
        self, blueprint, *, start_time_seconds=0.0, provider_name=None
    ):
        seconds = lengths[blueprint.narration_text]
        file = tmp_path / f"line_{len(service.read)}.wav"
        _tone(file, seconds)
        service.read.append((blueprint.metadata.get("speaker", "?"), seconds))

        return VoiceGenerationResult(
            success=True,
            scene_number=blueprint.scene_number,
            status=VoiceGenerationStatus.COMPLETED,
            provider="test",
            output_file=str(file),
            audio_track=AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file=str(file),
                start_time_seconds=start_time_seconds,
                duration_seconds=seconds,
                status=AudioTrackStatus.READY,
                metadata={"scene_number": blueprint.scene_number},
            ),
            attempts=1,
        )

    monkeypatch.setattr(VoiceGenerationService, "generate", fake_generate)
    scene_blueprint = _blueprint(3, "The court will hear. Order in court.", None)
    scene_blueprint.line_blueprints = [
        _blueprint(3, "The court will hear.", "Judge"),
        _blueprint(3, "Order in court.", "Narrator"),
    ]

    result = service.generate(scene_blueprint, start_time_seconds=7.0)

    assert result.success and result.audio_track is not None
    assert service.read == [("Judge", 1.0), ("Narrator", 1.5)]
    track = result.audio_track
    assert track.metadata["scene_number"] == 3
    assert track.metadata["voice_lines"] == ["Judge", "Narrator"]
    assert track.start_time_seconds == 7.0
    assert track.duration_seconds == pytest.approx(
        1.0 + 1.5 + LINE_GAP_SECONDS, abs=0.2
    )
    assert Path(str(track.source_file)).is_file()
    assert scene_blueprint.estimated_speech_duration_seconds == track.duration_seconds


def test_a_scene_without_lines_goes_through_the_unchanged_single_voice_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fake_generate(self, blueprint, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(len(blueprint.line_blueprints))

        return "single-voice-result"

    monkeypatch.setattr(VoiceGenerationService, "generate", fake_generate)
    service = MultiVoiceGenerationService(providers=[])

    assert (
        service.generate(_blueprint(1, "One voice only.", None))
        == "single-voice-result"
    )
    assert calls == [0]


def test_a_failing_line_fails_the_scene_with_its_own_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_generate(self, blueprint, **kwargs):  # type: ignore[no-untyped-def]
        return VoiceGenerationResult(
            success=False,
            scene_number=blueprint.scene_number,
            status=VoiceGenerationStatus.FAILED,
            attempts=1,
            failure=VoiceGenerationFailure(
                reason=VoiceGenerationFailureReason.PROVIDER_ERROR,
                message="the provider refused the line",
                provider="test",
                recoverable=True,
            ),
        )

    monkeypatch.setattr(VoiceGenerationService, "generate", fake_generate)
    scene_blueprint = _blueprint(2, "A. B.", None)
    scene_blueprint.line_blueprints = [_blueprint(2, "A.", "Judge")]

    result = MultiVoiceGenerationService(providers=[]).generate(scene_blueprint)

    assert result.success is False and result.scene_number == 2
    assert result.failure is not None
    assert result.failure.message == "the provider refused the line"


# ------------------------------------------------------------------ per-line voices, end to end (dry run)


def _cast_pipeline():  # type: ignore[no-untyped-def]
    from src.providers.dry_run_voice_provider import DryRunVoiceProvider
    from tests.test_media_generation_pipeline import _pipeline

    pipeline = _pipeline()
    pipeline.voice_generation_service = MultiVoiceGenerationService(
        providers=[DryRunVoiceProvider()]
    )

    return pipeline


def _job_with_cast_scenes(cast: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    job = _job(1)
    job.genre_id = "genre.mystery"
    job.scenes = _scenes()
    ContentIntelligencePipeline.set_voice_cast(job, enabled=True, cast=cast or {})

    return job


def test_each_speaker_is_resolved_with_the_voice_chosen_for_it() -> None:
    from src.services.genre_profile_registry_service import GenreProfileRegistryService
    from src.services.genre_voice_directive_generation_service import (
        GenreVoiceDirectiveGenerationService,
    )
    from src.services.voice_cast_service import attach_line_blueprints
    from src.services.voice_profile_registry_service import VoiceProfileRegistryService
    from src.services.voice_resolution_runtime import VoiceResolutionRuntimeFactory

    registry = VoiceProfileRegistryService.with_default_profiles()
    runtime = VoiceResolutionRuntimeFactory().build(profiles=registry.list_all())
    directives = GenreVoiceDirectiveGenerationService(
        genre_registry=GenreProfileRegistryService.with_default_profiles(),
        voice_profile_registry=runtime.voice_profile_registry,
    )
    job = _job_with_cast_scenes({"judge": "voice.tense_suspense"})
    cast_scene = next(s for s in job.scenes if s.voice_lines)
    scene_blueprint = _blueprint(cast_scene.scene_number, cast_scene.narration, None)

    attach_line_blueprints(
        job=job,
        scenes=[cast_scene],
        blueprints=[scene_blueprint],
        directive_service=directives,
        resolution_runtime=runtime,
        genre_id=job.genre_id,
        language="English",
    )

    assert len(scene_blueprint.line_blueprints) == len(cast_scene.voice_lines)
    line = scene_blueprint.line_blueprints[0]
    assert line.profile.resolved_profile_id == "voice.tense_suspense"
    assert line.narration_text == cast_scene.voice_lines[0].text
    assert line.metadata["speaker"] == "Judge"


def test_an_unassigned_speaker_is_read_by_the_projects_usual_voice() -> None:
    from src.services.genre_profile_registry_service import GenreProfileRegistryService
    from src.services.genre_voice_directive_generation_service import (
        GenreVoiceDirectiveGenerationService,
    )
    from src.services.voice_cast_service import attach_line_blueprints
    from src.services.voice_profile_registry_service import VoiceProfileRegistryService
    from src.services.voice_resolution_runtime import VoiceResolutionRuntimeFactory

    registry = VoiceProfileRegistryService.with_default_profiles()
    runtime = VoiceResolutionRuntimeFactory().build(profiles=registry.list_all())
    directives = GenreVoiceDirectiveGenerationService(
        genre_registry=GenreProfileRegistryService.with_default_profiles(),
        voice_profile_registry=runtime.voice_profile_registry,
    )
    job = _job_with_cast_scenes()
    scene = next(s for s in job.scenes if s.voice_lines)
    blueprint = _blueprint(scene.scene_number, scene.narration, None)
    attach_line_blueprints(
        job=job,
        scenes=[scene],
        blueprints=[blueprint],
        directive_service=directives,
        resolution_runtime=runtime,
        genre_id=job.genre_id,
        language="English",
    )
    usual = directives.generate(scene=scene, genre_id=job.genre_id).voice_profile_id

    assert blueprint.line_blueprints[0].profile.requested_profile_id == usual


def test_the_voiceover_makes_one_track_per_scene_even_when_voices_differ() -> None:
    job = _job_with_cast_scenes({"judge": "voice.tense_suspense"})
    narrated = [s for s in job.scenes if not s.silent]

    result = _cast_pipeline().run_voice(job)

    assert result.audio_timeline is not None
    tracks = [
        t
        for t in result.audio_timeline.tracks
        if t.track_type == AudioTrackType.VOICEOVER
    ]
    numbers = sorted(int(t.metadata["scene_number"]) for t in tracks)
    assert numbers == sorted(s.scene_number for s in narrated)
    assert len(numbers) == len(set(numbers))  # one voice track per scene
    cast_tracks = [t for t in tracks if t.metadata.get("voice_lines")]
    assert cast_tracks and cast_tracks[0].metadata["voice_lines"] == ["Judge"]


# ------------------------------------------------------------------ the screen


def test_the_intake_section_has_the_cast_switch_and_lists_speakers_once_on(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QCheckBox, QComboBox, QVBoxLayout, QWidget

    from tests.test_suggestions import _studio, _texts

    view, job, _errors = _studio(_job(2))
    holder = QWidget()
    view._render_voice_cast_controls(QVBoxLayout(holder), job)  # noqa: SLF001
    boxes = holder.findChildren(QCheckBox)

    assert [b.text() for b in boxes] == ["Read this script with a cast of voices"]
    assert boxes[0].isChecked() is False
    assert not holder.findChildren(QComboBox)

    job.voice_cast_enabled = True
    job.scenes = _scenes()
    holder2 = QWidget()
    view._render_voice_cast_controls(QVBoxLayout(holder2), job)  # noqa: SLF001
    choices = holder2.findChildren(QComboBox)

    assert len(choices) == 3  # Narrator, Judge and Joan of Arc
    assert (
        choices[0].itemText(0) == "The project's usual voice (default)"
    )  # the narrator
    assert choices[1].itemText(0) == "Narrator voice (default)"
    assert any("No voice chosen yet" in t for t in _texts(holder2))


def test_switching_it_on_and_choosing_a_voice_are_saved_on_the_job(qapp) -> None:  # type: ignore[no-untyped-def]
    from tests.test_suggestions import _studio

    view, job, _errors = _studio(_job(2))
    view._handle_voice_cast_toggled(True)  # noqa: SLF001
    saved = view._current_job()  # noqa: SLF001
    assert saved is not None and saved.voice_cast_enabled is True

    view._handle_voice_cast_choice("Judge", "voice.tense_suspense")  # noqa: SLF001
    saved = view._current_job()  # noqa: SLF001
    assert saved is not None
    assert saved.voice_cast == {"judge": "voice.tense_suspense"}


# ------------------------------------------------------------------ editing a segment's text


def _edited_scenes(new_text: str):  # type: ignore[no-untyped-def]
    script = _intake(_JOAN_SCRIPT)
    judge = next(s for s in script.segments if s.voice_lines)
    edited = judge.model_copy(update={"narration": new_text})  # what the editors do
    revised = script.model_copy(
        update={
            "segments": [
                edited if s.segment_number == judge.segment_number else s
                for s in script.segments
            ]
        }
    )

    return ScenePlannerAgent().plan_from_generated_script(revised, _editorial_profile())


def test_editing_a_named_line_makes_the_voice_read_the_new_words() -> None:
    scenes = _edited_scenes("The court is now in session.")
    first = scenes[0]

    assert first.narration == "The court is now in session."
    assert [(line.speaker, line.text) for line in first.voice_lines] == [
        ("Judge", "The court is now in session.")
    ]


def test_an_untouched_named_line_keeps_its_voice_line_exactly() -> None:
    scenes = _edited_scenes("The court will hear the evidence.")

    assert scenes[0].voice_lines[0].text == "The court will hear the evidence."


def test_the_segment_list_says_who_reads_each_segment(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from tests.test_suggestions import _studio, _texts

    view, job, _errors = _studio(_job(2))
    job.generated_script = _intake(_JOAN_SCRIPT)
    holder = QWidget()
    view._render_ci_script_panel(QVBoxLayout(holder), job)  # noqa: SLF001
    texts = _texts(holder)

    assert any("read by Judge" in t for t in texts)
    assert any("read by Joan of Arc" in t for t in texts)
    assert any("visual only, no voice" in t for t in texts)


# ------------------------------------------------------------------ a scene that is ONE named line


@_needs_ffmpeg
def test_a_scene_made_of_a_single_named_line_needs_no_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found live 2026-10-18: "JUDGE: The court will hear the evidence." is one line, one file - the join
    refused it ("Joining needs at least two audio files") and the whole voiceover failed.
    """

    service = MultiVoiceGenerationService(providers=[])
    line_file = tmp_path / "only.wav"
    _tone(line_file, 1.2)

    def fake_generate(self, blueprint, *, start_time_seconds=0.0, provider_name=None):  # type: ignore[no-untyped-def]
        return VoiceGenerationResult(
            success=True,
            scene_number=blueprint.scene_number,
            status=VoiceGenerationStatus.COMPLETED,
            provider="test",
            output_file=str(line_file),
            audio_track=AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file=str(line_file),
                start_time_seconds=start_time_seconds,
                duration_seconds=1.2,
                status=AudioTrackStatus.READY,
                metadata={"scene_number": blueprint.scene_number},
            ),
            attempts=1,
        )

    monkeypatch.setattr(VoiceGenerationService, "generate", fake_generate)
    scene_blueprint = _blueprint(1, "The court will hear the evidence.", None)
    scene_blueprint.line_blueprints = [
        _blueprint(1, "The court will hear the evidence.", "Judge")
    ]

    result = service.generate(scene_blueprint, start_time_seconds=3.0)

    assert result.success and result.audio_track is not None
    assert result.audio_track.source_file == str(line_file)
    assert result.audio_track.start_time_seconds == 3.0
    assert result.audio_track.metadata["voice_lines"] == ["Judge"]
    assert result.audio_track.duration_seconds == pytest.approx(1.2, abs=0.2)


def test_a_single_named_line_scene_goes_through_a_dry_run_voiceover() -> None:
    job = _job_with_cast_scenes({"judge": "voice.tense_suspense"})
    single = [s for s in job.scenes if len(s.voice_lines) == 1]

    assert single, "the script has scenes that are one named line"
    result = _cast_pipeline().run_voice(job)

    assert result.audio_timeline is not None


# ------------------------------------------------------------------ the narrator's own voice


def test_the_narrator_can_have_a_voice_chosen_for_it() -> None:
    from src.services.voice_cast_service import narrator_profile_id

    job = _job(2)
    assert narrator_profile_id(job) is None

    ContentIntelligencePipeline.set_voice_cast(
        job, enabled=True, cast={"narrator": "voice.history_narrator"}
    )
    assert narrator_profile_id(job) == "voice.history_narrator"
    assert speaker_profile_id(job, "Narrator") == "voice.history_narrator"

    ContentIntelligencePipeline.set_voice_cast(job, enabled=False)
    assert narrator_profile_id(job) is None  # cast switched off: the usual voice


def test_a_scene_read_only_by_the_narrator_uses_the_narrators_chosen_voice() -> None:
    job = _job_with_cast_scenes(
        {"narrator": "voice.history_narrator", "judge": "voice.tense_suspense"}
    )
    plain = [s for s in job.scenes if not s.voice_lines and not s.silent]
    assert plain

    result = _cast_pipeline().run_voice(job)

    assert result.audio_timeline is not None
    by_scene = {
        int(t.metadata["scene_number"]): t.metadata["requested_voice_profile_id"]
        for t in result.audio_timeline.tracks
        if t.track_type == AudioTrackType.VOICEOVER
    }
    assert {by_scene[s.scene_number] for s in plain} == {"voice.history_narrator"}


def test_the_cast_panel_lists_the_narrator_first(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    from tests.test_suggestions import _studio

    view, job, _errors = _studio(_job(2))
    job.voice_cast_enabled = True
    job.scenes = _scenes()
    holder = QWidget()
    view._render_voice_cast_controls(QVBoxLayout(holder), job)  # noqa: SLF001
    names = [label.text() for label in holder.findChildren(QLabel)]

    assert "Narrator" in names
    assert names.index("Narrator") < names.index("Judge")


def test_a_greyed_music_button_says_what_to_do_first(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QLabel

    from src.desktop.job_store import InMemoryJobStore
    from tests.test_production_audio_generation_gui import _job as audio_job
    from tests.test_production_audio_generation_gui import _view as audio_view

    store = InMemoryJobStore()
    job = audio_job(with_scenes=True, with_clips=True)
    store.add(job)
    view = audio_view(store)
    view.set_job(job.id)
    view.refresh(job)

    texts = [label.text() for label in view.findChildren(QLabel)]
    assert any("Build editing timeline first" in t for t in texts)


def test_a_written_emotion_tag_reaches_the_line_and_the_scene_blueprints() -> None:
    from src.models.delivery_cue import DeliveryCue
    from src.services.genre_profile_registry_service import GenreProfileRegistryService
    from src.services.genre_voice_directive_generation_service import (
        GenreVoiceDirectiveGenerationService,
    )
    from src.services.voice_cast_service import attach_line_blueprints
    from src.services.voice_profile_registry_service import VoiceProfileRegistryService
    from src.services.voice_resolution_runtime import VoiceResolutionRuntimeFactory

    registry = VoiceProfileRegistryService.with_default_profiles()
    runtime = VoiceResolutionRuntimeFactory().build(profiles=registry.list_all())
    directives = GenreVoiceDirectiveGenerationService(
        genre_registry=GenreProfileRegistryService.with_default_profiles(),
        voice_profile_registry=runtime.voice_profile_registry,
    )
    job = _job_with_cast_scenes({"judge": "voice.tense_suspense"})
    scene = next(s for s in job.scenes if s.voice_lines)
    first_line = scene.voice_lines[0].text
    job.delivery_cues = [
        DeliveryCue(anchor=" ".join(first_line.split()[:8]), tag="stern")
    ]
    blueprint = _blueprint(scene.scene_number, scene.narration, None)

    attach_line_blueprints(
        job=job,
        scenes=[scene],
        blueprints=[blueprint],
        directive_service=directives,
        resolution_runtime=runtime,
        genre_id=job.genre_id,
        language="English",
    )

    assert blueprint.line_blueprints[0].delivery_narration == f"[stern] {first_line}"
    assert blueprint.line_blueprints[0].narration_text == first_line
