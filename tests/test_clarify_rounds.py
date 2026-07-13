"""Round-aware `_clarify` proof — a new question always sends, a re-trigger never does.

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker gated on
`os.environ.get("DATABASE_URL")` being unset. That marker silently skips the ENTIRE
module — including any new test added to it — whenever DATABASE_URL is unset at
collection time. This module is genuinely hermetic (FakeConnection + monkeypatched repo.*
only, no live DB or LLM), so it lives here and runs unconditionally offline.

WHAT THIS MODULE PROVES:
The idempotency guard is keyed on (purpose, round), via
`repo.get_outbound_for_round(run_id, purpose, round=current_round)` — NOT on purpose
alone via `repo.get_outbound_message_id(run_id, purpose)`.

A purpose-only guard cannot distinguish "this round already sent" from "the PRIOR round
already sent", so it treats a genuinely NEW round-2+ question as a duplicate: the run
parks at AWAITING_REPLY with NO email out, waiting forever for a reply to a question the
client never received. The round-aware guard can tell them apart, and this module pins:

1. new-question-sends — a round-1 question actually sends when only a round-0 row exists.
   (If the guard ever reverts to purpose-only, this test fails: round 1 looks like a
   duplicate of round 0.)
2. same-round-suppressed — a round-N re-trigger with a round-N sent row IS correctly
   suppressed. A re-trigger is not a new question and must not re-send.
3. crash-idempotent advance — a send-then-crash state (sent row at round R, counter still
   R) re-enters cleanly: no second send, AND the counter is derived from the FOUND row,
   advancing to R+1 exactly once. A blind counter+1 would skip or repeat a round.
4. AST source-order guard — each of _clarify's three finalize paths contains
   set_clarification_round then set_status inside ONE `with conn.transaction():` block,
   with status advanced LAST, so a crash mid-sequence cannot leave the status ahead of
   the data it describes.
5. outbound row records its round — a sent clarification's outbound row carries
   round == the counter value at send time.

Money-path discipline: assertions target PERSISTED STATE and BEHAVIOR (gateway called or
not, round counter value, row round value) — never log strings.
"""
from __future__ import annotations

# AST and provider test doubles are intentionally lightweight in this module.
import ast
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.models.contracts import Decision, Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult, Roster
from app.pipeline.clarification import clarify as _clarify

# ---------------------------------------------------------------------------
# Shared seed identifiers (mirrors tests/test_atomic_persist.py / test_resume_pipeline.py)
# ---------------------------------------------------------------------------
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"


def _bare_roster(business_id: uuid.UUID = COASTAL_BIZ_ID) -> Roster:
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
# 1. new-question-sends — a new round must never look like a duplicate
# ===========================================================================


def test_new_round_question_actually_sends(monkeypatch, fake_repo, mock_llm):
    """At clarification_round=1 with an existing SENT round-0 row, the round-1 question
    must actually send (a NEW outbound row at round=1) and finalize the counter to 2.

    A purpose-only guard would find the round-0 row, treat round 1 as a duplicate, and
    suppress the send — parking the run at AWAITING_REPLY forever, waiting on a reply to
    a question the client never got.
    """
    import app.email.gateway as gateway_mod

    run_id = uuid.uuid4()
    email = _bare_inbound()
    decision = _bare_decision()
    extracted = _bare_extracted(run_id)
    roster = _bare_roster()

    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "status": "extracting",
        "business_id": COASTAL_BIZ_ID,
        "clarification_round": 1,
    }
    # Seed an existing SENT round-0 row (the prior round's clarification).
    fake_repo.outbound[str(run_id)] = [
        {
            "run_id": run_id,
            "purpose": "clarification",
            "round": 0,
            "send_state": "sent",
            "message_id": "<round0@test.example>",
        }
    ]

    send_calls: list[dict[str, Any]] = []
    real_send_outbound = gateway_mod.send_outbound

    def _spy_send_outbound(**kw):
        send_calls.append(kw)
        return real_send_outbound(**kw)

    monkeypatch.setattr(gateway_mod, "send_outbound", _spy_send_outbound)

    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")

    assert len(send_calls) == 1, (
        "a genuinely new round-1 question must actually call gateway.send_outbound — "
        "a purpose-only guard silently swallows this send and strands the run"
    )
    assert send_calls[0]["round"] == 1, "the send must be stamped with the CURRENT round (1)"

    rows = fake_repo.outbound[str(run_id)]
    round1_rows = [r for r in rows if r.get("round") == 1 and r.get("purpose") == "clarification"]
    assert round1_rows, "a NEW round-1 outbound row must exist (not an upsert-replace of round 0)"
    assert round1_rows[0]["send_state"] == "sent"

    assert fake_repo.runs[str(run_id)]["clarification_round"] == 2, (
        "finalize must advance the counter to round + 1 == 2 after the round-1 send"
    )
    assert fake_repo.runs[str(run_id)]["status"] == "awaiting_reply"


