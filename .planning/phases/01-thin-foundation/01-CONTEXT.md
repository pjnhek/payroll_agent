# Phase 1: Thin Foundation - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 1 delivers the **shared contract substrate** that every later phase imports — and nothing more. In scope:

1. **Postgres schema** for all 6 tables (`businesses`, `employees`, `payroll_runs`, `paystub_line_items`, `email_messages`, `eval_results`) with the **11-value `payroll_runs.status`** constraint and the **`email_messages.message_id` uniqueness** that makes duplicate webhook deliveries idempotent (FOUND-01, FOUND-02).
2. **Shared Pydantic v2 contracts** that import and validate sample data and are the SAME types the eval will later import (FOUND-03). FOUND-03 *names* four (`InboundEmail`, `Extracted`, `Decision`, `PaystubLineItem`) but the full set required to keep every judgment stage purely importable by the eval is larger — see **D-14** for the additional `Roster`/`Employee` input shape and the name-match-result and validation-issue shapes that `reconcile_names` and `decide` consume.
3. **Seed data** loading 3+ businesses and their employees (mixed hourly/salary, aliases, filing statuses, full calc-input set incl. static YTD-SS) sufficient to exercise every calc path and name-match case — including one happy-path business and one name-mismatch case (FOUND-05, FOUND-06).

**NOT in this phase (belongs downstream):**
- The full typed DB access layer with `SELECT ... FOR UPDATE` double-approval guard (**FOUND-04 is mapped to Phase 5**, not Phase 1). Phase 1 builds only the minimal DB plumbing the bootstrap + seed loader need (connect via pooler, apply schema, upsert seed rows). The atomic-status-transition / row-lock layer is Phase 5's concern.
- Any pipeline logic, LLM calls, calc engine, orchestrator, webhook, or dashboard. Those are Phases 2–6.
- The Decimal **rounding rule** and exact DB `numeric(p,s)` precision (a Phase 3 calc-engine decision — see Deferred).

</domain>

<decisions>
## Implementation Decisions

### Schema & Migration Mechanics
- **D-01:** Schema is applied by an **idempotent bootstrap script** (e.g. `app/db/bootstrap.py`, or a thin psql wrapper) that runs `schema.sql` with `CREATE ... IF NOT EXISTS` / `CREATE OR REPLACE`. Re-runnable safely; one command sets up a fresh DB. Non-destructive (NOT drop-and-recreate). Single `schema.sql` is the DDL source (Alembic remains out of scope per CLAUDE.md).
  - ⚠️ **Gotcha (give the bootstrap an explicit dev reset path):** `CREATE TABLE IF NOT EXISTS` means a schema edit during Phase 1 **silently does not apply to an already-existing DB** — there is no `CREATE OR REPLACE TABLE`. Without a reset path you lose an hour wondering why a new column isn't there. Add an opt-in `--reset` (DROP then recreate) flag for dev iteration, kept clearly separate from the default non-destructive path. (The default stays safe; the reset is the iteration escape hatch.)
