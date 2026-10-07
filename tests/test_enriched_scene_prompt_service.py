from __future__ import annotations

from src.models.cinematic_prompt import (
    CinematicPromptPackage,
    ResolvedCinematicPrompt,
)
from src.models.enriched_scene_prompt import EnrichedScenePrompt
from src.models.google_flow_generation import (
    GoogleFlowReferenceAsset,
    GoogleFlowReferenceRole,
)
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.scene import Scene
from src.models.script_lock import ScriptLock, ScriptProvenance
from src.models.shot_planning import (
    CinematicShotPlan,
    ShotAngle,
    ShotMovement,
    ShotSize,
    ShotSpecification,
)
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.models.visual_continuity import (
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.cinematic_prompt_compilation_service import (
    CinematicPromptCompilationService,
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
        self._cinematic_prompt_compilation_service = CinematicPromptCompilationService()

    def _resolve_reference_assets(
        self, job: VideoJob, scene: Scene
    ) -> list[GoogleFlowReferenceAsset]:
        return self._reference_assets

    def _configured_model_family(self) -> str | None:
        return self._model_family

    def _resolve_sub_clip_prompts(
        self, job: VideoJob, scene: Scene, durations: list[float]
    ) -> list[ResolvedCinematicPrompt] | None:
        if (
            job.cinematic_shot_plan is None
            or job.visual_continuity_bible is None
            or job.script_lock is None
        ):
            return None

        return self._cinematic_prompt_compilation_service.compile_sub_clip_prompts(
            scene=scene,
            shot_plan=job.cinematic_shot_plan,
            visual_continuity_bible=job.visual_continuity_bible,
            production_semantic_brief=job.production_semantic_brief,
            script_lock_hash=job.script_lock.script_content_hash,
            sub_clip_durations=durations,
        )


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

    # Google Flow only generates 4/6/8s clips, so a 6.4s narration is
    # sized up to the next verified length (it is trimmed at assembly).
    assert entry.execution_duration_seconds == 8.0


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


def _split_shot_plan() -> CinematicShotPlan:
    return CinematicShotPlan(
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
                duration_seconds=13.0,
            )
        ],
    )


def _split_bible() -> VisualContinuityBible:
    return VisualContinuityBible(
        script_lock_hash=_SCRIPT_LOCK_HASH,
        identities=[],
        clip_entries=[
            ClipContinuityEntry(
                scene_number=1,
                incoming_state=VisualState(location="a rainy street"),
                shot_action="She hails a taxi.",
                outgoing_state=VisualState(location="inside the taxi"),
                entity_names=[],
            )
        ],
    )


def _split_script_lock() -> ScriptLock:
    return ScriptLock(
        script_version_number=1,
        script_content_hash=_SCRIPT_LOCK_HASH,
        provenance=ScriptProvenance.INTERNAL,
    )


def test_build_entries_returns_a_single_entry_for_a_scene_that_does_not_need_splitting() -> (
    None
):
    service = EnrichedScenePromptService(
        scene_video_generation_service=_FakeSceneVideoGenerationService(),  # type: ignore[arg-type]
    )

    entries = service.build_entries(job=_job(), scene=_scene())

    assert len(entries) == 1
    assert entries[0].clip_sequence_index == 0


def test_build_entries_falls_back_to_a_single_entry_when_split_data_is_unavailable() -> (
    None
):
    """
    A scene whose real narration exceeds the max single-clip duration
    but was planned before shot/continuity/lock data existed must
    still produce one entry (the whole-scene fallback), never raise
    and never silently drop the scene from the Prompts tab.
    """

    scene = _scene()
    scene.real_narration_duration_seconds = 14.0

    service = EnrichedScenePromptService()

    entries = service.build_entries(job=_job(), scene=scene)

    assert len(entries) == 1
    assert entries[0].clip_sequence_index == 0


