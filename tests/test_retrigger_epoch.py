"""The retrigger epoch mechanism: no email row outlives the run state that made it.

The problem this solves: `clear_reply_context` resets the `payroll_runs`
round-machine state on a retrigger, but `email_messages` is an append-only audit
log and must never be deleted or mutated. Without a way to scope the log to the
current attempt, two stale rows survive the reset and corrupt the fresh run:

  - a stale pre-retrigger round-0 `sent` outbound row makes the round-aware
    idempotency guard believe the question was already asked, so the fresh
    clarification is silently never sent and the run parks forever; and
  - a stale `consumed_round`-stamped reply is re-injected into the extraction
    context, so the retriggered run is computed against an answer to a question
    it never asked — a mispay.

The mechanism: a per-run `reply_epoch` counter, bumped once by
`clear_reply_context` on every retrigger. `email_messages.epoch` is stamped at
write/link time from the owning run's CURRENT reply_epoch. The active round-machine
readers (`get_outbound_for_round` and `load_consumed_replies`) scope to the run's CURRENT
epoch, so a stale pre-retrigger row (epoch 0) is invisible to a post-retrigger run
(epoch 1) while still physically existing in the audit log.

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker gated
on `os.environ.get("DATABASE_URL")` being unset. This module is genuinely hermetic
(fake_repo + mock_llm only, no live DB/LLM) and must run unconditionally offline,
so it carries NO module-level conditional-skip marker of any kind.

Money-path discipline: these tests do NOT mock `clear_reply_context`, `_clarify`,
`get_outbound_for_round`, `resume_pipeline`, or `mark_reply_consumed` — they drive
the real seam and assert PERSISTED STATE/BEHAVIOR (a new outbound row exists and
the gateway was actually called; load_consumed_replies returns empty while the row
still physically exists), never a log string. A test that mocks the seam it is
meant to prove cannot catch a mispay.
"""
from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models.contracts import Decision, Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult
from app.models.status import RunStatus
from app.pipeline.clarification import clarify as _clarify
from app.pipeline.orchestrator import resume_pipeline
from app.queue import drain
from app.queue.drain import DrainOutcome

COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"


def test_generic_retrigger_rolls_back_when_provider_handoff_is_active(
    fake_repo, monkeypatch
):
    """The active provider fence must undo the earlier status CAS, not merely
    suppress the later epoch bump.  A browser retry cannot manufacture a fresh
    pipeline job while an old provider request is still ambiguous.
    """
    import app.routes.runs as runs_mod

    run_id = fake_repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.ERROR)
    fake_repo.outbound_provider_handoffs[str(uuid.uuid4())] = {
        "id": uuid.uuid4(),
        "run_id": run_id,
        "released_at": None,
    }
    before_run = copy.deepcopy(fake_repo.runs)
    before_jobs = copy.deepcopy(fake_repo.jobs)

    class _RollbackTransaction:
        def __enter__(self):
            self.runs = copy.deepcopy(fake_repo.runs)
            self.jobs = copy.deepcopy(fake_repo.jobs)
            self.dedup = copy.deepcopy(fake_repo._job_dedup_keys)
            return self

        def __exit__(self, exc_type, _exc, _traceback):
            if exc_type is not None:
                fake_repo.runs = self.runs
                fake_repo.jobs = self.jobs
                fake_repo._job_dedup_keys = self.dedup
            return False

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def transaction(self):
            return _RollbackTransaction()

    monkeypatch.setattr(runs_mod.repo, "get_connection", lambda: _Connection())
    wake_calls: list[None] = []
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))

    response = runs_mod.retrigger(run_id)

    assert response.status_code == 303
    assert fake_repo.runs == before_run
    assert fake_repo.jobs == before_jobs
    assert wake_calls == []


def test_released_provider_handoff_allows_ordinary_retrigger(fake_repo, monkeypatch):
    """Once the exact handoff is settled, the ordinary epoch/job wake path stays
    available; the active-fence no-op is not a permanent denial of recovery.
    """
    import app.routes.runs as runs_mod

    run_id = fake_repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.ERROR)
    fake_repo.outbound_provider_handoffs[str(uuid.uuid4())] = {
        "id": uuid.uuid4(),
        "run_id": run_id,
        "released_at": datetime.now(UTC),
    }
    wake_calls: list[None] = []
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))

    response = runs_mod.retrigger(run_id)

    assert response.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == RunStatus.RECEIVED.value
    assert fake_repo.load_run(run_id)["reply_epoch"] == 1
    assert len(fake_repo.jobs) == 1
    assert wake_calls == [None]


def _bare_roster(business_id: uuid.UUID = COASTAL_BIZ_ID):
    from app.models.roster import Roster

    return Roster(business_id=business_id, employees=[])


def _bare_inbound() -> InboundEmail:
    return InboundEmail(
        id=uuid.uuid4(),
        message_id="<orig@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="David Reyez 38 hours",
        created_at=datetime.now(UTC),
    )


