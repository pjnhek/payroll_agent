---
phase: "06"
plan: "02"
subsystem: "ops"
tags: [deploy, docker, render, health-routes, keepalive, config]
dependency_graph:
  requires: []
  provides:
    - Dockerfile
    - .dockerignore
    - render.yaml
    - .github/workflows/keepalive.yml
    - app/config.py resend_api_key + webhook_signing_secret + resend_from_addr + allow_unsigned_fixtures + resend_reply_to
    - app/main.py /health/live + /health/ready
    - .env.example RESEND_* vars
  affects:
    - "06-03 (human deploy checkpoint reads these artifacts)"
    - "06-04 (reads resend_from_addr, resend_reply_to, resend_api_key, webhook_signing_secret, allow_unsigned_fixtures from config)"
tech_stack:
  added:
    - "ghcr.io/astral-sh/uv:0.11.23 (build stage only; not in runtime)"
  patterns:
    - "Multi-stage Docker build: builder (uv sync --frozen --no-dev) + runtime (no uv binary)"
    - "Shell-form CMD for ${PORT:-10000} expansion (Pitfall 3 avoidance)"
    - "WORKDIR=/app in both stages for relative path resolution (Pitfall 2)"
    - "render.yaml Blueprint with sync:false secrets"
    - "GitHub Actions cron + workflow_dispatch keep-alive pattern"
    - "D-20 health probe split: liveness (no DB) + readiness (SELECT businesses)"
    - "REPLY-TO topology: resend_reply_to field routes client replies to inbound webhook address"
key_files:
  created:
    - Dockerfile
    - .dockerignore
    - render.yaml
    - .github/workflows/keepalive.yml
  modified:
    - app/config.py
    - app/main.py
    - .env.example
    - tests/test_dashboard.py
decisions:
  - "HIGH-1 fix applied: runtime CMD uses .venv/bin/uvicorn directly (no uv binary in runtime stage)"
  - "Shell-form CMD required for ${PORT:-10000} expansion (exec-form silently uses literal string)"
  - "WORKDIR=/app enforced in both stages (Jinja2Templates, StaticFiles, eval/chart.svg are relative paths)"
  - "render.yaml healthCheckPath=/health/live (no DB) so Supabase blip never fails Render deploy"
  - "RESEND_REPLY_TO as plain value: entry in render.yaml (not sync:false — it is an address, not a credential)"
  - "allow_unsigned_fixtures absent from render.yaml (BLOCKER-2: production safety)"
  - "keepalive.yml: curl -f with no swallow (MEDIUM-7 fix: OPS-03 goes RED on real failures)"
metrics:
  duration: "5 minutes"
  completed_date: "2026-06-24"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 4
---

# Phase 06 Plan 02: Deploy Artifacts Summary

**One-liner:** Multi-stage uv-in-image Dockerfile + Render blueprint + GitHub Actions keep-alive + Resend config fields + D-20 health probes, ready for the D-09 human deploy checkpoint.

## What Was Built

### Task 1: Dockerfile, .dockerignore, render.yaml (commit 550b0ed)

