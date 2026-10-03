"""
Muse reply identification, 2026-10-03: the in-page check that decides whether a
video sits AFTER the chat message holding this attempt's own prompt. The fakes
in test_muse_real_adapter.py cannot prove the JavaScript itself, so this runs it
in a real Chromium against a page shaped like Muse's chat (one
[data-message-item] container per turn, each with a <video> in a reply).

Reproduces the live failure: scene 1's video sits ABOVE scene 2's prompt but is
the one whose src loads late.
"""

from __future__ import annotations

import pytest

from src.models.muse_generation import MuseGenerationAttempt, MuseGenerationRequest
from src.providers.muse.real_adapter import MuseRealUIAdapter

sync_api = pytest.importorskip("playwright.sync_api")

_SCENE_ONE_PROMPT = (
    "Identity: honey in a kitchen. Environment: Kitchen. Lighting: warm. "
    "Also trim the generated 10 seconds video to only 8 seconds video."
)
_SCENE_TWO_PROMPT = (
    "Identity: honey in a kitchen. Environment: Kitchen. Lighting: warm. "
    "Also trim the generated 10 seconds video to only 1 seconds video."
)

# Scene 2's prompt as the page shows it: same words, but with the line breaks and
# runs of spaces a chat bubble introduces - the check normalises whitespace.
_SCENE_TWO_AS_RENDERED = _SCENE_TWO_PROMPT.replace(". ", ".\n      ").replace(
    "Also trim", "Also    trim"
)

_CHAT_HTML = f"""
<html><body>
  <div data-message-item><p>{_SCENE_ONE_PROMPT}</p></div>
  <div data-message-item><video id="one" src="blob:https://muse.ai/one"></video></div>
  <div data-message-item><p>{_SCENE_TWO_AS_RENDERED}</p></div>
  <div data-message-item><video id="two" src="blob:https://muse.ai/two"></video></div>
</body></html>
"""


@pytest.fixture(scope="module")
def page():  # type: ignore[no-untyped-def]
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception:  # noqa: BLE001 - no browser installed on this machine
            try:
                browser = playwright.chromium.launch(channel="chrome")
            except Exception:  # noqa: BLE001
                pytest.skip("No Chromium/Chrome available to run the page script.")

        page = browser.new_page()
        page.set_content(_CHAT_HTML)

        yield page

        browser.close()


def _attempt(prompt: str) -> MuseGenerationAttempt:
    request = MuseGenerationRequest(
        scene_number=2,
        prompt=prompt,
        prompt_version="v1",
        profile_id="muse.primary",
        idempotency_key="req-2",
    )

    return MuseGenerationAttempt(request=request, profile_id=request.profile_id)


def _check(page, video_id: str, prompt: str) -> bool:  # type: ignore[no-untyped-def]
    adapter = MuseRealUIAdapter.__new__(MuseRealUIAdapter)

    return adapter._follows_submitted_prompt(  # noqa: SLF001
        page.locator(f"#{video_id}"), _attempt(prompt)
    )


def test_an_earlier_scenes_video_does_not_follow_scene_twos_prompt(page) -> None:  # type: ignore[no-untyped-def]
    assert _check(page, "one", _SCENE_TWO_PROMPT) is False


def test_the_video_after_scene_twos_prompt_does(page) -> None:  # type: ignore[no-untyped-def]
    assert _check(page, "two", _SCENE_TWO_PROMPT) is True


def test_scene_ones_own_video_follows_scene_ones_prompt(page) -> None:  # type: ignore[no-untyped-def]
    """Same page, other attempt: the tail (8 seconds vs 1 seconds) is what tells
    the two scenes' otherwise identical prompts apart."""

    assert _check(page, "one", _SCENE_ONE_PROMPT) is True


def test_a_prompt_that_is_not_on_the_page_is_not_a_reason_to_stall(page) -> None:  # type: ignore[no-untyped-def]
    assert _check(page, "two", "A prompt that was never sent to this page.") is True