def _bare_decision() -> Decision:
    return Decision(
        final_action="request_clarification",
        gate_reasons=["David Reyez: unresolved"],
        unresolved_names=["David Reyez"],
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name="David Reyez",
                matched_employee_id=None,
                source="none",
                resolved=False,
                reason="no roster match",
            )
        ],
    )


def _bare_extracted(run_id: uuid.UUID) -> Extracted:
    return Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(submitted_name="__stub__", hours_regular=Decimal("0"))],
    )


# ===========================================================================
# A stale pre-retrigger round-0 'sent' row must not suppress the retriggered
# run's fresh round-0 clarification send.
# ===========================================================================


def test_retrigger_sends_fresh_clarification_despite_stale_round0_sent_row(
    monkeypatch, fake_repo, mock_llm
):
    """A run already sent its round-0 clarification (still 'sent' in
    email_messages, pre-retrigger). The operator retriggers: repo.clear_reply_context
    is called for REAL (bumping reply_epoch 0 -> 1). _clarify is then driven for
    REAL with current_round=0 (post-clear — the retriggered run's own fresh round 0).

    Without epoch scoping, get_outbound_for_round finds the STALE epoch-0 round-0
    'sent' row, concludes the question was already asked, and suppresses the send —
    so the retriggered run parks at awaiting_reply with no email ever leaving the
    system. Epoch-scoping the guard makes that stale row belong to a DIFFERENT
    epoch, so the send actually happens.
    """
    run_id = uuid.uuid4()
    email = _bare_inbound()
    decision = _bare_decision()
    extracted = _bare_extracted(run_id)
    roster = _bare_roster()

    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "status": "extracting",
        "business_id": COASTAL_BIZ_ID,
        "clarification_round": 0,
    }

    # Seed the STALE pre-retrigger round-0 'sent' row, written at epoch 0
    # (this is exactly what a real pre-retrigger _clarify send would have
    # produced — epoch 0 is the default for every row created before any
    # retrigger ever happened).
    fake_repo.outbound[str(run_id)] = [
        {
            "run_id": run_id,
            "purpose": "clarification",
            "round": 0,
            "epoch": 0,
            "send_state": "sent",
            "message_id": "<stale-round0@test.example>",
        }
    ]

    # The retrigger: clear_reply_context called FOR REAL — this is the actual
    # seam under test, not mocked. It resets clarification_round to 0 (already
    # 0 here — this run never sent a round-1+) AND bumps reply_epoch 0 -> 1.
    fake_repo.clear_reply_context(run_id)
    assert fake_repo.runs[str(run_id)].get("reply_epoch") == 1, (
        "clear_reply_context must bump reply_epoch on every call — that bump is "
        "the whole mechanism that makes pre-retrigger email rows invisible"
    )

    # Drive the REAL _clarify seam — current_round is read fresh from the
    # (just-cleared) run, so this call represents the retriggered run's own
    # first clarification attempt post-retrigger.
    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")

    matching_send_jobs = [
        job
        for job in fake_repo.jobs.values()
        if job["run_id"] == run_id and job["kind"] == "send_outbound"
    ]
    assert len(matching_send_jobs) == 1, (
        "the retriggered run's fresh round-0 clarification must queue one immutable "
        "send even though a stale pre-retrigger round-0 'sent' row still exists in "
        "email_messages — the epoch scope must make that stale row invisible to "
        "the idempotency guard"
    )
    assert drain.drain_once() is DrainOutcome.DONE

    # A SECOND 'sent' row now exists at round 0, distinguished by epoch — the
    # append-only audit log keeps BOTH the stale epoch-0 row and the fresh
    # epoch-1 row; nothing was deleted or mutated.
    rows = fake_repo.outbound[str(run_id)]
    round0_sent_rows = [
        r for r in rows if r.get("round") == 0 and r.get("send_state") == "sent"
    ]
    assert len(round0_sent_rows) == 2, (
        "both the stale pre-retrigger epoch-0 row AND the fresh post-retrigger "
        "epoch-1 row must coexist at round=0 — proves append-only (no delete, "
        "no mutation of the historical row)"
    )
    epochs_seen = {r.get("epoch", 0) for r in round0_sent_rows}
    assert epochs_seen == {0, 1}, (
        f"the two round-0 sent rows must be distinguished by epoch (0 and 1); "
        f"got epochs {epochs_seen}"
    )

    # The guard now sees the CURRENT epoch's row when queried directly.
    found = fake_repo.get_outbound_for_round(run_id, purpose="clarification", round=0)
    assert found is not None
    assert found["message_id"] != "<stale-round0@test.example>", (
        "get_outbound_for_round must resolve to the CURRENT epoch's row, not "
        "the stale pre-retrigger row"
    )

    assert fake_repo.runs[str(run_id)]["status"] == "awaiting_reply"
    assert fake_repo.runs[str(run_id)]["clarification_round"] == 1


