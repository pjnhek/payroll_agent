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
