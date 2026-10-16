"""
Visual-only scenes (2026-10-15): a script paragraph written `[VISUAL 8s] description` is a shot with no
narration - a fixed length, no voice track, no subtitles, music and effects still underneath. It stays an
ordinary scene with one clip and one crossfade, so the render arithmetic (voice placement, chunk slicing) is
unchanged; the voice after it must still start exactly where its own scene starts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.agents.scene_planner.agent import MergeSettings, ScenePlannerAgent
from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.ffmpeg_config import (
    FFmpegConfig,
    FFmpegHardwareAcceleration,
    FFmpegVideoCodec,
)
from src.models.generated_script import GeneratedScript
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.pipeline.render_stage import RenderPipelineStage
from src.pipeline.stage_result import PipelineStageStatus
from src.pipeline.voice_stage import VoicePipelineStage
from src.services.audio_realignment_service import BASIS_SEQUENTIAL, mark_position_basis
from src.services.clip_duration_reconciliation_service import (
    ClipDurationReconciliationService,
)
from src.services.dialogue_script_parser import DialogueScriptError
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.genre_timeline_pipeline_service import GenreTimelinePipelineService
from src.services.production_render_service import ProductionRenderService
from src.services.script_intake_service import ScriptIntakeService
from src.services.visual_scene_marker import (
    DEFAULT_VISUAL_SECONDS,
    parse_visual_marker,
)
from src.services.voice_timeline_service import VoiceTimelineService
from tests.test_audio_realignment_real_ffmpeg import (
    _make_clip,
    _make_voice,
    _picture_change_times,
    _tone_onsets,
)
from tests.test_render_stage import build_context, build_job
from tests.test_scene_planner_generated_script import _editorial_profile
from tests.test_voice_stage import (
    SyntheticVoiceGenerationService,
    SyntheticVoiceSpecification,
    build_scene,
)
from tests.test_voice_stage import build_context as voice_context
from tests.test_voice_stage import build_job as voice_job

_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _intake() -> ScriptIntakeService:
    return ScriptIntakeService.__new__(ScriptIntakeService)


def _script_from(text: str, *, character_oriented: bool = False) -> GeneratedScript:
    return _intake().normalize_text_to_script(
        raw_text=text,
        topic="The Room",
        genre_id="genre.default",
        target_duration_seconds=60,
        character_oriented=character_oriented,
    )


# ---------------------------------------------------------------------------- the marker


@pytest.mark.parametrize(
    "text, seconds",
    [
        ("[VISUAL 8s] The camera drifts.", 8.0),
        ("[visual 5] The camera drifts.", 5.0),
        ("[VISUAL: 4 seconds] The camera drifts.", 4.0),
        ("[Visual 2.5 sec]: The camera drifts.", 2.5),
        ("[VISUAL] The camera drifts.", DEFAULT_VISUAL_SECONDS),
        ("[SILENT 3s] The camera drifts.", 3.0),
    ],
)
def test_the_marker_is_read_in_its_written_forms(text: str, seconds: float) -> None:
    marker = parse_visual_marker(text)

    assert marker is not None
    assert marker.seconds == seconds
    assert marker.description == "The camera drifts."


def test_ordinary_text_is_not_a_marker() -> None:
    assert parse_visual_marker("The camera drifts over the room.") is None
    assert parse_visual_marker("[Editor's note] keep this.") is None


def test_a_description_that_continues_on_the_next_lines_is_kept_whole() -> None:
    marker = parse_visual_marker("[VISUAL 6s] The camera drifts\nover the empty room.")

    assert marker is not None
    assert marker.description == "The camera drifts over the empty room."


@pytest.mark.parametrize("text", ["[VISUAL 8s]", "[VISUAL 8s]   "])
def test_a_marker_without_a_description_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="needs a description"):
        parse_visual_marker(text)


@pytest.mark.parametrize("seconds", ["1", "9", "30"])
def test_seconds_outside_one_clip_are_refused_with_the_limit_named(
    seconds: str,
) -> None:
    with pytest.raises(ValueError, match="2 to 8 seconds"):
        parse_visual_marker(f"[VISUAL {seconds}s] An empty room.")


# ---------------------------------------------------------------------------- intake


def test_intake_makes_a_silent_segment_with_its_own_length() -> None:
    script = _script_from("Hello there.\n\n[VISUAL 8s] The empty room.\n\nGoodbye.")

    segments = script.segments
    assert [s.silent_seconds for s in segments] == [None, 8.0, None]
    assert segments[1].narration == "The empty room."
    assert segments[1].end_seconds - segments[1].start_seconds == 8.0
    # The next segment starts after the silent one.
    assert segments[2].start_seconds == segments[1].end_seconds


def test_what_is_spoken_never_includes_a_visual_description() -> None:
    script = _script_from("Hello there.\n\n[VISUAL 8s] The empty room.\n\nGoodbye.")

    assert script.full_narration == "Hello there. Goodbye."
    assert script.word_count == 3
    assert script.segments[1].word_count == 0


def test_a_visual_scene_changes_the_script_hash() -> None:
    plain = _script_from("Hello there.\n\nGoodbye.")
    with_visual = _script_from(
        "Hello there.\n\n[VISUAL 8s] The empty room.\n\nGoodbye."
    )
    longer = _script_from("Hello there.\n\n[VISUAL 6s] The empty room.\n\nGoodbye.")

    assert plain.content_hash != with_visual.content_hash
    assert with_visual.content_hash != longer.content_hash


def test_a_script_made_only_of_visual_shots_is_accepted() -> None:
    script = _script_from("[VISUAL 4s] A door.\n\n[VISUAL 4s] A window.")

    assert [s.silent_seconds for s in script.segments] == [4.0, 4.0]
    assert script.full_narration == ""


def test_a_bad_marker_stops_the_intake_with_a_clear_message() -> None:
    with pytest.raises(ValueError, match="2 to 8 seconds"):
        _script_from("Hello.\n\n[VISUAL 20s] A long, long hallway.")


def test_dialogue_scripts_take_visual_shots_between_the_speakers() -> None:
    script = _script_from(
        "WALTER: Who is there?\n\n[VISUAL 8s] The empty room.\n\nFRANK: Nobody.",
        character_oriented=True,
    )

    assert [s.silent_seconds for s in script.segments] == [None, 8.0, None]
    assert [len(s.dialogue) for s in script.segments] == [1, 0, 1]


def test_a_dialogue_error_after_a_visual_shot_still_names_the_right_line() -> None:
    text = "WALTER: Hello.\n\n[VISUAL 8s] The empty room.\n\nThis line has no speaker"

    with pytest.raises(DialogueScriptError, match="Line 5"):
        _script_from(text, character_oriented=True)


# ---------------------------------------------------------------------------- planning


def _planned(text: str, **kwargs):  # type: ignore[no-untyped-def]
    return ScenePlannerAgent().plan_from_generated_script(
        _script_from(text), _editorial_profile(), **kwargs
    )


def test_the_planner_makes_one_fixed_length_silent_scene() -> None:
    scenes = _planned(
        "The door was open.\n\n[VISUAL 8s] The empty room.\n\nNobody came."
    )
    silent = [s for s in scenes if s.silent]

    assert len(silent) == 1
    assert silent[0].estimated_duration_seconds == 8
    assert silent[0].narration == "The empty room."
    assert silent[0].title.endswith("(visual only)")
    assert [s.scene_number for s in scenes] == list(range(1, len(scenes) + 1))
    assert not any(s.silent for s in scenes if s is not silent[0])


def test_a_long_visual_description_is_never_split_into_several_scenes() -> None:
    text = "[VISUAL 8s] The camera drifts. It finds a table. A cup sits on it. The tea is warm."

    assert len(_planned(text)) == 1


def test_merging_never_joins_a_visual_scene_to_its_neighbours() -> None:
    text = "A door. A lamp.\n\n[VISUAL 4s] The empty room.\n\nA bed. A chair.\n\nA letter. A pen."
    scenes = _planned(text, merge=MergeSettings(target_seconds=9.0, keep_beats=False))
    silent = [s for s in scenes if s.silent]

    assert len(silent) == 1
    assert silent[0].narration == "The empty room."
    assert "merged_segment_numbers" not in silent[0].metadata


def test_the_script_estimate_for_a_visual_scene_is_its_written_length() -> None:
    scenes = _planned("[VISUAL 5s] A long corridor.")

    assert scenes[0].estimated_duration_seconds == 5


# ---------------------------------------------------------------------------- voice and subtitles


def test_a_visual_scene_gets_no_subtitles_whatever_the_project_override() -> None:
    from src.models.editing_directives import SceneEditingDirectives, SubtitleDirective

    service = GenreDirectiveGenerationService(genre_registry=_REGISTRY)
    scene = Scene(
        scene_number=1,
        title="Scene 1",
        narration="The empty room.",
        visual_prompt="v",
        estimated_duration_seconds=6,
        silent=True,
    )
    spoken = scene.model_copy(update={"silent": False})
    override = SceneEditingDirectives(
        scene_number=1, subtitles=SubtitleDirective(preset_id="subtitle.bold_punchy")
    )

    assert (
        service.generate(scene=scene, genre_id="genre.documentary").subtitles.enabled
        is False
    )
    assert (
        service.generate(
            scene=scene, genre_id="genre.documentary", overrides=override
        ).subtitles.enabled
        is False
    )
    assert service.generate(
        scene=spoken, genre_id="genre.documentary"
    ).subtitles.enabled


def test_the_voice_stage_needs_no_blueprint_for_a_visual_scene_and_steps_past_its_length() -> (
    None
):
    scenes = [
        build_scene(1),
        build_scene(2, estimated_duration_seconds=6),
        build_scene(3),
    ]
    scenes[1].silent = True
    job = voice_job(scenes=scenes)
    service = SyntheticVoiceGenerationService(
        specifications={
            1: SyntheticVoiceSpecification(duration_seconds=4.0),
            3: SyntheticVoiceSpecification(duration_seconds=5.0),
        }
    )
    blueprints = [
        ResolvedVoiceBlueprint.model_construct(scene_number=1),
        ResolvedVoiceBlueprint.model_construct(scene_number=3),
    ]
    stage = VoicePipelineStage(
        blueprints=blueprints,
        generation_service=service,
        timeline_service=VoiceTimelineService(),
    )

    result = stage.execute(voice_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert service.generated_scene_numbers == [1, 3]
    # Scene 3 starts after scene 1's 4 s AND the silent scene's 6 s - not right after scene 1.
    assert service.received_start_times == [0.0, 10.0]
    assert scenes[1].real_narration_duration_seconds is None


def test_a_missing_blueprint_for_a_spoken_scene_is_still_refused() -> None:
    scenes = [build_scene(1), build_scene(2)]
    scenes[1].silent = True
    job = voice_job(scenes=scenes)
    stage = VoicePipelineStage(
        blueprints=[ResolvedVoiceBlueprint.model_construct(scene_number=1)],
        generation_service=SyntheticVoiceGenerationService(
            specifications={1: SyntheticVoiceSpecification()}
        ),
        timeline_service=VoiceTimelineService(),
    )
    assert stage.execute(voice_context(job)).status == PipelineStageStatus.COMPLETED

    spoken = voice_job(scenes=[build_scene(1), build_scene(2)])
    refused = VoicePipelineStage(
        blueprints=[ResolvedVoiceBlueprint.model_construct(scene_number=1)],
        generation_service=SyntheticVoiceGenerationService(
            specifications={1: SyntheticVoiceSpecification()}
        ),
        timeline_service=VoiceTimelineService(),
    ).execute(voice_context(spoken))

    assert refused.status == PipelineStageStatus.FAILED


def test_a_stock_clip_for_a_visual_scene_is_trimmed_to_its_written_length(
    tmp_path: Path,
) -> None:
    class _RecordingExtractor:
        targets: list[float] = []

        def trim_to_duration(
            self, *, video_path: str, target_duration_seconds: float, output_path: str
        ) -> None:
            self.targets.append(target_duration_seconds)
            Path(output_path).write_bytes(b"trimmed")

    source = tmp_path / "1.mp4"
    source.write_bytes(b"original")
    scene = Scene(
        scene_number=1,
        title="Scene 1",
        narration="The empty room.",
        visual_prompt="v",
        estimated_duration_seconds=4,
        silent=True,
    )
    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=10,
        local_file=source.as_posix(),
        status=VideoClipStatus.READY,
    )
    extractor = _RecordingExtractor()

    result = ClipDurationReconciliationService(
        frame_extraction_service=extractor  # type: ignore[arg-type]
    ).reconcile(scenes=[scene], clips=[clip])

    assert extractor.targets == [4.0]
    assert result.clips[0].duration_seconds == 4


# ---------------------------------------------------------------------------- real render

_needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="Real render check requires ffmpeg and ffprobe.",
)
_TRANSITION = _REGISTRY.resolve(
    "genre.documentary"
).profile.editing.default_transition_duration_seconds
_CLIP_SECONDS = 4
_NARRATION_SECONDS = 3.0


@_needs_ffmpeg
def test_the_voice_after_a_visual_scene_starts_where_its_own_scene_starts(
    tmp_path: Path,
) -> None:
    """Red (spoken), green (VISUAL, no voice), blue (spoken). Voices are laid end to end as the Audio
    tab does; the render must move the blue scene's voice onto the blue picture, past the silent shot.
    """

    clips_dir = tmp_path / "clips"
    voice_dir = tmp_path / "voice"
    clips_dir.mkdir()
    voice_dir.mkdir()
    scenes: list[Scene] = []
    clips: list[VideoClip] = []
    tracks: list[AudioTrack] = []
    blueprints: list[ResolvedVoiceBlueprint] = []
    laid_at = 0.0

    for number, colour in enumerate(("red", "green", "blue"), start=1):
        silent = number == 2
        clip_file = clips_dir / f"{number}.mp4"
        _make_clip(clip_file, colour)
        scenes.append(
            Scene(
                scene_number=number,
                title=f"Scene {number}",
                narration="The empty room." if silent else f"Narration {number}.",
                visual_prompt=f"Visual {number}.",
                estimated_duration_seconds=_CLIP_SECONDS,
                status=SceneStatus.READY,
                silent=silent,
            )
        )
        clips.append(
            VideoClip(
                scene_number=number,
                source_type=SceneSourceType.MANUAL_UPLOAD,
                duration_seconds=_CLIP_SECONDS,
                prompt=f"s{number}",
                provider="Manual Upload",
                local_file=clip_file.as_posix(),
                resolution="320x180",
                source_status=SceneSourceStatus.READY,
                status=VideoClipStatus.READY,
            )
        )

        if silent:
            continue

        voice_file = voice_dir / f"{number}.wav"
        _make_voice(voice_file)
        track = AudioTrack(
            track_type=AudioTrackType.VOICEOVER,
            source_file=voice_file.as_posix(),
            start_time_seconds=laid_at,
            duration_seconds=_NARRATION_SECONDS,
            status=AudioTrackStatus.READY,
            metadata={"scene_number": number},
        )
        mark_position_basis(track, BASIS_SEQUENTIAL)
        tracks.append(track)
        laid_at += _NARRATION_SECONDS
        blueprints.append(
            ResolvedVoiceBlueprint(
                scene_number=number,
                status=VoiceBlueprintResolutionStatus.RESOLVED,
                profile=ResolvedVoiceProfileReference(
                    requested_profile_id="voice.test",
                    resolved_profile_id="voice.test",
                    display_name="Test Voice",
                    found_exact_match=True,
                    used_fallback=False,
                ),
                narration_text=f"Narration {number}.",
                estimated_speech_duration_seconds=_NARRATION_SECONDS,
            )
        )

    timeline = (
        GenreTimelinePipelineService(
            genre_directive_service=GenreDirectiveGenerationService(
                genre_registry=_REGISTRY
            ),
            directive_resolution_service=EditingDirectiveResolutionService(
                effect_registry=EffectRegistryService.with_default_presets()
            ),
        )
        .build(scenes=scenes, clips=clips, genre_id="genre.documentary")
        .timeline
    )
    job = build_job()
    job.scenes = scenes
    job.video_clips = clips
    job.video_timeline = timeline
    job.voice_file = tracks[0].source_file
    job.audio_timeline = AudioTimeline(tracks=tracks, sample_rate=48000, channels=2)

    target = tmp_path / "out" / "final.mp4"
    stage = RenderPipelineStage(
        production_render_service=ProductionRenderService(
            ffmpeg_config=FFmpegConfig(
                video_codec=FFmpegVideoCodec.LIBX264,
                hardware_acceleration=FFmpegHardwareAcceleration.NONE,
                timeout_seconds=600.0,
            ),
            output_file=target.as_posix(),
        ),
        voice_blueprints=blueprints,
        transition_duration_seconds=_TRANSITION,
        subtitles_enabled=False,
    )

    result = stage.execute(build_context(job))

    assert result.successful, result.errors

    onsets = _tone_onsets(target)
    picture = _picture_change_times(target)

    # Two tones only: scene 1's at the very start, scene 3's where the blue picture starts.
    assert onsets[0] == pytest.approx(0.0, abs=0.25)
    assert onsets[1] == pytest.approx(picture[2], abs=0.3)
    # And it is well past where it would sit with no silent scene (scene 2's picture start).
    assert onsets[1] > picture[1] + 1.0
