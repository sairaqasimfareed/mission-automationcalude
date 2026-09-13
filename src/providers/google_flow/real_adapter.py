from __future__ import annotations

import time
import zipfile
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from src.browser.flow_browser_worker import FlowBrowserWorker
from src.browser.flow_profile_paths import profile_directory
from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.providers.external_ui_generation_provider import (
    ExternalUIGenerationProvider,
    ExternalUIOperation,
)
from src.providers.google_flow.locators import GoogleFlowRealAccessibleNames

# Matches GoogleFlowUIAdapter's own local-storage convention
# (src/providers/google_flow/adapter.py's DEFAULT_FLOW_DOWNLOAD_ROOT) -
# a shared download tree for both adapters is intentional, since both
# ultimately download the same kind of provider-neutral artifact.
DEFAULT_FLOW_DOWNLOAD_ROOT = Path("data/google_flow_downloads")

# Real, verified vocabulary -> the real settings popover's own radio
# accessible names, per docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 4.
# The radio's accessible name IS the value itself for every dimension
# except variation_count (an int on GoogleFlowExecutionSettings, "x2"
# on the real control).
_VARIATION_COUNT_RADIO_NAMES = {1: "x1", 2: "x2", 3: "x3", 4: "x4"}


class GoogleFlowUIChangedError(RuntimeError):
    """
    Raised internally when a critical Flow control cannot be located
    at all. Never escapes GoogleFlowRealUIAdapter's own public
    methods - they catch it and return an attempt transitioned to
    UI_CHANGED instead, matching GoogleFlowUIAdapter's own "ambiguous
    critical control: UI_CHANGED, STOP. Never guess" rule.
    """


class GoogleFlowAuthRequiredError(RuntimeError):
    """Raised internally when the real product shows no sign of an
    authenticated session (see _detect_auth_required's own docstring
    for exactly what's checked and why)."""


def _extract_sole_video_from_zip(zip_path: Path, destination_dir: Path) -> Path:
    """
    Real Flow's download is a .zip archive containing exactly one real
    video file, not a raw video file directly (confirmed directly
    against a real download). Extracts that one video and removes the
    zip, so downloaded_file always points at a real, directly playable
    media file - never a zip - matching what downstream technical
    validation (MediaTechnicalValidationService) expects.

    Raises if the zip doesn't contain exactly one video - never
    guessing which of several files is the real one.
    """

    video_suffixes = {".mp4", ".mov", ".webm"}

    with zipfile.ZipFile(zip_path) as archive:
        video_names = [
            name
            for name in archive.namelist()
            if Path(name).suffix.lower() in video_suffixes
        ]

        if len(video_names) != 1:
            raise RuntimeError(
                f"Expected exactly one real video file inside the "
                f"downloaded zip, found {len(video_names)}: {video_names}."
            )

        archive.extract(video_names[0], destination_dir)

    extracted_path = destination_dir / video_names[0]
    zip_path.unlink()

    return extracted_path


