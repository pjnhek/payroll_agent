"""Inbound body-cleaning and dedup tests (INGEST-02).

The webhook cleans the inbound body with the in-house clean_body() code-strip BEFORE the
email_messages insert, so the persisted body_text IS the cleaned text. That row is the
single source of truth: load_source_email returns it unchanged, and a resume re-extracts
over it. Cleaning once on the way in — rather than on every read — is what guarantees the
body the operator sees at the gate is byte-for-byte the body extraction actually read.

No third-party reply-parser is involved, so there is no new dependency to keep current.
"""
from __future__ import annotations

import json
import pathlib
import uuid as _uuid_module
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import repo
from app.email.clean import clean_body
from app.queue import drain
from app.queue.drain import DrainOutcome

_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clean_happy_path.json"


# ---------------------------------------------------------------------------
# clean_body unit behavior — quoted history + signature stripping
# ---------------------------------------------------------------------------


def test_clean_strips_quoted_reply_block():
    raw = (
        "Maria 40 regular hours.\n"
        "\n"
        "On Mon, Jun 8, 2026 at 9:14 AM Dana <p@x.test> wrote:\n"
        "> Last week's hours were Maria 38.\n"
        "> Thanks!\n"
    )
    cleaned = clean_body(raw)
    assert "Maria 40 regular hours." in cleaned
    assert "Last week" not in cleaned, "quoted history must be stripped"
    assert "wrote:" not in cleaned


def test_clean_strips_leading_quote_marker_block():
    raw = "This week: Maria 40.\n> quoted line one\n> quoted line two\n"
    cleaned = clean_body(raw)
    assert "This week: Maria 40." in cleaned
    assert "quoted line" not in cleaned


def test_clean_strips_signature_block():
    raw = "James salaried, no changes.\n\n-- \nDana Whitfield\nOffice Manager\n"
    cleaned = clean_body(raw)
    assert "James salaried, no changes." in cleaned
    assert "Office Manager" not in cleaned, "signature must be stripped"


def test_clean_is_idempotent():
    raw = "Maria 40 regular hours."
    assert clean_body(clean_body(raw)) == clean_body(raw)


# ---------------------------------------------------------------------------
# INGEST-02 — the webhook persists the CLEANED body to body_text
# ---------------------------------------------------------------------------


@pytest.fixture
def client(fake_repo, monkeypatch):
    """TestClient with ALLOW_UNSIGNED_FIXTURES=true.

    Without the flag the route's production auth gate rejects canonical InboundEmail dict
    POSTs (correctly — they carry no svix-* signature), and no mocked test could reach
    the pipeline at all.
    """
    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    yield TestClient(app)
    get_settings.cache_clear()


def _script_clean_run(mock_llm) -> None:
    """The clean happy path makes exactly ONE LLM call — extraction.

    reconcile and decide are pure deterministic code and consume no scripted response;
    both names resolve exactly, so the run processes without a clarification draft. If
    this script ever needs a second entry, a judgment stage has grown an LLM call.
    """
    extraction = json.dumps(
        {
            "employees": [
                {"submitted_name": "Maria Chen", "hours_regular": "40"},
                {"submitted_name": "James Okafor"},
            ],
            "pay_period_start": "2026-06-15",
            "pay_period_end": None,
        }
    )
    mock_llm.script = [extraction]


def _drain_all() -> None:
    """Drain every currently-claimable job to EMPTY, deterministically.

    A single `drain_once()` call claims exactly ONE job — `FOR UPDATE SKIP
    LOCKED` FIFO order, not "the job I meant." After an INGEST job runs it may
    itself enqueue a RUN_PIPELINE job; a caller that wants a clean point (no
    leftover work queued) must drain to EMPTY, not just call it once.
    """
    while drain.drain_once() is not DrainOutcome.EMPTY:
        pass


