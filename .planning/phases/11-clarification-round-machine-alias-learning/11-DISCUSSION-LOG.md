# Phase 11: Clarification Round Machine & Alias Learning - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-05
**Phase:** 11-clarification-round-machine-alias-learning
**Areas discussed:** Round identity & send guard, Round cap & operator escape, Reply attribution & context, Alias bind-on-confirmation

---

## Todo folding (pre-discussion)

| Option | Description | Selected |
|--------|-------------|----------|
| The 3 clarify-cluster todos | 260705-01, 260705-02, 260623-08 — the phase's source material | ✓ |
| Also 260623-01 security hygiene | Filename injection, path containment, retry scrub | |
| Also cosmetic todos (02/03/04/05) | Locked out of v2 scope | |
| Fold none | Discuss from ROADMAP goal only | |

**User's choice:** The 3 clarify-cluster todos (recommended)

---

## Round identity & send guard

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit round counter | payroll_runs.clarification_round; guard keys (purpose, round); uq widens to (run_id, purpose, round) | ✓ |
| Asked-content hash | Suppress only when the new ask matches an already-sent ask; no round in schema | |
| Transition-scoped guard | Suppress only on re-trigger from awaiting_reply (review option b) | |

**User's choice:** Explicit round counter (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Increment at send, consume at claim | Round real at sent-commit; reply consumed_round set at CAS claim; unconsumed redelivery re-schedules resume | ✓ |
| Increment at reply arrival | Rounds = exchanges, but increment lands in webhook ingest txn; crash recreates a stale-state family | |
| Derive, don't store | COUNT sent outbound rows; no column but race-prone recounts | |

**User's choice:** Increment at send, consume at claim (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Clear at retrigger | Clear clarified_fields + pre_clarify_extracted + round state where reply context is discarded | ✓ |
| Archive then clear | Same, plus snapshot of the crashed round's state to an archive | |
| Consistency-checked badges | Keep data, render badges conditionally — treats the symptom | |

**User's choice:** Clear at retrigger (recommended) — WR-06

| Option | Description | Selected |
|--------|-------------|----------|
| Auto re-schedule on dashboard load | D-9-11 trigger pattern; awaiting_reply + unconsumed reply older than threshold → re-schedule resume | ✓ |
| Mark visible, operator resumes | Strict marking-not-restarting symmetry; adds operator chore | |
| Widen retrigger claimability only | Cheapest; the silent stall stays silent | |

**User's choice:** Auto re-schedule on dashboard load (recommended)

---

## Round cap & operator escape

| Option | Description | Selected |
|--------|-------------|----------|
| New status: needs_operator | Dedicated enum value; explicit exits; fits "status column is the engine" | ✓ |
| Reuse ERROR + sentinel | Zero schema change, but retrigger-from-original loses reply context | |
| Flag on awaiting_reply | Boolean flag; every scope list grows flag-conditional logic | |

**User's choice:** New status: needs_operator (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| 3 total rounds, one constant | All purposes counted together; one module constant | ✓ |
| 2 rounds, aggressive | Tighter demo story; risks escalating converging runs | |
| 3 per purpose | Two counters; more faithful, more machinery | |

**User's choice:** 3 total rounds, one constant (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Resolve names + resume, or reject | Minimal per-name roster dropdown (suggestion pre-selected) + Resume + Reject | ✓ |
| Reject only (minimal) | Display-only escape; dead end for the case needing judgment | |
| Full manual edit | Names AND money fields; blurs the single-gate story | |

**User's choice:** Resolve names + resume, or reject (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| No email — silent handoff | Operator resolves; next client email is the normal confirmation | ✓ |
| Courtesy note | New purpose/template/idempotency surface for a nicety | |

**User's choice:** No email — silent handoff (recommended)

---

## Reply attribution & context

