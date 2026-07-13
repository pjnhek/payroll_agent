---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 05
requirements-completed: [COMM-01, COMM-02, COMM-03]
subsystem: db
tags: [comment-hygiene, docstrings, schema, comm-01, comm-02, comm-03]
requires:
  - app/db/schema_introspect.py (_strip_line_comments — the parity-safety mechanism)
provides:
  - comment-clean app/db/ layer (11 files, zero ticket/process references)
  - COMM-02 complete — split repo/ modules carry real purpose docstrings
affects:
  - app/db/repo/ (7 modules)
  - app/db/seed.py, app/db/bootstrap.py, app/db/supabase.py, app/db/schema.sql
tech-stack:
  added: []
  patterns: [text-only sweep, AST-equivalence proof, SQL token-stream parity proof]
key-files:
  created: []
  modified:
    - app/db/repo/__init__.py
    - app/db/repo/_shared.py
    - app/db/repo/runs.py
    - app/db/repo/emails.py
    - app/db/repo/roster.py
    - app/db/repo/pipeline_state.py
    - app/db/repo/demo.py
    - app/db/seed.py
    - app/db/bootstrap.py
    - app/db/supabase.py
    - app/db/schema.sql
decisions:
  - Runtime string literals carrying ticket IDs (1 log message, 2 print diagnostics) were rewritten — they are in the gate regex's scope and 15-RESEARCH explicitly requires it. This is the only departure from "zero executable-line changes"; no control flow, SQL, or data literal changed.
  - schema.sql parity proven by TOKEN-STREAM equality after comment stripping (stronger than a line-diff assertion) — zero DDL tokens modified, so no schema push is required.
metrics:
  duration: ~45min
  tasks: 3
  commits: 3
  files_modified: 11
  completed: 2026-07-13
status: complete
---

# Phase 15 Plan 05: DB-Layer Comment Hygiene Summary

Swept the eleven-file `app/db/` layer clean of ticket/provenance references and completed COMM-02 by replacing the split repo/ package's draft docstrings with real purpose statements — keeping every constraint and failure mode the comments actually documented, and proving the schema.sql edits parity-safe without touching a database.

## What Was Built

**Task 1 — `app/db/repo/` (7 modules), commit `20e7c0f`**

COMM-02 is complete: every split module now opens with a 1–2 sentence purpose docstring, with invariant paragraphs only where a genuine invariant exists. No TOC-style function index survives anywhere in the package; no split history remains.

- `_shared.py` — keeps the SQL-discipline invariant (parameterized `%s`/named placeholders only, **never** f-string SQL, including the header-chain `references` LIKE that reads like string assembly) and `_conn_ctx`'s package-attribute monkeypatch-seam explanation. Planning-doc citation dropped.
- `__init__.py` — keeps the facade seam caveat at full accuracy: a facade-level `monkeypatch.setattr(repo, ...)` does **not** intercept an internal same-module call inside an aggregate module (`record_run_error` → `set_status`/`_scrub` inside `runs.py`), so those tests must patch `app.db.repo.runs` directly. `tests/test_gateway.py` and `tests/test_persistence.py` depend on this being documented correctly.
- `emails.py` — `insert_email_message`'s arbiter documentation kept at full D-02 money-path depth: the arbiter/constraint-drift invariant is stated as an invariant ("change both, in the same step, or neither"), with the per-column rationale and the concrete failure mode (a retrigger resets `clarification_round` to 0, so without `epoch` in the arbiter the fresh round-0 send UPSERTs the historical row and corrupts the append-only audit log).
- `runs.py` — the `RUN_COLS` block now states the constraint plainly ("a column missing from this constant is invisible to every load_run caller") and enumerates the three columns whose prior omission disabled live behavior. Scrub-helper offset-safety rationale (the message is never normalized; only the candidate pattern is), the two-writer status rule, and the terminal-status CAS guard all keep their failure modes.
- `pipeline_state.py`, `demo.py`, `roster.py` — purpose docstrings; the alias-candidate JSONB merge rationale, the four `clarified_fields` outcomes (with their overpay/underpay consequences), the epoch-bump rationale in `clear_reply_context`, and `load_all_runs`'s `jsonb_typeof` guard (why a bare `COALESCE` raises) all preserved.

**Task 2 — `seed.py`, `bootstrap.py`, `supabase.py`, commit `fed6c2c`**

- `supabase.py` keeps the *full why* of double-checked locking — explicitly stating that **both** checks are required and neither alone is correct — plus the Supavisor/`prepare_threshold` gotcha, now with its actual failure mode (transaction-mode pooling hands the next statement to a different backend, where the server-side prepared statement does not exist).
- `seed.py` keeps the fixed-UUID rationale, the collision-pair construction (shared alias, distinct `full_name`s, so `UNIQUE(business_id, full_name)` still holds — with a warning not to "fix" it), and the SS wage-base straddle arithmetic verbatim, including the wages-vs-tax comparison trap.
- `bootstrap.py` keeps the password-scrub contract, the lock/statement-timeout bounds, and the dead-table/dead-column migration rationale.

