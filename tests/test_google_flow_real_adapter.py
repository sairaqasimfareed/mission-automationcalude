from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.providers.external_ui_generation_provider import (
    ExternalUIOperation,
    ExternalUIOperationNotSupportedError,
)
from src.providers.google_flow.real_adapter import GoogleFlowRealUIAdapter

# This adapter drives the REAL Google Flow product - there is no local
# fixture standing in for it (unlike GoogleFlowUIAdapter's fake-Flow
# harness), and it must never be exercised against the real product in
# an automated test run. These tests instead verify the adapter's own
# LOGIC/sequencing against small, controlled Playwright-shaped fakes -
# genuinely testing what's testable without a real account, not a
# substitute for real-account verification (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md).


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

    def submit_with_recovery(self, fn: Callable[[], Any], *, timeout: float) -> Any:
        return fn()

    def open_persistent_context_from_worker_thread(
        self, profile_id: str, profile_directory: Path, *, headless: bool
    ) -> _FakeContext:
        return _FakeContext(self._page)


class _SequentialFakeWorker:
    """
    Like _FakeWorker, but hands out a genuinely NEW page (from a
    genuinely new context) on every call - used to verify
    _get_or_open_page() actually asks the worker again for a fresh
    page once its cached one is stale, rather than checking a real
    FlowBrowserWorker recovers from that same situation (that's
    test_flow_browser_worker.py's own, real-Chromium job).
    """

    def __init__(self, pages: list[_FakePage]) -> None:
        self._pages = list(pages)
        self.open_call_count = 0
        self.evict_call_count = 0

    def submit(self, fn: Callable[[], Any]) -> _ImmediateFuture:
        return _ImmediateFuture(fn())

    def submit_with_recovery(self, fn: Callable[[], Any], *, timeout: float) -> Any:
        return fn()

    def open_persistent_context_from_worker_thread(
        self, profile_id: str, profile_directory: Path, *, headless: bool
    ) -> _FakeContext:
        self.open_call_count += 1
        page = self._pages[min(self.open_call_count - 1, len(self._pages) - 1)]
        return _FakeContext(page)

    def evict_context_from_worker_thread(self, profile_id: str) -> None:
        self.evict_call_count += 1


class _FakeLocator:
    def __init__(self, *, count: int = 1, disabled: bool = False) -> None:
        self._count = count
        self.disabled = disabled
        self.click_calls = 0
        self.hover_calls = 0
        # If set, click() flips `disabled` to this value - simulates
        # the real, verified behavior of Start generation becoming
        # disabled again once a submission goes through
        # (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 5).
        self.disabled_after_click: bool | None = None

    @property
    def first(self) -> _FakeLocator:
        return self

    def count(self) -> int:
        return self._count

    def is_disabled(self, timeout: float | None = None) -> bool:
        return self.disabled

    def click(self, timeout: float | None = None) -> None:
        if self._count == 0:
            raise AssertionError("clicked a locator that should not exist")

        self.click_calls += 1

        if self.disabled_after_click is not None:
            self.disabled = self.disabled_after_click

    def hover(self, timeout: float | None = None) -> None:
        if self._count == 0:
            raise AssertionError("hovered a locator that should not exist")

        self.hover_calls += 1

    def filter(
        self,
        *,
        has: _FakeLocator | None = None,
        has_text: str | None = None,
    ) -> _FakeLocator:
        # Graceful fallback for a selector nothing was registered for
        # (page.locator("flow-video-tile") resolving to the shared
        # _MISSING instance below) - filtering an already-empty
        # locator further still correctly reports no match.
        return self


_MISSING = _FakeLocator(count=0)


class _FakeVideoTile:
    """
    Minimal stand-in for one real <flow-video-tile> locator scoped to
    a single row - supports get_by_role() the same way a real
    Playwright locator scoped to one tile does (its own "Generated
    video thumbnail" image, its own "More options" button), plus the
    prompt caption real Flow renders underneath each tile
    (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 5) - the real,
    content-based signal _tiles_matching_attempt() searches on instead
    of trusting position.
    """

    def __init__(
        self,
        *,
        caption: str,
        thumbnail: _FakeLocator | None = None,
        more_options: _FakeLocator | None = None,
    ) -> None:
        self.caption = caption
        self._thumbnail = thumbnail if thumbnail is not None else _FakeLocator(count=0)
        self._more_options = (
            more_options if more_options is not None else _FakeLocator()
        )

    def get_by_role(
        self, role: str, name: str | None = None, exact: bool = False
    ) -> _FakeLocator:
        if (role, name) == ("img", "Generated video thumbnail"):
            return self._thumbnail

        if (role, name) == ("button", "More options"):
            return self._more_options

        return _MISSING


class _FakeVideoTileSet:
    """
    Stands in for page.locator("flow-video-tile") - supports
    .filter(has_text=...), mirroring Playwright's own real
    case-insensitive substring match against each tile's own rendered
    text, so tests can register several tiles (some matching a given
    attempt's own prompt, some not) and assert the adapter finds the
    right one rather than a positional .first.
    """

    def __init__(self, tiles: list[_FakeVideoTile]) -> None:
        self._tiles = tiles

    def filter(
        self,
        *,
        has: _FakeLocator | None = None,
        has_text: str | None = None,
    ) -> _FakeVideoTileSet:
        if has_text is None:
            return self

        return _FakeVideoTileSet(
            [tile for tile in self._tiles if has_text.lower() in tile.caption.lower()]
        )

    def count(self) -> int:
        return len(self._tiles)

    @property
    def first(self) -> _FakeVideoTile:
        if not self._tiles:
            raise AssertionError("`.first` on an empty flow-video-tile locator")

        return self._tiles[0]