| Option | Description | Selected |
|--------|-------------|----------|
| Structured asked-summary | Code-owned "QUESTIONS WE ASKED" section from decision facts | ✓ |
| Full outbound body | The LLM-drafted email as third section; model-authored anchor | |
| Both | Max context, double prompt noise | |

**User's choice:** Structured asked-summary (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Absent-if-unaddressed, re-ask | Fill asked fields only when attributably answered; still-missing → new narrower question | ✓ |
| Prompt guidance only | Anchor helps, human gate catches the rest | |
| Deterministic pre-fill | Code attributes single-question bare answers; parser-toward-NLP risk | |

**User's choice:** Absent-if-unaddressed, re-ask (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Accumulate all reply bodies | ORIGINAL + all consumed replies in round order (09-REVIEWS fix (a)); fixture flips | ✓ |
| Diff vs last-persisted extraction | Fix (b): second diff state machine — the bug-prone family | |
| Both | Belt and braces; diff machine's cost stays | |

**User's choice:** Accumulate all reply bodies (recommended) — CX-01 closure

| Option | Description | Selected |
|--------|-------------|----------|
| Query email_messages rows | consumed_round-marked inbound rows in round order; single source of truth | ✓ |
| Append to a JSONB column | One cheap read; a second copy that can drift | |

**User's choice:** Query email_messages rows (recommended)

---

## Alias bind-on-confirmation

| Option | Description | Selected |
|--------|-------------|----------|
| Suggested employee resolves post-resume | Deterministic: bind iff suggested id newly resolved AND token gone from unresolved | ✓ |
| LLM confirmation classifier | Puts an LLM judgment in a name-routing write chain | |
| Only bind at operator actions | Happy case learns nothing; keeps re-asking | |

**User's choice:** Suggested employee resolves post-resume (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Richer alias_candidates values | {token: {suggested, bound}} — one column owns the lifecycle | ✓ |
| Sibling JSONB column | Two columns describe one lifecycle; drift-prone | |
| On the outbound email row | Provenance-nice but smears the lifecycle across tables | |

**User's choice:** Richer alias_candidates values (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Checkbox, default ON | "Remember this alias" per name in the resolve form; typos need not become aliases | ✓ |
| Always bind | Typo-resolutions become permanent known_aliases | |
| Never bind from the form | Wastes the highest-quality evidence | |

**User's choice:** Checkbox, default ON (recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Full-loop test + stops-asking assertion | Hermetic end-to-end incl. a second submission resolving via stored-alias with no clarification | ✓ |
| Loop test only | Skips the second-run assertion | |
| You decide | Planner sets test shape | |

**User's choice:** Full-loop test + stops-asking assertion (recommended)

---

## Claude's Discretion

- Column/marker/constraint naming and migration DDL mechanics (Phase 8 DO-block pattern)
- Cap-check placement and escalation write sequence (respecting D-9-02)
- Combined-context delimiter format and asked-summary wording
- Resolve-form UI details within the Jinja2/no-SPA idiom
- Operator-resume pipeline entry point (mapping applied deterministically before reconcile)
- Suggestion persistence granularity for multi-name clarifications (capture stays single-token, D-04)

## Deferred Ideas

- CX-01 fix (b) paid→paid cross-round diff — rejected for this phase; revisit only on evidence accumulation misses a real case
- Courtesy email at escalation — future polish if silent handoff confuses real clients
- Widening alias capture beyond single-token — explicitly out of scope
- 260623-01 security hygiene + cosmetic todos 260623-02/03/04/05 — reviewed, not folded

## Mid-discussion Q&A

User asked how the agent distinguishes a clarification reply from a new submission and attaches it to the right record. Answered: deterministic RFC header-chain matching (`find_awaiting_reply_for_header`) handles reply-vs-new and run-level attachment (already solid in v1, WR-03 linkage now durable); Phase 11 fixes the *consumption* layer — within-run attribution (question anchor), WR-04 redelivery re-attempts, WR-05 round-aware sends.
