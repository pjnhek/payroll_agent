# Live Schema-Parity Check — Design

**Date:** 2026-07-07
**Type:** Quick fix (`/gsd-quick` scope — not a milestone/phase)
**Author:** operator + Claude

## Problem

The deployed app can run ahead of the live database schema, with nothing to detect or prevent it.

Concretely, this already happened: Phase 11 shipped round-machine code to Render (which calls `repo.get_clarification_round()` → `SELECT clarification_round FROM payroll_runs …`) but Phase 11's schema migration was never applied to the live Supabase database. Every clarification run on the live app then crashed with `UndefinedColumn` inside `_clarify()` — *before* the clarification email is composed — so the email never sent. The run stalled with its own `error_detail` recording `pipeline: column "clarification_round" does not exist`.

The live DB was missing: `payroll_runs.clarification_round`, `payroll_runs.reply_epoch`, `email_messages.round`, `email_messages.consumed_round`, `email_messages.epoch`, and the `needs_operator` status CHECK value + `clarification_field_regression` purpose CHECK value.

**Root cause of the process gap:** every prior schema-touching phase (5, 6, 7.5, 8) had a *manual* "blocking live-DB checkpoint" that applied `schema.sql` to Supabase. Phase 11 was executed autonomously and skipped that manual step. The existing `tests/test_status_drift.py` only checks `schema.sql` ⟷ `RunStatus` enum agreement (static, source-only) — it never checks the **live database**, so this drift was invisible to CI and to the v2 milestone audit (which verified against a *local* Postgres).

The immediate drift was remediated by running the additive bootstrap (`uv run python -m app.db.bootstrap`, no `--reset`) against Supabase, verified: all columns/values now present, all 146 runs / 157 emails preserved. This spec makes the class of bug **detectable** and **preventable** going forward.

## Goals

1. **Detection** — a way to know, at any time, whether the live DB has every column and status/purpose value that `schema.sql` declares.
2. **Prevention** — schema changes land on the live DB automatically when they land on `master`, so a deploy can't outrun its migration.
3. **Monitoring** — the existing keep-alive cron surfaces drift as a RED run so a human is notified even if drift arrives from an out-of-band source (e.g. a manual Supabase edit).

## Non-Goals (explicitly deferred to a future milestone)

- **Versioned / ordered migrations** (Alembic, numbered SQL files, a migration-history table). The project deliberately chose `schema.sql` + `CREATE … IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` idempotency over Alembic ("over-engineering for a single-author greenfield demo" — see project constraints). Not reopened here.
- **A hard deploy gate** that blocks the Render deploy itself on drift. Render's `preDeployCommand` (the clean hook for this) is **paid-plan only** (verified against Render docs, 2026-07-07); this project runs on the free tier by design. Out of scope.
- **Auto-remediation from the cron.** The keep-alive check reports drift; it does not write DDL. Migration writes happen only on merge to `master` (Section 2), never on a timer.
- **Flagging live columns absent from `schema.sql`.** Extra/leftover live columns are harmless and are NOT treated as drift (avoids false-positive RED runs). Only *declared-but-missing* is a failure.

## Architecture

Three independent layers, each free-tier-safe. They compose but do not depend on one another.

```
Layer 1 (detect)   app/db/schema_introspect.py  →  GET /health/schema        [in the app]
Layer 2 (prevent)  .github/workflows/deploy-migrate.yml → bootstrap on push  [in CI]
Layer 3 (monitor)  keepalive.yml: curl -f $RENDER_URL/health/schema           [in CI cron]
```

### Layer 1 — Detection: `app/db/schema_introspect.py` + `GET /health/schema`

**`app/db/schema_introspect.py`** (new module — pure logic, independently testable):