class _FakeKeyboard:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.pressed: list[str] = []

    def type(self, text: str, delay: float | None = None) -> None:
        self.typed.append(text)

    def press(self, key: str) -> None:
        self.pressed.append(key)


class _FakeDownload:
    """
    Real Flow's real download can be EITHER a raw video file directly
    (confirmed directly - clicking "Original size" saved a real,
    directly playable .mp4) OR a .zip archive containing one (also
    confirmed directly, via a real manual download from the same
    menu) - save_as() writes whichever this instance was configured
    for, so download()'s own real suffix-based branching is actually
    exercised for both real cases, not mocked around.
    """

    def __init__(
        self, filename: str = "lighthouse.mp4", inner_video_name: str = "lighthouse.mp4"
    ) -> None:
        self.suggested_filename = filename
        self.inner_video_name = inner_video_name
        self.saved_to: Path | None = None

    def save_as(self, path: str) -> None:
        self.saved_to = Path(path)

        if self.saved_to.suffix.lower() == ".zip":
            with zipfile.ZipFile(self.saved_to, "w") as archive:
                archive.writestr(self.inner_video_name, b"fake real video bytes")
        else:
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


class _FakePage:
    def __init__(self, *, raise_on_goto: bool = False) -> None:
        self.url_history: list[str] = []
        self.keyboard = _FakeKeyboard()
        self._by_role: dict[tuple[str, str], _FakeLocator] = {}
        self._by_css: dict[str, _FakeLocator] = {}
        self._by_text: dict[str, _FakeLocator] = {}
        self._download = _FakeDownload()
        self.closed = False
        self._raise_on_goto = raise_on_goto

    def goto(self, url: str, timeout: float | None = None) -> None:
        if self._raise_on_goto:
            raise PlaywrightError("Target page, context or browser has been closed")

        self.url_history.append(url)

    def is_closed(self) -> bool:
        return self.closed

    def get_by_role(
        self, role: str, name: str | None = None, exact: bool = False
    ) -> _FakeLocator:
        return self._by_role.get((role, name or ""), _MISSING)

    def locator(self, selector: str) -> _FakeLocator:
        return self._by_css.get(selector, _MISSING)

    def get_by_text(self, text: str, exact: bool = False) -> _FakeLocator:
        return self._by_text.get(text, _MISSING)

    def wait_for_timeout(self, ms: float) -> None:
        pass

    def expect_download(self, timeout: float | None = None) -> _FakeDownloadContext:
        return _FakeDownloadContext(self._download)

    # --- test setup helpers ---

    def register_role(self, role: str, name: str, locator: _FakeLocator) -> None:
        self._by_role[(role, name)] = locator

    def register_css(self, selector: str, locator: _FakeLocator) -> None:
        self._by_css[selector] = locator

    def register_text(self, text: str, locator: _FakeLocator) -> None:
        self._by_text[text] = locator


def _authenticated_page(
    *, prompt_disabled: bool = False, raise_on_goto: bool = False
) -> _FakePage:
    page = _FakePage(raise_on_goto=raise_on_goto)
    page.register_role("button", "New project", _FakeLocator())
    page.register_css(".prompt-input .ProseMirror", _FakeLocator())
    start_button = _FakeLocator(disabled=prompt_disabled)
    start_button.disabled_after_click = True
    page.register_role("button", "Start generation", start_button)
    # GoogleFlowExecutionSettings.variation_count now defaults to 1
    # (a real-world fix: Flow's own current default is x2, not x1 -
    # see that field's own docstring), so _apply_settings() now
    # always opens the real settings popover and clicks "x1" even
    # when a caller supplies no execution_settings at all - every
    # test using this default authenticated page needs both real
    # controls registered for that always-taken path to succeed.
    page.register_role("button", "Settings trigger", _FakeLocator())
    page.register_role("radio", "x1", _FakeLocator())
    # Real-world finding, 2026-09-11: the same settings popover also
    # holds an Image/Video generation-mode radio pair, and
    # _apply_settings() now unconditionally clicks "Video" (this
    # adapter is video-only) every time it opens the popover - the
    # same "always taken path" reasoning as the x1 registration just
    # above, so every test using this default authenticated page
    # needs this control registered too.
    page.register_role("radio", "Video", _FakeLocator())
    return page


def _adapter(
    page: _FakePage, *, operation_timeout_seconds: float = 5.0
) -> GoogleFlowRealUIAdapter:
    return GoogleFlowRealUIAdapter(
        worker=_FakeWorker(page),  # type: ignore[arg-type]
        base_url="https://flow.google.com/project/test-project",
        operation_timeout_seconds=operation_timeout_seconds,
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )


def _request(**overrides: object) -> GoogleFlowGenerationRequest:
    defaults: dict[str, object] = {
        "scene_number": 1,
        "prompt": "A calm lighthouse at sunset, gentle waves below.",
        "prompt_version": "v1",
        "profile_id": "flow.primary",
        "idempotency_key": "req-1",
    }
    defaults.update(overrides)
    return GoogleFlowGenerationRequest(**defaults)  # type: ignore[arg-type]


