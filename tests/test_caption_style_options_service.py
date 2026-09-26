from __future__ import annotations

from src.services.caption_style_options_service import CaptionStyleOptionsService


def _service() -> CaptionStyleOptionsService:
    return CaptionStyleOptionsService()


def test_list_options_returns_every_registered_subtitle_preset() -> None:
    options = _service().list_options(genre_id="genre.documentary")

    assert {option.preset_id for option in options} == {
        "subtitle.default",
        "subtitle.cinematic",
        "subtitle.bold_punchy",
    }


def test_list_options_marks_the_genres_own_resolved_default() -> None:
    """genre.documentary's own real GenreEditingProfile.
    subtitle_preset_id is subtitle.cinematic - exactly one option must
    be marked as the genre default, and it must be that one, not
    subtitle.default (there is no code-level guarantee that "default"
    is any genre's own real default - it is just this preset's own
    id)."""

    options = _service().list_options(genre_id="genre.documentary")

    defaults = [option for option in options if option.is_genre_default]

    assert len(defaults) == 1
    assert defaults[0].preset_id == "subtitle.cinematic"

    non_defaults = [option for option in options if not option.is_genre_default]
    assert {option.preset_id for option in non_defaults} == {
        "subtitle.default",
        "subtitle.bold_punchy",
    }


def test_list_options_marks_bold_punchy_default_for_genres_that_request_it() -> None:
    """Real-world finding, 2026-09-26: genre.top10/genre.reaction/
    genre.comedy all request subtitle.bold_punchy as their real
    default (REQ-5) - confirmed here via the real genre registry, not
    a synthetic profile, since the actual bug (bold_punchy never
    registered in EffectRegistryService) would have made every one of
    these silently resolve to subtitle.default instead."""

    for genre_id in ("genre.top10", "genre.reaction", "genre.comedy"):
        options = _service().list_options(genre_id=genre_id)

        defaults = [option for option in options if option.is_genre_default]

        assert len(defaults) == 1, genre_id
        assert defaults[0].preset_id == "subtitle.bold_punchy", genre_id


def test_list_options_falls_back_to_default_preset_for_an_unknown_genre() -> None:
    options = _service().list_options(genre_id="genre.does_not_exist")

    defaults = [option for option in options if option.is_genre_default]

    assert len(defaults) == 1
    assert defaults[0].preset_id == "subtitle.default"


def test_list_options_carries_the_real_ffmpeg_style_for_each_preset() -> None:
    """A GUI preview built from option.style must never drift from the
    real renderer's own values - each option's style dict must be the
    real, distinct VideoFilterTranslationService._subtitle_style()
    result for its own preset_id, not a shared/blank placeholder."""

    options = _service().list_options(genre_id="genre.documentary")

    by_preset_id = {option.preset_id: option.style for option in options}

    assert by_preset_id["subtitle.default"]["fontcolor"] == "white"
    assert by_preset_id["subtitle.cinematic"]["fontcolor"] == "white"
    assert by_preset_id["subtitle.bold_punchy"]["fontcolor"] == "yellow"

    # Distinct font sizes confirm these are three real, different
    # styles, not the same dict duplicated across every option.
    sizes = {style["fontsize"] for style in by_preset_id.values()}
    assert len(sizes) == 3
