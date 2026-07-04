"""SC1 fault-injection tests proving DATA-01 atomicity (Phase 9, D-9-04..D-9-08).

Two groups:

1. Offline (no marker) — FakeConnection call-order/shape assertions. These pin
   the STRUCTURE of the new transaction wiring (persist-then-branch order,
   status-advance-last, the AST/indentation sibling-not-nested checks) without
   needing a live DB.

2. `@pytest.mark.integration` (skip-guarded on DATABASE_URL + ALLOW_DB_RESET=1,
   mirroring tests/test_claim_status.py / tests/test_persistence.py's two-factor
   convention) — real/local Postgres fault injection proving a crash mid-sequence
   genuinely rolls back every write in the same `conn.transaction()` block, not
   just the ones that hadn't run yet.

The live tests monkeypatch `app.llm.client.OpenAI` directly (NOT the shared
`mock_llm` fixture, which stubs DATABASE_URL — these tests need the REAL
DATABASE_URL) and `resend.Emails.send` directly (NOT `mock_resend_send`, kept
local for the same reason: avoid any fixture that assumes a mocked DB).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import resend

from app.models.contracts import Decision, Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult
from app.models.status import RunStatus

from tests.conftest import FakeConnection

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)

# ---------------------------------------------------------------------------
# Shared seed identifiers (mirrors tests/test_resume_pipeline.py)
# ---------------------------------------------------------------------------
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"
CHEN_ID = uuid.UUID("e0000001-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# Live-DB LLM/gateway mocking helpers — DELIBERATELY NOT the shared mock_llm
# fixture (it stubs DATABASE_URL) or mock_resend_send fixture (kept local so
# these tests never accidentally depend on a mocked-DB assumption elsewhere).
# ---------------------------------------------------------------------------


class _LiveMockMessage:
    def __init__(self, content):
        self.content = content


class _LiveMockChoice:
    def __init__(self, content):
        self.message = _LiveMockMessage(content)


class _LiveMockResponse:
    def __init__(self, content):
        self.choices = [_LiveMockChoice(content)]


class _LiveMockCompletions:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kwargs):
        self._parent.calls.append(kwargs)
        content = self._parent.script.pop(0) if self._parent.script else "{}"
        return _LiveMockResponse(content)


class _LiveMockChat:
    def __init__(self, parent):
        self.completions = _LiveMockCompletions(parent)


class LiveMockOpenAI:
    """Same shape as tests/conftest.py's MockOpenAI, kept local and DB-URL-free."""

    script: list = []
    calls: list = []

    def __init__(self, *, base_url=None, api_key=None, **_):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = _LiveMockChat(LiveMockOpenAI)


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


def _seed_live_run(*, body: str, from_addr: str = COASTAL_EMAIL) -> uuid.UUID:
    """Insert an inbound email + run against the REAL DB (repo.*, no conn=)."""
    from app.db import repo

    eid, _ = repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
    )
    return repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=eid)


def _live_inbound(body: str, from_addr: str = COASTAL_EMAIL) -> InboundEmail:
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<reply-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(timezone.utc),
    )


def _live_snapshot_extracted(
    submitted_name: str, run_id: uuid.UUID, hours_regular="40", hours_overtime="2"
) -> Extracted:
    emp = {"submitted_name": submitted_name, "hours_regular": hours_regular}
    if hours_overtime is not None:
        emp["hours_overtime"] = hours_overtime
    return Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(**emp)],
        pay_period_start=date.fromisoformat("2026-06-15"),
    )