- `expected_schema() -> ExpectedSchema` — parses `app/db/schema.sql` (bootstrap's own source of truth) into:
  - `tables: dict[str, set[str]]` — declared column names per table, as the **union** of columns from `CREATE TABLE` bodies **and** `ALTER TABLE … ADD COLUMN IF NOT EXISTS` migration statements. In the current `schema.sql` the Phase 11 columns (e.g. `clarification_round`, `email_messages.round`) appear in *both* places (belt-and-suspenders: CREATE for fresh DBs, ALTER for existing ones), so either parse alone would find them — but the parser must union both because a future column could legitimately be added via an ALTER-only line, and the check must not depend on which form was used.
  - `status_values: set[str]` — the `payroll_runs.status` CHECK value set (reusing the parsing approach already proven in `tests/test_status_drift.py`; the DO-block re-add list is authoritative for the live constraint).
  - `purpose_values: set[str]` — the `email_messages.purpose` CHECK value set (same parse), so a missing `clarification_field_regression` is also caught.
- `diff_against_live(conn) -> SchemaDiff` — queries the live DB and computes `expected − actual`:
  - Columns: `information_schema.columns` per table → `missing_columns: dict[str, list[str]]`.
  - Status values: `pg_get_constraintdef` of the `payroll_runs` status CHECK → `missing_status_values: list[str]`.
  - Purpose values: same for `email_messages` purpose CHECK → `missing_purpose_values: list[str]`.
  - `SchemaDiff.is_in_sync` is True iff all three missing-sets are empty.

`ExpectedSchema` and `SchemaDiff` are small frozen dataclasses (or Pydantic models, matching repo convention).

**`GET /health/schema`** in `app/main.py` — mirrors `/health/ready`:

```
GET /health/schema
  open one DB connection (app.db.supabase.get_connection)
  diff = diff_against_live(conn)
  if diff.is_in_sync:  return 200 {"status": "in_sync"}
  else:                return 503 {"status": "drift", "missing": {
                          "payroll_runs":   [...],   # missing columns
                          "email_messages": [...],
                          "status_values":  [...],
                          "purpose_values": [...] }}   (empty keys omitted)
```

- On DB connection failure: raise 503 with a generic body (no connection string / stack trace), matching the existing `/health/ready` T-06-02-02 rule.
- The response body lists only column/value *names* (schema identifiers, not row data) — no PII, no connection string.
- Doubles as a manual debugging URL: hitting it in a browser shows exactly what's missing.

**Why parse `schema.sql` rather than `RUN_COLS` or a hardcoded list:** `RUN_COLS` (the bulk `load_run` projection) does not even contain the Phase 11 columns — those are read via dedicated helpers — so it would not have caught this bug. `schema.sql` is precisely what the live DB is supposed to match and what `bootstrap` applies, so deriving "expected" from it makes the check auto-cover every future column/value with zero endpoint edits.

### Layer 2 — Prevention: `.github/workflows/deploy-migrate.yml`

New workflow, mirroring the existing `eval.yml` push job:

```yaml
name: deploy-migrate
on:
  push:
    branches: ["master"]
  workflow_dispatch:      # manual re-run
jobs:
  migrate:
    runs-on: ubuntu-latest
    steps:
      - checkout
      - setup-uv (python 3.12)
      - uv sync
      - run: uv run python -m app.db.bootstrap      # additive; NO --reset
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

- Runs once per merge to `master`, so any `schema.sql` change is applied to Supabase at merge time — code and live schema land together. Independent of the Render auto-deploy (Render free auto-deploys on push; this runs in parallel in CI).
- Idempotent: bootstrap's default path is `DROP TABLE IF EXISTS name_matches` + `DROP COLUMN IF EXISTS match_confidence` (both already gone) then applies `schema.sql`, which is entirely `CREATE … IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / idempotent DO-block CHECK swaps. Safe to re-run every push.
- Failure shows RED and **never blocks the running app** (this is CI, not the app's boot path).
- **Requires a new `DATABASE_URL` Actions secret** (the Supavisor pooler URL, IPv4-reachable from the runner on port 6543 — the reason the project uses the pooler host). This is the one new secret the design introduces; the migration it drives is non-destructive.

**Rejected alternatives for prevention:**
- `preDeployCommand` in `render.yaml` — the clean hook, but **paid-plan only**; project is free-tier by design.
- Bootstrap in the container start command (`Dockerfile` CMD) — couples every free-tier cold-start (frequent, given 15-min spin-down) to a DDL apply and adds boot latency, fighting the deliberate no-DB `/health/live` boot design.

### Layer 3 — Monitoring: keepalive step

Add one step to `.github/workflows/keepalive.yml`, after the existing `/health/ready` ping:

```yaml
      - name: Check live schema parity
        run: curl -f --max-time 90 "$RENDER_URL/health/schema"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}
```

- `-f` → a 503 (drift) exits non-zero → the scheduled keep-alive run goes RED → operator is notified.
- Catches drift from **any** source, including a manual Supabase edit that bypasses CI (Layer 2 only covers `master` merges).
- Uses the existing `RENDER_URL` secret — no new secret for this layer.

## Data Flow

**Detection (steady state / on demand):**
`keepalive cron (or browser)` → `GET /health/schema` → app parses `schema.sql` (`expected_schema`) + queries live `information_schema`/constraints (`diff_against_live`) → `200 in_sync` | `503 drift {missing}`.

**Prevention (on merge):**
`push to master` → `deploy-migrate.yml` → `bootstrap` applies `schema.sql` to Supabase (additive) → live DB now matches the merged `schema.sql` → the next `/health/schema` is `in_sync`.

## Error Handling

- `/health/schema` DB-unreachable → 503 generic body (no leakage), same as `/health/ready`.
- `expected_schema()` parse failure (malformed `schema.sql`) → surfaces as a 503 with a generic error; the parser is unit-tested against the committed `schema.sql` so a real parse break is caught in CI, not only at runtime.
- `deploy-migrate.yml` bootstrap failure (e.g. Supabase transient outage) → RED workflow run, re-runnable via `workflow_dispatch`; the app is unaffected.
- Bootstrap is idempotent, so a partial/failed migrate followed by a re-run converges.

## Testing

The only piece with real logic is `schema_introspect.py`; the endpoint and workflows are thin wiring.

- **Unit — `expected_schema()`**: parses the committed `schema.sql` and asserts known columns/values are present (e.g. `clarification_round`, `reply_epoch` in `payroll_runs`; `needs_operator` in status values; `clarification_field_regression` in purpose values). Guards against a parser that silently misses ALTER-migration columns or DO-block CHECK values.
- **Unit — `diff_against_live()`**: drive it against a fake/in-memory `information_schema` + constraint result (fixture double, matching the project's existing `FakeConnection`/`fake_repo` test pattern) proving:
  - a DB missing a declared column → that column in `missing_columns`, `is_in_sync == False`;
  - a DB with everything → all missing-sets empty, `is_in_sync == True`;
  - a DB with an EXTRA column not in `schema.sql` → still `in_sync` (extras are not drift).
- **Endpoint smoke** (optional, if it fits the existing app-test harness): `GET /health/schema` returns 200 with an in-sync fake and 503 with a drifted fake; body carries no connection string.
- No live-DB test in CI (the runner has no Supabase creds in the hermetic jobs); the live check is exercised by Layer 3 against the deployed app.

## Rollout / Operational Notes

1. Merge this change. `deploy-migrate.yml` runs on the merge and (idempotently) re-applies `schema.sql` — no-op since the DB is already in sync from the manual remediation.
2. **Add the `DATABASE_URL` Actions secret** (Supabase pooler URL) in repo Settings → Secrets → Actions, or `deploy-migrate.yml` fails fast with a clear "secret not set" message (mirroring keepalive's `RENDER_URL` guard).
3. `/health/schema` is live after the Render deploy; the next keep-alive cron exercises Layer 3.

## Backlog (future-milestone candidates, not this fix)

- Versioned/ordered migrations + migration-history table (tier 3 prevention).
- A hard deploy gate that blocks the deploy on drift (tier 2; needs a paid Render plan or a self-managed release step).
- Auto-remediation from the keep-alive cron (deliberately excluded here — no unattended DDL on a timer).
