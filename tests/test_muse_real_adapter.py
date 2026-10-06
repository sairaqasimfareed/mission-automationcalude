from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError

from src.models.muse_generation import (
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
    MuseReferenceAsset,
    MuseReferenceRole,
)
from src.providers.muse.real_adapter import MuseRealUIAdapter
from src.providers.muse_ui_provider import (
    MuseUIOperation,
    MuseUIOperationNotSupportedError,
)

# Same testing philosophy as test_google_flow_real_adapter.py: this
# adapter drives the REAL Muse product, with no local fixture standing
# in for it. These tests verify the adapter's own LOGIC/sequencing
# against small, controlled Playwright-shaped fakes - genuinely
# testing what's testable without a real account, not a substitute for
# real-account verification (still pending - see real_adapter.py's own
# locators.py docstring on which selectors are best-effort).


class _ImmediateFuture:
    def __init__(self, value: Any) -> None:
        self._value = value

    def result(self, timeout: float | None = None) -> Any:
        return self._value


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self.pages: list[_FakePage] = []
        self._page = page

    def new_page(self) -> _FakePage:
        self.pages.append(self._page)
        return self._page


class _FakeWorker:
    """Stands in for FlowBrowserWorker - runs submit() synchronously
    (no real thread, no real Playwright) and always hands back the
    same fake page for a given profile."""

    def __init__(self, page: _FakePage) -> None:
        self._page = page

    def submit(self, fn: Callable[[], Any]) -> _ImmediateFuture:
        return _ImmediateFuture(fn())

    def submit_with_recovery(
        self, fn: Callable[[], Any], *, timeout: float, label: str = ""
    ) -> Any:
        return fn()

    def open_persistent_context_from_worker_thread(
        self, profile_id: str, profile_directory: Path, *, headless: bool
    ) -> _FakeContext:
        return _FakeContext(self._page)

    def evict_context_from_worker_thread(self, profile_id: str) -> None:
        pass


