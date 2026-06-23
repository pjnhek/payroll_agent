"""Shared test fixtures for the Phase 2 walking skeleton.

Three reusable pieces every later-wave test imports (the plan's conftest artifact):

1. `fake_conn` / `FakeConnection` — an in-memory psycopg-Connection stand-in that
   records every executed SQL statement + params and replays scripted fetch
   results, so the parameterized-SQL discipline (no f-string SQL), the
   set_status-only-writes-status rule, and the model_dump serialization can be
   asserted offline with no live database.

2. `inbound_email` — a committed canonical InboundEmail fixture loader (a cleaned
   inbound body, the shape the extraction stage receives).

3. `roster_from_seed` — builds a typed Roster from the in-memory seed dataset
   (seed(dry_run=True)) so reconciliation/gate tests get a real roster without a DB.

The mocked-LLM client factory lives with the client tests (tests/test_llm_client.py
injects a FakeOpenAI over app.llm.client.OpenAI); it is re-exported here as
`fake_openai_factory` for any later-wave stage test that needs it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models.contracts import InboundEmail
from app.models.roster import Roster


# ---------------------------------------------------------------------------
# 1. FakeConnection — records SQL, replays scripted fetches (no DB)
# ---------------------------------------------------------------------------


class FakeCursor:
    """Minimal psycopg-cursor stand-in usable as a context manager."""

    def __init__(self, conn: "FakeConnection") -> None:
        self._conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        return self

    def fetchone(self):
        return self._conn._next_fetchone()

    def fetchall(self):
        return self._conn._next_fetchall()


class FakeTransaction:
    """Context manager mirroring psycopg's conn.transaction()."""

    def __enter__(self) -> "FakeTransaction":
        return self

    def __exit__(self, *exc) -> None:
        return None


class FakeConnection:
    """In-memory psycopg.Connection stand-in.

    Records (sql, params) for every execute() and serves scripted fetch results.
    Use `script_fetchone(...)` / `script_fetchall(...)` to enqueue results that
    the code-under-test will pull in order.
    """

    def __init__(self) -> None:
        self.executed: list[tuple] = []
        self._fetchone_q: list = []
        self._fetchall_q: list = []

    # --- scripting helpers (test-facing) ---
    def script_fetchone(self, row) -> None:
        self._fetchone_q.append(row)

    def script_fetchall(self, rows) -> None:
        self._fetchall_q.append(rows)

    def _next_fetchone(self):
        return self._fetchone_q.pop(0) if self._fetchone_q else None

    def _next_fetchall(self):
        return self._fetchall_q.pop(0) if self._fetchall_q else []

    # --- psycopg.Connection surface used by repo.py ---
    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def cursor(self, *args, **kwargs) -> FakeCursor:
        return FakeCursor(self)

    def fetchone(self):
        return self._next_fetchone()

    def fetchall(self):
        return self._next_fetchall()

    # --- assertion helpers ---
    def all_sql(self) -> str:
        return "\n".join(str(sql) for sql, _ in self.executed)

    def last(self) -> tuple:
        return self.executed[-1]


@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()


# ---------------------------------------------------------------------------
# 2. inbound_email — a canonical cleaned InboundEmail value
# ---------------------------------------------------------------------------


