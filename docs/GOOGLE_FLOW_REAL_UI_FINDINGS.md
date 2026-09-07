# Google Flow: Real, Verified UI Findings (2026-09-07)

This document records facts about the **real, live Google Flow product**
(`https://flow.google.com`), confirmed by actually signing in with a real
account and driving a real, headless Playwright session against the real
authenticated profile - not the local fake-Flow fixture
(`tests/fixtures/fake_flow_ui.html`), and not guessed.

Everything below was captured on 2026-09-07 against account
`sairaqasimfareed@gmail.com`, one real generation (explicit human
go-ahead obtained first - see `PROJECT_PROGRESS.md`), read-only
otherwise. `GoogleFlowLocators` (`src/providers/google_flow/locators.py`)
still defaults to the fixture-only selectors for the existing adapter
test suite; this document is the source of truth for wiring up real
selectors next, so that work is traceable to real evidence rather than
assumption.

## 1. Base URL and auth

- Real base URL: `https://flow.google.com` (confirmed earlier - see the
  `VERIFIED_FLOW_BASE_URL` entry in `locators.py`).
- An authenticated session (real cookies, from a real sign-in) served at
  the bare root URL redirects straight to the dashboard, not the public
  `/about` marketing page - `/about` is what an unauthenticated or
  cookie-less browser always sees, regardless of path.