class _FakeLocator:
    """
    srcs (2026-09-30): the video-selector fake needs to represent
    MULTIPLE distinct real elements, each with its own `src` attribute
    - real_adapter.py now identifies "this attempt's own video" by src
    identity, not position/count (see _latest_assistant_video's own
    docstring). None (the default) keeps every OTHER existing fake
    locator (buttons, message box, etc.) working exactly as before -
    .nth() still returns a usable scoped view, and .get_attribute
    ("src") falls back to a stable, per-object-and-index synthetic
    value so a test that only mutates `_count` (the original, simpler
    "a new video appeared" simulation) still produces a genuinely NEW
    value for each newly-added index, without that test needing to
    know about srcs at all.
    """

    def __init__(
        self,
        *,
        count: int = 1,
        input_value: str = "",
        srcs: list[str | None] | None = None,
        follows_prompt: list[bool | None] | None = None,
    ) -> None:
        self._count = count
        self._input_value = input_value
        self.click_calls = 0
        self.hover_calls = 0
        self._srcs = srcs
        # Per-index answer to "does this video sit after the chat message holding
        # the submitted prompt?" - what the real adapter asks the page via
        # evaluate(). None (the default) means every video does, which is how
        # every pre-existing test already behaves. A None ENTRY simulates the
        # prompt message not being found on the page at all.
        self._follows_prompt = follows_prompt
        self.evaluate_anchors: list[str] = []
        self._nth_index: int | None = None
        # Stable across every .nth() call on THIS SAME registered
        # locator (propagated, never reset, in .nth() below) - so two
        # separate .nth(0) calls (e.g. once at submit-time, once later
        # when resolving) produce the SAME synthetic src, matching a
        # real, unchanged video staying unchanged across polls.
        self._owner_id = id(self)
        # Set by _FakePage.register_*() at registration time, and
        # propagated through .nth() below - lets a resolved video
        # locator's own .locator()/.get_by_role() chain (2026-09-30,
        # scoping the download button to this video's own message
        # container) reach back to the same page-level registries
        # every other lookup already uses, without the fake needing to
        # actually model real DOM containment.
        self._page: _FakePage | None = None

    @property
    def first(self) -> _FakeLocator:
        return self

    @property
    def last(self) -> _FakeLocator:
        return self

    def count(self) -> int:
        return len(self._srcs) if self._srcs is not None else self._count

    def nth(self, index: int) -> _FakeLocator:
        scoped = _FakeLocator(count=1, input_value=self._input_value)
        scoped._srcs = self._srcs
        scoped._follows_prompt = self._follows_prompt
        scoped.evaluate_anchors = self.evaluate_anchors  # shared, so tests can read it
        scoped._nth_index = index
        scoped._owner_id = self._owner_id
        scoped._page = self._page

        return scoped

    def get_attribute(self, name: str) -> str | None:
        if name != "src" or self._nth_index is None:
            return None

        if self._srcs is not None:
            return self._srcs[self._nth_index]

        return f"fake-src-{self._owner_id}-{self._nth_index}"

    def evaluate(self, script: str, arg: str | None = None) -> bool | None:
        if arg is not None:
            self.evaluate_anchors.append(arg)

        if self._follows_prompt is None or self._nth_index is None:
            return True

        return self._follows_prompt[self._nth_index]

    def locator(self, selector: str) -> _FakeLocator:
        """
        2026-09-30: real_adapter.py's download() now scopes the
        download-button search to the video's own message container
        via video.locator("xpath=ancestor::..."). This fake does not
        model real DOM containment - it just returns itself, so a
        chained .get_by_role() below can reach back to the SAME
        page-level button registrations every other lookup already
        uses, matching this fake's own established "verify the
        adapter's calls, not real Playwright selector semantics"
        philosophy.
        """

        return self

    def get_by_role(
        self, role: str, name: str | None = None, exact: bool = False
    ) -> _FakeLocator:
        if self._page is None:
            return _MISSING

        return self._page.get_by_role(role, name=name, exact=exact)

    def click(self, timeout: float | None = None) -> None:
        if self.count() == 0:
            raise AssertionError("clicked a locator that should not exist")

        self.click_calls += 1

    def hover(self, timeout: float | None = None) -> None:
        if self.count() == 0:
            raise AssertionError("hovered a locator that should not exist")

        self.hover_calls += 1

    def input_value(self) -> str:
        return self._input_value


_MISSING = _FakeLocator(count=0)


class _FakeFileChooser:
    def __init__(self) -> None:
        self.set_files_calls: list[str] = []

    def set_files(self, files: str) -> None:
        self.set_files_calls.append(files)


class _FakeFileChooserInfo:
    def __init__(self, file_chooser: _FakeFileChooser | None = None) -> None:
        self._file_chooser = file_chooser or _FakeFileChooser()

    @property
    def value(self) -> _FakeFileChooser:
        return self._file_chooser


class _FakeFileChooserContext:
    def __init__(self, info: _FakeFileChooserInfo) -> None:
        self._info = info

    def __enter__(self) -> _FakeFileChooserInfo:
        return self._info

    def __exit__(self, *exc_info: object) -> None:
        return None


class _FakeDownload:
    def __init__(self, *, suggested_filename: str = "scene.mp4") -> None:
        self.suggested_filename = suggested_filename
        self.saved_to: Path | None = None

    def save_as(self, path: str) -> None:
        self.saved_to = Path(path)
        self.saved_to.write_bytes(b"fake real video bytes")


class _FakeDownloadInfo:
    def __init__(self, download: _FakeDownload) -> None:
        self.value = download


class _FakeDownloadContext:
    def __init__(self, download: _FakeDownload) -> None:
        self._download = download

    def __enter__(self) -> _FakeDownloadInfo:
        return _FakeDownloadInfo(self._download)

    def __exit__(self, *exc_info: object) -> None:
        return None


class _FakeKeyboard:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.pressed: list[str] = []

    def type(self, text: str, delay: float | None = None) -> None:
        self.typed.append(text)

    def press(self, key: str) -> None:
        self.pressed.append(key)


