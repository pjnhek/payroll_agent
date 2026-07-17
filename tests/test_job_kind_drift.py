"""CI drift guard: the `jobs` queue vocabulary must never collide with, nor drift
from, the `payroll_runs` business vocabulary or its own SQL CHECK constraints.

ROADMAP criterion #5 turned into a tripwire: a CI-enforced guard fails the build
if a `jobs.kind` value ever collides with a `payroll_runs.status` value, or drifts
from the `JobKind` enum in either direction. This module mirrors
tests/test_status_drift.py's shape — pure static-file parsing, no DB connection —
but needs its OWN inline-CHECK parser: `jobs.kind`/`jobs.state` are declared as
inline CHECKs inside `CREATE TABLE jobs (...)`, not via the executable DO-block
re-add pattern `app/db/schema_introspect.py::_do_block_check_values` parses (that
parser anchors on a constraint-name literal followed by its re-add CHECK, which
`jobs` deliberately has none of — see app/db/schema.sql's DEVIATION 1 comment).
Calling the DO-block parser against `jobs` raises ValueError; it does not
silently pass with an empty set, so this file writes a genuinely different,
simpler regex instead of reusing that helper with different arguments.

Falsifying mutations (each independently reverts the guard to red — see the
individual test bodies for the exact mutation and the executed proof pasted into
this plan's SUMMARY):
  (a) add a JobKind member with no corresponding value in the SQL CHECK
      -> test_job_kind_check_matches_python_enum goes red.
  (b) add a value to the SQL CHECK with no JobKind member
      -> the SAME test goes red (set equality, both directions).
  (c) rename a JobState member's value to a string RunStatus already owns
      -> test_job_state_never_collides_with_run_status goes red.
  (d) remove "jobs" from expected_schema().tables
      -> test_health_schema_covers_jobs goes red (the registration this guards
      is one careless refactor from silently disappearing without this).

The dispatch-table half of Proof 5 (`set(JobKind) == set(dispatch.HANDLERS)`) is
appended to THIS file by the plan that creates app/queue/dispatch.py — append
below the placeholder at the bottom rather than creating a second file.
"""

import ast
import pathlib
import re
import uuid

import pytest

from app.db import bootstrap
from app.db.schema_introspect import _create_body, expected_schema
from app.models.job import Job, JobKind, JobState
from app.models.status import RunStatus

_SCHEMA_SQL = pathlib.Path(__file__).parent.parent / "app" / "db" / "schema.sql"


