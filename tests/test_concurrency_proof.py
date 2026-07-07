"""OPS2-03 concurrency proof capstone (Phase 10, D-10-01/02/05/06/07).

Phase 9 established the atomicity/dedup/recovery invariants; this module PROVES
them under genuine OS-thread parallelism against a real Postgres — the evidence
behind the "production-grade" claim. Three surfaces, four invariants, N=8
simultaneous operations per surface, all fired through the real app pool via a
real TestClient (no per-thread raw psycopg.connect — see D-10-07):

  Surface A — test_dedup_exactly_one_run_per_message_id
      N=8 duplicate webhook POSTs sharing ONE message_id must resolve to
      EXACTLY ONE run (no duplicate run per message_id). Closes the Resend-
      redelivery race window on `insert_inbound_email`'s ON CONFLICT DO NOTHING.

  Surface B — test_concurrent_approvals_exactly_one_wins
      N=8 concurrent POSTs to the REAL HTTP /runs/{run_id}/approve route on ONE
      seeded run must result in EXACTLY ONE _deliver call and the run reaching
      'approved' exactly once (no double-approval, D-10-06). This is the
      route-level upgrade over test_claim_status.py's CAS-primitive-only stub —
      it catches regressions ABOVE the CAS, not just inside it.

  Surface C — test_concurrent_distinct_runs_no_lost_update
      N=8 webhook POSTs with N=8 DISTINCT message_ids fired concurrently must
      produce EXACTLY N runs (no lost update) and every run row must carry a
      non-null source_email_id with a matching email_messages row (no
      half-written state, D-9-09 ingest-transaction atomicity).

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

import os
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

N = 8  # D-10-07: genuinely interleaves, stays inside the pool budget (min=1/max=5)


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

    # Surfaces A + C: the winning thread's BackgroundTask would otherwise run
    # the real orchestrator (real DeepSeek/Kimi calls). No-op captures the call
    # so the test can assert exactly-one call.
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
    seed the one run that N=8 concurrent approvals will race against.
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


def _webhook_payload(message_id: str, *, body_text: str = "Maria Chen 40 regular hours.") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "message_id": message_id,
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": COASTAL_EMAIL,
        "to_addr": "agent@payroll-agent.local",
        "body_text": body_text,
        "created_at": "2026-06-15T10:00:00Z",
    }


# ===========================================================================
# Surface A — no duplicate run per message_id
# ===========================================================================


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_dedup_exactly_one_run_per_message_id(seeded_db, monkeypatch):
    """N=8 duplicate webhook POSTs sharing ONE message_id must create EXACTLY
    ONE run — proving `insert_inbound_email`'s ON CONFLICT (message_id) DO
    NOTHING + create_run sequence resolves the Resend-redelivery race via
    Postgres MVCC under genuine parallelism (OPS2-03, D-9-09)."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")

    from fastapi.testclient import TestClient

    import app.main as app_main

    pipeline_calls, _deliver_calls = _stub_pipeline_and_send(monkeypatch)

    client = TestClient(app_main.app)

    same_message_id = f"<race-{uuid.uuid4()}@acme.test>"
    payload = _webhook_payload(same_message_id)

    results: list[dict] = []
    lock = threading.Lock()

    def _post() -> None:
        r = client.post("/webhook/inbound", json=payload)
        with lock:
            results.append(r.json())

    threads = [threading.Thread(target=_post) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == N

    run_ids = {r.get("run_id") for r in results if r.get("run_id")}
    assert len(run_ids) == 1, (
        f"{N} concurrent duplicate webhook deliveries for the same message_id "
        f"must create EXACTLY ONE run; got run_ids={run_ids}"
    )

    statuses = {r.get("status") for r in results}
    assert statuses <= {"accepted", "duplicate"}, f"unexpected statuses: {statuses}"

    assert len(pipeline_calls) == 1, (
        f"exactly one _run_pipeline call expected (one winner schedules the "
        f"pipeline); got {len(pipeline_calls)}"
    )

    from app.db import repo

    with repo.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM payroll_runs WHERE source_email_id = "
            "(SELECT id FROM email_messages WHERE message_id = %s)",
            (same_message_id,),
        )
        (count,) = cur.fetchone()
    assert count == 1, f"expected exactly one run row for {same_message_id}, got {count}"

    get_settings.cache_clear()