# ===========================================================================
# A retrigger must not re-accumulate a reply that was consumed in a prior
# (pre-retrigger) epoch into the retriggered run's extraction context — even
# though the row itself is never deleted (the audit log is append-only).
# ===========================================================================


def test_retrigger_forgets_consumed_reply_from_prior_epoch(fake_repo, mock_llm):
    """Drive a REAL resume_pipeline call so a reply is genuinely consumed
    (mark_reply_consumed fires for real, not hand-seeded consumed_round).
    Then retrigger (clear_reply_context for real, bumping the epoch). Assert
    load_consumed_replies now returns EMPTY for the run — the epoch-0 consumed
    reply must not surface in epoch 1's accumulation, or the retriggered run is
    computed against an answer to a question it never asked (a mispay) — even
    though the row still physically exists in email_messages, proving the audit
    log stayed append-only and nothing was deleted.
    """
    import json

    from app.models.status import RunStatus as RS

    # Seed a run at awaiting_reply with a pre-clarify snapshot + reconciliation,
    # mirroring test_combined_context.py's established real-seam pattern.
    eid, _ = fake_repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen worked 40 regular hours",
    )
    run_id = fake_repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=eid)

    CHEN_ID = uuid.uuid4()
    snapshot = Extracted(
        run_id=run_id,
        employees=[
            ExtractedEmployee(submitted_name="Maria Chen", hours_regular=Decimal("40"))
        ],
        pay_period_start=None,
        pay_period_end=None,
    )
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    fake_repo.persist_reconciliation(
        run_id,
        [
            NameMatchResult(
                submitted_name="Maria Chen",
                matched_employee_id=CHEN_ID,
                source="exact",
                resolved=True,
                reason="exact match",
            )
        ],
    )
    fake_repo.runs[str(run_id)]["status"] = RS.AWAITING_REPLY.value

    # Persist + link a reply row BEFORE resume_pipeline (mirrors the real
    # webhook's insert_inbound_email + link_email_to_run sequence, and
    # test_combined_context.py's _inbound_persisted helper).
    reply_message_id = "<r1-epoch-test@test.example>"
    reply_eid, _ = fake_repo.insert_inbound_email(
        message_id=reply_message_id,
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria actually worked 30, not 40 -- no overtime this week.",
    )
    fake_repo.link_email_to_run(reply_eid, run_id)
    reply = InboundEmail(
        id=reply_eid,
        message_id=reply_message_id,
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria actually worked 30, not 40 -- no overtime this week.",
        created_at=datetime.now(UTC),
    )

    mock_llm.script = [
        json.dumps(
            {
                "employees": [{"submitted_name": "Maria Chen", "hours_regular": "30"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
        json.dumps({"suggestions": []}),
        "Could you confirm Maria Chen's overtime hours?",
    ]
    resume_pipeline(run_id, reply)

    # The REAL consumed marker was written by resume_pipeline's own
    # mark_reply_consumed call (Task 1 of Plan 11-02) -- not hand-seeded here.
    consumed_pre_retrigger = fake_repo.load_consumed_replies(run_id)
    assert len(consumed_pre_retrigger) == 1, (
        "resume_pipeline must have marked the reply consumed by now -- if "
        "this is 0, the seam this test depends on was removed"
    )
    assert consumed_pre_retrigger[0]["message_id"] == reply_message_id

    # The row genuinely exists, unconsumed-flag included, in the raw store —
    # captured now so we can prove append-only AFTER the retrigger below.
    raw_row_before = fake_repo.emails[reply_message_id]
    assert raw_row_before.get("consumed_round") is not None

    # Retrigger: clear_reply_context called FOR REAL (bumps reply_epoch).
    fake_repo.clear_reply_context(run_id)
    assert fake_repo.runs[str(run_id)].get("reply_epoch") == 1, (
        "clear_reply_context must bump reply_epoch on retrigger"
    )

    # The epoch-0 consumed reply must NOT surface in the post-retrigger
    # (epoch-1) accumulation.
    consumed_post_retrigger = fake_repo.load_consumed_replies(run_id)
    assert consumed_post_retrigger == [], (
        "a retrigger must forget a pre-retrigger epoch's consumed reply -- "
        "load_consumed_replies must return EMPTY immediately after the epoch "
        "bump, even though the row is never deleted"
    )

    # Append-only invariant: the row STILL physically exists in the raw
    # store, consumed_round untouched -- nothing was deleted or mutated by
    # the retrigger, only the epoch-scoped READ became blind to it.
    raw_row_after = fake_repo.emails[reply_message_id]
    assert raw_row_after is raw_row_before or raw_row_after == raw_row_before
    assert raw_row_after.get("consumed_round") is not None, (
        "the historical consumed_round stamp must survive the retrigger "
        "untouched -- clear_reply_context must NEVER mutate email_messages "
        "rows, only bump payroll_runs.reply_epoch"
    )
    assert raw_row_after.get("epoch", 0) == 0, (
        "the reply row's OWN epoch stamp (0, set at link time before the "
        "retrigger) must never be retroactively rewritten to the new epoch"
    )
