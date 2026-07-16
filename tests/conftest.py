"""Shared test fixtures — the offline doubles that let the whole suite run with no DB
and no network.

Three reusable pieces most tests import:

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
`fake_openai_factory` for any stage test that needs it.
"""
from __future__ import annotations

import contextlib
import os
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import resend  # noqa: F401 — imported so the module is available for monkeypatching

from app.models.contracts import InboundEmail
from app.models.roster import Roster

# A hard set (not setdefault) at module top, before any test module imports
# app.main. Ten existing tests open `with TestClient(app)`, which DOES run
# FastAPI lifespan events — once the queue worker's lifespan lands, an
# unpinned WORKER_COUNT would spawn real daemon threads hitting the real DB
# from every one of those tests. A hard set also beats any stray .env entry:
# actual environment variables outrank pydantic-settings' env_file loading.
# Tests that need a real worker call worker.start(n=...) explicitly — never
# through this env var.
os.environ["WORKER_COUNT"] = "0"

# ---------------------------------------------------------------------------
# 0a. Suite-wide daemon-worker leak guard — the name prefix every real queue
# worker thread carries, a thread scanner, and the failure body, factored
# apart from the autouse fixture below so a test can drive the guard
# directly (start a sentinel thread, assert the guard raises, join it, assert
# the guard then returns cleanly) without needing app.queue.worker to exist.
#
# The `worker` module is process-global state, and a hermetic worker-unit
# test file and this suite's live-DB durability proofs run in the SAME
# pytest process — a daemon thread leaked by one file is still alive,
# claiming rows, when a later file runs. Scanning threads by NAME (not by
# asking the worker module "do you have live workers?") is deliberate: the
# failure this exists to catch is a thread the worker module itself has
# forgotten about or never tracked, and a query routed back through that
# same module would answer "no" in exactly the case that matters.
# ---------------------------------------------------------------------------

QUEUE_WORKER_THREAD_PREFIX = "queue-worker-"


def live_queue_worker_threads() -> list[threading.Thread]:
    """Every currently-alive thread whose name starts with the queue worker
    prefix — a plain `threading.enumerate()` scan, no import on the worker
    module itself."""
    return [
        t
        for t in threading.enumerate()
        if t.is_alive() and t.name.startswith(QUEUE_WORKER_THREAD_PREFIX)
    ]


def fail_on_leaked_queue_workers() -> None:
    """Fail loudly, naming every surviving thread and its daemon flag, if any
    queue-worker-* thread is still alive. Factored out of the autouse fixture
    below so a test can exercise this behavior directly."""
    survivors = live_queue_worker_threads()
    if survivors:
        pytest.fail(
            "leaked queue-worker thread(s) still alive after test teardown: "
            + ", ".join(f"{t.name} (daemon={t.daemon})" for t in survivors)
        )


@pytest.fixture(autouse=True)
def _no_leaked_queue_workers():
    """Suite-wide autouse fixture: at the teardown of EVERY test, fail if a
    queue-worker-* thread survived it. Attributes a leak to the test that
    caused it rather than to an innocent test several files later that
    happens to trip over the leftover thread.

    This does NOT make tests/test_queue_durability.py's own `_isolated_jobs`
    delete-gate redundant, and the two are not interchangeable: pytest sets
    up conftest-level fixtures BEFORE module-local ones, so it tears THIS one
    down AFTER `_isolated_jobs` has already issued its DELETE. This fixture
    can only report a leak after the fact; only a gate INSIDE
    `_isolated_jobs`, ahead of its own delete statement, can prevent that
    delete from landing beneath a still-live worker.
    """
    yield
    fail_on_leaked_queue_workers()


# ---------------------------------------------------------------------------
# 0. Live-DB two-factor guard + shared seeded_db fixture
#
# Live-DB integration tests require BOTH DATABASE_URL (a reachable DB) AND
# ALLOW_DB_RESET=1 (explicit opt-in to the destructive bootstrap --reset). The
# guard and the fixture live here so every test module shares ONE definition —
# duplicating them per module invites the two factors drifting apart, and a
# reset that fires against a real database is unrecoverable. Module scope means
# each test module still resets+seeds exactly once.
# ---------------------------------------------------------------------------

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

# Shared skip mark for live-DB tests (two-factor guard).
_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)


@pytest.fixture(scope="module")
def seeded_db():
    """Module-scoped fixture: reset DB, apply schema, seed once.

    Only executes when both DATABASE_URL and ALLOW_DB_RESET=1 are set — the
    two-factor guard prevents an accidental destructive reset against a real DB.
    """
    if not (_HAS_DB and _HAS_RESET):
        pytest.skip(
            "DATABASE_URL or ALLOW_DB_RESET=1 not set — skipping live-DB fixture"
        )
    from app.db.bootstrap import bootstrap
    from app.db.seed import seed as _seed

    bootstrap(reset=True)
    _seed()
    yield


# ---------------------------------------------------------------------------
# 1. FakeConnection — records SQL, replays scripted fetches (no DB)
# ---------------------------------------------------------------------------


class FakeCursor:
    """Minimal psycopg-cursor stand-in usable as a context manager."""

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        return self

    def fetchone(self) -> Any:
        return self._conn._next_fetchone()

    def fetchall(self) -> Any:
        return self._conn._next_fetchall()


class FakeTransaction:
    """Context manager mirroring psycopg's conn.transaction()."""

    def __enter__(self) -> FakeTransaction:
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
        self.executed: list[tuple[Any, Any]] = []
        self._fetchone_q: list[Any] = []
        self._fetchall_q: list[Any] = []

    # --- scripting helpers (test-facing) ---
    def script_fetchone(self, row: Any) -> None:
        self._fetchone_q.append(row)

    def script_fetchall(self, rows: Any) -> None:
        self._fetchall_q.append(rows)

    def _next_fetchone(self) -> Any:
        return self._fetchone_q.pop(0) if self._fetchone_q else None

    def _next_fetchall(self) -> Any:
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

    def last(self) -> tuple[Any, Any]:
        return self.executed[-1]


@pytest.fixture
def fake_conn() -> FakeConnection:
    return FakeConnection()


@contextlib.contextmanager
def _fake_get_connection():
    """Context manager double for app.db.repo.get_connection.

    Patched onto app.db.repo.get_connection by the fake_repo fixture below so
    that `with repo.get_connection() as conn: with conn.transaction(): ...`
    code (the transaction seam the orchestrator and routes open) runs against a
    FakeConnection instead of opening a real Supabase pool. Without this seam
    any such block would make every fake_repo-driven test try to open a live
    connection and fail/hang.
    """
    yield FakeConnection()


