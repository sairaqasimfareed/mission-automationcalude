from src.agents.scene_planner.agent import ScenePlannerAgent
from src.models.media_strategy import SceneSourceType
from src.models.scene import SceneStatus
from src.models.script import Script, ScriptStatus

script = Script(
    title="Top 10 Hidden Underground Cities",
    content=(
        "Beneath ordinary streets, entire cities once existed in silence. "
        "These hidden spaces protected communities from invasion. "
        "Some included homes, tunnels, and food storage."
    ),
    prompt_version="script_prompt_v1.0.0",
    word_count=22,
    estimated_duration_seconds=10,
    status=ScriptStatus.APPROVED,
)

agent = ScenePlannerAgent()
scenes = agent.plan(script)

print("Total scenes:", len(scenes))

for scene in scenes:
    print(
        scene.scene_number,
        scene.title,
        scene.status,
        scene.estimated_duration_seconds,
    )

assert len(scenes) == 3
assert all(scene.status == SceneStatus.READY for scene in scenes)


# --- External audit fix: genre-based default acquisition route ---
# Post-Script-Approval Production Plan Phase 6: "Apply route defaults
# by project/genre with per-clip override." No genre_id given -
# preserves the exact prior MANUAL_UPLOAD-uniform behavior rather than
# guessing a genre.
assert all(scene.source_type == SceneSourceType.MANUAL_UPLOAD for scene in scenes)
assert all(scene.stock_query is None for scene in scenes)

# genre.documentary's real default is STOCK_FOOTAGE (real-world
# footage genres) - Scene's own validator requires a non-empty
# stock_query whenever source_type is STOCK_FOOTAGE, so this also
# proves a real value is supplied, not just the enum flipped.
documentary_scenes = agent.plan(script, genre_id="genre.documentary")

assert all(
    scene.source_type == SceneSourceType.STOCK_FOOTAGE for scene in documentary_scenes
)
assert all(scene.stock_query == scene.visual_prompt for scene in documentary_scenes)

# genre.horror's real default is MANUAL_UPLOAD (staged/dramatized
# content) - an unknown genre_id falls back to genre.default, also
# MANUAL_UPLOAD.
horror_scenes = agent.plan(script, genre_id="genre.horror")
unknown_genre_scenes = agent.plan(script, genre_id="genre.not_a_real_genre")

assert all(
    scene.source_type == SceneSourceType.MANUAL_UPLOAD for scene in horror_scenes
)
assert all(
    scene.source_type == SceneSourceType.MANUAL_UPLOAD for scene in unknown_genre_scenes
)

print("Scene Planner Agent tests completed successfully.")


# --- 2026-09-11 real fix, found live: plan() used to split on every
# literal "." (script.content.split(".")), which shattered anything
# but a bare sentence-ending period - a real script containing
# "11:47 p.m." produced real scene fragments like "O." and
# ")**\n\nIt's 11:47 p.". ---


def test_plan_no_longer_produces_single_letter_or_mid_word_fragments() -> None:
    """
    The regex split (requires trailing whitespace after ./!/?) is not
    full sentence-boundary detection - "p.m." followed by a space
    still counts as a split point, same as _subdivide_segment()'s own
    accepted, already-established behavior elsewhere in this file.
    What it genuinely fixes, verified here, is the old bug's real
    failure mode: script.content.split(".") split on *every* literal
    period, including ones with no trailing whitespace at all (mid-
    abbreviation, mid-markdown), producing single-letter fragments
    like "O." and mid-word truncations like "...p.".
    """

    abbreviation_script = Script(
        title="Midnight Knock",
        content=(
            "It's 11:47 p.m. and the house is silent. "
            "No one expects what happens next."
        ),
        prompt_version="script_prompt_v1.0.0",
        word_count=15,
        estimated_duration_seconds=8,
        status=ScriptStatus.APPROVED,
    )

    scenes = ScenePlannerAgent().plan(abbreviation_script)

    narrations = [scene.narration for scene in scenes]

    # The old bug's exact failure signatures - a lone "O." fragment or
    # a period-truncated "...p." with nothing after it - must never
    # appear again. Every real fragment here is at least a real,
    # multi-word clause.
    assert not any(narration.strip() == "O." for narration in narrations)
    assert all(len(narration.split()) > 1 for narration in narrations)
    assert "".join(narrations).replace(" ", "") == abbreviation_script.content.replace(
        " ", ""
    )


# --- 2026-09-11 real fix, found live: plan() used to assign a flat 8
# seconds to every scene regardless of how long that scene's real
# narration takes to speak. A real, legitimate downstream safety
# check (VoiceDirectiveResolutionService) correctly refused to
# generate voice the moment a real sentence needed more than 8
# seconds. ---


def test_plan_gives_a_long_sentence_more_than_the_eight_second_floor() -> None:
    long_sentence_script = Script(
        title="Midnight Knock",
        content=(
            "Short one. "
            "But here's the unsettling part: some sleep researchers "
            "say a knock like that can occur entirely inside your "
            "own head, a real, harmless condition called Exploding "
            "Head Syndrome."
        ),
        prompt_version="script_prompt_v1.0.0",
        word_count=30,
        estimated_duration_seconds=15,
        status=ScriptStatus.APPROVED,
    )

    scenes = ScenePlannerAgent().plan(long_sentence_script)

    assert len(scenes) == 2
    # A short sentence still gets the real 8-second floor for pacing.
    assert scenes[0].estimated_duration_seconds == 8
    # A long sentence (~28 words, ~12s at 2.3 words/second) must get
    # more than the flat 8-second default it used to always get - the
    # exact real scenario that broke real voice generation live.
    assert scenes[1].estimated_duration_seconds > 8