class _FakePage:
    def __init__(
        self, *, raise_on_goto: bool = False, raise_on_locator: bool = False
    ) -> None:
        self.url_history: list[str] = []
        self.wait_for_timeout_calls: list[float] = []
        self.download_timeouts: list[float | None] = []
        self.keyboard = _FakeKeyboard()
        self._by_placeholder: dict[str, _FakeLocator] = {}
        self._by_role: dict[tuple[str, str], _FakeLocator] = {}
        self._by_css: dict[str, _FakeLocator] = {}
        self._download = _FakeDownload()
        self._file_chooser_info = _FakeFileChooserInfo()
        self.closed = False
        self._raise_on_goto = raise_on_goto
        self._raise_on_locator = raise_on_locator

    def goto(self, url: str, timeout: float | None = None) -> None:
        if self._raise_on_goto:
            raise PlaywrightError("Target page, context or browser has been closed")

        self.url_history.append(url)

    def is_closed(self) -> bool:
        return self.closed

    def get_by_placeholder(self, text: str) -> _FakeLocator:
        return self._by_placeholder.get(text, _MISSING)

    def get_by_role(
        self, role: str, name: str | None = None, exact: bool = False
    ) -> _FakeLocator:
        return self._by_role.get((role, name or ""), _MISSING)

    def locator(self, selector: str) -> _FakeLocator:
        if self._raise_on_locator:
            raise PlaywrightError("Target page, context or browser has been closed")

        if selector in self._by_css:
            return self._by_css[selector]

        # A src-scoped re-location (e.g. "video:not(...)[src='...']",
        # composed by _latest_assistant_video once an attempt's own
        # video has already been resolved once) reuses whatever was
        # registered for the base video selector it was built from -
        # tests register the base selector once and never need to
        # predict the exact resolved src value themselves. Requires
        # the queried selector to continue with "[src=" specifically
        # (not just any shared string prefix) - "video" must NOT match
        # a query for "video:not([aria-hidden='true'])" just because
        # one happens to start with the other.
        for registered_selector, locator in self._by_css.items():
            if registered_selector and selector.startswith(
                f"{registered_selector}[src="
            ):
                return locator

        return _MISSING

    def wait_for_timeout(self, ms: float) -> None:
        self.wait_for_timeout_calls.append(ms)

    def expect_download(self, timeout: float | None = None) -> _FakeDownloadContext:
        self.download_timeouts.append(timeout)

        return _FakeDownloadContext(self._download)

    def expect_file_chooser(
        self, timeout: float | None = None
    ) -> _FakeFileChooserContext:
        return _FakeFileChooserContext(self._file_chooser_info)

    # --- test setup helpers ---

    def register_placeholder(self, text: str, locator: _FakeLocator) -> None:
        locator._page = self  # noqa: SLF001
        self._by_placeholder[text] = locator

    def register_role(self, role: str, name: str, locator: _FakeLocator) -> None:
        locator._page = self  # noqa: SLF001
        self._by_role[(role, name)] = locator

    def register_css(self, selector: str, locator: _FakeLocator) -> None:
        locator._page = self  # noqa: SLF001
        self._by_css[selector] = locator


def _authenticated_page() -> _FakePage:
    page = _FakePage()
    page.register_placeholder("Message", _FakeLocator())

    return page


def _request(**overrides: object) -> MuseGenerationRequest:
    defaults: dict[str, object] = {
        "scene_number": 1,
        "prompt": "A lighthouse at dusk, waves crashing below.",
        "prompt_version": "v1",
        "profile_id": "muse.primary",
        "idempotency_key": "req-1",
    }
    defaults.update(overrides)
    return MuseGenerationRequest(**defaults)  # type: ignore[arg-type]


def _attempt(request: MuseGenerationRequest) -> MuseGenerationAttempt:
    return MuseGenerationAttempt(request=request, profile_id=request.profile_id)