def test_build_entries_splits_a_scene_whose_narration_exceeds_the_max_duration() -> (
    None
):
    """
    Real-world finding, 2026-09-26: the Prompts tab used to show one
    whole-scene prompt even for a scene that would actually generate
    as multiple sub-clips - this is the split-aware counterpart to
    SceneVideoGenerationService's own _generate_split_scene(), reusing
    the exact same compile_sub_clip_prompts() output so what the user
    reads here matches what a real automated submission would send.
    """

    scene = _scene()
    scene.real_narration_duration_seconds = 14.0

    job = _job(
        cinematic_shot_plan=_split_shot_plan(),
        visual_continuity_bible=_split_bible(),
        script_lock=_split_script_lock(),
    )

    service = EnrichedScenePromptService(
        scene_video_generation_service=_FakeSceneVideoGenerationService(),  # type: ignore[arg-type]
    )

    entries = service.build_entries(job=job, scene=scene)

    assert len(entries) == 2
    assert [entry.clip_sequence_index for entry in entries] == [0, 1]
    assert [entry.execution_duration_seconds for entry in entries] == [8.0, 8.0]
    assert entries[0].base_prompt_text != entries[1].base_prompt_text
    assert "part 1 of 2" in entries[0].base_prompt_text.lower()
    assert "part 2 of 2" in entries[1].base_prompt_text.lower()


# ---------------------------------------------------------------------------
# Provider-aware previews, 2026-10-03: the Prompts/Content tabs must show what
# the project's chosen provider would actually generate - Muse's fixed 10s clip
# trimmed to length vs Google Flow's 4/6/8s clips.
# ---------------------------------------------------------------------------

_MUSE_TRIM_9 = "Also trim the generated 10 seconds video to only 7 seconds video."


def _split_job(provider: VideoProvider) -> VideoJob:
    job = _job(
        cinematic_shot_plan=_split_shot_plan(),
        visual_continuity_bible=_split_bible(),
        script_lock=_split_script_lock(),
    )
    job.video_provider = provider

    return job


def _scene_with_narration(seconds: float) -> Scene:
    scene = _scene()
    scene.real_narration_duration_seconds = seconds

    return scene


def _service(
    *,
    reference_assets: list[GoogleFlowReferenceAsset] | None = None,
    provider_names: dict[str, str] | None = None,
) -> EnrichedScenePromptService:
    return EnrichedScenePromptService(
        scene_video_generation_service=_FakeSceneVideoGenerationService(
            reference_assets=reference_assets
        ),  # type: ignore[arg-type]
        provider_name_for_profile=(
            (lambda profile_id: (provider_names or {}).get(profile_id))
            if provider_names is not None
            else None
        ),
    )


def test_a_flow_project_is_labelled_and_sized_for_google_flow() -> None:
    entry = _service().build_entry(
        job=_split_job(VideoProvider.GOOGLE_FLOW), scene=_scene_with_narration(7.0)
    )

    assert entry.execution_provider_label is not None
    assert "Google Flow" in entry.execution_provider_label
    assert entry.execution_duration_seconds == 8.0
    assert "trim the generated" not in entry.base_prompt_text
    assert "Generates on: Google Flow" in entry.full_text()


def test_a_muse_project_sizes_a_short_scene_to_its_exact_narration_and_asks_muse_to_trim() -> (
    None
):
    """
    Muse always generates 10 seconds, so a 6.4s scene is one clip trimmed
    down, and the prompt carries the explicit trim instruction a real
    submission sends.
    """

    entry = _service().build_entry(
        job=_split_job(VideoProvider.MUSE), scene=_scene_with_narration(6.4)
    )

    assert entry.execution_duration_seconds == 7.0  # 6.4s rounded UP
    assert "Duration: 7 seconds" in entry.base_prompt_text
    assert "trim the generated" not in entry.base_prompt_text
    assert entry.execution_provider_label is not None
    assert "Muse" in entry.execution_provider_label
    assert "Generates on: Muse" in entry.full_text()


def test_a_muse_scene_close_to_ten_seconds_gets_no_trim_instruction() -> None:
    entry = _service().build_entry(
        job=_split_job(VideoProvider.MUSE), scene=_scene_with_narration(9.8)
    )

    assert entry.execution_duration_seconds == 10.0  # 9.8s rounded UP
    assert "trim the generated" not in entry.base_prompt_text


