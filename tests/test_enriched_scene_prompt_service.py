from __future__ import annotations

from src.models.cinematic_prompt import CinematicPromptPackage, ResolvedCinematicPrompt
from src.models.enriched_scene_prompt import EnrichedScenePrompt
from src.models.google_flow_generation import (
    GoogleFlowReferenceAsset,
    GoogleFlowReferenceRole,
)
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.scene import Scene
from src.models.shot_planning import (
    CinematicShotPlan,
    ShotAngle,
    ShotMovement,
    ShotSize,
    ShotSpecification,
)
from src.models.video_job import VideoJob
from src.models.visual_continuity import (
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.enriched_scene_prompt_service import EnrichedScenePromptService

_SCRIPT_LOCK_HASH = "a" * 64


class _FakeSceneVideoGenerationService:
    def __init__(
        self,
        *,
        reference_assets: list[GoogleFlowReferenceAsset] | None = None,
        model_family: str | None = "veo-3",
    ) -> None:
        self._reference_assets = reference_assets or []
        self._model_family = model_family

    def _resolve_reference_assets(
        self, job: VideoJob, scene: Scene
    ) -> list[GoogleFlowReferenceAsset]:
        return self._reference_assets

    def _configured_model_family(self) -> str | None:
        return self._model_family


def _scene(*, scene_number: int = 1) -> Scene:
    return Scene(
        scene_number=scene_number,
        title="Test Scene",
        narration="Something happens.",
        visual_prompt="A cinematic visual.",
        estimated_duration_seconds=8,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        source_status=SceneSourceStatus.READY,
        manual_file_path="assets/videos/manual/test_scene.mp4",
    )


def _job(**overrides: object) -> VideoJob:
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="documentary",
        topic="A test topic",
    )

    for key, value in overrides.items():
        setattr(job, key, value)

    return job


def test_build_entry_with_no_supporting_data_falls_back_gracefully() -> None:
    """A scene planned before Production Plan phases ran at all (no
    shot plan, no continuity bible, no prompt package) must still
    produce a real entry, falling back to Scene.visual_prompt - never
    raise."""

    service = EnrichedScenePromptService()

    entry = service.build_entry(job=_job(), scene=_scene())

    assert entry.base_prompt_text == "A cinematic visual."
    assert entry.negative_constraints == []
    assert entry.transition_in is None
    assert entry.transition_out is None
    assert entry.continuity_incoming is None
    assert entry.continuity_outgoing is None
    assert entry.reference_assets == []
    assert entry.execution_model_family is None
    assert entry.specificity_score is None
    assert entry.is_blocked is None


def test_build_entry_uses_the_real_compiled_prompt_text_when_available() -> None:
    package = CinematicPromptPackage(
        script_lock_hash=_SCRIPT_LOCK_HASH,
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash=_SCRIPT_LOCK_HASH,
                prompt_text="The real compiled prompt text.",
                negative_constraints=["no text overlays", "no logos"],
            )
        ],
    )

    service = EnrichedScenePromptService()

    entry = service.build_entry(
        job=_job(cinematic_prompt_package=package), scene=_scene()
    )

    assert entry.base_prompt_text == "The real compiled prompt text."
    assert entry.negative_constraints == ["no text overlays", "no logos"]


def test_build_entry_folds_in_transitions_from_the_shot_plan() -> None:
    shot_plan = CinematicShotPlan(
        script_lock_hash=_SCRIPT_LOCK_HASH,
        shots=[
            ShotSpecification(
                scene_number=1,
                shot_size=ShotSize.MEDIUM,
                shot_angle=ShotAngle.EYE_LEVEL,
                movement=ShotMovement.STATIC,
                lens="35mm",
                composition="centered",
                blocking="subject centered",
                lighting="soft daylight",
                action="The subject walks forward.",
                transition_in="fade_black",
                transition_out="cross_dissolve",
                duration_seconds=8.0,
            )
        ],
    )

    service = EnrichedScenePromptService()

    entry = service.build_entry(job=_job(cinematic_shot_plan=shot_plan), scene=_scene())

    assert entry.transition_in == "fade_black"
    assert entry.transition_out == "cross_dissolve"


