"""Proof 1 (QUEUE-01) — the webhook does not block the event loop.

Two proofs live here, both hermetic (fake_repo, no live DB, no live LLM):

  1. test_two_concurrent_webhooks_run_in_parallel_not_serially — two concurrent
     POSTs to /webhook/inbound against a `gateway.parse_inbound` stub that blocks
     for SLOW_S=0.6s complete in wall-clock time roughly equal to ONE slow call,
     not their sum. This is ROADMAP criterion #1.

  2. test_reply_candidate_background_task_survives_the_threadpool_hop — Task 2
     moved `finish_reply_resume` (which calls `background_tasks.add_task(...)`)
     into a worker thread via `run_in_threadpool`. A timing assertion on the
     `new_run` branch does NOT cover this: `new_run` schedules its background
     task from the event loop, so it stays green even if the reply path's
     cross-thread `BackgroundTasks.add_task` append were silently dropped. This
     test proves the appended task actually survived the hop AND actually ran.

WHY httpx.AsyncClient + ASGITransport, NEVER starlette.testclient.TestClient
(mirrors the rationale documented in tests/test_concurrency_proof.py:27-39):
`/webhook/inbound` is `async def`; TestClient's synchronous `.post()` calls run
through an internal AnyIO portal that serializes concurrent callers onto ONE
worker thread driving ONE event loop iteration at a time — so N "concurrent"
TestClient calls funneled through a single shared client execute one at a time,
and the very race this proof exists to catch would never trigger. Only
`httpx.AsyncClient(transport=ASGITransport(app=app))` driven by genuine
`asyncio.gather(...)` inside a real `async def` test body exercises the actual
event loop the way concurrent production traffic would. Note ASGITransport does
NOT execute FastAPI lifespan events (no queue worker threads start here, even
after plan 16-07 lands) — but it DOES drain Starlette's post-response
BackgroundTasks before returning control to the caller, unlike TestClient,
which is exactly what makes proof 2 above meaningful.

FALSIFYING MUTATIONS (both executed against this file; the RED output is recorded
in this phase's execution record — a proof that survives its own mutation does
not count):

  (a) In app/routes/webhook.py, replace
      `result = await run_in_threadpool(_parse_and_ingest_sync, raw_body)`
      with `result = _parse_and_ingest_sync(raw_body)` (a direct call, no
      threadpool hop). Proof 1's wall-clock assertion MUST go red at
      ~2 * SLOW_S — the two slow parses now serialize on the event loop.

  (b) In app/routes/pipeline_glue.py's finish_reply_resume, replace
      `background_tasks.add_task(resume_pipeline_bg, run_id, reply_for_resume)`
      with a no-op (delete the call). Proof 2 MUST go red on its
      "the spy WAS called" assertion, while its 200/"resumed" response
      assertion STILL PASSES — which is exactly why the spy assertion has to
      exist: a response-shape check alone cannot see a silently-dropped
      BackgroundTask.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.email import gateway
from app.email.clean import clean_body
from app.main import app
from app.models.contracts import InboundEmail
from app.models.status import RunStatus
from app.routes import pipeline_glue

SLOW_S = 0.6

COASTAL_EMAIL = "payroll@coastalcleaning.example"


@pytest.fixture
def unsigned_fixtures_env(monkeypatch):
    """ALLOW_UNSIGNED_FIXTURES=true so canonical dict POSTs succeed (matches the
    `client` fixture convention in tests/test_webhook.py / test_reply_redelivery.py),
    with the lru_cache discipline mock_llm already establishes elsewhere in this
    suite: clear before AND after so per-test env edits never leak."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    yield
    get_settings.cache_clear()


def _make_slow_parse_inbound(call_count: dict[str, int]):
    """A PLAIN SYNCHRONOUS stub that blocks for SLOW_S via time.sleep, then returns
    a real InboundEmail. Deliberately sync `def`, not `async def` — the real
    `_parse_and_ingest_sync` is a sync function called via `run_in_threadpool`, so
    an `async def` stub handed a coroutine object back would blow up rather than
    measure anything. A blocking `time.sleep` in a sync stub is precisely the thing
    that serializes on the event loop and parallelizes in the threadpool."""

    def _slow_parse_inbound(raw: bytes) -> InboundEmail:
        call_count["n"] += 1
        n = call_count["n"]
        time.sleep(SLOW_S)
        return InboundEmail(
            id=uuid.uuid4(),
            message_id=f"<concurrency-proof-{n}-{uuid.uuid4()}@test.example>",
            in_reply_to=None,
            references_header=None,
            subject="Payroll hours for week of 2026-06-15",
            from_addr=COASTAL_EMAIL,
            to_addr="agent@payroll-agent.local",
            body_text="Maria Chen 40 regular hours.",
            created_at=datetime.now(UTC),
        )

    return _slow_parse_inbound


# ---------------------------------------------------------------------------
# Proof 1 — two concurrent webhooks run in parallel, not serially
# ---------------------------------------------------------------------------