- Automated sign-in (Playwright driving the OAuth handshake itself) is
  actively rejected by Google ("Couldn't sign you in - this browser or
  app may not be secure"). The only path that works: a human signs in
  using a real, non-automated browser; Playwright afterward reads that
  already-established session from the same on-disk profile directory
  (see `src/browser/manual_signin_bootstrap.py`).

## 2. Dashboard (`https://flow.google.com/`)

Real accessible names, confirmed via Playwright's ARIA snapshot:

- `button "New project"` - creates a **real** new project. Never click
  this speculatively; it has a real, visible side effect on the
  account.
- `link "Open project"` with `/url: /project/<uuid>` - one per existing
  project, each paired with a `button "Edit project title"` and
  `button "Delete project"` (never click delete on an account that
  isn't ours to manage).
- `button "Account details"` containing a nested
  `button "Google Account: <name> (<email>)"` - confirms which account
  is signed in.
- A dismissible `region "Promotional banner"` ("Tools from creators like
  you") - decorative, not part of the generation flow.

## 3. Inside a project - the compose UI (`/project/<uuid>`)

With an empty prompt:

```
paragraph: What do you want to create?          <- placeholder text
button "Add ingredients to the prompt box"       <- reference/ingredient attach
button "Agent"                                    <- mode toggle, default OFF (unclicked = "without agent")
button "Settings trigger": Video · 360p · 8s x2  <- opens the settings popover; label mirrors current settings
button "Start generation" [disabled]              <- disabled while the prompt is empty
```

The prompt box itself is a ProseMirror rich-text editor, not a plain
`<textarea>`:

```html
<flow-rich-text-editor class="prompt-input">
  <div class="prosemirror-editor">
    <div contenteditable="true" translate="no" class="ProseMirror"> ... </div>
  </div>
</flow-rich-text-editor>
```

CSS locator confirmed to work: `.prompt-input .ProseMirror`. It has no
ARIA role, so it cannot be targeted via `get_by_role` - CSS remains the
right tool for this one control specifically (matches this file's own
"prefer role/name, CSS where role isn't available" guidance).

Typing a real prompt into it and letting hydration settle:

```
text: A calm lighthouse at sunset, gentle waves below.   <- the typed prompt is now plain text, not a placeholder
button "Clear prompt"                                     <- new: appears once the prompt is non-empty
button "Add ingredients to the prompt box"
button "Agent"
button "Settings trigger": Video · 360p · 8s x2
button "Start generation"                                  <- no longer disabled
```

**No separate "review"/"analyze" screen appeared before generation
started** for this specific (benign) prompt - clicking "Start
generation" went directly to the generating state. The user who ran
this session confirmed from real, prior personal use that Google Flow
**does** sometimes show an approve/review prompt (most likely
content-policy-triggered, not universal) - so `GoogleFlowGenerationState`'s
existing `CONFIRMATION_REQUIRED`/`CONFIRMING` states and the adapter's
existing confirmation-optional branch are both real and should stay
exactly as already built; this session's one real test simply took the
no-confirmation path.

## 4. Settings popover (opened via the "Settings trigger" button)

Full real vocabulary, confirmed via one real settings popover open:

```
radiogroup: Image / Video                         (checked: Video)
radiogroup: Frames / Ingredients                    (checked: Ingredients)
radiogroup: 16:9 / 9:16                             (checked: 16:9)
---
button "Select model family": Omni 1.1 Flash       <- opens a further model picker (not yet opened/explored)
radiogroup: 360p / 720p                             (checked: 360p; 360p has a tooltip: "generates faster at lower resolution")
radiogroup: 4s / 6s / 8s / 10s                      (checked: 8s)
radiogroup: x1 / x2 / x3 / x4                       (checked: x2 - this is VARIATION COUNT, i.e. how many
                                                        videos are generated per submission for the same
                                                        prompt, confirmed by the account owner - NOT a
                                                        multiplier on credits-per-variation by itself)
---
text: "Generating will use"
link "12 credits" -> https://support.google.com/googleone?p=g1_ai_credit_menu
```

So for this account's real settings at the time (360p, 8s, x2), one
submission actually costs **12 real Google One AI credits** - a real,
verified cost figure (not a USD estimate; Google's own credit system,
not something this codebase should try to convert to
`estimated_cost_usd` without separately verified pricing).

`"Select model family": Omni 1.1 Flash` was NOT opened further in this
session - the other model choices Flow's marketing page mentions
(e.g. Veo 3.1, Nano Banana) were not confirmed as selectable options
here. Treat as unverified until actually opened.

## 5. Generating state

Immediately after clicking "Start generation" (for a `x2` submission):

- The prompt box **clears itself** back to the empty placeholder state.
- Two new tiles appear at the top of the "All media" grid, each showing
  a shimmering placeholder image and the submitted prompt text
  underneath, each paired with a `button "Reuse prompt"`.
- A `"Videos"` entry appears in the left sidebar navigation (alongside
  `All media`/`Characters`/`Scenes`), which was not present before this
  project had any video.
- `button "Start generation"` immediately returns to `[disabled]` (prompt
  is empty again).

No distinct loading/progress percentage was observed in the accessible
tree during generation - the tiles simply render as still-placeholder
until they resolve.

## 6. Completion

For this real test, both tiles finished in well under a minute (already
showing real thumbnails by the third 10-second poll, i.e. within
roughly 30 seconds of clicking Start generation):

```
img "Generated video thumbnail"
text: 360p
```
(one pair per completed video)

## 7. Video detail / edit view (`/project/<uuid>/edit/<scene-uuid>`)

Reached by clicking a completed `img "Generated video thumbnail"`:

```
button "Lighthouse standing near gentle …"          <- editable scene title, text derived from the prompt
button "Favourite"
button "Share"
button "Download scene"                              <- THE real download control
button "Move to bin"
button "Show history"
button "More options"
button "Done editing scene": Done                    <- returns to the project grid
img "Scene video preview"
button "Mute"
text: "Current time: 00:00:00"
button "Skip to previous clip" / "Play" / "Skip to next clip"
text: "Total duration: 00:00:00"
button "Full screen"
button "Zoom out" / button "Zoom in" [disabled]
paragraph: "Describe how to edit this video…"        <- a SEPARATE prompt box, for iterative editing of this
                                                          existing scene, not the original creation flow
button "Add ingredients to the prompt box"
text: "Omni 1.1 Flash"                                <- the model actually used, shown here (confirms the
                                                          model-family label from the settings popover)
button "Start generation" [disabled]                  <- same control, repurposed here for "edit this scene"
```

`button "Download scene"` was located but not clicked in this session
(no need to actually download a file to prove the control exists and
is named predictably).

## 8. What this means for the codebase (not yet done - tracked here first)

The real UI's settings mechanism (a popover of radio-button groups) is
structurally different from `GoogleFlowLocators`'/the fake fixture's
assumed shape (a plain `<select>` dropdown read via
`page.select_option()`). Wiring real selectors into
`GoogleFlowUIAdapter` needs more than swapping locator strings - the
settings-selection *logic* itself (click "Settings trigger", then click
the matching radio button per desired dimension, then close the
popover) needs new adapter code, kept separate from the
fixture-matching path so the existing 16 fixture-driven tests keep
passing unchanged. This is the next concrete step, not yet built.