def patch_get_connection(monkeypatch, repo_mod) -> None:
    """Monkeypatch repo_mod.get_connection to the FakeConnection double.

    For tests that monkeypatch individual app.db.repo.* helpers directly
    (rather than using the fake_repo fixture) and call orchestrator functions
    that open `with repo.get_connection() as conn: with conn.transaction():`
    blocks — without this patch such a test would attempt to open a real pooled
    Supabase connection and hang / time out. Call this once per test alongside
    the other repo_mod monkeypatches.
    """
    monkeypatch.setattr(repo_mod, "get_connection", _fake_get_connection, raising=False)


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
        created_at=datetime.now(UTC),
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
        self.emails: dict[str, dict[str, Any]] = {}  # message_id -> email row
        self.email_by_id: dict[str, dict[str, Any]] = {}  # email_id -> email row
        self.runs: dict[str, dict[str, Any]] = {}  # run_id -> run row
        self.line_items: dict[str, list[Any]] = {}  # run_id -> list[PaystubLineItem]
        # Outbound email_messages rows (the Message-ID threading anchor):
        # run_id -> list of rows.
        self.outbound: dict[str, list[dict[str, Any]]] = {}
        # Durable job queue mirror: job_id -> job row, plus a dedup_key index
        # standing in for the real table's UNIQUE(dedup_key) constraint.
        self.jobs: dict[str, dict[str, Any]] = {}
        self._job_dedup_keys: dict[str, uuid.UUID] = {}
        self.operator_resume_resolutions: dict[
            tuple[str, str], dict[str, str]
        ] = {}
        self.context_calls: list[tuple[Any, ...]] = []
        # Seed businesses for sender matching.
        from app.db.seed import seed

        seeded = seed(dry_run=True)
        self.contact_to_business = {
            b["contact_email"]: b["id"] for b in seeded.businesses
        }
        self.business_employees: dict[str, list[Any]] = {}
        for emp in seeded.employees:
            self.business_employees.setdefault(str(emp.business_id), []).append(emp)

    # --- ingest / lifecycle ---
    def insert_inbound_email(self, **kw: Any) -> tuple[uuid.UUID | None, bool]:
        mid = kw["message_id"]
        if mid in self.emails:
            return None, False
        eid = uuid.uuid4()
        # Every fake email row carries direction (the real insert_inbound_email
        # hardcodes 'inbound' in its SQL, so kw never passes it), round (default
        # 0), and consumed_round (default None, meaning unconsumed), so
        # load_consumed_replies / mark_reply_consumed /
        # get_inbound_by_message_id can read/write these exactly like the real
        # repo does on the real email_messages columns.
        row = {
            "id": eid,
            "direction": "inbound",
            "round": 0,
            "consumed_round": None,
            "created_at": datetime.now(UTC),
            **kw,
        }
        self.emails[mid] = row
        self.email_by_id[str(eid)] = row
        return eid, True

    def find_business_by_sender(self, from_addr, conn=None):
        return self.contact_to_business.get(from_addr)

    def link_email_to_run(
        self, email_id: uuid.UUID, run_id: uuid.UUID, conn: Any = None
    ) -> None:
        """Mirror repo.link_email_to_run.

        Back-fills run_id on an already-inserted inbound row once the ingest
        transaction classifies it as reply_candidate/late_reply, so tests can
        assert real reply rows are linked to their run like the demo path.

        Also stamps the linked row's epoch key from the CURRENT reply_epoch of
        the target run at link time (mirrors repo's correlated subquery), so a
        reply can never be read back against a later epoch's context. Defaults
        to 0 via .get on both sides, matching the real NOT NULL DEFAULT 0 column.
        """
        row = self.email_by_id.get(str(email_id))
        if row is not None:
            row["run_id"] = run_id
            run = self.runs.get(str(run_id))
            row["epoch"] = run.get("reply_epoch", 0) if run is not None else 0

    def find_run_by_message_id(self, message_id, conn=None):
        """Mirror repo.find_run_by_message_id (the webhook-dedup loser's lookup).

        Scans the in-memory email store for a row with this message_id, then
        returns the run whose source_email_id matches that row's id — the
        same join repo.py does in SQL, over the in-memory store instead.
        """
        row = self.emails.get(message_id)
        if row is None:
            return None
        email_id = row.get("id")
        for run in self.runs.values():
            if run.get("source_email_id") == email_id or str(
                run.get("source_email_id")
            ) == str(email_id):
                return run["id"]
        return None

    def create_run(
        self,
        *,
        business_id: uuid.UUID,
        source_email_id: uuid.UUID | None,
        pay_period_start: Any = None,
        pay_period_end: Any = None,
        record_only: bool = False,
        conn: Any = None,
    ) -> uuid.UUID:
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
            "error_detail": None,
            "pay_period_start": pay_period_start,
            "pay_period_end": pay_period_end,
            "record_only": record_only,
            # Every run starts at round 0, matching the real column's NOT NULL
            # DEFAULT 0.
            "clarification_round": 0,
        }
        return rid

    def load_run(
        self, run_id: uuid.UUID, conn: Any = None
    ) -> dict[str, Any] | None:
        # Mirror the real seam's contract (app/db/repo/runs.py load_run):
        # a missing run is None, not a cast-stamped lie.
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
            created_at=datetime.now(UTC),
        )

    def load_roster_for_business(self, business_id, conn=None):
        return Roster(
            business_id=business_id,
            employees=list(self.business_employees.get(str(business_id), [])),
        )

    # --- status / persistence ---
    def set_status(self, run_id: uuid.UUID, status: Any, conn: Any = None) -> None:
        from app.models.status import RunStatus

        self.runs[str(run_id)]["status"] = RunStatus(status).value

    def claim_status(
        self, run_id: uuid.UUID, expected: Any, new: Any, conn: Any = None
    ) -> bool:
        """Atomic CAS for the in-memory store (mirrors repo.claim_status).

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

    def record_run_error(
        self, run_id, reason, conn=None, *, detail_exc=None, stage=None, roster=None
    ):
        from app.db.repo import _TERMINAL_STATUSES
        from app.models.status import RunStatus

        # Mirror the real repo's guard: never clobber a terminal run to ERROR.
        if self.runs[str(run_id)]["status"] in _TERMINAL_STATUSES:
            return
        self.runs[str(run_id)]["error_reason"] = reason
        # Mirrors the real repo.record_run_error's keyword-only-extras shape
        # (conn stays positional-compatible) so call sites passing
        # detail_exc=/stage=/roster= don't raise TypeError against this fake.
        # The real PII scrub logic is unit-tested against the real
        # repo.record_run_error — this fake only needs to not error.
        self.runs[str(run_id)]["error_detail"] = None
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

    def load_line_items(self, run_id, conn=None):
        """Return stored PaystubLineItem list for a run (mirrors repo.load_line_items)."""
        return list(self.line_items.get(str(run_id), []))

    def load_all_runs(self, conn=None):
        """Return all runs as dicts with business_name (mirrors repo.load_all_runs).

        Also computes the SQL-computed `summary_gate_reason` / `employee_count`
        aliases the real repo.load_all_runs projects, so route-level tests that
        swap in InMemoryRepo keep exercising the real runs_list.html alias
        contract instead of silently falling through to the template's `--`
        else-branch.
        """
        result = []
        for run in self.runs.values():
            biz_name = "Test Business"
            decision = run.get("decision")
            gate_reasons = (
                (decision or {}).get("gate_reasons") if isinstance(decision, dict) else None
            )
            summary_gate_reason = gate_reasons[0] if gate_reasons else None
            extracted_data = run.get("extracted_data")
            employees = (
                extracted_data.get("employees")
                if isinstance(extracted_data, dict)
                else None
            )
            # Mirror the SQL jsonb_typeof guard: only a real list counts; any
            # non-list/missing value degrades to 0 instead of raising.
            employee_count = len(employees) if isinstance(employees, list) else 0
            result.append(
                {
                    **run,
                    "business_name": biz_name,
                    "summary_gate_reason": summary_gate_reason,
                    "employee_count": employee_count,
                }
            )
        return result

    def load_business_name(self, business_id, conn=None):
        """Return business name for the given business_id (mirrors repo).

        Returns the seeded business name when available, else a safe fallback.
        """
        # Reverse-lookup the seeded contact_to_business map for a display name.
        # The seed stores businesses by contact_email key; we need a name lookup.
        # For in-memory tests, return a stable placeholder that is NOT the fallback
        # "Payroll Run" text — this lets regression tests verify real names are used.
        from app.db.seed import seed as _seed
        seeded = _seed(dry_run=True)
        for biz in seeded.businesses:
            if biz["id"] == business_id or str(biz["id"]) == str(business_id):
                return biz.get("name") or biz.get("contact_email", "Test Business")
        return "Test Business"

    def set_alias_candidates(self, run_id, candidates, conn=None):
        """MERGE alias candidates into the in-memory run dict (mirrors repo's
        JSONB `||` merge — not an overwrite). A confirmed bind for one token,
        written in an earlier round or an earlier call, must survive a later,
        unrelated candidate write for a DIFFERENT token."""
        run = self.runs.get(str(run_id))
        if run is not None:
            run["alias_candidates"] = {
                **(run.get("alias_candidates") or {}),
                **candidates,
            }

    def update_known_alias(self, employee_id, new_alias, conn=None):
        """Idempotently append new_alias to an in-memory Employee's known_aliases
        (mirrors repo.update_known_alias).

        Mutates the SAME seeded Employee object(s) held in
        self.business_employees so a later load_roster_for_business call (the
        batch-safe roster refresh inside _write_aliases_if_safe, and any
        subsequent real run) sees the newly-learned alias — this is the
        load-bearing seam that makes the full-loop stops-asking test's SECOND
        submission actually resolve via the stored alias. Employee is a frozen
        Pydantic model in this codebase's style (model_copy, never in-place
        field assignment) EXCEPT known_aliases is a plain list — the real
        repo mutates the DB row's TEXT[] column; here the equivalent is
        appending directly to the list object's contents (list.append does
        mutate in place, so the SAME Employee instance shared across every
        roster this test loads reflects the write immediately). Returns True
        if the alias was newly added, False if already present (idempotent).
        """
        for employees in self.business_employees.values():
            for emp in employees:
                if emp.id == employee_id:
                    if new_alias in emp.known_aliases:
                        return False
                    emp.known_aliases.append(new_alias)
                    return True
        return False

    def set_pre_clarify_extracted(self, run_id, extracted, conn=None):
        """Snapshot the pre-clarification extraction (write-once IS NULL guard).

        Mirrors repo.set_pre_clarify_extracted. Returns True on first write, False if
        already set (the IS NULL guard simulated by checking the current value). The
        snapshot must never be overwritten by a later round — it is the only record of
        what the client originally sent, and the carry-forward backfill reads from it.
        """
        run = self.runs.get(str(run_id))
        if run is None:
            return False
        if run.get("pre_clarify_extracted") is not None:
            return False  # already set (IS NULL guard)
        run["pre_clarify_extracted"] = (
            extracted.model_dump(mode="json") if hasattr(extracted, "model_dump") else extracted
        )
        return True

    def load_pre_clarify_extracted(self, run_id, conn=None):
        """Load the pre-clarification snapshot. Returns None if not set."""
        from app.models.contracts import Extracted
        run = self.runs.get(str(run_id))
        if run is None or run.get("pre_clarify_extracted") is None:
            return None
        data = run["pre_clarify_extracted"]
        return Extracted.model_validate(data)

    def set_clarified_fields(self, run_id, clarified, conn=None):
        """Write clarified_fields, validating the shape on the way in.

        Validates through ClarifiedFields before storing (mirrors repo behavior) so a
        malformed outcome map can never reach the JSONB column.
        """
        from app.models.contracts import ClarifiedFields
        ClarifiedFields(outcomes=clarified)  # typed-on-write: reject a bad shape here
        run = self.runs.get(str(run_id))
        if run is not None:
            run["clarified_fields"] = clarified

    def load_clarified_fields(self, run_id, conn=None):
        """Load clarified_fields. Returns {} on NULL."""
        run = self.runs.get(str(run_id))
        if run is None:
            return {}
        return run.get("clarified_fields") or {}

    def set_hours_changes(self, run_id, changes, conn=None):
        """Store the display-only cross-round hours changes (mirrors repo).

        Serialized exactly as the real JSONB write does (model_dump(mode="json")), so the
        run-detail template reads the SAME dict shape here as it does off a real row —
        otherwise this fake would let a template that only works against Pydantic objects
        pass, and the live page would break.
        """
        run = self.runs.get(str(run_id))
        if run is not None:
            run["hours_changes"] = [ch.model_dump(mode="json") for ch in changes]

    def get_clarification_round(self, run_id, conn=None):
        """Read the fake run's clarification_round key (mirrors repo).

        Returns 0 if the run is missing or the key is absent (Python dict default
        via .get, exactly like the real column's NOT NULL DEFAULT 0).
        """
        run = self.runs.get(str(run_id))
        if run is None:
            return 0
        return run.get("clarification_round", 0)

    def set_clarification_round(self, run_id, value, conn=None):
        """Write the fake run's clarification_round key (mirrors repo)."""
        run = self.runs.get(str(run_id))
        if run is not None:
            run["clarification_round"] = value

    def clear_reply_context(self, run_id, conn=None):
        """Null ALL reply-round context on the fake run (mirrors repo) and
        return the NEW reply_epoch.

        "Context lost means ALL of it": clarified_fields, pre_clarify_extracted,
        clarification_round, AND alias_candidates together — matches the real
        repo's single-statement clear, so a retrigger can never leave a
        provenance badge on the dashboard that outlives the data behind it.

        Also increments reply_epoch (default 0 via .get), mirroring the real
        repo's increment in the same statement: bumping the epoch is what
        makes prior-epoch replies invisible without deleting rows from the
        append-only email_messages log. Returning the incremented int (rather
        than None, as this used to) lets a caller key a retrigger's dedup_key
        on the fresh epoch without a separate read.
        """
        run = self.runs.get(str(run_id))
        if run is not None:
            run["clarified_fields"] = None
            run["pre_clarify_extracted"] = None
            run["clarification_round"] = 0
            run["alias_candidates"] = None
            # hours_changes IS reply-round context — it is a diff BETWEEN rounds, so a
            # record surviving a retrigger would show the operator a change belonging to a
            # conversation that no longer exists.
            run["hours_changes"] = None
            run["reply_epoch"] = run.get("reply_epoch", 0) + 1
            return run["reply_epoch"]
        return 0

    def rewind_for_reclaim(self, run_id, conn=None):
        """Mirror repo.rewind_for_reclaim: rewind a stranded run to RECEIVED
        without touching reply_epoch — the automatic reclaim path must never
        mint the same "send it again" licence a human retrigger grants
        itself. Scoped to exactly the same three statuses as the real repo
        function; returns True if the run was rewound, False otherwise.
        """
        run = self.runs.get(str(run_id))
        if run is None or run.get("status") not in ("extracting", "computed", "sent"):
            return False
        run["status"] = "received"
        run["clarified_fields"] = None
        run["pre_clarify_extracted"] = None
        run["clarification_round"] = 0
        run["alias_candidates"] = None
        run["hours_changes"] = None
        return True

    # --- durable job queue (in-memory mirror of app/db/repo/jobs.py) ---
    def enqueue_job(
        self,
        *,
        kind: Any,
        dedup_key: str,
        run_id: uuid.UUID | None = None,
        email_id: uuid.UUID | None = None,
        operator_resolution_id: uuid.UUID | None = None,
        business_id: uuid.UUID | None = None,
        max_attempts: int | None = None,
        available_in_seconds: float = 0.0,
        safe_last_error: str | None = None,
        conn: Any = None,
    ) -> uuid.UUID | None:
        """Mirror repo.enqueue_job's exact kind-specific identifier contracts.

        Validation happens before touching ``self.jobs``. A second enqueue with
        the same dedup key returns None, matching ON CONFLICT DO NOTHING.
        """
        from app.models.job import JobKind

        if not isinstance(kind, JobKind):
            raise ValueError(f"enqueue_job: unsupported job kind {kind!r}")
        kind_value = kind.value
        if kind is JobKind.RUN_PIPELINE and run_id is None:
            raise ValueError(
                f"enqueue_job: kind={kind.value!r} requires a run_id — a "
                "run_pipeline job with no run would be claimed and marked "
                "done without processing any payroll."
            )
        if kind is JobKind.RESUME_REPLY and (
            run_id is None or email_id is None or operator_resolution_id is not None
        ):
            raise ValueError(
                "enqueue_job: kind='resume_reply' requires run_id and email_id only"
            )
        if kind is JobKind.OPERATOR_RESUME and (
            run_id is None or operator_resolution_id is None or email_id is not None
        ):
            raise ValueError(
                "enqueue_job: kind='operator_resume' requires run_id and "
                "operator_resolution_id only"
            )
        if dedup_key in self._job_dedup_keys:
            return None
        jid = uuid.uuid4()
        self.jobs[str(jid)] = {
            "id": jid,
            "kind": kind_value,
            "dedup_key": dedup_key,
            "run_id": run_id,
            "email_id": email_id,
            "operator_resolution_id": operator_resolution_id,
            "business_id": business_id,
            "state": "pending",
            "attempts": 0,
            "max_attempts": max_attempts if max_attempts is not None else 5,
            "lease_token": None,
            "last_error": safe_last_error,
            "available_in_seconds": available_in_seconds,
            "safe_last_error": safe_last_error,
        }
        self._job_dedup_keys[dedup_key] = jid
        return jid

    def claim_job(self, *, lease_seconds=None, conn=None):
        """Mirror repo.claim_job: claims the first pending job (in-memory
        insertion order stands in for the real query's ORDER BY), stamping a
        fresh lease_token and incrementing attempts AT CLAIM."""
        from app.models.job import Job, JobKind

        for job in self.jobs.values():
            if job["state"] == "pending" and job["attempts"] < job["max_attempts"]:
                job["state"] = "leased"
                job["lease_token"] = uuid.uuid4()
                job["attempts"] += 1
                return Job(
                    id=job["id"],
                    kind=JobKind(job["kind"]),
                    run_id=job["run_id"],
                    email_id=job["email_id"],
                    operator_resolution_id=job["operator_resolution_id"],
                    attempts=job["attempts"],
                    max_attempts=job["max_attempts"],
                    lease_token=job["lease_token"],
                )
        return None

    def complete_job(self, job_id, lease_token, conn=None):
        """Mirror repo.complete_job: fenced on lease_token."""
        job = self.jobs.get(str(job_id))
        if job is None or job["state"] != "leased" or job["lease_token"] != lease_token:
            return False
        job["state"] = "done"
        job["lease_token"] = None
        return True

    def fail_job(self, job_id, lease_token, *, error, backoff_seconds, conn=None):
        """Mirror repo.fail_job: fenced on lease_token, dead-letters at
        max_attempts."""
        from app.models.job import JobState

        job = self.jobs.get(str(job_id))
        if job is None or job["state"] != "leased" or job["lease_token"] != lease_token:
            return None
        job["last_error"] = str(error)[:200]
        job["lease_token"] = None
        if job["attempts"] >= job["max_attempts"]:
            job["state"] = "dead"
        else:
            job["state"] = "pending"
        return JobState(job["state"])

    def enqueue_classified_retry(
        self,
        run_id,
        result,
        *,
        kind,
        email_id=None,
        available_in_seconds,
        conn=None,
    ):
        """Mirror the atomic first-attempt retry bridge."""
        from app.db.repo.job_settlement import SettlementOutcome
        from app.pipeline.result import PipelineOutcome

        if result.outcome is not PipelineOutcome.RETRYABLE:
            raise ValueError("enqueue_classified_retry requires a retryable result")
        run = self.runs.get(str(run_id))
        if run is None:
            return SettlementOutcome.FENCED
        epoch = run.get("reply_epoch", 0)
        suffix = f":{email_id}" if email_id is not None else ""
        dedup_key = f"{kind.value}:{run_id}:{epoch}{suffix}"
        existing_id = self._job_dedup_keys.get(dedup_key)
        if run["status"] == "received":
            if existing_id is None:
                return SettlementOutcome.FENCED
            existing = self.jobs[str(existing_id)]
            return (
                SettlementOutcome.RETRIED
                if existing["kind"] == kind.value
                and existing["run_id"] == run_id
                and existing["email_id"] == email_id
                else SettlementOutcome.FENCED
            )
        if run["status"] != "extracting":
            return SettlementOutcome.FENCED
        run["status"] = "received"
        self.enqueue_job(
            kind=kind,
            dedup_key=dedup_key,
            run_id=run_id,
            email_id=email_id,
            available_in_seconds=available_in_seconds,
            safe_last_error=result.diagnostic_code,
        )
        return SettlementOutcome.RETRIED

    def enqueue_operator_resume_retry(
        self,
        run_id,
        operator_resolution_id,
        result,
        *,
        available_in_seconds,
        conn=None,
    ):
        """Mirror the resolution-scoped identifier-only retry bridge."""
        from app.db.repo.job_settlement import SettlementOutcome
        from app.models.job import JobKind
        from app.pipeline.result import PipelineOutcome

        if result.outcome is not PipelineOutcome.RETRYABLE:
            raise ValueError("enqueue_operator_resume_retry requires a retryable result")
        try:
            self.load_operator_resume_resolution(run_id, operator_resolution_id)
        except ValueError:
            return SettlementOutcome.FENCED
        run = self.runs.get(str(run_id))
        if run is None:
            return SettlementOutcome.FENCED
        dedup_key = f"operator_resume:{run_id}:{operator_resolution_id}"
        existing_id = self._job_dedup_keys.get(dedup_key)
        if run["status"] == "received":
            if existing_id is None:
                return SettlementOutcome.FENCED
            existing = self.jobs[str(existing_id)]
            return (
                SettlementOutcome.RETRIED
                if existing["kind"] == JobKind.OPERATOR_RESUME.value
                and existing["run_id"] == run_id
                and existing["operator_resolution_id"] == operator_resolution_id
                else SettlementOutcome.FENCED
            )
        if run["status"] != "extracting":
            return SettlementOutcome.FENCED
        run["status"] = "received"
        self.enqueue_job(
            kind=JobKind.OPERATOR_RESUME,
            dedup_key=dedup_key,
            run_id=run_id,
            operator_resolution_id=operator_resolution_id,
            available_in_seconds=available_in_seconds,
            safe_last_error=result.diagnostic_code,
        )
        return SettlementOutcome.RETRIED

    def settle_pipeline_job(
        self,
        job: Any,
        result: Any,
        *,
        backoff_seconds: float,
        conn: Any = None,
    ) -> Any:
        """Mirror the fenced classified settlement matrix atomically."""
        from app.db.repo.job_settlement import SettlementOutcome
        from app.pipeline.result import PipelineOutcome

        row = self.jobs.get(str(job.id))
        if (
            row is None
            or row["state"] != "leased"
            or row["lease_token"] != job.lease_token
            or row["run_id"] != job.run_id
            or job.run_id is None
        ):
            return SettlementOutcome.FENCED
        run = self.runs.get(str(job.run_id))
        if run is None:
            return SettlementOutcome.FENCED
        if result.outcome is PipelineOutcome.OK:
            row["state"] = "done"
            row["lease_token"] = None
            return SettlementOutcome.DONE
        if run["status"] != "extracting":
            return SettlementOutcome.FENCED
        if result.outcome is PipelineOutcome.RETRYABLE and row["attempts"] < row["max_attempts"]:
            run["status"] = "received"
            row["state"] = "pending"
            row["last_error"] = result.diagnostic_code
            row["lease_token"] = None
            row["available_in_seconds"] = backoff_seconds
            return SettlementOutcome.RETRIED
        row["state"] = (
            "dead" if result.outcome is PipelineOutcome.RETRYABLE else "done"
        )
        row["last_error"] = result.diagnostic_code
        row["lease_token"] = None
        run["status"] = "error"
        if result.outcome is PipelineOutcome.RETRYABLE:
            run["error_reason"] = "RetryExhausted"
            run["error_detail"] = (
                f"{result.diagnostic_code};attempts={row['attempts']}/{row['max_attempts']}"
            )[:200]
            return SettlementOutcome.DEAD
        run["error_reason"] = result.reason.value
        run["error_detail"] = result.diagnostic_code
        return SettlementOutcome.DONE

    def settle_background_terminal(
        self, run_id, result, *, expected_status=None, conn=None
    ):
        """Mirror terminal settlement for a BackgroundTask with no job."""
        from app.db.repo.job_settlement import SettlementOutcome
        from app.pipeline.result import PipelineOutcome

        if result.outcome is not PipelineOutcome.TERMINAL:
            raise ValueError("settle_background_terminal requires a terminal result")
        run = self.runs.get(str(run_id))
        expected_value = (
            expected_status.value if expected_status is not None else "extracting"
        )
        if run is None or run["status"] != expected_value:
            return SettlementOutcome.FENCED
        run["status"] = "error"
        run["error_reason"] = result.reason.value
        run["error_detail"] = result.diagnostic_code
        return SettlementOutcome.DONE

    def settle_infrastructure_failure(
        self,
        job,
        *,
        backoff_seconds,
        stage=None,
        reason=None,
        conn=None,
    ):
        """Mirror bounded infrastructure settlement without exception text."""
        from app.pipeline.result import (
            PipelineOutcome,
            PipelineReason,
            PipelineResult,
            PipelineStage,
        )

        return self.settle_pipeline_job(
            job,
            PipelineResult(
                outcome=PipelineOutcome.RETRYABLE,
                stage=stage or PipelineStage.UNKNOWN,
                reason=reason or PipelineReason.UNCLASSIFIED,
            ),
            backoff_seconds=backoff_seconds,
        )

    def reap_expired_final_attempt(self, *, conn=None):
        """Mirror one exact expired final-attempt lease settlement."""
        from app.db.repo.job_settlement import (
            _FINAL_LEASE_ERROR_STATUSES,
            _FINAL_LEASE_PRESERVE_STATUSES,
            SettlementOutcome,
        )
        from app.models.status import RunStatus

        candidates = [
            (index, row)
            for index, row in enumerate(self.jobs.values())
            if row["state"] == "leased"
            and row["attempts"] == row["max_attempts"]
            and row.get("lease_expired") is True
        ]
        candidates.sort(
            key=lambda candidate: candidate[1].get(
                "leased_until_order", candidate[0]
            )
        )
        for _index, row in candidates:
            run = self.runs.get(str(row["run_id"]))
            if run is None:
                return SettlementOutcome.FENCED
            run_status = RunStatus(run["status"])
            if run_status in _FINAL_LEASE_ERROR_STATUSES:
                run["status"] = RunStatus.ERROR.value
                run["error_reason"] = "FinalAttemptLeaseExpired"
                run["error_detail"] = (
                    "unknown:final_attempt_lease_expired;"
                    f"attempts={row['attempts']}/{row['max_attempts']}"
                )[:200]
            else:
                assert run_status in _FINAL_LEASE_PRESERVE_STATUSES
            row["state"] = "dead"
            row["lease_token"] = None
            row["leased_until"] = None
            return SettlementOutcome.REAPED_FINAL_LEASE
        return None

    def release_leases(self, lease_tokens, conn=None):
        """Mirror repo.release_leases: flips every leased row holding one of
        lease_tokens back to pending; returns the count."""
        count = 0
        for job in self.jobs.values():
            if job["state"] == "leased" and job["lease_token"] in lease_tokens:
                job["state"] = "pending"
                job["lease_token"] = None
                count += 1
        return count

    def get_job(self, job_id, conn=None):
        """Mirror repo.get_job: a plain single-row read."""
        return self.jobs.get(str(job_id))

    def get_record_only_flag(self, run_id, conn=None):
        """Return the record_only flag for a run (mirrors repo.get_record_only_flag).

        Returns False if the run is not found (safe default: live Resend path).
        All in-memory runs default to record_only=False (they are created via the
        webhook / demo_send_test path, not the compose path).
        """
        run = self.runs.get(str(run_id))
        if run is None:
            return False
        return bool(run.get("record_only", False))

    def load_thread_messages(self, run_id, conn=None):
        """Return thread messages for a run (mirrors repo.load_thread_messages).

        For in-memory tests, returns an empty list (no email rows are tracked at this
        granularity). Tests that need thread messages should monkeypatch directly.
        """
        return []

    def list_businesses(self, conn=None):
        """Return all businesses (mirrors repo.list_businesses).

        For in-memory tests, returns the seeded businesses list.
        """
        from app.db.seed import seed as _seed
        seeded = _seed(dry_run=True)
        return [
            {"id": str(b["id"]), "name": b["name"], "contact_email": b["contact_email"]}
            for b in seeded.businesses
        ]

    def get_demo_binding(self, operator_email, conn=None):
        """Return None (no demo bindings in the in-memory store)."""
        return None

    def bind_demo_business(self, business_name, operator_email, seed_business_ids, conn=None):
        """No-op in-memory bind; returns True for any known business_name."""
        return business_name in seed_business_ids

    # --- email / threading (the outbound Message-ID anchor) ---
    def insert_email_message(self, *, run_id, direction, message_id, conn=None, round=0, **kw):
        """Mirror repo.insert_email_message, including the round-aware upsert.

        The real repo upserts outbound purpose rows on (run_id, purpose, round) —
        a retry WITHIN a round advances send_state/message_id in place, but a NEW
        round always appends a NEW row, so prior-round history is never
        upsert-replaced. `round` defaults to 0 so callers that do not pass it
        behave exactly like the older (run_id, purpose) upsert key.

        The OUTBOUND path also stamps epoch from the target run's CURRENT
        reply_epoch at write time (mirrors repo's correlated subquery in the
        INSERT). The upsert key is (purpose, round, epoch), matching the
        uq_email_run_purpose_round_epoch constraint and repo's ON CONFLICT
        arbiter: a retriggered run's fresh round-0 send lands in a new epoch and
        must APPEND a new row, never upsert-mutate the stale pre-retrigger
        round-0 row from the prior epoch.
        """
        purpose = kw.get("purpose")
        run = self.runs.get(str(run_id)) if run_id is not None else None
        row = {
            "run_id": run_id,
            "direction": direction,
            "message_id": message_id,
            "round": round,
            "consumed_round": None,
            "created_at": datetime.now(UTC),
            **kw,
        }
        if direction == "outbound" and run_id is not None:
            epoch = run.get("reply_epoch", 0) if run is not None else 0
            row["epoch"] = epoch
            rows = self.outbound.setdefault(str(run_id), [])
            if purpose is not None:
                # Upsert key: (run_id, purpose, round, epoch) — mirrors the
                # uq_email_run_purpose_round_epoch constraint.
                for existing in rows:
                    if (
                        existing.get("purpose") == purpose
                        and existing.get("round") == round
                        and existing.get("epoch", 0) == epoch
                    ):
                        existing.update(row)
                        return uuid.uuid4()
            rows.append(row)
        return uuid.uuid4()

    def get_outbound_message_id(self, run_id, purpose=None, conn=None):
        """Purpose-aware outbound Message-ID lookup (mirrors repo.get_outbound_message_id).

        When purpose is provided, filters by purpose to match the real repo's behavior.
        When purpose is None (legacy test calls without purpose arg), returns the last
        outbound row for the run — this keeps callers that only assert an outbound
        row exists (not which purpose) working unchanged.
        """
        rows = self.outbound.get(str(run_id))
        if not rows:
            return None
        if purpose is not None:
            # Filter to rows with matching purpose and send_state='sent' (mirrors real repo)
            matching = [
                r for r in rows
                if r.get("purpose") == purpose and r.get("send_state") == "sent"
            ]
            return matching[-1]["message_id"] if matching else None
        return rows[-1]["message_id"]

    def get_outbound_for_round(self, run_id, purpose, round, conn=None):
        """Round-aware sibling of get_outbound_message_id (mirrors repo).

        Filters direction (implicit — only self.outbound rows are stored),
        purpose, send_state='sent', AND round; returns {"message_id", "round"}
        (not just the message_id) so a caller derives the next round from the
        FOUND row rather than a blind +1 off a counter that may have drifted.

        Also filters on row.get("epoch", 0) == the run's CURRENT reply_epoch,
        mirroring repo's correlated subquery scope: a prior-epoch send must never
        satisfy the idempotency check for the current epoch's question.
        """
        rows = self.outbound.get(str(run_id))
        if not rows:
            return None
        run = self.runs.get(str(run_id))
        current_epoch = run.get("reply_epoch", 0) if run is not None else 0
        matching = [
            r
            for r in rows
            if r.get("purpose") == purpose
            and r.get("send_state") == "sent"
            and r.get("round") == round
            and r.get("epoch", 0) == current_epoch
        ]
        if not matching:
            return None
        found = matching[-1]
        return {"message_id": found["message_id"], "round": found.get("round", 0)}

    def get_unconfirmed_outbound(self, run_id, *, purpose, round=0, conn=None):
        """Epoch-scoped unconfirmed-reservation read (mirrors repo.get_unconfirmed_outbound).

        Complementary to get_outbound_for_round: filters on send_state IN
        ('reserved', 'failed') instead of == 'sent', so it answers "might this
        already have reached the client?" rather than "was this proven sent?".
        Same purpose ValueError guard and same epoch scoping against the run's
        CURRENT reply_epoch as get_outbound_for_round — a prior-epoch reservation
        (a human retrigger has since bumped the epoch) must be invisible here,
        which is what lets an operator recover an escalated run.
        """
        if purpose not in ("clarification", "confirmation", "clarification_field_regression"):
            raise ValueError(
                "purpose must be 'clarification', 'confirmation', or "
                f"'clarification_field_regression', got {purpose!r}"
            )
        rows = self.outbound.get(str(run_id))
        if not rows:
            return None
        run = self.runs.get(str(run_id))
        current_epoch = run.get("reply_epoch", 0) if run is not None else 0
        matching = [
            r
            for r in rows
            if r.get("purpose") == purpose
            and r.get("round") == round
            and r.get("epoch", 0) == current_epoch
            and r.get("send_state") in ("reserved", "failed")
        ]
        if not matching:
            return None
        found = matching[-1]
        return {
            "message_id": found["message_id"],
            "send_state": found.get("send_state"),
            "round": found.get("round", 0),
            "created_at": found.get("created_at"),
        }

    def mark_reply_consumed(self, message_id, round, conn=None):
        """Write-once consumed_round marker on the matching inbound row.

        Mirrors the real repo's `consumed_round IS NULL` write-once guard: a
        second call for an already-consumed message_id is a no-op, so a
        redelivered reply can never be consumed twice.
        """
        row = self.emails.get(message_id)
        if (
            row is not None
            and row.get("direction") == "inbound"
            and row.get("consumed_round") is None
        ):
            row["consumed_round"] = round

    def load_consumed_replies(self, run_id, conn=None):
        """Return consumed inbound replies for a run, round-ordered.

        Mirrors repo.load_consumed_replies: filters inbound + consumed_round is
        not None, sorted by consumed_round ascending.

        Also filters on row.get("epoch", 0) == the run's CURRENT reply_epoch,
        mirroring repo's correlated subquery scope. A stale consumed reply from a
        pre-retrigger epoch is invisible here even though the row is never
        deleted — the audit log stays append-only, but its stale rows must not
        leak into the accumulated reply context.
        """
        run = self.runs.get(str(run_id))
        current_epoch = run.get("reply_epoch", 0) if run is not None else 0
        matching = [
            row
            for row in self.emails.values()
            if row.get("direction") == "inbound"
            and row.get("consumed_round") is not None
            and row.get("epoch", 0) == current_epoch
            and (
                str(row.get("run_id")) == str(run_id)
                if row.get("run_id") is not None
                else False
            )
        ]
        return sorted(matching, key=lambda r: r["consumed_round"])

    def get_inbound_by_message_id(self, message_id, conn=None):
        """Return the stored inbound row dict, or None (mirrors repo).

        The redelivery path must read the PERSISTED row: this fake returns exactly
        what insert_inbound_email stored, never a freshly-built InboundEmail from
        the redelivered request — otherwise a redelivery would resurrect a reply
        the DB has already marked consumed.
        """
        row = self.emails.get(message_id)
        if row is None or row.get("direction") != "inbound":
            return None
        return row

    def get_inbound_email_by_id(self, email_id, conn=None):
        """Return one stored inbound row by its durable UUID."""
        self.context_calls.append(("get_inbound_email_by_id", str(email_id)))
        row = self.email_by_id.get(str(email_id))
        if row is None or row.get("direction") != "inbound":
            return None
        return dict(row)

    def create_operator_resume_resolution(
        self, run_id, operator_resolution_id, overrides, conn=None
    ):
        """Store one immutable validated mapping with exact-id idempotency."""
        from app.db.repo.operator_resume_resolutions import _normalize_overrides, _uuid_text

        run_id_text = _uuid_text(run_id, "run_id")
        resolution_id_text = _uuid_text(
            operator_resolution_id, "operator_resolution_id"
        )
        normalized = _normalize_overrides(overrides)
        self.context_calls.append(
            (
                "create_operator_resume_resolution",
                run_id_text,
                resolution_id_text,
                dict(normalized),
            )
        )
        key = (resolution_id_text, run_id_text)
        conflicting_keys = [
            stored_key
            for stored_key in self.operator_resume_resolutions
            if stored_key[0] == resolution_id_text and stored_key != key
        ]
        if conflicting_keys:
            raise ValueError("conflicting operator resolution identifier")
        existing = self.operator_resume_resolutions.get(key)
        if existing is not None and existing != normalized:
            raise ValueError("conflicting operator resolution mapping")
        self.operator_resume_resolutions[key] = dict(normalized)

    def load_operator_resume_resolution(
        self,
        run_id: uuid.UUID,
        operator_resolution_id: uuid.UUID,
        conn: Any = None,
    ) -> dict[str, str]:
        """Return a defensive copy of one exact run/resolution mapping."""
        from app.db.repo.operator_resume_resolutions import _uuid_text

        key = (
            _uuid_text(operator_resolution_id, "operator_resolution_id"),
            _uuid_text(run_id, "run_id"),
        )
        self.context_calls.append(
            ("load_operator_resume_resolution", key[1], key[0])
        )
        stored = self.operator_resume_resolutions.get(key)
        if not stored:
            raise ValueError("operator resume resolution is missing")
        return dict(stored)

    # --- crash-safe send ordering + durable threading ---
    def get_outbound_references_chain(self, run_id, conn=None):
        """Return the references_header of the most recent sent outbound for this run.

        Mirrors repo.get_outbound_references_chain: the References chain is rebuilt
        from the DB, not from in-process state, so threading survives a restart.
        Returns None if no sent outbound row exists.
        """
        rows = self.outbound.get(str(run_id))
        if not rows:
            return None
        sent = [r for r in rows if r.get("send_state") == "sent"]
        if not sent:
            return None
        return sent[-1].get("references_header")

    def update_email_message_sent(self, message_id, conn=None):
        """Flip send_state to 'sent' for the outbound row with this synthetic message_id.

        Mirrors repo.update_email_message_sent (the success half of the crash-safe
        write-then-send ordering).
        """
        self.update_email_message_state(message_id, "sent", conn=conn)

    def update_email_message_state(
        self, message_id: str, state: str, conn: Any = None
    ) -> None:
        """Set send_state on the outbound row with this synthetic message_id.

        Mirrors repo.update_email_message_state: the row is written BEFORE the
        send is attempted, then flipped, so a crash mid-send leaves a visible
        pending row rather than an invisible lost email.
        """
        for rows in self.outbound.values():
            for row in rows:
                if row.get("message_id") == message_id:
                    row["send_state"] = state
                    return

    # --- header-chain reply routing ---
    def _header_matches(
        self,
        in_reply_to: str | None,
        references_header: str | None,
        row: dict[str, Any],
    ) -> bool:
        """Mirror the repo SQL: outbound Message-ID == in_reply_to OR is a WHOLE
        whitespace-bounded token in References. It must not be a bare substring
        match, or `<a@x>` would match inside `<a@xtra>` and route a reply to the
        wrong run."""
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
        """The SAME header match across ANY status (late-reply observability)."""
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
        "load_business_name",
        "set_status",
        "claim_status",
        "record_run_error",
        "persist_extracted",
        "persist_decision",
        "persist_reconciliation",
        "replace_line_items",
        "load_line_items",
        "load_all_runs",
        "set_alias_candidates",
        "update_known_alias",
        "insert_email_message",
        "get_outbound_message_id",
        "find_awaiting_reply_for_header",
        "find_any_run_for_header",
        # record_only + demo routing helpers
        "get_record_only_flag",
        "load_thread_messages",
        "list_businesses",
        "get_demo_binding",
        "bind_demo_business",
        # crash-safe send ordering + durable threading
        "get_outbound_references_chain",
        "update_email_message_sent",
        "update_email_message_state",
        # field-regression snapshot + clarified_fields outcomes
        "set_pre_clarify_extracted",
        "load_pre_clarify_extracted",
        "set_clarified_fields",
        "load_clarified_fields",
        # display-only cross-round hours changes. NOTE the `if hasattr(store, name)` guard
        # below: a method defined on InMemoryRepo but MISSING from this tuple is simply
        # never patched in — no AttributeError, no failure, just a silent fall-through to
        # the real DB-backed repo. Adding the method is not enough; it must be named here.
        "set_hours_changes",
        # webhook-dedup loser lookup
        "find_run_by_message_id",
        # reply/late-reply rows linked to their run
        "link_email_to_run",
        # clarification round-machine data-layer primitives
        "get_clarification_round",
        "set_clarification_round",
        "get_outbound_for_round",
        "get_unconfirmed_outbound",
        "mark_reply_consumed",
        "load_consumed_replies",
        "get_inbound_by_message_id",
        "get_inbound_email_by_id",
        "create_operator_resume_resolution",
        "load_operator_resume_resolution",
        "clear_reply_context",
        # automatic-reclaim rewind (never bumps reply_epoch) + the durable
        # job queue's claim/lease/fencing surface. A method defined on
        # InMemoryRepo but missing from THIS tuple is silently never
        # patched — see tests/test_fake_repo_pairing.py, which makes that
        # class of miss impossible to reintroduce.
        "rewind_for_reclaim",
        "enqueue_job",
        "claim_job",
        "complete_job",
        "fail_job",
        "release_leases",
        "get_job",
        "enqueue_classified_retry",
        "enqueue_operator_resume_retry",
        "settle_pipeline_job",
        "settle_background_terminal",
        "settle_infrastructure_failure",
        "reap_expired_final_attempt",
    ):
        if hasattr(store, name):
            monkeypatch.setattr(repo_mod, name, getattr(store, name), raising=False)

    # Patch app.db.repo.get_connection to a FakeConnection-backed context manager
    # so `with repo.get_connection() as conn: with conn.transaction(): ...` code
    # runs against the offline double instead of opening a real Supabase pool.
    monkeypatch.setattr(repo_mod, "get_connection", _fake_get_connection, raising=False)

    # Patch resend.Emails.send to a no-op in the mocked test context so that
    # pipeline tests (fake_repo) do not attempt real Resend API calls.
    # Tests that need to assert send behavior use the explicit mock_resend_send fixture
    # (or monkeypatch resend.Emails.send directly) — this default no-op just prevents
    # pool-connection errors from send_outbound calling resend without a live key.
    monkeypatch.setattr(
        resend.Emails,
        "send",
        staticmethod(lambda params: {"id": "fake-resend-id"}),
        raising=True,
    )

    return store


