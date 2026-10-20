"""Voice cast: who reads which line.

A voice-cast project maps each speaker named in the script ("Judge", "Joan of Arc") to one of the app's voice
profiles. A scene whose narration is made of lines from different readers (Scene.voice_lines) gets one voice
blueprint PER LINE attached to its scene blueprint; MultiVoiceGenerationService then reads each line with its
own voice and joins them into the scene's single voice track. The narrator - and any speaker with no voice
assigned - is read by the project's usual (genre) voice.
"""

from __future__ import annotations

from src.models.dialogue import NARRATOR_NAME
from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.delivery_cues import apply_delivery_cues
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.voice_resolution_runtime import VoiceResolutionRuntime


def cast_key(speaker: str) -> str:
    return " ".join(speaker.split()).lower()


def speaker_profile_id(job: VideoJob, speaker: str) -> str | None:
    """The voice profile assigned to `speaker` (the narrator included), or None when none was chosen."""

    return job.voice_cast.get(cast_key(speaker))


def narrator_profile_id(job: VideoJob) -> str | None:
    """The voice chosen for the narrator in a voice-cast project (None = the project's usual voice). It reads every
    line that names no speaker, including whole scenes that have no named voice at all.
    """

    if not job.voice_cast_enabled:
        return None

    return job.voice_cast.get(cast_key(NARRATOR_NAME))


def cast_speakers(job: VideoJob) -> list[str]:
    """The named speakers in the project's scenes (or script), once each, in order of appearance."""

    seen: list[str] = []

    if job.scenes:
        lines = [line for scene in job.scenes for line in scene.voice_lines]
    elif job.generated_script is not None:
        lines = [
            line
            for segment in job.generated_script.segments
            for line in segment.voice_lines
        ]
    else:
        lines = []

    for line in lines:
        if cast_key(line.speaker) == cast_key(NARRATOR_NAME):
            continue

        if line.speaker not in seen:
            seen.append(line.speaker)

    return seen


def unassigned_speakers(job: VideoJob) -> list[str]:
    """Speakers in the script with no voice chosen yet (they will be read by the narrator voice)."""

    return [s for s in cast_speakers(job) if speaker_profile_id(job, s) is None]


def _paced_speed(speed: float, job: VideoJob) -> float:
    """The voice's speed with the project's pace applied (ElevenLabs takes 0.7-1.2)."""

    return round(max(0.7, min(1.2, speed * job.pace.voice_speed_factor)), 3)


def attach_line_blueprints(
    *,
    job: VideoJob,
    scenes: list[Scene],
    blueprints: list[ResolvedVoiceBlueprint],
    directive_service: GenreVoiceDirectiveGenerationService,
    resolution_runtime: VoiceResolutionRuntime,
    genre_id: str,
    language: str,
    language_code: str = "en",
) -> None:
    """Give each scene blueprint whose scene has voice lines one blueprint per line, resolved with that
    line's own speaker voice. Scenes without voice lines are left untouched."""

    scenes_by_number = {scene.scene_number: scene for scene in scenes}

    for blueprint in blueprints:
        # The operator's emotion tags go back in for the voice request only (see delivery_cues).
        blueprint.delivery_narration = apply_delivery_cues(
            job.delivery_cues, blueprint.narration_text
        )
        blueprint.speed = _paced_speed(blueprint.speed, job)
        scene = scenes_by_number.get(blueprint.scene_number)

        if scene is None or not scene.voice_lines:
            continue

        line_blueprints: list[ResolvedVoiceBlueprint] = []

        for line in scene.voice_lines:
            directive = directive_service.generate(
                scene=scene,
                genre_id=genre_id,
                language=language,
                language_code=language_code,
                voice_profile_id=speaker_profile_id(job, line.speaker),
            )
            line_blueprint = resolution_runtime.resolution_service.resolve(
                directive,
                narration_text=line.text,
                scene_duration_seconds=None,
                target_provider=resolution_runtime.target_provider,
            )
            line_blueprint.delivery_narration = apply_delivery_cues(
                job.delivery_cues, line.text
            )
            line_blueprint.speed = _paced_speed(line_blueprint.speed, job)
            line_blueprint.metadata["speaker"] = line.speaker
            line_blueprints.append(line_blueprint)

        blueprint.line_blueprints = line_blueprints
