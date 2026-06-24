---
phase: "06"
plan: "03"
type: checkpoint
status: complete
completed: 2026-06-24
requirements:
  - OPS-01
  - OPS-02
---

# 06-03 SUMMARY — Thin Render deploy + Supabase standup (BLOCKING human checkpoint)

**Type:** `autonomous: false` — human-executed credentialed deploy. The agent prepared
all artifacts (06-01, 06-02); the human executed the deploy and confirmed the live stack.

## Outcome: ✅ PASS — thin stack live, Supabase reachable from Render, 06-05 unblocked

## Part A — D-08a local Supabase pooler pre-check (laptop)

| Check | Result |
|-------|--------|
| psycopg3 pool connects over 6543 (`prepare_threshold=None`) | ✅ `Pool OK: (1,)` |
| Schema + seed via **5432** session pooler (`bootstrap --reset` + `seed`) | ✅ Seeded 3 businesses, 7 employees |
| Schema + seed via **6543** transaction pooler (also tested) | ✅ Works too |
| `pytest -m integration` against live DB | ⚠️ surfaced a real bug (see below), then fixed |

**A4 RESOLVED (⚠ CONFIRM flag closed):** `bootstrap --reset` and `seed` succeed on **BOTH
6543 (transaction) and 5432 (session)** poolers. Per D-15, **prefer 5432 for DDL** going
forward regardless — both work, 5432 is the sanctioned DDL path.

**Production Supabase:** project ref `hdlfmlshdqcxwzlqfkym`, region `us-west-2`
(host `aws-1-us-west-2.pooler.supabase.com`). Direct host never used (IPv6-only).

### Bug surfaced + fixed at this gate (the value of a live integration run)
`tests/test_dashboard.py::test_health_ready_returns_200_with_db` (added in 06-08) referenced
a `seeded_db` fixture that existed only as **file-local copies** in test_gateway/test_persistence/
test_seed_roundtrip — so the live `pytest -m integration` errored with `fixture 'seeded_db' not
found`. This was masked through every prior mocked run (the test was deselected/xfailed). Fixed
in commit `820ddb6`: promoted the shared two-factor-guarded `seeded_db` fixture (+ `_HAS_DB`/
`_HAS_RESET`/`_SKIP_LIVE_DB`) to `conftest.py` and deleted the three duplicates (DRY). 463 tests
now collect with zero fixture errors; mocked suite 436 passed.

## Part B — D-09/D-09a thin Render deploy

**Render URL:** `https://payroll-agent.onrender.com` (deployed commit `820ddb6`, Docker, Free).

| Check | Result |
|-------|--------|
| `GET /health/live` | ✅ `{"status":"ok"}` (no DB) |
| `GET /health/ready` | ✅ `{"status":"ready"}` `[200]` — **Render → Supabase 6543 pooler works** (real SELECT on `businesses`) |
| `GET /` landing page | ✅ `200` |
| Deployed route table | ✅ all 17 routes registered (verified via `/openapi.json`) |
| Cold-start wake | ⏭️ **deferred/accepted** — known Render-free spin-down behavior (T-06-03-03 disposition = accept); documented in README per D-11; pre-warm before demo recording (D-05) |

**Deploy gotcha observed:** an early `/health/ready` curl returned 404 — this was a transient
mid-redeploy container swap (two pushes triggered redeploys: the 46-commit initial push + the
`seeded_db` fix). Once the new container was healthy, `/health/ready` → 200. The route was never
actually missing (same commit as `/health/live`); the `/openapi.json` route dump confirmed it.

## Between-gate steps (done before 06-05)

| Step | Result |
|------|--------|
| Resend inbound webhook at `https://payroll-agent.onrender.com/webhook/inbound` (events=`email.received`) | ✅ created; Signing Secret saved |
| Render env: real `RESEND_API_KEY` + `WEBHOOK_SIGNING_SECRET` (placeholders replaced) | ✅ updated |
| `RESEND_REPLY_TO` = confirmed inbound `.resend.app` address | ✅ set |
| `RENDER_URL` GitHub Actions repository secret | ✅ set (keepalive.yml ready) |
| `ALLOW_UNSIGNED_FIXTURES` NOT set in Render env (prod default False) | ✅ enforced (absent) |

## Security (threat model dispositions confirmed)

- T-06-03-01 (DATABASE_URL disclosure): mitigated — set as Render secret, never in git (render.yaml `sync:false`).
- T-06-03-05 (unsigned fixtures in prod): mitigated — `ALLOW_UNSIGNED_FIXTURES` deliberately absent → prod default False.
- T-06-03-06 (signing secret one-time reveal): mitigated — saved on webhook creation.

## Unblocks
**06-04** (wire real Resend provider behind gateway seam) and **06-05** (email round-trip verify):
real Resend credentials in Render env, webhook live, service running, DB reachable.
