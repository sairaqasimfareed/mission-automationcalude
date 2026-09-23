from __future__ import annotations


def resolve_title_card_text(
    *,
    override: str | None,
    selected_seo_title: str | None,
    topic: str,
) -> str:
    """
    REQ-4 (opening title card): resolve the real text shown on the
    title card's title beat.

    Resolution order: override (VideoJob.title_card_text, a real,
    explicit per-project choice) wins unconditionally when set;
    otherwise selected_seo_title (SEOPackage.selected_title, when one
    has already been generated for this job - real, deliberately NOT
    an embedded VideoJob field, so this function takes it as a plain
    parameter rather than reaching into job-store lookups itself);
    otherwise topic (VideoJob's own always-populated field).

    A blank/whitespace-only override or selected_seo_title falls
    through to the next source rather than showing empty text on the
    card - the same reason existing_selected_seo_title only helps when
    it is a real string, not the SEOPackage's own default/unset state.

    Deliberately a plain function, not a method on whatever the
    title-card render service ends up being - this is a thin,
    independently testable resolution step, same established pattern
    as filter_audio_timeline_for_mux()/clamp_to_verified_duration().
    """

    for candidate in (override, selected_seo_title, topic):
        if candidate is not None and candidate.strip():
            return candidate.strip()

    return topic.strip()
