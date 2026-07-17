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
  start of a run. The queue handler owns the external RECEIVED -> EXTRACTING
  claim, while the orchestrator retains its internal write for its existing
  stage contract. On the durable path that internal write is a redundant
  same-value transition, not a third queue-tier writer.
- It never builds a rich, multi-outcome failure-classification contract for
  what the pipeline call below returns. There is nothing real to classify
  with one yet, and inventing a taxonomy ahead of a real design for it is
  exactly the kind of premature structure this codebase avoids.
- It never raises on a lost CAS and never re-enqueues. A lost CAS means
  another actor already owns this run's next state; the correct response is
  to log and return, letting the caller mark the job done.

**AN UNRECORDABLE FAILURE IS A RETRY; A RECORDED ONE IS A COMPLETION — and the
one-word choice that makes it so.** This handler calls
`pipeline_glue.run_pipeline_now`, which lets whatever escapes the orchestrator
PROPAGATE; `drain_once` then routes it into a fenced `fail_job` write with backoff
and retries up to `max_attempts` before dead-lettering.

Be precise about WHICH failures those are, because the honest contract is narrower
than "catastrophic failures retry". `run_pipeline` catches its own failures,
persists ERROR on the run, and returns NORMALLY — including a transient database
error on its first read. Those do NOT reach here and do NOT retry: the run carries
a visible ERROR, an operator can see it and retrigger, and the job has genuinely
finished its work. What escapes is only what the orchestrator's boundary could not
RECORD — the module failing to import, or `record_run_error` itself failing. The
rule: **a failure a human can see completes the job; a failure nobody can see must
retry, or the run is lost with no trace.**

The handler must call the explicit value seam directly. A procedure that swallowed
the value or an escaping infrastructure failure would return cleanly, causing
`drain_once` to mark the durable job done and strand the run without retry evidence.

A STAGE failure is different and needs no queue involvement: the pipeline's own
catch-all persists ERROR on the run before returning, so the run is already
visible to a human in that state and the job completes normally.
"""
from __future__ import annotations

import logging

from app.db import repo
from app.models.job import Job
from app.models.status import RunStatus
from app.pipeline.result import (
    PipelineOutcome,
    PipelineResult,
    normalize_pipeline_result,
)
from app.routes import pipeline_glue

logger = logging.getLogger("payroll_agent.queue")


def handle_run_pipeline(job: Job) -> PipelineResult:
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
        return PipelineResult(outcome=PipelineOutcome.OK)

    # Keep the PipelineResult and any escaping infrastructure failure explicit so
    # drain_once can route them through fenced settlement, backoff, and retry. Consuming
    # either signal here would let the durable job disappear as a false success.
    return normalize_pipeline_result(pipeline_glue.run_pipeline_now(run_id))
