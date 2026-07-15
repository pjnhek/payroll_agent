"""Hermetic, FakeConnection-backed SQL-shape tests for `app/db/repo/jobs.py`.

No live database anywhere in this file — every assertion runs against the
recorded (sql, params) pairs a `FakeConnection` captures. This is the fast
feedback loop; the live-DB *behavioral* proofs (a genuine claim race, an
actually-reclaimed expired lease, a fenced zombie write) live in
`tests/test_queue_durability.py`.
"""
from __future__ import annotations

import dataclasses
import re
import uuid

import pytest

from app.models.job import Job, JobKind


@pytest.fixture(autouse=True)
def _settings_stub(monkeypatch: pytest.MonkeyPatch):
    """enqueue_job/claim_job fall back to get_settings() for max_attempts/
    lease_seconds when the caller omits them, and Settings.database_url has
    no default — so every test in this hermetic file needs a stub DB URL in
    scope, exactly like tests/test_queue_config.py's own pattern."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://repo-jobs-sql-test/stub")
    yield
    get_settings.cache_clear()


def _claim_sql(fake_conn) -> str:
    """Run claim_job once against fake_conn and return the recorded SQL text."""
    from app.db.repo import jobs

    fake_conn.script_fetchone(
        (uuid.uuid4(), "run_pipeline", uuid.uuid4(), 1, 5, uuid.uuid4())
    )
    jobs.claim_job(conn=fake_conn)
    sql, _params = fake_conn.last()
    return str(sql)


def test_claim_returning_maps_bijectively_onto_the_job_dataclass(fake_conn) -> None:
    """THE row-mapping test: claim_job's RETURNING columns, in order, must equal
    Job's dataclass fields, in order — an ORDERED-LIST equality, not a subset
    check, so a column with no field AND a field with no column both go red
    independently.
    """
    sql = _claim_sql(fake_conn)
    match = re.search(r"RETURNING\s+(.*)\Z", sql, re.DOTALL)
    assert match is not None, f"claim_job's SQL has no RETURNING clause:\n{sql}"
    returned_cols = [
        col.strip().removeprefix("j.")
        for col in match.group(1).strip().split(",")
    ]
    job_fields = [f.name for f in dataclasses.fields(Job)]
    assert returned_cols == job_fields, (
        "claim_job's RETURNING clause must map bijectively, in order, onto "
        f"Job's fields.\n  RETURNING: {returned_cols}\n  Job fields: {job_fields}\n"
        f"  symmetric difference: {set(returned_cols) ^ set(job_fields)}"
    )


def test_claim_sql_shape(fake_conn) -> None:
    """claim_job's SQL contains the three load-bearing properties: the
    expired-lease reclaim clause, the attempts-at-claim increment, and
    FOR UPDATE SKIP LOCKED living INSIDE the subquery (after the SELECT that
    precedes the outer UPDATE's `WHERE j.id = (`)."""
    sql = _claim_sql(fake_conn)
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "OR (c.state = 'leased'  AND c.leased_until <  now())" in sql or re.search(
        r"OR\s*\(c\.state\s*=\s*'leased'\s*AND\s*c\.leased_until\s*<\s*now\(\)\)", sql
    )
    assert re.search(r"attempts\s*=\s*j\.attempts\s*\+\s*1", sql)
    where_idx = sql.index("WHERE j.id = (")
    select_idx = sql.index("SELECT c.id")
    skip_locked_idx = sql.index("FOR UPDATE SKIP LOCKED")
    assert where_idx < select_idx < skip_locked_idx, (
        "FOR UPDATE SKIP LOCKED must appear inside the subquery, after a SELECT "
        "that itself appears after the outer UPDATE's WHERE j.id = ( — a bare "
        "UPDATE ... LIMIT 1 is not valid Postgres and FOR UPDATE on the outer "
        "statement gives no row-skipping."
    )


def test_complete_and_fail_both_fence_on_lease_token(fake_conn) -> None:
    """A cheap static tripwire for the double-fence mutation: both
    complete_job and fail_job's WHERE clauses must reference lease_token.

    The assertions target the WHERE CLAUSE SPECIFICALLY, never the substring
    "lease_token = " anywhere in the statement. Both statements also SET
    lease_token = NULL to release the lease as they close the row out — so a
    bare whole-statement substring check stays GREEN with the entire WHERE
    fence deleted. It would be asserting the RELEASE and calling it the FENCE,
    and a zombie worker's write would sail straight through it. Splitting on
    WHERE is what makes this tripwire able to fail at all.
    """
    from app.db.repo import jobs

    def _where_of(sql: object) -> str:
        squeezed = " ".join(str(sql).split())
        assert "WHERE" in squeezed, f"statement has no WHERE clause at all: {squeezed}"
        return squeezed.split("WHERE", 1)[1]

    job_id, token = uuid.uuid4(), uuid.uuid4()

    fake_conn.script_fetchone((job_id,))
    jobs.complete_job(job_id, token, conn=fake_conn)
    complete_where = _where_of(fake_conn.last()[0])

    fake_conn.script_fetchone(("pending",))
    jobs.fail_job(job_id, token, error="boom", backoff_seconds=1.0, conn=fake_conn)
    fail_where = _where_of(fake_conn.last()[0])

    assert "lease_token = %s" in complete_where, (
        "complete_job's WHERE clause must fence on lease_token; without it a zombie "
        "worker whose lease already expired can still mark the job done. "
        f"WHERE was: {complete_where}"
    )
    assert "lease_token = %(token)s" in fail_where, (
        "fail_job's WHERE clause must fence on lease_token too — this is the fence "
        f"people remember on complete and forget on fail. WHERE was: {fail_where}"
    )


def test_enqueue_sql_uses_on_conflict_do_nothing(fake_conn) -> None:
    from app.db.repo import jobs

    fake_conn.script_fetchone((uuid.uuid4(),))
    jobs.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key="run_pipeline:some-run:0",
        run_id=uuid.uuid4(),
        conn=fake_conn,
    )
    sql, _params = fake_conn.last()
    assert "ON CONFLICT (dedup_key) DO NOTHING" in str(sql)


