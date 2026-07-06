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

import contextlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

# Phase 6 Resend SDK mocks — added 06-01
import resend  # noqa: F401 — imported so the module is available for monkeypatching

from app.models.contracts import InboundEmail
from app.models.roster import Roster


# ---------------------------------------------------------------------------
# 0. Live-DB two-factor guard + shared seeded_db fixture (Finding #10)
#
# Live-DB integration tests require BOTH DATABASE_URL (a reachable DB) AND
# ALLOW_DB_RESET=1 (explicit opt-in to the destructive bootstrap --reset). This
# fixture and the guard constants were copy-pasted into test_seed_roundtrip.py,
# test_gateway.py, and test_persistence.py; they are promoted here so every test
# module — including test_dashboard.py's /health/ready check — shares ONE
# definition (DRY). Module scope means each test module still resets+seeds once.
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


@contextlib.contextmanager
def _fake_get_connection():
    """Context manager double for app.db.repo.get_connection (09-01, D-9-03).

    Patched onto app.db.repo.get_connection by the fake_repo fixture below so
    that `with repo.get_connection() as conn: with conn.transaction(): ...`
    code (the seam every Wave 2 orchestrator/main.py plan wires in) runs
    against a FakeConnection instead of opening a real Supabase pool. Without
    this seam the very first such block added anywhere would make every
    fake_repo-driven test try to open a live connection and fail/hang.
    """
    yield FakeConnection()