@pytest.fixture
def inbound_email() -> InboundEmail:
    """A cleaned canonical InboundEmail (the shape extraction receives)."""
    return InboundEmail(
        id=uuid.uuid4(),
        message_id="<client-001@acme.test>",
        in_reply_to=None,
        references_header=None,
        subject="Payroll hours for week of 2026-06-15",
        from_addr="payroll@acme.test",
        to_addr="agent@payroll-agent.local",
        body_text="Maria 40 regular, David 38 regular. Thanks!",
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# 3. roster_from_seed — a typed Roster from the in-memory seed
# ---------------------------------------------------------------------------


@pytest.fixture
def roster_from_seed() -> Roster:
    """Build a Roster for the happy-path business from seed(dry_run=True)."""
    from app.db.seed import seed

    result = seed(dry_run=True)
    business_id = result.employees[0].business_id
    employees = [e for e in result.employees if e.business_id == business_id]
    return Roster(business_id=business_id, employees=employees)


# ---------------------------------------------------------------------------
# 4. fake_repo — an in-memory repo store so the FULL pipeline runs offline
# ---------------------------------------------------------------------------
#
# The webhook + orchestrator both call app.db.repo helpers. To assert the
# end-to-end flow (POST → BackgroundTask → stages → awaiting_approval) with no
# live DB, this fixture monkeypatches the repo helpers the webhook/orchestrator
# touch onto an in-memory store that mirrors their real semantics: inbound dedupe
# on message_id, sender→business lookup over the seed, run-row lifecycle, JSONB
# persistence, the sole set_status writer, and record_run_error routing.


class InMemoryRepo:
    """Mirror of the repo surface the webhook + orchestrator exercise, in RAM."""

    def __init__(self) -> None:
        self.emails: dict[str, dict] = {}  # message_id -> email row
        self.email_by_id: dict[str, dict] = {}  # email_id -> email row
        self.runs: dict[str, dict] = {}  # run_id -> run row
        self.line_items: dict[str, list] = {}  # run_id -> list[PaystubLineItem]
        # Outbound email_messages rows (the FIX 3 anchor): run_id -> list of rows.
        self.outbound: dict[str, list] = {}
        # Seed businesses for sender matching.
        from app.db.seed import seed

        seeded = seed(dry_run=True)
        self.contact_to_business = {
            b["contact_email"]: b["id"] for b in seeded.businesses
        }
        self.business_employees: dict[str, list] = {}
        for emp in seeded.employees:
            self.business_employees.setdefault(str(emp.business_id), []).append(emp)

    # --- ingest / lifecycle ---
    def insert_inbound_email(self, **kw):
        mid = kw["message_id"]
        if mid in self.emails:
            return None, False
        eid = uuid.uuid4()
        row = {"id": eid, **kw}
        self.emails[mid] = row
        self.email_by_id[str(eid)] = row
        return eid, True

    def find_business_by_sender(self, from_addr, conn=None):
        return self.contact_to_business.get(from_addr)

    def create_run(self, *, business_id, source_email_id, pay_period_start=None,
                   pay_period_end=None, conn=None):
        rid = uuid.uuid4()
        self.runs[str(rid)] = {
            "id": rid,
            "business_id": business_id,
            "source_email_id": source_email_id,
            "status": "received",
            "extracted_data": None,
            "decision": None,
            "reconciliation": None,
            "error_reason": None,
            "pay_period_start": pay_period_start,
            "pay_period_end": pay_period_end,
        }
        return rid

    def load_run(self, run_id, conn=None):
        return self.runs.get(str(run_id))

    def load_source_email(self, run_id, conn=None):
        run = self.runs.get(str(run_id))
        if not run or not run["source_email_id"]:
            return None
        row = self.email_by_id.get(str(run["source_email_id"]))
        return row["body_text"] if row else None

    def load_inbound_email(self, run_id, conn=None):
        from app.models.contracts import InboundEmail

        run = self.runs.get(str(run_id))
        if not run or not run["source_email_id"]:
            return None
        row = self.email_by_id.get(str(run["source_email_id"]))
        if not row:
            return None
        return InboundEmail(
            id=row["id"],
            message_id=row["message_id"],
            in_reply_to=row.get("in_reply_to"),
            references_header=row.get("references_header"),
            subject=row.get("subject") or "",
            from_addr=row.get("from_addr") or "",
            to_addr=row.get("to_addr") or "",
            body_text=row["body_text"],
            created_at=datetime.now(timezone.utc),
        )

    def load_roster_for_business(self, business_id, conn=None):
        return Roster(
            business_id=business_id,
            employees=list(self.business_employees.get(str(business_id), [])),
        )

    # --- status / persistence ---
    def set_status(self, run_id, status, conn=None):
        from app.models.status import RunStatus

        self.runs[str(run_id)]["status"] = RunStatus(status).value

    def claim_status(self, run_id, expected, new, conn=None):
        """Atomic CAS for the in-memory store (mirrors repo.claim_status, D-12).

        Returns True and advances the run's status if the current status matches
        `expected`. Returns False if the run is not in the expected state.
        """
        from app.models.status import RunStatus

        run = self.runs.get(str(run_id))
        if run is None:
            return False
        if run["status"] != RunStatus(expected).value:
            return False
        run["status"] = RunStatus(new).value
        return True

    def record_run_error(self, run_id, reason, conn=None):
        from app.db.repo import _TERMINAL_STATUSES
        from app.models.status import RunStatus

        # Mirror the real repo's WR-04 guard: never clobber a terminal run to ERROR.
        if self.runs[str(run_id)]["status"] in _TERMINAL_STATUSES:
            return
        self.runs[str(run_id)]["error_reason"] = reason
        self.set_status(run_id, RunStatus.ERROR)

    def persist_extracted(self, run_id, extracted, conn=None):
        self.runs[str(run_id)]["extracted_data"] = extracted.model_dump(mode="json")

    def persist_decision(self, run_id, decision, conn=None):
        self.runs[str(run_id)]["decision"] = decision.model_dump(mode="json")

    def persist_reconciliation(self, run_id, matches, conn=None):
        self.runs[str(run_id)]["reconciliation"] = [
            m.model_dump(mode="json") for m in matches
        ]

    def replace_line_items(self, run_id, items, conn=None):
        self.line_items[str(run_id)] = list(items)

    def set_alias_candidates(self, run_id, candidates, conn=None):
        """Store alias candidates in the in-memory run dict (D-04, mirrors repo)."""
        run = self.runs.get(str(run_id))
        if run is not None:
            run["alias_candidates"] = candidates

    # --- email / threading (the FIX 3 outbound Message-ID anchor) ---
    def insert_email_message(self, *, run_id, direction, message_id, conn=None, **kw):
        row = {"run_id": run_id, "direction": direction, "message_id": message_id, **kw}
        if direction == "outbound" and run_id is not None:
            self.outbound.setdefault(str(run_id), []).append(row)
        return uuid.uuid4()

    def get_outbound_message_id(self, run_id, purpose=None, conn=None):
        """Purpose-aware outbound Message-ID lookup (mirrors repo.get_outbound_message_id).

        When purpose is provided, filters by purpose to match the real repo's behavior.
        When purpose is None (legacy test calls without purpose arg), returns the last
        outbound row for the run — this preserves backward compatibility for test_orchestrator_states
        and test_demo_fixtures which assert the outbound row exists, not which purpose.
        """
        rows = self.outbound.get(str(run_id))
        if not rows:
            return None
        if purpose is not None:
            # Filter to rows with matching purpose and send_state='sent' (mirrors real repo)
            matching = [r for r in rows if r.get("purpose") == purpose and r.get("send_state") == "sent"]
            return matching[-1]["message_id"] if matching else None
        return rows[-1]["message_id"]

    # --- header-chain reply routing (CLAR-02/03, Plan 04) ---
    def _header_matches(self, in_reply_to, references_header, row):
        """Mirror the repo SQL: outbound Message-ID == in_reply_to OR is a WHOLE
        whitespace-bounded token in References (WR-02 anchoring — not a bare
        substring, so `<a@x>` never matches inside `<a@xtra>`)."""
        mid = row["message_id"]
        if in_reply_to is not None and mid == in_reply_to:
            return True
        if not references_header:
            return False
        # Whole-token match: mid must appear as a whitespace-separated token.
        return mid in references_header.split()

    def find_awaiting_reply_for_header(self, *, in_reply_to, references_header, conn=None):
        """Header match restricted to status='awaiting_reply' (resume lookup)."""
        for run_id, rows in self.outbound.items():
            run = self.runs.get(run_id)
            if not run or run["status"] != "awaiting_reply":
                continue
            for row in rows:
                if self._header_matches(in_reply_to, references_header, row):
                    return uuid.UUID(run_id)
        return None

    def find_any_run_for_header(self, *, in_reply_to, references_header, conn=None):
        """The SAME header match across ANY status (late-reply observability, FIX 10)."""
        for run_id, rows in self.outbound.items():
            for row in rows:
                if self._header_matches(in_reply_to, references_header, row):
                    return uuid.UUID(run_id)
        return None


@pytest.fixture
def fake_repo(monkeypatch) -> InMemoryRepo:
    """Patch app.db.repo helpers onto an in-memory store (webhook + orchestrator)."""
    store = InMemoryRepo()
    import app.db.repo as repo_mod

    for name in (
        "insert_inbound_email",
        "find_business_by_sender",
        "create_run",
        "load_run",
        "load_source_email",
        "load_inbound_email",
        "load_roster_for_business",
        "set_status",
        "claim_status",
        "record_run_error",
        "persist_extracted",
        "persist_decision",
        "persist_reconciliation",
        "replace_line_items",
        "set_alias_candidates",
        "insert_email_message",
        "get_outbound_message_id",
        "find_awaiting_reply_for_header",
        "find_any_run_for_header",
    ):
        if hasattr(store, name):
            monkeypatch.setattr(repo_mod, name, getattr(store, name), raising=False)
    return store


# ---------------------------------------------------------------------------
# 5. mock_llm — script the OpenAI client so stages run with no network
# ---------------------------------------------------------------------------


class _MockMessage:
    def __init__(self, content):
        self.content = content


class _MockChoice:
    def __init__(self, content):
        self.message = _MockMessage(content)


class _MockResponse:
    def __init__(self, content):
        self.choices = [_MockChoice(content)]


class _MockCompletions:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kwargs):
        self._parent.calls.append(kwargs)
        content = self._parent.script.pop(0) if self._parent.script else "{}"
        return _MockResponse(content)