# ===========================================================================
# Task 1 — _run_stages process branch (D-9-04)
# ===========================================================================


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_process_branch_crash_leaves_run_unadvanced(seeded_db, monkeypatch):
    """SC1: a crash injected mid-persist-sequence leaves the run wholly un-advanced.

    Forces repo.replace_line_items to raise on its FIRST call inside the real
    _run_stages process-branch invocation. Asserts the run's status is unchanged
    from its pre-call value and extracted_data/decision/reconciliation are all
    still None — the persists that "already succeeded" before the injected
    exception (persist_extracted/persist_decision/persist_reconciliation) are
    rolled back too, not just replace_line_items/set_status which never ran.
    """
    from app.db import repo
    from app.pipeline import orchestrator as orch_mod

    get_settings_cache_clear = __import__("app.config", fromlist=["get_settings"]).get_settings
    get_settings_cache_clear.cache_clear()

    run_id = _seed_live_run(body="Maria Chen 40 regular")

    pre_run = repo.load_run(run_id)
    pre_status = pre_run["status"]
    assert pre_run["extracted_data"] is None
    assert pre_run["decision"] is None
    assert pre_run["reconciliation"] is None

    monkeypatch.setattr("app.llm.client.OpenAI", LiveMockOpenAI)
    LiveMockOpenAI.script = [
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}]),
    ]
    LiveMockOpenAI.calls = []

    def _boom(*a, **kw):
        raise RuntimeError("injected crash — replace_line_items")

    monkeypatch.setattr(repo, "replace_line_items", _boom)

    from app.db.seed import seed as _seed

    result = _seed(dry_run=True)
    roster_employees = [e for e in result.employees if e.business_id == COASTAL_BIZ_ID]
    from app.models.roster import Roster

    roster = Roster(business_id=COASTAL_BIZ_ID, employees=roster_employees)
    email = _live_inbound("Maria Chen 40 regular", from_addr=COASTAL_EMAIL)

    with pytest.raises(RuntimeError, match="injected crash"):
        orch_mod._run_stages(run_id, email, roster, llm=None)

    post_run = repo.load_run(run_id)
    assert post_run["status"] == pre_status, (
        "SC1: run status must be UNCHANGED after a crash mid-persist-sequence — "
        f"expected {pre_status!r}, got {post_run['status']!r}"
    )
    assert post_run["extracted_data"] is None, (
        "SC1: persist_extracted's write must be rolled back too — not just the "
        "later replace_line_items call that raised"
    )
    assert post_run["decision"] is None, (
        "SC1: persist_decision's write must be rolled back too"
    )
    assert post_run["reconciliation"] is None, (
        "SC1: persist_reconciliation's write must be rolled back too"
    )


def test_run_stages_process_branch_call_order_and_status_last():
    """Offline (FakeConnection): pin the exact call order + status-advance-last
    inside _run_stages' process-branch transaction (D-9-02/D-9-04), and confirm
    the request_clarification branch's _clarify(...) call site is a SIBLING
    statement outside the `with conn.transaction():` block (D-9-01), via an
    AST/indentation check on the live source (checker's own technique).
    """
    import ast

    import app.pipeline.orchestrator as orch_mod

    src_path = orch_mod.__file__
    src = open(src_path).read()
    tree = ast.parse(src)

    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run_stages"
    )

    # Exactly one `with conn.transaction():` block inside _run_stages (comments
    # mentioning the phrase, e.g. the D-9-01 sibling-statement note, must not
    # be counted — only actual `with` statements via AST).
    tx_count = sum(
        1
        for node in ast.walk(func)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "transaction"
            for item in node.items
        )
    )
    assert tx_count == 1, (
        f"_run_stages must contain exactly one 'with conn.transaction():' block; "
        f"found {tx_count}"
    )

    # The _clarify(...) call inside _run_stages is NEVER nested inside any `with` block.
    def _walk(node, in_with=False):
        found = []
        for child in ast.iter_child_nodes(node):
            child_in_with = in_with or isinstance(child, ast.With)
            if isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Name) and f.id == "_clarify":
                    found.append((child.lineno, in_with))
            found.extend(_walk(child, child_in_with))
        return found

    clarify_calls = _walk(func)
    assert clarify_calls, "_run_stages must call _clarify(...) on the clarification branch"
    for lineno, in_with in clarify_calls:
        assert in_with is False, (
            f"_clarify(...) call at line {lineno} must be OUTSIDE any 'with' block "
            "(D-9-01 — no transaction may span an LLM/provider call)"
        )


# ===========================================================================
# Task 2 — _clarify's three exit paths (offline call-order pin)
# ===========================================================================


