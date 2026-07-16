"""GET /internal/pump — the authenticated external-cron drain trigger.

Render free has no background-worker primitive and only wakes on inbound HTTP,
so this route is the PRIMARY execution trigger for the durable job queue, not
a redundancy alongside the in-process worker threads (app/queue/worker.py).
It loops the exact SAME `drain.drain_once()` those threads call — never a
route-local fork of the claim/dispatch/complete/fail sequence — bounded by a
dual cap (max-jobs AND wall-clock), and aggregates each call's `DrainOutcome`
into real per-invocation counts, never a bare 200.

Sync `def`, modeled on app/routes/health.py: FastAPI runs a plain `def` route
in the AnyIO threadpool, keeping the event loop free while the drain loop
performs blocking psycopg calls and, per job, potentially a long LLM call
inside dispatch.handle.
"""
from __future__ import annotations

import hmac
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import repo
from app.queue.drain import DrainOutcome, drain_once

logger = logging.getLogger("payroll_agent.queue")

router = APIRouter()

# The dual cap, checked BETWEEN drain_once() calls (never mid-call), so a
# request can begin ONE final job just under the wall-clock deadline.
#
# CORRECTNESS rests on lease recovery (lease_seconds=900, app/config.py), NOT
# on these caps or the cron's own curl budget: a job a pump request does not
# finish is held by its lease. While it has attempts remaining, the next
# cadence reclaims and idempotently re-runs it (SKIP LOCKED); after its final
# attempt, the shared drain's bounded reaper atomically settles the expired
# lease as dead before reporting the queue empty.
#
# _MAX_WALL_CLOCK_SECONDS=120 is the between-jobs cap. The cron's own
# `curl --max-time` budget is sized independently and larger (Render
# cold-start plus this cap plus one worst-case job's external-call
# allowance — the summed explicit provider timeouts on the longest
# clarification path — with deterministic compute/DB/overhead on top, so it
# claims no headroom), provisional until a live smoke test confirms Render's
# undocumented server-side request-duration ceiling. It is NOT derived from
# the max inter-write stall gap in app/routes/runs.py (a stall threshold
# between two DB writes, not a total single-job runtime). A rare overrun
# goes RED but is safe: the sync route's in-flight work is not cancelled by
# a client-side timeout, so the drain most likely finishes server-side
# (RED-but-succeeded); attempts-remaining leases are reclaimable and expired
# final-attempt leases are settled by drain_once()'s bounded reaper.
_MAX_JOBS_PER_PUMP = 20
_MAX_WALL_CLOCK_SECONDS = 120


def _authorized(request: Request) -> bool:
    """Constant-time Bearer compare, fail-closed on an unset/empty secret.

    An empty/unset PUMP_TOKEN must reject EVERY call, never fall open —
    checked and returned BEFORE the compare so a misconfigured deploy can
    never be satisfied by an empty Authorization header. Uses
    `hmac.compare_digest`, never `==` — a naive string compare on a bearer
    secret is a timing side-channel.
    """
    token = get_settings().pump_token
    if not token:
        return False
    expected = f"Bearer {token}".encode()
    got = request.headers.get("authorization", "").encode()
    return hmac.compare_digest(got, expected)


# GET (not POST): simplest for a curl cron, and the drain is idempotent —
# repo.claim_job()'s SKIP LOCKED makes a repeat or concurrent hit safe.
@router.get("/internal/pump")
def pump(request: Request) -> JSONResponse:
    if not _authorized(request):
        # 401, deliberately not 404 — a misconfigured PUMP_TOKEN must be
        # loud (the cron's `curl -f` goes RED), not silently masked as
        # "route gone."
        raise HTTPException(status_code=401, detail="unauthorized")

    counts = dict.fromkeys(
        ("done", "retried", "dead", "fenced", "reaped_final_lease"), 0
    )
    claimed = 0
    drained = 0
    deadline = time.monotonic() + _MAX_WALL_CLOCK_SECONDS
    try:
        while drained < _MAX_JOBS_PER_PUMP and time.monotonic() < deadline:
            outcome = drain_once()
            if outcome is DrainOutcome.EMPTY:
                break
            drained += 1
            if outcome is DrainOutcome.REAPED_FINAL_LEASE:
                counts["dead"] += 1
                counts["reaped_final_lease"] += 1
            else:
                claimed += 1
                counts[outcome.value] += 1
        queue_depth = repo.count_open_jobs()
    except Exception as exc:  # noqa: BLE001 — honest catch-all, see comment below.
        # This includes a genuine infra outage on claim/count AND a
        # propagated drain_once() double-failure (fail_job's own write
        # failed during an outage) — an unexpected programming error would
        # also land here. In normal operation only infra failures reach this
        # branch. Never log/return str(exc) — it could carry a connection
        # string.
        logger.error("pump: infra failure mid-drain: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="pump unavailable") from exc

    # A reaped final lease is dead transport work, but no worker claimed it in
    # this request. Every other non-empty outcome represents one claimed job.
    # Therefore:
    # claimed == done + retried + (dead - reaped_final_lease) + fenced.
    return JSONResponse({"claimed": claimed, **counts, "queue_depth": queue_depth})
