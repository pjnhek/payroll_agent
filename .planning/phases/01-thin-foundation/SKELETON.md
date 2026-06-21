# Walking Skeleton — Payroll Agent

**Phase:** 1 (Thin Foundation)
**Generated:** 2026-06-21

## Capability Proven End-to-End

A developer runs `python -m app.db.bootstrap && python -m app.db.seed` and gets a seeded Postgres database (local or Supabase) with 3 businesses and 6 employees — confirmed by reading those rows back through the same Pydantic v2 contracts that the pipeline and eval will later import. This proves the full importable-substrate slice: package scaffolding, DB connection path (including the Supavisor pooler IPv4/prepare_threshold=None gotcha), schema application, and a real DB read/write round-trip through the shared type contracts.

## Scoping Note

**This phase delivers the importable substrate slice, not a web-app slice.** The locked CONTEXT.md phase boundary explicitly excludes pipeline logic, LLM calls, webhook, and dashboard from Phase 1. The first true end-to-end web request (POST fixture → pipeline → gated decision) is Phase 2's walking skeleton. The Render + Docker deploy is Phase 6.

The skeleton this phase proves:
- The project is an importable Python package (`from app.models import ...` works from `eval/`)
- The schema applies to a real Postgres via the bootstrap script (Supavisor pooler path confirmed)
- Seed data writes real rows and reads them back through Pydantic contracts (round-trip integrity)
- The shared type contracts are complete enough for every downstream judgment stage to be pure functions (data-in, data-out, zero DB access inside the function)

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Runtime | Python 3.12 pinned | Sweet spot: every library supports it; avoids 3.13/3.14 wheel-availability edge cases for native deps |
| Web framework | FastAPI 0.138.0 | Async webhook + Pydantic-native validation; the whole app is "receive JSON, validate, run pipeline, render pages" — FastAPI does this with no extra glue. Not wired in Phase 1. |
| Validation | Pydantic v2 (2.13.4) | Validation layer for both inbound webhook payloads and LLM structured outputs; `model_validate_json()` is the retry-on-parse-failure primitive; Decimal serialization via `model_dump(mode="json")` |
| Config | pydantic-settings 2.14.2 | `BaseSettings` loads `.env` at startup; missing DATABASE_URL fails fast instead of mid-pipeline |
| Data layer | Supabase Postgres via psycopg[binary,pool] 3.3.4 | Direct SQL (not supabase-py) — real transactions, `RETURNING`, row locking, connection pool; `psycopg` is the correct tool when Postgres IS the state machine and the HITL checkpoint |
| DB connection | Supavisor pooler host, transaction mode port 6543 | IPv4-reachable from Render (the direct `db.<ref>.supabase.co` host is IPv6-only and fails from Render free); `prepare_threshold=None` on every connection to prevent psycopg3's auto-prepare from failing across pooled backends |
| Schema migrations | Single `schema.sql` with `CREATE TABLE IF NOT EXISTS` + opt-in `--reset` flag | Alembic is rejected for this greenfield demo (CLAUDE.md); one file is the DDL source of truth; `CREATE TABLE IF NOT EXISTS` is idempotent; `--reset` is the dev iteration escape hatch |
| Status column | TEXT NOT NULL + CHECK constraint (11 values) | NOT a native Postgres ENUM — evolving a state is a one-line CHECK edit with no `ALTER TYPE` ceremony (which can't run in a transaction); plays cleanly with the idempotent re-runnable schema.sql |
| Python status type | `RunStatus(str, enum.Enum)` | Single source of truth for the 11 status values; SQL CHECK mirrors it; `test_status_drift.py` fails CI if they diverge |
| Money/rates | `Decimal`, never `float` | Pushed into the shared contracts from day one so Phase 3 golden tests can assert to the penny; maps directly to Postgres `numeric` |
| Decimal → JSON | `model_dump(mode="json")` → string | Decimal fields serialize as strings ("1234.56"), not bare JSON numbers (which reload as float); persisted to jsonb columns from this output, not from `json.dumps(raw_dict_with_Decimal)` which raises TypeError |
| Directory layout | `app/models/`, `app/db/`, `app/pipeline/`, `eval/` | Pre-specified by the build plan; `app` is the importable package; `eval/` imports from it as `from app.models import ...` |
| Deployment target | Render free web service + Supabase Postgres | Not wired until Phase 6; D-04's pooler path test locally already proves the most critical connection gotcha |

## Stack Touched in Phase 1

- [x] Project scaffold (pyproject.toml, pip install -e ., requirements.txt, .env.example, package __init__ files)
- [x] Type contracts (app/models/ — 8 Pydantic v2 types including RunStatus StrEnum)
- [x] Database schema (app/db/schema.sql — 6 tables with IF NOT EXISTS, CHECK, UNIQUE)
- [x] Database connection (app/db/supabase.py — psycopg3 ConnectionPool, prepare_threshold=None)
- [x] Database write (app/db/bootstrap.py — schema apply; app/db/seed.py — upsert seed rows)
- [x] Database read (tests/test_seed_roundtrip.py — reads seeded rows back through Pydantic contracts)
- [ ] Routing — no routes in Phase 1 (first route is Phase 2's POST /webhook/inbound)
- [ ] UI — no UI in Phase 1 (first UI is Phase 5's dashboard)
- [ ] Deployment — not wired until Phase 6 (Render + Docker + Supabase from cloud)

## Out of Scope (Deferred to Later Phases)

- Any pipeline logic, LLM calls, extract/reconcile/validate/decide functions (Phase 2)
- FastAPI webhook and routes (Phase 2)
- Orchestrator / state machine driver (Phase 2)
- Email gateway interface and stub (Phase 2)
- Payroll calculation engine (Phase 3)
- IRS Pub 15-T 2026 bracket tables and golden tests (Phase 3)
- Decimal rounding policy (ROUND_HALF_UP, quantization) and DB numeric(p,s) precision (Phase 3)
- Eval harness, fixtures, and scoring (Phase 4)
- Dashboard UI, approval gate, PDF generation (Phase 5)
- Full typed DB access layer with SELECT ... FOR UPDATE (FOUND-04 — Phase 5)
- Real email gateway provider (Phase 6)
- Docker + Render deploy + GitHub Actions keep-alive (Phase 6)
- Hello-world Render+Supabase deploy (optional Phase 1 stretch; full deploy is Phase 6)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this substrate without altering the contract types or schema structure:

- Phase 2: POST a messy fixture → full pipeline (extract → reconcile → validate → decide, gated) → pauses/resumes; calc thin (gross + FICA only, net "pre-federal")
- Phase 3: Replace thin calc with real IRS Pub 15-T 2026 federal withholding + full net, golden-tested to the penny
- Phase 4: Eval harness importing the same production judgment functions; ~15-25 fixtures; per-category chart
- Phase 5: Dashboard (three-column operator gate), approval, confirmation email, on-demand paystub PDFs
- Phase 6: Real email gateway wired behind the interface, Docker + Render + Supabase deploy, keep-alive, README + demo

## Key Gotchas (Proven or Deferred)

| Gotcha | Decision | Status |
|--------|----------|--------|
| Supavisor transaction mode (6543) + psycopg3 auto-prepare → server-side prepared statements break across pooled backends | `prepare_threshold=None` on every connection (D-04) | Proven in Phase 1 (live DB) |
| `psycopg.Jsonb(raw_dict_with_Decimal)` raises TypeError — psycopg's json.dumps doesn't handle bare Decimal | Persist jsonb from `model.model_dump(mode="json")` output (D-06) | Proven in Phase 1 (round-trip test) |
| `CREATE TABLE IF NOT EXISTS` silently skips schema edits to existing DBs | `--reset` flag (opt-in DROP + recreate) as iteration escape hatch (D-01) | Available from Phase 1 |
| Direct Supabase host `db.<ref>.supabase.co` is IPv6-only → fails from Render's IPv4 network | Always use Supavisor pooler host, port 6543 (D-04) | .env.example demonstrates correct form |
| 2026 SS wage base = $184,500 — must straddle the cap in seed data, not just approach it | Thomas Bergmann: ytd_ss_wages=$183,900, annual=$240,000, biweekly → per-period gross $9,230.77 > remaining $600 (D-13) | Seeded in Phase 1; partial-cap branch proved in Phase 3 |