# ---------------------------------------------------------------------------
# 5. mock_llm — script the OpenAI client so stages run with no network
# ---------------------------------------------------------------------------


class _MockMessage:
    def __init__(self, content: Any) -> None:
        self.content = content


class _MockChoice:
    def __init__(self, content: Any) -> None:
        self.message = _MockMessage(content)


class _MockResponse:
    def __init__(self, content: Any) -> None:
        self.choices = [_MockChoice(content)]


class _MockCompletions:
    def __init__(self, parent: type[MockOpenAI]) -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _MockResponse:
        self._parent.calls.append(kwargs)
        content = self._parent.script.pop(0) if self._parent.script else "{}"
        return _MockResponse(content)


class _MockChat:
    def __init__(self, parent: type[MockOpenAI]) -> None:
        self.completions = _MockCompletions(parent)


class MockOpenAI:
    """A scriptable OpenAI stand-in shared across all client instances.

    Because app.llm.client constructs a fresh OpenAI() per call, the script is a
    class-level FIFO queue so sequential stage calls (extract → decide) each pop
    the next scripted JSON string in order.
    """

    script: list[Any] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, *, base_url: Any = None, api_key: Any = None, **_: Any) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.chat = _MockChat(MockOpenAI)


@pytest.fixture
def mock_llm(monkeypatch):
    """Patch app.llm.client.OpenAI with a class-level FIFO script.

    Returns the MockOpenAI class; set `mock_llm.script = [json1, json2, ...]` to
    enqueue the structured responses sequential stage calls will consume.

    Also stubs DATABASE_URL so get_settings() does not raise ValidationError in
    test environments that lack a .env file (worktrees, bare CI, etc.). The stub
    value is never used for actual DB access — the fake_repo fixture fully patches
    all repo calls so no psycopg connection is ever opened in the mocked suite.
    The lru_cache on get_settings() is cleared before and after so per-test env
    edits take effect cleanly (mirrors test_llm_client.py's clear_settings_cache).
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    MockOpenAI.script = []
    MockOpenAI.calls = []
    monkeypatch.setattr("app.llm.client.OpenAI", MockOpenAI)
    yield MockOpenAI
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 6. seed_roster — Roster with the David+Daniel Reyes collision pair
# ---------------------------------------------------------------------------


@pytest.fixture
def seed_roster() -> Roster:
    """A Roster built from Business 2 seed data, which contains the
    David Reyes / Daniel Reyes collision pair.

    Both David Reyes (e0000003) and Daniel Reyes (e0000007) carry
    known_aliases=["D. Reyes"], so submitting "D. Reyes" always gates to
    request_clarification: a name that could be two people on the roster is never
    resolved, because resolving it would guess with someone's money.
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


