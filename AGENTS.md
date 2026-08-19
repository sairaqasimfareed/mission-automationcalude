# AGENTS.md

## Purpose

This is the implementation contract for any AI coding session working on
this repository. It exists because this codebase has already grown two
disconnected content-generation stacks once (see
`docs/IMPLEMENTATION_STATE.md`), and the goal of this document is to make
sure a future session never does that again by accident.

Read this before writing code. Read `docs/IMPLEMENTATION_STATE.md` and
`docs/SYSTEM_TRACEABILITY_MATRIX.md` before touching a subsystem you
haven't worked in before.

## Rules

1. **Inspect the existing architecture before coding.** Grep for the
   capability you're about to build before writing a new model, service,
   or provider. If something adjacent already exists, extend it - don't
   build a parallel version because the existing one is inconvenient to
   read.

2. **Do not create duplicate subsystems.** One canonical persistence
   layer (`VideoJob` + `JsonJobStore`), one approval model
   (`ApprovalPolicyConfig`/`ApprovalDecision`), one provider-abstraction
   pattern per media type (`VoiceProvider`/`MusicProvider`/
   `SoundEffectProvider`/stock's `VisualAssetRouter`). If you think you
   need a second one, that's a sign to read the first one more closely,
   not a green light to add another.

3. **Preserve canonical persistence.** `VideoJob` is the single source of
   truth. New artifacts get one new optional field with a sensible
   default - never a second parallel store, never GUI-only state. See
   rule 4.

4. **Never treat GUI state as authoritative.** A view reads `VideoJob`
   from the job store, renders it, and dispatches actions back through a
   service. A view must not hold business state that isn't also on
   `VideoJob` (selection state like "which scenes are checked right now"
   is fine - a fact about the video is not).

5. **Follow selective invalidation rules.** Before changing an upstream
   artifact (script, research, scene plan), check
   `docs/SYSTEM_TRACEABILITY_MATRIX.md` and the invalidation matrix in
   `docs/ARCHITECTURE.md` for what depends on it. Don't silently leave a
   stale downstream artifact looking valid.

6. **Do not call a feature complete without tests.** A model without a
   test proving its validators reject bad input, a service without a
   test proving its failure path, a GUI stage without a test proving the
   handler doesn't crash on missing prerequisites - none of these are
   done. Match the existing per-service test convention (real service
   instances, no mocking framework, `_StubLLMService`-style stubs only
   for LLM/provider boundaries).

7. **Reconcile documentation after implementation, not before.** Update
   `docs/IMPLEMENTATION_STATE.md` and `docs/REMAINING_GAPS.md` as part of
   the same change, not as a separate follow-up task that never happens.
   A feature that isn't reflected in `IMPLEMENTATION_STATE.md` should be
   treated as not done yet by the next session that reads it.

## Non-negotiable engineering gate, every change

```text
mypy            (bare `mypy`, no path args - the real gate; files=["src"] in pyproject.toml)
ruff check
black --check
targeted pytest for the files you touched
full pytest suite
```

A pre-existing `UP042` ruff finding on every `(str, Enum)` class is a
known, accepted repo-wide convention - do not "fix" it as a drive-by. A
test failing only in a full-suite run and passing in isolation, on this
specific machine, for FFmpeg subprocess timing or Qt-threading timing
tests, is a documented environmental flake - confirm by re-running the
single test in isolation before treating it as a regression, and re-run
once more if the machine appears to be under heavy load (wall-clock time
far exceeding CPU time on the process is the tell).

## Git workflow

Commit locally with real messages. Do not push to the remote unless the
user explicitly asks. Never force-push, never amend a shared commit,
never skip hooks.

## Scope boundary

Google Flow, browser automation targeting Google Flow, or any
Flow-specific integration are explicitly out of scope. If a task
description implies automating a third-party product's web UI outside
its published API, stop and ask rather than building it.

## Where to look first

| Question | Look here |
|---|---|
| What already exists for X? | `docs/SYSTEM_TRACEABILITY_MATRIX.md` |
| Is X done, partial, or missing? | `docs/IMPLEMENTATION_STATE.md` |
| What's known-broken or deferred? | `docs/REMAINING_GAPS.md` |
| How do I know a change is really done? | `docs/ACCEPTANCE_CRITERIA.md` |
| What happens if the app dies mid-stage? | `docs/RECOVERY.md` |
| What's the overall system shape? | `docs/ARCHITECTURE.md` |
