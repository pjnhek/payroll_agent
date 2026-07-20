"""GET /ops — the transport-surface view.

Renders queue depth (split pending vs leased), the oldest currently-due
pending job's age, the open-backlog attempts distribution, the bounded
dead-letter list, and the banner for runs the queue cannot account for.
`/runs` stays the payroll surface — the run's own business status; `/ops`
is the transport surface — the job queue's own state. A run's status and
its queue state are two different state machines, and nothing on this page
may present the queue's state as if it were the run's.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.config import get_settings
from app.db import repo
from app.routes.templating import templates

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()

# The cron in .github/workflows/pump.yml schedules a drain every 30 minutes
# ("*/30 * * * *"; see README's pump cadence / instance-hour budget section
# for the arithmetic behind that number). This constant exists so the page
# can render the oldest-due-pending age next to the bound that makes it
# meaningful instead of as a bare number, and a test parses the workflow's
# cron expression directly and asserts it against this value, so a cadence
# change that forgets to update this constant reds instead of silently
# turning the rendered comparison into a lie.
PUMP_CADENCE_MINUTES = 30


@router.get("/ops")
def ops_view(request: Request) -> Response:
    """Read the transport surface and render it. Deliberately side-effect free.

    Durable queue workers own automatic recovery; an operator acts through
    the explicit mutation routes on run detail (Retrigger), never from this
    page. This route's job is to make a problem findable; run detail's job
    is to act on it. Every read below is a bounded SELECT — no drain, no
    enqueue, no status write happens on this GET.
    """
    try:
        counts = repo.count_jobs_by_state()
        oldest_due_pending_seconds = repo.oldest_due_pending_age_seconds()
        attempts_rows = repo.attempts_distribution()
        dead_letter_rows = repo.list_dead_letter_jobs()
        unaccounted_error_rows = repo.list_unaccounted_error_runs()
    except Exception:
        # DB unavailable (no pool / no connection): render zeroed/empty state
        # rather than 500, matching the rest of the dashboard's cold-start
        # tolerance.
        logger.debug("ops metrics unavailable — rendering zeroed/empty state")
        counts = {"pending": 0, "leased": 0}
        oldest_due_pending_seconds = None
        attempts_rows = []
        dead_letter_rows = []
        unaccounted_error_rows = []

    return templates.TemplateResponse(
        request,
        "ops.html",
        {
            "pending_count": counts.get("pending", 0),
            "leased_count": counts.get("leased", 0),
            "oldest_due_pending_seconds": oldest_due_pending_seconds,
            "attempts_rows": attempts_rows,
            "max_attempts": get_settings().max_attempts,
            "dead_letter_rows": dead_letter_rows,
            "unaccounted_error_rows": unaccounted_error_rows,
            "pump_cadence_minutes": PUMP_CADENCE_MINUTES,
            "generated_at": datetime.now(UTC),
        },
    )