def test_clarify_idempotency_path_writes_snapshot_then_status_in_one_transaction(
    monkeypatch,
):
    """Offline: _clarify's idempotency early-return path (PATH 1) calls
    set_pre_clarify_extracted THEN set_status(AWAITING_REPLY), both carrying
    conn=, inside one transaction block (Test 3 of Task 2's behavior spec).
    """
    import app.db.repo as repo_mod
    import app.email.gateway as gateway_mod
    from app.pipeline.orchestrator import _clarify
    from tests.conftest import patch_get_connection

    ordering: list[tuple[str, bool]] = []

    def _fake_send_outbound(**kw):
        raise AssertionError("send_outbound must NOT be called on the idempotency path")

    monkeypatch.setattr(gateway_mod, "send_outbound", _fake_send_outbound, raising=True)
    monkeypatch.setattr(
        repo_mod,
        "get_outbound_message_id",
        lambda run_id, purpose=None, conn=None: "<already-sent@test>",
        raising=False,
    )

    def _spy_snapshot(run_id, extracted, conn=None):
        ordering.append(("set_pre_clarify_extracted", conn is not None))
        return True

    def _spy_status(run_id, status, conn=None):
        ordering.append(("set_status", conn is not None))

    monkeypatch.setattr(repo_mod, "set_pre_clarify_extracted", _spy_snapshot, raising=False)
    monkeypatch.setattr(repo_mod, "set_status", _spy_status, raising=False)
    patch_get_connection(monkeypatch, repo_mod)

    run_id = uuid.uuid4()
    _biz_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")
    roster = _bare_roster(_biz_id)
    email = _bare_inbound()
    decision = _bare_decision()
    extracted = Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(submitted_name="__stub__", hours_regular=Decimal("0"))],
    )

    _clarify(run_id, email, decision, roster, extracted, llm=None)

    assert ordering == [
        ("set_pre_clarify_extracted", True),
        ("set_status", True),
    ], (
        "PATH 1 (idempotency early-return): set_pre_clarify_extracted must run "
        "BEFORE set_status(AWAITING_REPLY), both carrying conn= (one transaction, "
        "status-advance-last, D-9-02/D-9-06); got: " + repr(ordering)
    )


def _bare_roster(business_id):
    from app.models.roster import Roster

    return Roster(business_id=business_id, employees=[])


def _bare_inbound():
    return InboundEmail(
        id=uuid.uuid4(),
        message_id="<orig@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="David Reyez 38 hours",
        created_at=datetime.now(timezone.utc),
    )


def _bare_decision():
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


# ===========================================================================
# Task 2 — _defer_field_regression_clarification (offline AST/order pin)
# ===========================================================================


