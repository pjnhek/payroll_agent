"""The D-11-17 full-loop stops-asking test (CLAR2-04, Phase 11 Plan 04).

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker
gated on `os.environ.get("DATABASE_URL")` being unset (the established
09-REVIEWS.md / test_multiround_context_edge.py convention this module
restates). This module is genuinely hermetic (fake_repo + mock_llm only, no
live DB/LLM) and must run unconditionally offline — no module-level skip
marker of any kind.

WHAT THIS MODULE PROVES (D-11-17's core finding: faked-state tests kept an
unreachable bind loop green; only REAL resolution proves the loop closes):

  The full end-to-end alias-learning loop, driving REAL reconcile_names and
  REAL _write_aliases_if_safe throughout (mock_llm is used ONLY for the
  extraction/suggestion/draft TEXT — never for name resolution, never for a
  faked post-reconciliation state):

    1. FIRST submission: the client emails a nickname ("Jimmy") for an
       employee (James Okafor) who has NO stored alias for it yet. Real
       reconcile_names resolves this as source="none"/unresolved (no guess).
       The deterministic decide() gate requests clarification. _clarify
       captures the token, calls the (mocked-response) suggest_employees,
       and persists the D-11-14 nested suggestion
       {"Jimmy": {"suggested": <james.id>, "bound": None}}.
    2. A CONFIRMING client reply restates the suggested canonical name
       ("James Okafor") — resume_pipeline re-runs REAL reconcile_names; James
       newly resolves and "Jimmy" is gone from unresolved. The D-11-15
       bind-on-confirmation check (real, not seeded) binds
       {"Jimmy": {"suggested": <james.id>, "bound": <james.id>}}.
    3. The operator approves at the single human gate — _deliver calls the
       REAL _write_aliases_if_safe (not mocked), which runs the D-01b
       collision re-check and writes known_aliases via update_known_alias.
    4. THE STOPS-ASKING ASSERTION: a SECOND, INDEPENDENT submission using the
       SAME nickname ("Jimmy") drives REAL reconcile_names against the
       now-updated roster (load_roster_for_business re-reads
       employees.known_aliases) and resolves via the stored alias
       (source="alias", resolved=True) — the run does NOT enter
       clarification at all (decide() gates to "process" directly) and a
       real paystub is computed for James Okafor.

  The misname guard (D-11-15) is also pinned here at the full-loop level: a
  reply that corrects the SAME token to a DIFFERENT, non-suggested employee
  must bind nothing (see test_misname_reply_binds_nothing_end_to_end below).
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models.contracts import InboundEmail
from app.models.status import RunStatus
from app.pipeline.orchestrator import resume_pipeline, run_pipeline

# ---------------------------------------------------------------------------
# Stable identifiers (Business 1 / Coastal Cleaning Co. seed data). James
# Okafor (e0000002) carries ZERO known_aliases at seed time — a genuinely
# clean slate for the "Jimmy" nickname-learning scenario.
# ---------------------------------------------------------------------------
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"
JAMES_ID = uuid.UUID("e0000002-0000-0000-0000-000000000002")
JAMES_ID_STR = str(JAMES_ID)


def _extraction_json(employees: list[dict], pay_period_start: str = "2026-06-15") -> str:
    return json.dumps(
        {"employees": employees, "pay_period_start": pay_period_start, "pay_period_end": None}
    )


def _suggestion_json(suggestions: dict[str, str]) -> str:
    return json.dumps(
        {
            "suggestions": [
                {"submitted_name": k, "suggested_full_name": v}
                for k, v in suggestions.items()
            ]
        }
    )


def _seed_inbound_run(fake_repo, *, body: str, from_addr: str = COASTAL_EMAIL) -> uuid.UUID:
    """Seed a fresh inbound email + run (mirrors the real webhook's create_run
    call) — this is a genuinely FIRST submission, driven through run_pipeline,
    not a hand-built awaiting_reply row."""
    eid, _ = fake_repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
    )
    return fake_repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=eid)


def _inbound_persisted(
    fake_repo, run_id: uuid.UUID, body: str, message_id: str, from_addr: str = COASTAL_EMAIL
) -> InboundEmail:
    """Build a reply InboundEmail AND persist its row in fake_repo, linked to
    run_id — mirrors what the real webhook does (insert_inbound_email +
    link_email_to_run) BEFORE resume_pipeline is called. Required for
    mark_reply_consumed/load_consumed_replies to have a real row to act on."""
    eid, _ = fake_repo.insert_inbound_email(
        message_id=message_id,
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
    )
    fake_repo.link_email_to_run(eid, run_id)
    return InboundEmail(
        id=eid,
        message_id=message_id,
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(UTC),
    )


def test_full_loop_learns_alias_and_stops_asking(fake_repo, mock_llm):
    """The D-11-17 stops-asking proof, end-to-end, REAL resolution throughout.

    Money-path assertion (Phase 7.5 lesson): the SECOND submission's paystub
    line-item VALUE is asserted, not merely a status label.
    """
    # ---- STEP 1: FIRST submission — a nickname with NO stored alias yet -----
    run_id = _seed_inbound_run(fake_repo, body="Jimmy worked 40 regular hours this week.")

    # run_pipeline's real four-stage gate path:
    #   extract() -> reconcile_names() [REAL, unresolved] -> validate -> decide()
    #   -> request_clarification -> _clarify() -> suggest_employees() [mocked
    #      TEXT response only] -> compose_clarification() [mocked TEXT] -> send.
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Jimmy", "hours_regular": "40"}]),
        _suggestion_json({"Jimmy": "James Okafor"}),
        "Did you mean James Okafor? Please confirm.",
    ]
    run_pipeline(run_id)

    run_after_first = fake_repo.load_run(run_id)
    assert run_after_first["status"] == RunStatus.AWAITING_REPLY.value, (
        "the first submission must clarify — 'Jimmy' has no stored alias and "
        "does not resolve via real reconcile_names"
    )

    # The D-11-14 nested suggestion must be persisted with a REAL employee id
    # (mapped from the suggested full_name via the already-loaded roster —
    # Pitfall #5), NOT the raw suggested name string.
    candidates_after_first = run_after_first.get("alias_candidates") or {}
    assert "Jimmy" in candidates_after_first, (
        "the single genuinely-unresolved token 'Jimmy' must be captured"
    )
    persisted_candidate = candidates_after_first["Jimmy"]
    assert isinstance(persisted_candidate, dict), (
        "the D-11-14 nested shape must be used, not a flat value"
    )
    assert persisted_candidate == {"suggested": JAMES_ID_STR, "bound": None}, (
        f"expected {{'suggested': {JAMES_ID_STR!r}, 'bound': None}}, got "
        f"{persisted_candidate!r} — suggest_employees returns a NAME "
        "('James Okafor'), which must be mapped to james's employee id at "
        "persist time (D-11-14, Pitfall #5), and must NOT be bound yet."
    )

    # ---- STEP 2: a CONFIRMING reply restates the suggested canonical name ---
    # Real reconcile_names must resolve "James Okafor" -> james.id. No
    # monkeypatched post-reconciliation state anywhere in this test.
    mock_llm.script = [
        _extraction_json([{"submitted_name": "James Okafor", "hours_regular": "40"}]),
    ]
    reply = _inbound_persisted(
        fake_repo, run_id, "Yes, I meant James Okafor.", message_id="<confirm@test.example>"
    )
    resume_pipeline(run_id, reply)

    run_after_confirm = fake_repo.load_run(run_id)
    assert run_after_confirm["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"the confirming reply resolves James for real — the run must reach "
        f"awaiting_approval; got {run_after_confirm['status']!r}"
    )
    candidates_after_confirm = run_after_confirm.get("alias_candidates") or {}
    bound_candidate = candidates_after_confirm.get("Jimmy")
    assert bound_candidate == {"suggested": JAMES_ID_STR, "bound": JAMES_ID_STR}, (
        f"D-11-15 bind-on-confirmation must fire from REAL post-resume "
        f"reconciliation (James newly resolved, 'Jimmy' gone from "
        f"unresolved) — got {bound_candidate!r}"
    )

    # ---- STEP 3: operator approves at the SINGLE human gate ------------------
    # _deliver calls the REAL _write_aliases_if_safe (never mocked in this
    # test) — the D-01b collision re-check runs, then update_known_alias
    # persists known_aliases via the real repo call (mirrored by fake_repo).
    from app.pipeline.orchestrator import _deliver

    claimed = fake_repo.claim_status(
        run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED
    )
    assert claimed, "the approval CAS claim must succeed for a fresh awaiting_approval run"
    run_for_deliver = fake_repo.load_run(run_id)
    _deliver(run_id, run_for_deliver)

    run_after_approve = fake_repo.load_run(run_id)
    assert run_after_approve["status"] == RunStatus.RECONCILED.value, (
        f"approval + delivery must reach RECONCILED; got "
        f"{run_after_approve['status']!r}"
    )

    # Assert the REAL write side actually ran: James's known_aliases now
    # contains "Jimmy" (read straight off the seeded roster fixture's live
    # in-memory employee objects, which _write_aliases_if_safe mutates via
    # repo.update_known_alias against the SAME seeded employee objects the
    # fake_repo's business_employees map holds).
    james_employee = next(
        e for e in fake_repo.business_employees[str(COASTAL_BIZ_ID)] if e.id == JAMES_ID
    )
    assert "Jimmy" in james_employee.known_aliases, (
        f"known_aliases for James Okafor must now include 'Jimmy' — the REAL "
        f"_write_aliases_if_safe (D-01b collision re-check + update_known_alias) "
        f"must have run at the approval gate; got {james_employee.known_aliases!r}"
    )

    # ---- STEP 4: THE STOPS-ASKING ASSERTION ----------------------------------
    # A SECOND, INDEPENDENT submission with the SAME nickname. Real
    # reconcile_names against the NOW-UPDATED roster resolves via the stored
    # alias — zero clarification, straight to a computed paystub.
    outbound_before_second = len(fake_repo.outbound.get(str(run_id), []))

    second_run_id = _seed_inbound_run(
        fake_repo, body="Jimmy worked 35 regular hours this week."
    )
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Jimmy", "hours_regular": "35"}]),
    ]
    run_pipeline(second_run_id)

    second_run = fake_repo.load_run(second_run_id)
    assert second_run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"the SECOND 'Jimmy' submission must resolve via the stored alias and "
        f"go straight to awaiting_approval — NO clarification round; got "
        f"{second_run['status']!r}"
    )

    # No clarification outbound row was ever created for the second run.
    second_run_outbound = fake_repo.outbound.get(str(second_run_id), [])
    clarification_rows = [
        r
        for r in second_run_outbound
        if r.get("purpose") in ("clarification", "clarification_field_regression")
    ]
    assert not clarification_rows, (
        "the second submission must send ZERO clarification emails — the "
        "system has stopped asking about 'Jimmy'"
    )
    # The FIRST run's outbound count is unaffected by the second run (sanity —
    # confirms the two runs are genuinely independent).
    assert len(fake_repo.outbound.get(str(run_id), [])) == outbound_before_second

    # Reconciliation on the second run resolved via the stored alias, not a guess.
    second_reconciliation = second_run.get("reconciliation") or []
    jimmy_match = next(
        m for m in second_reconciliation if m.get("submitted_name") == "Jimmy"
    )
    assert jimmy_match["resolved"] is True
    assert jimmy_match["source"] == "alias", (
        f"the second submission's 'Jimmy' must resolve with source='alias' "
        f"(the READ side of the learning loop, D-21-07); got {jimmy_match!r}"
    )
    assert jimmy_match["matched_employee_id"] == JAMES_ID_STR

    # Money-path assertion (Phase 7.5 lesson): assert the PAID VALUE, not just
    # a status label. A real paystub line item exists for James at 35 hours —
    # proving the run actually PROCESSED (not just resolved-but-stuck).
    second_line_items = fake_repo.load_line_items(second_run_id)
    assert second_line_items, "a paystub must be computed for the second run"
    james_items = [i for i in second_line_items if str(i.employee_id) == JAMES_ID_STR]
    assert james_items, f"a paystub line item for James Okafor ({JAMES_ID_STR}) must exist"
    assert james_items[0].hours_regular == Decimal("35"), (
        f"the second run's paystub must pay James Okafor for the hours "
        f"submitted under his learned nickname; got {james_items[0].hours_regular!r}"
    )


def test_misname_reply_binds_nothing_end_to_end(fake_repo, mock_llm):
    """D-11-15 misname guard, pinned at the FULL-LOOP level with REAL resolution.

    A nickname is captured and a suggestion persisted (real capture path), but
    the confirming reply actually corrects to a DIFFERENT, non-suggested
    employee (Maria Chen, not James Okafor). The suggested id (James) never
    newly-resolves, so nothing binds — "Robbie" must NOT become an alias for
    Maria. This exercises the exact real-resolution chain the stops-asking
    test does, but proves the negative case: the loop must NOT learn from
    mere correction, only from CONFIRMED suggestion evidence.
    """
    run_id = _seed_inbound_run(fake_repo, body="Robbie worked 20 regular hours this week.")

    mock_llm.script = [
        _extraction_json([{"submitted_name": "Robbie", "hours_regular": "20"}]),
        _suggestion_json({"Robbie": "James Okafor"}),
        "Did you mean James Okafor? Please confirm.",
    ]
    run_pipeline(run_id)

    run_after_first = fake_repo.load_run(run_id)
    assert run_after_first["status"] == RunStatus.AWAITING_REPLY.value
    candidates = run_after_first.get("alias_candidates") or {}
    assert candidates.get("Robbie") == {"suggested": JAMES_ID_STR, "bound": None}

    # The reply corrects to a DIFFERENT person entirely — Maria Chen, who was
    # never suggested for "Robbie". Real reconcile_names resolves Maria (her
    # full_name is an exact match on the seeded roster); James never
    # newly-resolves.
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "20"}]),
    ]
    reply = _inbound_persisted(
        fake_repo,
        run_id,
        "Sorry, I meant Maria Chen, not Robbie.",
        message_id="<misname@test.example>",
    )
    resume_pipeline(run_id, reply)

    run_after_reply = fake_repo.load_run(run_id)
    assert run_after_reply["status"] == RunStatus.AWAITING_APPROVAL.value, (
        "Maria Chen resolves via her real exact-match roster entry, so the run "
        "must proceed to awaiting_approval even though the alias bind is skipped"
    )
    candidates_after = run_after_reply.get("alias_candidates") or {}
    robbie_candidate = candidates_after.get("Robbie")
    assert robbie_candidate == {"suggested": JAMES_ID_STR, "bound": None}, (
        f"'Robbie' must remain UNBOUND — James (the suggested id) never newly "
        f"resolved (Maria did, a different, non-suggested employee); got "
        f"{robbie_candidate!r}. Binding here would silently misroute every "
        "future 'Robbie' to James."
    )

    # Approve — the write side must skip this candidate (bound is None).
    from app.pipeline.orchestrator import _deliver

    claimed = fake_repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
    assert claimed
    run_for_deliver = fake_repo.load_run(run_id)
    _deliver(run_id, run_for_deliver)

    james_employee = next(
        e for e in fake_repo.business_employees[str(COASTAL_BIZ_ID)] if e.id == JAMES_ID
    )
    assert "Robbie" not in james_employee.known_aliases, (
        "the misname 'Robbie' must NEVER be learned as an alias for James — "
        "the write side must have skipped the unbound candidate"
    )
