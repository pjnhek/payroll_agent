---
id: 260705-01
created: 2026-07-05
source: Phase 9 post-review conversation tracing (after codex cross-AI review)
resolves_phase:
priority: medium
files:
  - app/pipeline/orchestrator.py:667-724 (resume binding + misname guard)
  - app/pipeline/orchestrator.py:1039-1091 (capture gates in _clarify)
  - app/pipeline/orchestrator.py:1206-1218 (write side skips unbound candidates)
  - tests/test_alias_write.py:720-1100 (binding tests fake the resolved state)
---

# Alias-learning WRITE side is unreachable for new nicknames (circular evidence requirement)

## Problem

The automated nickname-learning loop (capture → bind → write) can never fire end-to-end
in production for a genuinely new nickname. Traced 2026-07-05, verified against live source:

1. Capture (`_clarify`) only fires when the token matches ZERO roster names/aliases
   (gate 4) → persists `alias_candidates = {token: None}`.
2. Binding at resume (NEW-2 misname guard) requires the SAME token to appear as the
   `submitted_name` of a DETERMINISTICALLY RESOLVED post-resume reconciliation entry —
   but reconcile only resolves exact-full-name or already-stored alias, and nothing in a
   reply changes the roster. The token that qualified for capture *by failing to resolve*
   must *resolve* one round later against unchanged data. Circular → unreachable.
3. Write side (`_write_aliases_if_safe`) hits `if employee_id_str is None: continue` and
   logs "alias write skipped … no resolved employee_id (never clarified)". Observable
   symptom on any real nickname round-trip.

Reply phrasing cannot fix it: "Bobby is Robert Nguyen" re-extracts as the canonical name
(token gone from submitted names → guard fails); keeping "Bobby" leaves it unresolved
(guard also fails); "Bobby Nguyen" is just a new unresolved token.

The misname guard itself is CORRECT (it killed the real learn-"Maria"-as-James misroute
bug) — the gap is that legit-nickname and misname cases are indistinguishable from
re-extraction evidence alone, so the guard blocks both. Money is never wrong; the cost is
the system re-asks about the same nickname every payroll, and the "human-confirmation
learning loop" in the project narrative is effectively read-only (aliases resolve if
seeded manually, are never acquired automatically).

Why tests are green: all binding tests inject a faked post-resume reconciliation where
the token resolved with `source: "alias"` — a state that presupposes the alias was
already learned. No end-to-end test exercises the loop with real resolution.

## Solution

Bind on EXPLICIT CONFIRMATION EVIDENCE instead of re-extraction evidence: the
clarification email already proposes a specific employee ("did you mean Robert Nguyen?"
via suggest_employees). Record the proposed token→employee mapping with the outbound
clarification; if the client's reply confirms that specific suggestion, bind
{token: suggested_employee_id} — the mapping is stated by a human in-round, not inferred
from a diff, so the misname guard's never-learn-from-inference intent is preserved
(nobody proposed "James" for "Maria", so the misroute case still can't slip through).
Keep the existing write-time collision re-check. Requires a small state addition
(persist the suggestion alongside alias_candidates) + a reply-confirmation detector —
design it WITH the clarify round machine redesign ([260705-02], WR-05/WR-06 cluster),
since round semantics and confirmation parsing interact.