def _attempt(request: GoogleFlowGenerationRequest) -> GoogleFlowGenerationAttempt:
    return GoogleFlowGenerationAttempt(request=request, profile_id=request.profile_id)


# --- check_profile_health ---


def test_check_profile_health_true_when_new_project_button_present() -> None:
    page = _authenticated_page()
    adapter = _adapter(page)

    assert adapter.check_profile_health("flow.primary") is True
    assert page.url_history == ["https://flow.google.com/project/test-project"]


def test_check_profile_health_false_when_not_authenticated() -> None:
    page = _FakePage()  # no New project / Account details registered
    adapter = _adapter(page)

    assert adapter.check_profile_health("flow.primary") is False


def test_check_profile_health_true_on_the_library_view_with_no_new_project_button() -> (
    None
):
    """
    Real-world finding, 2026-09-11: a real project's "All media"
    library view (reachable via that project's own left-hand nav)
    shows neither "New project" nor "Account details" at all, even
    for a fully authenticated session - confirmed directly by the
    account owner's own screenshot of three intact, real generated
    videos while this method was reporting the profile unhealthy.
    check_profile_health must not report unhealthy just because the
    project happens to be showing that view - the persistent compose
    bar's prompt box is present there too and is a real, verified
    signal of its own.
    """

    page = _FakePage()
    page.register_css(".prompt-input .ProseMirror", _FakeLocator())
    adapter = _adapter(page)

    assert adapter.check_profile_health("flow.primary") is True


def test_get_or_open_page_recovers_when_the_cached_page_is_closed() -> None:
    """
    Real-world finding: a real operator hit Playwright's own "Target
    page, context or browser has been closed" through Check
    Connection. This adapter caches one Page per profile_id
    (_get_or_open_page's own self._pages) across its whole lifetime -
    a single, long-lived instance per src/desktop/services.py, reused
    across an entire real generation attempt's submit/observe/
    download sequence. If the underlying page/context ever dies
    (closed externally, or evicted and reopened fresh at the
    FlowBrowserWorker layer below - see test_flow_browser_worker.py's
    matching recovery test), this cache would keep handing back the
    OLD, now-dead Page object forever, since nothing here ever asked
    the worker again once a page was cached. Simulated directly: mark
    the first page closed (bypassing any real close path) and confirm
    the adapter notices and asks its worker for a fresh one instead of
    reusing the dead reference or raising.
    """

    first_page = _authenticated_page()
    second_page = _authenticated_page()
    worker = _SequentialFakeWorker([first_page, second_page])
    adapter = GoogleFlowRealUIAdapter(
        worker=worker,  # type: ignore[arg-type]
        base_url="https://flow.google.com/project/test-project",
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )

    assert adapter.check_profile_health("flow.primary") is True
    assert worker.open_call_count == 1

    first_page.closed = True

    assert adapter.check_profile_health("flow.primary") is True
    assert worker.open_call_count == 2
    # The second call must have gone through second_page, not the
    # stale, closed first_page.
    assert second_page.url_history == ["https://flow.google.com/project/test-project"]


def test_check_profile_health_recovers_when_goto_raises_a_closed_target_error() -> None:
    """
    Second real-world finding on the same live repro: is_closed() is a
    CLIENT-SIDE flag that only flips once Playwright's own connection
    notices the browser process is gone - a real operator closing the
    window via the OS (not through this app) can leave a brief window
    where is_closed() still reports False but the underlying browser
    is already dead, so _get_or_open_page()'s own liveness check alone
    (test_get_or_open_page_recovers_when_the_cached_page_is_closed,
    above) is not sufficient - the very next page.goto() can still
    raise. Simulated directly: the first page's goto() raises exactly
    the real error message seen live; check_profile_health() must
    catch it, force BOTH its own page cache and the worker's
    underlying context cache out (not just retry against the same
    stale references), and succeed against a genuinely fresh page.
    """

    first_page = _authenticated_page(raise_on_goto=True)
    second_page = _authenticated_page()
    worker = _SequentialFakeWorker([first_page, second_page])
    adapter = GoogleFlowRealUIAdapter(
        worker=worker,  # type: ignore[arg-type]
        base_url="https://flow.google.com/project/test-project",
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )

    assert adapter.check_profile_health("flow.primary") is True
    assert worker.open_call_count == 2
    assert worker.evict_call_count == 1
    assert second_page.url_history == ["https://flow.google.com/project/test-project"]


def test_check_profile_health_propagates_a_second_consecutive_failure() -> None:
    """The one retry is a real recovery attempt, not an infinite
    loop - if the freshly-reopened page ALSO fails, that's a genuine,
    different problem (e.g. a real network outage) that must still
    surface to the caller, not be silently swallowed."""

    first_page = _authenticated_page(raise_on_goto=True)
    second_page = _authenticated_page(raise_on_goto=True)
    worker = _SequentialFakeWorker([first_page, second_page])
    adapter = GoogleFlowRealUIAdapter(
        worker=worker,  # type: ignore[arg-type]
        base_url="https://flow.google.com/project/test-project",
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )

    try:
        adapter.check_profile_health("flow.primary")
    except PlaywrightError:
        pass
    else:
        raise AssertionError(
            "A second consecutive goto() failure must still raise, not be "
            "silently swallowed."
        )


