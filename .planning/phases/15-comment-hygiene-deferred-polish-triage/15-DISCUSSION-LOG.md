# Phase 15: Comment Hygiene & Deferred-Polish Triage - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-10
**Phase:** 15-Comment Hygiene & Deferred-Polish Triage
**Areas discussed:** Preservation bar & rewrite style, Scope beyond app/, Regression guard, POLISH depth & disposition

---

## Preservation bar & rewrite style

### Q1 — Default rule for each ticket-ID comment

| Option | Description | Selected |
|--------|-------------|----------|
| Keep constraint, drop label | Judge on content: rewrite real constraints as plain maintainer English; delete pure provenance | ✓ |
| Aggressive prune | Delete by default; keep only where code alone can't convey the constraint | |
| You decide | Claude picks the rule and documents the bar | |

**User's choice:** Keep constraint, drop label (recommended)

### Q2 — Money-path comment depth

| Option | Description | Selected |
|--------|-------------|----------|
| Full depth — failure mode included | Keep the constraint AND what goes wrong if violated | ✓ |
| Constraint only, trimmed | State the invariant in one line; drop consequence narration | |
| You decide per comment | Full depth where violation = money error, trim elsewhere | |

**User's choice:** Full depth — failure mode included (recommended)

### Q3 — Module docstring shape

| Option | Description | Selected |
|--------|-------------|----------|
| Purpose + invariants where real | 1–2 sentence purpose; genuine invariants get a short paragraph | ✓ |
| Uniform one-liners | Single-sentence purpose everywhere | |
| You decide | Per-module choice | |

**User's choice:** Purpose + invariants where real (recommended)

### Q4 — Non-ticket provenance (phase numbers, review rounds, planning-doc refs)

| Option | Description | Selected |
|--------|-------------|----------|
| Strip process refs, keep external citations | All project-process refs stripped like ticket IDs; IRS/SSA citations stay | ✓ |
| Ticket IDs only | Only literal COMM-01 patterns stripped | |
| You decide | Claude draws the line | |

**User's choice:** Strip process refs, keep external citations (recommended)

---

## Scope beyond app/

### Q1 — How far does the comment sweep extend?

| Option | Description | Selected |
|--------|-------------|----------|
| Whole codebase | app/*.py + schema.sql + templates + eval/ + scripts/ + tests/ under one rule | ✓ |
| app/ + schema.sql + templates | Runtime-reader surface only; tests keep history | |
| app/*.py only (literal COMM-01) | Exactly the requirement's success criterion | |

**User's choice:** Whole codebase (recommended)
**Notes:** Grounded in the roadmap goal's "across the codebase" wording vs COMM-01's narrower success criterion.

### Q2 — Ticket-ID test names

| Option | Description | Selected |
|--------|-------------|----------|
| Rename — drop the prefix | test_cr01_x → test_x; pure rename, suite proves neutrality | ✓ |
| Keep names, comments only | Names stay as regression anchors | |
| You decide | Rename where remaining name stands alone | |

**User's choice:** Rename — drop the prefix (recommended)

### Q3 — Maintainer-facing Markdown in the code tree

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — same rule | e.g. eval/fixtures/DIVERGENCES.md swept; .planning/ stays the provenance record | ✓ |
| Exempt Markdown | Only executable-adjacent files swept | |
| You decide | Per-doc judgment | |

**User's choice:** Yes — same rule (recommended)

---

## Regression guard

### Q1 — Prevent ticket-ID comments returning?

| Option | Description | Selected |
|--------|-------------|----------|
| Guard test in the suite | pytest source-scan test (BOUND-01 precedent), runs in existing CI test job | ✓ |
| One-time sweep only | No enforcement; convention only | |
| You decide | Claude picks mechanism | |

**User's choice:** Guard test in the suite (recommended)

### Q2 — Guard pattern strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Ticket-shaped patterns only | D-<n>, WR-/CR-/CX-/GAP-<n>, FIX <n>, Pitfall #<n>, (review fix), capital-P Phase <n> | ✓ |
| Broad process-language ban | Also flag words like "review", "plan" | |
| You decide | Tune regexes against the swept corpus | |

**User's choice:** Ticket-shaped patterns only (recommended)

### Q3 — Guard scan scope

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror the sweep | Same file set the sweep cleaned; exclude .planning/ + guard's own table | ✓ |
| app/ only | Runtime package only | |
| You decide | Claude sets scope | |

**User's choice:** Mirror the sweep (recommended)

---

## POLISH depth & disposition

### Q1 — Items beyond WR-01/WR-02 (WR-03/04/05, INFO-01/02)

| Option | Description | Selected |
|--------|-------------|----------|
| Fix cheap+real, disposition the rest | Small test-first fixes for WR-04/05, INFO-01/02 if still present; disposition WR-03 | ✓ |
| Disposition-only | Document all five as accepted demo posture | |
| Fix everything | Also WR-03's column projection | |

**User's choice:** Fix cheap+real, disposition the rest (recommended)

### Q2 — What counts as "WR-01 verified"?

| Option | Description | Selected |
|--------|-------------|----------|
| Regression test | Hermetic crash→retrigger→outbound test asserting thread anchor survives | ✓ |
| Code trace + written disposition | Trace source, document safety | |
| You decide | Based on seam testability | |

**User's choice:** Regression test (recommended)

### Q3 — Fixture 10's fixture_category

| Option | Description | Selected |
|--------|-------------|----------|
| "typo" | Matches the six-category eval taxonomy; verify chart grouping unchanged | ✓ |
| "clarify" / new category | Label by outcome, not input kind | |
| You decide | Pick from existing taxonomy | |

**User's choice:** "typo" (recommended)

---

## Claude's Discretion

- Guard-test implementation details (regex table, walker, failure message)
- Per-comment keep-vs-delete judgment within the D-01 bar; final rewritten wording
- Commit sequencing (comment-only commits separated from POLISH fix commits)
- Where POLISH disposition records live (todo closure vs VERIFICATION.md)
- Whether empty `__init__.py` files need docstrings

## Deferred Ideas

- Clean multi-employee PROCESS fixture (straight-through 2-employee approval demo) — new capability from todo 260623-05's tail; backlog.