def _adapter(page: _FakePage, *, tmp_path: Path) -> MuseRealUIAdapter:
    return MuseRealUIAdapter(
        worker=_FakeWorker(page),  # type: ignore[arg-type]
        base_url="https://muse.ai",
        operation_timeout_seconds=5.0,
        download_root=tmp_path,
    )


# --- supported_operations / ensure_supported ---


def test_cancel_or_abandon_is_not_a_declared_supported_operation() -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=Path("unused"))

    assert MuseUIOperation.CANCEL_OR_ABANDON not in adapter.supported_operations


# --- check_profile_health ---


def test_check_profile_health_true_when_message_box_present() -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=Path("unused"))

    assert adapter.check_profile_health("muse.primary") is True


def test_check_profile_health_false_without_message_box() -> None:
    page = _FakePage()
    adapter = _adapter(page, tmp_path=Path("unused"))

    assert adapter.check_profile_health("muse.primary") is False


# --- submit ---


def test_submit_happy_path_types_prompt_and_reaches_generating(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == MuseGenerationState.GENERATING
    assert page.keyboard.typed == [request.prompt]
    assert page.keyboard.pressed == ["Enter"]


def test_submit_reports_ui_changed_when_the_page_is_stale_and_closed(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29: confirmed live -
    "muse.submit | scene=8 | failed after 0.1s | TargetClosedError".
    A cached page can raise on the very first real use (goto()) even
    though nothing here detected it as closed yet - this used to
    happen OUTSIDE submit()'s own try/except (navigation ran before
    the try block even started), so the real exception escaped
    completely uncaught and left the ledger entry frozen at PLANNED
    with zero recorded transitions. It must now be reported as a
    clean, recoverable UI_CHANGED instead.
    """

    page = _FakePage(raise_on_goto=True)
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == MuseGenerationState.UI_CHANGED


def test_submit_reports_auth_required_when_not_authenticated(tmp_path: Path) -> None:
    page = _FakePage()  # no message box registered - not authenticated
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == MuseGenerationState.AUTH_REQUIRED


def test_submit_reports_submission_uncertain_when_message_box_still_has_text(
    tmp_path: Path,
) -> None:
    page = _FakePage()
    page.register_placeholder("Message", _FakeLocator(input_value="still here"))
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == MuseGenerationState.SUBMISSION_UNCERTAIN


def test_submit_attaches_a_reference_image_via_native_file_chooser(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()
    page.register_css('[data-pel-click="chat_tap_attachment"]', _FakeLocator())
    adapter = _adapter(page, tmp_path=tmp_path)

    reference_source = tmp_path / "reference.jpg"
    reference_source.write_bytes(b"fake reference image bytes")
    request = _request(
        reference_assets=[
            MuseReferenceAsset(
                source_path=str(reference_source),
                checksum="abc123",
                role=MuseReferenceRole.CHARACTER,
            )
        ]
    )

    result = adapter.submit(request, _attempt(request))

    assert result.state == MuseGenerationState.GENERATING
    file_chooser = page._file_chooser_info.value
    assert file_chooser.set_files_calls == [str(reference_source)]


def test_submit_reports_ui_changed_when_attach_button_is_missing(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()  # no attach-button selector registered
    adapter = _adapter(page, tmp_path=tmp_path)

    reference_source = tmp_path / "reference.jpg"
    reference_source.write_bytes(b"fake reference image bytes")
    request = _request(
        reference_assets=[
            MuseReferenceAsset(
                source_path=str(reference_source),
                checksum="abc123",
                role=MuseReferenceRole.CHARACTER,
            )
        ]
    )

    result = adapter.submit(request, _attempt(request))

    assert result.state == MuseGenerationState.UI_CHANGED
    assert page.keyboard.typed == []  # never proceeded to type the prompt


class _AppearsAfterPolls(_FakeLocator):
    """A control that is absent for the first `polls` looks, then present - how the
    "+" button behaves at full window width, where the page keeps drawing after
    it has loaded."""

    def __init__(self, polls: int) -> None:
        super().__init__()
        self._remaining = polls
        self.looks = 0

    def count(self) -> int:
        self.looks += 1

        if self._remaining > 0:
            self._remaining -= 1

            return 0

        return 1


def _reference_request(tmp_path: Path):  # type: ignore[no-untyped-def]
    reference_source = tmp_path / "reference.jpg"
    reference_source.write_bytes(b"fake reference image bytes")

    return reference_source, _request(
        reference_assets=[
            MuseReferenceAsset(
                source_path=str(reference_source),
                checksum="abc123",
                role=MuseReferenceRole.CHARACTER,
            )
        ]
    )


def test_a_attach_button_that_appears_a_moment_late_is_waited_for(
    tmp_path: Path,
) -> None:
    """Live, 2026-10-06: at full window width the page was still drawing after it
    loaded; the "+" button was on screen seconds later but a one-shot check had
    already declared it missing and stopped scene 2."""

    page = _authenticated_page()
    late_button = _AppearsAfterPolls(polls=6)
    page.register_css('[data-pel-click="chat_tap_attachment"]', late_button)
    adapter = _adapter(page, tmp_path=tmp_path)
    source, request = _reference_request(tmp_path)

    result = adapter.submit(request, _attempt(request))

    assert result.state == MuseGenerationState.GENERATING
    assert late_button.looks > 6  # it kept looking until the button arrived
    assert page.keyboard.typed  # and then went on to type the prompt


def test_the_wait_for_the_attach_button_is_bounded(tmp_path: Path) -> None:
    """It waits, but not forever: a button that never appears still stops the
    submission before anything is typed (no reference, no send)."""

    page = _authenticated_page()  # no attach button registered
    adapter = _adapter(page, tmp_path=tmp_path)
    source, request = _reference_request(tmp_path)

    result = adapter.submit(request, _attempt(request))

    assert result.state == MuseGenerationState.UI_CHANGED
    assert "did not appear within 20s" in (result.state_history[-1].detail or "")
    assert page.keyboard.typed == []
    # polled in half-second steps up to the limit, not one instant check
    assert len(page.wait_for_timeout_calls) >= 40


def test_a_message_box_that_appears_a_moment_late_is_waited_for(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()
    late_box = _AppearsAfterPolls(polls=4)
    page.register_placeholder("Message", late_box)
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == MuseGenerationState.GENERATING
    assert late_box.looks > 4


# --- observe ---


def test_observe_keeps_polling_while_no_video_exists(tmp_path: Path) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    result = adapter.observe(submitted)

    assert result.state == MuseGenerationState.GENERATING


def test_observe_reports_ready_to_download_once_a_video_appears(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    page.register_css("video:not([aria-hidden='true'])", _FakeLocator())

    result = adapter.observe(submitted)

    assert result.state == MuseGenerationState.READY_TO_DOWNLOAD


def test_observe_does_not_report_ready_from_a_previous_scenes_leftover_video(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29: Muse reuses one continuous chat
    thread across every scene - a previous scene's own completed reply
    video is still on the page, unchanged, while a new scene's prompt
    is generating. The very first poll after submitting must not treat
    that leftover video as this attempt's own reply just because it is
    still "the last video on the page" - only a video count that has
    grown PAST what existed right before this prompt was sent counts.
    """

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)

    # A previous scene's reply video is already on the page BEFORE
    # this attempt is even submitted.
    leftover_video = _FakeLocator(count=1)
    page.register_css("video:not([aria-hidden='true'])", leftover_video)

    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    result = adapter.observe(submitted)

    assert result.state == MuseGenerationState.GENERATING  # not fooled