class GoogleFlowRealUIAdapter(ExternalUIGenerationProvider):
    """
    A SEPARATE adapter from GoogleFlowUIAdapter (src/providers/google_flow/adapter.py),
    deliberately - not a locators-string swap on the same class. The
    real product's settings mechanism is a popover of radio-button
    groups, opened via a "Settings trigger" button; GoogleFlowUIAdapter's
    whole interaction shape (a <select> dropdown read via
    select_option(), distinct named analysis/generation/result panels)
    was built against tests/fixtures/fake_flow_ui.html and does not
    match the real product's structure at all - forcing both into one
    class via conditionals would tangle two genuinely different
    interaction models together. GoogleFlowUIAdapter and its 16
    fixture-driven tests are completely untouched by this class.

    Built from real, verified findings - docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md,
    captured against a real, authenticated Google Flow session,
    including one real, human-authorized generation. What IS verified
    (and exercised by this class's own logic): the dashboard, the
    compose UI inside an existing project, typing a real prompt, the
    settings popover's full real vocabulary (model family, resolution,
    duration, aspect ratio, variation count), clicking Start
    generation, the generating -> completed tile sequence, and the
    real Download scene control. Also now confirmed (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md
    section 4a): the confirmation-before-generating screen is an
    Agent-mode-only, explicitly configurable setting ("Confirm before
    generating": Always/Never, in Agent settings) - not content/
    policy-triggered, and irrelevant to this class, since it never
    enables Agent mode (the "Agent" toggle is never clicked - see
    section 4's own "Operationally important" note on why Agent-off is
    the real, working path this class drives). What IS still NOT
    verified and deliberately NOT built here, rather than guessed:
    the ingredient/reference-attachment flow ("Add ingredients to the
    prompt box" was seen but never opened) and any error-state
    screens. A submission that unexpectedly hits either lands on
    UI_CHANGED/SUBMISSION_UNCERTAIN rather than a fabricated click
    sequence.

    base_url/base_url_resolver must resolve to a SPECIFIC project URL
    (https://flow.google.com/project/<uuid>), not the bare domain -
    the real compose UI lives inside a project, and this class never
    creates one itself ("New project" has a real, visible side effect
    on the account and is never clicked automatically). Reuses the
    exact same per-account "Flow URL" field/mechanism
    GoogleFlowUIAdapter and the desktop panel already use, rather than
    adding a redundant new field - the operator points it at a
    project's URL instead of the bare domain for real submissions.

    Only ever mutates its own `_pages` dict from inside the worker
    thread (every public method here runs its actual work through
    `self._worker.submit(...)`), matching FlowBrowserWorker's own
    threading contract - identical discipline to GoogleFlowUIAdapter.
    """

    def __init__(
        self,
        *,
        worker: FlowBrowserWorker,
        base_url: str | None = None,
        base_url_resolver: Callable[[str], str] | None = None,
        names: GoogleFlowRealAccessibleNames | None = None,
        headless: bool = True,
        operation_timeout_seconds: float = 30.0,
        download_root: Path = DEFAULT_FLOW_DOWNLOAD_ROOT,
        profile_directory_resolver: Callable[[str], Path] = profile_directory,
    ) -> None:
        """
        Exactly one of base_url/base_url_resolver must be given.

        base_url is what the desktop panel uses - one operator, one
        account selected at a time, so one fixed project URL per
        adapter instance is correct there. base_url_resolver is what a
        single, long-lived adapter instance serving MULTIPLE accounts
        needs (e.g. the orchestrator, routing across several accounts
        via GoogleFlowAccountRouterService) - each account's own saved
        project URL (ProviderProfile.metadata["flow_url"], the exact
        same value the desktop panel's Flow URL field manages) rather
        than one URL forced onto every account.
        """

        if (base_url is None) == (base_url_resolver is None):
            raise ValueError(
                "Exactly one of base_url or base_url_resolver must be given."
            )

        self._worker = worker

        if base_url_resolver is not None:
            self._base_url_resolver: Callable[[str], str] = base_url_resolver
        else:
            fixed_url = base_url
            assert fixed_url is not None  # guaranteed by the check above  # noqa: S101
            self._base_url_resolver = lambda _profile_id: fixed_url

        self._names = names or GoogleFlowRealAccessibleNames()
        self._headless = headless
        self._operation_timeout_seconds = operation_timeout_seconds
        self._download_root = download_root
        self._profile_directory_resolver = profile_directory_resolver

        self._pages: dict[str, Page] = {}

    @property
    def _action_timeout_ms(self) -> float:
        """Same reasoning as GoogleFlowUIAdapter's own property of the
        same name: kept shorter than every outer future timeout below
        so a genuine "can't find/interact with this control" condition
        fails fast and is actually caught."""

        return self._operation_timeout_seconds * 1000

    @property
    def _navigation_timeout_ms(self) -> float:
        """
        Real-world finding, 2026-09-14: the first live run through
        submit()'s real page.goto() (a heavy, client-rendered Angular
        app, not a static page) timed out at the same 30s
        _action_timeout_ms every click/locator check uses - reasonable
        for "can this element be found on an already-loaded page", far
        too tight for "load this whole app from scratch" under
        anything but a fast connection. A slow real network directly
        hits this call, never the fast, already-rendered-DOM checks
        elsewhere, so only navigation gets the longer budget.
        """

        return self._operation_timeout_seconds * 2 * 1000

    @property
    def provider_name(self) -> str:
        return "Google Flow"

    def health_check(self) -> bool:
        return True

    @property
    def supported_operations(self) -> frozenset[ExternalUIOperation]:
        return frozenset(
            {
                ExternalUIOperation.SUBMIT,
                ExternalUIOperation.OBSERVE,
                ExternalUIOperation.DOWNLOAD,
            }
        )

    def check_profile_health(self, profile_id: str) -> bool:
        def _run() -> bool:
            # Real-world finding: is_closed() is a CLIENT-SIDE flag
            # that only flips once Playwright's own connection
            # notices the browser process is gone - a real operator
            # closing the window via the OS (not through this app)
            # can leave a brief window where is_closed() still says
            # False but the process is already dead, so
            # _get_or_open_page()'s own liveness check (necessary, but
            # not sufficient on its own) can still hand back a page
            # that then fails on the very next real operation. One
            # retry here, forcing BOTH this adapter's own page cache
            # and the worker's underlying context cache out (not
            # relying on is_closed() to have caught up by now),
            # recovers transparently with a genuinely fresh browser
            # process instead of surfacing a raw Playwright error the
            # operator can't act on.
            try:
                page = self._get_or_open_page(profile_id)
                page.goto(
                    self._base_url_resolver(profile_id),
                    timeout=self._navigation_timeout_ms,
                )
            except PlaywrightError:
                self._pages.pop(profile_id, None)
                self._worker.evict_context_from_worker_thread(profile_id)
                page = self._get_or_open_page(profile_id)
                page.goto(
                    self._base_url_resolver(profile_id),
                    timeout=self._navigation_timeout_ms,
                )

            # Real-world finding, 2026-09-11: goto() only waits for the
            # 'load' event, not for this real, client-rendered Angular
            # app to finish hydrating its buttons - _looks_authenticated's
            # own checks are all instant, non-waiting .count() reads
            # (unlike an action such as .click(), .count() never
            # auto-waits for an element to appear), so calling it
            # immediately after goto() raced the real render and
            # intermittently reported a fully authenticated, healthy
            # real session (confirmed directly - the same page moments
            # later showed "Account details" present) as unhealthy.
            # Bumped from 1500ms to 3000ms, 2026-09-12: still
            # intermittently too short under rapid repeated real
            # automation (multiple scenes submitted back-to-back).
            page.wait_for_timeout(3000)

            return self._looks_authenticated(page)

        return self._worker.submit_with_recovery(
            _run, timeout=self._operation_timeout_seconds * 3
        )

    def set_confirm_before_generating(self, profile_id: str, *, always: bool) -> None:
        """
        Explicit, standalone action - never bundled silently into a
        generation request - that flips Google Flow's own real, saved
        "Confirm before generating" account setting
        (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 4a).

        This is deliberately the ONE place in this codebase that
        touches that Flow-side setting at all: every generation this
        adapter drives is instead gated by this app's OWN,
        independent approval policy
        (GoogleFlowGenerationOrchestratorService's Agent-mode gate),
        which never depends on what this Flow-side toggle is set to.
        Call this only in direct response to an explicit operator
        action (e.g. a clearly-labeled GUI button), never as a side
        effect of anything else.

        Confirmed real click path: Agent settings is the SAME
        "Settings trigger" popover, showing this content only once
        Agent mode is on - so this method clicks Agent on, opens
        Settings, sets the radio, saves, then clicks Agent again to
        restore it to its confirmed real default (off) - assumes the
        toggle started off, matching that confirmed default; there is
        no verified way to detect its current state first.
        """

        def _run() -> None:
            page = self._get_or_open_page(profile_id)
            page.goto(
                self._base_url_resolver(profile_id), timeout=self._navigation_timeout_ms
            )

            page.get_by_role("button", name=self._names.agent_toggle_button).click(
                timeout=self._action_timeout_ms
            )
            page.get_by_role("button", name=self._names.settings_trigger_button).click(
                timeout=self._action_timeout_ms
            )

            radio_name = (
                self._names.confirm_before_generating_always_radio
                if always
                else self._names.confirm_before_generating_never_radio
            )
            page.get_by_role("radio", name=radio_name).click(
                timeout=self._action_timeout_ms
            )
            page.get_by_role("button", name=self._names.save_settings_button).click(
                timeout=self._action_timeout_ms
            )

            # Restore the Agent toggle to its confirmed real default
            # (off) - this method's job is only the saved confirmation
            # preference, not leaving Agent mode itself switched on.
            page.get_by_role("button", name=self._names.agent_toggle_button).click(
                timeout=self._action_timeout_ms
            )

        self._worker.submit_with_recovery(
            _run, timeout=self._operation_timeout_seconds * 3
        )

    def submit(
        self,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.SUBMIT)

        def _run() -> GoogleFlowGenerationAttempt:
            page = self._get_or_open_page(attempt.profile_id)
            page.goto(
                self._base_url_resolver(attempt.profile_id),
                timeout=self._navigation_timeout_ms,
            )
            # Real-world finding, 2026-09-12: the exact same race
            # check_profile_health() was already fixed for (goto()
            # only waits for 'load', not for this client-rendered
            # Angular app to finish hydrating, and _looks_authenticated's
            # own checks are instant, non-waiting .count() reads) also
            # exists here - confirmed directly: a real submission
            # right after a real, successful download (which leaves
            # the page on the "All media" view) reported AUTH_REQUIRED
            # on a session that was genuinely still authenticated.
            page.wait_for_timeout(3000)

            if not self._looks_authenticated(page):
                return attempt.with_transition(
                    GoogleFlowGenerationState.AUTH_REQUIRED,
                    detail="Flow shows no sign of an authenticated session.",
                )

            try:
                self._preflight(page)
            except GoogleFlowUIChangedError as error:
                return attempt.with_transition(
                    GoogleFlowGenerationState.UI_CHANGED,
                    detail=str(error),
                )

            return self._drive_submission(page, request, attempt)

        # Real-world finding, 2026-09-12: under the account's current
        # real conditions (a low-credit banner, more account load),
        # even a doubled _wait_for_new_tiles_or_confirmation() wait
        # was still intermittently too short - bumped to 4x there, so
        # this outer budget needs matching headroom for the
        # settings/typing steps that also run inside the same call.
        #
        # Real-world finding, 2026-09-14: widening page.goto() to its
        # own 2x _navigation_timeout_ms (a separate real fix, for a
        # real navigation timeout under slow internet) made the old
        # 6x outer ceiling too tight - navigation(2x) + the settings/
        # typing steps + the confirmation wait(4x) can now add up to
        # more than 6x on a genuinely slow connection, and this exact
        # failure mode was confirmed live: submit_with_recovery's
        # outer future timed out and tore the browser down while a
        # real generation had already started (the account owner
        # watched it happen). Widened to 9x so navigation(2x) +
        # confirmation-wait(4x) + a real settings/typing buffer all
        # fit with room to spare.
        return self._worker.submit_with_recovery(
            _run, timeout=self._operation_timeout_seconds * 9
        )

    def observe(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.OBSERVE)

        def _run() -> GoogleFlowGenerationAttempt:
            page = self._pages.get(attempt.profile_id)

            if page is None:
                return attempt.with_transition(
                    GoogleFlowGenerationState.UI_CHANGED,
                    detail=(
                        "No open Flow page exists for this attempt's profile - "
                        "cannot observe."
                    ),
                )

            if attempt.state not in {
                GoogleFlowGenerationState.SUBMITTED,
                GoogleFlowGenerationState.GENERATING,
            }:
                return attempt

            thumbnails = page.get_by_role(
                "img", name=self._names.generated_video_thumbnail
            )

            if thumbnails.count() == 0:
                # Still generating - real Flow shows no distinct
                # progress indicator in the accessible tree, only the
                # eventual thumbnail (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md
                # section 5) - read-only, correctly reports unchanged.
                return attempt

            return attempt.with_transition(
                GoogleFlowGenerationState.READY_TO_DOWNLOAD,
                detail=f"Flow shows {thumbnails.count()} generated thumbnail(s).",
            )

        return self._worker.submit_with_recovery(
            _run, timeout=self._operation_timeout_seconds
        )

    def download(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.DOWNLOAD)

        def _run() -> GoogleFlowGenerationAttempt:
            page = self._pages.get(attempt.profile_id)

            if page is None:
                raise RuntimeError(
                    "No open Flow page exists for this attempt's profile."
                )

            destination_dir = self._download_root / attempt.profile_id / str(attempt.id)
            destination_dir.mkdir(parents=True, exist_ok=True)

            # Real-world finding, 2026-09-11 (superseding an earlier,
            # wrong assumption that download lived inside a single-
            # video edit view modal reachable straight from the
            # compose view): the real download control only exists on
            # the "All media" library view.
            page.get_by_text(self._names.all_media_nav_item, exact=True).first.click(
                timeout=self._action_timeout_ms
            )
            # goto()/navigation only waits for load, not for this
            # client-rendered Angular view to finish hydrating - same
            # real race check_profile_health hit (see its own fix).
            page.wait_for_timeout(1500)

            first_thumbnail = page.get_by_role(
                "img", name=self._names.generated_video_thumbnail
            ).first
            # The row's own controls (its "More options" button among
            # them) only render into the DOM on a real hover event -
            # confirmed directly (a page-wide search found 0 of them
            # before hovering, exactly 1 new one after).
            first_thumbnail.hover(timeout=self._action_timeout_ms)
            page.wait_for_timeout(1500)

            # Real Flow renders one <flow-video-tile> per row, each
            # with its own identically-named "More options" button (on
            # top of a separate, ALWAYS-present, unrelated "More
            # options" button elsewhere on the page) - scope to the
            # specific tile structurally containing the thumbnail just
            # hovered, exactly like the earlier <flow-batch-info>
            # download-button scoping fix. Never guess which of
            # several identically-labeled real controls is the right
            # one.
            tile = page.locator("flow-video-tile").filter(has=first_thumbnail)
            tile.get_by_role("button", name=self._names.more_options_button).click(
                timeout=self._action_timeout_ms
            )

            # Clicking "Download" alone never fires a real download -
            # it only opens a further submenu of format/resolution
            # choices (Animated GIF / Original size / Upscaled / 4K),
            # confirmed directly (expect_download() timed out waiting
            # after only this click). "Original size" is the one real,
            # free choice (Upscaled/4K cost extra real credits) that
            # always matches whatever resolution the video actually
            # generated at.
            page.get_by_role("menuitem", name=self._names.download_menu_item).click(
                timeout=self._action_timeout_ms
            )

            with page.expect_download(
                timeout=self._operation_timeout_seconds * 1000
            ) as download_info:
                page.get_by_role(
                    "menuitem", name=self._names.download_original_size_menu_item
                ).click(timeout=self._action_timeout_ms)

            download = download_info.value
            saved_path = destination_dir / download.suggested_filename
            download.save_as(str(saved_path))

            # Real-world finding, 2026-09-11: real Flow's download can
            # be EITHER a raw video file directly (confirmed directly -
            # clicking "Original size" specifically saved a real,
            # directly playable .mp4) OR a .zip archive containing one
            # (also confirmed directly via a real manual download from
            # the same menu). Never assume which - check the real
            # saved file itself rather than guessing from the menu
            # path taken.
            destination = (
                _extract_sole_video_from_zip(saved_path, destination_dir)
                if saved_path.suffix.lower() == ".zip"
                else saved_path
            )

            # Real-world finding, 2026-09-11: with_transition() only
            # ever records the state/history, never touches
            # downloaded_file - this field was never actually being
            # set here, so validate_downloaded_attempt() would always
            # have raised "Cannot validate an attempt with no
            # downloaded_file set" even on an otherwise-successful
            # download.
            return attempt.with_transition(
                GoogleFlowGenerationState.DOWNLOADED,
                detail=f"Saved to {destination}.",
            ).model_copy(update={"downloaded_file": str(destination)})

        return self._worker.submit_with_recovery(
            _run, timeout=self._operation_timeout_seconds * 2
        )

    def cancel_or_abandon(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        # Same honesty as GoogleFlowUIAdapter: no real, verified way to
        # actually stop an in-flight generation was found - claiming
        # to cancel it would be dishonest rather than merely
        # unimplemented.
        self.ensure_supported(ExternalUIOperation.CANCEL_OR_ABANDON)

        raise AssertionError("unreachable - ensure_supported always raises first")

    def _drive_submission(
        self,
        page: Page,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        current = attempt

        try:
            self._apply_settings(page, request.execution_settings)
        except _FlowSettingsUnavailableError as error:
            return current.with_transition(
                GoogleFlowGenerationState.FAILED,
                detail=f"FLOW_SETTINGS_UNAVAILABLE: {error}",
            )

        current = current.with_transition(
            GoogleFlowGenerationState.SETTINGS_VERIFIED,
            detail="Requested settings applied via the real settings popover.",
        )

        prompt_box = page.locator(self._names.prompt_input_css)
        prompt_box.click(timeout=self._action_timeout_ms)
        page.keyboard.type(request.prompt, delay=10)
        current = current.with_transition(
            GoogleFlowGenerationState.PROMPT_PREPARED,
            detail="Exact persisted prompt typed - never rewritten.",
        )

        if request.reference_assets:
            # "Add ingredients to the prompt box" was located but its
            # real upload flow was never opened/verified (see class
            # docstring) - never guessed here.
            return current.with_transition(
                GoogleFlowGenerationState.UI_CHANGED,
                detail=(
                    "This request has reference assets, but the real "
                    "ingredient-attachment flow is not yet verified - "
                    "refusing to guess rather than risk a silent drop."
                ),
            )

        start_button = page.get_by_role(
            "button", name=self._names.start_generation_button
        )

        if start_button.is_disabled(timeout=self._action_timeout_ms):
            return current.with_transition(
                GoogleFlowGenerationState.FAILED,
                detail=(
                    "Start generation stayed disabled after typing the "
                    "prompt - the real product's own disabled-state rule "
                    "(docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 3)."
                ),
            )

        current = current.with_transition(
            GoogleFlowGenerationState.ANALYZING,
            detail="About to click Start generation.",
        )

        # The credit-sensitive boundary (this whole initiative's own
        # rule): persisted BEFORE the operation that may spend
        # provider credit.
        current = current.with_transition(
            GoogleFlowGenerationState.SUBMITTING,
            detail="Crossing the credit-sensitive submission boundary.",
        )

        start_button.click(timeout=self._action_timeout_ms)

        if self._wait_for_new_tiles_or_confirmation(page):
            current = current.with_transition(
                GoogleFlowGenerationState.SUBMITTED,
                detail="New generating tile(s) appeared after Start generation.",
            )

            return current.with_transition(
                GoogleFlowGenerationState.GENERATING,
                detail="Generation is in progress.",
            )

        # No positive evidence generation actually started (no new
        # tile). This class never enables Agent mode (see the class
        # docstring), and confirmation-before-generating is confirmed
        # to be an Agent-mode-only setting
        # (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 4a) - so this
        # is NOT expected to be a confirmation screen for the account/
        # settings this class actually drives, but something else
        # unrecognized. Never blindly retried, matching the credit-
        # sensitive-state rule exactly.
        return current.with_transition(
            GoogleFlowGenerationState.SUBMISSION_UNCERTAIN,
            detail=(
                "No positive evidence generation started after clicking "
                "Start generation - an unrecognized real screen (not "
                "expected to be Agent-mode confirmation, since Agent is "
                "never enabled by this class)."
            ),
        )

    def _apply_settings(
        self, page: Page, settings: GoogleFlowExecutionSettings
    ) -> None:
        """
        Click the real "Agent" toggle if requested, then open the real
        settings popover and click the radio/menu option matching each
        requested dimension - never silent substitution, matching
        GoogleFlowUIAdapter's own rule: a requested value this method
        cannot find raises _FlowSettingsUnavailableError rather than
        leaving Flow's current default silently in place.
        """

        if settings.agent_mode:
            # A separate control from the popover below (it lives on
            # the main compose bar, not inside "Settings trigger") -
            # docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 3 confirms
            # its default is OFF/unclicked, so a single click reliably
            # turns it on for a freshly loaded project page. Whether
            # it stays on across multiple submissions on the SAME
            # cached page (this adapter reuses one page per profile,
            # _get_or_open_page) is NOT verified - only ever requesting
            # agent_mode=True is safe; there is no verified way to
            # detect/force it back off yet, so agent_mode=False is
            # treated the same as None (never touched) rather than
            # guessed at.
            page.get_by_role("button", name=self._names.agent_toggle_button).click(
                timeout=self._action_timeout_ms
            )

        # variation_count is no longer Optional (GoogleFlowExecutionSettings'
        # own model default is now 1, a deliberate policy - see that
        # field's own docstring for why), so it is always truthy and
        # this check now always opens the settings popover, at
        # minimum to explicitly click x1 - the one case this used to
        # skip entirely (every field unset) is exactly the case that
        # needs fixing: Flow's own current default is x2, not x1, and
        # this codebase's whole architecture assumes one video per
        # submission.
        if not any(
            (
                settings.model_family,
                settings.resolution,
                settings.duration_seconds,
                settings.aspect_ratio,
                settings.variation_count,
            )
        ):
            return  # unreachable while variation_count defaults to 1; kept for clarity/safety

        page.get_by_role("button", name=self._names.settings_trigger_button).click(
            timeout=self._action_timeout_ms
        )
        # Real-world finding, 2026-09-12: the popover's own open
        # animation/render isn't instant - the same category of race
        # already fixed elsewhere (an instant, non-waiting .count()
        # check run immediately after an action that needs a moment to
        # render). Confirmed directly: a real submission failed with
        # "requested generation_mode 'Video' is not one of the real
        # options Flow currently offers" - the Video radio genuinely
        # wasn't in the DOM yet at the instant _click_radio checked.
        page.wait_for_timeout(800)

        # Real-world finding, 2026-09-11: the same settings popover
        # also contains an Image/Video generation-mode radio pair
        # ("image | Image" / "videocam | Video"), and a real project's
        # compose bar can be left in Image mode (confirmed directly -
        # the account owner's "semi" project was showing "Nano Banana"
        # image-model options under "Select model family" instead of
        # any Veo option). This class exists exclusively to drive
        # Google Flow's VIDEO generation - never image - so unlike
        # every other dimension below (which only acts when the
        # caller explicitly asked), forcing Video mode here is an
        # unconditional invariant of this class, not a per-request
        # setting: leaving Flow's current mode silently in place was
        # exactly what made every model_family selection below search
        # the wrong catalog and fail with a real, misleading
        # FLOW_SETTINGS_UNAVAILABLE ("model_family '...' is not one of
        # the real options") even when the requested model_family
        # string was byte-for-byte correct.
        self._click_radio(page, "Video", dimension="generation_mode")

        if settings.model_family:
            page.get_by_role(
                "button", name=self._names.select_model_family_button
            ).click(timeout=self._action_timeout_ms)

            # Real-world finding: Flow now offers "Veo 3.1 - Lite" and
            # "Veo 3.1 - Lite [Lower Priority]" as two GENUINELY
            # SEPARATE, distinct real options (confirmed directly - a
            # real settings popover shows both as their own list rows,
            # not one label with a transient suffix). exact=True stays
            # correct and necessary here specifically because of that
            # - a substring match would ambiguously match both real
            # options whenever "Veo 3.1 - Lite" itself is requested.
            option = page.get_by_role(
                "menuitem", name=settings.model_family, exact=True
            )

            if option.count() == 0:
                raise _FlowSettingsUnavailableError(
                    f"requested model_family '{settings.model_family}' is not "
                    "one of the real options Flow currently offers."
                )

            option.click(timeout=self._action_timeout_ms)

        if settings.resolution:
            self._click_radio(page, settings.resolution, dimension="resolution")

        if settings.duration_seconds:
            duration_name = f"{int(settings.duration_seconds)}s"
            self._click_radio(page, duration_name, dimension="duration_seconds")

        if settings.aspect_ratio:
            self._click_radio(page, settings.aspect_ratio, dimension="aspect_ratio")

        if settings.variation_count:
            variation_name = _VARIATION_COUNT_RADIO_NAMES.get(settings.variation_count)

            if variation_name is None:
                raise _FlowSettingsUnavailableError(
                    f"requested variation_count {settings.variation_count} is "
                    "not one of the real x1-x4 options Flow currently offers."
                )

            self._click_radio(page, variation_name, dimension="variation_count")

        # Closing mechanism is NOT verified against the real product -
        # Escape is a conservative, standard way to dismiss a popover
        # without guessing at a specific close control this session
        # never observed.
        page.keyboard.press("Escape")

    def _click_radio(self, page: Page, name: str, *, dimension: str) -> None:
        radio = page.get_by_role("radio", name=name)

        if radio.count() == 0:
            raise _FlowSettingsUnavailableError(
                f"requested {dimension} '{name}' is not one of the real "
                "options Flow currently offers."
            )

        radio.first.click(timeout=self._action_timeout_ms)

    def _wait_for_new_tiles_or_confirmation(self, page: Page) -> bool:
        """
        Poll for the real, verified positive-evidence signal that
        generation actually started: the prompt box clearing itself
        back to empty (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 5 -
        confirmed real, immediate behavior for the one real submission
        tested). Returns False, never guessing at an unrecognized
        screen, if that doesn't happen within the timeout.

        Real-world finding, 2026-09-12: a real submission against a
        brand-new project (the account owner had just switched to a
        fresh Flow project) genuinely started generating for real -
        confirmed directly, moments later, by both the account owner
        watching it happen and a follow-up inspection showing Start
        generation disabled and a thumbnail present - but took longer
        than operation_timeout_seconds (30s) to visibly disable,
        making this method report a false SUBMISSION_UNCERTAIN on a
        submission that had actually succeeded.

        Bumped again the same day, 4x instead of 2x: even the doubled
        wait was still repeatedly too short under the account's real,
        current conditions (a persistent low-credit banner, more
        account load) - confirmed directly across a whole batch run,
        where 4 separate real submissions all reported
        SUBMISSION_UNCERTAIN, yet a follow-up "All media" check found
        all 4 had genuinely completed. submit()'s own outer budget
        (operation_timeout_seconds * 6) was widened to match, so this
        4x wait always fits inside it alongside the settings/typing
        steps that run before this wait.
        """

        start_button = page.get_by_role(
            "button", name=self._names.start_generation_button
        )

        deadline = time.monotonic() + (self._operation_timeout_seconds * 4)

        while time.monotonic() < deadline:
            if start_button.is_disabled():
                return True

            page.wait_for_timeout(50)

        return False

    def _looks_authenticated(self, page: Page) -> bool:
        """
        Real, verified authenticated-session signal
        (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 2): the real
        dashboard shows a "New project" button; an unauthenticated
        visitor never does (the public marketing page shows "Create
        with Google Flow" instead). Works whether base_url is the
        dashboard or a project URL, since a project's own navigation
        bar/back button only renders for an authenticated session too -
        this checks account details instead when New project itself
        isn't present (i.e. base_url is a project, not the dashboard).

        Real-world finding, 2026-09-11: a real project has more than
        one internal view (the compose view vs. the "All media"
        library view, reachable via that project's own left-hand
        nav), and neither "New project" nor "Account details" is
        present on that library view, even for a fully authenticated
        session - confirmed directly by the account owner's own
        screenshot showing three intact, real generated videos while
        this method was reporting the profile unhealthy. The prompt
        box (prompt_input_css) is a persistent, always-visible compose
        bar shown on every real internal project view regardless of
        which left-nav tab is selected - the most view-independent
        real signal available, so it's checked last as a genuine
        alternative, never as a substitute for the other two checks'
        own real meaning.
        """

        if page.get_by_role("button", name=self._names.new_project_button).count() > 0:
            return True

        if page.get_by_role("button", name="Account details").count() > 0:
            return True

        return page.locator(self._names.prompt_input_css).count() > 0

    def _preflight(self, page: Page) -> None:
        """
        Verify the real prompt box and Start generation button are
        both present before touching anything credit-sensitive -
        matches GoogleFlowUIAdapter's own preflight discipline, using
        the real, verified controls instead of the fixture's.
        """

        missing = []

        if page.locator(self._names.prompt_input_css).count() == 0:
            missing.append("prompt_input")

        if (
            page.get_by_role("button", name=self._names.start_generation_button).count()
            == 0
        ):
            missing.append("start_generation_button")

        if missing:
            raise GoogleFlowUIChangedError(
                "UI_CHANGED: the following expected real Flow controls "
                f"could not be found: {', '.join(missing)}."
            )

    def _get_or_open_page(self, profile_id: str) -> Page:
        """
        Must only ever be called from inside the worker thread - same
        contract as GoogleFlowUIAdapter._get_or_open_page(), which its
        own docstring explains in full (the real-world bug fixed by
        reading a real persistent, already-authenticated profile
        instead of an ephemeral one).
        """

        existing = self._pages.get(profile_id)

        if existing is not None:
            if not existing.is_closed():
                return existing

            # Real-world finding, mirroring
            # FlowBrowserWorker._is_context_alive()'s own reasoning:
            # this adapter instance is long-lived (one shared instance
            # per the composition root, reused across an entire real
            # generation attempt'''s submit/observe/download sequence -
            # see src/desktop/services.py), so a page cached here can
            # easily outlive the browser context it belongs to. Even
            # after the worker itself recovers from a dead context
            # (evicting and reopening a fresh one), this cache would
            # still hand back the OLD, now-orphaned Page object
            # instead of ever asking the worker again - the exact
            # "Target page, context or browser has been closed" a real
            # operator hit via Check Connection. Evict and fall
            # through to resolve a fresh page from the (possibly
            # freshly-reopened) context instead.
            self._pages.pop(profile_id, None)

        directory = self._profile_directory_resolver(profile_id)
        context = self._worker.open_persistent_context_from_worker_thread(
            profile_id, directory, headless=self._headless
        )
        page = context.pages[0] if context.pages else context.new_page()
        self._pages[profile_id] = page

        return page


class _FlowSettingsUnavailableError(RuntimeError):
    """Internal only - a requested execution setting has no matching
    real control. Always caught by _drive_submission and turned into a
    FAILED transition; never escapes this module."""
