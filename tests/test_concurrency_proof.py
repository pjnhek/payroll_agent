"""OPS2-03 concurrency proof capstone (Phase 10, D-10-01/02/05/06/07).

Phase 9 established the atomicity/dedup/recovery invariants; this module PROVES
them under genuine concurrency against a real Postgres — the evidence behind
the "production-grade" claim. Three surfaces, four invariants:

  Surface A — test_dedup_exactly_one_run_per_message_id
      N_INGEST threads, released simultaneously by a threading.Barrier, all
      call `repo.insert_inbound_email` directly with ONE shared message_id,
      then `repo.create_run` on the winner. This drives real DB-level MVCC
      contention on the `ON CONFLICT (message_id) DO NOTHING` clause — NOT
      through the async `/webhook/inbound` route (see CR-01 note below).
      Must resolve to EXACTLY ONE run (no duplicate run per message_id).

  Surface B — test_concurrent_approvals_exactly_one_wins
      N_APPROVE concurrent POSTs to the REAL HTTP /runs/{run_id}/approve route
      (a *sync* FastAPI route, dispatched to Starlette's anyio worker
      threadpool — genuinely parallel OS threads) on ONE seeded run must
      result in EXACTLY ONE _deliver call and the run reaching 'approved'
      exactly once (no double-approval, D-10-06). This is the route-level
      upgrade over test_claim_status.py's CAS-primitive-only stub — it
      catches regressions ABOVE the CAS, not just inside it.

  Surface C — test_concurrent_distinct_runs_no_lost_update
      N_INGEST threads, released simultaneously by a threading.Barrier, call
      `repo.insert_inbound_email` + `repo.create_run` directly with N_INGEST
      DISTINCT message_ids. Must produce EXACTLY N_INGEST runs (no lost
      update) and every run row must carry a non-null source_email_id with a
      matching email_messages row (no half-written state, D-9-09 ingest-
      transaction atomicity).

CR-01 note (why Surfaces A/C bypass the HTTP route): `/webhook/inbound` is
`async def` (app/main.py:276) whose only `await` is `await request.body()`,
BEFORE any DB work — the dedup insert -> create_run body is synchronous
blocking psycopg with no yield point. Starlette runs `async def` endpoints
directly on the single event loop, and a shared TestClient funnels every
thread through one ASGI portal, so N threads posting to that route execute
strictly one-at-a-time: the ON CONFLICT / lost-update races are never
triggered (confirmed against live source; the old HTTP-fan-out version of
this test would pass even with the ON CONFLICT clause deleted). Surface B's
route (`def approve`, sync) IS dispatched to a real worker threadpool, so it
stays HTTP-driven and its CAS proof is genuinely parallel and sound (D-10-06)
— left unchanged here.

Each test is guarded by the two-factor live-DB skip (DATABASE_URL +
ALLOW_DB_RESET=1) and depends on the seeded_db fixture (Coastal business +
roster). The default hermetic suite (`uv run pytest -m 'not integration'`)
never touches this module (D-10-04) — it is excluded by the `integration`
pytest marker.

Local invocation (requires a real/local Postgres):

    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres \\
    ALLOW_DB_RESET=1 ALLOW_UNSIGNED_FIXTURES=true \\
    uv run pytest tests/test_concurrency_proof.py -m integration -v

In CI, `.github/workflows/concurrency-proof.yml` runs this exact module against
an ephemeral postgres:16 service container on every push to master — green is
standing evidence the four invariants hold under real parallelism; red is a
caught regression.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.conftest import _SKIP_LIVE_DB

# ---------------------------------------------------------------------------
# Shared seed identifiers (mirrors tests/test_atomic_persist.py:49-50)
# ---------------------------------------------------------------------------
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"

# Surface B (/approve): each request holds a pooled connection only for the
# sub-ms CAS update, so 8 brief holders comfortably cycle through the pool.
N_APPROVE = 8

# Surfaces A & C (direct repo-seam ingest race, WR-01/IN-02): each
# barrier-released thread holds a pooled connection for the FULL ingest
# transaction (insert_inbound_email -> create_run), i.e. these threads are
# simultaneous connection HOLDERS, not brief CAS callers like Surface B. The
# app pool is min_size=1/max_size=5/timeout=5s (app/db/supabase.py), so
# N_INGEST must be <= 5 — otherwise the 6th+ thread blocks on
# pool.connection() and can hit the 5s PoolTimeout under a cold/slow CI
# runner, flaking the test on pool exhaustion rather than the invariant
# under test. N_INGEST == max_size (5) exercises the pool at full genuine
# concurrency without exceeding it.
N_INGEST = 5


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _stub_pipeline_and_send(monkeypatch):
    """Install the wholesale no-op stubbing this proof depends on (load-bearing).

    `.env` carries LIVE DeepSeek/Kimi/Resend keys. TestClient runs FastAPI
    BackgroundTasks SYNCHRONOUSLY, and the approve route calls `_deliver`
    synchronously inline (main.py:764) — any unstubbed path here would fire a
    real LLM call or a real Resend send on every concurrent request, flaking
    the proof and burning API credits. Returns (pipeline_calls, deliver_calls).
    """
    import app.main as app_main

    # Surfaces A + C: create_run does not itself schedule the pipeline (the
    # direct repo-seam call bypasses the webhook route entirely), but the
    # stub is kept so nothing downstream can ever fire a live call, and so
    # the module's isolation invariant is uniform across all three surfaces.
    pipeline_calls: list = []
    monkeypatch.setattr(
        app_main, "_run_pipeline", lambda run_id: pipeline_calls.append(run_id)
    )

    # Surface B: `_deliver` is imported INSIDE the approve route (main.py:753),
    # so it must be patched on the orchestrator module — patching app_main here
    # would be a silent no-op and every concurrent approval would attempt a
    # real send.
    deliver_calls: list = []
    monkeypatch.setattr(
        "app.pipeline.orchestrator._deliver",
        lambda rid, run: deliver_calls.append(rid),
    )

    # Belt-and-suspenders no-op (tests/conftest.py resend pattern) — guarantees
    # no accidental live Resend send even if a code path changes underneath us.
    import resend

    monkeypatch.setattr(
        resend.Emails,
        "send",
        staticmethod(lambda params: {"id": "fake-resend-id"}),
        raising=True,
    )

    return pipeline_calls, deliver_calls


def _seed_live_run(*, body: str, from_addr: str = COASTAL_EMAIL) -> uuid.UUID:
    """Insert an inbound email + run against the REAL DB (repo.*, no conn=).

    Adapted from tests/test_atomic_persist.py:120-133 — used by Surface B to
    seed the one run that N_APPROVE concurrent approvals will race against.
    """
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


# ===========================================================================
# Surface A — no duplicate run per message_id
# ===========================================================================


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_dedup_exactly_one_run_per_message_id(seeded_db, monkeypatch):
    """N_INGEST threads, released simultaneously by a threading.Barrier, race
    `insert_inbound_email` for ONE shared message_id — proving the `ON
    CONFLICT (message_id) DO NOTHING` + `create_run` sequence resolves the
    Resend-redelivery race via genuine Postgres MVCC contention (OPS2-03,
    D-9-09), not sequential-request serialization."""
    from app.db import repo

    _pipeline_calls, _deliver_calls = _stub_pipeline_and_send(monkeypatch)

    same_message_id = f"<race-{uuid.uuid4()}@acme.test>"

    barrier = threading.Barrier(N_INGEST)
    results: list[tuple[uuid.UUID | None, bool, uuid.UUID | None]] = []
    lock = threading.Lock()

    def _ingest() -> None:
        barrier.wait()  # release all N_INGEST threads at the same instant
        eid, inserted = repo.insert_inbound_email(
            message_id=same_message_id,
            in_reply_to=None,
            references_header=None,
            subject="Payroll hours",
            from_addr=COASTAL_EMAIL,
            to_addr="agent@payroll-agent.local",
            body_text="Maria Chen 40 regular hours.",
        )
        rid = repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=eid) if inserted else None
        with lock:
            results.append((eid, inserted, rid))

    threads = [threading.Thread(target=_ingest) for _ in range(N_INGEST)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == N_INGEST

    # WR-02: assert the winner/loser split EXPLICITLY — do not filter None
    # out of a set, which would silently pass even if every loser fabricated
    # a bogus run_id or the winner lookup were broken.
    winners = [r for r in results if r[1] is True]
    losers = [r for r in results if r[1] is False]
    assert len(winners) == 1, (
        f"exactly one of {N_INGEST} genuinely-concurrent duplicate inserts "
        f"must win the ON CONFLICT race; got {len(winners)} winners in {results}"
    )
    assert len(losers) == N_INGEST - 1

    winner_eid, _winner_inserted, winner_rid = winners[0]
    assert winner_eid is not None
    assert winner_rid is not None, "the winning insert must produce a non-null run id"

    # repo.py:171 docstring: ON CONFLICT DO NOTHING returns no row to a
    # duplicate loser, so insert_inbound_email yields (None, False) for every
    # loser. Assert against that ACTUAL documented behavior, not an
    # assumption — and every loser's derived run id must also be None (the
    # direct-seam code only calls create_run when inserted=True).
    for eid, inserted, rid in losers:
        assert eid is None, f"duplicate loser must get email_id=None, got {eid!r}"
        assert inserted is False
        assert rid is None, f"duplicate loser must never create a run, got {rid!r}"

    # Every non-null eid across all results must be identical (the single
    # committed row); losers contribute no eid at all.
    non_null_eids = {r[0] for r in results if r[0] is not None}
    assert non_null_eids == {winner_eid}

    # DB backstop: exactly one committed run row for this message_id.
    with repo.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM payroll_runs WHERE source_email_id = "
            "(SELECT id FROM email_messages WHERE message_id = %s)",
            (same_message_id,),
        )
        (count,) = cur.fetchone()
    assert count == 1, f"expected exactly one run row for {same_message_id}, got {count}"


# ===========================================================================
# Surface B — no double-approval via the real HTTP /approve route
# ===========================================================================


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_concurrent_approvals_exactly_one_wins(seeded_db, monkeypatch):
    """N_APPROVE concurrent POSTs to the REAL /runs/{run_id}/approve route on
    ONE seeded run must fire EXACTLY ONE `_deliver` and reach 'approved'
    exactly once — proving `claim_status`'s CAS (AWAITING_APPROVAL ->
    APPROVED) closes the double-approval race at the ROUTE level, not just
    inside the CAS primitive (D-10-06, upgrading test_claim_status.py's
    stub-only coverage). `/approve` is a *sync* FastAPI route, so Starlette
    dispatches these N_APPROVE requests to its anyio worker threadpool —
    genuinely parallel OS threads, unlike the async `/webhook/inbound` route
    (see the module docstring's CR-01 note).

    The route ALWAYS 303-redirects regardless of claim outcome (main.py:783),
    so HTTP status is NOT a signal of who won — the winning side effect
    (deliver_calls / terminal DB status) is asserted instead.
    """
    from app.config import get_settings
    from app.db import repo
    from app.models.status import RunStatus

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")

    from fastapi.testclient import TestClient

    import app.main as app_main

    _pipeline_calls, deliver_calls = _stub_pipeline_and_send(monkeypatch)

    client = TestClient(app_main.app)

    run_id = _seed_live_run(body="Maria Chen 40 regular hours.")
    repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)

    with ThreadPoolExecutor(max_workers=N_APPROVE) as ex:
        responses = list(
            ex.map(lambda _: client.post(f"/runs/{run_id}/approve"), range(N_APPROVE))
        )

    assert len(responses) == N_APPROVE

    assert len(deliver_calls) == 1, (
        f"exactly one _deliver call expected (one winner claims the CAS above "
        f"the delivery boundary); got {len(deliver_calls)}"
    )

    run = repo.load_run(run_id)
    assert run is not None
    assert run["status"] == "approved", (
        f"run must reach 'approved' exactly once under {N_APPROVE} concurrent "
        f"approvals; got status={run['status']!r}"
    )

    get_settings.cache_clear()


# ===========================================================================
# Surface C — no lost update AND no half-write across distinct concurrent runs
# ===========================================================================


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_concurrent_distinct_runs_no_lost_update(seeded_db, monkeypatch):
    """N_INGEST threads, released simultaneously by a threading.Barrier, call
    `insert_inbound_email` + `create_run` directly with N_INGEST DISTINCT
    message_ids — proving no distinct concurrent ingest is dropped or
    silently merged (no lost update) AND every run row carries a non-null
    source_email_id with a matching email_messages row (no half-write — the
    ingest transaction is atomic per D-9-09, even under real concurrent
    load). This is the throughput/atomicity-under-load surface distinct from
    Surface A's single-message_id dedup race.
    """
    from app.db import repo

    _pipeline_calls, _deliver_calls = _stub_pipeline_and_send(monkeypatch)

    message_ids = [f"<distinct-{uuid.uuid4()}@acme.test>" for _ in range(N_INGEST)]

    barrier = threading.Barrier(N_INGEST)
    results: list[tuple[str, uuid.UUID, uuid.UUID]] = []
    lock = threading.Lock()

    def _ingest(mid: str) -> None:
        barrier.wait()  # release all N_INGEST threads at the same instant
        eid, inserted = repo.insert_inbound_email(
            message_id=mid,
            in_reply_to=None,
            references_header=None,
            subject="Payroll hours",
            from_addr=COASTAL_EMAIL,
            to_addr="agent@payroll-agent.local",
            body_text="Maria Chen 40 regular hours.",
        )
        assert inserted, f"distinct message_id {mid} must always insert cleanly"
        rid = repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=eid)
        with lock:
            results.append((mid, eid, rid))

    threads = [threading.Thread(target=_ingest, args=(mid,)) for mid in message_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == N_INGEST

    run_ids = {rid for _mid, _eid, rid in results}
    assert len(run_ids) == N_INGEST, (
        f"{N_INGEST} distinct concurrent ingests must produce exactly "
        f"{N_INGEST} distinct runs (no lost update); got {len(run_ids)} "
        f"distinct run_ids"
    )

    # Note: create_run does NOT call _run_pipeline (that only happens via the
    # webhook route's BackgroundTask), so unlike the old HTTP-fan-out version
    # of this test, there is no pipeline_calls count to assert here for the
    # direct-seam surface.

    with repo.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT pr.id, pr.source_email_id, em.id
            FROM payroll_runs pr
            LEFT JOIN email_messages em ON em.id = pr.source_email_id
            WHERE pr.id = ANY(%s)
            """,
            (list(run_ids),),
        )
        rows = cur.fetchall()

    assert len(rows) == N_INGEST, f"expected {N_INGEST} run rows for the distinct ingests, got {len(rows)}"
    for run_pk, source_email_id, matched_email_pk in rows:
        assert source_email_id is not None, (
            f"run {run_pk} has a null source_email_id — half-written state "
            f"under concurrent distinct ingest (D-9-09 violation)"
        )
        assert matched_email_pk is not None, (
            f"run {run_pk}'s source_email_id={source_email_id} has no matching "
            f"email_messages row — orphaned/half-written run"
        )
