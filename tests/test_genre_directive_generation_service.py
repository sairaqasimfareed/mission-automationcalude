from __future__ import annotations

from src.models.editing_directives import (
    CameraDirective,
    MusicDirective,
    SceneEditingDirectives,
    SoundEffectDirective,
    SubtitleDirective,
    TransitionDirective,
    VisualEffectDirective,
)
from src.models.scene import (
    Scene,
    SceneStatus,
)
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)

registry = GenreProfileRegistryService.with_default_profiles()

service = GenreDirectiveGenerationService(
    genre_registry=registry,
)


horror_scene = Scene(
    scene_number=1,
    title="The Locked Door",
    narration=("A locked wooden door slowly " "opens in the darkness."),
    visual_prompt=("Dark hallway with an old " "wooden door"),
    estimated_duration_seconds=8,
    status=SceneStatus.READY,
)

horror_directives = service.generate(
    scene=horror_scene,
    genre_id="genre.horror",
)

print(
    "Generated genre:",
    horror_directives.genre_preset_id,
)

print(
    "Generated camera:",
    horror_directives.camera.preset_id,
)

print(
    "Generated effects:",
    horror_directives.active_effect_count,
)

assert horror_directives.scene_number == 1

assert horror_directives.genre_preset_id == "genre.horror"

assert horror_directives.camera.preset_id == "camera.slow_zoom_in"

assert horror_directives.camera.end_offset_seconds == 8.0

assert horror_directives.transition_in.preset_id == "transition.fade_black"

assert horror_directives.transition_in.duration_seconds == 0.8

assert horror_directives.music.preset_id == "music.horror_low_drone"

assert horror_directives.music.enabled is True

assert len(horror_directives.visual_effects) == 3

assert len(horror_directives.animations) == 2

assert len(horror_directives.sound_effects) == 2

assert horror_directives.sound_effects[0].relative_position_percent is not None

assert horror_directives.subtitles.preset_id == "subtitle.cinematic"

assert horror_directives.metadata["generated_from_genre_profile"] is True


override_directives = SceneEditingDirectives(
    scene_number=1,
    camera=CameraDirective(
        preset_id="camera.none",
        zoom_start=1.0,
        zoom_end=1.15,
        end_offset_seconds=8.0,
    ),
    transition_out=TransitionDirective(
        preset_id="transition.cut",
        duration_seconds=0.0,
    ),
    visual_effects=[
        VisualEffectDirective(
            preset_id="visual.vignette_soft",
            enabled=False,
        ),
    ],
    music=MusicDirective(
        preset_id="music.none",
        enabled=False,
        volume_percent=0.0,
    ),
    sound_effects=[
        SoundEffectDirective(
            preset_id="sfx.door_creak",
            start_offset_seconds=6.5,
            volume_percent=85.0,
        ),
    ],
    subtitles=SubtitleDirective(
        preset_id="subtitle.default",
        maximum_words_per_line=6,
    ),
    metadata={
        "override_source": ("script_scene_directive"),
    },
)

overridden = service.generate(
    scene=horror_scene,
    genre_id="genre.horror",
    overrides=override_directives,
)

assert overridden.camera.preset_id == "camera.none"

assert overridden.camera.zoom_end == 1.15

assert overridden.music.enabled is False
assert overridden.music.volume_percent == 0.0

door_creak = next(
    effect
    for effect in overridden.sound_effects
    if (effect.preset_id == "sfx.door_creak")
)

assert door_creak.start_offset_seconds == 6.5
assert door_creak.volume_percent == 85.0

vignette = next(
    effect
    for effect in overridden.visual_effects
    if (effect.preset_id == "visual.vignette_soft")
)

assert vignette.enabled is False

assert overridden.subtitles.maximum_words_per_line == 6

assert overridden.metadata["scene_overrides_applied"] is True

assert overridden.metadata["override_source"] == "script_scene_directive"


unknown_genre_directives = service.generate(
    scene=Scene(
        scene_number=2,
        title="Unknown Genre Scene",
        narration="Neutral narration.",
        visual_prompt="Neutral visual",
        estimated_duration_seconds=6,
        status=SceneStatus.READY,
    ),
    genre_id="genre.not_registered",
)

assert unknown_genre_directives.genre_preset_id == "genre.default"

assert unknown_genre_directives.metadata["genre_fallback_used"] is True

assert unknown_genre_directives.warnings


scenes = [
    Scene(
        scene_number=3,
        title="Third Scene",
        narration="Third narration.",
        visual_prompt="Third visual.",
        estimated_duration_seconds=5,
        status=SceneStatus.READY,
    ),
    Scene(
        scene_number=1,
        title="First Scene",
        narration="First narration.",
        visual_prompt="First visual.",
        estimated_duration_seconds=7,
        status=SceneStatus.READY,
    ),
    Scene(
        scene_number=2,
        title="Second Scene",
        narration="Second narration.",
        visual_prompt="Second visual.",
        estimated_duration_seconds=6,
        status=SceneStatus.READY,
    ),
]

generated_many = service.generate_many(
    scenes=scenes,
    genre_id="genre.documentary",
)

assert [directives.scene_number for directives in generated_many] == [
    1,
    2,
    3,
]

assert all(
    directives.genre_preset_id == "genre.documentary" for directives in generated_many
)


try:
    service.apply_overrides(
        base=horror_directives,
        overrides=SceneEditingDirectives(
            scene_number=99,
        ),
    )
except ValueError:
    print("Mismatched override scene " "successfully blocked.")
else:
    raise AssertionError("Override scene mismatch should fail.")


try:
    service.generate_many(
        scenes=[
            horror_scene,
            horror_scene,
        ],
        genre_id="genre.horror",
    )
except ValueError:
    print("Duplicate scene generation " "successfully blocked.")
else:
    raise AssertionError("Duplicate scenes should fail.")


print("Genre Directive Generation Service " "tests completed successfully.")