def patch_get_connection(monkeypatch, repo_mod) -> None:
    """Monkeypatch repo_mod.get_connection to the FakeConnection double (09-02).

    For tests that monkeypatch individual app.db.repo.* helpers directly
    (rather than using the fake_repo fixture) and call orchestrator functions
    that now open `with repo.get_connection() as conn: with conn.transaction():`
    blocks (09-02 D-9-04..D-9-08 transaction wiring) — without this patch such
    a test would attempt to open a real pooled Supabase connection and hang /
    time out. Call this once per test alongside the other repo_mod monkeypatches.
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


# Mirrors app.db.repo._STRANDED_SCOPE_STATUSES (09-01, D-9-12 scope pin) — kept
# as a separate local constant (not imported) so this fake never silently
# inherits a scope change without a corresponding InMemoryRepo test failure.
_STRANDED_SCOPE_STATUSES = ["received", "extracting", "computed"]


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
        # Phase 11 (D-11-01/02): every fake email row carries direction (real
        # insert_inbound_email always inserts 'inbound' — the real SQL hardcodes
        # it, so kw never actually passes it), round (default 0), and
        # consumed_round (default None, meaning unconsumed), so
        # find_stranded_unconsumed_replies / load_consumed_replies /
        # mark_reply_consumed / get_inbound_by_message_id can read/write these
        # exactly like the real repo does on the real email_messages columns.
        row = {
            "id": eid,
            "direction": "inbound",
            "round": 0,
            "consumed_round": None,
            "created_at": datetime.now(timezone.utc),
            **kw,
        }
        self.emails[mid] = row
        self.email_by_id[str(eid)] = row
        return eid, True

    def find_business_by_sender(self, from_addr, conn=None):
        return self.contact_to_business.get(from_addr)

    def link_email_to_run(self, email_id, run_id, conn=None):
        """Mirror repo.link_email_to_run (WR-03 phase-9 review fix).

        Back-fills run_id on an already-inserted inbound row once the ingest
        transaction classifies it as reply_candidate/late_reply, so tests can
        assert real reply rows are linked to their run like the demo path.

        GAP-2/GAP-3 (11-06): also stamps the linked row's epoch key from the
        CURRENT reply_epoch of the target run at link time (mirrors repo's
        correlated subquery). Defaults to 0 via .get for both sides so a run
        or row that predates the epoch mechanism behaves exactly like a real
        NOT NULL DEFAULT 0 column.
        """
        row = self.email_by_id.get(str(email_id))
        if row is not None:
            row["run_id"] = run_id
            run = self.runs.get(str(run_id))
            row["epoch"] = run.get("reply_epoch", 0) if run is not None else 0

    def find_run_by_message_id(self, message_id, conn=None):
        """Mirror repo.find_run_by_message_id (09-01, DATA-02 dedup-loser lookup).

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

    def create_run(self, *, business_id, source_email_id, pay_period_start=None,
                   pay_period_end=None, record_only=False, conn=None):
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
            # Phase 11 (D-11-01): every run starts at round 0, matching the real
            # column's NOT NULL DEFAULT 0 — old code never sets this key.
            "clarification_round": 0,
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

    def sweep_stranded_runs(self, threshold_seconds, conn=None):
        """Mirror repo.sweep_stranded_runs (09-01, D-9-10/11/12 recovery sweep).

        Scope is hardcoded to EXACTLY {received, extracting, computed} — matches
        the real repo's scope-pin. error_detail is built from the same static
        prefix concatenated with the run's OWN pre-mutation status value,
        mirroring the real SQL's `%s || status` concatenation semantics (not a
        Python `{status}` placeholder). This in-memory double has no real
        `updated_at` age check — it sweeps every run currently in scope,
        since tests script exactly the runs they want swept.
        """
        from app.models.status import RunStatus

        swept: list[uuid.UUID] = []
        prefix = "recovery: stranded in-flight (background task died) — swept from "
        for run_id_str, run in self.runs.items():
            if run["status"] in _STRANDED_SCOPE_STATUSES:
                old_status = run["status"]
                run["error_reason"] = "StrandedRunSwept"
                run["error_detail"] = prefix + old_status
                run["status"] = RunStatus.ERROR.value
                swept.append(run["id"])
        return swept

    def record_run_error(
        self, run_id, reason, conn=None, *, detail_exc=None, stage=None, roster=None
    ):
        from app.db.repo import _TERMINAL_STATUSES
        from app.models.status import RunStatus

        # Mirror the real repo's WR-04 guard: never clobber a terminal run to ERROR.
        if self.runs[str(run_id)]["status"] in _TERMINAL_STATUSES:
            return
        self.runs[str(run_id)]["error_reason"] = reason
        # OPS2-01: mirrors the real repo.record_run_error's new keyword-only-extras
        # shape (conn stays positional-compatible) so orchestrator.py/main.py call
        # sites that pass detail_exc=/stage=/roster= don't raise TypeError against
        # this fake. The real scrub logic is unit-tested against the real
        # repo.record_run_error in Plan 08-02 — this fake only needs to not error.
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

        Review fix #7: also computes the SQL-computed `summary_gate_reason` /
        `employee_count` aliases the real repo.load_all_runs (Plan 08-02) now
        projects, so route-level tests that swap in InMemoryRepo keep exercising
        the real runs_list.html alias contract instead of silently falling
        through to the template's `--` else-branch.
        """
        result = []
        for run in self.runs.values():
            biz_name = "Test Business"
            decision = run.get("decision")
            gate_reasons = (decision or {}).get("gate_reasons") if isinstance(decision, dict) else None
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
        """Return business name for the given business_id (CR-03 fix, mirrors repo).

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
        """Store alias candidates in the in-memory run dict (D-04, mirrors repo)."""
        run = self.runs.get(str(run_id))
        if run is not None:
            run["alias_candidates"] = candidates

    def update_known_alias(self, employee_id, new_alias, conn=None):
        """Idempotently append new_alias to an in-memory Employee's known_aliases
        (D-01, mirrors repo.update_known_alias — Phase 11 Plan 04, D-11-17).

        Mutates the SAME seeded Employee object(s) held in
        self.business_employees so a later load_roster_for_business call (the
        BATCH-SAFE roster refresh inside _write_aliases_if_safe, and any
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
        """Snapshot pre-clarify extracted (IS NULL write-once guard, D-19 MONEY-03).

        Mirrors repo.set_pre_clarify_extracted. Returns True on first write, False if
        already set (in-memory IS NULL guard simulated by checking current value).
        """
        run = self.runs.get(str(run_id))
        if run is None:
            return False
        if run.get("pre_clarify_extracted") is not None:
            return False  # already set (IS NULL guard)
        run["pre_clarify_extracted"] = extracted.model_dump(mode="json") if hasattr(extracted, "model_dump") else extracted
        return True

    def load_pre_clarify_extracted(self, run_id, conn=None):
        """Load pre-clarify snapshot (D-19 MONEY-03). Returns None if not set."""
        from app.models.contracts import Extracted
        run = self.runs.get(str(run_id))
        if run is None or run.get("pre_clarify_extracted") is None:
            return None
        data = run["pre_clarify_extracted"]
        return Extracted.model_validate(data)

    def set_clarified_fields(self, run_id, clarified, conn=None):
        """Write clarified_fields (D-13 MONEY-03, D-7.5-03b typed-on-write).

        Validates through ClarifiedFields before storing (mirrors repo behavior).
        """
        from app.models.contracts import ClarifiedFields
        ClarifiedFields(outcomes=clarified)  # D-7.5-03b: validate on write
        run = self.runs.get(str(run_id))
        if run is not None:
            run["clarified_fields"] = clarified

    def load_clarified_fields(self, run_id, conn=None):
        """Load clarified_fields (D-13 MONEY-03). Returns {} on NULL."""
        run = self.runs.get(str(run_id))
        if run is None:
            return {}
        return run.get("clarified_fields") or {}

    def get_clarification_round(self, run_id, conn=None):
        """Read the fake run's clarification_round key (D-11-01, mirrors repo).

        Returns 0 if the run is missing or the key is absent — matches create_run
        below, which does not set the key (Python dict default via .get, exactly
        like the real column's NOT NULL DEFAULT 0).
        """
        run = self.runs.get(str(run_id))
        if run is None:
            return 0
        return run.get("clarification_round", 0)

    def set_clarification_round(self, run_id, value, conn=None):
        """Write the fake run's clarification_round key (D-11-01, mirrors repo)."""
        run = self.runs.get(str(run_id))
        if run is not None:
            run["clarification_round"] = value

    def clear_reply_context(self, run_id, conn=None):
        """Null ALL reply-round context on the fake run (D-11-04, mirrors repo).

        "Context lost means ALL of it": clarified_fields, pre_clarify_extracted,
        clarification_round, AND alias_candidates together — matches the real
        repo's single-statement clear so a hermetic retrigger test can assert
        every one of these was actually reset, not just some of them.

        GAP-2/GAP-3 (11-06): also increments reply_epoch (default 0 via .get)
        on the fake run dict, mirroring the real repo's `reply_epoch =
        reply_epoch + 1` in the same statement.
        """
        run = self.runs.get(str(run_id))
        if run is not None:
            run["clarified_fields"] = None
            run["pre_clarify_extracted"] = None
            run["clarification_round"] = 0
            run["alias_candidates"] = None
            run["reply_epoch"] = run.get("reply_epoch", 0) + 1

    def get_record_only_flag(self, run_id, conn=None):
        """Return the record_only flag for a run (06-08, mirrors repo.get_record_only_flag).

        Returns False if the run is not found (safe default: live Resend path).
        All in-memory runs default to record_only=False (they are created via the
        webhook / demo_send_test path, not the compose path).
        """
        run = self.runs.get(str(run_id))
        if run is None:
            return False
        return bool(run.get("record_only", False))

    def load_thread_messages(self, run_id, conn=None):
        """Return thread messages for a run (06-08, mirrors repo.load_thread_messages).

        For in-memory tests, returns an empty list (no email rows are tracked at this
        granularity). Tests that need thread messages should monkeypatch directly.
        """
        return []

    def list_businesses(self, conn=None):
        """Return all businesses (06-08, mirrors repo.list_businesses).

        For in-memory tests, returns the seeded businesses list.
        """
        from app.db.seed import seed as _seed
        seeded = _seed(dry_run=True)
        return [
            {"id": str(b["id"]), "name": b["name"], "contact_email": b["contact_email"]}
            for b in seeded.businesses
        ]

    def get_demo_binding(self, operator_email, conn=None):
        """Return None (no demo bindings in the in-memory store, 06-08)."""
        return None

    def bind_demo_business(self, business_name, operator_email, seed_business_ids, conn=None):
        """No-op in-memory bind (06-08); returns True for any known business_name."""
        return business_name in seed_business_ids

    # --- email / threading (the FIX 3 outbound Message-ID anchor) ---
    def insert_email_message(self, *, run_id, direction, message_id, conn=None, round=0, **kw):
        """Mirror repo.insert_email_message, including the D-11-01 round-aware upsert.

        The real repo upserts outbound purpose rows on (run_id, purpose, round) —
        a retry WITHIN a round advances send_state/message_id in place, but a NEW
        round always appends a NEW row (no upsert-replace of prior-round history,
        D-11-01). `round` defaults to 0 so pre-Phase-11 callers (none of which pass
        it yet) are behavior-identical to the old (run_id, purpose) upsert key.

        GAP-2/GAP-3 (11-06): the OUTBOUND path also stamps epoch from the
        target run's CURRENT reply_epoch at write time (mirrors repo's
        correlated subquery in the INSERT). The upsert key is widened to
        (purpose, round, epoch) — mirrors the widened uq_email_run_purpose_round_epoch
        constraint and repo's ON CONFLICT (run_id, purpose, round, epoch)
        arbiter (GAP-2 fix): a retriggered run's fresh round-0 send (new
        epoch) must always APPEND a new row, never upsert-mutate the stale
        pre-retrigger round-0 row from a prior epoch.
        """
        purpose = kw.get("purpose")
        run = self.runs.get(str(run_id)) if run_id is not None else None
        row = {
            "run_id": run_id,
            "direction": direction,
            "message_id": message_id,
            "round": round,
            "consumed_round": None,
            "created_at": datetime.now(timezone.utc),
            **kw,
        }
        if direction == "outbound" and run_id is not None:
            epoch = run.get("reply_epoch", 0) if run is not None else 0
            row["epoch"] = epoch
            rows = self.outbound.setdefault(str(run_id), [])
            if purpose is not None:
                # Upsert key: (run_id, purpose, round, epoch) — mirrors
                # uq_email_run_purpose_round_epoch (GAP-2 widened constraint).
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

    def get_outbound_for_round(self, run_id, purpose, round, conn=None):
        """Round-aware sibling of get_outbound_message_id (D-11-01/13, mirrors repo).

        Filters direction (implicit — only self.outbound rows are stored),
        purpose, send_state='sent', AND round; returns {"message_id", "round"}
        (not just the message_id) so a caller derives the next round from the
        FOUND row, never a blind +1 (Pitfall #3).

        GAP-2 (11-06): also filters on row.get("epoch", 0) == the run's
        CURRENT reply_epoch — the actual GAP-2 fix, mirroring repo's
        correlated subquery scope.
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

    def mark_reply_consumed(self, message_id, round, conn=None):
        """Write-once consumed_round marker on the matching inbound row (D-11-02).

        Mirrors the real repo's `consumed_round IS NULL` write-once guard: a
        second call for an already-consumed message_id is a no-op.
        """
        row = self.emails.get(message_id)
        if row is not None and row.get("direction") == "inbound" and row.get("consumed_round") is None:
            row["consumed_round"] = round

    def load_consumed_replies(self, run_id, conn=None):
        """Return consumed inbound replies for a run, round-ordered (D-11-10/12/13).

        Mirrors repo.load_consumed_replies: filters inbound + consumed_round is
        not None, sorted by consumed_round ascending.

        GAP-3 (11-06): also filters on row.get("epoch", 0) == the run's
        CURRENT reply_epoch — the actual GAP-3 fix, mirroring repo's
        correlated subquery scope. A stale consumed reply from a pre-retrigger
        epoch is invisible here even though the row is never deleted.
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
        """Return the stored inbound row dict, or None (D-11-13, mirrors repo).

        WR-04 redelivery reads the PERSISTED row (Pitfall #11a) — this fake
        returns exactly what insert_inbound_email stored, never a freshly-built
        InboundEmail from a redelivered request.
        """
        row = self.emails.get(message_id)
        if row is None or row.get("direction") != "inbound":
            return None
        return row

    def find_stranded_unconsumed_replies(self, threshold_seconds, conn=None):
        """Stale unconsumed inbound replies against awaiting_reply runs (D-11-05).

        Mirrors repo.find_stranded_unconsumed_replies: applies the awaiting_reply
        + unconsumed + age filter using the row's created_at (every fake row now
        carries one, from insert_inbound_email/insert_email_message).

        GAP-2/GAP-3 (11-06): also requires row.get("epoch", 0) == the run's
        CURRENT reply_epoch — mirrors repo's `em.epoch = pr.reply_epoch` JOIN
        condition. A genuinely stale epoch-0 unconsumed reply must never be
        auto-resumed against a run that has since been retriggered into a
        NEW epoch-1 awaiting_reply state.
        """
        threshold = timedelta(seconds=threshold_seconds)
        now = datetime.now(timezone.utc)
        found: list[dict] = []
        for row in self.emails.values():
            if row.get("direction") != "inbound" or row.get("consumed_round") is not None:
                continue
            run_id = row.get("run_id")
            if run_id is None:
                continue
            run = self.runs.get(str(run_id))
            if not run or run.get("status") != "awaiting_reply":
                continue
            if row.get("epoch", 0) != run.get("reply_epoch", 0):
                continue
            created_at = row.get("created_at")
            if created_at is not None and now - created_at < threshold:
                continue
            found.append(row)
        return found

    # --- 06-04 new repo helpers (D-13c crash-safe ordering + D-14 threading) ---
    def get_outbound_references_chain(self, run_id, conn=None):
        """Return the references_header of the most recent sent outbound for this run.

        Mirrors repo.get_outbound_references_chain (D-14 durable threading rebuild).
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

        Mirrors repo.update_email_message_sent (D-13c success path, HIGH-1 waive).
        """
        self.update_email_message_state(message_id, "sent", conn=conn)

    def update_email_message_state(self, message_id, state, conn=None):
        """Set send_state on the outbound row with this synthetic message_id.

        Mirrors repo.update_email_message_state (D-13c crash-safe flip, HIGH-3).
        """
        for rows in self.outbound.values():
            for row in rows:
                if row.get("message_id") == message_id:
                    row["send_state"] = state
                    return

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
        # 06-08 additions — record_only + demo routing helpers
        "get_record_only_flag",
        "load_thread_messages",
        "list_businesses",
        "get_demo_binding",
        "bind_demo_business",
        # 06-04 additions — D-13c crash-safe ordering + D-14 durable threading
        "get_outbound_references_chain",
        "update_email_message_sent",
        "update_email_message_state",
        # 07.5-03 additions — D-19 MONEY-03 snapshot + D-13 MONEY-03 clarified_fields
        "set_pre_clarify_extracted",
        "load_pre_clarify_extracted",
        "set_clarified_fields",
        "load_clarified_fields",
        # 09-01 additions — DATA-03 stranded-run sweep + DATA-02 dedup-loser lookup
        "sweep_stranded_runs",
        "find_run_by_message_id",
        # phase-9 review WR-03 — reply/late-reply rows linked to their run
        "link_email_to_run",
        # Phase 11 (11-01) additions — round machine data-layer primitives
        "get_clarification_round",
        "set_clarification_round",
        "get_outbound_for_round",
        "mark_reply_consumed",
        "load_consumed_replies",
        "get_inbound_by_message_id",
        "clear_reply_context",
        "find_stranded_unconsumed_replies",
    ):
        if hasattr(store, name):
            monkeypatch.setattr(repo_mod, name, getattr(store, name), raising=False)

    # 09-01 (D-9-03): patch app.db.repo.get_connection to a FakeConnection-backed
    # context manager so `with repo.get_connection() as conn: with
    # conn.transaction(): ...` code (every subsequent Phase 9 plan's seam) runs
    # against the offline double instead of opening a real Supabase pool.
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


