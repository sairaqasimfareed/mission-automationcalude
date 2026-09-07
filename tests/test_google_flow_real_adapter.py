from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

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

    def open_persistent_context_from_worker_thread(
        self, profile_id: str, profile_directory: Path, *, headless: bool
    ) -> _FakeContext:
        return _FakeContext(self._page)


class _FakeLocator:
    def __init__(self, *, count: int = 1, disabled: bool = False) -> None:
        self._count = count
        self.disabled = disabled
        self.click_calls = 0
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


_MISSING = _FakeLocator(count=0)


class _FakeKeyboard:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.pressed: list[str] = []

    def type(self, text: str, delay: float | None = None) -> None:
        self.typed.append(text)

    def press(self, key: str) -> None:
        self.pressed.append(key)


class _FakeDownload:
    def __init__(self, filename: str = "lighthouse.mp4") -> None:
        self.suggested_filename = filename
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


class _FakePage:
    def __init__(self) -> None:
        self.url_history: list[str] = []
        self.keyboard = _FakeKeyboard()
        self._by_role: dict[tuple[str, str], _FakeLocator] = {}
        self._by_css: dict[str, _FakeLocator] = {}
        self._download = _FakeDownload()

    def goto(self, url: str, timeout: float | None = None) -> None:
        self.url_history.append(url)

    def get_by_role(
        self, role: str, name: str | None = None, exact: bool = False
    ) -> _FakeLocator:
        return self._by_role.get((role, name or ""), _MISSING)

    def locator(self, selector: str) -> _FakeLocator:
        return self._by_css.get(selector, _MISSING)

    def wait_for_timeout(self, ms: float) -> None:
        pass

    def expect_download(self, timeout: float | None = None) -> _FakeDownloadContext:
        return _FakeDownloadContext(self._download)

    # --- test setup helpers ---

    def register_role(self, role: str, name: str, locator: _FakeLocator) -> None:
        self._by_role[(role, name)] = locator

    def register_css(self, selector: str, locator: _FakeLocator) -> None:
        self._by_css[selector] = locator


def _authenticated_page(*, prompt_disabled: bool = False) -> _FakePage:
    page = _FakePage()
    page.register_role("button", "New project", _FakeLocator())
    page.register_css(".prompt-input .ProseMirror", _FakeLocator())
    start_button = _FakeLocator(disabled=prompt_disabled)
    start_button.disabled_after_click = True
    page.register_role("button", "Start generation", start_button)
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


# --- observe() ---


def test_observe_reports_ready_to_download_once_a_thumbnail_appears() -> None:
    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))
    assert submitted.state == GoogleFlowGenerationState.GENERATING

    page.register_role("img", "Generated video thumbnail", _FakeLocator(count=2))

    observed = adapter.observe(submitted)

    assert observed.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD


def test_observe_is_read_only_before_completion() -> None:
    page = _authenticated_page()
    adapter = _adapter(page)
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    observed = adapter.observe(submitted)

    assert observed.state == GoogleFlowGenerationState.GENERATING


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

    page.register_role("img", "Generated video thumbnail", _FakeLocator())
    page.register_role("button", "Download scene", _FakeLocator())
    page.register_role("button", "Done editing scene", _FakeLocator())

    ready = adapter.observe(submitted)
    assert ready.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD

    downloaded = adapter.download(ready)

    assert downloaded.state == GoogleFlowGenerationState.DOWNLOADED
    saved_files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(saved_files) == 1


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