# ---------------------------------------------------------------------------
# 7. Resend SDK mock fixtures — offline seams for the gateway tests
# ---------------------------------------------------------------------------


class _FakeResendReceivedEmail:
    """Minimal stand-in for resend.ReceivedEmail.

    Mirrors the shape returned by resend.EmailsReceiving.get(email_id):
      - message_id (str): the RFC Message-ID
      - text (str | None): plain-text body
      - html (str | None): HTML body
      - headers (dict): flat key->value; keys may be mixed-case per provider

    The `headers` dict uses mixed-case keys matching real provider output, so tests
    exercise the case-insensitive header extraction path — a case-sensitive lookup
    would silently drop In-Reply-To and break reply threading.
    """

    def __init__(
        self,
        *,
        message_id: str = "<test-recv@resend.test>",
        text: str | None = "Maria 40 hours",
        html: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> None:
        self.message_id = message_id
        self.text = text
        self.html = html
        # Default: mixed-case keys, to exercise the header-normalization path.
        self.headers: dict[str, Any] = headers if headers is not None else {
            "In-Reply-To": "<prev@x.test>",
            "References": "<prev@x.test>",
            "Subject": "Payroll hours",
        }


@pytest.fixture
def fake_received_email() -> _FakeResendReceivedEmail:
    """A minimal resend.ReceivedEmail stand-in with mixed-case header keys.

    Real providers do not normalize header key casing, so this fixture keeps the
    case-insensitive extraction path under test.
    """
    return _FakeResendReceivedEmail()


@pytest.fixture
def mock_resend_verify(monkeypatch):
    """Monkeypatch resend.Webhooks.verify to a no-op (always passes).

    Returns None (the real SDK's success return value) so the code under test
    sees a valid signature and proceeds. Use this for the happy-path gateway tests.
    """
    def _noop_verify(payload_dict):
        return None  # resend.Webhooks.verify returns None on success

    monkeypatch.setattr(resend.Webhooks, "verify", staticmethod(_noop_verify))
    return _noop_verify


@pytest.fixture
def mock_resend_verify_reject(monkeypatch):
    """Monkeypatch resend.Webhooks.verify to always raise ValueError('bad sig').

    Use this for the signature-rejection path — the route must return 400 and abort
    before any pipeline work when verify raises, so an unsigned payload can never
    create a run.
    """
    def _reject_verify(payload_dict):
        raise ValueError("bad sig")

    monkeypatch.setattr(resend.Webhooks, "verify", staticmethod(_reject_verify))
    return _reject_verify


@pytest.fixture
def mock_resend_send(monkeypatch):
    """Monkeypatch resend.Emails.send to return a fake send response without hitting the network.

    Returns {"id": "<out-test@resend.com>"} — the shape the real SDK returns on success.
    Captures all calls in a list for assertion in tests.
    """
    calls: list[dict[str, Any]] = []

    def _fake_send(params: dict[str, Any]) -> dict[str, str]:
        calls.append(params)
        return {"id": "<out-test@resend.com>"}

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_fake_send))
    # Return the calls list so tests can assert call count and params.
    return calls
