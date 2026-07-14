"""The `run_pipeline` job handler — the one place the queue tier is allowed
to advance `payroll_runs.status`, and the only two ways it may do so.

INVARIANT J-1, restated precisely (this wording is the one that must survive
in this file, not an earlier, looser draft): `payroll_runs.status` has
exactly TWO permitted writers reachable from the queue tier, and both are
compare-and-swap writes — a conditional `UPDATE ... WHERE status IN (...)
RETURNING id` whose False/None return means "someone else owns this; drop
cleanly." There is no third writer, and there is no unconditional
`set_status` call anywhere under `app/queue/`.

1. `claim_status(RECEIVED -> EXTRACTING)` is the sole FORWARD transition. A
   lost forward CAS is a DONE job, not a retry — this tier never decides what
   payroll status comes next; it only asks, and accepts no for an answer.
2. `rewind_for_reclaim(run_id)` is the sole, explicitly-named RECOVERY
   transition. It is not a forward transition: it moves BACKWARD
   (extracting/computed/sent -> received), it is itself a CAS (scoped to
   exactly those three statuses, so it can never clobber a run outside that
   scope), it fires only when `job.attempts > 1` (a genuine crash-reclaim,
   never a first attempt), and it never bumps `reply_epoch` — see its own
   docstring in `app/db/repo/pipeline_state.py` for why granting that licence
   automatically, on every lease-expiry reclaim, would be a very different
   and much riskier thing than granting it to a deliberate human retrigger.

So "the first durable action" is a CONDITIONAL, not a fixed step, and both
readings of J-1 are satisfiable together: on a first attempt the first
durable action is `claim_status`; on a reclaim (`attempts > 1`) the first
durable action is `rewind_for_reclaim` — itself a CAS — immediately followed
by `claim_status`. Every path obeys the one invariant that actually matters:
every business-status write from this tier is a CAS, and this tier drops
cleanly whenever it loses one. `tests/test_queue_drain.py`'s
`test_queue_tier_status_writers_are_cas_only` is the static guard that makes
this enforceable rather than aspirational — it fails the build by name on any
third writer, or on any call to `repo.set_status` from anywhere under
`app/queue/`, however that call is spelled.

**What re-running a reclaimed job actually guarantees, stated precisely.**
This handler being idempotent for pipeline STATE (the CAS above advances
at-most-once; line items are replaced wholesale, not appended) is not, by
itself, what keeps a re-run safe for the CLIENT. That guarantee comes from a
separate, fail-closed send guard that refuses to re-send when an unconfirmed
outbound row exists in the run's current epoch and escalates to a human
instead — and it can only see that row because the rewind above never bumps
the epoch. Do not describe an already-sent guard alone as sufficient: a
worker killed between the provider accepting a send and this app committing
its own "sent" record leaves no such row behind, and only the epoch-scoped
guard closes that window.

**Three things this handler deliberately does NOT do, because a future
change reaching for them here would defeat correctness this tier depends
on:**

- It never touches `app/pipeline/orchestrator.py`'s own status write at the
  start of a run. That line is the ONLY thing that ever moves a plainly
  ingested (non-retriggered) run out of RECEIVED today, because that path
  still runs on the framework's own background-task mechanism with no
  external CAS anywhere. Deleting it here would leave every ordinary run
  sitting at RECEIVED forever; on the retrigger path it is simply a
  redundant same-value write.
- It never builds a rich success/retryable/terminal result contract for what
  the pipeline call below returns. There is nothing real to classify with one
  yet, and inventing a taxonomy ahead of a real design for it is exactly the
  kind of premature structure this codebase avoids.
- It never raises on a lost CAS and never re-enqueues. A lost CAS means
  another actor already owns this run's next state; the correct response is
  to log and return, letting the caller mark the job done.

**A known, accepted gap this handler does not close (pinned by a named test,
not buried in a comment).** The function this handler calls
(`pipeline_glue.run_pipeline_bg`) already catches a catastrophic failure
before any real pipeline work begins (an import error, the database being
unreachable at the very first read) and returns normally rather than
raising — a safety net that predates this queue and exists so a background
task can never crash the process that scheduled it. Under this handler, that
same swallow means the job is marked done even though the run never
advanced. A STAGE failure is different and already fully visible: the
pipeline's own catch-all persists ERROR on the run before returning, so the
run shows up in that state for a human to see. Only the narrower,
catastrophic-START case is silently swallowed today. The honest claim this
handler can make is: no accepted retrigger is lost to a worker PROCESS
DEATH — the durable row survives and is reclaimed. It is not "every failure
is automatically retried." Turning the swallowed-start case into a real
retry is future work with its own design; until then,
`test_swallowed_start_failure_marks_the_job_done_KNOWN_GAP_FAIL01` pins the
current behavior as a named, visible gap rather than a silent one.
"""
from __future__ import annotations

import logging

from app.db import repo
from app.models.job import Job
from app.models.status import RunStatus
from app.routes import pipeline_glue

logger = logging.getLogger("payroll_agent.queue")


def handle_run_pipeline(job: Job) -> None:
    """Drive one `run_pipeline` job. See this module's docstring for the full
    INVARIANT J-1 contract this function implements; the logic below is
    exactly three steps, in this order, and nothing here writes
    `payroll_runs.status` outside of the two named CAS calls.
    """
    run_id = job.run_id
    if run_id is None:
        # The database rejects a run_pipeline row with no run_id before insert
        # (see the jobs table's own CHECK constraint), so this should be
        # unreachable — but Job.run_id is still typed as optional because the
        # dataclass is shared transport for every future job kind. Raising
        # here rather than silently no-op'ing keeps a future bug in the
        # insert path loud instead of dispatching a job that can never
        # advance anything.
        raise ValueError(f"handle_run_pipeline: job {job.id} has no run_id")

    if job.attempts > 1:
        # A reclaim: the previous holder of this job died somewhere mid-pipeline,
        # so the run may be sitting at extracting/computed/sent and the forward
        # CAS below could never win on its own. This is itself a CAS, scoped to
        # exactly those three statuses — a legitimate pause waiting on a human,
        # or a run that already reached a terminal state, is left untouched.
        rewound = repo.rewind_for_reclaim(run_id)
        logger.info(
            "queue reclaim: run_id=%s attempts=%s rewound=%s",
            run_id,
            job.attempts,
            rewound,
        )

    if not repo.claim_status(run_id, RunStatus.RECEIVED, RunStatus.EXTRACTING):
        # Another actor already owns this run's next state, or the run is
        # resting somewhere the rewind above correctly declined to touch. A
        # lost forward CAS is a completed job, not a retry: do not raise, do
        # not re-enqueue, do not write an error to the run.
        logger.info(
            "queue: run_id=%s lost the RECEIVED->EXTRACTING claim; dropping "
            "cleanly (job=%s, attempts=%s)",
            run_id,
            job.id,
            job.attempts,
        )
        return

    pipeline_glue.run_pipeline_bg(run_id)
