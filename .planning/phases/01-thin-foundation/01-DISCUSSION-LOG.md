# Phase 1: Thin Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 1-Thin Foundation
**Areas discussed:** Schema & migration mechanics, Money/Decimal in contracts, Contracts vs DB rows, Seed data authoring

---

## Schema & Migration Mechanics

### How is the schema applied to Postgres?
| Option | Description | Selected |
|--------|-------------|----------|
| Idempotent bootstrap script | `db/bootstrap.py`/psql wrapper running schema.sql with CREATE IF NOT EXISTS / CREATE OR REPLACE; re-runnable, CI-friendly | ✓ |
| Plain schema.sql, applied manually | Commit schema.sql; operator pastes/`psql -f` by hand; not re-runnable, partial apply leaves broken DB | |
| Drop-and-recreate on bootstrap | DROP all tables then recreate each run; dead-simple but destructive | |

**User's choice:** Idempotent bootstrap script.

### How is the 11-value `payroll_runs.status` represented?
| Option | Description | Selected |
|--------|-------------|----------|
| TEXT + CHECK constraint | `status text CHECK (status IN (...))`; one-line edits to evolve state; clean with idempotent schema.sql; Python owns the enum | ✓ |
| Native Postgres ENUM type | `CREATE TYPE ... AS ENUM`; strongest DB typing but awkward to evolve, complicates idempotent bootstrap | |

**User's choice:** TEXT + CHECK constraint.

### Single source of truth for the 11 status values?
| Option | Description | Selected |
|--------|-------------|----------|
| Python StrEnum canonical; SQL CHECK mirrors | `RunStatus(StrEnum)` is canonical; SQL CHECK mirrors; CI test asserts equality so drift fails | ✓ |
| SQL canonical; Python reads a plain list | SQL CHECK is truth; Python keeps a hand-maintained tuple; no StrEnum type safety | |
| You decide | Claude picks during planning | |

**User's choice:** Python StrEnum canonical; SQL CHECK mirrors it.

### What does the bootstrap target during Phase 1 dev?
| Option | Description | Selected |
|--------|-------------|----------|
| Both — same script, DB URL from env | Identical script runs local Postgres + Supabase pooler; env var swaps target; proves pooler path early | ✓ |
| Supabase only | Develop directly against Supabase from day one; slower loop, network-dependent | |
| Local Postgres only for now | Defer all Supabase wiring; fastest loop but pushes IPv4/pooler risk later | |

**User's choice:** Both — same script, DB URL from env.

---

## Money/Decimal in Contracts

### How are monetary fields typed in the contracts?
| Option | Description | Selected |
|--------|-------------|----------|
| Python Decimal everywhere | All money fields `Decimal`, never float; maps to Postgres numeric; enables penny-accurate golden tests over shared contracts | ✓ |
| float in contracts, Decimal only in calc engine | Contracts carry floats, convert to Decimal in calculate.py; reintroduces rounding error at the contract/eval boundary | |

**User's choice:** Python Decimal everywhere.

### How does Decimal serialize to/from JSON?
| Option | Description | Selected |
|--------|-------------|----------|
| Serialize as JSON string, parse back to Decimal | Money as `"123.45"` strings, coerced back to Decimal; lossless; stable for byte-comparing eval fixtures | ✓ |
| Serialize as JSON number | Bare JSON number; standard parsers reload as float, dropping the Decimal guarantee | |
| You decide | Claude picks during planning | |

**User's choice:** Serialize as JSON string, parse back to Decimal.

---

## Contracts vs DB Rows

### What do the 4 contracts model?
| Option | Description | Selected |
|--------|-------------|----------|
| Pipeline data-passing types, decoupled from rows | Pure values flowing stage-to-stage; `Extracted` is what extraction returns + goes into extracted_data jsonb; preserves the eval-reuse seam | ✓ |
| One Pydantic model per DB table (row mirrors) | Each contract mirrors a table; lightweight ORM; couples judgment contracts to storage, fights the pure-function seam | |
| You decide | Claude picks during planning | |

**User's choice:** Pipeline data-passing types, decoupled from rows.

### Does the Phase 1 Decision contract carry the full gated shape now?
| Option | Description | Selected |
|--------|-------------|----------|
| Full gated shape now | model_action, gate_triggered, gate_reasons, final_action, unresolved_names, missing_fields, confidence, reasons (LLM-08); final_action structurally separate from model_action | ✓ |
| Minimal now, expand in Phase 2 | Thin Decision (action + reasons); grows in P2; eval/orchestrator contracts churn, gate split invisible in substrate | |
| You decide | Claude picks during planning | |

**User's choice:** Full gated shape now.

### How are contracts importable by both pipeline and eval?
| Option | Description | Selected |
|--------|-------------|----------|
| Contracts in app/models/, eval imports from app | Keep contracts in app/models/ (per build plan); eval does `from app.models import Decision`; one definition, both consumers | ✓ |
| Promote contracts to a top-level shared package | Move to neutral `contracts/`/`payroll_core/`; cleaner dependency direction but diverges from build plan layout | |
| You decide | Claude picks during planning | |

**User's choice:** Contracts in app/models/, eval imports from app.

---

## Seed Data Authoring

### How is seed data authored and loaded?
| Option | Description | Selected |
|--------|-------------|----------|
| Python loader driven by the Pydantic contracts | `db/seed.py` inserts records validated against the SAME contracts; bad calc inputs fail at seed time; idempotent; one source of truth | ✓ |
| Raw SQL INSERT statements in a seed.sql | Hand-written INSERTs; simple/transparent but bypasses Pydantic validation; UUIDs/arrays/jsonb fiddly | |
| YAML/JSON fixtures + a thin loader | Declarative files + loader; readable but adds parsing layer, still needs validation wiring | |