def test_build_entry_folds_in_full_continuity_state_not_just_location_and_lighting() -> (
    None
):
    bible = VisualContinuityBible(
        script_lock_hash=_SCRIPT_LOCK_HASH,
        identities=[],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(
                    wardrobe="a worn leather jacket",
                    condition="tired",
                    location="a rainy street",
                    time_of_day="night",
                    weather="rain",
                    lighting="neon glow",
                    props=["umbrella"],
                    vehicles=["taxi"],
                ),
                shot_action="She hails a taxi.",
                outgoing_state=VisualState(
                    wardrobe="a worn leather jacket",
                    condition="relieved",
                    location="inside the taxi",
                    time_of_day="night",
                    weather="rain",
                    lighting="dashboard glow",
                ),
                entity_names=[],
            )
        ],
    )

    service = EnrichedScenePromptService()

    entry = service.build_entry(job=_job(visual_continuity_bible=bible), scene=_scene())

    assert entry.continuity_incoming is not None
    assert entry.continuity_incoming.wardrobe == "a worn leather jacket"
    assert entry.continuity_incoming.weather == "rain"
    assert entry.continuity_incoming.props == ["umbrella"]
    assert entry.continuity_incoming.vehicles == ["taxi"]

    assert entry.continuity_outgoing is not None
    assert entry.continuity_outgoing.location == "inside the taxi"
    assert entry.continuity_outgoing.condition == "relieved"


def test_build_entry_resolves_real_reference_assets_via_the_injected_service() -> None:
    reference_asset = GoogleFlowReferenceAsset(
        source_path="/assets/character_ref.png",
        checksum="deadbeef",
        role=GoogleFlowReferenceRole.CHARACTER,
    )

    fake_generation_service = _FakeSceneVideoGenerationService(
        reference_assets=[reference_asset],
        model_family="veo-3",
    )

    service = EnrichedScenePromptService(
        scene_video_generation_service=fake_generation_service,  # type: ignore[arg-type]
    )

    entry = service.build_entry(job=_job(), scene=_scene())

    assert entry.reference_assets == [reference_asset]
    assert entry.execution_model_family == "veo-3"


def test_build_entry_never_fabricates_aspect_ratio_or_resolution() -> None:
    """Real, disclosed honesty: today's real submissions never pin
    aspect_ratio/resolution ahead of time - this screen must show that
    truthfully (None) rather than making up a value."""

    service = EnrichedScenePromptService()

    entry = service.build_entry(job=_job(), scene=_scene())

    assert entry.execution_aspect_ratio is None
    assert entry.execution_resolution is None


def test_build_entry_uses_real_narration_duration_over_the_estimate_when_available() -> (
    None
):
    scene = _scene()
    scene.real_narration_duration_seconds = 6.4

    service = EnrichedScenePromptService()

    entry = service.build_entry(job=_job(), scene=scene)

    assert entry.execution_duration_seconds == 6.4


def test_build_entry_falls_back_to_the_estimate_when_no_real_duration_exists() -> None:
    service = EnrichedScenePromptService()

    entry = service.build_entry(job=_job(), scene=_scene())

    assert entry.execution_duration_seconds == 8.0


def test_build_entry_folds_in_quality_scores_and_block_status() -> None:
    package = CinematicPromptPackage(
        script_lock_hash=_SCRIPT_LOCK_HASH,
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash=_SCRIPT_LOCK_HASH,
                prompt_text="Text.",
                specificity_score=40,
                continuity_score=90,
                action_score=85,
                camera_score=88,
                lighting_score=91,
                reveal_safety_score=95,
            )
        ],
    )

    service = EnrichedScenePromptService()

    entry = service.build_entry(
        job=_job(cinematic_prompt_package=package), scene=_scene()
    )

    assert entry.specificity_score == 40
    assert entry.is_blocked is True  # 40 < QUALITY_BLOCK_THRESHOLD (50)


def test_full_text_renders_every_populated_section() -> None:
    entry = EnrichedScenePrompt(
        scene_number=1,
        base_prompt_text="Base prompt text.",
        negative_constraints=["no logos"],
        transition_in="fade_black",
        transition_out="cross_dissolve",
        continuity_incoming=VisualState(location="a street"),
        continuity_outgoing=VisualState(location="inside a taxi"),
        reference_assets=[
            GoogleFlowReferenceAsset(
                source_path="/ref.png",
                checksum="abc",
                role=GoogleFlowReferenceRole.CHARACTER,
            )
        ],
        execution_model_family="veo-3",
        execution_duration_seconds=8.0,
        specificity_score=80,
        continuity_score=80,
        action_score=80,
        camera_score=80,
        lighting_score=80,
        reveal_safety_score=80,
        is_blocked=False,
    )

    text = entry.full_text()

    assert "Base prompt text." in text
    assert "no logos" in text
    assert "fade_black" in text
    assert "cross_dissolve" in text
    assert "a street" in text
    assert "inside a taxi" in text
    assert "/ref.png" in text
    assert "veo-3" in text
    assert "specificity=80" in text


def test_full_text_shows_not_yet_scored_when_no_scores_exist() -> None:
    entry = EnrichedScenePrompt(
        scene_number=1,
        base_prompt_text="Base prompt text.",
    )

    text = entry.full_text()

    assert "not yet scored" in text