def test_base_url_resolver_looks_up_the_right_account() -> None:
    """
    A single, long-lived adapter instance (e.g. the orchestrator's)
    can serve multiple accounts - each account's own saved project URL
    is what actually gets navigated to, never one URL forced onto
    every account.
    """

    page = _authenticated_page()
    urls_by_profile = {
        "flow.primary": "https://flow.google.com/project/primary-project",
        "flow.secondary": "https://flow.google.com/project/secondary-project",
    }
    adapter = GoogleFlowRealUIAdapter(
        worker=_FakeWorker(page),  # type: ignore[arg-type]
        base_url_resolver=lambda profile_id: urls_by_profile[profile_id],
        operation_timeout_seconds=5.0,
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )

    adapter.check_profile_health("flow.secondary")

    assert page.url_history == ["https://flow.google.com/project/secondary-project"]


def test_constructor_requires_exactly_one_of_base_url_or_resolver() -> None:
    page = _authenticated_page()

    try:
        GoogleFlowRealUIAdapter(worker=_FakeWorker(page))  # type: ignore[arg-type]
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    try:
        GoogleFlowRealUIAdapter(
            worker=_FakeWorker(page),  # type: ignore[arg-type]
            base_url="https://flow.google.com/project/x",
            base_url_resolver=lambda profile_id: "https://flow.google.com/project/x",
        )
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# --- set_confirm_before_generating() ---


def test_set_confirm_before_generating_never_clicks_the_real_sequence() -> None:
    page = _authenticated_page()
    agent_button = _FakeLocator()
    page.register_role("button", "Agent", agent_button)
    settings_button = _FakeLocator()
    page.register_role("button", "Settings trigger", settings_button)
    never_radio = _FakeLocator()
    page.register_role("radio", "Never", never_radio)
    save_button = _FakeLocator()
    page.register_role("button", "Save", save_button)
    adapter = _adapter(page)

    adapter.set_confirm_before_generating("flow.primary", always=False)

    assert agent_button.click_calls == 2  # on, then restored off
    assert settings_button.click_calls == 1
    assert never_radio.click_calls == 1
    assert save_button.click_calls == 1


def test_set_confirm_before_generating_always_clicks_the_always_radio() -> None:
    page = _authenticated_page()
    page.register_role("button", "Agent", _FakeLocator())
    page.register_role("button", "Settings trigger", _FakeLocator())
    always_radio = _FakeLocator()
    page.register_role("radio", "Always", always_radio)
    page.register_role("button", "Save", _FakeLocator())
    adapter = _adapter(page)

    adapter.set_confirm_before_generating("flow.primary", always=True)

    assert always_radio.click_calls == 1


# --- submit(): happy path ---


def test_submit_reaches_generating_on_the_real_happy_path() -> None:
    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING
    visited = [entry.state for entry in result.state_history]
    assert GoogleFlowGenerationState.SETTINGS_VERIFIED in visited
    assert GoogleFlowGenerationState.PROMPT_PREPARED in visited
    assert GoogleFlowGenerationState.SUBMITTING in visited
    assert GoogleFlowGenerationState.SUBMITTED in visited
    assert page.keyboard.typed == [request.prompt]


def test_submit_detects_auth_required() -> None:
    page = _FakePage()
    adapter = _adapter(page)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.AUTH_REQUIRED


def test_submit_detects_ui_changed_when_critical_controls_are_missing() -> None:
    page = _authenticated_page()
    # Remove the prompt box - simulates a real Flow redesign this
    # adapter has never seen.
    page.register_css(".prompt-input .ProseMirror", _MISSING)
    adapter = _adapter(page)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.UI_CHANGED
    assert "prompt_input" in result.state_history[-1].detail  # type: ignore[operator]


def test_submit_refuses_reference_assets_rather_than_guess() -> None:
    from src.models.google_flow_generation import (
        GoogleFlowReferenceAsset,
        GoogleFlowReferenceRole,
    )

    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request(
        reference_assets=[
            GoogleFlowReferenceAsset(
                source_path="assets/hero.png",
                checksum="abc123",
                role=GoogleFlowReferenceRole.CHARACTER,
            )
        ]
    )

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.UI_CHANGED
    assert "ingredient" in result.state_history[-1].detail.lower()  # type: ignore[union-attr]


def test_submit_reports_failed_when_start_generation_stays_disabled() -> None:
    page = _authenticated_page(prompt_disabled=True)
    adapter = _adapter(page)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.FAILED
    assert "disabled" in result.state_history[-1].detail.lower()  # type: ignore[union-attr]


def test_submit_reports_submission_uncertain_when_no_tiles_appear() -> None:
    page = _authenticated_page()
    # Start generation never actually goes disabled after the click -
    # no positive evidence generation started.
    start_button = page.get_by_role("button", name="Start generation")
    start_button.disabled_after_click = None
    adapter = _adapter(page, operation_timeout_seconds=0.1)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.SUBMISSION_UNCERTAIN


def test_submit_reports_settings_unavailable_for_an_unknown_model_family() -> None:
    page = _authenticated_page()
    page.register_role("button", "Settings trigger", _FakeLocator())
    page.register_role("button", "Select model family", _FakeLocator())
    # No "not_a_real_model" menuitem registered - _MISSING is returned.
    adapter = _adapter(page)
    request = _request(execution_settings={"model_family": "not_a_real_model"})

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.FAILED
    assert "FLOW_SETTINGS_UNAVAILABLE" in result.state_history[-1].detail  # type: ignore[operator]