**Dockerfile** — Multi-stage uv-in-image pattern (Astral official, D-19):
- Builder stage: `python:3.12-slim AS builder` + `ghcr.io/astral-sh/uv:0.11.23` (pinned)
- `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, `UV_PYTHON_DOWNLOADS=0` env vars
- Layer 1: `COPY pyproject.toml uv.lock` + `uv sync --frozen --no-dev --no-install-project` (cache-friendly)
- Layer 2: `COPY . .` + `uv sync --frozen --no-dev` (installs project)
- Runtime stage: `python:3.12-slim AS runtime`, `COPY --from=builder /app /app`, `ENV PATH="/app/.venv/bin:$PATH"`
- HIGH-1 fix: `CMD ["/bin/sh", "-c", ".venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]`
  - Shell form required for `${PORT:-10000}` expansion (exec-form ignores env vars — Pitfall 3)
  - `.venv/bin/uvicorn` directly — uv binary NOT in runtime stage (build tool only)
  - `WORKDIR=/app` in both stages (Jinja2Templates, StaticFiles, eval/chart.svg use relative paths — Pitfall 2)

**`.dockerignore`** — Excludes `.venv/`, `.git/`, `tests/`, `.env`, `__pycache__/`, `.planning/`, `payroll_agent.egg-info/`, `scripts/`, `.github/`, `eval/fixtures/*_extraction.json`. Keeps `app/`, `eval/chart.svg`, `eval/summary.json`, `eval/fixtures/`, `fixtures/` (demo fixtures baked into image per D-21).

**`render.yaml`** — Render Blueprint:
- `type: web`, `runtime: docker`, `healthCheckPath: /health/live` (D-20: liveness, no DB)
- 5 `sync: false` secrets: `DATABASE_URL`, `RESEND_API_KEY`, `WEBHOOK_SIGNING_SECRET`, `EXTRACTION_API_KEY`, `DRAFT_API_KEY`
- Plain `value:` entries: `EXTRACTION_MODEL`, `DRAFT_MODEL`, `EXTRACTION_BASE_URL`, `DRAFT_BASE_URL`, `TAX_YEAR`, `ALLOW_LIVE_LLM`, `RESEND_FROM_ADDR`, `RESEND_REPLY_TO`
- `RESEND_REPLY_TO` as plain `value:` (not sync:false — it is an address, not a credential; operator overrides in dashboard)
- `ALLOW_UNSIGNED_FIXTURES` intentionally absent (BLOCKER-2: must never be true in production)

### Task 2: config.py + health routes + .env.example + keepalive.yml (commit 06b208a)

**`app/config.py`** — Five new fields after `allow_live_llm`:
- `resend_api_key: str = ""` — RESEND_API_KEY env var
- `webhook_signing_secret: str = ""` — WEBHOOK_SIGNING_SECRET env var
- `resend_from_addr: str = "onboarding@resend.dev"` — shared free-tier sender
- `allow_unsigned_fixtures: bool = False` — BLOCKER-2 dev-mode bypass flag (default production-safe)
- `resend_reply_to: str = ""` — REPLY-TO topology: inbound .resend.app address (omitted from send when empty)

**`app/main.py`** — Two new health routes:
- `GET /health/live` returns `{"status": "ok"}` with NO DB access (Render deploy healthCheckPath, T-06-02-01: no stack/version exposed)
- `GET /health/ready` runs `SELECT 1 FROM businesses LIMIT 1` via psycopg pool, returns `{"status": "ready"}` or 503 (keep-alive cron target, T-06-02-02: no connection string in error response)
- D-21 comment added to `/eval/chart.svg` confirming WORKDIR=/app dependency

**`.env.example`** — Added four Resend env var stubs with reply-to topology comment for dev parity.

**`.github/workflows/keepalive.yml`** — Keep-alive workflow:
- `schedule: cron: "17 10 * * 1,4"` (10:17 UTC Monday+Thursday, avoids :00 high-load)
- `workflow_dispatch:` (REQUIRED: manual re-enable after 60-day auto-disable — Pitfall 6)
- Step 1: validate `RENDER_URL` secret is set (exit 1 if missing)
- Step 2: `curl -f --max-time 90 "$RENDER_URL/health/ready"` — MEDIUM-7 fix: `-f` flag fails on HTTP 4xx/5xx, no `|| echo` swallow so OPS-03 goes RED on real outages

**`tests/test_dashboard.py`** — Two new health tests:
- `test_health_live_returns_200_no_db`: GREEN (asserts 200 + `{"status": "ok"}`, no DB needed)
- `test_health_ready_returns_200_with_db`: `@pytest.mark.integration` (skip-guarded, live DB required)

## Verification Results

All plan verification checks passed:
- `grep "\.venv/bin/uvicorn" Dockerfile` exits 0 (HIGH-1 fix confirmed)
- `grep "uv sync --frozen --no-dev" Dockerfile` exits 0 (D-19 builder stage)
- `uv run pytest tests/test_dashboard.py -k "health_live" -x -q` 1 passed
- `grep "sync: false" render.yaml | wc -l` returns 5
- `grep "workflow_dispatch" .github/workflows/keepalive.yml` exits 0
- `grep "curl -f" .github/workflows/keepalive.yml` exits 0
- `grep -c "|| echo" .github/workflows/keepalive.yml` returns 0
- All config field checks exit 0
- ALLOW_UNSIGNED_FIXTURES absent from render.yaml confirmed
- REPLY-TO fields in config.py, render.yaml, .env.example confirmed

## Deviations from Plan

### Pre-existing Test Failures (Out of Scope — Rule 4 boundary)

During final verification, 30 pre-existing test failures were observed across `test_threading.py`, `test_webhook.py`, `test_orchestrator_states.py`, and `test_llm_client.py`. These failures were confirmed to pre-exist at the base commit (before any Task 2 changes) by temporarily stashing Task 2 changes and running the same tests. They originate from the parallel 06-01 agent's in-flight changes (new required config fields or module changes not yet in this worktree's base). These are out-of-scope per the deviation scope boundary rule: they are in unrelated files and caused by a different plan's changes.

The plan's stated pass threshold (>=422 passed, no regressions from 06-02) will be verifiable after the orchestrator merges all wave 1 agents.

No deviations introduced by 06-02 code.

## Known Stubs

None. All new config fields have functionally correct defaults suitable for production and local dev.

## Threat Flags

No new threat surface beyond the plan's documented threat model (T-06-02-01 through T-06-02-SC). Both health routes return only structured status strings with no sensitive data.

## Self-Check: PASSED

Files created exist:
- `Dockerfile` FOUND
- `.dockerignore` FOUND
- `render.yaml` FOUND
- `.github/workflows/keepalive.yml` FOUND

Files modified exist with expected content:
- `app/config.py` FOUND with resend_reply_to field
- `app/main.py` FOUND with /health/live route
- `.env.example` FOUND with RESEND_REPLY_TO
- `tests/test_dashboard.py` FOUND with test_health_live_returns_200_no_db

Commits verified:
- 550b0ed: Task 1 (Dockerfile, .dockerignore, render.yaml)
- 06b208a: Task 2 (config.py, main.py, .env.example, keepalive.yml, test_dashboard.py)