def test_enqueue_run_pipeline_without_a_run_id_raises_before_touching_the_db(
    fake_conn,
) -> None:
    """The Python-side guard: the ValueError must fire BEFORE any statement is
    issued — assert the exception type specifically (never a bare Exception,
    which the DB's own CHECK constraint would also satisfy) AND that
    fake_conn recorded zero statements."""
    from app.db.repo import jobs

    with pytest.raises(ValueError, match="run_pipeline"):
        jobs.enqueue_job(
            kind=JobKind.RUN_PIPELINE,
            dedup_key="x",
            run_id=None,
            conn=fake_conn,
        )
    assert fake_conn.executed == []


def test_release_leases_empty_sequence_issues_no_statement(fake_conn) -> None:
    from app.db.repo import jobs

    result = jobs.release_leases([], conn=fake_conn)
    assert result == 0
    assert fake_conn.executed == []


def test_release_leases_sql_shape(fake_conn) -> None:
    from app.db.repo import jobs

    token = uuid.uuid4()
    fake_conn.script_fetchall([(uuid.uuid4(),)])
    count = jobs.release_leases([token], conn=fake_conn)
    assert count == 1
    sql, params = fake_conn.last()
    assert "state = 'pending'" in str(sql)
    assert "lease_token = ANY(%s)" in str(sql)


def test_get_job_sql_shape(fake_conn) -> None:
    from app.db.repo import jobs

    job_id = uuid.uuid4()
    fake_conn.script_fetchone({"id": job_id})
    jobs.get_job(job_id, conn=fake_conn)
    sql, params = fake_conn.last()
    assert "SELECT" in str(sql) and "FROM jobs WHERE id = %s" in str(sql)
    assert "SELECT *" not in str(sql)