**User's choice:** Python loader driven by the Pydantic contracts.

### How does re-running the seed loader behave?
| Option | Description | Selected |
|--------|-------------|----------|
| Upsert on a natural key | businesses by contact_email, employees by (business_id, full_name); ON CONFLICT DO UPDATE; fixed UUIDs; never touches real runs | ✓ |
| Wipe-and-reseed (truncate seed tables first) | Truncate then re-insert; simple but blows away test payroll_runs/email_messages | |
| Insert-if-empty (skip if already seeded) | No-op if rows exist; safe but seed-data edits need a manual wipe | |

**User's choice:** Upsert on a natural key.

### Which flavor of name-mismatch is the primary gated-clarification demo?
| Option | Description | Selected |
|--------|-------------|----------|
| Typo below 0.8 confidence — the gate-block hero case | Near-miss name (e.g. Jonathan Reyes vs Jonathon Ríos); model might say process, code gate blocks <0.8 and forces clarify; the DEMO-01 story | ✓ |
| Nickname that SHOULD resolve cleanly | Alias 'Bob' for 'Robert Martinez'; deterministic match, no clarification; proves fast-path but no gate drama | |
| Unknown employee — name resolves to nobody | Name not on roster; clarifies via LLM-09; clean trigger but less compelling than a near-miss | |
| You decide / cover several | Seed richly; Claude picks primary framing in planning | |

**User's choice:** Typo below 0.8 confidence — the gate-block hero case.

### How rich should the seed roster be?
| Option | Description | Selected |
|--------|-------------|----------|
| Coverage-driven minimum | ~3 businesses, ~5-8 employees hitting every path once: ≥1 hourly + ≥1 salary, all 3 filing statuses, ≥1 near-miss, ≥1 clean alias, ≥1 high earner near the SS cap | ✓ |
| Just the two demo businesses, minimal employees | ~3-4 employees; fastest but may leave a filing status / wage-base cap unexercised | |
| You decide | Claude picks composition during planning | |

**User's choice:** Coverage-driven minimum.

---

## Claude's Discretion

The user explicitly chose recommended options in every question (no "you decide" selections), but the following sub-decisions were left to planning with noted defaults (see CONTEXT.md `### Claude's Discretion`):
- Pydantic validation strictness (extra-field policy, field bounds) — default strict on internal contracts, lenient at the webhook boundary.
- Exact field lists for `InboundEmail` / `Extracted` / `PaystubLineItem` — drive from build-plan data model + LLM-03 / FOUND-06.
- Bootstrap/seed invocation ergonomics (make target vs `python -m`; combined vs separate commands).
- The drift-test mechanism (regex-parse the CHECK vs a shared generated constant).

## Process Note (not a phase decision)

The user asked whether to Codex-review the decisions now or feed them into Claude's planning first. Resolved: **write CONTEXT.md now, Codex-review the PLAN later** (`/gsd-plan-phase 1` → `/gsd-review 1`) — the plan is the artifact with teeth (file list, DDL, seed records); the four decisions here are conventional/low-risk substrate not worth an external round-trip.

## Deferred Ideas

- Decimal rounding rule (`ROUND_HALF_UP` to cents) + DB `numeric(p,s)` precision — a Phase 3 (calc-engine) concern, not contract substrate.
- Full typed DB access layer with `SELECT ... FOR UPDATE` double-approval guard (FOUND-04) — mapped to Phase 5; Phase 1 builds only minimal DB plumbing.
- Hello-world Render+Supabase deploy (STATE.md build-time guidance) — valuable to retire the deploy landmine early; surfaced as an optional Phase 1 stretch, full deploy is Phase 6.

## Post-Review Hardening (2026-06-21)

A cross-review pass arrived after the initial CONTEXT.md was written. All 13 original decisions stood; the following were added/corrected in CONTEXT.md (see its `<review_adjustments>` section). Recorded here for the audit trail:

- **D-12 reframed (structural):** name-mismatch hero case is a Phase 1 *candidate*, not final — original `Reyes`/`Ríos` example was a double-difference name the model would clarify on its own (gate never fires). Corrected to a single clean typo on a distinctive name targeting a 0.6–0.79 confidence band; **Phase 2 owns an exit check** that it actually produces `model_action=process` + gate-block.
- **D-14 added (structural):** the contract set is larger than the four FOUND-03 names. Phase 1 must also type the `Roster`/`Employee` input shape (so `reconcile_names` takes a value, never a `business_id` DB lookup), the name-match-result shape, and the validation-issue shape — acceptance bar: every judgment stage callable from the eval with only typed fixture inputs, zero DB access inside. Protects the D-07 DRY seam.
- **D-13 corrected:** seed the period wage so YTD-SS *straddles* the $184,500 cap within the run; "just under" alone leaves the partial-cap branch dead in Phase 3 golden tests.
- **Four gotchas handed to the planner** (inline on their decisions): `prepare_threshold=None` (transaction-mode pooler + psycopg3 auto-prepare, D-04); persist jsonb from `model_dump(mode="json")` not raw `Decimal`s (D-06); add a `--reset` dev path since `CREATE TABLE IF NOT EXISTS` silently skips schema edits (D-01); wage-base straddle (D-13). The two non-obvious technical claims were verified against psycopg 3.3 docs (Jun 2026) before adoption, not taken on faith.
- **Hello-world deploy de-risked:** reviewer confirmed D-04's local pooler test already retires most of the deploy risk (same IPv4 6543 host Render uses); only `$PORT` bind + cold-start remain, both small. Stays an optional Phase 1 stretch.
- **Process note:** the review explicitly green-lit sending to the planner after these fixes.