def _install_durable_event_store(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[_uuid_module.UUID, dict[str, Any]]:
    """Back the receipt and delayed-ingest seams with one in-memory event store."""
    events: dict[_uuid_module.UUID, dict[str, Any]] = {}

    def _insert_or_get_event(*, external_event_id, payload, conn=None):
        for event in events.values():
            if event["external_event_id"] == external_event_id:
                return event["id"], False
        event_id = _uuid_module.uuid4()
        events[event_id] = {
            "id": event_id,
            "external_event_id": external_event_id,
            "payload": payload,
        }
        return event_id, True

    def _load_event(event_id, conn=None):
        event = events.get(event_id)
        return None if event is None else {"id": event["id"], "payload": event["payload"]}

    monkeypatch.setattr(repo, "insert_or_get_inbound_event", _insert_or_get_event)
    monkeypatch.setattr(repo, "load_inbound_event", _load_event)
    return events


def test_body_cleaned(client, fake_repo, monkeypatch):
    """The fixture carries a quoted reply block and a signature; only the cleaned text
    is persisted to email_messages.body_text."""
    events = _install_durable_event_store(monkeypatch)
    payload = json.loads(_FIXTURE.read_text())

    r = client.post("/webhook/inbound", json=payload)
    assert r.status_code == 200
    event_id = _uuid_module.UUID(r.json()["event_id"])
    assert events[event_id]["payload"] == payload
    assert fake_repo.emails == {}, "the request boundary must stop at durable receipt"
    assert drain.drain_once() is DrainOutcome.DONE

    # Exactly one inbound email stored; its body_text is the cleaned body.
    assert len(fake_repo.emails) == 1
    stored = next(iter(fake_repo.emails.values()))
    body = stored["body_text"]

    assert "Maria Chen - 40 regular hours" in body
    # The fixture's quoted history + signature are gone.
    assert "wrote:" not in body, "quoted attribution must be stripped before insert"
    assert "Last week's hours" not in body, "quoted history must be stripped"
    assert "Office Manager" not in body, "signature must be stripped"

    # And load_source_email returns that SAME cleaned body unchanged (no re-clean).
    run_id = next(iter(fake_repo.runs))
    assert fake_repo.load_source_email(run_id) == body


# ===========================================================================
# The dedup gate — one payroll run per inbound message_id, however many deliveries
# ===========================================================================

import os  # noqa: E402 — the dedup tests below were appended after the module's imports

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"


def test_duplicate_delivery_pipeline_runs_once_unit(monkeypatch, fake_repo):
    """A duplicate delivery must NOT start a second pipeline run.

    Email providers retry webhook deliveries. Without the dedup gate, one client email
    would produce two payroll runs — and the operator could approve both.

    Mocked unit test (no live DB): the first POST inserts the email and queues
    run_pipeline; the second POST with the same message_id short-circuits (the repo
    returns inserted=False) and run_pipeline is NOT queued again.

    ALLOW_UNSIGNED_FIXTURES is set here so the route accepts a canonical InboundEmail
    dict POST with no svix-* signature headers, which keeps this a fast hermetic unit
    test rather than an integration one.
    """
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    # Enable unsigned fixture POSTs in dev mode so canonical dict payloads reach the
    # route logic; the prod default returns 400 without svix headers.
    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")

    events = _install_durable_event_store(monkeypatch)

    def _forbidden(*args, **kwargs):
        pytest.fail("webhook request executed payroll inline")

    import app.routes.pipeline_glue as pipeline_glue
    from app.queue.handlers import pipeline, resume_reply

    monkeypatch.setattr(pipeline_glue, "run_pipeline_now", _forbidden)
    monkeypatch.setattr(pipeline_glue, "resume_pipeline_now", _forbidden)
    monkeypatch.setattr(pipeline, "handle_run_pipeline", _forbidden)
    monkeypatch.setattr(resume_reply, "handle_resume_reply", _forbidden)

    test_client = TestClient(app, raise_server_exceptions=False)

    # Both POSTs use the same message_id.
    payload = {
        "id": str(_uuid_module.uuid4()),
        "message_id": "<dup-dedup-test@acme.test>",
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": "payroll@coastalcleaning.example",
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria 40 regular hours.",
        "created_at": "2026-06-15T10:00:00Z",
    }

    r1 = test_client.post("/webhook/inbound", json=payload)
    r2 = test_client.post("/webhook/inbound", json=payload)

    # Both requests should return 200 (the dedup path is silent — no 4xx).
    assert r1.status_code == 200, f"First POST must return 200; got {r1.status_code}"
    assert r2.status_code == 200, f"Duplicate POST must return 200; got {r2.status_code}"

    assert r1.json()["event_id"] == r2.json()["event_id"]
    assert r1.json()["status"] == "accepted"
    assert r2.json()["status"] == "duplicate"
    assert len(events) == 1
    ingest_jobs = [j for j in fake_repo.jobs.values() if j["kind"] == "ingest"]
    assert len(ingest_jobs) == 1
    assert ingest_jobs[0]["dedup_key"] == f"ingest:{r1.json()['event_id']}"
    assert fake_repo.runs == {}, "neither receipt request may execute payroll inline"

    assert drain.drain_once() is DrainOutcome.DONE
    assert len(fake_repo.runs) == 1
    run_id = _uuid_module.UUID(next(iter(fake_repo.runs)))
    pipeline_jobs = [j for j in fake_repo.jobs.values() if j["kind"] == "run_pipeline"]
    assert len(pipeline_jobs) == 1
    assert pipeline_jobs[0]["run_id"] == run_id
    assert pipeline_jobs[0]["email_id"] is None
    assert pipeline_jobs[0]["dedup_key"] == f"run_pipeline:{run_id}:0"

    # Clean up the settings cache after env monkeypatching.
    get_settings.cache_clear()


@pytest.mark.integration
def test_duplicate_delivery_pipeline_runs_once():
    """The dedup gate against a LIVE DB: two deliveries, same message_id → one run.

    The mocked twin above can only prove the route short-circuits when the repo SAYS
    inserted=False. This one proves the DB itself enforces it: the second delivery
    returns 200, creates no second run, and leaves exactly one email_messages row for
    the message_id (the ON CONFLICT DO NOTHING clause doing its job).

    Requires DATABASE_URL + ALLOW_DB_RESET=1 (the same two-factor guard as the other
    integration tests) and is excluded from the mocked suite by its marker.

    `/webhook/inbound` (`app/routes/webhook.py`) is a durable-receipt-only
    boundary — it commits the `inbound_events` row + one identifier-only
    INGEST job and calls `wake.wake()` (a plain `threading.Event.set()` only a
    running lifespan-owned worker thread would observe). A bare
    `TestClient(app, ...)` with no `with` block never starts that lifespan, so
    nothing ever drains the job. The mocked twin just above
    (`test_duplicate_delivery_pipeline_runs_once_unit`) already handles this —
    it explicitly calls `drain.drain_once()` after both POSTs. This live-DB
    counterpart uses the same idiom, chosen over `with TestClient(app) as
    client:` because the actual worker pool races asynchronously against the
    assertions below; the mocked twin's explicit synchronous `drain_once()`
    call is what makes this test deterministic.

    TWO INDEPENDENT DEDUP LAYERS, BOTH EXERCISED. A bare identical-payload
    redelivery (r1/r2 below) is caught entirely at the `inbound_events` layer —
    `external_event_id` is a SHA-256 digest of the exact raw bytes in fixture
    mode, so the second POST never even reaches a second INGEST job. That layer
    alone would make the ORIGINAL invariant this test is named for — "the
    ON CONFLICT DO NOTHING clause [on email_messages.message_id] doing its
    job" — unreachable code from this test's own perspective, which is exactly
    the "regression wearing a fix's clothes" a version that no longer exercises
    the retry would be. So a THIRD delivery (r3) uses a DIFFERENT top-level
    `id` (different raw bytes -> different event -> its own INGEST job) but
    the SAME `message_id` — simulating a genuinely distinct provider event
    that happens to reference the same underlying message. Draining THAT job
    is what actually reaches `insert_inbound_email`'s `ON CONFLICT
    (message_id) DO NOTHING` a second time and proves the layer this test was
    originally written to prove still holds post-Phase-19.
    """
    if not (_HAS_DB and _HAS_RESET):
        pytest.skip("DATABASE_URL or ALLOW_DB_RESET=1 not set — skipping live-DB dedup test")

    from fastapi.testclient import TestClient

    from app.db.bootstrap import bootstrap
    from app.db.seed import seed as _seed_fn
    from app.main import app

    bootstrap(reset=True)
    _seed_fn()

    # Use a real seeded contact_email so find_business_by_sender succeeds.
    seeded = _seed_fn(dry_run=True)
    contact_email = seeded.businesses[0]["contact_email"]

    dedup_mid = f"<dedup-integ-{_uuid_module.uuid4()}@acme.test>"
    payload = {
        "id": str(_uuid_module.uuid4()),
        "message_id": dedup_mid,
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": contact_email,
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria 40 regular hours.",
        "created_at": "2026-06-15T10:00:00Z",
    }

    test_client = TestClient(app, raise_server_exceptions=True)
    r1 = test_client.post("/webhook/inbound", json=payload)
    r2 = test_client.post("/webhook/inbound", json=payload)

    assert r1.status_code == 200, f"First POST must return 200; got {r1.status_code}"
    assert r2.status_code == 200, (
        f"Duplicate POST must return 200 (silent dedup, not an error); got {r2.status_code}"
    )
    assert r1.json()["event_id"] == r2.json()["event_id"], (
        "both deliveries of the same payload must resolve to the SAME durable "
        "event — a different event_id here means the SHA-256 fixture dedup key "
        "failed to recognize the redelivery as the same event"
    )
    assert r1.json()["status"] == "accepted"
    assert r2.json()["status"] == "duplicate"

    # Drain the durable ingest boundary synchronously to EMPTY — see the
    # docstring above for why this replaces the old assumption that the
    # webhook itself already did this work in-request, and the _drain_all
    # docstring for why one drain_once() call is not enough here: the r1/r2
    # INGEST job itself enqueues a RUN_PIPELINE job on success, and a bare
    # single call could claim EITHER one depending on queue state.
    _drain_all()

    # A THIRD delivery: a genuinely DIFFERENT event (different top-level `id`,
    # so a different raw-byte hash and a different inbound_events row) carrying
    # the SAME message_id. This is what actually exercises the message_id-level
    # dedup the test's docstring is about — see the docstring for why r1/r2
    # alone cannot reach it.
    payload_distinct_event = dict(payload, id=str(_uuid_module.uuid4()))
    r3 = test_client.post("/webhook/inbound", json=payload_distinct_event)
    assert r3.status_code == 200, f"Third POST must return 200; got {r3.status_code}"
    assert r3.json()["status"] == "accepted", (
        "a genuinely different event must be accepted as new at the event layer "
        "— only the shared message_id should be deduplicated, one layer deeper"
    )
    assert r3.json()["event_id"] != r1.json()["event_id"], (
        "the third delivery must be a DISTINCT event from r1/r2, or this test "
        "would just be re-proving the event-layer dedup a second time"
    )
    _drain_all()

    # Verify only one email_messages row exists for this message_id (DB-level assertion).
    # The ON CONFLICT DO NOTHING constraint is the correctness backstop.
    # We query the DB directly to confirm only one row was inserted.
    from app.db.supabase import get_pool
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM email_messages WHERE message_id = %s",
            (dedup_mid,),
        ).fetchone()
    assert row is not None and row[0] == 1, (
        f"Only ONE email_messages row must exist for the duplicate message_id "
        f"(got {row[0] if row else 'None'}) — ON CONFLICT DO NOTHING must deduplicate"
    )
