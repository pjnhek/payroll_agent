"""Hermetic tests for GET /internal/pump (app/routes/pump.py, PUMP-01).

No live Postgres anywhere in this file — every test drives the route through
`TestClient(app_main.app)` (exercising FastAPI's real 401/503 handling, not
the route function in isolation) with `repo`/`drain_once`/`dispatch` seams
monkeypatched. `tests/conftest.py` pins WORKER_COUNT=0 suite-wide, so every
`TestClient` instance here already runs with zero live worker threads.

Test groups, selectable via `-k`:
  - auth: 401 on missing/wrong/empty-secret Bearer token; 200 on correct
    token, including the claimed==sum invariant.
  - bounded: the dual drain cap (max-jobs AND wall-clock, checked separately
    so neither could be a silent no-op).
  - infra_failure: a genuine infra outage returns 503 while a business
    outcome like dead-letter/backoff still returns 200, including BOTH
    required double-failure proofs — the narrow drain_once-raises mapping
    AND the real fake-repo chain through the REAL drain_once().
"""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
import app.routes.pump as pump_module
from app.config import get_settings
from app.db import repo
from app.models.job import Job, JobKind
from app.queue import dispatch, drain
from app.queue.drain import DrainOutcome

PUMP_PATH = "/internal/pump"


@pytest.fixture(autouse=True)
def _settings_cache_clean(monkeypatch: pytest.MonkeyPatch):
    """Clear the get_settings() lru_cache BOTH before the test AND after
    (post-yield). A PUMP_TOKEN cached from an earlier test must never leak
    into this one, and this test's own PUMP_TOKEN must never leak into the
    next. Mirrors tests/test_repo_jobs_sql.py's autouse settings-stub idiom.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://pump-route-test/stub")
    yield
    get_settings.cache_clear()


def _client_with_token(monkeypatch: pytest.MonkeyPatch, token: str) -> TestClient:
    """Set PUMP_TOKEN (possibly empty, for the fail-closed case), clear the
    settings cache so the fresh value is actually read, and return a
    TestClient over the real app."""
    monkeypatch.setenv("PUMP_TOKEN", token)
    get_settings.cache_clear()
    return TestClient(app_main.app)


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assert_accounting_identity(body: dict[str, int]) -> None:
    """Maintenance reaps are dead rows, never claimed executions."""
    assert body["claimed"] == (
        body["done"]
        + body["retried"]
        + (body["dead"] - body["reaped_final_lease"])
        + body["fenced"]
    )


# ── auth ──────────────────────────────────────────────────────────────────


def test_auth_missing_header_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH)
    assert resp.status_code == 401


def test_auth_wrong_bearer_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH, headers=_auth_header("wrong"))
    assert resp.status_code == 401


def test_auth_empty_pump_token_fails_closed_even_with_plausible_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PUMP_TOKEN unset/empty rejects EVERY call, even a header that looks
    plausible (here, the empty string itself) — the fail-closed contract."""
    client = _client_with_token(monkeypatch, "")
    resp = client.get(PUMP_PATH, headers=_auth_header(""))
    assert resp.status_code == 401


def test_auth_correct_token_returns_200_with_counts_invariant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pump_module, "drain_once", lambda: DrainOutcome.EMPTY)
    monkeypatch.setattr(repo, "count_open_jobs", lambda: 0)

    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH, headers=_auth_header("secret-token"))

    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "claimed",
        "done",
        "retried",
        "dead",
        "fenced",
        "reaped_final_lease",
        "queue_depth",
    ):
        assert key in body
    assert body["reaped_final_lease"] == 0
    _assert_accounting_identity(body)


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (
            [DrainOutcome.REAPED_FINAL_LEASE],
            {
                "claimed": 0,
                "done": 0,
                "retried": 0,
                "dead": 1,
                "fenced": 0,
                "reaped_final_lease": 1,
            },
        ),
        (
            [
                DrainOutcome.DONE,
                DrainOutcome.REAPED_FINAL_LEASE,
                DrainOutcome.RETRIED,
                DrainOutcome.DEAD,
                DrainOutcome.FENCED,
                DrainOutcome.REAPED_FINAL_LEASE,
            ],
            {
                "claimed": 4,
                "done": 1,
                "retried": 1,
                "dead": 3,
                "fenced": 1,
                "reaped_final_lease": 2,
            },
        ),
    ],
    ids=["reap-only", "mixed-outcomes"],
)
def test_reaped_final_leases_are_dead_but_never_claimed(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[DrainOutcome],
    expected: dict[str, int],
) -> None:
    sequence = iter([*outcomes, DrainOutcome.EMPTY])
    monkeypatch.setattr(pump_module, "drain_once", lambda: next(sequence))
    monkeypatch.setattr(repo, "count_open_jobs", lambda: 0)

    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH, headers=_auth_header("secret-token"))

    assert resp.status_code == 200
    body = resp.json()
    assert body == {**expected, "queue_depth": 0}
    _assert_accounting_identity(body)