def test_observe_reports_ready_once_a_new_video_appears_past_the_baseline(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)

    leftover_video = _FakeLocator(count=1)
    page.register_css("video:not([aria-hidden='true'])", leftover_video)

    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    # This attempt's own reply has now actually rendered - the video
    # count on the page has grown past the pre-submit baseline of 1.
    leftover_video._count = 2  # noqa: SLF001

    result = adapter.observe(submitted)

    assert result.state == MuseGenerationState.READY_TO_DOWNLOAD


def test_observe_does_not_report_ready_for_a_video_still_missing_its_src(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-30: under a slow network connection, a
    genuinely NEW <video> element can exist in the DOM (so a naive
    count-based check alone would already see "a new video") while its
    own content is still loading - visually "a picture box without a
    download button", confirmed directly in a real Generate All run.
    A video whose own src is still empty/unset must never be treated
    as this attempt's own ready reply, even though the count already
    grew past the submit-time baseline.
    """

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)

    videos = _FakeLocator(srcs=["blob:https://muse.ai/older-video"])
    page.register_css("video:not([aria-hidden='true'])", videos)

    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    # A new <video> element has appeared (count grew from 1 to 2), but
    # its own src is still unset - Muse has not finished loading it.
    videos._srcs = ["blob:https://muse.ai/older-video", None]  # noqa: SLF001

    result = adapter.observe(submitted)

    assert result.state == MuseGenerationState.GENERATING  # not fooled


def test_observe_reports_ready_once_the_placeholder_video_gets_a_real_src(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)

    videos = _FakeLocator(srcs=["blob:https://muse.ai/older-video"])
    page.register_css("video:not([aria-hidden='true'])", videos)

    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    # Still loading on the first poll...
    videos._srcs = ["blob:https://muse.ai/older-video", None]  # noqa: SLF001
    still_generating = adapter.observe(submitted)
    assert still_generating.state == MuseGenerationState.GENERATING

    # ...and has now genuinely finished loading.
    videos._srcs = [  # noqa: SLF001
        "blob:https://muse.ai/older-video",
        "blob:https://muse.ai/this-attempts-own-video",
    ]
    result = adapter.observe(still_generating)

    assert result.state == MuseGenerationState.READY_TO_DOWNLOAD


def test_download_reuses_the_resolved_video_even_if_more_videos_appear_later(
    tmp_path: Path,
) -> None:
    """
    Once observe() has confidently identified this attempt's own video
    (by its stable src), download() must re-locate that EXACT same
    element - never re-guess "the last one" - even if yet another,
    even newer video has appeared on the page in between (e.g. a
    different scene's own reply arriving out of order, or the DOM
    reordering after a real Chromium crash+restore).
    """

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)

    videos = _FakeLocator(srcs=["blob:https://muse.ai/older-video"])
    page.register_css("video:not([aria-hidden='true'])", videos)
    page.register_role("button", "Download", _FakeLocator())

    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    videos._srcs = [  # noqa: SLF001
        "blob:https://muse.ai/older-video",
        "blob:https://muse.ai/this-attempts-own-video",
    ]
    ready = adapter.observe(submitted)
    assert ready.state == MuseGenerationState.READY_TO_DOWNLOAD

    # A THIRD, even newer video shows up before download() runs - must
    # not confuse which one this attempt's own reply actually is.
    videos._srcs = [  # noqa: SLF001
        "blob:https://muse.ai/older-video",
        "blob:https://muse.ai/this-attempts-own-video",
        "blob:https://muse.ai/a-later-unrelated-scenes-video",
    ]

    downloaded = adapter.download(ready)

    assert downloaded.state == MuseGenerationState.DOWNLOADED


def test_download_refuses_a_previous_scenes_leftover_video(tmp_path: Path) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)

    leftover_video = _FakeLocator(count=1)
    page.register_css("video:not([aria-hidden='true'])", leftover_video)

    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    result = adapter.download(submitted)

    assert result.state == MuseGenerationState.UI_CHANGED
    assert leftover_video.hover_calls == 0  # never touched the wrong video


def test_observe_reports_ui_changed_when_the_page_goes_stale_mid_poll(
    tmp_path: Path,
) -> None:
    """Same TargetClosedError-class real-world finding as submit()'s
    own test - a cached page can go stale BETWEEN a successful submit
    and a later poll, not only during submit() itself."""

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    page._raise_on_locator = True  # noqa: SLF001

    result = adapter.observe(submitted)

    assert result.state == MuseGenerationState.UI_CHANGED


def test_observe_ignores_a_decorative_avatar_video_elsewhere_on_the_page(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-29: Muse's own UI renders a decorative,
    aria-hidden <video> (avatar chrome, unrelated to any chat message)
    that an unscoped "video" locator's .last could pick over the real
    reply video once it happened to sit later in DOM order - reported
    READY_TO_DOWNLOAD, but download()'s later .hover() on it timed out
    since it is never actually visible. Registering only the
    old, unscoped "video" key (simulating just the decorative element
    being present) must NOT be treated as a real video.
    """

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    page.register_css("video", _FakeLocator())  # the decorative element only

    result = adapter.observe(submitted)

    assert result.state == MuseGenerationState.GENERATING  # still not found


def test_observe_ignores_an_attempt_not_awaiting_generation(tmp_path: Path) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    # Populate the adapter's page cache first (matching a real caller,
    # which always submits/checks health before ever observing) so
    # the "no open page for this profile" branch doesn't fire before
    # the actual state check this test targets.
    adapter.check_profile_health("muse.primary")
    request = _request()
    attempt = _attempt(request)  # still PLANNED

    result = adapter.observe(attempt)

    assert result is attempt


# --- download ---


def test_download_happy_path_saves_the_file(tmp_path: Path) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    page.register_css("video:not([aria-hidden='true'])", _FakeLocator())
    page.register_role("button", "Download", _FakeLocator())

    ready = adapter.observe(submitted)
    downloaded = adapter.download(ready)

    assert downloaded.state == MuseGenerationState.DOWNLOADED
    assert downloaded.downloaded_file is not None
    assert Path(downloaded.downloaded_file).exists()


def test_download_allows_a_slow_start_before_giving_up(tmp_path: Path) -> None:
    """Live, 2026-10-06: scene 11's video was ready but its download only began
    after more than the old 30s allowance, so the attempt was failed and blocked
    the account. The download-start budget must be far longer than a normal
    click's."""

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))
    page.register_css("video:not([aria-hidden='true'])", _FakeLocator())
    page.register_role("button", "Download", _FakeLocator())

    adapter.download(adapter.observe(submitted))

    assert page.download_timeouts == [180_000.0]


