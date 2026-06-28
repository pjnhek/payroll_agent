# Phase 7: Money-Correctness Deepening (Pure-Function Gates) - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning

> **⚠ SCOPE OVERRIDE (2026-06-27 — supersedes the "In scope" line below):** Phase 7 was re-scoped to
> **MONEY-01 + MONEY-02 ONLY**. **MONEY-03 (field-regression) was moved to the new Phase 7.5** after
> three cross-AI review rounds (see `07-REVIEWS.md`) showed its resume state machine needs a
> `_run_stages` split refactor as a foundation. **Do NOT plan MONEY-03 work in this phase.** The
> MONEY-03 decisions (D-08..D-30) below are RETAINED as the design record that Phase 7.5 inherits —
> they are NOT a Phase 7 deliverable. The ROADMAP §"Phase 7" success criteria (only SC1 + SC2) are
> authoritative for what this phase plans. Phase 7 MAY still land forward-compatible *scaffolding* —
> the `field_regression` `ValidationIssue` Literal value and the `FieldDrop`/`RawFieldDrop` models —
> so Phase 7.5 builds on a stable contract; these are harmless no-ops in Phase 7 (nothing emits
> `field_regression` here). `_is_paid` (D-09) IS a Phase 7 deliverable (MONEY-01 needs it).

<domain>
## Phase Boundary