class _MockChat:
    def __init__(self, parent):
        self.completions = _MockCompletions(parent)


class MockOpenAI:
    """A scriptable OpenAI stand-in shared across all client instances.

    Because app.llm.client constructs a fresh OpenAI() per call, the script is a
    class-level FIFO queue so sequential stage calls (extract → decide) each pop
    the next scripted JSON string in order.
    """

    script: list = []
    calls: list = []

    def __init__(self, *, base_url=None, api_key=None, **_):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = _MockChat(MockOpenAI)


@pytest.fixture
def mock_llm(monkeypatch):
    """Patch app.llm.client.OpenAI with a class-level FIFO script.

    Returns the MockOpenAI class; set `mock_llm.script = [json1, json2, ...]` to
    enqueue the structured responses sequential stage calls will consume.
    """
    MockOpenAI.script = []
    MockOpenAI.calls = []
    monkeypatch.setattr("app.llm.client.OpenAI", MockOpenAI)
    return MockOpenAI


# ---------------------------------------------------------------------------
# 6. seed_roster — Roster with the David+Daniel Reyes collision pair (Plan 05-02)
# ---------------------------------------------------------------------------


@pytest.fixture
def seed_roster() -> Roster:
    """A Roster built from Business 2 seed data, which contains the
    David Reyes / Daniel Reyes collision pair.

    Both David Reyes (e0000003) and Daniel Reyes (e0000007) carry
    known_aliases=["D. Reyes"], so submitting "D. Reyes" always gates to
    request_clarification (the collision-safety invariant, D-21-02).

    Required by: test_alias_write.py (Plan 05-01 Task 1), test_delivery.py
    (Plan 05-02 Task 2), and any future test needing the collision pair.
    """
    from app.db.seed import seed

    result = seed(dry_run=True)

    # Business 2 UUID (b0000002) contains David + Daniel Reyes collision pair.
    biz2_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    biz2_employees = [e for e in result.employees if e.business_id == biz2_id]

    # Verify the collision pair is present (guard against seed changes).
    names = {e.full_name for e in biz2_employees}
    assert "David Reyes" in names, "seed must contain David Reyes (e0000003)"
    assert "Daniel Reyes" in names, "seed must contain Daniel Reyes (e0000007)"

    return Roster(business_id=biz2_id, employees=biz2_employees)