# ---------------------------------------------------------------------------
# 7. Phase 6 Resend SDK mock fixtures (06-01) — clean seams for gateway tests
# ---------------------------------------------------------------------------


class _FakeResendReceivedEmail:
    """Minimal stand-in for resend.ReceivedEmail.

    Mirrors the shape returned by resend.EmailsReceiving.get(email_id):
      - message_id (str): the RFC Message-ID
      - text (str | None): plain-text body
      - html (str | None): HTML body
      - headers (dict): flat key->value; keys may be mixed-case per provider (A1)

    The `headers` dict uses mixed-case keys matching real provider output, so tests
    exercise the case-insensitive extraction path (Pitfall 4 / D-18).
    """

    def __init__(
        self,
        *,
        message_id: str = "<test-recv@resend.test>",
        text: str | None = "Maria 40 hours",
        html: str | None = None,
        headers: dict | None = None,
    ) -> None:
        self.message_id = message_id
        self.text = text
        self.html = html
        # Default: mixed-case keys to exercise the normalization path (A1 assumption).
        self.headers: dict = headers if headers is not None else {
            "In-Reply-To": "<prev@x.test>",
            "References": "<prev@x.test>",
            "Subject": "Payroll hours",
        }


@pytest.fixture
def fake_received_email() -> _FakeResendReceivedEmail:
    """A minimal resend.ReceivedEmail stand-in with mixed-case header keys.

    Exercises the A1 assumption (header key casing from real providers) and the
    case-insensitive extraction path (Pitfall 4 / D-18 / 06-RESEARCH §1).
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

    Use this for the signature-rejection path (OPS-02 / D-17) — the route must
    return 400 and abort before any pipeline work when verify raises.
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
    calls: list[dict] = []

    def _fake_send(params):
        calls.append(params)
        return {"id": "<out-test@resend.com>"}

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_fake_send))
    # Return the calls list so tests can assert call count and params.
    return calls
