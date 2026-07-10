"""SC2 concurrency race proof — webhook dedup under real Postgres MVCC (09-03, DATA-02).

Two real OS threads fire two real Postgres transactions (via a real TestClient
hitting a real/local Postgres) with the SAME message_id, near-simultaneously.
Asserts exactly one run exists across both responses — proving the ingest
transaction's dedup-insert + reply-classification + create_run sequence resolves
the race via Postgres's own MVCC blocking behavior on the uq_message_id UNIQUE
index (RESEARCH.md Pitfall 3: FakeConnection cannot simulate this — only a real
connection proves atomicity, not just SQL shape).

Skip-guarded on DATABASE_URL (matches test_claim_status.py's exact skip shape).
This is a SEPARATE test module from tests/test_webhook.py and does NOT inherit
that module's client fixture's env setup — pytest does not share monkeypatch
state across test modules, so this module sets ALLOW_UNSIGNED_FIXTURES=true
itself (Codex Round-2 MEDIUM) before constructing its own TestClient, or every
POST would 400 on signature rejection before ever reaching the dedup-insert
logic this test exists to prove.
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Any

import pytest


@pytest.mark.integration
def test_duplicate_webhook_delivery_creates_exactly_one_run(monkeypatch):
    """Two concurrent duplicate webhook deliveries for the same message_id must
    result in exactly one payroll run (SC2, D-9-09, Codex HIGH-1's regression
    guard proven against real Postgres concurrency, not a mocked simulation)."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — skipping live-DB integration test")

    from app.config import get_settings

    get_settings.cache_clear()
    # Codex Round-2 MEDIUM: mirrors tests/test_webhook.py's client fixture pattern
    # verbatim — this module does NOT inherit that fixture's env setup, so every
    # POST here would otherwise receive a 400 (unsigned webhook rejected) before
    # ever reaching the dedup-insert logic this test exists to prove.
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")

    from fastapi.testclient import TestClient

    import app.main as app_main
    import app.routes.pipeline_glue as pipeline_glue_mod

    # Codex MEDIUM (SC2 test isolation): TestClient runs FastAPI BackgroundTasks
    # SYNCHRONOUSLY, so the "winning" thread's request would otherwise launch the
    # REAL pipeline (real LLM calls) inside this test. Monkeypatch run_pipeline_bg
    # to a no-op BEFORE firing the two threads so this test proves ONLY the
    # dedup/race property against real Postgres. This test's message_id is fresh
    # and carries no reply headers, so the race can only ever hit the new-run
    # path — resume_pipeline_bg is not monkeypatched because it cannot be reached.
    pipeline_calls: list[uuid.UUID] = []
    monkeypatch.setattr(
        pipeline_glue_mod, "run_pipeline_bg", lambda run_id: pipeline_calls.append(run_id)
    )

    client = TestClient(app_main.app)

    same_message_id = f"<race-{uuid.uuid4()}@acme.test>"
    payload = {
        "id": str(uuid.uuid4()),
        "message_id": same_message_id,
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": "payroll@coastalcleaning.example",
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria Chen 40 regular hours.",
        "created_at": "2026-06-15T10:00:00Z",
    }

    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    def _post() -> None:
        r = client.post("/webhook/inbound", json=payload)
        with lock:
            results.append(r.json())

    t1 = threading.Thread(target=_post)
    t2 = threading.Thread(target=_post)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    run_ids = {r.get("run_id") for r in results if r.get("run_id")}
    assert len(run_ids) == 1, (
        f"two concurrent duplicate webhook deliveries for the same message_id "
        f"must create EXACTLY ONE run (SC2, D-9-09); got run_ids={run_ids}"
    )

    # Exactly one of the two responses is the winner ("accepted"); the other is
    # the loser ("duplicate", reporting the winner's run_id per D-9-09).
    statuses = {r.get("status") for r in results}
    assert statuses <= {"accepted", "duplicate"}, f"unexpected statuses: {statuses}"

    # The winner's background task was scheduled (proving the race resolved to
    # exactly one _run_pipeline call, matching the exactly-one-run assertion).
    assert len(pipeline_calls) == 1, (
        f"exactly one _run_pipeline call expected (one winner schedules the "
        f"pipeline); got {len(pipeline_calls)}"
    )

    get_settings.cache_clear()