def test_submit_applies_a_known_model_family_and_real_settings() -> None:
    page = _authenticated_page()
    page.register_role("button", "Settings trigger", _FakeLocator())
    page.register_role("button", "Select model family", _FakeLocator())
    menu_item = _FakeLocator()
    page.register_role("menuitem", "Veo 3.1 - Lite", menu_item)
    resolution_radio = _FakeLocator()
    page.register_role("radio", "360p", resolution_radio)
    duration_radio = _FakeLocator()
    page.register_role("radio", "8s", duration_radio)
    variation_radio = _FakeLocator()
    page.register_role("radio", "x2", variation_radio)
    adapter = _adapter(page)
    request = _request(
        execution_settings={
            "model_family": "Veo 3.1 - Lite",
            "resolution": "360p",
            "duration_seconds": 8,
            "variation_count": 2,
        }
    )

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING
    assert menu_item.click_calls == 1
    assert resolution_radio.click_calls == 1
    assert duration_radio.click_calls == 1
    assert variation_radio.click_calls == 1
    assert page.keyboard.pressed == ["Escape"]


def test_submit_forces_video_mode_before_opening_model_family() -> None:
    """
    Real-world finding, 2026-09-11: a real Flow project's compose bar
    can be left in Image mode (the account owner's "semi" project was
    showing "Nano Banana" image-model options, not any Veo option,
    under "Select model family"). _apply_settings() must click the
    real "Video" radio BEFORE opening "Select model family" - the
    real product only shows Veo's video-model catalog once Video mode
    is active, so a model_family value that's byte-for-byte correct
    still fails to be found while the popover is in Image mode.
    """

    page = _authenticated_page()
    video_radio = _FakeLocator()
    page.register_role(
        "radio", "Video", video_radio
    )  # overrides the auto-registered one
    page.register_role("button", "Select model family", _FakeLocator())
    menu_item = _FakeLocator()
    page.register_role("menuitem", "Veo 3.1 - Lite [Lower Priority]", menu_item)
    adapter = _adapter(page)
    request = _request(
        execution_settings={"model_family": "Veo 3.1 - Lite [Lower Priority]"}
    )

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING
    assert video_radio.click_calls == 1
    assert menu_item.click_calls == 1


def test_submit_fails_safely_when_video_mode_control_is_missing() -> None:
    """
    Mirrors GoogleFlowUIAdapter's own "ambiguous critical control:
    UI_CHANGED/FAILED, never guess" rule - if the real "Video" radio
    can't be found at all (an unrecognized real UI change), this must
    fail loudly rather than silently proceed to search whatever
    catalog happens to be showing.
    """

    page = _authenticated_page()
    page.register_role("radio", "Video", _FakeLocator(count=0))
    adapter = _adapter(page)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.FAILED
    assert "FLOW_SETTINGS_UNAVAILABLE" in result.state_history[-1].detail  # type: ignore[operator]


def test_submit_forces_x1_by_default_even_with_no_execution_settings_requested() -> (
    None
):
    """
    Real-world finding: a fresh Flow project defaults to x2 (two
    videos generated per submission for the same prompt), not x1 -
    confirmed directly against the real product. This codebase's
    whole Google Flow architecture (one scene -> one generation
    attempt -> one downloaded clip) assumes exactly one result per
    submission, so leaving variation_count unset used to mean
    "trust whatever Flow's own current default is" - silently wrong
    the moment that default became x2. GoogleFlowExecutionSettings.
    variation_count now defaults to 1, not None - the most common
    real path (an orchestrator call supplying no execution_settings
    at all, GoogleFlowGenerationOrchestratorService's own
    `execution_settings or GoogleFlowExecutionSettings()` fallback)
    must still explicitly click "x1", not silently accept Flow's own
    x2 default.
    """

    page = _authenticated_page()
    x1_radio = _FakeLocator()
    page.register_role("radio", "x1", x1_radio)  # overrides the auto-registered one
    adapter = _adapter(page)
    request = _request()  # no execution_settings at all

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING
    assert x1_radio.click_calls == 1
    assert page.keyboard.pressed == ["Escape"]


def test_submit_clicks_the_real_agent_toggle_when_requested() -> None:
    page = _authenticated_page()
    agent_button = _FakeLocator()
    page.register_role("button", "Agent", agent_button)
    adapter = _adapter(page)
    request = _request(execution_settings={"agent_mode": True})

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING
    assert agent_button.click_calls == 1
    # variation_count now always defaults to 1 (a deliberate,
    # separate real-world fix - see GoogleFlowExecutionSettings'
    # own docstring), so the settings popover always opens at least
    # to force x1, even when agent_mode is the only setting a caller
    # explicitly requested - Escape is real, expected evidence of
    # that popover being opened and closed, not a stray extra action.
    assert page.keyboard.pressed == ["Escape"]


def test_submit_never_clicks_agent_toggle_when_not_requested() -> None:
    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()  # agent_mode defaults to None

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING
    # "Agent" was never registered on this page at all - if the
    # adapter tried to click it, _MISSING's click() would raise.


# --- observe() ---


def test_observe_reports_ready_to_download_once_a_thumbnail_appears() -> None:
    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))
    assert submitted.state == GoogleFlowGenerationState.GENERATING

    tile = _FakeVideoTile(caption=request.prompt, thumbnail=_FakeLocator(count=2))
    page.register_css("flow-video-tile", _FakeVideoTileSet([tile]))  # type: ignore[arg-type]

    observed = adapter.observe(submitted)

    assert observed.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD


