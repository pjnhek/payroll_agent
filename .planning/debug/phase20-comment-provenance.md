---
status: resolved
trigger: "Phase 20 Nyquist validation: full pytest suite fails comment-provenance guard on five D-09/D-11 references."
created: 2026-07-18
updated: 2026-07-18
---

# Debug Session: Phase 20 Comment Provenance

## Symptoms

- Expected: `uv run pytest -q` completes without ticket or decision provenance in the scanned source tree.
- Actual: `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` reports five `D-09` / `D-11` citations.
- Error: the guard identifies comments in `app/db/repo/outbound_handoffs.py`, `tests/conftest.py`, `tests/test_phase20_clarification_review.py`, and `tests/test_send_idempotency.py`.
- Timeline: introduced by completed Phase 20 work; discovered during Nyquist validation on 2026-07-18.
- Reproduction: `uv run pytest -q -x`.

## Current Focus

- hypothesis: Confirmed — the comments explain a valid ownership boundary but use planning-decision labels prohibited by the permanent provenance guard.
- next_action: Complete: replace only the labels with reader-facing behavioral language and verify the guard plus full suite.

## Evidence

- timestamp: 2026-07-18
  observation: The guard reports exactly five decision-ID citations and no executable behavior failure.
- timestamp: 2026-07-18
  observation: The focused guard reproduced the same five violations, all in docstrings describing delivery-review handoff ownership; its scan record reported 178 files scanned.
- timestamp: 2026-07-18
  observation: Replacing the decision labels with equivalent reader-facing constraints removed the provenance citations without changing executable code.
- timestamp: 2026-07-18
  observation: The focused provenance guard passed (1 passed). Every test module in the full tests/test_*.py tree also passed under pytest; the modules were run concurrently only to fit the execution environment's per-command time window.

## Eliminated

- hypothesis: A runtime delivery or persistence behavior is broken.
  reason: The failure is limited to comment-provenance text.

## Resolution

- root_cause: "Five Phase 20 docstrings used D-09/D-11 planning-decision labels; the permanent guard correctly rejects those labels anywhere in its scanned source surface."
- fix: "Reworded the five docstrings to retain the delivery-review ownership and frozen-envelope constraints without provenance citations."
- verification: "Focused provenance guard passed (1 passed); every module in the full tests/test_*.py tree passed under pytest."
- files_changed:
  - app/db/repo/outbound_handoffs.py
  - tests/conftest.py
  - tests/test_phase20_clarification_review.py
  - tests/test_send_idempotency.py
  - .planning/debug/phase20-comment-provenance.md
