---
phase: "06"
plan: "06"
subsystem: demo-ops
tags: [demo, routing, readme, cleanup, architecture]
dependency_graph:
  requires: ["06-05"]
  provides: ["demo-reset-script", "per-fixture-routing", "readme", "architecture-diagram"]
  affects: ["app/main.py", "app/email/gateway.py", "scripts/demo_reset.py", "README.md", "docs/"]
tech_stack:
  added: []
  patterns: ["_SEED_CONTACTS constant routing", "FK-safe demo reset", "demo_sender_bindings re-arm"]
key_files:
  created:
    - scripts/demo_reset.py
    - docs/architecture.mmd
    - docs/architecture.png
    - docs/architecture.svg
  modified:
    - app/main.py
    - app/email/gateway.py
    - README.md
    - tests/test_dashboard.py
decisions:
  - "HIGH-1 (R4): per-fixture from_addr resolved from _SEED_CONTACTS constant (zero DB coupling); seed contacts permanently stable per 06-08 HIGH-2"
  - "demo_reset.py re-arms demo_sender_bindings via UPSERT only; never mutates businesses.contact_email"
  - "PNG generated via npx @mermaid-js/mermaid-cli with system Chrome puppeteer config"
metrics:
  duration_minutes: 45
  completed_date: "2026-06-24"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 8
---

# Phase 06 Plan 06: Wave 5 Demo Polish + README Summary

Per-fixture demo routing via stable _SEED_CONTACTS constant, FK-safe demo_reset.py with demo_sender_bindings re-arm, full recruiter README with architecture diagram, and removal of temporary debug logging.

## What Was Built

### Task 1: HIGH-1 per-fixture routing + demo_reset.py + debug log removal

**app/main.py:**
- Added `business_name` key to all 4 existing `_DEMO_FIXTURES` entries, matching seed.py _BUSINESSES names exactly
- Added `unknown_shorthand_metro` entry using the REAL committed `eval/fixtures/04_unknown_shorthand_metro.json` fixture ("Dave Reyes", Metro Deli Group, from_addr hr@metrodeli.example) — Beat 2 hero
- In `demo_send_test` handler: replaced the old `fixture_data.get("from_addr")` call with HIGH-1 per-fixture resolution: `_SEED_CONTACTS[fixture_meta["business_name"]]` — zero DB coupling, always correct because seed contacts are permanently stable (06-08 HIGH-2)
- No DEMO_CONTACT_EMAIL env var override at send time; no gate_block_hero phantom key

**scripts/demo_reset.py:**
- `--confirm` flag required for destructive reset; no-arg prints usage and exits 0
- FK-safe deletion order: `UPDATE payroll_runs SET source_email_id = NULL` → delete paystub_line_items → delete email_messages → delete payroll_runs
- NO alias_audit reference (table does not exist in schema.sql — LOW-4 fix)
- Calls `seed()` to reset known_aliases via ON CONFLICT DO UPDATE
- Re-arms demo identity: INSERT INTO demo_sender_bindings ... ON CONFLICT DO UPDATE (never UPDATE businesses SET contact_email)
- `--reset-aliases` mode: seed() + re-arm, no delete, no --confirm needed
- Exposes `_rearm_demo_identity(conn)` as a public function for unit-testing

**app/email/gateway.py:**
- Removed `LOG_WEBHOOK_DEBUG_IDS` debug block (if os.getenv block + logger.info call) — T-06-06-03
- Removed `import os` (no longer used after debug block removal)
- Updated docstring to remove Step 4b reference

**Tests (TDD — RED then GREEN):**
- `test_demo_send_test_coastal_routes_to_coastal`: proves coastal_exact routes to Coastal Cleaning Co. unconditionally via _SEED_CONTACTS
- `test_demo_send_test_metro_unknown_shorthand_routes_to_metro`: proves unknown_shorthand_metro routes to Metro Deli Group
- `test_demo_reset_rearming_writes_demo_sender_bindings_not_contact_email`: unit test via FakeConnection proves _rearm_demo_identity writes demo_sender_bindings only, never UPDATE businesses