def test_observe_ignores_an_unrelated_tiles_thumbnail() -> None:
    """
    Real-world finding, 2026-09-14: observe() used to check for ANY
    generated thumbnail on the whole page, which is already true in
    any project with prior videos in it - confirmed live, it reported
    READY_TO_DOWNLOAD on the very first poll of a brand-new submission
    purely because an unrelated older video's thumbnail already
    existed. It must only count a thumbnail on the tile matching THIS
    attempt's own prompt.
    """

    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    unrelated_tile = _FakeVideoTile(
        caption="A completely different, already-finished video.",
        thumbnail=_FakeLocator(count=1),
    )
    page.register_css("flow-video-tile", _FakeVideoTileSet([unrelated_tile]))  # type: ignore[arg-type]

    observed = adapter.observe(submitted)

    assert observed.state == GoogleFlowGenerationState.GENERATING


def test_observe_is_read_only_before_completion() -> None:
    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    observed = adapter.observe(submitted)

    assert observed.state == GoogleFlowGenerationState.GENERATING


def test_observe_reconciles_submission_uncertain_with_real_matching_evidence() -> None:
    """
    Real-world finding, 2026-09-14: the "did it start" heuristic
    (Start generation button becoming disabled) reported
    SUBMISSION_UNCERTAIN on two separate real submissions this
    session, despite the account owner directly confirming both had
    actually completed in Flow's own "All media" tab - GF-7's own
    disclosed "real reconciliation needs the live adapter to check"
    gap. observe() now checks the real evidence (a tile matching this
    attempt's own prompt with a completed thumbnail) even from
    SUBMISSION_UNCERTAIN, not just SUBMITTED/GENERATING.
    """

    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))
    uncertain = submitted.with_transition(
        GoogleFlowGenerationState.SUBMISSION_UNCERTAIN, detail="test setup"
    )

    tile = _FakeVideoTile(caption=request.prompt, thumbnail=_FakeLocator(count=1))
    page.register_css("flow-video-tile", _FakeVideoTileSet([tile]))  # type: ignore[arg-type]

    observed = adapter.observe(uncertain)

    assert observed.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD


def test_observe_leaves_submission_uncertain_alone_without_matching_evidence() -> None:
    """
    The reconciliation above must never invent evidence that isn't
    there - no matching tile (or one still a placeholder) must leave
    a SUBMISSION_UNCERTAIN attempt exactly as it was, still requiring
    an operator's own judgment, not silently promoted.
    """

    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))
    uncertain = submitted.with_transition(
        GoogleFlowGenerationState.SUBMISSION_UNCERTAIN, detail="test setup"
    )

    observed = adapter.observe(uncertain)

    assert observed.state == GoogleFlowGenerationState.SUBMISSION_UNCERTAIN


def test_observe_without_an_open_page_is_ui_changed() -> None:
    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()
    attempt = _attempt(request).with_transition(
        GoogleFlowGenerationState.SETTINGS_VERIFIED, detail="x"
    )
    attempt = attempt.with_transition(
        GoogleFlowGenerationState.PROMPT_PREPARED, detail="x"
    )
    attempt = attempt.with_transition(GoogleFlowGenerationState.ANALYZING, detail="x")
    attempt = attempt.with_transition(GoogleFlowGenerationState.SUBMITTING, detail="x")
    attempt = attempt.with_transition(GoogleFlowGenerationState.SUBMITTED, detail="x")
    attempt = attempt.with_transition(GoogleFlowGenerationState.GENERATING, detail="x")

    observed = adapter.observe(attempt)

    assert observed.state == GoogleFlowGenerationState.UI_CHANGED


# --- download() ---


class _DownloadFlowControls:
    def __init__(
        self,
        thumbnail: _FakeLocator,
        more_options_button: _FakeLocator,
        download_menuitem: _FakeLocator,
        original_size_menuitem: _FakeLocator,
    ) -> None:
        self.thumbnail = thumbnail
        self.more_options_button = more_options_button
        self.download_menuitem = download_menuitem
        self.original_size_menuitem = original_size_menuitem


def _register_download_flow(
    page: _FakePage,
    *,
    thumbnail_count: int = 1,
    prompt: str = "A calm lighthouse at sunset, gentle waves below.",
) -> _DownloadFlowControls:
    """
    Registers the real, verified 2026-09-11 download flow: click "All
    media" -> hover the thumbnail -> the row's own <flow-video-tile>-
    scoped "More options" button -> "Download" menuitem (opens a
    format submenu) -> "Original size" menuitem (the one that actually
    fires a real download). `prompt` defaults to _request()'s own
    default so the registered tile's caption matches the attempt
    _tiles_matching_attempt() will search for.
    """

    page.register_text("All media", _FakeLocator())

    thumbnail = _FakeLocator(count=thumbnail_count)
    more_options_button = _FakeLocator()
    tile = _FakeVideoTile(
        caption=prompt, thumbnail=thumbnail, more_options=more_options_button
    )
    page.register_css("flow-video-tile", _FakeVideoTileSet([tile]))  # type: ignore[arg-type]

    download_menuitem = _FakeLocator()
    page.register_role("menuitem", "Download", download_menuitem)
    original_size_menuitem = _FakeLocator()
    page.register_role("menuitem", "Original size", original_size_menuitem)

    return _DownloadFlowControls(
        thumbnail, more_options_button, download_menuitem, original_size_menuitem
    )