Close two **silent-mispay** paths in the shipped pure-function judgment layer so the core thesis —
"never silently pays wrong" — holds against messy real input, not just the demo path. Brownfield
correctness fixes on `validate.py` (MONEY-01) and `reconcile_names.py` (MONEY-02). TDD throughout —
a failing test first for every fix. *(MONEY-03's field-regression rule is Phase 7.5; see scope override above.)*

**In scope (Phase 7, post-split):** MONEY-01 (zero-hours $0 gate), MONEY-02 (Unicode NFC name normalization). **MONEY-03 → Phase 7.5 (do NOT build here).**

**Out of scope (belongs to later v2 phases, do NOT build here):** atomic multi-write transactions / crash-idempotency at the DB layer (Phase 9), webhook-dedup CAS and stuck-run recovery (Phase 9), the concurrency/load proof test (Phase 10), schema indexes + `error_detail` enrichment + `SELECT *` removal (Phase 8). Where Phase 7's resume sequencing **touches** atomicity, see D-13/D-14 below — Phase 7 specifies the *ordering invariant*; the broader transaction hardening is Phase 9's. Cross-reference, do not double-build.

</domain>

<decisions>
## Implementation Decisions

### MONEY-01 — Zero-hours silent $0 (target: `app/pipeline/validate.py` `any_hours`, ~line 84)
- **D-01:** The bug: `any_hours = any(getattr(emp,f) is not None ...)` lets an HOURLY employee with `hours_regular=Decimal("0")` (all else absent) PASS the gate → `$0` gross → `$0` paystub ships. The reconciliation backstop **cannot** catch this (`$0` is arithmetically self-consistent), so this gate is the only defense.
- **D-02:** **Fix rule:** for an HOURLY employee, gate to `request_clarification` when EVERY one of the five hours fields is absent-OR-explicit-0 — i.e. **no field is present AND `> 0`**. Concretely: replace the `is not None` predicate with the shared `_is_paid` predicate (D-09).
- **D-03:** **Edges (locked):**
  - A genuine partial week still processes (e.g. `hours_regular=0` but `hours_holiday=8` → `holiday>0` → not gated).
  - **Salaried untouched** — it computes from `annual_salary` and legitimately reports no hours; it never reaches this gate.
  - Does **NOT** gate `regular=40 + OT=0` — that is a valid full week already owned by the separate **D-05 over-40 guard** (`validate.py:102–140`); gating it here would clarify normal payroll and contradict D-05. This fix composes with D-05, it does not overlap it.
  - **`pay_type` null/unknown ⇒ fail-safe = treat as "could be hourly" and APPLY the gate** (clarify rather than silently process). Do not skip the guard on unknown pay_type.
  - **Negative hours:** already safe upstream — `ExtractedEmployee` is `Decimal | None + ge=0 + extra="forbid"` (`contracts.py:75–80`); a negative value fails at the EXTRACTION parse boundary → one reflective retry → ERROR, and never reaches `validate()` as a typed value (see `validate.py:15–20` docstring). **Do NOT add a dead negative-hours guard in validate.py** — the typed path structurally cannot carry a negative.

### MONEY-02 — Unicode NFC (target: `app/pipeline/reconcile_names.py` `_norm`, ~line 32)
- **D-04:** The bug: `_norm` does `" ".join(name.split()).casefold()` — whitespace + casefold only, **not** NFC. "José" (NFC) won't resolve "José" (NFD decomposition) → silent fail-to-resolve.
- **D-05:** **Fix (hardened form):** apply `unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).casefold())`. The double-NFC-around-casefold is deliberate — `casefold()` *can* de-normalize its output, so the canonical caseless form is NFC(casefold(NFC(s))), not the naive NFC-then-casefold. Cheap insurance; "locked" is exactly where this kind of bug hides.
- **D-06:** **`_norm` is the single chokepoint — confirmed.** It is the only name-normalizer; every other caller (`orchestrator.py:198/204/346/348`, `roster.py` references) imports *this same* function. The fix is symmetric across roster names and submitted names by construction. **Conservative choice: NFC over NFKC** (NFKC would fold compatibility chars too aggressively for names) — keep NFC.
- **D-07:** Test: the previously-failing NFD case now resolves to the same employee (assert same `matched_employee_id`).

### MONEY-03 — Field-regression clarification (the design-heavy fix; NEW code)
Scenario: original "40 + 2 OT", reply "40" (no OT) → reply silently drops OT → underpay. Must clarify **once** ("did you forget the overtime?"), then carry the original value forward — never an infinite re-clarify loop.

**Detection scope:**
- **D-08:** Watch **all five hours fields** (`hours_regular`, `hours_overtime`, `hours_vacation`, `hours_sick`, `hours_holiday`) for a regression. `contribution_401k_override` and salary are **excluded** (rarer real case, more false-positive surface). The OT example is just the headline.
- **D-09 (load-bearing — shared predicate):** Factor out **`_is_paid(v) = v is not None and v > 0`** and call it from THREE sites: `any_hours` (MONEY-01), `detect_field_regression` (MONEY-03), and align it with D-05's existing `ot_missing = ot is None or ot == 0`. **Rationale:** if detect defines presence as `is not None`, then `OT 2→0` is a "change" → honored silently → OT zeroed → silent underpay = the exact bug MONEY-03 exists to prevent. The shared predicate makes `2→0` a **drop**, not a silent change. One predicate, three call sites, zero disagreement on the zero boundary.
- **D-10 (trigger = DROP ONLY):** Clarify only on present→absent (where "present" = `_is_paid` true, so `2→0` counts as a drop per D-09). A genuine value **increase or change** that is still paid (`OT 2→3`) is the client deliberately correcting — honored silently, never second-guessed. A reply EXISTS to change values; clarifying every correction defeats its purpose.
- **D-11 (diff set):** Compare only employees resolved to the **SAME roster `employee_id` in BOTH** the pre-clarify and post-reply extractions. A newly-resolved employee (the reply's actual purpose) has no pre-baseline and is correctly skipped; a restated name still follows its `employee_id`. This is robust against name-resolution false positives (mis-guess → corrected to a different id → not in diff set → skipped).
- **D-12 (multi-line same employee):** `calculate.py` currently emits one `PaystubLineItem` **per extracted entry with no dedup** (verified, `calculate.py:286–289`), so two lines for one employee is undefined for the diff. Apply a **symmetric reduction keyed by `employee_id`** to BOTH the snapshot and the resumed extraction *before* diffing. **Default: last-wins** (the correction line supersedes). The reduction MUST be identical on both sides or it manufactures phantom drops / misses real ones depending on line ordering. *(Researcher: confirm no hidden multi-line assumption elsewhere in calc.)*

**Loop guard, carry-forward, and the explicit-drop outcome:**
- **D-13 (guard carries an OUTCOME, not a count):** `clarified_fields` is a NEW nullable **JSONB column on `payroll_runs`**, mirroring the existing `alias_candidates` scratch pattern. Shape: `{employee_id: {field: outcome}}` where `outcome ∈ {asked, carried_forward, confirmed_dropped}`. **Rationale (the deepest catch):** a clarification reply is NOT silence. The client's reply to "did you forget the OT?" might be *"no — remove it."* A count-only guard would backfill OT=2 anyway → overpay AND ignore an explicit instruction. Carrying an outcome distinguishes "ignored the question again" from "answered: remove it."
- **D-14 (explicit-drop honored):** A reply that **explicitly zeroes** the field (the client saying "remove it" → re-extraction yields an explicit `0`) resolves to **`confirmed_dropped` → NO backfill**, honored. Only true silence (field still absent, no explicit zero) resolves to **`carried_forward` → backfill**.
- **D-15 (context-aware predicate interaction with MONEY-01):** In the *regression-reply context*, an explicit `0` means **resolved/deliberate** — the OPPOSITE of MONEY-01's "explicit 0 on a fresh submission = clarify." MONEY-01 runs on a *fresh* extraction (0 = suspicious); the regression-outcome check runs on a *reply to a specific question* (0 = answer). **The `clarified_fields` outcome (`confirmed_dropped`) MUST short-circuit BEFORE MONEY-01 re-flags the same field**, or a confirmed-removed field loops back into clarification.
- **D-16 (carry-forward mechanism):** When the guard resolves to `carried_forward`, **backfill** the dropped field's original value **from the `pre_clarify_extracted` snapshot INTO the post-resume `extracted_data`** BEFORE validate/decide/calc run. The snapshot is the authoritative original; backfilling makes `extracted_data`, the paystub, and the reconciliation all agree on one source of truth, and the operator gate's honest leftmost column stays truthful.

**Detection seam (keeps it eval-testable and DRY):**
- **D-17 (pure helper → ValidationIssue):** A standalone PURE helper **`detect_field_regression(original, resumed) -> list[FieldDrop]`**. Its result is passed into **`validate()` via a NEW optional `prior=None` kwarg**; `validate()` emits a `ValidationIssue(issue_type="field_regression")`. **`decide.py` is UNCHANGED** — it already gates `request_clarification` on any missing/issue, so the regression becomes "just another validation issue." The eval scores it through the same `validate` path it already imports.
- **D-18 (DRY spine preserved):** Fresh runs call `validate(..., prior=None)` (a true no-op — every existing test and behavior preserved); resume passes the snapshot. `_run_stages` stays a **single shared function**; the orchestrator decides what to pass. One optional kwarg, default behavior unchanged.

**New storage + crash-ordering invariants (Phase-7-local; broader atomicity is Phase 9):**
- **D-19 (snapshot cell, snapshot-once):** A NEW `pre_clarify_extracted` JSONB cell, written at the `awaiting_reply` pause **only when `pre_clarify_extracted IS NULL`**. The snapshot-once `IS NULL` guard prevents a later round (e.g. a name-clarify, then a field-drop reply) from advancing the baseline past the **original** intent. The snapshot is treated **read-only** by resume.
- **D-20 (termination ordering — the actual halt mechanism):** In the resume sequence, **backfill MUST precede `validate(..., prior=snapshot)`** so that on pass 2 detect finds no drop and emits nothing. Because `decide.py` gates on *any* issue, a single stray `field_regression` issue on pass 2 is an **infinite loop**. This suppression must be airtight. Locked in-run order: `claim_status(AWAITING_REPLY→EXTRACTING)` (existing CAS) → load → snapshot iff null → re-extract (overwrite `extracted_data`) → reduce-by-employee_id (D-12) → `detect(snapshot, current)` → per drop: **if outcome already recorded → resolve per D-13/D-14 (backfill or honor); else record `asked` + let validate emit** → `validate(current, prior=snapshot)` → `decide` → persist.
- **D-21 (snapshot durability):** `pre_clarify_extracted` must be **committed at the pause** before any `extracted_data` overwrite, and protected as the irreplaceable value: `extracted_data` is rebuildable from (immutable original + reply + snapshot); the snapshot is not. *(The full single-transaction wrapping of pause-write + guard-write + state transition is Phase 9 atomicity work; Phase 7 specifies the ordering and the `IS NULL` guard. Cross-reference, do not implement Phase 9's transaction model here.)*
- **D-22 (concurrency already handled — do NOT re-add):** Double/duplicate replies are already behind the **`claim_status` CAS** in `resume_pipeline` (`orchestrator.py:124`, `AWAITING_REPLY→EXTRACTING`, loser drops cleanly). The `alias_candidates` write path uses the same CAS — there is **no gap to fix here**. Named so the planner does not "re-add" a guard.

### Thesis honesty (Q2 — state out loud, do not paper over)
- **D-23 (two-layer eval split):** `prior=None` keeps the *judgment* on one path (verified no-op) — the eval certifies "given a prior, does `validate` detect the drop and gate." It **cannot** certify "clarifies exactly once then terminates": the snapshot / `clarified_fields` loop-guard / backfill / `_run_stages` wiring is **state the import-`validate()` eval cannot see**. That is an **integration-test** claim against the real DB columns + orchestrator. **CONTEXT/docs/writeup must state the split: eval = judgment, integration tests = state machine.** Do not claim the eval covers the loop guard.
- **D-24 (fixture fidelity):** The eval's `prior` fixtures MUST be produced by **serializing a real extraction through the same path that writes `pre_clarify_extracted`** — NOT hand-typed JSON — or `validate()` can behave differently in eval vs prod despite being one function (serializer skew).

### TDD additions (beyond the three headline fixtures)
- **D-25:** **predicate-consistency** test — `OT 2→0` gates identically to `OT 2→absent` (proves D-09 shared predicate).
- **D-26:** **explicit-drop-confirmation** test — a reply that explicitly zeroes the field ⇒ honored, NO carry-forward (this **fails today**; it surfaces the D-13/D-14 gap and is the regression that proves the fix).
- **D-27:** **determinism identity** test — a no-op reply ⇒ `detect_field_regression` returns `[]` (proves snapshot and re-extracted-original agree by construction; guards the temp-0 property at `client.py:124`).
- **D-28:** **multi-round baseline** test — name-clarify then field-drop ⇒ `pre_clarify_extracted` NOT overwritten (proves D-19 snapshot-once).
- **D-29 (integration-layer, cross-reference Phase 9/10):** crash-idempotency (kill after overwrite, before commit ⇒ same final state) and concurrency (two resumes ⇒ exactly one clarification) tests are **integration claims** that overlap Phase 9 atomicity + Phase 10 concurrency-proof. Note the overlap so they are not double-built; Phase 7 may add a focused once-then-carry-forward integration test for its own loop guard.

### Priority within the phase
- **D-30:** Fix the two money-movers FIRST — the **shared `_is_paid` predicate (D-09)** and the **carry-forward-vs-explicit-drop outcome (D-13/D-14)** — before crash-safety hardening. Silence around an explicit "remove it" is the worst kind of payroll bug: it looks correct and pays wrong.

### Claude's Discretion
- Exact clarification-email copy/template wording for the field-regression line (must phrase the question so "yes, remove it" lands as an explicit zero in re-extraction per D-14). Reuses `compose_clarification` + the suggestion call + the `awaiting_reply` pause + resume — no new email infrastructure.
- The precise JSONB shape of `clarified_fields` / `pre_clarify_extracted` (follow the `alias_candidates` precedent).
- Whether the symmetric multi-line reduction (D-12) is last-wins vs sum — **last-wins is the locked default**; deviate only if the researcher finds an existing calc aggregation contract.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit findings this phase closes (the WHY, with file:line)
- `.planning/v2-hardening-audit.md` §"Ring 1 — Money-correctness" (lines ~18–29) — HIGH-01 (zero-hours silent $0), MED-01 (Unicode NFC), and the field-regression backlog item. Each finding traces to real file:line.
- `.planning/backlog.md` — the field-regression entry (lines ~84–120): the mechanism sketch (`pre_clarify_extracted` cell, pure `detect_field_regression`, new gate reason), the **two design traps** (clarify-loop guard, false-positive on intentional change), and the locked owner decision "clarify ONCE, then carry-forward." Phase 7 EXTENDS this with D-13/D-14 (outcome-not-count) and D-09 (shared predicate).

### Requirements + roadmap
- `.planning/REQUIREMENTS.md` — MONEY-01, MONEY-02, MONEY-03 (lines ~12–14) and the requirement→phase map.
- `.planning/ROADMAP.md` §"Phase 7: Money-Correctness Deepening" — the three success criteria (these are the acceptance bar).

### Code targets (read before implementing)
- `app/pipeline/validate.py` — `any_hours` (~line 84, MONEY-01), the D-05 over-40 guard (~102–140, composes with MONEY-01), the `prior=` seam for `field_regression` (D-17/D-18). The docstring (lines 15–20) documents why negatives can't reach this function (D-03).
- `app/pipeline/reconcile_names.py` — `_norm` (~line 32, MONEY-02), the sole name-normalization chokepoint (D-06).
- `app/pipeline/orchestrator.py` — `resume_pipeline` (~94–241): the wholesale re-extraction + overwrite, the existing `claim_status` CAS (line 124, D-22), the pre-vs-post resolved-id diff already used for alias binding (a model for the D-11 diff set), and the `_combined_context_email` resume context.
- `app/pipeline/decide.py` — gates `request_clarification` on any missing `ValidationIssue` (this is why D-17's seam needs NO change to decide).
- `app/db/repo.py` — `set_alias_candidates` / `claim_status` / `persist_extracted` (the JSONB-scratch + CAS precedents for D-13/D-19/D-22).
- `app/pipeline/calculate.py` — one `PaystubLineItem` per entry, no dedup (~286–289, the D-12 multi-line gap).
- `app/models/contracts.py` — `ExtractedEmployee` hours fields `Decimal | None + ge=0` (~75–80, the D-03 negative-safe parse boundary).
- `app/llm/client.py` — `temperature=0` on structured calls (line 124, the determinism property D-27 proves).

### Eval (the proof — preserve the single-path thesis)
- `eval/run_eval.py` — imports `validate`/`decide` directly; the D-23 two-layer split and D-24 fixture-fidelity rules apply here. Add fixtures for zero-hours-hourly, NFD-name, and the drop→clarify-once→carry-forward judgment slice.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`alias_candidates` JSONB column + `set_alias_candidates` + `claim_status` CAS** — the exact per-run-scratch + atomic-claim pattern to copy for `clarified_fields` (D-13) and `pre_clarify_extracted` (D-19). New state mirrors a proven precedent; no new table.
- **`resume_pipeline`'s pre-vs-post resolved-`employee_id` diff** (`orchestrator.py:143–234`) — already computes the set of newly-resolved employees for alias binding. The D-11 "resolved-in-both by employee_id" diff is the same machinery, applied to hours fields instead of resolution.
- **The `request_clarification` path** — `compose_clarification`, the suggestion call, the `awaiting_reply` pause, and resume all already exist. MONEY-03 reuses every one of them via a single new `ValidationIssue` type; no new email/pause infrastructure.
- **D-05 over-40 guard** — already encodes "explicit 0 == absent" for OT (`ot_missing = ot is None or ot == 0`). This is the precedent for the `_is_paid` shared predicate (D-09), not a conflict.

### Established Patterns
- **Pure-function judgment spine:** the four stages are `data in → data out`; gates live in `decide.py` computing a code-owned `final_action`; the eval imports those exact functions. Every Phase 7 change MUST preserve this — hence the `detect_field_regression` pure helper + `prior=` kwarg seam (D-17/D-18) rather than orchestrator-side gating.
- **`claim_status` CAS at every contended gate** (D-12/D-13 shipped in v1) — resume is already race-safe (D-22). Do not re-add.
- **PII-safe error handling** — the resume error boundary persists `type(exc).__name__` only (`orchestrator.py:235–241`); keep any new logging PII-safe.

### Integration Points
- `validate()` signature gains optional `prior=None` (only non-`None` on resume) — the single seam where the new judgment enters.
- `payroll_runs` gains two nullable JSONB columns (`pre_clarify_extracted`, `clarified_fields`) via `schema.sql` + bootstrap, following the `alias_candidates` migration precedent.
- The resume in-run ordering (D-20) sequences snapshot → re-extract → reduce → detect → outcome-resolve/backfill → validate → decide inside `_run_stages` / `resume_pipeline`.

</code_context>

<specifics>
## Specific Ideas

- The MONEY-03 worked example is the acceptance anchor: original "40 + 2 OT", reply "40" (no OT) → detect drop → clarify once ("did you forget the overtime?") → if still unaddressed, carry forward OT=2 and process; if the reply explicitly says "0 OT / remove it", honor it silently (D-14).
- The phase's own "two money-movers" framing (D-30): ship the shared predicate and the explicit-drop outcome before crash-safety polish.
- Hardened NFC form `NFC(casefold(NFC(s)))` (D-05) is a deliberate over-correction against casefold de-normalization — chosen even though Latin names likely never hit it, because "locked" is where such bugs hide.

</specifics>

<deferred>
## Deferred Ideas

- **401k / salary field-regression** — D-08 deliberately excludes `contribution_401k_override` and salary from the watched set (rarer real case, more false-positive surface). If real usage shows dropped-401k regressions, revisit in a later money-correctness pass.
- **Full single-transaction wrapping of the resume sequence** (pause-write + guard-write + state transition + the multi-write persist) — Phase 7 specifies the *ordering invariant* and the `IS NULL` snapshot guard (D-19/D-20/D-21); the atomic `with conn.transaction():` model is **Phase 9 (Atomic Data Integrity)**. Cross-referenced so it is not double-built.
- **Crash-idempotency + concurrency proof tests** (D-29) — the integration-layer assertions overlap **Phase 9** (atomicity) and **Phase 10** (concurrency proof). Phase 7 adds only a focused once-then-carry-forward loop-guard integration test for its own behavior.
- **Sum (vs last-wins) multi-line reduction** (D-12) — last-wins is the locked default; a sum/explicit-aggregation contract is deferred unless the calc layer is found to need it.
- **Second-order field-regression (a NEW drop introduced by the clarification *answer*)** — KNOWN, ACCEPTED LIMITATION of the two-inbound design (surfaced by the Codex review, 07-REVIEWS.md). Round 2 (the answer to "did you forget the OT?") runs `_run_stages(prior=None)`, so it does NOT field-regression-detect a field the *reply itself* newly drops while leaving other hours paid (e.g. reply restores OT but now omits holiday). Mitigation in place: MONEY-01's `_is_paid` zero-hours gate STILL runs on round 2 (only `resolved_drops` pairs are skipped), so a reply that leaves an employee with NO paid hours is still gated to clarification — the silent-$0 path stays closed. The narrow residual is a *partial* second-order drop. This is a deliberate trade for **guaranteed loop termination** (chasing drops inside a clarification answer risks the infinite re-clarify the phase exists to prevent). Revisit only if real usage shows chained partial drops; a bounded "one more round" guard keyed off `clarified_fields` generation would be the natural extension.

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 7-Money-Correctness Deepening*
*Context gathered: 2026-06-27*