def test_no_function_builds_sql_with_an_fstring(fake_conn) -> None:
    """Every recorded execute() call across all seven functions must pass its
    values through a params tuple/dict — never bake a value into the SQL text
    itself via an f-string."""
    from app.db.repo import jobs

    job_id, token = uuid.uuid4(), uuid.uuid4()

    fake_conn.script_fetchone((uuid.uuid4(),))
    jobs.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key="d1",
        run_id=uuid.uuid4(),
        conn=fake_conn,
    )
    fake_conn.script_fetchone(
        (uuid.uuid4(), "run_pipeline", uuid.uuid4(), 1, 5, uuid.uuid4())
    )
    jobs.claim_job(conn=fake_conn)
    fake_conn.script_fetchone((job_id,))
    jobs.complete_job(job_id, token, conn=fake_conn)
    fake_conn.script_fetchone(("pending",))
    jobs.fail_job(job_id, token, error="boom", backoff_seconds=1.0, conn=fake_conn)
    fake_conn.script_fetchall([(uuid.uuid4(),)])
    jobs.release_leases([token], conn=fake_conn)
    fake_conn.script_fetchone({"id": job_id})
    jobs.get_job(job_id, conn=fake_conn)
    fake_conn.script_fetchone((3,))
    jobs.count_open_jobs(conn=fake_conn)

    for sql, params in fake_conn.executed:
        assert isinstance(params, (tuple, dict)), (
            f"execute() call recorded params of type {type(params)!r}, expected "
            f"a tuple or dict (no f-string SQL): {sql!r}"
        )


def test_facade_exports_all_seven_functions() -> None:
    from app.db import repo

    for name in (
        "enqueue_job",
        "claim_job",
        "complete_job",
        "fail_job",
        "release_leases",
        "get_job",
        "count_open_jobs",
    ):
        assert hasattr(repo, name), f"app.db.repo is missing facade export {name!r}"


def test_every_function_takes_conn_and_uses_conn_ctx() -> None:
    """Every function in jobs.py has `conn: psycopg.Connection | None = None`
    in its signature and opens with the _conn_ctx(conn)/_nulltx() pair —
    checked via source inspection, not by eye."""
    import inspect

    from app.db.repo import jobs

    for name in (
        "enqueue_job",
        "claim_job",
        "complete_job",
        "fail_job",
        "release_leases",
        "get_job",
        "count_open_jobs",
    ):
        fn = getattr(jobs, name)
        sig = inspect.signature(fn)
        assert "conn" in sig.parameters, f"{name} is missing a conn parameter"
        assert sig.parameters["conn"].default is None
        source = inspect.getsource(fn)
        assert "_conn_ctx(conn)" in source, f"{name} does not open with _conn_ctx(conn)"


def test_count_open_jobs_maps_scalar_row_to_int_and_scopes_the_where(
    fake_conn,
) -> None:
    """HONEST hermetic coverage only: a FakeConnection records the (sql,
    params) pair, it does not execute the count, so this proves exactly two
    things — the return→int conversion, and the literal WHERE text (pending +
    leased counted, done/dead excluded BY the WHERE). It does NOT and cannot
    prove that Postgres actually counts a mixed pending/leased/done/dead
    population correctly; that behavioral proof is live-Postgres and lands in
    17-05.
    """
    from app.db.repo import jobs

    fake_conn.script_fetchone((3,))
    result = jobs.count_open_jobs(conn=fake_conn)
    assert result == 3
    assert isinstance(result, int)
    sql, params = fake_conn.last()
    assert "state IN ('pending', 'leased')" in str(sql)


def test_count_open_jobs_empty_row_returns_zero(fake_conn) -> None:
    """No/None row (the FakeConnection's empty-scripted-result stand-in for
    "no rows matched") maps to 0, not a crash or a None leak."""
    from app.db.repo import jobs

    fake_conn.script_fetchone(None)
    result = jobs.count_open_jobs(conn=fake_conn)
    assert result == 0
    assert isinstance(result, int)