def test_defer_field_regression_clarification_txn_closes_before_clarify_call(
    monkeypatch,
):
    """Offline (FakeConnection): _defer_field_regression_clarification's Step 3
    (set_clarified_fields) is the ONLY call inside its own `with
    conn.transaction():` block, and that block closes (AST/indentation check)
    before the Step 5 _clarify(...) call — sibling statement, never nested.
    """
    import ast

    import app.pipeline.orchestrator as orch_mod

    src = open(orch_mod.__file__).read()
    tree = ast.parse(src)

    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_defer_field_regression_clarification"
    )

    def _walk(node, in_with=False):
        results = []
        for child in ast.iter_child_nodes(node):
            child_in_with = in_with or isinstance(child, ast.With)
            if isinstance(child, ast.With):
                seg = ast.get_source_segment(src, child)
                first_line = seg.splitlines()[0] if seg else ""
                results.append(("WITH", child.lineno, first_line))
            if isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Attribute) and f.attr == "set_clarified_fields":
                    results.append(("SET_CLARIFIED", child.lineno, in_with))
                if isinstance(f, ast.Name) and f.id == "_clarify":
                    results.append(("CLARIFY_CALL", child.lineno, in_with))
            results.extend(_walk(child, child_in_with))
        return results

    events = _walk(func)

    set_clarified_events = [e for e in events if e[0] == "SET_CLARIFIED"]
    clarify_events = [e for e in events if e[0] == "CLARIFY_CALL"]
    assert len(set_clarified_events) == 1, (
        f"expected exactly one set_clarified_fields call in "
        f"_defer_field_regression_clarification; found {len(set_clarified_events)}"
    )
    assert set_clarified_events[0][2] is True, (
        "set_clarified_fields must be called INSIDE a 'with' block (its own transaction)"
    )
    assert clarify_events, "_defer_field_regression_clarification must call _clarify(...)"
    for lineno, in_with in [(e[1], e[2]) for e in clarify_events]:
        assert in_with is False, (
            f"_clarify(...) call at line {lineno} must be OUTSIDE any 'with' block "
            "(sibling statement, after the set_clarified_fields transaction closes)"
        )
    # Source-order: the transaction's WITH line comes before the _clarify call line.
    with_lines = [e[1] for e in events if e[0] == "WITH"]
    assert with_lines, "expected a 'with' block wrapping the Step 3 write"
    assert max(with_lines) < min(e[1] for e in clarify_events), (
        "the set_clarified_fields transaction block must close BEFORE the "
        "_clarify(...) call in source order"
    )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_defer_field_regression_write_survives_later_clarify_failure(seeded_db, monkeypatch):
    """Checker BLOCKER round 2: drive resume_pipeline's Round-1 field-regression
    path against a REAL DB; force the later _clarify call to raise AFTER
    _defer_field_regression_clarification's Step 3 write would have committed.
    Assert clarified_fields shows the 'asked' entry persisted (survives — it is
    a separate, already-closed transaction). resume_pipeline's own D-A1-03
    error-wrap boundary catches the forced failure and routes the run to ERROR
    (it never re-raises) — this proves no partial finalize state leaked from
    _clarify's own writes: the run lands in the diagnosable ERROR state, never
    a state that looks like a successful AWAITING_REPLY send that never happened.
    """
    from app.db import repo
    from app.pipeline.orchestrator import resume_pipeline

    get_settings = __import__("app.config", fromlist=["get_settings"]).get_settings
    get_settings.cache_clear()

    run_id = _seed_live_run(body="Maria Chen 40 regular 2 overtime")
    repo.set_status(run_id, RunStatus.AWAITING_REPLY)

    snapshot = _live_snapshot_extracted("Maria Chen", run_id, hours_regular="40", hours_overtime="2")
    repo.set_pre_clarify_extracted(run_id, snapshot)
    prior_match = NameMatchResult(
        submitted_name="Maria Chen",
        matched_employee_id=CHEN_ID,
        source="exact",
        resolved=True,
        reason="exact match",
    )
    repo.persist_reconciliation(run_id, [prior_match])

    monkeypatch.setattr("app.llm.client.OpenAI", LiveMockOpenAI)
    # Round-1 reply drops OT (silence) → field_regression detected → clarify_deferred.
    LiveMockOpenAI.script = [
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}]),
    ]
    LiveMockOpenAI.calls = []

    def _boom_clarify(*a, **kw):
        raise RuntimeError("injected crash — _clarify after Step-3 commit")

    import app.pipeline.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_clarify", _boom_clarify)

    reply = _live_inbound("Maria Chen 40 regular hours")

    # resume_pipeline's own D-A1-03 error-wrap boundary swallows the forced
    # failure and routes the run to ERROR — it never re-raises (verified against
    # live source, app/pipeline/orchestrator.py resume_pipeline's except clause).
    resume_pipeline(run_id, reply)

    post_run = repo.load_run(run_id)
    clarified = repo.load_clarified_fields(run_id)
    chen_id_str = str(CHEN_ID)
    assert clarified.get(chen_id_str, {}).get("hours_overtime") == "asked", (
        "the Step-3 set_clarified_fields commit must survive the later _clarify "
        f"failure (it is a separate, already-closed transaction); got: {clarified!r}"
    )
    assert post_run["status"] == RunStatus.ERROR.value, (
        "the run must land in the diagnosable ERROR state via resume_pipeline's "
        "D-A1-03 error-wrap boundary — never a state that implies a clarification "
        f"was sent when it wasn't; got status={post_run['status']!r}"
    )