def test_download_saves_a_file_and_transitions_to_downloaded(
    tmp_path: Path,
) -> None:
    page = _authenticated_page()
    adapter = GoogleFlowRealUIAdapter(
        worker=_FakeWorker(page),  # type: ignore[arg-type]
        base_url="https://flow.google.com/project/test-project",
        operation_timeout_seconds=5.0,
        download_root=tmp_path,
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    controls = _register_download_flow(page)

    ready = adapter.observe(submitted)
    assert ready.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD

    downloaded = adapter.download(ready)

    assert downloaded.state == GoogleFlowGenerationState.DOWNLOADED
    assert controls.thumbnail.hover_calls == 1
    assert controls.more_options_button.click_calls == 1
    assert controls.download_menuitem.click_calls == 1
    assert controls.original_size_menuitem.click_calls == 1
    # Real-world finding: "Original size" saves a real, directly
    # playable .mp4 - no zip involved for this specific menu path.
    assert downloaded.downloaded_file is not None
    assert downloaded.downloaded_file.endswith(".mp4")
    assert Path(downloaded.downloaded_file).is_file()
    saved_files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(saved_files) == 1


def test_download_extracts_the_video_when_flow_saves_a_zip_instead(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-11: a real MANUAL download from the
    same menu produced a .zip archive containing one real video, not a
    raw video file directly - confirmed directly by the account owner
    (a native Windows "Save As" dialog offering "ZIP File" as the save
    type). download() must not assume either shape; it checks the
    real saved file's own suffix and extracts only when it's actually
    a zip.
    """

    page = _authenticated_page()
    adapter = GoogleFlowRealUIAdapter(
        worker=_FakeWorker(page),  # type: ignore[arg-type]
        base_url="https://flow.google.com/project/test-project",
        operation_timeout_seconds=5.0,
        download_root=tmp_path,
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    _register_download_flow(page)
    page._download = _FakeDownload(filename="download.zip")  # noqa: SLF001

    ready = adapter.observe(submitted)
    assert ready.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD

    downloaded = adapter.download(ready)

    assert downloaded.state == GoogleFlowGenerationState.DOWNLOADED
    assert downloaded.downloaded_file is not None
    assert downloaded.downloaded_file.endswith(".mp4")
    assert Path(downloaded.downloaded_file).is_file()
    # The zip itself must not be left behind once extracted.
    saved_files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(saved_files) == 1
    assert saved_files[0].suffix == ".mp4"


def test_download_scopes_to_the_tile_matching_this_attempts_own_prompt(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-14 (supersedes the 2026-09-11 finding
    this test used to cover): download() used to grab whichever
    thumbnail rendered first/topmost across the WHOLE "All media"
    grid, with no check that it belonged to THIS attempt - a real risk
    the moment a project has more than one video (an unrelated older
    video, or another scene generated around the same time), which a
    live test surfaced directly. It must find the one tile whose own
    caption matches this attempt's own prompt and act only on that
    tile's own scoped controls, ignoring every other tile on the page.
    """

    page = _authenticated_page()
    adapter = GoogleFlowRealUIAdapter(
        worker=_FakeWorker(page),  # type: ignore[arg-type]
        base_url="https://flow.google.com/project/test-project",
        operation_timeout_seconds=5.0,
        download_root=tmp_path,
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    page.register_text("All media", _FakeLocator())

    unrelated_more_options = _FakeLocator()
    unrelated_tile = _FakeVideoTile(
        caption="A completely different video about mountains.",
        thumbnail=_FakeLocator(count=1),
        more_options=unrelated_more_options,
    )
    thumbnail = _FakeLocator(count=1)
    more_options_button = _FakeLocator()
    own_tile = _FakeVideoTile(
        caption=request.prompt, thumbnail=thumbnail, more_options=more_options_button
    )
    tile_set: Any = _FakeVideoTileSet([unrelated_tile, own_tile])
    page.register_css("flow-video-tile", tile_set)

    page.register_role("menuitem", "Download", _FakeLocator())
    page.register_role("menuitem", "Original size", _FakeLocator())

    ready = adapter.observe(submitted)
    assert ready.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD

    downloaded = adapter.download(ready)

    assert downloaded.state == GoogleFlowGenerationState.DOWNLOADED
    assert more_options_button.click_calls == 1
    assert unrelated_more_options.click_calls == 0


def test_download_refuses_to_guess_when_the_tile_is_ambiguous(
    tmp_path: Path,
) -> None:
    """
    Real-world finding, 2026-09-14: the same prompt got submitted more
    than once during this session's own investigation (a stuck earlier
    attempt, then a genuine retry) - a real scenario where two tiles
    can legitimately match the same prompt text. download() must
    refuse to guess between them rather than silently picking one.
    """

    page = _authenticated_page()
    adapter = GoogleFlowRealUIAdapter(
        worker=_FakeWorker(page),  # type: ignore[arg-type]
        base_url="https://flow.google.com/project/test-project",
        operation_timeout_seconds=5.0,
        download_root=tmp_path,
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    page.register_text("All media", _FakeLocator())
    tile_a = _FakeVideoTile(caption=request.prompt, thumbnail=_FakeLocator(count=1))
    tile_b = _FakeVideoTile(caption=request.prompt, thumbnail=_FakeLocator(count=1))
    page.register_css("flow-video-tile", _FakeVideoTileSet([tile_a, tile_b]))  # type: ignore[arg-type]

    ready = submitted.with_transition(
        GoogleFlowGenerationState.READY_TO_DOWNLOAD, detail="test setup"
    )

    result = adapter.download(ready)

    assert result.state == GoogleFlowGenerationState.UI_CHANGED


# --- cancel_or_abandon ---


def test_cancel_or_abandon_is_not_supported() -> None:
    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()

    try:
        adapter.cancel_or_abandon(_attempt(request))
        raise AssertionError("expected ExternalUIOperationNotSupportedError")
    except ExternalUIOperationNotSupportedError as error:
        assert error.operation == ExternalUIOperation.CANCEL_OR_ABANDON


# --- integration with the real GoogleFlowGenerationOrchestratorService ---
#
# Every test above verifies this adapter's own logic in isolation.
# These verify the actual wiring point desktop/services.py's
# get_google_flow_generation_orchestrator_service() sets up for real:
# a genuine GoogleFlowAccountRouterService/GoogleFlowGenerationOrchestratorService
# driving a genuine GoogleFlowRealUIAdapter (only the browser itself is
# faked) - catching integration bugs (wrong attribute names, wrong
# exception types, mismatched profile_id plumbing) neither class's own
# isolated test suite would.


def test_orchestrator_drives_a_real_adapter_end_to_end(tmp_path: Path) -> None:
    from src.models.provider_profile import (
        ProviderCategory,
        ProviderHealthStatus,
        ProviderProfile,
    )
    from src.models.video_job import VideoJob
    from src.services.google_flow_account_router_service import (
        GoogleFlowAccountRouterService,
    )
    from src.services.google_flow_generation_orchestrator_service import (
        GoogleFlowGenerationOrchestratorService,
    )
    from src.services.registry.provider_registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.register(
        ProviderProfile(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=True,
            health_status=ProviderHealthStatus.HEALTHY,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"flow_url": "https://flow.google.com/project/test-project"},
        )
    )

    page = _authenticated_page()
    # Mirrors get_google_flow_real_ui_adapter()'s own _resolve_base_url
    # exactly - each account's saved flow_url, never a fixed URL.
    adapter = GoogleFlowRealUIAdapter(
        worker=_FakeWorker(page),  # type: ignore[arg-type]
        base_url_resolver=lambda profile_id: registry.get(profile_id).metadata[
            "flow_url"
        ],
        operation_timeout_seconds=5.0,
        download_root=tmp_path,
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )
    orchestrator = GoogleFlowGenerationOrchestratorService(
        provider=adapter,
        account_router=GoogleFlowAccountRouterService(registry),
    )
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )

    submitted = orchestrator.submit_new_attempt(
        job,
        scene_number=1,
        prompt="A calm lighthouse at sunset, gentle waves below.",
        prompt_version="v1",
        idempotency_key="req-1",
    )

    assert submitted.state == GoogleFlowGenerationState.GENERATING
    assert page.url_history == ["https://flow.google.com/project/test-project"]
    # The ledger actually persisted this attempt onto the job, not
    # just returned it - the whole point of routing through the
    # orchestrator rather than calling the adapter directly.
    assert len(job.flow_generation_attempts) == 1
    assert job.flow_generation_attempts[0].id == submitted.id

    _register_download_flow(page)

    observed = orchestrator.observe_attempt(job, submitted)
    assert observed.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD
    assert job.flow_generation_attempts[0].state == (
        GoogleFlowGenerationState.READY_TO_DOWNLOAD
    )

    downloaded = orchestrator.download_attempt(job, observed)
    assert downloaded.state == GoogleFlowGenerationState.DOWNLOADED
    assert job.flow_generation_attempts[0].state == GoogleFlowGenerationState.DOWNLOADED
    saved_files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(saved_files) == 1


def test_orchestrator_reports_auth_required_via_a_real_adapter() -> None:
    from src.models.provider_profile import (
        ProviderCategory,
        ProviderHealthStatus,
        ProviderProfile,
    )
    from src.models.video_job import VideoJob
    from src.services.google_flow_account_router_service import (
        GoogleFlowAccountRouterService,
    )
    from src.services.google_flow_generation_orchestrator_service import (
        GoogleFlowGenerationOrchestratorService,
    )
    from src.services.registry.provider_registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.register(
        ProviderProfile(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=True,
            health_status=ProviderHealthStatus.HEALTHY,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"flow_url": "https://flow.google.com/project/test-project"},
        )
    )

    page = _FakePage()  # not authenticated - no New project/Account details
    adapter = GoogleFlowRealUIAdapter(
        worker=_FakeWorker(page),  # type: ignore[arg-type]
        base_url_resolver=lambda profile_id: registry.get(profile_id).metadata[
            "flow_url"
        ],
        operation_timeout_seconds=5.0,
        profile_directory_resolver=lambda profile_id: Path("unused") / profile_id,
    )
    orchestrator = GoogleFlowGenerationOrchestratorService(
        provider=adapter,
        account_router=GoogleFlowAccountRouterService(registry),
    )
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )

    result = orchestrator.submit_new_attempt(
        job,
        scene_number=1,
        prompt="A calm lighthouse at sunset, gentle waves below.",
        prompt_version="v1",
        idempotency_key="req-1",
    )

    assert result.state == GoogleFlowGenerationState.AUTH_REQUIRED
    assert (
        job.flow_generation_attempts[0].state == GoogleFlowGenerationState.AUTH_REQUIRED
    )