### Task 2: Full README + architecture diagram

**README.md:** Full rewrite with:
- Thesis ("messy payroll email in; correct human-approved payroll out")
- Verbatim locked disclaimer: Educational only, OBBBA excluded, Additional Medicare unmodeled
- Mermaid diagram fenced block (13 nodes, awaiting_reply + awaiting_approval pause states, decide.py code gate)
- Architecture PNG embed with fallback caption
- Demo recording placeholder + eval chart reference
- Key design choices (3 bullets)
- For Engineers section: stack table, local setup, run tests, deploy (5 env vars), outbound sender constraint (onboarding@resend.dev + Add Domain upgrade path), keep-alive, demo reset command with --confirm, Additional Medicare note

**docs/architecture.mmd:** Mermaid source file (diffable, regeneratable)

**docs/architecture.png:** PNG generated via `npx @mermaid-js/mermaid-cli` with system Chrome puppeteer config (62KB, 800x600)

**docs/architecture.svg:** SVG alongside PNG (29KB)

## Operator Action Required

**IMPORTANT: After this deployment, the operator must also remove `LOG_WEBHOOK_DEBUG_IDS=true` from the Render dashboard environment variables.** The code removal alone does not unset the deployed env var — the variable exists but is now dead code. Remove it from Render → Service → Environment to keep the env clean.

## Test Results

- Baseline: 455 mocked-suite tests
- After Task 1 + Task 2: **458 passed** (3 new tests added, 0 failed, 0 regressions)
- `uv run pytest -q -m "not integration and not live_llm"`: 458 passed, 17 deselected

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 192b48a | test | add failing tests for HIGH-1 per-fixture routing and demo_reset re-arming (RED) |
| 95d0fd7 | feat | HIGH-1 per-fixture routing fix + demo_reset.py + remove debug logging (GREEN) |
| 3369376 | feat | full README + architecture diagram (Mermaid source + PNG + SVG) |

## Deviations from Plan

**1. [Rule 1 - Bug] Mermaid `B[/webhook/inbound]` syntax error**
- **Found during:** Task 2 PNG generation
- **Issue:** Mermaid CLI (version installed via npx) treats `/` inside `[...]` node labels as a special token (trapezoid shorthand), causing a lexical error
- **Fix:** Changed `B[/webhook/inbound]` to `B["POST /webhook/inbound"]` using double-quoted label which escapes special characters. Same approach applied to all node labels with special chars. .mmd file updated accordingly.
- **Files modified:** docs/architecture.mmd
- **Commit:** 3369376

**2. [Rule 3 - Blocking] npx mermaid CLI no-arg invocation failed**
- **Found during:** Task 2 PNG generation (first attempt)
- **Issue:** `npx -y @mermaid-js/mermaid-cli mmdc -i ...` passed `mmdc` as an argument to the installed package's binary, which expects the options directly; also the `npx -y` download flag is deprecated in npx 11.x
- **Fix:** Used `npx @mermaid-js/mermaid-cli -i docs/architecture.mmd -o docs/architecture.png -p /tmp/puppeteer-config.json` with a puppeteer config pointing to the system Chrome installation (`/Applications/Google Chrome.app/...`)
- **Files modified:** docs/architecture.png (generated)
- **Commit:** 3369376

## Known Stubs

No stubs. All files created/modified are fully wired.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced. The gateway.py cleanup removes an information disclosure path (T-06-06-03 closed).

## Self-Check: PASSED

All files confirmed on disk:
- app/main.py: FOUND
- scripts/demo_reset.py: FOUND
- README.md: FOUND
- docs/architecture.mmd: FOUND
- docs/architecture.png: FOUND
- app/email/gateway.py: FOUND

All commits confirmed in git log:
- 192b48a (test — RED): FOUND
- 95d0fd7 (feat — GREEN): FOUND
- 3369376 (feat — Task 2): FOUND
