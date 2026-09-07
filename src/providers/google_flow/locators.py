from __future__ import annotations

from pydantic import BaseModel

# GF-4/section 15, "Settings mapping": "Keep the mapping between
# canonical execution settings and visible Flow controls inside the
# Google Flow adapter/settings module. Do not leak UI labels
# throughout the application."
#
# IMPORTANT, read before ever pointing this at the real product: every
# selector below targets tests/fixtures/fake_flow_ui.html, a local
# fixture built for this initiative's own fake-Flow test harness
# (GF-16) - NOT Google Flow's real, current DOM. These defaults exist
# so GoogleFlowUIAdapter's actual logic (preflight, settings
# verification, prompt insertion, analyze/confirm handling, UI_CHANGED
# detection) is genuinely exercised against a real running browser
# instead of shipping completely untested. Before any real-account use
# (GF-17), construct a GoogleFlowLocators instance pointed at Google
# Flow's real, verified selectors - prefer semantic roles/accessible
# names/stable visible text over raw CSS selectors when doing so, per
# this phase's own guidance.
#
# What IS now verified, by actually visiting the public marketing
# page (no login involved - nothing here required or used a
# credential): the real base URL is https://flow.google.com (see
# VERIFIED_FLOW_BASE_URL below); it correctly redirects an
# unauthenticated visitor to Google's own standard OAuth sign-in at
# accounts.google.com, matching this whole initiative's "normal
# browser authentication experience" design exactly. What remains
# unverified: the authenticated app's actual DOM once signed in - that
# needs a human to complete the real Google sign-in themselves (GF-13's
# own Open Login button), which is exactly where the next real step in
# GF-17's certification picks up.
VERIFIED_FLOW_BASE_URL = "https://flow.google.com"


class GoogleFlowLocators(BaseModel):
    """Every selector the Google Flow adapter needs, in one place."""

    auth_required_banner: str = "#auth-required-banner"

    prompt_input: str = "#prompt-input"
    model_family_select: str = "#model-family-select"
    reference_drop_zone: str = "#reference-drop-zone"
    reference_attached_label: str = "#reference-attached-label"
    generate_button: str = "#generate-button"

    analysis_panel: str = "#analysis-panel"
    confirm_button: str = "#confirm-button"

    generation_panel: str = "#generation-panel"

    result_panel: str = "#result-panel"
    result_status: str = "#result-status"
    download_link: str = "#download-link"