# ===========================================================================
# Task 2 — _deliver's already-sent guard + main finalize transaction
# ===========================================================================


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_round2_clarified_fields_persist_before_run_stages(seeded_db, monkeypatch):
    """09-06 gap closure (WR-02): the Round-2 NON-deferred fall-through must persist
    `clarified_fields`'s terminal outcomes in its OWN closed transaction strictly
    BEFORE `_run_stages` is called on that path — a crash inside `_run_stages`' own
    persist transaction must never leave `clarified_fields` stuck at 'asked'.

    Setup: seed a run already at Round 2 (a prior `clarified_fields` entry exists for
    Chen's hours_overtime = 'asked'), matching prior reconciliation + a pre-clarify
    snapshot so `resume_pipeline` walks the Round-2 (`is_round_2=True`) branch. The
    reply answers the asked field with a positive value → classify-first (STEP 1)
    resolves it to 'client_supplied' in-memory, `stage.clarify_deferred` is False
    (no NEW field_regression this round).

    Fault injection: monkeypatch repo.set_status to raise on its FIRST call — this
    fires INSIDE _run_stages' own persist transaction (process branch), i.e. AFTER
    the fix's own set_clarified_fields commit has already closed.

    Assertions (both in the same test, proving the two writes are independently
    committed, not silently coupled):
      (a) repo.load_clarified_fields(run_id) shows 'client_supplied' (terminal), not
          'asked' — the earlier write survived the later crash.
      (b) the run's status is NOT 'awaiting_approval' — _run_stages' own crashed
          transaction rolled back cleanly and never advanced the run that far;
          resume_pipeline's D-A1-03 error-wrap boundary instead routes the run to
          the diagnosable ERROR status (its own genuine, second set_status call).
    """
    from app.db import repo
    from app.pipeline.orchestrator import resume_pipeline

    get_settings = __import__("app.config", fromlist=["get_settings"]).get_settings
    get_settings.cache_clear()

    run_id = _seed_live_run(body="Maria Chen 40 regular 2 overtime")
    repo.set_status(run_id, RunStatus.AWAITING_REPLY)

    # Snapshot = the pre-clarify extraction (Round-1's original submission).
    snapshot = _live_snapshot_extracted(
        "Maria Chen", run_id, hours_regular="40", hours_overtime="2"
    )
    repo.set_pre_clarify_extracted(run_id, snapshot)

    # Prior reconciliation: Maria Chen already resolved (Round-1's persisted match).
    prior_match = NameMatchResult(
        submitted_name="Maria Chen",
        matched_employee_id=CHEN_ID,
        source="exact",
        resolved=True,
        reason="exact match",
    )
    repo.persist_reconciliation(run_id, [prior_match])

    # Prior clarified_fields entry: hours_overtime is 'asked' — this makes
    # is_round_2 True (bool(clarified) is truthy) when resume_pipeline loads it.
    chen_id_str = str(CHEN_ID)
    repo.set_clarified_fields(run_id, {chen_id_str: {"hours_overtime": "asked"}})

    monkeypatch.setattr("app.llm.client.OpenAI", LiveMockOpenAI)
    # Round-2 reply: classify extraction (reply-only) AND process extraction
    # (combined body) both need scripted responses — two extract() calls happen
    # in the Round-2 non-deferred branch (CR-01 fix: reply-only + combined).
    LiveMockOpenAI.script = [
        _extraction_json(
            [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "3"}]
        ),
        _extraction_json(
            [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "3"}]
        ),
    ]
    LiveMockOpenAI.calls = []

    # Inject the crash INSIDE _run_stages' own persist transaction (process branch) —
    # set_status is the last write in that transaction (status-advance-last, D-9-02),
    # so forcing it to raise on its FIRST call proves the whole _run_stages transaction
    # (including persist_extracted/persist_decision/persist_reconciliation) rolls back.
    # Only the FIRST call raises — resume_pipeline's own D-A1-03 error-wrap boundary
    # calls record_run_error, which calls set_status(ERROR) a SECOND time; that call
    # must succeed genuinely so the run lands in the diagnosable ERROR state instead of
    # the exception propagating past resume_pipeline's own except clause.
    real_set_status = repo.set_status
    _calls = {"n": 0}

    def _boom_set_status_once(run_id_, status, conn=None):
        _calls["n"] += 1
        if _calls["n"] == 1:
            raise RuntimeError("injected crash — _run_stages' own set_status")
        return real_set_status(run_id_, status, conn=conn)

    monkeypatch.setattr(repo, "set_status", _boom_set_status_once)

    reply = _live_inbound("Maria Chen 40 regular 3 overtime")

    # resume_pipeline's own D-A1-03 error-wrap boundary swallows the forced failure —
    # it never re-raises (routes the run to ERROR instead).
    resume_pipeline(run_id, reply)
    monkeypatch.undo()

    from app.db import repo as real_repo

    clarified = real_repo.load_clarified_fields(run_id)
    assert clarified.get(chen_id_str, {}).get("hours_overtime") == "client_supplied", (
        "the D-9-06 fix's set_clarified_fields commit must survive the later crash "
        f"inside _run_stages' own transaction; got: {clarified!r}"
    )

    post_run = real_repo.load_run(run_id)
    assert post_run["status"] != RunStatus.AWAITING_APPROVAL.value, (
        "SC1: _run_stages' own crashed transaction must roll back cleanly and never "
        f"advance the run to AWAITING_APPROVAL; got status={post_run['status']!r}"
    )
    assert post_run["status"] == RunStatus.ERROR.value, (
        "the run must land in the diagnosable ERROR state via resume_pipeline's "
        f"D-A1-03 error-wrap boundary; got status={post_run['status']!r}"
    )


