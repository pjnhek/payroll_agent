---
phase: 20-exactly-once-send
plan: 16
subsystem: ui
tags: [fastapi, jinja2, clarification, delivery-review, exactly-once, safety]

# Dependency graph
requires:
  - phase: 20-13
    provides: purpose-aware final-lease review markers and the same-row clarification retry facade
  - phase: 20-14
    provides: current-epoch outbound lookup and body-free delivery-review projection
  - phase: 20-15
    provides: fake repository parity for purpose-aware review and clarification retry
provides:
  - purpose-aware confirmation and clarification delivery-review route loading
  - frozen clarification question evidence with isolated retry, handled, and reject actions
  - fail-closed guards preventing generic alias resolution and retrigger recovery
  - server-rendered clarification review card and safety regressions
affects: [dashboard, clarification delivery, alias learning, durable send review]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - delivery-review markers are matched to the outbound purpose before projection or mutation
    - clarification ambiguity uses the same immutable snapshot and durable job without confirmation controls
    - incomplete review evidence fails closed before generic operator recovery

key-files:
  created:
    - tests/test_phase20_clarification_review.py
  modified:
    - app/routes/runs.py
    - app/templates/run_detail.html
    - app/static/style.css
    - tests/test_dashboard.py

key-decisions:
  - "ClarificationDeliveryReview accepts only clarification and clarification_field_regression snapshots; DeliveryReview remains confirmation-only."
  - "Clarification retry calls advance_existing_clarification_delivery_review_job_due_now on the existing row and never creates a slot or provider call."
  - "Malformed or missing-snapshot delivery-review markers render a bounded unavailable state and cannot fall through to alias resolution or generic retrigger."

patterns-established:
  - "Use load_delivery_review_snapshot for bounded facts and load_outbound_snapshot only for authorized frozen artifact evidence."
  - "Purpose-specific POST actions perform only fenced CAS/retry operations and wake the queue after commit."

requirements-completed: [SEND-02, SEND-03]

coverage:
  - id: D1
    description: "Confirmation and clarification delivery ambiguity load purpose-matched frozen evidence and expose isolated actions."
    requirement: SEND-02
    verification:
      - kind: unit
        ref: "uv run pytest -q tests/test_phase20_clarification_review.py tests/test_dashboard.py tests/test_clarify.py tests/test_alias_write.py tests/test_send_idempotency.py"
        status: pass
      - kind: automated_ui
        ref: "tests/test_dashboard.py::test_clarification_delivery_review_card_is_purpose_isolated"
        status: pass
    human_judgment: false
  - id: D2
    description: "Server-rendered clarification review presents frozen-question evidence and retry/handled/reject choices without alias or provider diagnostics."
    requirement: SEND-03
    verification:
      - kind: automated_ui
        ref: "tests/test_dashboard.py::test_clarification_review_projection_is_bounded_and_question_is_frozen"
        status: pass
      - kind: unit
        ref: "tests/test_phase20_clarification_review.py::test_delivery_review_marker_blocks_retrigger_before_context_clear_or_enqueue"
        status: pass
      - kind: manual_procedural
        ref: "Browser inspection of confirmation and ClarificationDeliveryReview cards"
        status: unknown
    human_judgment: true
    rationale: "Automated TestClient rendering proves labels, targets, and safety boundaries; visual legibility and real operator interaction still require a browser check."

# Metrics
duration: ~15min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 16: Clarification Delivery Review Summary

**Purpose-aware clarification delivery review with frozen-question replay, provider-free outcomes, and generic-recovery guards.**

## Performance

- **Duration:** approximately 15 minutes
- **Started:** 2026-07-17T16:19:31-07:00
- **Completed:** 2026-07-17T16:30:31-07:00
- **Tasks:** 2/2
- **Files modified:** 5 implementation/test files, plus this summary

## Accomplishments

- Delivery-review loading now pairs `DeliveryReview` with confirmation and `ClarificationDeliveryReview` with clarification or field-regression snapshots, including bounded final-lease evidence.
- Clarification review reads the exact stored subject, body, RFC threading headers, Message-ID, and attachment bytes, then offers only same-row retry, handled, or reject actions. Retry uses `advance_existing_clarification_delivery_review_job_due_now`; handled and reject never call the provider or write aliases.
- Generic resolve and retrigger paths are blocked before roster/alias work, reply-context clearing, pipeline enqueue, or restart. The dashboard has a distinct clarification card and a fail-closed unavailable state.

## Task Commits

Each task followed the required RED/GREEN sequence:

1. **Task 1 RED: add clarification delivery-review controller regressions** — `2177e8f` (test)
2. **Task 1 GREEN: isolate clarification delivery-review actions** — `f0b72a8` (feat)
3. **Task 2 RED: add clarification review dashboard regressions** — `2430f63` (test)
4. **Task 2 GREEN: render isolated clarification review card** — `5beb48c` (feat)
5. **Safety correction: fail closed on incomplete review markers** — `ff93c00` (fix)
6. **Quality correction: normalize test imports** — `a204fa4` (style)

The summary metadata is committed separately after self-check.

## Files Created/Modified

- `app/routes/runs.py` — purpose-aware review loader/projection, frozen clarification artifact routing, isolated clarification actions, and generic recovery guards.
- `app/templates/run_detail.html` — distinct confirmation/clarification review branches and bounded missing-evidence state.
- `app/static/style.css` — compact clarification review card styling.
- `tests/test_phase20_clarification_review.py` — controller, frozen evidence, same-row retry, provider-free outcome, and guard regressions.
- `tests/test_dashboard.py` — rendered card, bounded projection, action target, and no-alias/no-provider-diagnostic assertions.

## Verification

- `uv run pytest -q tests/test_phase20_clarification_review.py tests/test_dashboard.py tests/test_clarify.py tests/test_alias_write.py tests/test_send_idempotency.py` — **127 passed, 5 skipped**.
- `uv run pytest -q -rs` — **1144 passed, 82 skipped**.
- `uv run mypy app/routes/runs.py` — **passed**.
- `uv run ruff check app/routes/runs.py tests/test_dashboard.py tests/test_phase20_clarification_review.py` — **passed**.
- Server-rendered TestClient checks cover both review cards, frozen question routes, action targets, and absence of generic alias controls.

## Unavailable Evidence

Live Postgres settlement, epoch, queue, and concurrency proofs were skipped because `DATABASE_URL` and `ALLOW_DB_RESET=1` were not configured. The exact plan suite had 5 such skips; the full suite had 82 guarded live-DB/live-LLM skips. These are unavailable evidence, not passing database proofs.

## Human Check Required

Open one confirmation delivery review and one `ClarificationDeliveryReview` run in a browser. Confirm the clarification card visibly shows the frozen question plus **Retry same question**, **Mark handled**, and **Reject** only; confirm confirmation alone shows typed new-confirmation authorization; and confirm neither card exposes raw provider diagnostics or generic Resolve & Resume/remember-alias controls. No browser session was available during this execution.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical safety guard] Prevented incomplete delivery-review markers from falling through to generic operator resolution.**

- **Found during:** final controller/UI safety pass
- **Issue:** A marker with missing or malformed frozen evidence could otherwise render the generic needs-operator alias-resolution branch.
- **Fix:** Guarded all delivery-review markers before generic recovery and rendered a bounded unavailable state when the purpose-specific review cannot load.
- **Files modified:** `app/routes/runs.py`, `app/templates/run_detail.html`
- **Verification:** focused dashboard/controller suite and full suite passed.
- **Committed in:** `ff93c00`

**2. [Rule 3 - Blocking quality issue] Fixed import ordering in the new controller test module.**

- **Found during:** ruff verification
- **Issue:** Ruff rejected the new test module's standard-library import order.
- **Fix:** Applied Ruff's import organization.
- **Files modified:** `tests/test_phase20_clarification_review.py`
- **Verification:** `uv run ruff check ...` passed.
- **Committed in:** `a204fa4`

**Total deviations:** 2 auto-fixed issues. Both were directly required for safety or completion; no architectural scope changed.

## Known Stubs

- `app/templates/run_detail.html:197` — “Delivery review unavailable” is an intentional fail-closed state for missing snapshot evidence, not an unfinished implementation.
- `tests/test_dashboard.py` contains pre-existing missing-file “placeholder” assertions and an empty-roster fixture used to prove graceful degradation; these are test fixtures, not user-facing clarification data.

## Issues Encountered

`ruff format --check` reports that the existing large route/dashboard files would be reformatted. The plan requires Ruff lint, which passes; a broad formatting rewrite was not applied because it would create unrelated churn.

## User Setup Required

None for automated verification. A browser inspection remains the human check described above.

## Next Phase Readiness

The clarification and confirmation delivery-review surfaces now share frozen evidence boundaries while keeping purpose-specific actions separate. Phase 21 can consume the route/test evidence; rerun the guarded Postgres proofs and browser check in an environment with database access.

---
*Phase: 20-Exactly-Once Send*
*Plan: 20-16*
*Completed: 2026-07-17*

## Self-Check: PASSED

- Summary file exists at the expected phase path.
- All six implementation/test commits listed above are present in git history.
- `git diff --check` passed for the summary.
- `.planning/STATE.md` remains the pre-existing orchestrator-owned unstaged edit; `.planning/ROADMAP.md` was not modified or staged.
