# Backlog

Ideas captured but not yet scheduled into a milestone phase. Promote via `/gsd-review-backlog`.

---

## Learn aliases from confirmed clarifications

**Captured:** 2026-06-21 (during Phase 2 live-gate tuning)
**Suggested home:** Phase 5 (Dashboard & Delivery) — fits the operator-confirmation flow.

**Idea:** When a `llm_nickname` (or low-confidence) match is gated to clarification and the
client/operator subsequently CONFIRMS that the submitted name does refer to a given employee,
**persist that submitted name as a `known_alias` on the employee** so the same nickname
resolves deterministically (Layer 1, confidence 1.0, no model call, no clarification) on every
future run. A real payroll system learns its clients' shorthand instead of re-asking weekly.

**Why deferred from Phase 2:** It's a new capability with design decisions that belong with the
Phase 5 operator gate, not the Phase 2 walking skeleton:
- **What counts as "confirmed"?** Auto-learn on any clarification reply (risky — the reply might
  correct the name, not confirm it), or only when the human operator approves the match at the
  Phase 5 gate (safer, human-in-the-loop — the natural fit).
- **Write-back path:** touches the resume/reply path + the `employees.known_aliases` persistence
  (currently aliases are seed-only). Needs a repo write + idempotency (don't double-add).
- **Eval impact:** alias-learning changes reconciliation behavior across runs; Phase 4's eval
  rides the same functions, so the learning must be reproducible/seedable for scoring.

**Acceptance sketch (for whoever plans it):** an operator-approved nickname match writes the
submitted name into the matched employee's `known_aliases`; a subsequent run with the same
nickname resolves at Layer 1 (deterministic, confidence 1.0) with no clarification.

---

## Field-regression clarification — "did you forget the overtime?"

**Captured:** 2026-06-24 (during Phase 6 ship, scoped against the live resume loop)
**Suggested home:** A small standalone phase AFTER Phase 6 ships (do not insert into Phase 6 — it
is the ship/demo spine; this needs design time, not a rushed insert). Owner decision: backlog it.

**Idea:** When a clarification reply silently drops or changes a money-affecting field the original
submission mentioned (canonical case: original says "Person A: 40 hrs + 2 OT", the bot clarifies a
name, the client re-replies "40 hrs for Person A" with no OT), the bot should notice the OT
regression and ask **once** ("Your first email listed 2 hrs overtime for Person A; your reply
didn't mention it — keep it, or is it 0 now?") before processing. On-thesis: extends "every
money-moving judgment is a deterministic code gate, never a guess" to "and we catch when a reply
quietly changes the money."

**Grounded findings (verified against the code 2026-06-24 — read before planning):**
- Resume **re-extracts over the MERGED original + reply** body (`orchestrator.py:138-139`,
  `_combined_context_email`), NOT the reply alone. So the original OT text is still in the LLM
  context on resume — the naive "reply drops OT → wrong paycheck" failure is **largely already
  prevented** by the merge. The real gap is narrower than it first appears.
- `extracted_data` is **OVERWRITTEN wholesale on resume** (`orchestrator.py:243`, `persist_extracted`
  "never appended") — there is NO preserved pre-clarification snapshot, so nothing can compare
  original-vs-reply today.
- OT is only treated as a "required/missing" field in two narrow cases (`validate.py:108-139`):
  weekly employee >40 regular hrs, or biweekly >80, both with no/zero OT. Outside those thresholds
  a missing OT is silently allowed. D-05 (`validate.py:113`) treats absent and explicit-zero
  identically for ambiguity — BUT the extractor DOES distinguish `None` from `Decimal("0")`
  (`contracts.py:76` `hours_overtime: Decimal | None`), so the signal needed for "absent vs
  intentional zero" exists.
- `decide.py` (rules at `decide.py:13-31`, impl `86-140`) has no field-regression rule; gate
  reasons are name-unresolved, missing-required-field, run-level collision only.

**Mechanism (Small–Medium, ~half-to-full day of code):**
1. At the `awaiting_reply` pause, copy `extracted_data` into a new `pre_clarify_extracted` JSONB
   cell BEFORE resume overwrites it (one column + one repo write).
2. Pure helper `detect_field_regression(original, resumed) -> list[FieldDrop]` — deterministic,
   fully unit-testable; compares OT (and optionally hours) per resolved employee for
   present→absent or value-changed. Fits the "pure function over facts" spine.
3. New `field_regression` gate reason in `decide.py` feeding the EXISTING `request_clarification`
   path — reuses compose_clarification, the suggestion call, the awaiting_reply pause, and resume.
4. One clarification template line.

**The two design traps (this is where the real work is, NOT code volume):**
- **Clarify-loop trap:** bot asks about OT → client replies again without restating → bot asks
  again forever. REQUIRED guard: "already asked about this field on this run → carry the original
  value forward and process, do NOT re-ask." **Owner decision: clarify ONCE, then carry-forward.**
  Needs a per-run record of which fields were already clarified (e.g., a flag on the run or a
  field-set in the decision JSONB).
- **D-05 absent-vs-explicit-zero:** "client didn't restate OT" (→ clarify once / carry forward)
  must be distinguished from "client explicitly wrote 0 OT" (→ honor it, never ask). The
  `None` vs `Decimal("0")` signal exists in the contract; the gate must use it or it will either
  nag on legitimate corrections or miss real drops.

**Acceptance sketch (for whoever plans it):** original submission has OT=2 for a resolved employee;
a clarification reply that omits OT triggers exactly ONE clarification asking to confirm keep-2-or-
make-it-0; if the client confirms 0, process with 0; if the client still doesn't address it on the
next reply, carry forward the original OT=2 and process (no second clarification). An explicit
"0 OT" in the reply is honored silently with no clarification. Fully covered by unit tests on the
pure `detect_field_regression` helper + an integration test of the once-then-carry-forward loop.

**Related:** the confidence-rubric change (Phase 2, 2026-06-21) that makes `llm_nickname` gate
at 0.75 is what makes this valuable — without learning, every nickname re-asks forever.
*(Superseded note: 2.1 removed the confidence rubric entirely — the alias-learning value now
rests on the deterministic `source="none"` clarify path instead, but the idea is unchanged.)*

---

## Atomic status claim — close the resume/approve race (Phase 5 idempotency)

**Captured:** 2026-06-22 (Codex review round 3 of Phase 2.1 — independently rediscovered the
known CR-02 residual).
**Suggested home:** **Phase 5 (Dashboard & Delivery)** — it is already scoped here via
**FOUND-04** (`SELECT ... FOR UPDATE` against double-approval), **CLAR-04** (idempotent sends),
and **INGEST-05** (idempotent re-trigger). This is the implementation detail of those three.

**Problem (HIGH, found 3× now — overnight code-review CR-02, then Codex 2.1 round 3):** the
run status guards are **load-then-set, not atomic**. In `app/pipeline/orchestrator.py`
`resume_pipeline`, two distinct clarification replies can BOTH read `status == awaiting_reply`,
BOTH set `EXTRACTING`, and BOTH run stages / send / replace line items → double-resume. The
operator approve/reject path (`app/main.py`) has the same race → double-pay / double-send. The
initial run claim is similarly unguarded. The in-code comment in `resume_pipeline` already
documents this as the accepted Phase-2 minimum, deferred here.

**Fix:** an atomic claim helper in `app/db/repo.py` —
`UPDATE payroll_runs SET status = %s WHERE id = %s AND status = %s RETURNING id` (claim succeeds
only if the row was still in the expected status), or `SELECT ... FOR UPDATE` inside the
transaction. Use it for **(a)** resume (claim `awaiting_reply → extracting`), **(b)** approve/reject
(claim the pending status), and **(c)** the initial run claim. A losing concurrent caller gets no
row back and drops cleanly (logs a late/duplicate, does not re-run). This is exactly the
FOUND-04 `FOR UPDATE` guard Phase 5 already promises.

**Why not in 2.1:** 2.1 was a decisioning re-architecture; this is concurrency/idempotency work
that belongs with the Phase 5 operator gate (where approve/reject and re-trigger are built), so
the claim helper is written once and used across all three paths. Pulling it into 2.1 would have
been scope creep into Phase 5. The current Phase-2 status-precondition removes the WIDE window;
the atomic close is the Phase 5 deliverable.

**Acceptance sketch (for whoever plans Phase 5):** two concurrent approvals of the same run
result in exactly ONE `approved → sent → reconciled` advance and ONE outbound send; two
concurrent clarification replies resume the run exactly once; a re-triggered errored run cannot
double-process. Tested with a concurrency/locking test against the live (or a transactional) DB.

---

## Over-40-no-OT validation rule — close the silent OT under-pay hole

**Captured:** 2026-06-22 (Phase 3 discuss-phase review — direct safety consequence of the
Phase 3 calc decision D-03 "explicit OT only, never auto-split").
**Suggested home:** its **OWN small focused insertion BEFORE Phase 5** (e.g. Phase 3.1 or a quick
task). Explicitly NOT bundled into Phase 3's penny-tax calc work (keep that pure for the hard
part), and explicitly NOT parked in Phase 5 — a silent money-guard in a never-wrong-on-money
project should not ride two phases out, where it's exactly the kind of item that slips or gets
under-specified once Phase 5 context loads. The rule only emits a `ValidationIssue` into the
clarification gate already built and tested in Phase 2, so it can land the moment there's a clean
hour. Sequencing is the planner/manager's call; the constraint is **before Phase 5**.

**Problem:** Phase 3 D-03 makes the calc trust the submitted OT split and never auto-derive OT
(correct — biweekly/semi-monthly employees submit PERIOD totals, and the calc has no workweek
concept). But that opens a **silent under-payment**: a weekly employee who writes "45 hours" with
no OT field gets 45 straight-time hours and **loses the OT premium**. Under-paying is worse than
over-paying for this project's thesis.

**Fix (per-WORKWEEK, NOT a flat ">40"):** FLSA overtime is per workweek, and only weekly and
biweekly periods map cleanly onto whole workweeks. Add a `validate.py` rule: **flag when
`hours_regular` exceeds 40 × (whole workweeks in the period) with no `hours_overtime` field →
emit a `ValidationIssue` that gates the run to clarification.**
- **Weekly (`pay_periods_per_year=52`, 1 workweek):** `hours_regular > 40`, no OT → clarify.
- **Biweekly (`=26`, 2 workweeks):** `hours_regular > 80`, no OT → clarify (>80 guarantees a week
  passed 40, so OT must exist; the clarification asks for the split since the amount is unknowable
  from the total).
- **Semi-monthly (`=24`) / Monthly (`=12`):** boundaries cut across workweeks → period total
  cannot reveal OT → **documented limitation, no flag** (this is the only place a README "client
  must state OT explicitly" line is correct — for the undetectable slice only).

The detectable frequencies (52, 26) are exactly the two the seed already covers, so it's testable
against seeded employees immediately.

**Why it's worth its own slot (not cleanup):** it's also a demo beat — weekly "Bob worked 45
hours" with no OT field producing "is that 40 regular + 5 overtime, or 45 straight?" puts the
never-wrong-on-money thesis on camera, catching a money-affecting ambiguity instead of silently
under-paying.

**Acceptance sketch (for whoever plans it):** a weekly fixture with `hours_regular=45` and no
`hours_overtime` produces a `ValidationIssue` and `decide.py` gates the run to
`request_clarification`; a biweekly fixture with `hours_regular=85` and no OT does the same; a
biweekly fixture with `hours_regular=78` does NOT flag; a semi-monthly/monthly fixture over 40/wk
does NOT flag (documented limitation). Calc behavior (D-03) is unchanged — the catch is purely in
validation, upstream of the workweek-agnostic calc.