# ── bounded ───────────────────────────────────────────────────────────────


def test_bounded_max_jobs_cap_stops_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop stops at _MAX_JOBS_PER_PUMP even though drain_once() always
    reports a claimable job (never DrainOutcome.EMPTY)."""
    monkeypatch.setattr(pump_module, "drain_once", lambda: DrainOutcome.DONE)
    monkeypatch.setattr(repo, "count_open_jobs", lambda: 999)

    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH, headers=_auth_header("secret-token"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["claimed"] == pump_module._MAX_JOBS_PER_PUMP
    assert body["done"] == pump_module._MAX_JOBS_PER_PUMP


def test_bounded_max_jobs_cap_includes_reaped_maintenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reaps do not inflate claimed, but still consume the bounded drain budget."""
    calls = 0

    def _reap() -> DrainOutcome:
        nonlocal calls
        calls += 1
        return DrainOutcome.REAPED_FINAL_LEASE

    monkeypatch.setattr(pump_module, "drain_once", _reap)
    monkeypatch.setattr(repo, "count_open_jobs", lambda: 999)

    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH, headers=_auth_header("secret-token"))

    assert resp.status_code == 200
    body = resp.json()
    assert calls == pump_module._MAX_JOBS_PER_PUMP
    assert body["claimed"] == 0
    assert body["dead"] == pump_module._MAX_JOBS_PER_PUMP
    assert body["reaped_final_lease"] == pump_module._MAX_JOBS_PER_PUMP
    _assert_accounting_identity(body)


def test_bounded_wall_clock_cap_stops_the_loop_before_max_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SEPARATE proof that the WALL-CLOCK branch — not the job-count cap —
    forced the exit. `time.monotonic` is jumped past the deadline after
    exactly N iterations, N < _MAX_JOBS_PER_PUMP; a bare "loop terminates and
    returns 200" assertion would still pass even if the wall-clock check
    were a no-op and the max-jobs cap did all the work.
    """
    n_iterations = 3
    assert n_iterations < pump_module._MAX_JOBS_PER_PUMP

    real_monotonic = time.monotonic
    call_count = {"n": 0}

    class _FakeTime:
        """A stand-in for the stdlib `time` module, bound ONLY onto
        `pump_module`'s own `time` name (not the global `time` module) — the
        ASGI/anyio machinery driving TestClient's request also calls
        `time.monotonic()` internally, so patching the global function would
        exhaust this fake's carefully-counted call budget before the route's
        own loop ever runs.
        """

        @staticmethod
        def monotonic() -> float:
            # Call #1 is the route's own `deadline = time.monotonic() + CAP`
            # computation — must return a real value so the deadline itself
            # is sane. Calls #2..#(1+n_iterations) are the loop-condition
            # checks that must PASS (allowing exactly n_iterations
            # drain_once() calls). Every call after that returns a value far
            # past the deadline, so the NEXT loop-condition check (the one
            # that would allow a 4th iteration) fails on the wall-clock
            # branch specifically.
            call_count["n"] += 1
            if call_count["n"] <= 1 + n_iterations:
                return real_monotonic()
            return real_monotonic() + pump_module._MAX_WALL_CLOCK_SECONDS + 1000

    monkeypatch.setattr(pump_module, "time", _FakeTime)
    monkeypatch.setattr(pump_module, "drain_once", lambda: DrainOutcome.DONE)
    monkeypatch.setattr(repo, "count_open_jobs", lambda: 0)

    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH, headers=_auth_header("secret-token"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["claimed"] == n_iterations
    assert body["claimed"] < pump_module._MAX_JOBS_PER_PUMP


# ── infra_failure ─────────────────────────────────────────────────────────


def test_infra_failure_count_open_jobs_raises_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine infra outage on the queue_depth read — not a dispatch
    failure — must surface as 503, never a swallowed 500-as-200."""
    monkeypatch.setattr(pump_module, "drain_once", lambda: DrainOutcome.EMPTY)

    def _raise_db_error() -> int:
        raise RuntimeError("simulated database outage on count_open_jobs")

    monkeypatch.setattr(repo, "count_open_jobs", _raise_db_error)

    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH, headers=_auth_header("secret-token"))

    assert resp.status_code == 503