def _inline_check_values(sql: str, table: str, column: str) -> set[str]:
    """Parse the value set out of the FIRST `CHECK (<column> IN (...))` inside
    `CREATE TABLE <table> (...)`.

    A genuinely different, simpler parser than
    `schema_introspect._do_block_check_values`: it has no constraint-name
    literal to anchor on, because `jobs.kind`/`jobs.state` are inline CHECKs
    with no DO-block re-add. Scoping the search to `table`'s CREATE body (via
    `_create_body`, already parenthesis-balanced) rather than the whole file
    keeps this from ever accidentally matching a sibling table's CHECK on a
    same-named column.
    """
    body = _create_body(sql, table)
    m = re.search(
        rf"CHECK\s*\(\s*{re.escape(column)}\s+IN\s*\((.*?)\)\s*\)",
        body,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        raise ValueError(
            f"No inline 'CHECK ({column} IN (...))' found in the {table} CREATE body"
        )
    return {v.strip().strip("'") for v in m.group(1).split(",") if v.strip()}


def _clean_sql() -> str:
    return re.sub(r"--[^\n]*", "", _SCHEMA_SQL.read_text())


class TestKindStatusCollision:
    """INVARIANT J-1: the queue vocabulary can never name a business status."""

    def test_job_kind_never_collides_with_run_status(self) -> None:
        kind_values = {m.value for m in JobKind}
        status_values = {m.value for m in RunStatus}
        collision = kind_values & status_values
        assert not collision, (
            f"JobKind value(s) {sorted(collision)} collide with RunStatus — a "
            "jobs.kind that equals a payroll_runs.status is INVARIANT J-1 "
            "violated at the vocabulary level"
        )

    def test_job_state_never_collides_with_run_status(self) -> None:
        state_values = {m.value for m in JobState}
        status_values = {m.value for m in RunStatus}
        collision = state_values & status_values
        assert not collision, (
            f"JobState value(s) {sorted(collision)} collide with RunStatus — a "
            "future JobState member taking a string RunStatus already owns is "
            "exactly the trap this guard exists to catch"
        )


class TestJobKindCheckDrift:
    """jobs.kind/jobs.state SQL CHECK value sets must set-EQUAL their Python enum."""

    def test_job_kind_check_matches_python_enum(self) -> None:
        sql = _clean_sql()
        sql_values = _inline_check_values(sql, "jobs", "kind")
        py_values = {m.value for m in JobKind}
        sql_only = sql_values - py_values
        py_only = py_values - sql_values
        assert sql_values == py_values, (
            f"jobs.kind drift detected!\n"
            f"  In SQL CHECK but not in JobKind: {sql_only or 'none'}\n"
            f"  In JobKind but not in SQL CHECK: {py_only or 'none'}\n"
            f"  SQL values:    {sorted(sql_values)}\n"
            f"  Python values: {sorted(py_values)}"
        )

    def test_job_state_check_matches_python_enum(self) -> None:
        sql = _clean_sql()
        sql_values = _inline_check_values(sql, "jobs", "state")
        py_values = {m.value for m in JobState}
        sql_only = sql_values - py_values
        py_only = py_values - sql_values
        assert sql_values == py_values, (
            f"jobs.state drift detected!\n"
            f"  In SQL CHECK but not in JobState: {sql_only or 'none'}\n"
            f"  In JobState but not in SQL CHECK: {py_only or 'none'}\n"
            f"  SQL values:    {sorted(sql_values)}\n"
            f"  Python values: {sorted(py_values)}"
        )


class TestJobsDdlInventory:
    """jobs' DDL inventory is pinned by name, so a silent drop/rename fails loud."""

    def test_jobs_ddl_inventory_is_pinned(self) -> None:
        sql = _clean_sql()
        for name in (
            "uq_jobs_dedup_key",
            "ck_jobs_lease_coherent",
            "idx_jobs_claimable",
        ):
            assert name in sql, f"{name} must be present in schema.sql"

        body = _create_body(sql, "jobs")
        assert body, "could not extract the jobs CREATE body"
        assert "CASCADE" not in body.upper(), (
            "jobs' CREATE body must not declare a cascading delete — an "
            "append-only audit log (matching the email_messages precedent) "
            "cannot silently vaporize a run's attempt history"
        )
        assert "event_id" in body, (
            "Durable ingest requires jobs.event_id to point at the "
            "verified inbound envelope before any payroll run exists"
        )

    def test_bootstrap_drop_order_includes_jobs(self) -> None:
        assert "jobs" in bootstrap._DROP_ORDER
        assert "payroll_runs" in bootstrap._DROP_ORDER
        assert bootstrap._DROP_ORDER.index("jobs") < bootstrap._DROP_ORDER.index(
            "payroll_runs"
        ), (
            "'jobs' must precede 'payroll_runs' in _DROP_ORDER — it FK-references "
            "payroll_runs, so dropping payroll_runs first would orphan (or, with "
            "CASCADE, silently vaporize) job rows before jobs itself is dropped"
        )

    def test_health_schema_covers_jobs(self) -> None:
        assert "jobs" in expected_schema().tables, (
            "'jobs' must be a key of expected_schema().tables — without this, a "
            "live deploy on which the jobs table silently failed to apply would "
            "still report /health/schema as in_sync"
        )


class TestNoDbConnectionNeeded:
    """This file must stay a pure static-file test — no DB import, ever."""

    def test_no_db_connection_needed(self) -> None:
        source = pathlib.Path(__file__).read_text()
        tree = ast.parse(source, filename=__file__)

        _FORBIDDEN = {"app.db.supabase", "psycopg", "psycopg_pool"}

        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN:
                        offenders.append(f"line {node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in _FORBIDDEN or module.startswith("app.db.supabase"):
                    offenders.append(f"line {node.lineno}: from {module} import ...")

        assert not offenders, (
            "test_job_kind_drift.py must not import the DB layer.\n"
            "Forbidden import(s) found:\n  " + "\n  ".join(offenders)
        )


class TestDispatchTableMatchesJobKind:
    """The dispatch-table half of the collision/enum-drift/dispatch-drift
    guard: every `JobKind` member must have exactly one registered handler,
    and every registered handler must correspond to a real `JobKind` member.

    Set EQUALITY, never a subset/superset check in either direction — a
    pre-loosened `<=`/`>=` guard would silently permit exactly the
    phantom-kind-with-no-handler this assertion exists to catch: a job whose
    kind can be enqueued and claimed but never dispatched, or a handler
    nobody can ever reach. Importing `app.queue.dispatch` here pulls in
    `app.db.repo` transitively, but nothing in this test opens a connection
    or reads `DATABASE_URL` — it only inspects `dispatch.HANDLERS`, a plain
    module-level dict, so this file's "no DB import" contract (see
    `TestNoDbConnectionNeeded` above) still holds: no *connection* is ever
    made.
    """

    def test_job_kind_equals_dispatch_table(self) -> None:
        from app.queue import dispatch

        assert {m.value for m in JobKind} == set(dispatch.HANDLERS.keys())

    def test_all_job_kinds_sql_and_handlers_land_atomically(self) -> None:
        """Every declared transport operation has one SQL value and handler."""
        from app.queue import dispatch

        expected = {"ingest", "run_pipeline", "resume_reply", "operator_resume"}
        sql_values = _inline_check_values(_clean_sql(), "jobs", "kind")

        assert {member.value for member in JobKind} == expected
        assert sql_values == expected
        assert {member.value for member in dispatch.HANDLERS} == expected

        module, name = dispatch.HANDLERS[JobKind.RESUME_REPLY]
        assert module.__name__ == "app.queue.handlers.resume_reply"
        assert name == "handle_resume_reply"

        module, name = dispatch.HANDLERS[JobKind.OPERATOR_RESUME]
        assert module.__name__ == "app.queue.handlers.operator_resume"
        assert name == "handle_operator_resume"

        module, name = dispatch.HANDLERS[JobKind.INGEST]
        assert module.__name__ == "app.queue.handlers.ingest"
        assert name == "handle_ingest"

    def test_ingest_dispatch_resolves_the_module_attribute_at_call_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.pipeline.result import PipelineOutcome, PipelineResult
        from app.queue import dispatch

        module, name = dispatch.HANDLERS[JobKind.INGEST]
        observed: list[uuid.UUID | None] = []

        def replacement(job: Job) -> PipelineResult:
            observed.append(job.event_id)
            return PipelineResult(outcome=PipelineOutcome.OK)

        monkeypatch.setattr(module, name, replacement)
        event_id = uuid.uuid4()
        job = Job(
            id=uuid.uuid4(),
            kind=JobKind.INGEST,
            run_id=None,
            email_id=None,
            operator_resolution_id=None,
            event_id=event_id,
            attempts=1,
            max_attempts=5,
            lease_token=uuid.uuid4(),
        )

        assert dispatch.handle(job).outcome is PipelineOutcome.OK
        assert observed == [event_id]

    def test_ingest_handler_forwards_only_the_event_identifier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.pipeline.result import PipelineOutcome, PipelineResult
        from app.queue.handlers import ingest

        event_id = uuid.uuid4()
        expected = PipelineResult(outcome=PipelineOutcome.OK)
        observed: list[uuid.UUID] = []

        def process(received_event_id: uuid.UUID) -> PipelineResult:
            observed.append(received_event_id)
            return expected

        monkeypatch.setattr(ingest.ingest_service, "process_inbound_event", process)
        job = Job(
            id=uuid.uuid4(),
            kind=JobKind.INGEST,
            run_id=None,
            email_id=None,
            operator_resolution_id=None,
            event_id=event_id,
            attempts=1,
            max_attempts=5,
            lease_token=uuid.uuid4(),
        )

        assert ingest.handle_ingest(job) is expected
        assert observed == [event_id]

    def test_ingest_handler_fails_closed_without_an_event_identifier(self) -> None:
        from app.queue.handlers import ingest

        job = Job(
            id=uuid.uuid4(),
            kind=JobKind.INGEST,
            run_id=None,
            email_id=None,
            operator_resolution_id=None,
            event_id=None,
            attempts=1,
            max_attempts=5,
            lease_token=uuid.uuid4(),
        )

        with pytest.raises(ValueError, match="event_id"):
            ingest.handle_ingest(job)


def test_resume_reply_sql_requires_exact_identifier_context() -> None:
    """A reply retry carries only its run and persisted inbound-email ids."""
    body = _create_body(_clean_sql(), "jobs").lower()

    assert "ck_jobs_resume_reply_context" in body
    assert "kind <> 'resume_reply'" in body
    assert "run_id is not null" in body
    assert "email_id is not null" in body
    assert "operator_resolution_id is null" in body


def test_operator_resume_sql_requires_exact_identifier_context() -> None:
    """An operator retry carries only its run and immutable resolution ids."""
    body = _create_body(_clean_sql(), "jobs").lower()

    assert "ck_jobs_operator_resume_context" in body
    assert "kind <> 'operator_resume'" in body
    assert "run_id is not null" in body
    assert "operator_resolution_id is not null" in body
    assert "email_id is null" in body


def test_ingest_sql_requires_only_an_event_identifier_while_open() -> None:
    """Open ingest work cannot smuggle any payroll or message context."""
    schema = " ".join(_clean_sql().lower().split())

    expected = (
        "constraint ck_jobs_ingest_context check ( kind <> 'ingest' or ( "
        "run_id is null and email_id is null and "
        "operator_resolution_id is null and business_id is null and "
        "(event_id is not null or state in ('done','dead')) ) )"
    )
    assert schema.count(expected) == 2


def test_http_routes_do_not_produce_ingest_jobs() -> None:
    """The internal consumer must remain unreachable from request handlers."""
    route_source = "\n".join(
        path.read_text()
        for path in sorted((pathlib.Path("app") / "routes").glob("*.py"))
    )
    assert "JobKind.INGEST" not in route_source