# ===========================================================================
# 2. same-round-suppressed — CLAR-04 true-duplicate preserved
# ===========================================================================


def test_same_round_retrigger_is_suppressed(monkeypatch, fake_repo):
    """A sent row already exists AT THE CURRENT round -> _clarify suppresses
    the send (gateway NOT called), takes the early-return finalize path, and
    the run settles at awaiting_reply (CLAR-04 true-duplicate preserved).
    """
    import app.email.gateway as gateway_mod

    run_id = uuid.uuid4()
    email = _bare_inbound()
    decision = _bare_decision()
    extracted = _bare_extracted(run_id)
    roster = _bare_roster()

    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "status": "extracting",
        "business_id": COASTAL_BIZ_ID,
        "clarification_round": 1,
    }
    # A sent row EXISTS at round=1 (the CURRENT round) — a true duplicate.
    fake_repo.outbound[str(run_id)] = [
        {
            "run_id": run_id,
            "purpose": "clarification",
            "round": 1,
            "send_state": "sent",
            "message_id": "<round1@test.example>",
        }
    ]

    def _fail_send_outbound(**kw):
        raise AssertionError("send_outbound must NOT be called for a same-round duplicate")

    monkeypatch.setattr(gateway_mod, "send_outbound", _fail_send_outbound)

    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")

    assert fake_repo.runs[str(run_id)]["status"] == "awaiting_reply"
    # Idempotent advance: derived from the FOUND row's round (1) + 1 = 2.
    assert fake_repo.runs[str(run_id)]["clarification_round"] == 2


# ===========================================================================
# 3. crash-idempotent advance — the counter is derived, never blindly incremented
# ===========================================================================


def test_crash_then_reentry_advances_round_exactly_once(monkeypatch, fake_repo):
    """Simulates the post-crash state: a sent row exists at round R (the send
    succeeded) but the counter is STILL R (the finalize transaction never
    committed — the crash happened between send and finalize). Re-entering
    _clarify must NOT send a second email, AND must advance the counter to
    R+1 exactly once, derived from the sent row (never a blind current+1 on
    a possibly-stale in-process value).
    """
    import app.email.gateway as gateway_mod

    run_id = uuid.uuid4()
    email = _bare_inbound()
    decision = _bare_decision()
    extracted = _bare_extracted(run_id)
    roster = _bare_roster()

    R = 2
    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "status": "extracting",
        "business_id": COASTAL_BIZ_ID,
        # Post-crash state: counter STILL at R even though the round-R send
        # already succeeded (the finalize transaction that would have
        # advanced it never committed).
        "clarification_round": R,
    }
    fake_repo.outbound[str(run_id)] = [
        {
            "run_id": run_id,
            "purpose": "clarification",
            "round": R,
            "send_state": "sent",
            "message_id": "<roundR@test.example>",
        }
    ]

    def _fail_send_outbound(**kw):
        raise AssertionError(
            "send_outbound must NOT be called on re-entry — the round-R send already "
            "succeeded, so re-sending would ask the client the same question twice"
        )

    monkeypatch.setattr(gateway_mod, "send_outbound", _fail_send_outbound)

    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")

    assert fake_repo.runs[str(run_id)]["clarification_round"] == R + 1, (
        "re-entry must derive the next round from the SENT ROW's own round "
        "(R + 1), self-healing the stale counter exactly once"
    )
    assert fake_repo.runs[str(run_id)]["status"] == "awaiting_reply"


# ===========================================================================
# 4. AST source-order guard — status advances LAST, on all three finalize paths
# ===========================================================================


