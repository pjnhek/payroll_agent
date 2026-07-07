# Live Schema-Parity Check (Columns + Selected CHECK/UNIQUE Constraints) — Design

**Date:** 2026-07-07
**Type:** Quick fix (`/gsd-quick` scope — not a milestone/phase)
**Author:** operator + Claude
**Review:** Codex (gpt-5.5, xhigh) reviewed 2026-07-07 → "ship with fixes"; all 10 findings incorporated below (see "Review resolutions" at end).

> **Scope honesty:** this checks that the live DB has every **column** and every **`status`/`purpose` CHECK value** that `schema.sql` declares, plus the Phase-11 app-critical **`uq_email_run_purpose_round_epoch` unique constraint**. It does NOT check column *types*, `NOT NULL`/`DEFAULT` drift, indexes, or other constraints — see Non-Goals. It is deliberately named "column and selected-constraint parity," not full schema parity.

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
- **Deeper schema drift** (Codex #4): column *type* changes, `NOT NULL`/`DEFAULT` drift, indexes, and constraints other than the one allowlisted UNIQUE are **out of scope**. The failure class this fix targets is "a declared column or status/purpose value or the `ON CONFLICT` unique constraint is simply *absent* on live" — which is exactly the Phase-11 bug. A column that exists but has the wrong type/nullability is not detected here; that would need a full-schema differ (backlog).

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
  - `tables: dict[str, set[str]]` — declared column names per table, as the **union** of columns from `CREATE TABLE` bodies **and** `ALTER TABLE … ADD COLUMN IF NOT EXISTS` migration statements.
    - The parser must union both forms and must not depend on which one a column came from. In the current `schema.sql`, the Phase 11 columns appear in *both* (belt-and-suspenders), but **`record_only` is declared via an `ALTER`-only line** (`schema.sql:125`) — so the ALTER parse is genuinely load-bearing, and `record_only` is the canonical unit-test case for it (Codex finding #3).
    - **Parser robustness (Codex #3):** the CREATE-body column extractor must not be a naive line/regex split — it must handle nested parens (e.g. `NUMERIC(12,2)`, `CHECK (col IN (...))`), skip `--` comments, and **exclude table-level constraint clauses** (`CONSTRAINT …`, `UNIQUE (…)`, `CHECK (…)`, `FOREIGN KEY …`, `PRIMARY KEY …`) so a constraint name is never mistaken for a column. Use a small paren-balanced scanner over the CREATE body, then take the first identifier of each top-level comma-separated item that is not a constraint keyword.
  - `status_values: set[str]` — the `payroll_runs.status` CHECK value set. **Parse the executable DO-block re-add list** (`payroll_runs_status_check`), NOT the first inline `CREATE TABLE` CHECK match — reuse the existing `_extract_do_block_status_values` approach from `tests/test_status_drift.py`, because the DO-block is what actually defines the live constraint and a one-sided edit to the inline CHECK must not hide drift (Codex #2).
  - `purpose_values: set[str]` — the `email_messages.purpose` CHECK value set, parsed from its DO-block re-add list (`email_messages_purpose_check`) the same way, so a missing `clarification_field_regression` is caught.
  - `unique_constraints: set[str]` — the set of app-critical named UNIQUE constraints to verify exist on the live DB. For this fix that is exactly `{"uq_email_run_purpose_round_epoch"}` (the Phase-11 `ON CONFLICT (run_id, purpose, round, epoch)` arbiter — part of the same Phase-11 drift). Kept as an explicit small allowlist, not a full unique-constraint diff (Codex #4).
- `diff_against_live(conn) -> SchemaDiff` — queries the live DB and computes `expected − actual`. **All catalog queries are schema-qualified to `public`** (Codex #7) so a Supabase-managed schema or a `search_path` change can't cause a false result:
  - Columns: `information_schema.columns WHERE table_schema = 'public' AND table_name = %s` per table → `missing_columns: dict[str, list[str]]`.
  - Status/purpose values: `pg_get_constraintdef(oid)` of the CHECK constraints selected **by `pg_constraint.conkey`** (the constraint's column set) on `to_regclass('public.payroll_runs')` / `to_regclass('public.email_messages')` — never by name substring. **The live definition normalizes to `status = ANY (ARRAY['received'::text, …])`, NOT `status IN (...)`** (Codex #1, confirmed empirically against this DB) — so the value extractor must parse the `ANY (ARRAY[...])` form and strip `::text` / whitespace / quotes. → `missing_status_values`, `missing_purpose_values`.
  - Unique constraints: `pg_constraint WHERE contype='u' AND conrelid = to_regclass('public.email_messages') AND conname = %s` → `missing_unique_constraints: list[str]`.
  - `SchemaDiff.is_in_sync` is True iff all four missing-sets are empty.

`ExpectedSchema` and `SchemaDiff` are small frozen dataclasses (or Pydantic models, matching repo convention).

**`GET /health/schema`** in `app/main.py` — mirrors `/health/ready`:

```
GET /health/schema
  open one DB connection (app.db.supabase.get_connection)
  diff = diff_against_live(conn)
  if diff.is_in_sync:  return 200 {"status": "in_sync"}
  else:                return 503 {"status": "drift", "missing": {
                          "payroll_runs":       [...],   # missing columns
                          "email_messages":     [...],
                          "status_values":      [...],
                          "purpose_values":     [...],
                          "unique_constraints": [...] }}   (empty keys omitted)
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
      # Codex #10: fail fast + clearly if the secret was never configured
      - name: Validate DATABASE_URL secret is set
        run: |
          if [ -z "$DATABASE_URL" ]; then
            echo "ERROR: DATABASE_URL secret not set (Settings → Secrets → Actions)"; exit 1; fi
        env: { DATABASE_URL: ${{ secrets.DATABASE_URL }} }
      # Codex #6: prove the schema-introspection PARSER is sound BEFORE touching prod.
      # A malformed schema.sql (bad CHECK/ALTER edit) fails here, before any DDL runs.
      - name: Introspection unit tests (pre-flight, no DB)
        run: uv run pytest tests/test_schema_introspect.py -q
      # Codex #8: bound lock/statement time so a live-app lock contention fails RED, not hangs.
      - name: Apply additive migration to live Supabase
        run: uv run python -m app.db.bootstrap      # additive; NO --reset
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          # bootstrap sets lock_timeout / statement_timeout on its admin connection
          # (e.g. 10s / 60s) so a DDL blocked by the live app aborts red instead of hanging CI.
      # Codex #6: prove the migration actually CONVERGED — direct live diff, same logic
      # as GET /health/schema, run in-process against the just-migrated DB.
      - name: Verify live schema is in sync (post-flight)
        run: uv run python -m app.db.check_schema   # exit 0 = in_sync, non-zero = still drifted
        env: { DATABASE_URL: ${{ secrets.DATABASE_URL }} }
```

- Runs once per merge to `master`, applying any `schema.sql` change to Supabase at merge time. Also exposes `app.db.check_schema` as a thin CLI wrapper over `diff_against_live` (reused by the post-flight step and available for manual use), so the CI diff and the `/health/schema` endpoint share ONE implementation.
- **Honest prevention claim (Codex #5):** this is **best-effort, converge-within-one-CI-run** prevention — NOT a hard gate. Render free auto-deploys on push, and this CI job runs *in parallel* with that deploy, so there is a brief race window where the new code could serve traffic against the not-yet-migrated schema before this job finishes. That residual window is exactly what **Layer 1 (`/health/schema`) + Layer 3 (keepalive)** exist to catch. Closing the race entirely (disable Render auto-deploy; deploy only after migration) needs a paid deploy hook or a self-managed release step and is out of scope (backlog).
- Idempotent: bootstrap's default path is `DROP TABLE IF EXISTS name_matches` + `DROP COLUMN IF EXISTS match_confidence` (both already gone) then applies `schema.sql`, which is entirely `CREATE … IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / idempotent DO-block CHECK swaps. Safe to re-run every push. A malformed `schema.sql` is caught by the pre-flight unit tests before any DDL touches prod (Codex #6); a genuinely bad-but-parseable schema is a design-time author error the same as any other merge to master.
- Failure shows RED and **never blocks the running app** (this is CI, not the app's boot path).
- **Requires a new `DATABASE_URL` Actions secret** (the Supavisor pooler URL, IPv4-reachable from the runner on port 6543 — the reason the project uses the pooler host). This is the one new secret the design introduces; the migration it drives is non-destructive. **Add the secret BEFORE merging this change** (Codex #10) so the first run doesn't fail on a missing secret.

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
- **Detection latency (Codex #9):** the keep-alive cron runs twice a week (Mon/Thu), so out-of-band drift caught *only* by this layer could sit undetected for up to ~3–4 days. That is acceptable for this monitoring layer because (a) the common drift source — a `schema.sql` merge — is applied and diff-verified synchronously by Layer 2 at merge time, and (b) `/health/schema` can be hit on demand any time. If faster out-of-band detection is ever wanted, tighten the cron; not done now (YAGNI).

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

Tests live in `tests/test_schema_introspect.py` (also the CI pre-flight gate, Layer 2).

- **Unit — `expected_schema()` parser** (Codex #1/#2/#3):
  - asserts known columns present: `clarification_round`, `reply_epoch` in `payroll_runs`; `round`, `consumed_round`, `epoch` in `email_messages`.
  - **`record_only` is asserted present** — it is ALTER-only in `schema.sql` (`schema.sql:125`), proving the ALTER parse is load-bearing (Codex #3).
  - asserts a table-level constraint clause (e.g. `CONSTRAINT uq_email_run_purpose_round_epoch …`, `CHECK (…)`) is **NOT** mistaken for a column (Codex #3).
  - status values include `needs_operator` and are parsed from the **DO-block re-add list**; a fixture where the inline CHECK and the DO-block diverge proves the DO-block wins (Codex #2).
  - purpose values include `clarification_field_regression`; `unique_constraints` includes `uq_email_run_purpose_round_epoch` (Codex #4).
- **Unit — `diff_against_live()`** against a fake `information_schema`/`pg_constraint` result (fixture double, matching the project's `FakeConnection`/`fake_repo` pattern):
  - a DB missing a declared column → that column in `missing_columns`, `is_in_sync == False`;
  - **CHECK constraint returned in `status = ANY (ARRAY['received'::text, …])` form** (the real `pg_get_constraintdef` shape, Codex #1) is parsed correctly — a fixture in this exact form with `needs_operator` absent → `missing_status_values == ['needs_operator']`;
  - missing `uq_email_run_purpose_round_epoch` → `missing_unique_constraints` non-empty (Codex #4);
  - a DB with everything → all missing-sets empty, `is_in_sync == True`;
  - a DB with an EXTRA column not in `schema.sql` → still `in_sync` (extras are not drift).
- **Endpoint smoke** (optional, if it fits the existing app-test harness): `GET /health/schema` returns 200 with an in-sync fake and 503 with a drifted fake; body carries no connection string.
- No live-DB test in the hermetic CI (the eval/introspection jobs have no Supabase creds); the live check is exercised by Layer 2's post-flight step (which HAS `DATABASE_URL`) and Layer 3 against the deployed app.

## Rollout / Operational Notes

1. **FIRST, before merging (Codex #10): add the `DATABASE_URL` Actions secret** (Supabase pooler URL) in repo Settings → Secrets → Actions. If it is absent, `deploy-migrate.yml`'s validation step fails fast with a clear message (mirroring keepalive's `RENDER_URL` guard) — but adding it first means the very first run succeeds.
2. Merge this change. `deploy-migrate.yml` runs on the merge: pre-flight introspection tests → additive bootstrap (no-op, DB already in sync from the manual remediation) → post-flight live diff confirms `in_sync`.
3. `/health/schema` is live after the Render deploy; the next keep-alive cron exercises Layer 3.

## Backlog (future-milestone candidates, not this fix)

- Versioned/ordered migrations + migration-history table (tier 3 prevention).
- A hard deploy gate that blocks the deploy on drift (tier 2; needs a paid Render plan or a self-managed release step). Closing the Layer-2 auto-deploy/CI race (Codex #5) belongs here.
- Full-schema drift detection: column types, `NOT NULL`/`DEFAULT`, indexes, all constraints (extends Codex #4 beyond the one allowlisted UNIQUE).
- Auto-remediation from the keep-alive cron (deliberately excluded here — no unattended DDL on a timer).

## Review resolutions (Codex, 2026-07-07)

| # | Finding (tag) | Resolution |
|---|---------------|------------|
| 1 | `pg_get_constraintdef` returns `ANY (ARRAY[...])`, not `IN (...)` (BLOCKER) | Parser targets the `ANY (ARRAY[...])` form, strips `::text`; CHECKs selected by `conkey`, not regex/name. Unit test uses the real shape. |
| 2 | Parse the DO-block re-add list, not the inline CHECK (SHOULD-FIX) | Expected values parsed from the DO-block (reuse `_extract_do_block_status_values`); divergence test added. |
| 3 | Column parser fragile; test `record_only` (SHOULD-FIX) | Paren-balanced scanner, comment-skip, table-constraint exclusion; `record_only` (ALTER-only) is a required unit-test case. |
| 4 | Missing `uq_email_run_purpose_round_epoch` (SHOULD-FIX) | Added a targeted unique-constraint check + renamed the spec to "column and selected-constraint parity"; deeper drift → backlog. |
| 5 | "Can't outrun its migration" overstated (SHOULD-FIX) | Reframed as best-effort/converge-within-one-CI-run; residual race explicitly covered by Layers 1+3; hard gate → backlog. |
| 6 | Run tests before + live diff after bootstrap in CI (SHOULD-FIX) | Added pre-flight introspection tests and a post-flight `check_schema` live diff to `deploy-migrate.yml`. |
| 7 | Schema-qualify catalog queries (SHOULD-FIX) | All queries filter `table_schema='public'` / use `to_regclass('public.…')`. |
| 8 | Set `lock_timeout`/`statement_timeout` on the migration conn (CONSIDER) | bootstrap's admin connection sets both so lock contention fails RED, not hangs. |
| 9 | State the twice-weekly monitoring latency (CONSIDER) | Documented ~3–4 day worst-case for out-of-band-only drift; acceptable given Layer 2 synchronous verify. |
| 10 | Secret-before-merge / add a guard (NIT) | Rollout reordered (secret first); explicit `DATABASE_URL` validation step in the workflow. |
