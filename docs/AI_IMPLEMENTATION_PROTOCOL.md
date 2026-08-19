# AI Implementation Protocol

This is the phase-execution protocol for the production-hardening
effort tracked in `docs/REMAINING_GAPS.md`. `AGENTS.md` is the standing
contract (what never to do); this document is the process for each unit
of work within that contract.

## Steps for every phase

1. Inspect the current implementation first - read the relevant rows in
   `docs/SYSTEM_TRACEABILITY_MATRIX.md` and `docs/IMPLEMENTATION_STATE.md`
   before writing anything.
2. Identify exact gaps against `docs/REMAINING_GAPS.md`'s checklist for
   that phase.
3. Reuse existing functionality - a phase that adds a new model or
   service should be able to point at what it's extending.
4. Avoid duplicate subsystems (see `AGENTS.md` rule 2).
5. Make the smallest sound architectural extension that closes the gap -
   not the largest one that's theoretically more complete.
6. Define persistence/restart behavior explicitly as part of the design,
   not as an afterthought - "what does this look like after a restart
   mid-stage" is a real question for every new stage.
7. Preserve backward compatibility - new `VideoJob` fields get sensible
   defaults; nothing about an existing saved project should stop loading.
8. Add focused tests matching `docs/ACCEPTANCE_CRITERIA.md`.
9. Run the full quality gate: `mypy` (bare), `ruff check`, `black
   --check`, targeted tests for changed files, then the full `pytest`
   suite.
10. Reconcile documentation before calling the phase complete -
    `IMPLEMENTATION_STATE.md`, `REMAINING_GAPS.md`,
    `SYSTEM_TRACEABILITY_MATRIX.md`, and a dated entry in
    `PROJECT_PROGRESS.md`, all in the same change.

## Phase sequence

Matches `docs/REMAINING_GAPS.md`'s section order:

| Phase | Focus |
|---|---|
| 0 | Audit and control layer (this set of documents) |
| 1 | Approval runtime gating + decision history |
| 2 | Readiness service + typed blocker model |
| 3 | Selective invalidation matrix |
| 4 | Unified production audio hardening ("Generate All Audio") |
| 5 | Final Preview |
| 6 | Render identity + asset provenance |
| 7 | Budget gating beyond LLM calls |
| 8 | Dry-run as an explicit execution mode |
| 9 | GUI: persistent project header + recovery UX |
| 10 | CI, pre-commit, remaining testing gaps |

Phases are sequenced by dependency where one exists (Phase 5's Final
Preview depends on Phase 6's render identity; Phase 4's script-identity
binding depends on Phase 1's decision history) - see the individual
phase notes in `REMAINING_GAPS.md` for the specific dependency. Where no
dependency exists, phases are ordered by leverage: cheapest and most
unblocking first.

## What "no giant rewrite" means in practice

Every phase should be committable and shippable on its own, the same way
each content-intelligence sprint earlier in this project's history was
(see `PROJECT_PROGRESS.md`). If a phase's diff starts touching files
outside the capability it's supposed to close, stop and reconsider scope
before continuing.
