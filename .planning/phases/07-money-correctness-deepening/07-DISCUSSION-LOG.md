# Phase 7: Money-Correctness Deepening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-27
**Phase:** 7-Money-Correctness Deepening
**Areas discussed:** Regression scope, Loop guard & carry-forward, Detection seam, MONEY-01 zero edges

---

## Regression scope (MONEY-03)

### Which fields count as a money-affecting regression

| Option | Description | Selected |
|--------|-------------|----------|
| All hours fields | Watch all five hours fields for present→absent. Every one feeds gross; OT is just the headline. 401k/salary excluded. | ✓ |
| OT only | Only `hours_overtime` present→absent (backlog sketch + example). Smallest surface, but a dropped vacation/sick/holiday still underpays. | |
| All money inputs | Five hours fields PLUS `contribution_401k_override`/salary. Broadest, more false-positive surface. | |

**User's choice:** All hours fields → **D-08**

### What change triggers a clarify

| Option | Description | Selected |
|--------|-------------|----------|
| Drop only | Clarify only on present→absent. A change/increase is the client correcting — honored silently. Lowest false-positive risk. | ✓ |
| Drop + decrease | Also clarify on a decreased value. Asymmetric, risks nagging an intentional lower number. | |
| Drop + any change | Clarify on any value change. Defeats the purpose of a reply; loops annoyingly. | |

**User's choice:** Drop only → **D-10**

### Which employees the diff compares

