"""RFC Message-ID dedup race through durable receipt and delayed ingest.

Two real OS threads commit distinct transport events carrying one RFC ``message_id``.
Two more barrier-released threads then drive the committed event identifiers through
the real delayed-ingest handler against Postgres. Exactly one email, run, and downstream
RUN_PIPELINE job may survive the RFC-identity race.

Skip-guarded on DATABASE_URL, evaluated once at import time (matches the
`_HAS_DB` pattern several other test modules define locally) rather than
re-checked inside the test body: a suite-wide fixture may stub DATABASE_URL
in os.environ for tests that lack a real DSN, and a runtime re-check of the
raw environment variable would see that stub and wrongly proceed to run
live-DB logic against a fake host. An import-time constant is captured
before any fixture runs, so it cannot be affected by one.
This is a SEPARATE test module from tests/test_webhook.py and does NOT inherit
that module's client fixture's env setup — pytest does not share monkeypatch
state across test modules, so this module sets ALLOW_UNSIGNED_FIXTURES=true
itself before constructing its own TestClient, or every POST would 400 on
signature rejection before ever reaching the dedup-insert logic this test exists
to prove.
"""
from __future__ import annotations

import ast
import os
import pathlib
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

_HAS_DB = bool(os.environ.get("DATABASE_URL"))