def test_infra_failure_dead_or_retried_outcome_still_returns_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead-lettered or backed-off job is normal queue operation, not a
    pump failure — 200 + counts, never 5xx."""
    outcomes = iter([DrainOutcome.DEAD, DrainOutcome.RETRIED, DrainOutcome.EMPTY])
    monkeypatch.setattr(pump_module, "drain_once", lambda: next(outcomes))
    monkeypatch.setattr(repo, "count_open_jobs", lambda: 2)

    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH, headers=_auth_header("secret-token"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["dead"] == 1
    assert body["retried"] == 1
    assert body["claimed"] == 2


def test_infra_failure_drain_once_raises_maps_to_503_not_a_fenced_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The NARROW mapping test: drain_once() itself raising must map to 503,
    not be silently swallowed into a 200-with-a-fenced-count. Pins the
    exception -> 503 mapping in isolation; the real fake-repo double-failure
    chain below is the LOAD-BEARING proof that the real drain_once() body
    actually re-raises AND retains its lease through the HTTP call — this
    test alone would pass even if that real chain were broken.
    """

    def _raise(*args: object, **kwargs: object) -> DrainOutcome:
        raise RuntimeError("simulated drain_once failure")

    monkeypatch.setattr(pump_module, "drain_once", _raise)

    client = _client_with_token(monkeypatch, "secret-token")
    resp = client.get(PUMP_PATH, headers=_auth_header("secret-token"))

    assert resp.status_code == 503


def test_infra_failure_real_double_failure_chain_through_testclient_returns_503_and_retains_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LOAD-BEARING double-failure proof: reuses the exact double-failure
    fake-repo idiom from tests/test_queue_drain.py
    (`test_a_failed_infrastructure_settlement_keeps_the_lease_recorded`) —
    claim returns a leased job, dispatch.handle raises, and
    repo.settle_infrastructure_failure ALSO raises — but drives it through
    TestClient -> GET /internal/pump instead of calling drain.drain_once()
    directly, so the REAL drain_once() runs its double-failure branch and
    RE-RAISES into the route's try/except.

    Neither the narrow drain_once-monkeypatched-to-raise test above, nor a
    count_open_jobs-only test, proves this: both bypass the real
    drain_once() body that must actually retain the lease token (module
    state) through an HTTP request/response round trip.
    """
    token = uuid.uuid4()
    leased_job = Job(
        id=uuid.uuid4(),
        kind=JobKind.RUN_PIPELINE,
        run_id=uuid.uuid4(),
        attempts=1,
        max_attempts=5,
        lease_token=token,
    )

    def _outage(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated database outage")

    connection_calls = 0

    def _unexpected_connection() -> None:
        nonlocal connection_calls
        connection_calls += 1
        raise AssertionError(
            "the double-failure proof must patch the settlement seam directly, "
            "not pass incidentally because a real/fake DB connection raises"
        )

    monkeypatch.setattr(repo, "claim_job", lambda: leased_job)
    monkeypatch.setattr(dispatch, "handle", _outage)  # the handler fails: DB is down
    monkeypatch.setattr(repo, "settle_infrastructure_failure", _outage)
    monkeypatch.setattr(repo, "get_connection", _unexpected_connection)

    client = _client_with_token(monkeypatch, "secret-token")
    try:
        resp = client.get(PUMP_PATH, headers=_auth_header("secret-token"))

        assert resp.status_code == 503
        assert connection_calls == 0, (
            "the proof reached a DB connection instead of the patched atomic "
            "infrastructure-settlement seam"
        )
        assert drain.held_tokens() == [token], (
            "the real drain_once() double-failure branch must RETAIN the lease "
            "token through the HTTP call — lease_settled stayed False, which is "
            "exactly what makes a graceful-shutdown release safe"
        )
    finally:
        drain._held_tokens.clear()  # module state: never leak into the next test
