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

# What is now ALSO verified, 2026-09-07: a human signed in for real
# (via the manual sign-in bootstrap, src/browser/manual_signin_bootstrap.py)
# and, with an explicit one-time go-ahead, one real prompt was
# genuinely submitted and generated against the real product - the
# full write-up (real accessible names/roles, the real settings
# popover's vocabulary, the real generating/completed/edit-view
# structure) is docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md. The constants
# and GoogleFlowRealAccessibleNames below capture those verified facts
# as real code, not just prose - matching VERIFIED_FLOW_BASE_URL's own
# precedent - but do NOT yet change GoogleFlowUIAdapter's actual
# behavior: the real settings UI is a popover of radio-button groups,
# not the <select> dropdown GoogleFlowLocators/the fake fixture below
# assume, so wiring these in needs new adapter interaction logic (open
# the popover, click the matching radio), not just new locator
# strings - tracked as the next step, not yet built.

VERIFIED_MODEL_FAMILIES: tuple[str, ...] = (
    "Omni 1.1 Flash",
    "Veo 3.1 - Lite",
    "Veo 3.1 - Fast",
    "Veo 3.1 - Quality",
)

# Confirmed by the account owner: their account's unlimited
# (non-credit-metered) generation tier runs on this model, with the
# "Agent" toggle left off - "Omni 1.1 Flash" (the real product's own
# default, and what this session's one real test generation used) is
# metered instead (12 real Google One AI credits for a 360p/8s/x2
# submission).
RECOMMENDED_UNLIMITED_MODEL_FAMILY = "Veo 3.1 - Lite"

VERIFIED_RESOLUTIONS: tuple[str, ...] = ("360p", "720p")
VERIFIED_DURATIONS_SECONDS: tuple[int, ...] = (4, 6, 8, 10)
# How many video variations one submission generates for the same
# prompt - confirmed by the account owner NOT to be a credit
# multiplier by itself; the real settings popover shows one combined
# credit cost for the whole submission (see
# docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 4).
VERIFIED_VARIATION_COUNTS: tuple[int, ...] = (1, 2, 3, 4)
VERIFIED_ASPECT_RATIOS: tuple[str, ...] = ("16:9", "9:16")


class GoogleFlowRealAccessibleNames(BaseModel):
    """
    Real, verified accessible names/roles for the authenticated
    product's actual controls - captured via Playwright's own ARIA
    snapshot (locator.aria_snapshot()) against a real signed-in
    session, never the fake fixture.

    Deliberately a SEPARATE model from GoogleFlowLocators below (whose
    fields remain fixture-only, and are still what
    GoogleFlowUIAdapter's tested logic actually drives) rather than
    overwriting it - wiring these into real adapter behavior is a
    disclosed, tracked next step (see
    docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 8), not done here.
    Each string here is an accessible NAME - pair with Playwright's
    own role= selector syntax or get_by_role(), not raw CSS, except
    prompt_input_css (the prompt box has no ARIA role at all).
    """

    new_project_button: str = "New project"
    open_project_link: str = "Open project"

    # The prompt box is a ProseMirror rich-text editor
    # (<flow-rich-text-editor class="prompt-input">), not a plain
    # <textarea> - it has no ARIA role, so CSS remains the right tool
    # for this one control specifically.
    prompt_input_css: str = ".prompt-input .ProseMirror"
    clear_prompt_button: str = "Clear prompt"
    add_ingredients_button: str = "Add ingredients to the prompt box"
    agent_toggle_button: str = "Agent"
    settings_trigger_button: str = "Settings trigger"
    select_model_family_button: str = "Select model family"
    start_generation_button: str = "Start generation"

    generated_video_thumbnail: str = "Generated video thumbnail"
    download_scene_button: str = "Download scene"
    done_editing_scene_button: str = "Done editing scene"


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