def test_round2_clarified_fields_persist_call_order_before_run_stages():
    """Offline (AST/source-order check): the Round-2 non-deferred branch's
    `set_clarified_fields` call is the ONLY such call before `_run_stages` returns
    on that path, is nested inside a `with conn.transaction():` block (its own
    closed transaction), and its `with` block closes strictly BEFORE the
    `stage = _run_stages(...)` call in source order — pinning the D-9-06 fix so a
    future refactor cannot silently move the write back to the buggy fall-through
    position (after `_run_stages` returns).
    """
    import ast

    import app.pipeline.orchestrator as orch_mod

    src = open(orch_mod.__file__).read()
    tree = ast.parse(src)

    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "resume_pipeline"
    )

    def _walk(node, in_with=False):
        results = []
        for child in ast.iter_child_nodes(node):
            child_in_with = in_with or isinstance(child, ast.With)
            if isinstance(child, ast.With):
                results.append(("WITH", child.lineno))
            if isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Attribute) and f.attr == "set_clarified_fields":
                    results.append(("SET_CLARIFIED", child.lineno, in_with))
                if isinstance(f, ast.Name) and f.id == "_run_stages":
                    results.append(("RUN_STAGES_CALL", child.lineno, in_with))
            results.extend(_walk(child, child_in_with))
        return results

    events = _walk(func)

    set_clarified_events = [e for e in events if e[0] == "SET_CLARIFIED"]
    run_stages_events = [e for e in events if e[0] == "RUN_STAGES_CALL"]

    assert len(run_stages_events) == 2, (
        "expected exactly two `_run_stages(...)` calls in resume_pipeline (Round-1 "
        f"branch + Round-2 branch); found {len(run_stages_events)}"
    )

    # For every set_clarified_fields call, it must be inside a `with` block (its own
    # transaction) — no bare, unwrapped call anywhere in resume_pipeline.
    for lineno, in_with in [(e[1], e[2]) for e in set_clarified_events]:
        assert in_with is True, (
            f"set_clarified_fields call at line {lineno} must be INSIDE a "
            "'with conn.transaction():' block (its own closed transaction) — no bare "
            "unwrapped call is permitted (D-9-06)"
        )

    # No `set_clarified_fields` call may appear strictly AFTER the LAST `_run_stages`
    # call's line — that would be the old buggy fall-through position.
    last_run_stages_line = max(e[1] for e in run_stages_events)
    for lineno, _in_with in [(e[1], e[2]) for e in set_clarified_events]:
        assert lineno < last_run_stages_line, (
            f"set_clarified_fields call at line {lineno} appears AFTER the last "
            f"_run_stages(...) call (line {last_run_stages_line}) — the Round-2 "
            "non-deferred fall-through must persist clarified_fields BEFORE calling "
            "_run_stages, not after (D-9-06 gap closure regression guard)"
        )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_deliver_finalize_alias_failure_still_reaches_reconciled(seeded_db, monkeypatch):
    """Pitfall 2 regression: force _write_aliases_if_safe to raise inside
    _deliver's finalize block; assert the run STILL reaches RECONCILED — the
    try/except isolation was NOT accidentally moved outside `with
    conn.transaction():`.
    """
    from app.db import repo
    from app.pipeline.orchestrator import _deliver

    monkeypatch.setattr(resend.Emails, "send", staticmethod(lambda params: {"id": "test-id"}))

    run_id = _seed_live_run(body="Maria Chen 40 regular")
    repo.set_status(run_id, RunStatus.APPROVED)
    run = repo.load_run(run_id)

    import app.pipeline.orchestrator as orch_mod

    def _boom_alias(*a, **kw):
        raise RuntimeError("injected crash — alias write")

    monkeypatch.setattr(orch_mod, "_write_aliases_if_safe", _boom_alias)

    _deliver(run_id, run)

    post_run = repo.load_run(run_id)
    assert post_run["status"] == "reconciled", (
        "a forced alias-write failure must NOT roll back the delivery finalize — "
        f"the run must still reach 'reconciled'; got {post_run['status']!r}"
    )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_deliver_finalize_status_crash_leaves_run_at_approved(seeded_db, monkeypatch):
    """Force repo.set_status to raise on its FIRST call inside _deliver's
    finalize block (simulating a crash between the alias write and
    set_status(SENT)); assert the run's status is unchanged from APPROVED —
    never left at 'sent' alone with 'reconciled' missing.
    """
    from app.db import repo
    from app.pipeline.orchestrator import _deliver

    monkeypatch.setattr(resend.Emails, "send", staticmethod(lambda params: {"id": "test-id"}))

    run_id = _seed_live_run(body="Maria Chen 40 regular")
    repo.set_status(run_id, RunStatus.APPROVED)
    run = repo.load_run(run_id)

    def _boom_status(run_id_, status, conn=None):
        raise RuntimeError("injected crash — set_status(SENT)")

    monkeypatch.setattr(repo, "set_status", _boom_status)

    with pytest.raises(RuntimeError, match="injected crash"):
        _deliver(run_id, run)

    # Bypass the monkeypatched set_status for the assertion read via a direct load_run.
    monkeypatch.undo()
    from app.db import repo as real_repo

    post_run = real_repo.load_run(run_id)
    assert post_run["status"] == RunStatus.APPROVED.value, (
        "a crash between the alias write and set_status(SENT) must leave the run "
        f"at APPROVED (unadvanced) — never 'sent' alone; got {post_run['status']!r}"
    )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_deliver_finalize_crash_preserves_wr04_payroll_roster_attribute(seeded_db, monkeypatch):
    """Checker WARNING 1: a forced exception inside the NEW finalize `with
    conn.transaction():` block still results in the raised exception carrying
    `payroll_roster` — proving the finalize transaction is nested INSIDE the
    existing WR-04 try/except, not outside or replacing it.
    """
    from app.db import repo
    from app.pipeline.orchestrator import _deliver

    monkeypatch.setattr(resend.Emails, "send", staticmethod(lambda params: {"id": "test-id"}))

    run_id = _seed_live_run(body="Maria Chen 40 regular")
    repo.set_status(run_id, RunStatus.APPROVED)
    run = repo.load_run(run_id)

    def _boom_status(run_id_, status, conn=None):
        raise RuntimeError("injected crash — WR-04 preservation check")

    monkeypatch.setattr(repo, "set_status", _boom_status)

    with pytest.raises(RuntimeError) as exc_info:
        _deliver(run_id, run)

    assert hasattr(exc_info.value, "payroll_roster"), (
        "a failure inside the new finalize transaction must still result in "
        "exc.payroll_roster being attached (WR-04 preservation, checker WARNING 1)"
    )


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_deliver_retry_over_sent_completes_alias_write_exactly_once(seeded_db, monkeypatch):
    """Codex HIGH-2 regression: calling _deliver a SECOND time over an
    already-sent confirmation row (retry-over-sent path) must invoke
    _write_aliases_if_safe exactly once during that second call, and the run
    must reach status == 'reconciled' — closing the silent-alias-skip gap.
    """
    from app.db import repo
    from app.pipeline.orchestrator import _deliver

    monkeypatch.setattr(resend.Emails, "send", staticmethod(lambda params: {"id": "test-id"}))

    run_id = _seed_live_run(body="Maria Chen 40 regular")
    repo.set_status(run_id, RunStatus.APPROVED)
    run = repo.load_run(run_id)

    # First call: real happy path, genuinely reaches SENT + RECONCILED.
    _deliver(run_id, run)
    post_first = repo.load_run(run_id)
    assert post_first["status"] == "reconciled"

    # Simulate "operator retriggers _deliver again" by resetting status back to
    # APPROVED (the run's confirmation row genuinely IS already 'sent' — the
    # already-sent guard branch is what we're exercising).
    repo.set_status(run_id, RunStatus.APPROVED)

    import app.pipeline.orchestrator as orch_mod

    alias_calls: list = []
    original_write = orch_mod._write_aliases_if_safe

    def _spy_write(run_id_, run_, roster_, conn=None):
        alias_calls.append(1)
        return original_write(run_id_, run_, roster_, conn=conn)

    monkeypatch.setattr(orch_mod, "_write_aliases_if_safe", _spy_write)

    run2 = repo.load_run(run_id)
    _deliver(run_id, run2)

    assert len(alias_calls) == 1, (
        "the hardened already-sent guard must invoke _write_aliases_if_safe "
        f"exactly once on a retry-over-sent call; got {len(alias_calls)} calls"
    )
    post_second = repo.load_run(run_id)
    assert post_second["status"] == "reconciled", (
        "the retry-over-sent path must still reach 'reconciled'; got "
        f"{post_second['status']!r}"
    )