# ===========================================================================
# Surface B — no double-approval via the real HTTP /approve route
# ===========================================================================


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_concurrent_approvals_exactly_one_wins(seeded_db, monkeypatch):
    """N=8 concurrent POSTs to the REAL /runs/{run_id}/approve route on ONE
    seeded run must fire EXACTLY ONE `_deliver` and reach 'approved' exactly
    once — proving `claim_status`'s CAS (AWAITING_APPROVAL -> APPROVED) closes
    the double-approval race at the ROUTE level, not just inside the CAS
    primitive (D-10-06, upgrading test_claim_status.py's stub-only coverage).

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

    with ThreadPoolExecutor(max_workers=N) as ex:
        responses = list(
            ex.map(lambda _: client.post(f"/runs/{run_id}/approve"), range(N))
        )

    assert len(responses) == N

    assert len(deliver_calls) == 1, (
        f"exactly one _deliver call expected (one winner claims the CAS above "
        f"the delivery boundary); got {len(deliver_calls)}"
    )

    run = repo.load_run(run_id)
    assert run is not None
    assert run["status"] == "approved", (
        f"run must reach 'approved' exactly once under {N} concurrent "
        f"approvals; got status={run['status']!r}"
    )

    get_settings.cache_clear()


# ===========================================================================
# Surface C — no lost update AND no half-write across distinct concurrent runs
# ===========================================================================


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_concurrent_distinct_runs_no_lost_update(seeded_db, monkeypatch):
    """N=8 webhook POSTs with N=8 DISTINCT message_ids fired concurrently must
    produce EXACTLY N runs (no lost update — none of the N distinct ingests is
    dropped or silently merged) AND every run row must have a non-null
    source_email_id with a matching email_messages row (no half-write — the
    ingest transaction is atomic per D-9-09, even under concurrent distinct
    load). This is the throughput/atomicity-under-load surface distinct from
    Surface A's single-message_id dedup race.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")

    from fastapi.testclient import TestClient

    import app.main as app_main

    pipeline_calls, _deliver_calls = _stub_pipeline_and_send(monkeypatch)

    client = TestClient(app_main.app)

    message_ids = [f"<distinct-{uuid.uuid4()}@acme.test>" for _ in range(N)]
    payloads = [_webhook_payload(mid) for mid in message_ids]

    with ThreadPoolExecutor(max_workers=N) as ex:
        responses = list(
            ex.map(
                lambda p: client.post("/webhook/inbound", json=p).json(), payloads
            )
        )

    assert len(responses) == N

    run_ids = {r.get("run_id") for r in responses if r.get("run_id")}
    assert len(run_ids) == N, (
        f"{N} distinct concurrent ingests must produce exactly {N} distinct "
        f"runs (no lost update); got {len(run_ids)} distinct run_ids"
    )

    assert len(pipeline_calls) == N, (
        f"exactly {N} _run_pipeline calls expected (one per distinct new run); "
        f"got {len(pipeline_calls)}"
    )

    from app.db import repo

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

    assert len(rows) == N, f"expected {N} run rows for the distinct ingests, got {len(rows)}"
    for run_pk, source_email_id, matched_email_pk in rows:
        assert source_email_id is not None, (
            f"run {run_pk} has a null source_email_id — half-written state "
            f"under concurrent distinct ingest (D-9-09 violation)"
        )
        assert matched_email_pk is not None, (
            f"run {run_pk}'s source_email_id={source_email_id} has no matching "
            f"email_messages row — orphaned/half-written run"
        )

    get_settings.cache_clear()