| Option | Description | Selected |
|--------|-------------|----------|
| Resolved-in-both, by employee_id | Diff only employees resolved to the same roster id in both extractions. Stable identity; newly-resolved (reply's purpose) correctly skipped. | ✓ |
| Match by submitted_name | Diff by submitted_name string. Brittle — a restated name breaks the match. | |
| All extracted employees | Diff everyone regardless of resolution. Noisy; manufactures spurious regressions. | |

**User's choice:** Resolved-in-both, by employee_id → **D-11**

**Notes:** Review later surfaced the multi-line same-employee gap (one `employee_id`, two extracted lines) — folded as **D-12** (symmetric last-wins reduction before diffing). Predicate `0-vs-absent` consistency surfaced as **D-09** (shared `_is_paid`): `OT 2→0` must count as a drop, not a silent change, or it reintroduces the underpay bug.

---

## Loop guard & carry-forward (MONEY-03)

### Where the "already clarified this field once" record lives

| Option | Description | Selected |
|--------|-------------|----------|
| New JSONB column on payroll_runs | Per-run JSONB cell mirroring `alias_candidates`. Per-employee/per-field, no new table, unit-testable. | ✓ |
| Reuse pre_clarify snapshot | Infer "already asked" from snapshot existence. Conflates snapshot-taken with field-asked; fragile for multiple fields. | |
| Derive from email_messages history | Query sent clarification rows. Indirect; couples guard to email composition. | |

**User's choice:** New JSONB column on payroll_runs → **D-13** (extended to carry an *outcome*, not a count)

### How carry-forward reconstructs the original value

| Option | Description | Selected |
|--------|-------------|----------|
| Backfill from pre_clarify snapshot into extracted_data | Authoritative original; makes extracted_data/paystub/reconciliation agree; honest gate stays truthful. | ✓ |
| Carry forward at calc time only | extracted_data and paystub disagree; breaks the honest-gate leftmost column. | |
| Re-clarify with original pre-filled | Adds a second clarify round; contradicts the locked clarify-once policy. | |

**User's choice:** Backfill from pre_clarify snapshot into extracted_data → **D-16**

**Notes:** Review surfaced **C-7** (the deepest catch): a count-only guard backfills even when the client explicitly replied "remove it" → overpay + ignored instruction. Folded as **D-13/D-14** — the guard carries an outcome (`asked / carried_forward / confirmed_dropped`); an explicit-0 reply ⇒ `confirmed_dropped` ⇒ no backfill. **D-15** notes the context-aware interaction with MONEY-01 (explicit-0 means "suspicious" on a fresh run, but "answer" on a clarification reply).

---

## Detection seam (MONEY-03)

### How the field-regression signal enters the gate

| Option | Description | Selected |
|--------|-------------|----------|
| Pure helper + ValidationIssue from validate() | `detect_field_regression` pure helper → `validate(prior=)` emits `field_regression` issue. decide.py unchanged; eval scores same path. | ✓ |
| New gate reason inside decide() | Pass prior into decide(); widens its signature, duplicates the force-clarify logic. | |
| Detect in orchestrator, set gate directly | Bypasses validate/decide; eval would NOT exercise it — breaks the single-path thesis. | |

**User's choice:** Pure helper + ValidationIssue from validate() → **D-17**

### How `prior` is threaded through the shared `_run_stages`

| Option | Description | Selected |
|--------|-------------|----------|
| Optional prior=None arg on validate() | Fresh run passes None (no-op, all tests preserved); resume passes snapshot. _run_stages stays single shared fn. | ✓ |
| Separate validate_resume() wrapper | Two entry points; _run_stages must branch fresh-vs-resume. Less DRY. | |
| Orchestrator appends issues post-validate | Regression bypasses validate(); eval must replicate the append — weakens single-path guarantee. | |

**User's choice:** Optional prior=None arg on validate() → **D-18**

**Notes:** Review surfaced the **Q2 thesis erosion** (D-23): `prior=None` keeps the *judgment* on one path, but the snapshot/loop-guard/backfill lifecycle is state the import-`validate()` eval can't see — that's an integration claim, not a pure-eval claim. Stated explicitly as a two-layer split. **D-24** added: `prior` fixtures must be serialized through the real snapshot path, not hand-typed (serializer skew).

---

## MONEY-01 zero edges

### Exactly which zero pattern gates to clarification

| Option | Description | Selected |
|--------|-------------|----------|
| All-zero-or-absent across the five hours = missing | No positive hours anywhere (any field present-and->0) → gate. Closes the bug regardless of which field carried the 0; partial weeks still process; salaried untouched. | ✓ |
| Only hours_regular=0 gates | Narrowest; leaves a sibling hole (lone sick=0 still ships $0). | |
| Any single explicit 0 gates | Too aggressive; would gate regular=40 + OT=0 (a valid week already owned by D-05). | |

**User's choice:** All-zero-or-absent across the five hours = missing → **D-01/D-02/D-03**

**Notes:** Implemented via the shared `_is_paid` predicate (D-09). Review confirmed: negative hours are already caught at the parse boundary (`contracts.py ge=0` → ERROR), so no dead negative guard is added; `pay_type` unknown ⇒ treat as hourly and apply the gate (fail-safe).

---

## MONEY-02 (not separately discussed — locked by success criterion)

Locked: `unicodedata.normalize("NFC", …)` before casefold in `reconcile_names._norm`, with an NFD-resolve test. Review hardened the canonical form to `NFC(casefold(NFC(s)))` (casefold can de-normalize) — **D-05** — and confirmed `_norm` is the sole name-normalization chokepoint — **D-06**. NFC over NFKC kept (conservative for names).

---

## Claude's Discretion

- Clarification-email copy/template wording for the field-regression line (must phrase so "remove it" lands as an explicit zero per D-14). Reuses existing `compose_clarification` + pause/resume.
- Precise JSONB shapes of `clarified_fields` / `pre_clarify_extracted` (follow `alias_candidates` precedent).
- Multi-line reduction default is last-wins (D-12); deviate only if the researcher finds an existing calc aggregation contract.

## Deferred Ideas

- 401k/salary field-regression (excluded from the watched set, D-08).
- Full single-transaction wrapping of the resume sequence → Phase 9 (atomicity); Phase 7 specifies only ordering + the IS-NULL snapshot guard.
- Crash-idempotency + concurrency proof tests → overlap Phase 9/10; Phase 7 adds only its own once-then-carry-forward loop-guard integration test.
- Sum (vs last-wins) multi-line reduction — deferred unless calc needs it.