def test_clarify_finalize_paths_advance_round_before_status_ast():
    """Parse clarify's live source: each of the three finalize blocks (idempotency
    early-return, record_only, live gateway) must call set_clarification_round textually
    BEFORE set_status, both inside the SAME `with conn.transaction():` block.

    Status must advance last. If the status flipped to AWAITING_REPLY before the round
    counter was written, a crash in between would leave a run parked on a round the DB
    says never happened.
    """
    import app.pipeline.clarification as clarification_mod

    src_path = clarification_mod.__file__
    with open(src_path) as f:
        src = f.read()
    tree = ast.parse(src)

    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "clarify"
    )

    def _call_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                return f.id
            if isinstance(f, ast.Attribute):
                return f.attr
        return None

    # Find every `with conn.transaction():` block inside clarify. There are FOUR total:
    # the cap-escalation block (set_status(NEEDS_OPERATOR) only, no round advance — the
    # escalation is a terminal handoff, not another round) plus the THREE finalize blocks
    # this test targets (early-return, record_only, live gateway), each of which advances
    # the round before advancing status.
    all_tx_blocks = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "transaction"
            for item in node.items
        )
    ]
    assert len(all_tx_blocks) == 4, (
        f"_clarify must contain exactly 4 'with conn.transaction():' blocks "
        f"(cap-escalation + early-return + record_only + live gateway); "
        f"found {len(all_tx_blocks)}"
    )

    def _calls_in_block(node: ast.AST) -> list[str | None]:
        return [
            _call_name(stmt)
            for stmt in ast.walk(node)
            if _call_name(stmt) in ("set_clarification_round", "set_status")
        ]

    # The finalize blocks are the ones that call set_clarification_round; the
    # cap-escalation block deliberately does NOT, so it is excluded here — it has its
    # own dedicated test below.
    tx_blocks = [
        node for node in all_tx_blocks if "set_clarification_round" in _calls_in_block(node)
    ]
    assert len(tx_blocks) == 3, (
        f"exactly 3 of the 4 transaction blocks must advance the round counter "
        f"(early-return, record_only, live gateway); found {len(tx_blocks)}"
    )

    for tx_node in tx_blocks:
        calls_in_order = []
        for stmt in ast.walk(tx_node):
            name = _call_name(stmt)
            if name in ("set_clarification_round", "set_status"):
                calls_in_order.append(name)
        assert "set_clarification_round" in calls_in_order, (
            f"transaction block at line {tx_node.lineno} must call "
            "set_clarification_round — the round advance is what makes re-entry idempotent"
        )
        assert "set_status" in calls_in_order, (
            f"transaction block at line {tx_node.lineno} must call set_status"
        )
        assert calls_in_order.index("set_clarification_round") < calls_in_order.index(
            "set_status"
        ), (
            f"transaction block at line {tx_node.lineno}: set_clarification_round must "
            f"come BEFORE set_status (status advances last); got order {calls_in_order!r}"
        )


def test_clarify_cap_check_precedes_any_transaction_block():
    """The cap-escalation transaction (set_status(NEEDS_OPERATOR)) must be the FIRST
    `with conn.transaction():` block in clarify's source.

    That is: the cap check runs before the (purpose, round) guard's own transaction, and
    long before any LLM or gateway call — the cap `return`s before reaching them, so a
    capped run can never spend a model call or send an email on its way out.
    """
    import app.pipeline.clarification as clarification_mod

    src_path = clarification_mod.__file__
    with open(src_path) as f:
        src = f.read()
    tree = ast.parse(src)

    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "clarify"
    )

    tx_blocks = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "transaction"
            for item in node.items
        )
    ]
    first_tx = min(tx_blocks, key=lambda n: n.lineno)

    def _call_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                return f.attr
        return None

    calls_in_first = [
        _call_name(stmt) for stmt in ast.walk(first_tx) if _call_name(stmt) is not None
    ]
    assert "set_status" in calls_in_first, (
        "the first transaction block in clarify's source must be the cap-escalation "
        "block (its only write is set_status(NEEDS_OPERATOR))"
    )
    assert "set_clarification_round" not in calls_in_first, (
        "the cap-escalation block must NOT advance the round counter — escalation is "
        "silent and terminal, not another round"
    )


# ===========================================================================
# 5. outbound row records its round
# ===========================================================================


def test_sent_outbound_row_records_round_at_send_time(fake_repo, mock_llm):
    """After a send, the fake outbound row for the clarification carries
    round == the counter value AT SEND TIME (not 0, not the post-finalize
    value)."""
    run_id = uuid.uuid4()
    email = _bare_inbound()
    decision = _bare_decision()
    extracted = _bare_extracted(run_id)
    roster = _bare_roster()

    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "status": "extracting",
        "business_id": COASTAL_BIZ_ID,
        "clarification_round": 2,
    }
    fake_repo.outbound[str(run_id)] = []

    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")

    rows = fake_repo.outbound[str(run_id)]
    assert rows, "a clarification send must write an outbound row"
    sent_row = rows[-1]
    assert sent_row["round"] == 2, (
        "the outbound row must be stamped with round == counter value at send "
        f"time (2); got {sent_row.get('round')!r}"
    )
    assert fake_repo.runs[str(run_id)]["clarification_round"] == 3