**Task 3 — `app/db/schema.sql`, commit `1711320`**

Every `--` comment carrying a decision/review ID rewritten as constraint documentation. Constraint-adjacent comments keep full failure-mode depth: the `(run_id, purpose, round, epoch)` unique-index arbitration (restated as an explicit invariant paired with `insert_email_message`), the status/purpose CHECK atomic DROP+ADD rationale (a failed ADD rolls back the DROP, so the state-machine column is never left unconstrained), the `NOT NULL DEFAULT 0` dedup guard on `round`, and the `send_state` NULLABLE audit semantics.

## Verification

| Gate | Result |
|------|--------|
| Gate grep over all 11 files | **CLEAN** (zero hits, incl. extended vocabulary + `post-split`) |
| `tests/test_persistence.py` | 20 passed, 1 skipped |
| `tests/test_schema_introspect.py` | **9/9 passed** |
| `uv run pytest -q` (full suite) | **615 passed, 51 skipped**, 0 regressions |
| `uv run ruff check` | All checks passed |
| `uv run mypy` | Success — no issues in 114 source files |

**Fresh manifest first (per the plan's review-LOW finding):** the sweep was driven from a regenerated manifest run with the full gate regex over this plan's file set, not from the plan's discussion-time estimates. Actual counts differed from the estimates (e.g. `roster.py` had **0** hits, not the assumed handful, and needed no edit at all).

**Text-only proof (repo/ + seed/bootstrap/supabase):** each file's AST was parsed before and after with all docstrings stripped, and the dumps compared. Nine of ten Python files are **code-identical**. The two exceptions are documented under Deviations below.

**schema.sql parity proof (stronger than the plan required):** rather than asserting the line-diff only touches `--` lines, the comment-stripped **token stream** was compared against the prior revision using the exact same `re.sub(r"--[^\n]*", "", sql)` transform `schema_introspect._strip_line_comments` applies:

```
TOKEN STREAMS IDENTICAL: True
```

Zero DDL tokens were modified. Combined with `test_schema_introspect.py` passing 9/9, this proves the parsed schema surface is unchanged — **no database schema push is required by this plan**, and deploy-migrate CI cannot drift on it.

## Deviations from Plan

### [Rule 3 — rubric conflict resolved in favor of the gate] Three runtime string literals rewritten

The plan's acceptance criteria say "no executable-line changes in the commit diff(s)." Three **diagnostic string literals** carried ticket IDs inside the gate regex's scope, so leaving them would have failed the plan's own `done` criterion (zero gate-regex hits):

| File | Literal | Change |
|------|---------|--------|
| `app/db/repo/runs.py:637` | `logger.info` message | `(WR-04 guard, WR-03 CAS)` → `(terminal-status CAS guard)` |
| `app/db/bootstrap.py` | `print()` diagnostic | `(D-21-06 dead-table migration)` → `(dead-table migration)` |
| `app/db/bootstrap.py` | `print()` diagnostic | `(D-21-06 dead-column migration)` → `(dead-column migration)` |

This is explicitly sanctioned by 15-RESEARCH.md, which flags exactly this class: *"ticket-shaped strings live not only in comments but in runtime string literals ... the sweep must rewrite those too or the guard will fail on its own corpus."*

Confirmed safe before committing:
- AST diff was verified to contain **only** these three `Constant` nodes — no control flow, no SQL, no data literal, no `noqa`/`type: ignore` marker moved.
- `grep` confirmed **no test asserts on any of these strings** (the `WR-` matches in `tests/` are test-file *comments*, which belong to a different plan's file scope).

No Rule 4 (architectural) situations arose. No package installs. No DB connection was opened at any point.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path, file access pattern, or schema surface was introduced — the schema.sql token stream is provably unchanged (T-15-04 mitigated: text-only diffs, introspection-test proof, full suite + ruff + strict mypy green at every commit).

## Requirements Satisfied

- **COMM-01** — `app/db/` and `schema.sql` carry zero ticket-ID/process references; surviving comments document constraints.
- **COMM-02** — every split DB module carries a real module-purpose docstring; zero TOC style, zero split/provenance history.
- **COMM-03** — docstrings state purpose and invariants, not phase history.

## Self-Check: PASSED

- Modified files exist on disk: all 11 confirmed.
- Commits exist: `20e7c0f`, `fed6c2c`, `1711320` — all confirmed in `git log`.
- Gate grep clean across all 11 files.
- Full suite / ruff / mypy green.
