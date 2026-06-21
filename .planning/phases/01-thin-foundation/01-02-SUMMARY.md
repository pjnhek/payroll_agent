---
phase: 01-thin-foundation
plan: 02
subsystem: database
tags: [postgres, psycopg, schema, ddl, pydantic-settings, bootstrap, drift-guard]

requires:
  - phase: 01-01
    provides: RunStatus (11-member StrEnum) — mirrored verbatim in schema.sql CHECK constraint

provides:
  - app/db/schema.sql — DDL source of truth: 6 tables (IF NOT EXISTS), pgcrypto, 11-value status CHECK, UNIQUE(message_id), UNIQUE(business_id,full_name) on employees, updated_at on businesses+employees, deferred FK for payroll_runs/email_messages circular reference
  - app/config.py — pydantic-settings Settings class (DATABASE_URL no-default fast-fail, model tier config, tax_year)
  - app/db/supabase.py — psycopg ConnectionPool with prepare_threshold=None (Supavisor transaction-mode D-04 gotcha)
  - app/db/bootstrap.py — idempotent schema apply (default) + opt-in --reset with DROP ... CASCADE in reverse dependency order
  - tests/test_status_drift.py — CI drift guard: SQL CHECK values set-equal RunStatus members, no DB connection

affects:
  - 01-03-PLAN.md (seed.py uses get_connection() from supabase.py; ON CONFLICT uses UNIQUE(business_id,full_name) from schema.sql)
  - Phase 2 (pipeline stages use DATABASE_URL from config.py; supabase.py pool is the shared DB handle)
  - Phase 5 (atomic-transition layer built on top of this minimal DB plumbing)