def test_download_reports_ui_changed_when_no_video_is_present(tmp_path: Path) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    result = adapter.download(submitted)

    assert result.state == MuseGenerationState.UI_CHANGED


def test_download_reports_ui_changed_when_the_page_goes_stale(tmp_path: Path) -> None:
    """Same TargetClosedError-class real-world finding as submit()'s/
    observe()'s own tests - a cached page can go stale before
    download() ever gets to use it."""

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    page.register_css("video:not([aria-hidden='true'])", _FakeLocator())
    ready = adapter.observe(submitted)

    page._raise_on_locator = True  # noqa: SLF001

    result = adapter.download(ready)

    assert result.state == MuseGenerationState.UI_CHANGED


def test_download_reports_ui_changed_when_hover_reveals_no_download_control(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    page.register_css("video:not([aria-hidden='true'])", _FakeLocator())
    # No "Download" button registered.

    result = adapter.download(submitted)

    assert result.state == MuseGenerationState.UI_CHANGED


# --- cancel_or_abandon ---


def test_cancel_or_abandon_is_never_supported(tmp_path: Path) -> None:
    """
    Matches Google Flow's real adapter exactly: cancel_or_abandon is
    deliberately excluded from supported_operations, since
    MuseGenerationOrchestratorService.abandon_attempt() marks a stuck
    attempt FAILED directly on the ledger and never calls through to
    the provider at all.
    """

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    with pytest.raises(MuseUIOperationNotSupportedError):
        adapter.cancel_or_abandon(submitted)


# --- a reply must FOLLOW this attempt's own prompt (2026-10-03) ---

_OLD = "blob:https://muse.ai/scene-one-video"
_NEW = "blob:https://muse.ai/scene-two-video"
_VIDEO_CSS = "video:not([aria-hidden='true'])"


def test_a_leftover_video_that_loads_its_src_late_is_not_taken_for_this_attempt(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-10-03: while scene 2 generated, Muse's window
    scrolled up and scene 1's video (which had no loaded src when scene 2 was
    submitted) loaded it. It was not in the set of srcs known at submit, so it
    looked brand new - and scene 1's video was downloaded again for scene 2.
    It sits BEFORE scene 2's own prompt in the thread, so it must be ignored.
    """

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    videos = _FakeLocator(srcs=[None])  # scene 1's video: present but no src yet
    page.register_css(_VIDEO_CSS, videos)

    request = _request(scene_number=2)
    submitted = adapter.submit(request, _attempt(request))

    # The window scrolls up: scene 1's video now has a src. It is not "known"
    # (it had none at submit) and it is the only video - but it precedes the
    # prompt, so it cannot be this attempt's reply.
    videos._srcs = [_OLD]  # noqa: SLF001
    videos._follows_prompt = [False]  # noqa: SLF001

    result = adapter.observe(submitted)

    assert result.state == MuseGenerationState.GENERATING  # not fooled


def test_the_video_after_the_prompt_is_chosen_even_with_an_older_one_loaded_too(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    videos = _FakeLocator(srcs=[None])
    page.register_css(_VIDEO_CSS, videos)

    request = _request(scene_number=2)
    submitted = adapter.submit(request, _attempt(request))

    videos._srcs = [_OLD, _NEW]  # noqa: SLF001
    videos._follows_prompt = [False, True]  # noqa: SLF001

    result = adapter.observe(submitted)

    assert result.state == MuseGenerationState.READY_TO_DOWNLOAD
    assert adapter._resolved_video_src[str(submitted.id)] == _NEW  # noqa: SLF001


def test_download_never_picks_the_earlier_scenes_video(tmp_path: Path) -> None:
    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    videos = _FakeLocator(srcs=[None])
    page.register_css(_VIDEO_CSS, videos)

    request = _request(scene_number=2)
    submitted = adapter.submit(request, _attempt(request))
    videos._srcs = [_OLD]  # noqa: SLF001
    videos._follows_prompt = [False]  # noqa: SLF001

    result = adapter.download(submitted)

    assert result.state == MuseGenerationState.UI_CHANGED
    assert result.downloaded_file is None


def test_the_check_matches_on_the_end_of_the_prompt_not_its_shared_head(
    tmp_path: Path,
) -> None:
    """Every scene's prompt opens with the same identity/environment text; the
    tail carries the scene's own duration, so that is what identifies it."""

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    videos = _FakeLocator(srcs=[None])
    page.register_css(_VIDEO_CSS, videos)

    prompt = (
        "Identity: The script states that honey may be in the kitchen. "
        "Environment: Kitchen.\n\nAlso trim the generated 10 seconds video "
        "to only 1 seconds video."
    )
    request = _request(scene_number=2, prompt=prompt)
    submitted = adapter.submit(request, _attempt(request))
    videos._srcs = [_NEW]  # noqa: SLF001
    adapter.observe(submitted)

    anchor = videos.evaluate_anchors

    # Whitespace is normalised and only the END of the prompt is used.
    assert anchor
    assert anchor[-1].endswith("only 1 seconds video.")
    assert "Identity" not in anchor[-1]


def test_if_the_prompt_message_cannot_be_found_the_old_src_logic_still_applies(
    tmp_path: Path,
) -> None:
    """Skipping the check (not stalling forever) when the page gives nothing
    to anchor on; the duplicate-download guard downstream still applies."""

    page = _authenticated_page()
    adapter = _adapter(page, tmp_path=tmp_path)
    videos = _FakeLocator(srcs=[None])
    page.register_css(_VIDEO_CSS, videos)

    request = _request(scene_number=2)
    submitted = adapter.submit(request, _attempt(request))
    videos._srcs = [_NEW]  # noqa: SLF001
    videos._follows_prompt = [None]  # noqa: SLF001

    assert adapter.observe(submitted).state == MuseGenerationState.READY_TO_DOWNLOAD