def test_a_nine_second_scene_is_one_clip_on_muse_but_split_on_flow() -> None:
    """The exact disagreement a live project showed: 9s is a single trimmed
    clip for Muse (ceiling 10s) but needs two clips on Flow (ceiling 8s)."""

    muse_entries = _service().build_entries(
        job=_split_job(VideoProvider.MUSE), scene=_scene_with_narration(9.0)
    )
    flow_entries = _service().build_entries(
        job=_split_job(VideoProvider.GOOGLE_FLOW),
        scene=_scene_with_narration(9.0),
    )

    assert len(muse_entries) == 1
    assert muse_entries[0].execution_duration_seconds == 9.0
    assert len(flow_entries) == 2


def test_flow_splits_nine_seconds_into_six_plus_four_with_the_seam_clip_forced_to_eight() -> (
    None
):
    """The plan is 6+4, but Flow silently refuses image ingredients on a
    clip shorter than 8s - and every clip after the first carries the
    previous clip's last frame - so the second is requested at 8s, exactly
    as SceneVideoGenerationService._submit() does."""

    entries = _service().build_entries(
        job=_split_job(VideoProvider.GOOGLE_FLOW), scene=_scene_with_narration(9.0)
    )

    assert [entry.execution_duration_seconds for entry in entries] == [6.0, 8.0]


def test_flow_forces_the_first_clip_to_eight_when_an_identity_reference_exists() -> (
    None
):
    reference = GoogleFlowReferenceAsset(
        source_path="C:/refs/identity.jpg",
        checksum="b" * 64,
        role=GoogleFlowReferenceRole.CHARACTER,
    )

    entries = _service(reference_assets=[reference]).build_entries(
        job=_split_job(VideoProvider.GOOGLE_FLOW), scene=_scene_with_narration(9.0)
    )

    assert [entry.execution_duration_seconds for entry in entries] == [8.0, 8.0]


def test_muse_splits_a_long_scene_evenly_with_exact_lengths_and_trim_instructions() -> (
    None
):
    entries = _service().build_entries(
        job=_split_job(VideoProvider.MUSE), scene=_scene_with_narration(14.0)
    )

    assert [entry.execution_duration_seconds for entry in entries] == [7.0, 7.0]
    assert all(
        "Duration: 7 seconds" in entry.base_prompt_text
        and "trim the generated" not in entry.base_prompt_text
        for entry in entries
    )
    assert "part 1 of 2" in entries[0].base_prompt_text.lower()


def test_a_scene_pinned_to_a_muse_account_uses_muse_rules_in_a_flow_project() -> None:
    scene = _scene_with_narration(6.4)
    scene.preferred_profile_id = "muse.primary"

    entry = _service(provider_names={"muse.primary": "Muse"}).build_entry(
        job=_split_job(VideoProvider.GOOGLE_FLOW), scene=scene
    )

    assert entry.execution_duration_seconds == 7.0
    assert "Muse" in (entry.execution_provider_label or "")


def test_a_scene_pinned_to_a_flow_account_uses_flow_rules_in_a_muse_project() -> None:
    scene = _scene_with_narration(6.4)
    scene.preferred_profile_id = "flow.primary"

    entry = _service(provider_names={"flow.primary": "Google Flow"}).build_entry(
        job=_split_job(VideoProvider.MUSE), scene=scene
    )

    assert entry.execution_duration_seconds == 8.0
    assert "Google Flow" in (entry.execution_provider_label or "")


def test_an_unresolvable_pinned_account_falls_back_to_the_projects_provider() -> None:
    scene = _scene_with_narration(6.4)
    scene.preferred_profile_id = "deleted.account"

    entry = _service(provider_names={}).build_entry(
        job=_split_job(VideoProvider.MUSE), scene=scene
    )

    assert "Muse" in (entry.execution_provider_label or "")
