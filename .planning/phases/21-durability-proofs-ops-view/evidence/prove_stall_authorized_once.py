"""Reach the pre-authorization stall through ordinary queue mechanics.

The earlier probe hand-set attempts = max_attempts, which invites the objection
that the state is unreachable in production. This version never writes attempts.
It only expires leases -- exactly what a crashed worker leaves behind -- and lets
claim_job burn the attempts itself, simulating a worker that dies in the window
between claim_job and authorize_outbound_provider_handoff on every retry.

If the terminal reap still yields invalid_context with zero open jobs and the run
still sitting at 'approved', the stall is reachable without any SQL surgery
beyond fast-forwarding the lease clock.
"""

import uuid

from app.db import repo
from app.db.bootstrap import bootstrap
from app.db.seed import seed
from app.models.job import JobKind
from app.models.status import RunStatus

bootstrap(reset=True)
seed()

with repo.get_connection() as conn, conn.transaction():
    biz = conn.execute("SELECT id FROM businesses LIMIT 1").fetchone()[0]
    run_id = uuid.UUID(
        str(
            conn.execute(
                "INSERT INTO payroll_runs (business_id, status) "
                "VALUES (%s,'received') RETURNING id",
                (biz,),
            ).fetchone()[0]
        )
    )
repo.set_status(run_id, RunStatus.APPROVED)
snapshot = repo.reserve_outbound_snapshot(
    run_id=run_id,
    purpose="confirmation",
    round=0,
    message_id=f"<natural-stall-{uuid.uuid4()}@test.example>",
    from_addr="agent@payroll-agent.local",
    to_addr="payroll@coastalcleaning.example",
    reply_to=None,
    in_reply_to=None,
    references_header=None,
    subject="Approved payroll confirmation",
    body_text="Approved payroll confirmation",
    attachments=(),
)
job_id = repo.enqueue_job(
    kind=JobKind.SEND_OUTBOUND,
    dedup_key=repo.send_outbound_dedup_key(snapshot["email_id"]),
    run_id=run_id,
    email_id=snapshot["email_id"],
)


def expire_lease(jid):
    """What a dead worker leaves behind: a lease nobody will ever renew."""
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET leased_until = now() - interval '60 seconds' "
            "WHERE id = %s",
            (str(jid),),
        )


cycles = 0
while cycles < 25:
    claimed = repo.claim_job()
    if claimed is None or claimed.id != job_id:
        break
    cycles += 1
    job = repo.get_job(job_id)
    if cycles == 1:
        repo.authorize_outbound_provider_handoff(claimed)
    print(
        f"  cycle {cycles}: attempts={job['attempts']}/{job['max_attempts']}"
        f" state={job['state']}"
    )
    if job["attempts"] >= job["max_attempts"]:
        expire_lease(job_id)
        break
    expire_lease(job_id)

outcome = repo.reap_expired_final_attempt()
run = repo.load_run(run_id)
job = repo.get_job(job_id)
with repo.get_connection() as conn:
    open_jobs = conn.execute(
        "SELECT count(*) FROM jobs WHERE run_id = %s AND state IN ('pending','leased')",
        (str(run_id),),
    ).fetchone()[0]
    attempts_logged = conn.execute(
        "SELECT count(*) FROM outbound_delivery_attempts WHERE snapshot_id = %s",
        (str(snapshot["snapshot_id"]),),
    ).fetchone()[0]
    send_state = conn.execute(
        "SELECT send_state FROM email_messages WHERE id = %s",
        (str(snapshot["email_id"]),),
    ).fetchone()[0]
    handoffs = conn.execute(
        "SELECT count(*) FROM outbound_provider_handoffs WHERE run_id = %s",
        (str(run_id),),
    ).fetchone()[0]

print(f"\ncrash cycles run     : {cycles}  (attempts burned by claim_job, never written by hand)")
print(f"provider handoffs    : {handoffs}")
print(f"reap outcome         : {outcome}")
print(f"run.status           : {run['status']}")
print(f"run.error_reason     : {run['error_reason']}")
print(f"job.state            : {job['state']}")
print(f"job.last_error       : {job['last_error']}")
print(f"open jobs for run    : {open_jobs}")
print(f"delivery attempts    : {attempts_logged}")
print(f"email send_state     : {send_state}")
print(
    "\nSTALLED: approved payroll, no open job, no operator signal."
    if run["status"] == "approved" and open_jobs == 0 and run["error_reason"] is None
    else "\nNot stalled -- run reached an operator or retained work."
)