- **D-02:** `payroll_runs.status` is modeled as **`TEXT NOT NULL` + a `CHECK (status IN (...))` constraint over the 11 values** — NOT a native Postgres `ENUM` type. Rationale: evolving a state is a one-line CHECK edit (no `ALTER TYPE ... ADD VALUE` ceremony, which can't run in a transaction), and it plays cleanly with an idempotent re-runnable `schema.sql`. The 11 values are exactly: `received, extracting, needs_clarification, awaiting_reply, computed, awaiting_approval, approved, sent, reconciled, rejected, error`.
- **D-03:** **Python `RunStatus(StrEnum)`** (in `app/models/`) is the **single source of truth** for the 11 status values; the SQL `CHECK` list **mirrors** it. A small test asserts the SQL CHECK values equal the enum members so drift **fails CI**. The state machine stays type-safe in Python.
- **D-04:** The bootstrap script targets **both local Postgres and Supabase via the same code**, reading the connection string from env (`DATABASE_URL` via pydantic-settings). Identical script, env var swaps the target. Honors the env-driven config constraint and proves the Supabase pooler (IPv4, transaction mode 6543) connection path early without slowing the local inner loop. **Connect via the Supavisor pooler host, never the direct `db.<ref>.supabase.co` host** (IPv6-only; Render/local-IPv4 mismatch — per CLAUDE.md "What NOT to Use").
  - ⚠️ **Gotcha (transaction-mode pooler + psycopg3 prepared statements):** Supavisor transaction mode (6543) returns the backend connection to the pool per-transaction, so **server-side prepared statements break across pooled backends.** psycopg3 **auto-prepares after a query repeats** (default `prepare_threshold=5`), so the seed upsert loop will start preparing and then fail. **Set `prepare_threshold=None` on the connection** (disables prepared statements). Verified against psycopg 3.3 docs + the pgbouncer/Supabase transaction-mode caveat (Jun 2026). This bites specifically during the D-11 seed upserts if unhandled. *(Modern Supavisor/PgBouncer 1.22+ can support prepared statements in transaction mode, but disabling is the version-independent safe choice for a free-tier demo.)*

### Money / Decimal in Contracts
- **D-05:** All monetary and rate/hours fields in the Pydantic contracts are **`Decimal`, never `float`** — pushed up into the shared contracts from day one (not just inside the calc engine). Maps directly to Postgres `numeric`. This is what lets the Phase 3 golden tests assert to the penny over the same contract types.
- **D-06:** **Decimal ⇄ JSON is lossless via string serialization**: money fields serialize to JSON as strings (`"123.45"`) and Pydantic coerces back to `Decimal` on load — never as a bare JSON number (which standard parsers reload as float). This protects precision across the `extracted_data` / `decision` jsonb columns AND the committed eval fixtures (also makes fixtures stable for byte-comparison).
  - ⚠️ **Gotcha (make the string-serialization actually hold at the DB boundary):** psycopg's `Json`/`Jsonb` wrapper calls `json.dumps`, which **raises `TypeError` on a bare `Decimal`.** So **persist jsonb columns from Pydantic's own `model_dump(mode="json")` output** (which already stringifies Decimal per this decision) — NOT a dict of raw `Decimal`s handed to `Jsonb(...)`. This makes D-06 the single end-to-end mechanism (contract → jsonb → fixture → back) instead of needing a separate custom `set_json_dumps` hook. Verified against psycopg 3.3 JSON-adaptation docs (Jun 2026).

### Contracts vs DB Rows (the DRY seam)
- **D-07:** The 4 contracts are **pipeline data-passing types, decoupled from table rows** — pure values that flow stage-to-stage (extract → reconcile → decide → calc). E.g. `Extracted` is what extraction returns and what gets stored *into* the `extracted_data` jsonb, not a 1:1 mirror of any table. This preserves the pure-function / data-in-data-out seam PROJECT.md describes, which is exactly what makes the eval credible (it imports and scores these same types). The DB layer persists rows separately.
- **D-08:** The **`Decision` contract carries its full gated shape now** (not a minimal stub expanded later): `model_action`, `gate_triggered`, `gate_reasons`, `final_action`, `unresolved_names`, `missing_fields`, `confidence`, `reasons` — the exact LLM-08 persisted object. **`final_action` (code-owned) is structurally separate from `model_action` (model-proposed)**, encoding the "code owns the gate" thesis into the type itself. Phase 2 *fills it in* (writes `decide.py`); nothing downstream has to reshape the contract.
- **D-09:** Contracts live in **`app/models/`** (per the build plan's repo structure); the eval imports them via the package — `from app.models import Decision`, etc. **One definition, both consumers** (satisfies FOUND-03). Requires the project be set up as an importable package (`pyproject.toml` / proper `PYTHONPATH`) so `eval/` can reach `app.models`.
- **D-14 (added in review — protects the DRY seam):** The four FOUND-03-named contracts are **not the complete set.** Every judgment stage is a pure function that must be callable by the eval (EVAL-03) with *fixture inputs* — which means **every input a stage consumes must be a typed value passed in, never fetched from the DB inside the stage.** The most important missing one: `reconcile_names(extracted_names, roster)` needs a **typed `Roster` / `Employee` input shape**, defined in Phase 1 alongside the four. If the planner lets `reconcile` reach into the DB by `business_id` to load the roster, it stops being data-in-data-out and the eval can no longer call it with a fixture roster — collapsing the exact seam D-07 exists to protect. **Type these in Phase 1 too:**
  - a **`Roster` / `Employee` input shape** (the business's employees as a pure value `reconcile_names` accepts);
  - the **name-match-result shape** that `reconcile_names` returns and `decide` consumes (per-name match + confidence + reason, supporting LLM-05/LLM-09's one-to-one mapping);
  - the **validation-issue shape** that field validation produces and `decide` consumes (per-field presence/bounds issues, LLM-06).
  The acceptance bar: **every judgment stage (`extract`, `reconcile_names`, `validate`, `decide`) must be callable from a test/eval with only typed fixture inputs — zero DB access inside the function.** (Phase 2 writes the function bodies; Phase 1 only fixes the I/O types so they never have to be reshaped.)

### Seed Data Authoring
- **D-10:** Seed data is authored and loaded by a **Pydantic-contract-driven Python loader** (e.g. `app/db/seed.py`) — every seeded record is validated against the SAME contracts the pipeline uses, so an incomplete calc-input set (missing filing_status, missing YTD-SS, etc.) **fails at seed time, not mid-demo**. Reuses the DB layer; one source of truth for shape. (Not raw `seed.sql`, which would bypass validation; not YAML — no extra parsing layer needed.)
- **D-11:** Re-seeding is **idempotent via upsert on a natural key** — `businesses` keyed by `contact_email` (how ingest routes), `employees` by `(business_id, full_name)`; `ON CONFLICT DO UPDATE` refreshes in place so edits to seed data take effect without a wipe. **Fixed/stable UUIDs** are baked into the seed data so PKs don't churn across runs (keeps later fixture/FK references stable). The loader **never touches real `payroll_runs` / `email_messages`** (not wipe-and-reseed).
- **D-12:** The **primary name-mismatch demo case is the "model says `process` but the code gate blocks" hero case** — i.e. `model_action = process` while `final_action = request_clarification`. **The seed for this is a CANDIDATE in Phase 1, not a locked final.** Two corrections from review:
  - **The near-miss must be a single clean typo on an otherwise-distinctive name** (one dropped/transposed letter, e.g. `Reyes` → `Reyez`), NOT two simultaneous differences. The originally-illustrated `Jonathan Reyes` vs `Jonathon Ríos` has both a first-name variant AND a genuinely different surname (Reyes ≠ Ríos) — a well-prompted model will most likely *propose `request_clarification` on its own*, so the gate never visibly fires. That is the opposite of the demo: the model being cautious, not the code overriding it. The target is a name the model is *tempted to match and proceed on* but whose reported confidence lands in the **0.6–0.79 band**.
  - **Whether any seed actually yields `process`-plus-sub-0.8 depends on Phase 2's prompt + model behavior, which doesn't exist yet.** So Phase 1 seeds this as a candidate; **it becomes a Phase 2 exit check** that the case genuinely produces model-says-process + gate-blocks on camera, tuning the name AND the prompt until it does. Do NOT treat the Phase 1 seed as final — the hero moment is only real once Phase 2 confirms the model proposes `process`. This is the exact DEMO-01 / Phase 2 Success-Criteria #1 story and the most load-bearing thing the demo must show on camera.
- **D-13:** The seed roster is a **coverage-driven minimum: ~3 businesses, ~5–8 employees total**, deliberately chosen to hit every path exactly once — **≥1 hourly + ≥1 salary**, **all 3 filing statuses** spread across the set, **≥1 near-miss name** (the gate case, D-12), **≥1 clean alias** (deterministic fast-path, no model call), and **≥1 high earner positioned so the SS wage-base cap (CALC-04) actually triggers within a single run.** ⚠️ Review correction: "YTD-SS just under $184,500" alone does NOT exercise the cap — the cap only fires if the employee's **per-period gross crosses $184,500 during this run**. Seed both the static YTD-SS **and** a period wage (rate × hours, or salary/periods) such that **YTD-SS + this period's SS wages straddles the $184,500 cap** — so the partial-cap branch genuinely runs in Phase 3's golden tests rather than staying dead code. Small enough to hand-author; rich enough that no calc/match branch is left without a seeded example.

### Claude's Discretion
Resolved with sensible defaults during planning (no user constraint expressed):
- **Pydantic validation strictness** — extra-field policy (`extra="forbid"` for the strict internal contracts vs lenient at the inbound webhook boundary), field constraints (non-negative hours, sane bounds). Default: strict (`forbid`) on internal contracts; the inbound webhook payload validation can be more lenient since it mirrors an external provider shape.
- **Exact field lists** for `InboundEmail` / `Extracted` / `PaystubLineItem` — drive from the build plan's data model + REQUIREMENTS (LLM-03 extraction fields: name-as-written, regular/OT/vacation/sick/holiday hours, optional current-run-only 401k override; FOUND-06 calc inputs on employees).
- **Bootstrap/seed invocation ergonomics** — make target vs `python -m`, single combined `bootstrap` command vs separate `bootstrap` + `seed`. Default: separate, composable, both env-driven.
- **The drift test's mechanism** (parse CHECK out of schema.sql via regex vs a shared constant the SQL is generated from). Default: a test that reads the 11 values from both sources and asserts set-equality.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents (researcher, planner) MUST read these before planning or implementing.**

### Schema, contracts & repo structure (the build plan is authoritative for shape)
- `payroll-agent-build-plan.md` §"Data model (Supabase Postgres)" — the full 6-table column draft (businesses, employees, payroll_runs, paystub_line_items, email_messages, eval_results), including the status value list and the jsonb columns (`extracted_data`, `decision`). **Phase 1 schema follows this; deviations must be justified.**
- `payroll-agent-build-plan.md` §"Repo structure" — the committed layout (`app/models/`, `app/db/schema.sql`, `app/db/supabase.py`, `eval/`). D-09's import path and D-01/D-10's file locations follow this tree.
- `payroll-agent-build-plan.md` §"Decisioning model" — the three-layer (deterministic / LLM / hard-gate) design that the `Decision` contract shape (D-08) must support.

### Locked tech stack, versions & gotchas
- `CLAUDE.md` §"Recommended Stack" / "Version Compatibility" — pinned versions: Python 3.12, Pydantic 2.13.4, pydantic-settings 2.14.2, psycopg[binary,pool] 3.3.4. Use these.
- `CLAUDE.md` §"What NOT to Use" — **direct Supabase host is IPv6-only → use the Supavisor pooler host, transaction mode port 6543** (D-04); `supabase-py` is rejected in favor of `psycopg` for the transactional state machine; no Alembic (single `schema.sql`).
- `CLAUDE.md` §"FICA constants" — the **$184,500 (2026) SS wage base / $11,439 employee max** that D-13's high-earner YTD-SS seed value must straddle.

### Requirements & decisions this phase is bound by
- `.planning/REQUIREMENTS.md` §Foundations — **FOUND-01, FOUND-02, FOUND-03, FOUND-05, FOUND-06** (the 5 mapped to Phase 1). Note **FOUND-04 is Phase 5**, not here.
- `.planning/REQUIREMENTS.md` §"LLM Judgment" — **LLM-03** (extraction field list incl. current-run-only 401k override) and **LLM-07/LLM-08** (the gated `Decision` object shape D-08 must match) are the forward contracts Phase 1 types must anticipate.
- `.planning/PROJECT.md` §Context — "The DRY seam (load-bearing)" and "The `status` column IS the orchestration engine" paragraphs ground D-07/D-08 and D-02/D-03.
- `.planning/ROADMAP.md` §"Phase 1: Thin Foundation" — the 4 Success Criteria this phase is verified against.
- `.planning/STATE.md` §"Build-time guidance" — **pull-forward note: hello-world Render+Supabase deploy during P1/P2.** Per the review reframe (see `<review_adjustments>` / Deferred), D-04's local pooler test already retires most of this risk; the full deploy is an optional Phase 1 stretch, not a blocking requirement.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **None — this is a greenfield repo.** No source code exists yet (only `.planning/`, `CLAUDE.md`, and `payroll-agent-build-plan.md`). Phase 1 creates the first code: `app/models/` (the four FOUND-03 contracts + the D-14 roster/match-result/issue shapes + `RunStatus(StrEnum)`), `app/db/schema.sql`, `app/db/bootstrap.py` (with the D-01 `--reset` dev path), `app/db/seed.py`, the DB connection helper (with D-04 `prepare_threshold=None`), and the package scaffolding (`pyproject.toml` / `requirements.txt`).

### Established Patterns (to follow, from the locked docs)
- **Env-driven config** (CLAUDE.md): all connection strings / model IDs come from env via pydantic-settings; missing config fails fast at startup. D-04 follows this.
- **One `schema.sql` as DDL source-of-truth, applied idempotently** (CLAUDE.md rejects Alembic for this greenfield demo). D-01.
- **Decimal for money + `psycopg` for state** (CLAUDE.md). D-05, and the DB layer foundation.
- **Repo structure is pre-specified** in the build plan — follow `app/models/`, `app/db/`, `eval/` rather than inventing a layout.

### Integration Points
- **Forward seam → Phase 2:** the contracts (the four named + the D-14 roster/match-result/issue shapes) are imported by the pipeline stages (extract/reconcile/decide/calc) as pure-function I/O types. The `Decision` shape (D-08) must be exactly what `decide.py` will populate; the roster shape (D-14) is what `reconcile_names` accepts as a value.
- **Forward seam → Phase 4 (eval):** `eval/` imports the SAME contracts via `from app.models import ...` (D-09) — the credibility lever; the package must be importable from the sibling `eval/` dir. **Acceptance bar (D-14): every judgment stage is callable from the eval with only typed fixture inputs — zero DB access inside the function.**
- **Forward seam → Phase 3 (calc):** Decimal contracts (D-05/D-06) + the seeded high-earner YTD-SS (D-13) are what make the penny-accurate golden tests and the wage-base cap testable.
- **Forward seam → Phase 5 (FOUND-04):** the Phase 1 DB plumbing is intentionally minimal; the atomic-transition / `FOR UPDATE` layer is added in Phase 5 on top of it.

</code_context>

<specifics>
## Specific Ideas

- **Name-mismatch hero case** (D-12): a **single clean typo on an otherwise-distinctive name** (one dropped/transposed letter, e.g. `Reyes` → `Reyez`) — close enough to tempt the model into `process`, caught by the <0.8 gate. NOT a double-difference name like `Reyes` vs `Ríos` (the model would clarify on its own and the gate would never visibly fire). The exact name is a candidate, not final: Phase 2 tunes the name + prompt until the model actually proposes `process` with confidence in the 0.6–0.79 band, and that's a Phase 2 exit check (DEMO-01).
- **Status enum is the orchestration engine** — the 11 values aren't just a column constraint; they're the future state machine + HITL checkpoint + crash-recovery anchor (PROJECT.md). That's *why* D-03 insists Python owns the canonical enum.

</specifics>

<deferred>
## Deferred Ideas

- **Decimal rounding rule + DB `numeric(p,s)` precision** — the `ROUND_HALF_UP`-to-cents quantization policy and exact column precision are a **Phase 3 (Harden the Calc)** concern, not contract substrate. The contracts just type fields as `Decimal`; how/when they're rounded is decided when the calc engine and golden tests land. *(Captured so it isn't lost; explicitly out of Phase 1.)*
- **Full typed DB access layer (FOUND-04)** — atomic status transitions + `SELECT ... FOR UPDATE` double-approval guard is **Phase 5**, per the traceability map. Phase 1 builds only minimal DB plumbing (connect, apply schema, upsert seed).
- **Hello-world Render+Supabase deploy** (from STATE.md build-time guidance) — **review reframe:** D-04 testing the pooler path locally *already retires most of this risk*, since you hit the same IPv4 6543 host Render will use. The only Render-specific residuals are the `$PORT` bind and cold-start behavior, both small. So leaving the full deploy **optional in Phase 1** is fine (no longer a flagged landmine); the full deploy is Phase 6's mandate.

</deferred>

<review_adjustments>
## Review Adjustments (post cross-review hardening, 2026-06-21)

This CONTEXT.md was hardened after a cross-review pass. The original 13 decisions stood; the following were added/corrected — **planner must honor these:**

- **D-12 reframed (structural):** the name-mismatch hero case is a **Phase 1 candidate, not final**; the seed must be a single clean typo on a distinctive name (not a double-difference), and **Phase 2 owns an exit check** that the case actually yields `model_action=process` + gate-blocks on camera. Don't lock the seed as the proof.
- **D-14 added (structural):** the contract set is **larger than the four FOUND-03 names** — Phase 1 must also type the `Roster`/`Employee` input shape, the name-match-result shape, and the validation-issue shape, so every judgment stage is callable by the eval with **zero DB access inside the function.** This is the load-bearing protection for the D-07 DRY seam.
- **D-13 corrected:** seed the period wage so YTD-SS **straddles** the $184,500 cap within the run — "just under" alone leaves the partial-cap branch dead.
- **Four gotchas handed to the planner** (inline on their decisions): `prepare_threshold=None` for the transaction-mode pooler (D-04); persist jsonb from `model_dump(mode="json")` not raw Decimals (D-06); add a `--reset` dev path because `CREATE TABLE IF NOT EXISTS` silently skips schema edits (D-01); the wage-base straddle (D-13). The two non-obvious ones (psycopg3 auto-prepare + pooler; psycopg `Jsonb` raising on bare `Decimal`) were **verified against psycopg 3.3 docs (Jun 2026)**, not taken on faith.

</review_adjustments>

---

*Phase: 1-Thin Foundation*
*Context gathered: 2026-06-21*
