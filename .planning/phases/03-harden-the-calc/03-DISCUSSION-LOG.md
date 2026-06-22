# Phase 3: Harden the Calc - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-22
**Phase:** 3-Harden the Calc
**Areas discussed:** Golden-oracle sourcing, Tax-constants module shape, Calc edge cases, Test taxonomy & coverage

---

## Area 1 — Golden-oracle sourcing

| Option | Description | Selected |
|--------|-------------|----------|
| IRS worked examples + 2nd calculator | Primary: transcribe the IRS Pub 15-T's OWN worked Worksheet 1A examples (IRS-authored, independent of YOUR table transcription) as golden values. Backstop: cross-check a few against an independent online payroll calculator. The oracle is the IRS itself. | ✓ |
| Hand-computed by you | You hand-walk Worksheet 1A and commit hand-computed nets with the arithmetic shown. Independent of the code, but more error-prone than the IRS examples. | |
| python-taxes cross-check | Use python-taxes (MIT, 2023–2025 tables) as the oracle generator. Can't produce 2026 ground truth (no 2026 tables) — only a method/structure check against an older year. | |

**User's choice:** IRS worked examples + 2nd calculator
**Notes:** This was framed as the load-bearing decision (STATE.md build-time guidance: the oracle must not be derived from the same transcribed 2026 tables, or a transcription typo makes code+test wrong in the same direction and they falsely tie out — the CALC-08 trap recreated in the oracle). Claude flagged a two-layer fixture structure as a consequence: layer A = verbatim IRS worked-example fixtures (the true independence guarantee, since IRS wage figures won't match the seeded employees), layer B = a few seeded-employee fixtures cross-checked against the second independent calculator. Both layers captured in CONTEXT.md D-01.

---

## Area 2 — Tax-constants module shape

| Option | Description | Selected |
|--------|-------------|----------|
| One module, all tax constants | New year-keyed module holds Pub 15-T brackets + Step-1 standard amounts AND the FICA constants migrated out of calculate.py. One dated SSA+IRS source header, one audit point. | ✓ |
| Separate FICA vs federal modules | Keep FICA where it is / its own module; add a separate federal-withholding tables module. Two files, two headers; inline FICA stays un-dated. | |
| Leave FICA inline, add federal only | Minimal diff: only add the Pub 15-T module, leave FICA inline. FICA misses the dated-header treatment CALC-06 implies. | |

**User's choice:** One module, all tax constants
**Notes:** DRY + single audit point won. Claude flagged the migration constraint: the existing FICA tests pin the inline values, so the constants MOVE but the VALUES don't change — those tests must stay green through the migration. Header must carry the IRS Pub 15-T + SSA cbb.html source URLs and the retrieval date (CALC-06). Year-keying must make a future 2027 additive. Captured in CONTEXT.md D-02.

---

## Area 3 — Calc edge cases

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit hours_overtime only | The calc trusts the submitted OT split and never auto-derives; hours_regular paid straight-time even if >40. Matches how emails arrive and avoids guessing a workweek boundary. | ✓ |
| Auto-split regular over 40 | If hours_regular > 40 with no hours_overtime, the calc splits first-40 straight / remainder 1.5×. More FLSA-correct per single workweek, but over-pays OT when employees submit period totals (biweekly/semi-monthly). | |
| Both: explicit wins, else auto-split | Use hours_overtime if present, else auto-split. Carries the same period-total hazard plus a second code path. | |

**User's choice:** Explicit hours_overtime only
**Notes:** The decisive factor: biweekly/semi-monthly employees submit PERIOD totals, not single-workweek hours, so auto-splitting at a 40-hour boundary would over-pay OT; the calc has no workweek concept and must not invent one. Keeps `calculate` a pure function of submitted fields. Claude noted two related sub-questions are already pinned by the success criteria and NOT re-opened: salaried gross adds leave pay (CALC-02), and the 401k base is gross and reduces the federal base but not FICA (CALC-03). Captured in CONTEXT.md D-03 + the "confirmed-not-gray" list.

---

## Area 4 — Test taxonomy & coverage

| Option | Description | Selected |
|--------|-------------|----------|
| Full matrix + edge cases | The 6 Worksheet 1A schedules (3 statuses × Step-2 branch) to the penny, PLUS SS-cap straddle, 401k-federal-not-FICA, multi-bracket high earner, below-threshold zero-withholding, hourly-with-OT, salaried-with-leave, and negative disclaimer assertions (OBBBA / Additional-Medicare not applied). The "most-tested unit" bar. | ✓ |
| Filing-status matrix only | The 6 schedules + one happy-path gross/FICA case; skips straddle / 401k-interaction / bracket-boundary edges. | |
| IRS examples + smoke | Only the verbatim IRS examples + a couple gross/FICA/net smoke tests. Lightest; doesn't exercise the seeded employees or edge interactions. | |

**User's choice:** Full matrix + edge cases
**Notes:** CLAUDE.md says the Pub 15-T engine MUST be the most-tested unit in the repo; the full-matrix bar honors that. The negative/disclaimer assertions (a $200k+ YTD case showing Medicare stays flat 1.45%, OBBBA not applied) back the README disclaimers with tests rather than prose. Captured in CONTEXT.md D-04.

---

## Post-context review round (2026-06-22) — four hardening items folded in

After the initial four-area pass, the user raised four review points to make "golden to the penny" actually hold. All four accepted; CONTEXT.md updated.

1. **Layer-B oracle quality (→ D-01 hardened).** Pub 15-T ships only a couple of worked examples, so most of the matrix leans on layer B. Two hazards captured: (a) generic take-home estimators use annual-liability/simplified math, not the per-period Pub 15-T percentage method, so they disagree to the penny even when correct and you can't tell methodology from a transcription bug — layer B MUST use a calculator that explicitly implements the percentage method; (b) one source isn't verification — uncovered cells need **two independent** percentage-method calculators to agree. Researcher confirms which tools qualify.

2. **Rounding convention/granularity/step-locations (→ D-03 rounding bullet hardened).** ROUND_HALF_UP pins direction, not granularity (cents vs whole-dollar) or worksheet step locations. Mismatch makes the penny test fail on rounding, not logic. Must be transcribed from the same live PDF as the brackets and matched to the worked examples.

3. **Two taxonomy gaps (→ D-04 extended).** (a) Step-3 dependent credit (partial, and credit-exceeds-tentative → floors at $0 not negative) + Step-4a/4b paths — the engine uses the FOUND-06 seeded values, so they must be tested. (b) Multiple pay frequencies — annualization is a separate error surface; ≥2 frequencies in the penny matrix. Seed nuance surfaced: only 52 + 26 are seeded; 24/12 need synthetic fixtures.

4. **Cross-phase OT under-pay hole (→ new D-05 + backlog).** Explicit-OT-only (D-03) silently under-pays a weekly "45 hours, no OT field" employee. User corrected the rule from a flat ">40" to **per-workweek** (>40×whole-workweeks): weekly >40 and biweekly >80 are detectable → clarify; semi-monthly/monthly cut across workweeks → documented limitation. Its own focused insertion **before Phase 5** (not bundled into Phase 3 calc, not deferred to Phase 5 — a money-guard shouldn't ride two phases out). Decided via AskUserQuestion; the user's freeform answer overrode all three offered options on both timing and the rule's correctness. Also a demo beat.

## Claude's Discretion

- Exact path/name and internal year-keying data structure of the tax-constants module (scope fixed by D-02; layout open).
- Whether the Pub 15-T engine is a standalone pure module imported by calculate.py (research/CLAUDE.md bias toward this for the highest-bug-risk unit) or functions in calculate.py.
- Exact golden-fixture count beyond the required matrix + named edges, and fixture format (inline Python vs JSON).
- Mechanical handling of the "pre-federal" label retirement (calculate.py constant + README stub).
- Where the CALC-08 reconciliation check lives (per-line in calculate vs run-level; the payroll_runs.reconciliation JSONB column is its home if run-level).

## Deferred Ideas

- State withholding (flat-rate / per-state) → v2 (CALC-V2-01); state_withholding stays nullable/None.
- Per-employee YTD tax ledger → v2 (CALC-V2-02); Phase 3 uses static seeded ytd_ss_wages.
- OBBBA provisions → never (out of scope, disclaimed); standard method only.
- Additional Medicare 0.9% → not modeled (disclaimed); only asserted-as-absent.
- Eval scoring of the calc functions → Phase 4.
- Paystub PDFs + confirmation email rendering real net → Phase 5.