def test_two_concurrent_webhooks_run_in_parallel_not_serially(
    monkeypatch, fake_repo, unsigned_fixtures_env
) -> None:
    call_count = {"n": 0}
    monkeypatch.setattr(gateway, "parse_inbound", _make_slow_parse_inbound(call_count))

    async def _fire_two() -> tuple[float, tuple[Any, Any]]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            t0 = time.monotonic()
            responses = await asyncio.gather(
                # DISTINCT payload bodies (both irrelevant — parse_inbound is
                # stubbed above and ignores raw_body — but kept distinct so
                # neither request's raw bytes accidentally collide/dedup on
                # something else). Each stubbed InboundEmail carries a DISTINCT
                # message_id (see _make_slow_parse_inbound), so both take the
                # new_run outcome — this proof is scoped to criterion #1 only,
                # never touching the dedup path.
                client.post("/webhook/inbound", json={"marker": "request-A"}),
                client.post("/webhook/inbound", json={"marker": "request-B"}),
            )
            elapsed = time.monotonic() - t0
            return elapsed, responses

    elapsed, responses = asyncio.run(_fire_two())

    # Generous margin: parallel => ~SLOW_S; serial (the bug) => ~2*SLOW_S.
    assert elapsed < 1.5 * SLOW_S, (
        f"elapsed={elapsed:.2f}s suggests the two requests were serialized, not "
        f"run concurrently off the event loop (expected ~{SLOW_S}s, not ~{2 * SLOW_S}s)"
    )

    # Anti-vacuity: a route that 400s/502s on both requests would satisfy the
    # timing assertion trivially (two fast failures are also "not 2x slow"). Both
    # responses must genuinely be the accepted new_run outcome, AND the slow stub
    # must have actually been invoked exactly twice — proving the requests reached
    # the blocking work rather than short-circuiting before it.
    for response in responses:
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"
    assert call_count["n"] == 2, (
        f"expected the slow parse stub to run exactly twice, got {call_count['n']}"
    )


# ---------------------------------------------------------------------------
# Proof 2 — the reply-candidate BackgroundTask survives the threadpool hop
# ---------------------------------------------------------------------------


def test_reply_candidate_background_task_survives_the_threadpool_hop(
    monkeypatch, fake_repo, unsigned_fixtures_env
) -> None:
    # Seed a run at AWAITING_REPLY with a stored outbound clarification row whose
    # message_id the reply's In-Reply-To will match (mirrors
    # tests/test_webhook.py::test_reply_and_late_reply_rows_linked_to_run).
    orig_eid, _ = fake_repo.insert_inbound_email(
        message_id="<orig-threadpool-001@acme.test>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular hours.",
    )
    # repo.find_business_by_sender returning this run's business is what makes
    # reply_sender_ok's spoof guard PASS below — a mismatched sender would return
    # sender_mismatch and schedule nothing, making this test pass vacuously.
    business_id = fake_repo.find_business_by_sender(COASTAL_EMAIL)
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=orig_eid)

    clar_message_id = "<clarify-threadpool-001@payroll-agent.local>"
    fake_repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=clar_message_id,
        purpose="clarification",
        send_state="sent",
    )
    fake_repo.runs[str(run_id)]["status"] = RunStatus.AWAITING_REPLY.value

    spy_calls: list[tuple[uuid.UUID, InboundEmail]] = []

    def _spy(spied_run_id: uuid.UUID, inbound: InboundEmail) -> None:
        spy_calls.append((spied_run_id, inbound))

    monkeypatch.setattr(pipeline_glue, "resume_pipeline_bg", _spy)

    raw_body_text = (
        "Maria Chen actually worked 42 hours.\n\n"
        "> On Mon, Jun 15, 2026, agent wrote:\n"
        "> Please confirm Maria Chen's hours."
    )
    reply_payload = {
        "id": str(uuid.uuid4()),
        "message_id": "<reply-threadpool-001@acme.test>",
        "in_reply_to": clar_message_id,
        "references_header": clar_message_id,
        "subject": "Re: payroll hours",
        "from_addr": COASTAL_EMAIL,
        "to_addr": "agent@payroll-agent.local",
        "body_text": raw_body_text,
        "created_at": "2026-06-16T09:30:00Z",
    }

    async def _fire_reply() -> Any:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # ASGITransport, unlike TestClient, drains Starlette's post-response
            # BackgroundTasks before returning control here — so by the time this
            # await resolves, resume_pipeline_bg has either genuinely run or been
            # genuinely dropped, never left "scheduled but unobserved".
            return await client.post("/webhook/inbound", json=reply_payload)

    response = asyncio.run(_fire_reply())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resumed"
    assert body["run_id"] == str(run_id)

    # Assert the spy actually ran — "the response said resumed" is exactly the
    # assertion that CANNOT see a background_tasks.add_task call that appended
    # successfully but whose task never drained.
    assert len(spy_calls) == 1, (
        "resume_pipeline_bg must actually be invoked after the response — a "
        "BackgroundTasks.add_task appended from inside the worker thread "
        "finish_reply_resume ran in must survive the run_in_threadpool hop, not "
        "merely produce a 'resumed' response body"
    )
    spied_run_id, reply_for_resume = spy_calls[0]
    assert str(spied_run_id) == str(run_id)

    # The spy must have been called with the CLEANED body, not the raw one — the
    # `email.model_copy(update={"body_text": cleaned})` inside finish_reply_resume
    # must survive the hop too. Computed independently via clean_body rather than
    # hardcoded, but still a meaningful assertion: clean_body demonstrably strips
    # the quoted ">" block above, so a bug that shipped the RAW body through
    # unchanged would fail this comparison.
    expected_cleaned = clean_body(raw_body_text)
    assert expected_cleaned != raw_body_text, (
        "sanity: this test's raw body must actually contain something clean_body "
        "strips, or the cleaned-vs-raw assertion below would be vacuous"
    )
    assert reply_for_resume.body_text == expected_cleaned, (
        f"expected the CLEANED body {expected_cleaned!r}, got the raw/uncleaned "
        f"body {reply_for_resume.body_text!r} — the model_copy(update=...) must "
        "survive the cross-thread hop"
    )