@pytest.mark.integration
def test_duplicate_webhook_delivery_creates_exactly_one_run(monkeypatch):
    """Distinct transport events with one RFC identity create exactly one run."""
    if not _HAS_DB:
        pytest.skip("DATABASE_URL not set — skipping live-DB integration test")

    from app.config import get_settings

    get_settings.cache_clear()
    # Mirrors tests/test_webhook.py's client fixture pattern verbatim. This module does
    # NOT inherit that fixture's env setup, so every POST here would otherwise receive a
    # 400 (unsigned webhook rejected) before ever reaching the dedup-insert logic this
    # test exists to prove.
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")

    from fastapi.testclient import TestClient

    import app.main as app_main
    import app.routes.pipeline_glue as pipeline_glue_mod
    from app.db import repo
    from app.email import gateway
    from app.models.job import Job, JobKind
    from app.queue import wake
    from app.queue.handlers import ingest as ingest_handler
    from app.queue.handlers import pipeline, resume_reply

    real_parse_inbound = gateway.parse_inbound
    real_handle_ingest = ingest_handler.handle_ingest

    def _forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("webhook request executed provider or payroll work inline")

    monkeypatch.setattr(gateway, "parse_inbound", _forbidden)
    monkeypatch.setattr(pipeline_glue_mod, "run_pipeline_now", _forbidden)
    monkeypatch.setattr(pipeline_glue_mod, "resume_pipeline_now", _forbidden)
    monkeypatch.setattr(ingest_handler, "handle_ingest", _forbidden)
    monkeypatch.setattr(pipeline, "handle_run_pipeline", _forbidden)
    monkeypatch.setattr(resume_reply, "handle_resume_reply", _forbidden)
    wakes: list[str] = []
    monkeypatch.setattr(wake, "wake", lambda: wakes.append("wake"))

    client = TestClient(app_main.app)

    same_message_id = f"<race-{uuid.uuid4()}@acme.test>"
    def _payload() -> dict[str, Any]:
        return {
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

    payloads = [_payload(), _payload()]

    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    request_barrier = threading.Barrier(2, timeout=30)

    def _post(payload: dict[str, Any]) -> None:
        request_barrier.wait()
        r = client.post("/webhook/inbound", json=payload)
        with lock:
            results.append({"status_code": r.status_code, **r.json()})

    t1 = threading.Thread(target=_post, args=(payloads[0],))
    t2 = threading.Thread(target=_post, args=(payloads[1],))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    assert {r["status_code"] for r in results} == {200}
    assert {r["status"] for r in results} == {"accepted"}
    event_ids = {uuid.UUID(r["event_id"]) for r in results}
    assert len(event_ids) == 2, "the request race must commit two transport identities"
    assert len(wakes) == 2

    with repo.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, run_id, email_id, operator_resolution_id, event_id,
                   attempts, max_attempts, lease_token, dedup_key, state
              FROM jobs
             WHERE event_id = ANY(%s)
            """,
            (list(event_ids),),
        ).fetchall()
    assert len(rows) == 2
    assert {row[1] for row in rows} == {JobKind.INGEST.value}
    assert {uuid.UUID(str(row[5])) for row in rows} == event_ids
    assert {row[9] for row in rows} == {f"ingest:{event_id}" for event_id in event_ids}
    assert {row[10] for row in rows} == {"pending"}
    assert all(row[2] is None and row[3] is None and row[4] is None for row in rows)

    monkeypatch.setattr(gateway, "parse_inbound", real_parse_inbound)
    monkeypatch.setattr(ingest_handler, "handle_ingest", real_handle_ingest)
    ingest_jobs = [
        Job(
            id=uuid.UUID(str(row[0])),
            kind=JobKind.INGEST,
            run_id=None,
            email_id=None,
            operator_resolution_id=None,
            event_id=uuid.UUID(str(row[5])),
            attempts=int(row[6]),
            max_attempts=int(row[7]),
            lease_token=(
                uuid.UUID(str(row[8])) if row[8] is not None else uuid.uuid4()
            ),
        )
        for row in rows
    ]
    ingest_barrier = threading.Barrier(2, timeout=30)
    handler_results = []

    def _process(job: Job) -> None:
        ingest_barrier.wait()
        result = real_handle_ingest(job)
        with lock:
            handler_results.append(result)

    workers = [threading.Thread(target=_process, args=(job,)) for job in ingest_jobs]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(handler_results) == 2
    assert {result.outcome.value for result in handler_results} == {"ok"}

    with repo.get_connection() as conn:
        email_row = conn.execute(
            "SELECT id, count(*) OVER () FROM email_messages WHERE message_id = %s",
            (same_message_id,),
        ).fetchone()
        assert email_row is not None and email_row[1] == 1
        run_rows = conn.execute(
            "SELECT id FROM payroll_runs WHERE source_email_id = %s",
            (email_row[0],),
        ).fetchall()
        pipeline_rows = conn.execute(
            """
            SELECT kind, dedup_key, run_id, email_id, operator_resolution_id, event_id
              FROM jobs
             WHERE kind = 'run_pipeline' AND run_id = ANY(%s)
            """,
            ([row[0] for row in run_rows],),
        ).fetchall()
    assert len(run_rows) == 1
    run_id = uuid.UUID(str(run_rows[0][0]))
    assert pipeline_rows == [
        (JobKind.RUN_PIPELINE.value, f"run_pipeline:{run_id}:0", run_id, None, None, None)
    ]

    get_settings.cache_clear()


@pytest.mark.integration
@pytest.mark.queueproof
@pytest.mark.proof(id="PROOF-02")
def test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run(
    monkeypatch,
    seeded_db: None,
):
    """One authenticated transport identity stays singular across a DB race.

    PROOF-02 (ROADMAP criterion 2): a redelivery of the same Svix event must
    survive as exactly one `inbound_events` row, one `jobs` row, one
    `payroll_runs` row, and one `email_messages` row. The four "exactly one"
    assertions below establish each of those in turn:
      - `event_count == 1` (line ~286) — one `inbound_events` row.
      - `len(job_rows) == 1` (line ~287) — one `jobs` row.
      - `email_row[1] == 1` (line ~312) — one `email_messages` row.
      - `run_count == 1` (line ~319) — one `payroll_runs` row.

    REQUIREMENTS' named vacuity condition for PROOF-02 is that this would be
    trivially true if the dedup key were something available only AFTER the
    provider fetch (the RFC `Message-ID`) — a key that is unstable across
    concurrent deliveries would make this proof empty. That premise is now a
    checked fact, not prose: `test_prefetch_dedup_key_derivation_guard` below
    asserts, via `ast`, that `external_event_id` (the two-layer dedup's Layer
    0 — see `app/db/repo/inbound_events.py`'s `ON CONFLICT
    (external_event_id) DO NOTHING`) derives ONLY from `request.headers`
    (signed path) or the raw request body (fixture path), and that no
    provider-message parse/fetch call happens before the durable-receipt
    handoff. The RFC `Message-ID` cannot serve as this layer's key precisely
    because it is Layer 1 — `email_messages.message_id UNIQUE` — read only
    after the provider fetch, which runs inside the delayed ingest worker
    (never inline in this webhook request) so the request path never blocks
    on it. Layer 0 (this test) dedups the DELIVERY; Layer 1 dedups the
    MESSAGE.
    """
    if not _HAS_DB:
        pytest.skip("DATABASE_URL not set — skipping live-DB integration test")

    from fastapi.testclient import TestClient

    import app.main as app_main
    from app.config import get_settings
    from app.db import repo
    from app.email import gateway
    from app.models.contracts import InboundEmail
    from app.models.job import Job, JobKind
    from app.queue import wake
    from app.queue.handlers import ingest as ingest_handler

    get_settings.cache_clear()
    event_key = f"evt_same_svix_{uuid.uuid4()}"
    message_id = f"<same-svix-{uuid.uuid4()}@acme.test>"
    payload = {"data": {"email_id": f"em_{uuid.uuid4()}"}}
    parsed_email = InboundEmail(
        id=uuid.uuid4(),
        message_id=message_id,
        in_reply_to=None,
        references_header=None,
        subject="Payroll hours",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular hours.",
        created_at=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(gateway, "verify", lambda body, headers, secret: None)
    monkeypatch.setattr(gateway, "parse_inbound", lambda stored: parsed_email)
    wakes: list[str] = []
    monkeypatch.setattr(wake, "wake", lambda: wakes.append("wake"))
    client = TestClient(app_main.app)
    barrier = threading.Barrier(2, timeout=30)
    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    def _post() -> None:
        barrier.wait()
        response = client.post(
            "/webhook/inbound",
            json=payload,
            headers={
                "svix-id": event_key,
                "svix-timestamp": "1784160000",
                "svix-signature": "v1,test",
            },
        )
        with lock:
            results.append({"status_code": response.status_code, **response.json()})

    workers = [threading.Thread(target=_post) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(results) == 2
    assert {result["status_code"] for result in results} == {200}
    assert {result["status"] for result in results} == {"accepted", "duplicate"}
    assert len({result["event_id"] for result in results}) == 1
    assert wakes == ["wake"]

    event_id = uuid.UUID(results[0]["event_id"])
    with repo.get_connection() as conn:
        event_count_row = conn.execute(
            "SELECT count(*) FROM inbound_events WHERE external_event_id = %s",
            (event_key,),
        ).fetchone()
        job_rows = conn.execute(
            """
            SELECT id, attempts, max_attempts, lease_token
              FROM jobs
             WHERE kind = 'ingest' AND event_id = %s
            """,
            (str(event_id),),
        ).fetchall()
    assert event_count_row is not None
    event_count = event_count_row[0]
    assert event_count == 1
    assert len(job_rows) == 1

    job_row = job_rows[0]
    result = ingest_handler.handle_ingest(
        Job(
            id=uuid.UUID(str(job_row[0])),
            kind=JobKind.INGEST,
            run_id=None,
            event_id=event_id,
            attempts=int(job_row[1]),
            max_attempts=int(job_row[2]),
            lease_token=(
                uuid.UUID(str(job_row[3]))
                if job_row[3] is not None
                else uuid.uuid4()
            ),
        )
    )
    assert result.outcome.value == "ok"

    with repo.get_connection() as conn:
        email_row = conn.execute(
            "SELECT id, count(*) OVER () FROM email_messages WHERE message_id = %s",
            (message_id,),
        ).fetchone()
        assert email_row is not None and email_row[1] == 1
        run_count_row = conn.execute(
            "SELECT count(*) FROM payroll_runs WHERE source_email_id = %s",
            (email_row[0],),
        ).fetchone()
    assert run_count_row is not None
    run_count = run_count_row[0]
    assert run_count == 1
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# PROOF-02's pre-fetch guard: an AST/dataflow check over app/routes/webhook.py,
# not a text search (a comment can satisfy a text search; this repo has already
# been burned by a verification grep that silently lied).
#
# Two structural properties, each pinning one half of REQUIREMENTS' named
# vacuity condition for PROOF-02 ("vacuous if dedup is keyed on something
# available only post-fetch"):
#
#   1. Every assignment to `external_event_id` inside the webhook handler
#      derives from `request.headers` (the signed, authenticated path) or the
#      raw request body (the explicitly-opt-in fixture path) — never from a
#      fetched provider message. Matched on the assignment VALUE's node
#      structure (a Subscript of `request.headers` keyed the constant
#      "svix-id"), not on a rendered source string, so a resolver limited to
#      string literals could not see it.
#   2. No call to a provider message-parse/fetch seam appears, by AST node
#      position, before the `_persist_verified_receipt_sync` durable-receipt
#      handoff inside the same handler.
#
# Mirrors the AST-over-source idiom already established by
# tests/test_bound01_private_imports.py (scan_tree_for_violations) and
# tests/test_fake_repo_pairing.py: pure detection functions, scanned against
# the live tree by one test, and proven reachable against a synthetic
# violation by companion tests — so a scanner that silently finds nothing
# stays distinguishable from a scanner that correctly finds nothing.
# ---------------------------------------------------------------------------

_WEBHOOK_SOURCE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "app" / "routes" / "webhook.py"
)
_HANDLER_FUNCTION_NAME = "inbound"
_PERSIST_HANDOFF_NAME = "_persist_verified_receipt_sync"

# Enumerated from live source (app/email/gateway.py, app/queue/handlers/ingest.py)
# rather than guessed: any call to one of these names is a provider
# message-parse/fetch. Written as a named constant, not inlined into the check
# below, so a future seam rename reds this guard instead of silently widening
# the hole it exists to close.
_PROVIDER_PARSE_SEAM_NAMES = {"parse_inbound", "process_inbound_event"}


def _find_function(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Locate a top-level-or-nested function/coroutine `FunctionDef` by name."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"no function named {name!r} found in the parsed tree")


def _is_signed_path_header_derivation(value: ast.expr) -> bool:
    """True for exactly `request.headers["svix-id"]`: a Subscript of the
    attribute access `request.headers`, keyed by the string constant
    "svix-id". Matches the ASSIGNMENT VALUE's node structure, not a rendered
    source string — a differently-derived value (a different header, a
    fetched-message field, a hardcoded constant) fails this shape check even
    though it might still satisfy a naive text search for "svix-id".
    """
    if not isinstance(value, ast.Subscript):
        return False
    receiver = value.value
    if not (isinstance(receiver, ast.Attribute) and receiver.attr == "headers"):
        return False
    if not (isinstance(receiver.value, ast.Name) and receiver.value.id == "request"):
        return False
    key = value.slice
    return isinstance(key, ast.Constant) and key.value == "svix-id"


def _is_raw_body_digest_derivation(value: ast.expr) -> bool:
    """True for the explicitly-opt-in fixture branch's derivation: any
    expression embedding a call rooted at `hashlib` (the raw-body digest,
    `hashlib.sha256(raw_body).hexdigest()`) — content-addressed on the
    request body actually received, never on a fetched provider message.
    """
    for node in ast.walk(value):
        if not isinstance(node, ast.Call):
            continue
        root: ast.expr = node.func
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name) and root.id == "hashlib":
            return True
    return False


def _external_event_id_assignments(handler: ast.AST) -> list[ast.Assign]:
    """Every `ast.Assign` inside `handler` whose sole target is the name
    `external_event_id`, in the order `ast.walk` visits them."""
    assigns: list[ast.Assign] = []
    for node in ast.walk(handler):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "external_event_id":
            assigns.append(node)
    return assigns


def _check_signed_path_derivation(
    tree: ast.Module, function_name: str = _HANDLER_FUNCTION_NAME
) -> list[str]:
    """Return violation strings unless EVERY assignment to `external_event_id`
    inside `function_name` derives from `request.headers['svix-id']` or the
    raw-body digest, AND at least one such assignment is the header-derived
    (signed-path) one. An empty return means the pre-fetch property holds.
    """
    handler = _find_function(tree, function_name)
    assigns = _external_event_id_assignments(handler)
    if not assigns:
        return [
            f"no assignment to 'external_event_id' found in {function_name}() — "
            "the signed-path pre-fetch derivation this guard protects cannot be located"
        ]

    violations: list[str] = []
    found_header_derivation = False
    for assign in assigns:
        value = assign.value
        if _is_signed_path_header_derivation(value):
            found_header_derivation = True
            continue
        if _is_raw_body_digest_derivation(value):
            continue
        violations.append(
            f"line {assign.lineno}: 'external_event_id' is assigned from "
            f"{ast.dump(value)}, which is neither request.headers['svix-id'] "
            "nor a raw-body digest — it may be reading a value only available "
            "after a provider fetch"
        )
    if not found_header_derivation:
        violations.append(
            "no assignment derives 'external_event_id' from "
            "request.headers['svix-id'] — the signed-path pre-fetch "
            "derivation PROOF-02's vacuity condition requires is missing"
        )
    return violations


def _preorder_positions(node: ast.AST) -> dict[int, int]:
    """Map `id(node)` -> its index in one full pre-order traversal of `node`'s
    subtree, walking each node's child fields in their declared (source)
    order via `ast.iter_child_nodes`. This is a STRUCTURAL position derived
    purely from the AST's own child ordering — never from `.lineno` /
    `.col_offset` file-text coordinates — so the ordering check below compares
    AST node positions, not line numbers read from the file.
    """
    positions: dict[int, int] = {}
    counter = 0

    def _visit(current: ast.AST) -> None:
        nonlocal counter
        positions[id(current)] = counter
        counter += 1
        for child in ast.iter_child_nodes(current):
            _visit(child)

    _visit(node)
    return positions


def _call_target_name(call: ast.Call) -> str | None:
    """The bare or attribute name a Call node invokes (`foo(...)` -> "foo",
    `mod.foo(...)` -> "foo"), or None for a call through a non-name/attribute
    expression this guard has no seam name to compare against."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _check_no_provider_parse_before_handoff(
    tree: ast.Module, function_name: str = _HANDLER_FUNCTION_NAME
) -> list[str]:
    """Return violation strings if any call to a name in
    `_PROVIDER_PARSE_SEAM_NAMES` occupies an earlier AST position, within
    `function_name`'s body, than the reference to `_PERSIST_HANDOFF_NAME`
    (the durable-receipt handoff). An empty return means no provider
    message-parse/fetch call happens before the handoff.
    """
    handler = _find_function(tree, function_name)
    positions = _preorder_positions(handler)

    handoff_position: int | None = None
    for node in ast.walk(handler):
        if isinstance(node, ast.Name) and node.id == _PERSIST_HANDOFF_NAME:
            position = positions[id(node)]
            if handoff_position is None or position < handoff_position:
                handoff_position = position
    if handoff_position is None:
        return [
            f"no reference to {_PERSIST_HANDOFF_NAME!r} found in {function_name}() "
            "— the durable-receipt handoff this guard orders against cannot be located"
        ]

    violations: list[str] = []
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        name = _call_target_name(node)
        if name in _PROVIDER_PARSE_SEAM_NAMES and positions[id(node)] < handoff_position:
            violations.append(
                f"line {node.lineno}: call to provider parse/fetch seam {name!r} "
                f"occupies an earlier AST position than the {_PERSIST_HANDOFF_NAME!r} "
                "durable-receipt handoff"
            )
    return violations


@pytest.mark.integration
@pytest.mark.queueproof
def test_prefetch_dedup_key_derivation_guard() -> None:
    """PROOF-02's vacuity condition, closed as a checked fact over live source.

    PROOF-02 is vacuous if dedup is keyed on something available only
    post-fetch — specifically, the RFC `Message-ID`, which is Layer 1
    (`email_messages.message_id UNIQUE`) and is not read until the provider
    fetch that runs inside the delayed ingest worker, never inline in this
    webhook request. This test pins that premise structurally instead of
    leaving it as prose: it asserts, via `ast`, that Layer 0's key
    (`external_event_id`, the `inbound_events.external_event_id UNIQUE` /
    `ON CONFLICT (external_event_id) DO NOTHING` arbiter's key — see
    app/db/repo/inbound_events.py) derives only from the request transport
    (headers or raw body) inside app/routes/webhook.py's `inbound` handler,
    and that no provider-message parse/fetch call happens before the
    handler's durable-receipt transaction. This guard, not a behavioural
    mutation elsewhere, is what pins the "unavailable until after the fetch"
    premise; a stability mutation only falsifies a narrower, separate claim
    (dedup-key stability). Carries `integration`/`queueproof`, not `proof`:
    exactly one test (above) carries the PROOF-02 id.
    """
    source = _WEBHOOK_SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_WEBHOOK_SOURCE_PATH))

    violations = _check_signed_path_derivation(tree) + _check_no_provider_parse_before_handoff(
        tree
    )
    assert not violations, (
        "PROOF-02 pre-fetch dedup-key guard violation(s) in "
        f"{_WEBHOOK_SOURCE_PATH}:\n" + "\n".join(violations)
    )


def test_signed_path_guard_reds_when_assignment_is_repointed() -> None:
    """Proves `_check_signed_path_derivation` is reachable, not dead code.

    Rather than temporarily editing the live app/routes/webhook.py file and
    reverting it (stateful, and unnecessary since the check function is pure
    over whatever AST it is given), this constructs a synthetic handler whose
    `external_event_id` is repointed at an unrelated expression and confirms
    the SAME check function reds on it — the codebase's established idiom
    for proving a scanner's own detection logic
    (tests/test_bound01_private_imports.py's
    test_scanner_detects_synthetic_violation uses the equivalent tmp_path
    form). Equivalent in rigor to a literal mutate-observe-revert cycle: the
    function under test never inspects anything but its AST argument.
    """
    synthetic_source = (
        "def inbound(request):\n"
        "    external_event_id = some_unrelated_value\n"
        "    result = _persist_verified_receipt_sync(external_event_id)\n"
        "    return result\n"
    )
    tree = ast.parse(synthetic_source)

    violations = _check_signed_path_derivation(tree)

    assert violations, "expected a violation when 'external_event_id' is repointed"
    assert any("external_event_id" in v for v in violations)
    assert any("some_unrelated_value" in v or "no assignment derives" in v for v in violations)


def test_ordering_guard_reds_when_provider_parse_precedes_handoff() -> None:
    """Proves `_check_no_provider_parse_before_handoff` is reachable.

    Synthetic handler mirroring the live shape, but with a provider
    parse/fetch call inserted BEFORE the durable-receipt handoff reference —
    the exact defect shape this check exists to catch (a future refactor
    that starts reading the fetched message before the receipt commits).
    """
    synthetic_source = (
        "def inbound(request):\n"
        "    parsed = gateway.parse_inbound(raw_body)\n"
        "    result = _persist_verified_receipt_sync(external_event_id)\n"
        "    return result\n"
    )
    tree = ast.parse(synthetic_source)

    violations = _check_no_provider_parse_before_handoff(tree)

    assert violations, "expected a violation when provider parsing precedes the handoff"
    assert any("parse_inbound" in v for v in violations)


def test_ordering_guard_is_clean_when_no_provider_parse_seam_appears() -> None:
    """Confirms the ordering check does not false-positive against a handler
    whose only calls are unrelated to the enumerated provider parse/fetch
    seam names — proving the live-source guard's clean result reflects an
    actual absence, not an ordering check that never fires."""
    synthetic_source = (
        "def inbound(request):\n"
        "    validated = _validated_payload(raw_body, allow_unsigned_fixture)\n"
        "    result = _persist_verified_receipt_sync(external_event_id)\n"
        "    return result\n"
    )
    tree = ast.parse(synthetic_source)

    violations = _check_no_provider_parse_before_handoff(tree)

    assert not violations
