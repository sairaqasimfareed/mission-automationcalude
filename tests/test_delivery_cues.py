"""Emotion tags written in a script ([stern] ...): taken out of the text, kept as cues, put back only
for a tag-aware voice request."""

from __future__ import annotations

from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_directives import VoiceDeliveryMode
from src.services.delivery_cues import apply_delivery_cues, extract_delivery_cues
from src.services.elevenlabs_voice_translation_service import (
    ElevenLabsVoiceTranslationService,
)

SCRIPT = (
    "JUDGE: [stern] The court will hear the evidence.\n"
    "[somber] Six days later: death.\n"
    "VOICE (Joan of Arc): [pleading] All I said and revoked, I said for fear of the fire.\n"
    "[VISUAL 4s] A candle flame shivers.\n"
    "The ship was found adrift. [sighs] No one aboard was ever seen again.\n"
)


def test_tags_leave_the_script_text() -> None:
    clean, cues = extract_delivery_cues(SCRIPT)

    assert "[stern]" not in clean and "[somber]" not in clean and "[sighs]" not in clean
    assert "JUDGE: The court will hear the evidence." in clean
    assert "Six days later: death." in clean
    assert "The ship was found adrift. No one aboard was ever seen again." in clean
    assert [cue.tag for cue in cues] == ["stern", "somber", "pleading", "sighs"]


def test_a_visual_line_is_not_a_tag() -> None:
    clean, cues = extract_delivery_cues(SCRIPT)

    assert "[VISUAL 4s] A candle flame shivers." in clean
    assert all(cue.tag != "VISUAL 4s" for cue in cues)


def test_a_text_without_tags_is_unchanged() -> None:
    text = "Just one line.\nAnd another."

    assert extract_delivery_cues(text) == (text, [])


def test_the_tag_goes_back_in_front_of_its_own_words_only() -> None:
    _clean, cues = extract_delivery_cues(SCRIPT)

    assert (
        apply_delivery_cues(
            cues,
            "The ship was found adrift. No one aboard was ever seen again.",
        )
        == "The ship was found adrift. [sighs] No one aboard was ever seen again."
    )
    assert apply_delivery_cues(cues, "A line no tag belongs to.") is None


def _blueprint(**overrides: object) -> ResolvedVoiceBlueprint:
    base: dict[str, object] = dict(
        scene_number=1,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.neutral_narrator",
            resolved_profile_id="voice.neutral_narrator",
            display_name="Neutral Narrator",
        ),
        narration_text="The court will hear the evidence.",
        delivery_narration="[stern] The court will hear the evidence.",
    )
    base.update(overrides)

    return ResolvedVoiceBlueprint(**base)  # type: ignore[arg-type]


def test_a_tag_aware_model_gets_the_written_tag() -> None:
    request = ElevenLabsVoiceTranslationService().translate(
        _blueprint(voice_delivery_mode=VoiceDeliveryMode.EMOTION_TAGS),
        voice_id="v",
    )

    assert request.text == "[stern] The court will hear the evidence."
    assert request.model_id == "eleven_v3"


def test_any_other_model_never_gets_the_tag() -> None:
    request = ElevenLabsVoiceTranslationService().translate(
        _blueprint(voice_delivery_mode=VoiceDeliveryMode.CONTINUITY_STITCHING),
        voice_id="v",
    )

    assert "[" not in request.text
    assert request.text == "The court will hear the evidence."
