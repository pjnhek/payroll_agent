# Phase 17: The Pump - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 17-the-pump
**Areas discussed:** Pump auth mechanism, Drain loop & counts, pump.yml composition, Response & failure scope

---

## Pump auth mechanism

### Auth method

| Option | Description | Selected |
|--------|-------------|----------|
| Bearer token header | `Authorization: Bearer $PUMP_TOKEN`, constant-time compared vs a `PUMP_TOKEN` env var (sync:false secret + GitHub Actions secret). Secret stays out of URL/logs. | ✓ |
| Custom header (X-Pump-Token) | Same shared secret in a bespoke header; no advantage over Bearer. | |
| Query-string token | `?token=` — leaks the secret into access/Render/Actions logs. | |

**User's choice:** Bearer token header
**Notes:** Matches the existing render.yaml `sync:false` secret pattern. Machine-to-machine only — not a step toward operator/dashboard auth (which stays the accepted out-of-scope gap).

### Auth failure response

| Option | Description | Selected |
|--------|-------------|----------|
| 401 Unauthorized | Standard for a bad/missing credential; `curl -f` reds so misconfig is visible. | ✓ |
| 404 Not Found | Hides the route but masks real cron misconfig as "route gone". | |
| 403 Forbidden | "Authenticated but not allowed" — doesn't fit a shared-secret gate. | |

**User's choice:** 401 Unauthorized

### Empty-secret behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Fail closed — reject all | No configured token → every call 401/503; no unauthenticated drain ever. | ✓ |
| Fail open in dev only | Mirror ALLOW_UNSIGNED_FIXTURES; adds a bypass flag to a money-moving trigger. | |
| Fail open always | Ships an open drain endpoint if the secret is dropped. | |

**User's choice:** Fail closed — reject all
**Notes:** No dev bypass needed — tests call `drain_once()` directly (Phase 16 D-06).

---

## Drain loop & counts

### Producing the counts

| Option | Description | Selected |
|--------|-------------|----------|
| Enrich the drain seam | `drain_once()` returns a terminal outcome (empty/done/retried/dead/fenced); pump aggregates exact per-invocation counts; workers ignore the value. | ✓ |
| Snapshot query | Keep bool; read done/retried/dead/depth from a GROUP BY snapshot — skews under concurrent workers. | |
| Claimed + depth only | Pump returns only claimed + depth; defers the breakdown to Phase 21 — under-delivers criterion #1. | |

**User's choice:** Enrich the drain seam
**Notes:** Cost is threading the terminal `dead`/`retried` state (decided inside `fail_job`) up through the completion write path; worker truthiness contract (`empty` stays falsy) must be preserved.

### Loop bound

| Option | Description | Selected |
|--------|-------------|----------|
| Drain-to-empty + safety cap | Loop until empty, stop at a max-jobs / wall-clock cap so one request can't run unbounded. | ✓ |
| Drain-to-empty, no cap | Simplest; a backlog or fast-re-eligible job could run the request long. | |
| Single drain_once() | One job per 30-min hit — a backlog would take hours to clear. | |

**User's choice:** Drain-to-empty + safety cap
**Notes:** Cap values derived from measured pipeline runtime, documented at the call site (same discipline as LEASE_SECONDS).

---

## pump.yml composition

### Workflow structure

| Option | Description | Selected |
|--------|-------------|----------|
| One job, three curl -f steps | 30-min cron: authenticated /internal/pump, then /health/ready, then /health/schema — all `curl -f`. | ✓ |
| Pump + schema only (drop ready) | Pump touches the DB anyway, but criterion #4 mandates both keepalive jobs including the readiness wake. | |
| Split into two workflows | Contradicts "pump.yml is the only cron". | |

**User's choice:** One job, three curl -f steps

### workflow_dispatch

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, keep it | One-click re-enable after GitHub's 60-day auto-disable (carries keepalive's rationale). | ✓ |
| No, schedule only | Re-enable means a trip into repo settings. | |

**User's choice:** Yes, keep it

---

## Response & failure scope

### RED scope for business outcomes

| Option | Description | Selected |
|--------|-------------|----------|
| No — 200 with counts | Dead-letter/retry are normal operation; pump returns 200 + counts; the alarm is OPS-01/Phase 21. | ✓ |
| Yes — non-2xx on dead > 0 | Reds on a dead-letter; pulls Phase 21 alarming forward and spams RED on an expected dead-letter. | |

**User's choice:** No — 200 with counts

### Infra-failure response

| Option | Description | Selected |
|--------|-------------|----------|
| 5xx — cron goes RED | Real outage (pool exhausted, Supabase down) → 5xx → RED, same posture as the health probes. | ✓ |
| 200 with an error field | Cron stays GREEN during a real outage — the silent-failure mode `-f` exists to avoid. | |

**User's choice:** 5xx — cron goes RED

---

## Claude's Discretion

- Exact `PUMP_TOKEN` env var name and response JSON key names/shape.
- Whether `/internal/pump` is `POST` or `GET` (idempotent drain; either defensible).
- The precise max-jobs / wall-clock cap values (derived from measured runtime, documented).
- Whether queue-depth is read in the final claim transaction or a separate cheap `SELECT count(*)`.

## Deferred Ideas

- Ops view + swallowing-bug alarm (queue depth / oldest-pending age / dead-letter list) — OPS-01, Phase 21.
- `ok`/`retryable`/`terminal` failure contract + real backoff classification — FAIL-01/02, Phase 18.
- Deleting `sweep_stranded_runs` / dashboard-page-load-as-cron — FAIL-03, Phase 18.
- Adaptive cadence / dynamic cap tuning — out of scope (fixed 30-min cron + static documented cap).