tech-stack:
  added:
    - psycopg[binary,pool]==3.3.4 (direct Postgres driver, binary wheel, connection pool)
    - pydantic-settings==2.14.2 (env-driven Settings class)
  patterns:
    - prepare_threshold=None on every psycopg connection for Supavisor transaction-mode pooling (D-04)
    - Deferred ALTER TABLE to resolve circular FK between payroll_runs and email_messages (Finding #2)
    - DO $$ BEGIN IF NOT EXISTS ... END; $$ idempotent guard for ALTER TABLE ADD CONSTRAINT (no ADD CONSTRAINT IF NOT EXISTS in Postgres)
    - lru_cache on get_settings() — reads .env once per process lifetime
    - TEXT + CHECK (not native ENUM) for status — one-line edit, runs in a transaction (D-02)
    - Python RunStatus enum = canonical source; SQL mirrors it; CI drift guard asserts set-equality (D-03)

key-files:
  created:
    - app/db/__init__.py
    - app/db/schema.sql
    - app/db/supabase.py
    - app/config.py
    - app/db/bootstrap.py
    - tests/test_status_drift.py

key-decisions:
  - "D-04 applied: prepare_threshold=None on psycopg ConnectionPool kwargs — prevents auto-prepare from breaking under Supavisor transaction-mode (port 6543)"
  - "Finding #2 resolved: payroll_runs.source_email_id declared as plain UUID (no inline FK); ALTER TABLE deferred to after email_messages exists, guarded by pg_constraint existence check"
  - "Finding #1 honoured: updated_at TIMESTAMPTZ NOT NULL DEFAULT now() on both businesses and employees; UNIQUE(business_id, full_name) constraint named uq_employee_business_name for Plan 03 ON CONFLICT upsert"
  - "T-02-01 mitigated: bootstrap.py strips DATABASE_URL password via urllib.parse before any diagnostic print"
  - "T-02-02 mitigated: reset=False is the function default; DROP path is inside explicit if reset: block with printed warning"

patterns-established:
  - "Idempotent bootstrap: schema.sql uses IF NOT EXISTS throughout; deferred FK block uses pg_constraint guard"
  - "Drift guard pattern: regex-strip comments, parse SQL CHECK, assert set-equal to Python enum — pure static file test, no DB"
  - "Env-driven config: BaseSettings with no-default DATABASE_URL fails fast at import time, not mid-pipeline"

requirements-completed:
  - FOUND-01
  - FOUND-02

duration: 3min
completed: "2026-06-21"
---

# Phase 1 Plan 2: DB Schema, Bootstrap, and Drift Guard Summary

**PostgreSQL DDL source of truth (6 tables, 11-value status CHECK mirroring RunStatus, circular-FK workaround via deferred ALTER TABLE) with idempotent bootstrap script and CI drift guard test — all static checks and 19 pytest tests passing.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-06-21T06:06:30Z
- **Completed:** 2026-06-21T06:09:19Z
- **Tasks:** 2
- **Files created:** 6

## Accomplishments

- `app/db/schema.sql`: complete 6-table DDL with pgcrypto extension, 11-value status CHECK exactly matching RunStatus enum, UNIQUE constraint on email_messages.message_id (FOUND-02), UNIQUE(business_id,full_name) on employees (for Plan 03 upsert, Finding #1), updated_at on businesses and employees (Finding #1), and a DO $$ block that defers the payroll_runs → email_messages FK to after both tables exist (Finding #2)
- `app/config.py` + `app/db/supabase.py`: pydantic-settings fast-fail config and psycopg ConnectionPool with prepare_threshold=None encoding the D-04 Supavisor transaction-mode gotcha permanently into the connection layer
- `app/db/bootstrap.py`: idempotent schema apply by default; `--reset` flag drops tables in reverse-dependency order with DROP … CASCADE (documented and clearly separated); password stripped before any print (T-02-01)
- `tests/test_status_drift.py`: 4-test CI gate (schema file exists, set-equality, exact count 11, no-DB-import) runs in 0.08s with no database; total test suite 19 passed

## Task Commits

1. **Task 1: schema.sql + config.py + supabase.py connection pool** — `a283b8a` (feat)
2. **Task 2: bootstrap.py + test_status_drift.py** — `68b63dc` (feat)

## Files Created/Modified

- `app/db/__init__.py` — empty package init
- `app/db/schema.sql` — DDL source of truth (6 tables, extensions, constraints, deferred FK block)
- `app/config.py` — pydantic-settings Settings + lru_cache get_settings()
- `app/db/supabase.py` — psycopg ConnectionPool singleton (prepare_threshold=None) + get_connection() context manager
- `app/db/bootstrap.py` — idempotent apply script with opt-in --reset; reads config from env; strips password from diagnostic output
- `tests/test_status_drift.py` — CI drift guard: SQL CHECK == RunStatus members (4 tests, no DB)

## Deviations from Plan

None. Plan executed exactly as written.

## Known Stubs

None. This plan creates DB schema and infrastructure files. No data-returning code or UI is present.

## Threat Surface Scan

No new network endpoints or auth paths introduced. This plan is pure schema DDL + configuration.

T-02-01 (Information Disclosure — bootstrap diagnostic prints): mitigated. `_safe_db_url()` uses `urllib.parse` to strip the password before any `print()` in bootstrap.py.
T-02-02 (Tampering — --reset destructive path): mitigated. `reset=False` is the function signature default; the DROP path is inside `if reset:` block with a printed warning; default invocation `python -m app.db.bootstrap` never triggers it.
T-02-03 (Information Disclosure — schema.sql): accepted. schema.sql contains no credentials, only table structures; safe to commit.
T-02-04 (Denial of Service — Supavisor + prepared statements): mitigated. `prepare_threshold=None` in pool kwargs on every connection.
T-02-SC (Tampering — psycopg package): mitigated. Version pinned to 3.3.4 per CLAUDE.md verified PyPI list (Jun 2026).

## Self-Check: PASSED

Files exist:
- app/db/__init__.py: FOUND
- app/db/schema.sql: FOUND
- app/config.py: FOUND
- app/db/supabase.py: FOUND
- app/db/bootstrap.py: FOUND
- tests/test_status_drift.py: FOUND

Commits exist:
- a283b8a: feat(01-02): schema.sql + config.py + supabase.py connection pool
- 68b63dc: feat(01-02): bootstrap.py (idempotent apply + --reset CASCADE) + drift guard test
