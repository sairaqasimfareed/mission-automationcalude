# Acceptance Criteria

## What "done" means for any capability

A capability is not done until all of these are true simultaneously:

1. **Model** - a real, validated Pydantic model, not a loose dict.
2. **Service** - business logic lives in a service, not in a GUI handler.
3. **Persistence** - the result is a field on `VideoJob` (or a model
   reachable from it) that survives a `JsonJobStore` round-trip.
4. **Restart behavior is defined** - does re-opening the project after a
   crash mid-stage correctly show what completed, and does re-running
   the stage either skip already-valid work or clearly redo it on
   purpose? (Most existing content-intelligence stages currently redo
   work unconditionally on re-run - see `docs/REMAINING_GAPS.md`.)
5. **GUI integration, where applicable** - reachable from a real button,
   not only callable from a test.
6. **Tests** - at minimum: model validators reject bad input; service
   happy path; service failure path; GUI handler doesn't crash on
   missing prerequisites (for GUI-reachable capabilities).
7. **Traceability row** - added to `docs/SYSTEM_TRACEABILITY_MATRIX.md`
   in the same change.
8. **Quality gate green** - `mypy` (bare, no path args), `ruff check`,
   `black --check`, targeted tests, and a full `pytest` run (or a
   documented, isolation-confirmed flake if one full-suite test fails).

A capability satisfying 1-3 and 5-8 but not 4 is **Partial**, not Done -
mark it that way in `docs/IMPLEMENTATION_STATE.md`.

## Definition of Done for the whole production-hardening effort

The golden path below must work end to end, and behave deterministically
under the failure modes listed after it:

```text
Create Project
      -> Define Audience / Strategy
      -> Create Story Architecture
      -> Generate Script
      -> Apply Approval Policy
      -> Plan Scenes
      -> Acquire/Create Assets
      -> Generate Narration/Music/SFX
      -> Build Timelines
      -> Render
      -> Final Preview
      -> Approve Final
      -> Export
```

Deterministic behavior required under:

- restart (at any boundary in the golden path)
- revision (script changed after downstream work already exists)
- provider failure (any provider call fails)
- missing asset (a scene has no resolved visual)
- rejected approval (a human returns a stage for revision)
- audio regeneration (narration/music/SFX redone after the fact)
- scene replacement (one scene's asset swapped after timeline exists)

Valid upstream work must be preserved whenever possible in every one of
these cases - see the selective-invalidation matrix once it exists
(`docs/REMAINING_GAPS.md` Phase 3).

## Per-phase acceptance (see `docs/REMAINING_GAPS.md` for the phase list)

Each phase in the gap register is accepted when:

- every checkbox in its section of `REMAINING_GAPS.md` is checked and
  removed from that file;
- the corresponding row(s) in `IMPLEMENTATION_STATE.md` say Done, not
  Partial;
- the corresponding row(s) exist in `SYSTEM_TRACEABILITY_MATRIX.md`;
- `PROJECT_PROGRESS.md` has a dated entry describing what shipped.

No phase is accepted on the basis of a description alone - the criteria
above require the artifacts to actually exist and be internally
consistent with each other.
