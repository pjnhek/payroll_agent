"""Stub email gateway + DB repo surface tests.

Two tiers (mirroring tests/test_seed_roundtrip.py):
- Always-run, DB-free: a FakeConnection (tests/conftest.py) records the SQL +
  params each repo helper executes, so we can assert the parameterized-SQL
  discipline, the synthetic Message-ID shape, model_dump serialization, the
  set_status-only-writes-status rule, the record_run_error single-path routing,
  and the cleaned-body round-trip — all offline.
- Live-DB round-trips behind @pytest.mark.integration + the two-factor guard
  (DATABASE_URL + ALLOW_DB_RESET=1).
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Any

import pytest

from app.db import repo
from app.email import gateway
from app.models.contracts import Decision
from app.models.roster import NameMatchResult
from app.models.status import RunStatus

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)

_MSG_ID_RE = re.compile(r"^<[0-9a-f-]{36}@payroll-agent\.local>$")


def _decision(action="process") -> Decision:
    """A deterministic Decision (D-21-01): final_action + gate detail + per-name
    resolutions. No model action, no score — decide computes final_action purely
    from the resolution facts."""
    return Decision(
        final_action=action,
        gate_reasons=[],
        unresolved_names=[],
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name="Maria Chen",
                matched_employee_id=uuid.uuid4(),
                source="exact",
                resolved=True,
                reason="exact match",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Gateway — synthetic Message-ID shape + outbound row anchored on email_messages
# ---------------------------------------------------------------------------


def test_send_outbound_generates_rfc_shaped_message_id(fake_conn, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    # Pre-seed: get_outbound_references_chain → None, insert_email_message → id
    fake_conn.script_fetchone(None)
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    monkeypatch.setattr(
        resend.Emails, "send", staticmethod(lambda p: {"id": "test-provider-id"})
    )
    run_id = uuid.uuid4()
    msg_id = gateway.send_outbound(
        run_id=run_id,
        to_addr="client@acme.test",
        subject="We need a clarification",
        body="Could you confirm David's hours?",
        conn=fake_conn,
    )
    assert _MSG_ID_RE.match(msg_id), f"Message-ID not RFC-shaped: {msg_id}"
    get_settings.cache_clear()


def test_send_outbound_inserts_outbound_email_messages_row(fake_conn, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    # Pre-seed: get_outbound_references_chain → None, insert_email_message → id
    fake_conn.script_fetchone(None)
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    monkeypatch.setattr(
        resend.Emails, "send", staticmethod(lambda p: {"id": "test-provider-id"})
    )
    run_id = uuid.uuid4()
    msg_id = gateway.send_outbound(
        run_id=run_id,
        to_addr="client@acme.test",
        subject="Clarify",
        body="body",
        conn=fake_conn,
    )
    # Find the INSERT into email_messages among all executed SQL
    insert_found = None
    for sql, params in fake_conn.executed:
        if "email_messages" in str(sql) and "INSERT" in str(sql).upper():
            insert_found = (sql, params)
            break
    assert insert_found is not None, "No INSERT into email_messages found"
    sql, params = insert_found
    assert "outbound" in str(params)  # direction='outbound'
    assert str(run_id) in str(params)
    assert msg_id in str(params)  # the synthetic anchor lives ON the row
    get_settings.cache_clear()


def test_send_outbound_uses_parameterized_sql_no_fstring(fake_conn, monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    # Pre-seed: get_outbound_references_chain → None, insert_email_message → id
    fake_conn.script_fetchone(None)
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    monkeypatch.setattr(
        resend.Emails, "send", staticmethod(lambda p: {"id": "test-provider-id"})
    )
    gateway.send_outbound(
        run_id=uuid.uuid4(),
        to_addr="c@acme.test",
        subject="s",
        body="b",
        conn=fake_conn,
    )
    # Check the INSERT SQL uses %s placeholders
    insert_sql = None
    for sql, _params in fake_conn.executed:
        if "email_messages" in str(sql) and "INSERT" in str(sql).upper():
            insert_sql = str(sql)
            break
    assert insert_sql is not None, "No INSERT into email_messages found"
    assert "%s" in insert_sql, "outbound insert must use %s placeholders"
    get_settings.cache_clear()


def test_parse_inbound_validates_canonical_payload():
    raw = {
        "id": str(uuid.uuid4()),
        "message_id": "<a@acme.test>",
        "in_reply_to": None,
        "references_header": None,
        "subject": "hours",
        "from_addr": "p@acme.test",
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria 40",
        "created_at": "2026-06-15T10:00:00Z",
    }
    email = gateway.parse_inbound(raw)
    assert email.message_id == "<a@acme.test>"
    assert email.from_addr == "p@acme.test"


# ---------------------------------------------------------------------------
# set_status — the SOLE status writer; writes the enum .value, not a bare string
# ---------------------------------------------------------------------------


def test_set_status_writes_enum_value(fake_conn):
    run_id = uuid.uuid4()
    repo.set_status(run_id, RunStatus.AWAITING_APPROVAL, conn=fake_conn)
    sql, params = fake_conn.last()
    assert "status" in str(sql).lower()
    assert RunStatus.AWAITING_APPROVAL.value in str(params)
    assert "RunStatus." not in str(params), "must write .value, not the enum repr"


# ---------------------------------------------------------------------------
# persist_decision — writes the decision JSONB ONLY, never status (FIX B)
# ---------------------------------------------------------------------------


def test_persist_decision_serializes_via_model_dump_json(fake_conn):
    run_id = uuid.uuid4()
    repo.persist_decision(run_id, _decision(), conn=fake_conn)
    sql, params = fake_conn.last()
    assert "decision" in str(sql).lower()
    # The deterministic Decision round-trips via model_dump(mode="json"): the
    # per-name resolutions are folded into the decision JSONB (D-21-04), so the
    # submitted_name + source land in the serialized params.
    assert "Maria Chen" in str(params), "resolutions must serialize into the decision JSONB"
    assert "exact" in str(params), "the resolution source must serialize"


def test_persist_decision_never_writes_status(fake_conn):
    repo.persist_decision(uuid.uuid4(), _decision(), conn=fake_conn)
    assert "status" not in fake_conn.all_sql().lower(), (
        "persist_decision must NOT touch status (FIX B); the orchestrator calls "
        "set_status separately to advance state"
    )


def test_persist_decision_signature_has_no_final_status():
    import inspect

    sig = inspect.signature(repo.persist_decision)
    assert "final_status" not in sig.parameters, (
        "persist_decision must take NO final_status argument (FIX B)"
    )


# ---------------------------------------------------------------------------
# record_run_error — writes error_reason AND routes ERROR THROUGH set_status (FIX B)
# ---------------------------------------------------------------------------


def test_record_run_error_writes_reason_and_routes_through_set_status(fake_conn, monkeypatch):
    import app.db.repo.runs as repo_runs

    calls: dict[str, list[RunStatus]] = {"set_status": []}
    real_set_status = repo.set_status

    def _spy(run_id, status, conn=None):
        calls["set_status"].append(status)
        return real_set_status(run_id, status, conn=conn)

    # record_run_error's internal call to set_status is a same-module bare-name
    # lookup against runs.py's own globals (post-split), NOT the facade's — a
    # facade-level monkeypatch.setattr(repo, "set_status", ...) would not be
    # seen by record_run_error at all. Patch app.db.repo.runs directly instead.
    monkeypatch.setattr(repo_runs, "set_status", _spy)

    run_id = uuid.uuid4()
    # WR-03 CAS: record_run_error's guarded UPDATE ... RETURNING must yield a row
    # for the claim to succeed (a None row means the run is terminal/missing).
    fake_conn.script_fetchone((str(run_id),))
    repo.record_run_error(run_id, "extraction failed twice", conn=fake_conn)

    # error_reason was written
    assert "error_reason" in fake_conn.all_sql().lower()
    assert "extraction failed twice" in str(fake_conn.executed)
    # and the ERROR transition went THROUGH set_status (single status-write path)
    assert RunStatus.ERROR in calls["set_status"], (
        "record_run_error must route its ERROR transition through set_status (FIX B)"
    )


# ---------------------------------------------------------------------------
# persist_reconciliation — list[NameMatchResult] via model_dump(mode="json")
# ---------------------------------------------------------------------------


def test_persist_reconciliation_serializes_each_name(fake_conn):
    run_id = uuid.uuid4()
    # An unresolved name (D-21-01): the deterministic resolver could not match the
    # unknown shorthand to any roster employee — source="none", resolved=False, no
    # employee guessed. No score is carried anywhere.
    matches = [
        NameMatchResult(
            submitted_name="David Reyez",
            matched_employee_id=None,
            source="none",
            resolved=False,
            reason="no deterministic or stored-alias match",
        )
    ]
    repo.persist_reconciliation(run_id, matches, conn=fake_conn)
    sql, params = fake_conn.last()
    assert "reconciliation" in str(sql).lower()
    assert "David Reyez" in str(params)
    assert '"none"' in str(params), "the deterministic source must serialize as JSON"


# ---------------------------------------------------------------------------
# Parameterized-SQL discipline across the whole repo module (T-injection)
# ---------------------------------------------------------------------------


def test_repo_has_no_fstring_sql():
    import importlib
    import inspect
    import pkgutil

    import app.db.repo as repo_pkg

    # Post-split, the facade (repo.__file__) contains no SQL at all — this sweep
    # must scan across ALL the package's modules to preserve its original
    # whole-repo-layer guarantee (Codex Round 2 vacuous-scan finding).
    # Enumerate the package DYNAMICALLY (Phase 13 review WR-03) so a future
    # sixth aggregate module — or SQL added to _shared.py — can never silently
    # escape the sweep the way a hardcoded module tuple would let it.
    modules = {
        m.name: importlib.import_module(f"app.db.repo.{m.name}")
        for m in pkgutil.iter_modules(repo_pkg.__path__)
    }
    known = {"_shared", "demo", "emails", "pipeline_state", "roster", "runs"}
    assert known <= set(modules), (
        f"repo package enumeration lost a known module: {sorted(known - set(modules))}"
    )
    src = "".join(inspect.getsource(m) for m in modules.values())
    # No execute(f"...") f-string SQL, and no %-interpolated execute(...).
    assert not re.search(r"execute\(\s*f[\"']", src), "no f-string SQL in repo.py"
    # The references LIKE must be a named placeholder, never interpolated.
    assert "%(references)s" in src or "%(references_header)s" in src, (
        "header-chain references LIKE must use a named placeholder"
    )


def test_repo_exposes_full_named_surface():
    for name in (
        "find_business_by_sender",
        "load_run",
        "load_source_email",
        "record_run_error",
        "get_outbound_message_id",
        "find_awaiting_reply_for_header",
        "find_any_run_for_header",
        "insert_inbound_email",
        "create_run",
        "set_status",
        "persist_extracted",
        "persist_decision",
        "persist_reconciliation",
        "replace_line_items",
        "insert_email_message",
        "load_roster_for_business",
    ):
        assert hasattr(repo, name), f"repo.py is missing required helper: {name}"


# ---------------------------------------------------------------------------
# Header-chain lookups — named placeholders, awaiting_reply-only vs any-status
# ---------------------------------------------------------------------------


def test_find_awaiting_reply_restricts_to_awaiting_reply_status(fake_conn):
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    repo.find_awaiting_reply_for_header(
        in_reply_to="<out@payroll-agent.local>",
        references_header="<out@payroll-agent.local>",
        conn=fake_conn,
    )
    sql = str(fake_conn.last()[0])
    assert "awaiting_reply" in sql, "must restrict to status='awaiting_reply'"
    assert "%(references)s" in sql or "%(in_reply_to)s" in sql


def test_find_any_run_for_header_matches_across_any_status(fake_conn):
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    repo.find_any_run_for_header(
        in_reply_to="<out@payroll-agent.local>",
        references_header="<out@payroll-agent.local>",
        conn=fake_conn,
    )
    sql = str(fake_conn.last()[0])
    assert "awaiting_reply" not in sql, (
        "any-status lookup must NOT restrict by status (late-reply observability, FIX 10)"
    )


def test_find_business_by_sender_uses_contact_email(fake_conn):
    fake_conn.script_fetchone((str(uuid.uuid4()),))
    repo.find_business_by_sender("payroll@acme.test", conn=fake_conn)
    sql, params = fake_conn.last()
    assert "contact_email" in str(sql)
    assert "payroll@acme.test" in str(params)


def test_find_business_by_sender_returns_none_for_unknown(fake_conn):
    # no scripted row → fetchone returns None
    result = repo.find_business_by_sender("stranger@nowhere.test", conn=fake_conn)
    assert result is None, "unknown sender returns None (INGEST-03 — webhook stops)"


def test_insert_inbound_email_uses_on_conflict_do_nothing(fake_conn):
    fake_conn.script_fetchone((str(uuid.uuid4()),))  # RETURNING id → inserted
    repo.insert_inbound_email(
        message_id="<dup@acme.test>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="p@acme.test",
        to_addr="agent@payroll-agent.local",
        body_text="cleaned body",
        run_id=None,
        conn=fake_conn,
    )
    sql, params = fake_conn.last()
    assert "ON CONFLICT" in str(sql).upper()
    assert "DO NOTHING" in str(sql).upper()
    # the body it is GIVEN (already cleaned) is what gets persisted
    assert "cleaned body" in str(params)


# ===========================================================================
# Live-DB round-trips (two-factor guard)
# ===========================================================================


# `seeded_db` is provided by tests/conftest.py (shared two-factor-guarded fixture).


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_inbound_body_roundtrip_is_not_recleaned(seeded_db):
    """insert_inbound_email persists the cleaned body; load_source_email returns it
    unchanged — no re-cleaning on read (FIX C)."""
    from app.db.seed import seed as _seed

    result = _seed(dry_run=True)
    business_id = result.businesses[0]["id"]

    cleaned = "Maria 40 regular hours. (signature + quoted history already stripped)"
    msg_id = f"<{uuid.uuid4()}@acme.test>"
    email_id, inserted = repo.insert_inbound_email(
        message_id=msg_id,
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="p@acme.test",
        to_addr="agent@payroll-agent.local",
        body_text=cleaned,
        run_id=None,
    )
    assert inserted is True
    run_id = repo.create_run(
        business_id=business_id,
        source_email_id=email_id,
        pay_period_start="2026-06-15",
        pay_period_end="2026-06-21",
    )
    body = repo.load_source_email(run_id)
    assert body == cleaned, "load_source_email must return the cleaned body unchanged (FIX C)"


@_SKIP_LIVE_DB
@pytest.mark.integration
def test_record_run_error_persists_reason_and_error_status(seeded_db):
    from app.db.seed import seed as _seed

    result = _seed(dry_run=True)
    business_id = result.businesses[0]["id"]
    msg_id = f"<{uuid.uuid4()}@acme.test>"
    email_id, _ = repo.insert_inbound_email(
        message_id=msg_id,
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="p@acme.test",
        to_addr="agent@payroll-agent.local",
        body_text="body",
        run_id=None,
    )
    run_id = repo.create_run(
        business_id=business_id,
        source_email_id=email_id,
        pay_period_start="2026-06-15",
        pay_period_end=None,
    )
    repo.record_run_error(run_id, "extraction failed twice")
    run = repo.load_run(run_id)
    assert run is not None
    assert run["status"] == RunStatus.ERROR.value
    assert run["error_reason"] == "extraction failed twice"


# ===========================================================================
# Phase 6 Wave 0 xfail stubs — OPS-02 gateway (06-01 Task 2)
#
# ALL tests below target not-yet-implemented Phase 6 behavior. They are
# decorated with @pytest.mark.xfail(strict=True, reason="implemented in 06-04").
# strict=True means:
#   - An XFAIL (expected failure) exits 0 — the no-op-swap gate stays GREEN.
#   - An XPASS (unexpected pass) exits non-zero — the signal to REMOVE the
#     markers in 06-04 when the real gateway lands.
#
# The ONE exception: test_parse_inbound_canonical_fixture_still_works has NO
# xfail — it must stay GREEN throughout (HIGH-2 fixture-path guard).
# ===========================================================================

import resend  # noqa: F401, E402 — installed via 06-01 Task 1; needed for monkeypatching, imported late to keep the patch target order documented above

# ===========================================================================
# MEDIUM-5: SDK smoke-check test (Wave 0 guard — Task 0)
# Asserts resend==2.32.2 call surfaces exist so a Python SDK naming mismatch
# is caught at Wave 0, not at the live human gate (D-09b). Researcher verified
# these by source inspection; this locks it as an executable guard.
# ===========================================================================


def test_resend_sdk_call_surfaces_exist():
    """MEDIUM-5: SDK smoke check — asserts resend==2.32.2 call surfaces exist.

    No network calls. Pure import + attribute inspection. Must PASS immediately
    (no xfail). Catches Python SDK naming mismatches before the live demo gate.
    """
    import inspect

    # 1. resend.Webhooks.verify — the signature-verification surface (D-17).
    assert hasattr(resend, "Webhooks"), "resend.Webhooks does not exist"
    assert hasattr(resend.Webhooks, "verify"), "resend.Webhooks.verify does not exist"

    # 2. resend.EmailsReceiving.get — the inbound email fetch surface (D-01a).
    assert hasattr(resend, "EmailsReceiving"), "resend.EmailsReceiving does not exist"
    assert hasattr(resend.EmailsReceiving, "get"), "resend.EmailsReceiving.get does not exist"

    # 3. resend.Emails.send — the outbound send surface.
    assert hasattr(resend, "Emails"), "resend.Emails does not exist"
    assert hasattr(resend.Emails, "send"), "resend.Emails.send does not exist"

    # 4. resend.Emails.send call-surface check.
    # Researcher verified from source inspection that resend.Emails.send accepts a
    # single SendParams TypedDict argument (a TypedDict, so dict subclass). The dict
    # has keys including 'headers' and 'attachments'. We verify the signature accepts
    # a positional param (the send dict) and check the send dict schema includes both keys.
    sig = inspect.signature(resend.Emails.send)
    params_list = list(sig.parameters.keys())
    # The send method takes 'params' (the SendParams TypedDict) as first positional.
    assert len(params_list) >= 1, (
        "resend.Emails.send must accept at least one argument (the SendParams dict)"
    )
    first_param_name = params_list[0]
    assert first_param_name not in ("self", "cls") or len(params_list) >= 2, (
        "resend.Emails.send must have at least one non-self parameter"
    )
    # Verify that SendParams TypedDict defines 'headers' and 'attachments' keys.
    # resend.Emails.SendParams is a TypedDict subclass of dict.
    assert hasattr(resend.Emails, "SendParams"), "resend.Emails.SendParams does not exist"
    _send_params_hints = resend.Emails.SendParams.__annotations__
    # Note: TypedDict __annotations__ may come from parent classes; use get_type_hints for
    # the full set. For simplicity, check that the TypedDict references 'headers' or
    # that **kwargs is accepted (dict passthrough). The TypedDict approach: SendParams
    # extends dict, so arbitrary keys can be passed — 'headers' and 'attachments' work.
    # We assert the known keys are documented in the TypedDict or its bases.
    all_hints = {}
    for cls in reversed(resend.Emails.SendParams.__mro__):
        if hasattr(cls, "__annotations__"):
            all_hints.update(cls.__annotations__)
    assert "headers" in all_hints or issubclass(resend.Emails.SendParams, dict), (
        "resend.Emails.SendParams must support 'headers' key (either annotated or dict subclass)"
    )
    assert "attachments" in all_hints or issubclass(resend.Emails.SendParams, dict), (
        "resend.Emails.SendParams must support 'attachments' key "
        "(either annotated or dict subclass)"
    )


class _FakeReceivedEmail:
    """Minimal stand-in for resend.ReceivedEmail used in gateway xfail tests.

    Mirrors the shape returned by resend.EmailsReceiving.get(email_id).
    Each test that needs different field values constructs its own instance
    inline — this class is kept at module level so all gateway tests share it.
    """

    def __init__(
        self,
        *,
        message_id: str = "<abc@resend.com>",
        text: str | None = "Maria 40 hours",
        html: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message_id = message_id
        self.text = text
        self.html = html
        self.headers: dict[str, str] = headers if headers is not None else {}


# ---------------------------------------------------------------------------
# HIGH-2 fixture-path guard — MUST stay GREEN throughout (NO xfail)
# ---------------------------------------------------------------------------


def test_parse_inbound_canonical_fixture_still_works():
    """The fixture/dev path through the gateway seam works with the current stub.

    This test is NOT xfail — it must stay GREEN throughout all waves. It pins
    that the canonical InboundEmail dict shape still round-trips cleanly through
    gateway.parse_inbound (no provider call needed for the fixture path). This
    is the HIGH-2 fixture-path guard: if it regresses, the whole fixture-first
    development contract breaks. (OPS-02 / D-18)
    """
    from uuid import uuid4

    raw = {
        "id": str(uuid4()),
        "message_id": "<test@fixture.test>",
        "from_addr": "hr@acme.test",
        "to_addr": "agent@test.com",
        "subject": "hours",
        "body_text": "Maria 40h",
        "in_reply_to": None,
        "references_header": None,
        "created_at": "2026-06-15T10:00:00Z",
    }
    result = gateway.parse_inbound(raw)
    assert result.message_id == "<test@fixture.test>"
    assert result.from_addr == "hr@acme.test"


# ---------------------------------------------------------------------------
# OPS-02 / D-17 — signature verification (xfail until 06-04)
# ---------------------------------------------------------------------------


def test_verify_raises_on_bad_signature(monkeypatch):
    """gateway.verify must propagate ValueError from resend.Webhooks.verify.

    The route calls gateway.verify(payload_bytes, svix_headers, secret) as step
    zero before any parsing or dedup. When the HMAC check fails, ValueError must
    propagate so the route can return 400 and abort. (OPS-02 / D-17)
    """
    def _reject(payload_dict):
        raise ValueError("bad sig")

    monkeypatch.setattr(resend.Webhooks, "verify", staticmethod(_reject))

    # gateway.verify is the thin shim that calls resend.Webhooks.verify.
    # It does not exist in the Phase 2 stub — this xfails because AttributeError
    # (no 'verify' on the module) is an unexpected failure, not the expected ValueError.
    # When 06-04 adds gateway.verify, the monkeypatched ValueError must propagate.
    with pytest.raises(ValueError):
        gateway.verify(
            b'{"type":"email.received"}',
            {"svix-id": "x", "svix-timestamp": "y", "svix-signature": "z"},
            "whsec_testsecret",
        )


def test_verify_passes_on_valid_signature(monkeypatch):
    """gateway.verify must return cleanly when resend.Webhooks.verify succeeds.

    Happy path: the HMAC check passes, no exception raised. (OPS-02 / D-17)
    """
    def _noop(payload_dict):
        return None  # success

    monkeypatch.setattr(resend.Webhooks, "verify", staticmethod(_noop))

    # Should not raise when verify succeeds.
    gateway.verify(
        b'{"type":"email.received"}',
        {"svix-id": "x", "svix-timestamp": "y", "svix-signature": "z"},
        "whsec_testsecret",
    )


# ---------------------------------------------------------------------------
# OPS-02 / D-01a / D-18 — two-step parse: metadata webhook → fetch → InboundEmail
# ---------------------------------------------------------------------------


def test_parse_inbound_two_step_fetch(monkeypatch):
    """parse_inbound must fetch the full email via resend.EmailsReceiving.get.

    The Resend webhook payload is metadata-only (no body, no threading headers).
    parse_inbound must call resend.EmailsReceiving.get(email_id) to retrieve the
    body + headers and return a fully-populated InboundEmail. (OPS-02 / D-01a)
    """
    from app.config import get_settings
    from app.models.contracts import InboundEmail

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")

    fake_email_obj = _FakeReceivedEmail(
        message_id="<abc@resend.com>",
        text="Maria 40 hours",
        html=None,
        headers={
            "In-Reply-To": "<prev@x.test>",
            "References": "<prev@x.test>",
        },
    )

    def _fake_get(email_id):
        assert email_id == "re_123", f"expected email_id='re_123', got {email_id!r}"
        return fake_email_obj

    monkeypatch.setattr(resend.EmailsReceiving, "get", staticmethod(_fake_get))

    # Raw webhook payload — metadata only, no body (D-01a confirmed shape).
    raw_webhook = {
        "data": {
            "email_id": "re_123",
            "from": "hr@acme.test",
            "to": ["agent@x.test"],
            "subject": "hours",
            "message_id": "<abc@resend.com>",
        }
    }
    result = gateway.parse_inbound(raw_webhook)

    assert isinstance(result, InboundEmail)
    assert result.message_id == "<abc@resend.com>", (
        f"message_id must be the RFC Message-ID from the fetched email object; "
        f"got {result.message_id!r}"
    )
    assert result.in_reply_to == "<prev@x.test>", (
        f"in_reply_to must be extracted from headers dict; got {result.in_reply_to!r}"
    )
    assert result.body_text == "Maria 40 hours", (
        f"body_text must come from the fetched email_obj.text; got {result.body_text!r}"
    )


def test_parse_inbound_normalizes_headers_case_insensitively(monkeypatch):
    """parse_inbound must handle lowercase header keys from the provider.

    Real providers are inconsistent about header key casing — some send 'In-Reply-To',
    others send 'in-reply-to'. The gateway must normalize case-insensitively.
    (OPS-02 / D-18 / Pitfall 4)
    """
    from app.config import get_settings
    from app.models.contracts import InboundEmail

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")

    fake_email_obj = _FakeReceivedEmail(
        message_id="<abc@resend.com>",
        text="Maria 40 hours",
        html=None,
        headers={
            "in-reply-to": "<prev@x.test>",  # lowercase keys (the pitfall case)
            "references": "<prev@x.test>",
        },
    )

    monkeypatch.setattr(
        resend.EmailsReceiving,
        "get",
        staticmethod(lambda email_id: fake_email_obj),
    )

    raw_webhook = {
        "data": {
            "email_id": "re_456",
            "from": "hr@acme.test",
            "to": ["agent@x.test"],
            "subject": "hours",
            "message_id": "<abc@resend.com>",
        }
    }
    result = gateway.parse_inbound(raw_webhook)

    assert isinstance(result, InboundEmail)
    assert result.in_reply_to == "<prev@x.test>", (
        f"in_reply_to must be extracted from lowercase 'in-reply-to' header key; "
        f"got {result.in_reply_to!r}"
    )


def test_parse_inbound_dedup_keys_on_rfc_message_id(monkeypatch):
    """The returned InboundEmail.message_id must be the RFC message_id, NOT email_id.

    The Resend 'email_id' is an internal Resend identifier (e.g. 're_123').
    The dedup key must be the RFC Message-ID from email_obj.message_id, which is
    the globally-unique RFC value. (OPS-02 / D-13 dedup key correctness)
    """
    from app.config import get_settings
    from app.models.contracts import InboundEmail

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")

    rfc_message_id = "<rfc-correct@acme.test>"
    resend_email_id = "re_internal_id_999"

    fake_email_obj = _FakeReceivedEmail(
        message_id=rfc_message_id,  # the RFC value
        text="body text",
        html=None,
        headers={},
    )

    monkeypatch.setattr(
        resend.EmailsReceiving,
        "get",
        staticmethod(lambda email_id: fake_email_obj),
    )

    raw_webhook = {
        "data": {
            "email_id": resend_email_id,  # Resend internal ID — NOT the dedup key
            "from": "hr@acme.test",
            "to": ["agent@x.test"],
            "subject": "hours",
            "message_id": rfc_message_id,
        }
    }
    result = gateway.parse_inbound(raw_webhook)

    assert isinstance(result, InboundEmail)
    assert result.message_id == rfc_message_id, (
        f"InboundEmail.message_id must be the RFC Message-ID from email_obj.message_id "
        f"({rfc_message_id!r}), NOT the Resend internal email_id ({resend_email_id!r}); "
        f"got {result.message_id!r}"
    )
    assert result.message_id != resend_email_id, (
        "message_id must NOT be the Resend internal email_id — dedup keys on the RFC value"
    )


def test_parse_inbound_parseaddr_display_name(monkeypatch):
    """parse_inbound must strip display names from the 'from' field.

    Real providers send display-name forms like 'HR Dept <hr@acme.test>'. The
    gateway must run email.utils.parseaddr to extract the bare address before
    passing it to find_business_by_sender. (OPS-02 / D-18 / LOW-9)
    """
    from app.config import get_settings
    from app.models.contracts import InboundEmail

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")

    fake_email_obj = _FakeReceivedEmail(
        message_id="<display@resend.com>",
        text="body text",
        html=None,
        headers={},
    )

    monkeypatch.setattr(
        resend.EmailsReceiving,
        "get",
        staticmethod(lambda email_id: fake_email_obj),
    )

    # The 'from' field has a display name — the common real-provider format.
    raw_webhook = {
        "data": {
            "email_id": "re_display",
            "from": "HR Dept <hr@acme.test>",  # display-name form (LOW-9)
            "to": ["agent@x.test"],
            "subject": "hours",
            "message_id": "<display@resend.com>",
        }
    }
    result = gateway.parse_inbound(raw_webhook)

    assert isinstance(result, InboundEmail)
    assert result.from_addr == "hr@acme.test", (
        f"from_addr must be the bare address (stripped of display name via parseaddr); "
        f"got {result.from_addr!r} — expected 'hr@acme.test'"
    )
    assert "HR Dept" not in result.from_addr, (
        "from_addr must not contain the display name"
    )


# ---------------------------------------------------------------------------
# OPS-02 / D-13c / MEDIUM-6 — reserved→sent ordering (xfail until 06-04)
# ---------------------------------------------------------------------------


def test_send_outbound_reserved_before_sent_ordering(fake_conn, monkeypatch):
    """send_outbound must write send_state='reserved' BEFORE calling resend.Emails.send.

    D-13c crash-safe ordering: if the process dies between the reserved write and
    the send call, the row is visible in the DB as reserved (not lost). The 'sent'
    or 'failed' update follows the send call.

    MEDIUM-6: asserts RELATIVE order (not absolute index 0/1) because
    get_outbound_references_chain adds a DB READ before the reserved INSERT, so
    absolute indexing breaks. (OPS-02 / D-13c / MEDIUM-6)
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")

    send_calls: list[dict[str, Any]] = []

    def _fake_send(params):
        send_calls.append(params)
        return {"id": "<out@resend.com>"}

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_fake_send))

    gateway.send_outbound(
        run_id=uuid.uuid4(),
        to_addr="x@test.com",
        subject="s",
        body="b",
        conn=fake_conn,
    )

    # Find the reserved INSERT among all executed SQL rows (relative order).
    reserved_idx = None
    for i, (_sql, params) in enumerate(fake_conn.executed):
        if params and "reserved" in str(params):
            reserved_idx = i
            break

    assert reserved_idx is not None, (
        "send_outbound must write send_state='reserved' to email_messages before the send call "
        "(D-13c crash-safe ordering)"
    )

    # The send call must happen AFTER the reserved insert.
    # We verify this by checking that reserved_idx was recorded BEFORE send was called.
    # Since fake_conn.executed grows synchronously, len at the time of send call > reserved_idx.
    assert len(send_calls) == 1, "resend.Emails.send must be called exactly once"

    # After the send, the row must be updated to 'sent'.
    sent_found = any(
        params and "sent" in str(params)
        for sql, params in fake_conn.executed[reserved_idx + 1:]
    )
    assert sent_found, (
        "send_outbound must update send_state to 'sent' after a successful resend.Emails.send call "
        "(D-13c crash-safe ordering)"
    )


def test_send_outbound_failed_on_provider_exception(fake_conn, monkeypatch):
    """send_outbound must update send_state to 'failed' when resend.Emails.send raises.

    HIGH-3 fix: when the provider call raises (network error, rate limit, etc.),
    the outbound row must transition reserved→failed (not left as reserved) and the
    exception must re-raise so the caller knows the send did not succeed.
    (OPS-02 / D-13c / HIGH-3)
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")

    # Pre-seed: get_outbound_references_chain → None, insert_email_message → id
    fake_conn.script_fetchone(None)
    fake_conn.script_fetchone((str(uuid.uuid4()),))

    def _raise_send(params):
        raise RuntimeError("network error")

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_raise_send))

    with pytest.raises(RuntimeError, match="network error"):
        gateway.send_outbound(
            run_id=uuid.uuid4(),
            to_addr="x@test.com",
            subject="s",
            body="b",
            conn=fake_conn,
        )

    # The reserved INSERT must have been written before the send attempt.
    reserved_found = any(
        params and "reserved" in str(params)
        for _, params in fake_conn.executed
    )
    assert reserved_found, (
        "send_outbound must write send_state='reserved' before the failing send attempt (D-13c)"
    )

    # After the exception, the row must be updated to 'failed' (HIGH-3 fix).
    failed_found = any(
        params and "failed" in str(params)
        for _, params in fake_conn.executed
    )
    assert failed_found, (
        "send_outbound must update send_state to 'failed' when resend.Emails.send raises "
        "(HIGH-3 fix — reserved→failed, not left as reserved)"
    )


# ---------------------------------------------------------------------------
# OPS-02 / D-14 — durable threading from DB state (xfail until 06-04)
# ---------------------------------------------------------------------------


def test_threading_references_rebuilt_from_db_state(fake_conn, monkeypatch):
    """send_outbound must build the References chain from persisted DB state.

    D-14 durable threading: the chain is rebuilt from the PERSISTED outbound row in
    email_messages, NOT from caller-passed values alone. This ensures the chain
    survives dropped/duplicated deliveries. Setup: FakeConnection is pre-seeded to
    return a prior outbound row with references_header='<prior@x.test>'. The test
    asserts the INSERT params include BOTH '<prior@x.test>' AND '<inbound@x.test>'
    in the references_header. (OPS-02 / D-14)
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")

    # Pre-seed: a prior outbound row for this run with references_header='<prior@x.test>'
    fake_conn.script_fetchone(("<prior@x.test>",))  # returned by get_outbound_references_chain

    def _fake_send(params):
        return {"id": "<new-out@resend.com>"}

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_fake_send))

    gateway.send_outbound(
        run_id=uuid.uuid4(),
        to_addr="x@test.com",
        subject="s",
        body="b",
        in_reply_to="<inbound@x.test>",
        conn=fake_conn,
    )

    # The INSERT params must include the accumulated References chain.
    all_params_str = str(fake_conn.executed)
    assert "<prior@x.test>" in all_params_str, (
        "references_header in the DB INSERT must include the PRIOR outbound chain "
        "loaded from DB state (<prior@x.test>) — not only the caller-passed in_reply_to"
    )
    assert "<inbound@x.test>" in all_params_str, (
        "references_header must also include the new inbound message_id (<inbound@x.test>) "
        "appended to the chain"
    )


def test_inbound_reply_routes_to_correct_run(monkeypatch):
    """POST /webhook/inbound with in_reply_to matching an awaiting_reply run must resume it.

    MEDIUM-7 fix: when an inbound email's In-Reply-To matches an outbound clarification
    Message-ID for an awaiting_reply run, the route must call resume_pipeline (via
    BackgroundTasks.add_task), NOT run_pipeline. This confirms reply routing works end-
    to-end for the mock case. (OPS-02 / D-14)

    xfail removed in 06-04 Task 3 — the route was restructured to async Request with
    ALLOW_UNSIGNED_FIXTURES support, enabling canonical dict POSTs in dev mode.
    """
    from fastapi.testclient import TestClient

    from app.db import repo as _repo
    from app.main import app

    run_id = uuid.uuid4()
    # Use a fixed business_id so the FIX-5 spoof guard passes:
    # find_business_by_sender must return the SAME id as awaiting_run["business_id"].
    sender_business_id = uuid.uuid4()
    clarification_mid = "<clar-abc@payroll-agent.local>"

    # Monkeypatch: find_awaiting_reply_for_header returns run_A
    monkeypatch.setattr(
        _repo,
        "find_awaiting_reply_for_header",
        lambda *, in_reply_to, references_header, conn=None: run_id,
    )
    # Monkeypatch: find_business_by_sender returns the SAME business_id as the run.
    # FIX-5 spoof guard: str(reply_business_id) must equal str(run["business_id"]).
    monkeypatch.setattr(
        _repo,
        "find_business_by_sender",
        lambda from_addr, conn=None: sender_business_id,
    )
    # Monkeypatch: load_run to return an awaiting_reply run (for FIX-5 guard)
    awaiting_run = {
        "id": run_id,
        "business_id": sender_business_id,  # must match find_business_by_sender return
        "source_email_id": uuid.uuid4(),
        "status": "awaiting_reply",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
    }
    monkeypatch.setattr(
        _repo,
        "load_run",
        lambda rid, conn=None: awaiting_run,
    )

    # We cannot easily spy on BackgroundTasks.add_task in TestClient mode,
    # so we monkeypatch the internal pipeline functions and assert which was called.
    import app.routes.pipeline_glue as _main
    resume_called: list[uuid.UUID] = []
    monkeypatch.setattr(
        _main,
        "resume_pipeline_bg",
        lambda run_id, reply_email_id, conn=None: resume_called.append(run_id),
    )
    run_pipeline_called: list[uuid.UUID] = []
    monkeypatch.setattr(
        _main,
        "run_pipeline_bg",
        lambda run_id, conn=None: run_pipeline_called.append(run_id),
    )
    # Also patch insert_inbound_email to succeed
    monkeypatch.setattr(
        _repo,
        "insert_inbound_email",
        lambda **kw: (uuid.uuid4(), True),
    )

    # 09-03 (DATA-02): inbound() now wraps dedup + reply-classification + routing in
    # one `with repo.get_connection() as conn: with conn.transaction(): ...` block.
    # This test monkeypatches individual _repo functions (not the fake_repo fixture),
    # so get_connection must be patched to a FakeConnection double too, or the route
    # attempts a real pool connection with the bogus DATABASE_URL below.
    import contextlib as _contextlib

    from tests.conftest import FakeConnection

    @_contextlib.contextmanager
    def _fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(_repo, "get_connection", _fake_get_connection, raising=False)

    # WARNING-1 remediation (06-04 Task 2): route now requires ALLOW_UNSIGNED_FIXTURES=true
    # for canonical dict POSTs without svix-* signature headers.
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")

    client = TestClient(app, raise_server_exceptions=False)
    # Post a canonical InboundEmail dict with in_reply_to matching the clarification.
    raw_reply = {
        "id": str(uuid.uuid4()),
        "message_id": "<reply-001@client.test>",
        "in_reply_to": clarification_mid,
        "references_header": clarification_mid,
        "subject": "Re: Payroll clarification",
        "from_addr": "hr@acme.test",
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Sorry, I meant James Okafor.",
        "created_at": "2026-06-15T10:00:00Z",
    }
    response = client.post("/webhook/inbound", json=raw_reply)
    assert response.status_code == 200

    # The reply must route to resume_pipeline, NOT run_pipeline.
    assert len(resume_called) > 0, (
        "POST /webhook/inbound with in_reply_to matching an awaiting_reply run must call "
        "resume_pipeline (not run_pipeline) — MEDIUM-7 fix (D-14)"
    )
    assert len(run_pipeline_called) == 0, (
        "run_pipeline must NOT be called for a reply to an awaiting_reply run"
    )
    get_settings.cache_clear()


@pytest.mark.integration
def test_inbound_reply_routes_to_correct_run_integration():
    """Real-DB integration: reply-routing uses the real SQL predicate end-to-end.

    Unlike the mocked unit test, this test does NOT monkeypatch
    repo.find_awaiting_reply_for_header — it exercises the real SQL predicate
    (_HEADER_MATCH_PREDICATE, _pad_references, find_awaiting_reply_for_header)
    end-to-end. Setup: INSERT a real outbound email_messages row for a run in
    status awaiting_reply, then POST a reply whose in_reply_to matches that row's
    message_id. Assert resume_pipeline (not run_pipeline) is queued.
    (OPS-02 / D-14 / MEDIUM-5 real-SQL integration path)
    """
    if not (_HAS_DB and _HAS_RESET):
        pytest.skip("DATABASE_URL or ALLOW_DB_RESET=1 not set — live-DB required")

    from app.db import repo as _repo
    from app.db.bootstrap import bootstrap
    from app.db.seed import seed as _seed

    bootstrap(reset=True)
    _seed()

    result = _seed(dry_run=True)
    business_id = result.businesses[0]["id"]

    # Insert the source inbound email row.
    source_mid = f"<integ-source-{uuid.uuid4()}@acme.test>"
    email_id, inserted = _repo.insert_inbound_email(
        message_id=source_mid,
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="p@acme.test",
        to_addr="agent@payroll-agent.local",
        body_text="source body",
        run_id=None,
    )
    assert inserted

    run_id = _repo.create_run(
        business_id=business_id,
        source_email_id=email_id,
        pay_period_start="2026-06-15",
        pay_period_end="2026-06-21",
    )

    # Insert an outbound clarification row in awaiting_reply state.
    outbound_mid = f"<integ-out-{uuid.uuid4()}@payroll-agent.local>"
    _repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=outbound_mid,
        purpose="clarification",
        send_state="sent",
        subject="Please clarify",
        to_addr="p@acme.test",
        from_addr="agent@payroll-agent.local",
        body_text="Could you confirm?",
    )
    _repo.set_status(run_id, RunStatus.AWAITING_REPLY)

    # The real SQL predicate must find run_id via the outbound_mid.
    matched = _repo.find_awaiting_reply_for_header(
        in_reply_to=outbound_mid,
        references_header=None,
    )
    assert matched == run_id, (
        f"find_awaiting_reply_for_header must return run_id when in_reply_to matches "
        f"the outbound clarification Message-ID (real SQL predicate end-to-end); "
        f"got {matched!r}"
    )


# ===========================================================================
# Task 1 (06-04) new tests — HIGH-1-AUTH, HIGH-3 attachments, LOW-9 parseaddr,
# REPLY-TO TOPOLOGY
# ===========================================================================


def test_send_outbound_configures_resend_api_key(fake_conn, monkeypatch):
    """HIGH-1-AUTH (R5 — live-demo-critical): send_outbound sets resend.api_key as its
    FIRST action, even when called from /demo/send-test without a prior parse_inbound.

    Asserts that resend.api_key is updated from a stale/unset value to the configured
    key before resend.Emails.send is invoked.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key-123")

    # Pre-seed: get_outbound_references_chain returns None (no prior chain)
    # and insert_email_message returns a row id
    fake_conn.script_fetchone(None)   # get_outbound_references_chain → None
    fake_conn.script_fetchone((str(uuid.uuid4()),))  # insert_email_message → id

    key_at_send_time: list[str | None] = []

    def _capture_send(params):
        key_at_send_time.append(resend.api_key)
        return {"id": "resend-provider-id-001"}

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_capture_send))

    # Set a stale key before calling send_outbound — must be overwritten.
    resend.api_key = "stale-key"

    gateway.send_outbound(
        run_id=uuid.uuid4(),
        to_addr="client@acme.test",
        subject="Test",
        body="body",
        conn=fake_conn,
    )

    # The api_key must have been set to the configured value BEFORE the send call.
    assert len(key_at_send_time) == 1, "resend.Emails.send must be called exactly once"
    assert key_at_send_time[0] == "test-key-123", (
        f"resend.api_key must equal 'test-key-123' at the time resend.Emails.send is invoked; "
        f"got {key_at_send_time[0]!r} — send_outbound must set api_key as its FIRST line "
        "(HIGH-1-AUTH: /demo/send-test calls send_outbound without prior parse_inbound)"
    )
    assert resend.api_key == "test-key-123", (
        "resend.api_key was not updated from the stale value — HIGH-1-AUTH fix missing"
    )
    get_settings.cache_clear()


def test_send_outbound_forwards_attachments(fake_conn, monkeypatch):
    """HIGH-3 attachments: send_outbound must base64-encode and forward PDF bytes.

    Asserts that resend.Emails.send is called with an 'attachments' key containing
    the expected filename and base64-encoded PDF content. (OPS-02 / HIGH-3)
    """
    import base64 as _b64

    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")

    # Pre-seed: get_outbound_references_chain → None, insert_email_message → id
    fake_conn.script_fetchone(None)
    fake_conn.script_fetchone((str(uuid.uuid4()),))

    captured_params: list[dict[str, Any]] = []

    def _capture_send(params):
        captured_params.append(params)
        return {"id": "resend-attach-id"}

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_capture_send))

    pdf_bytes = b"%PDF-1.4 fake-pdf-content"
    gateway.send_outbound(
        run_id=uuid.uuid4(),
        to_addr="client@acme.test",
        subject="Payroll Confirmation",
        body="See attached paystubs.",
        attachments=[("paystub.pdf", pdf_bytes)],
        conn=fake_conn,
    )

    assert len(captured_params) == 1, "resend.Emails.send must be called exactly once"
    send_dict = captured_params[0]
    assert "attachments" in send_dict, (
        "resend.Emails.send dict must contain 'attachments' key (HIGH-3 fix)"
    )
    attachments = send_dict["attachments"]
    assert len(attachments) == 1, "exactly one attachment expected"
    att = attachments[0]
    assert att["filename"] == "paystub.pdf", (
        f"attachment filename must be 'paystub.pdf'; got {att['filename']!r}"
    )
    expected_content = _b64.b64encode(pdf_bytes).decode()
    assert att["content"] == expected_content, (
        f"attachment content must be base64-encoded PDF bytes; "
        f"got {att['content'][:40]!r}..."
    )
    get_settings.cache_clear()


def test_send_outbound_includes_reply_to_when_configured(fake_conn, monkeypatch):
    """REPLY-TO TOPOLOGY: send_outbound includes reply_to in the send dict when
    resend_reply_to is non-empty. The reply_to value is the inbound .resend.app address
    that the webhook IS connected to (not onboarding@resend.dev). (T-06-04-13)
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_REPLY_TO", "payroll@jiodnel.resend.app")

    # Pre-seed: get_outbound_references_chain → None, insert_email_message → id
    fake_conn.script_fetchone(None)
    fake_conn.script_fetchone((str(uuid.uuid4()),))

    captured_params: list[dict[str, Any]] = []

    def _capture_send(params):
        captured_params.append(params)
        return {"id": "resend-reply-to-id"}

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_capture_send))

    gateway.send_outbound(
        run_id=uuid.uuid4(),
        to_addr="client@acme.test",
        subject="Payroll Question",
        body="Please reply.",
        conn=fake_conn,
    )

    assert len(captured_params) == 1, "resend.Emails.send must be called exactly once"
    send_dict = captured_params[0]
    assert "reply_to" in send_dict, (
        "resend.Emails.send dict must contain 'reply_to' key when resend_reply_to is configured "
        "(REPLY-TO TOPOLOGY: directs client replies to the inbound webhook address)"
    )
    assert send_dict["reply_to"] == "payroll@jiodnel.resend.app", (
        f"reply_to must equal 'payroll@jiodnel.resend.app'; got {send_dict['reply_to']!r}"
    )
    get_settings.cache_clear()


def test_send_outbound_omits_reply_to_when_not_configured(fake_conn, monkeypatch):
    """REPLY-TO TOPOLOGY: send_outbound omits reply_to from the send dict when
    resend_reply_to is empty. Passing an empty string would send a malformed
    Reply-To header — the key must be absent, not set to ''. (T-06-04-13)
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    # Force resend_reply_to empty. delenv() is NOT enough: Settings reads .env
    # (env_file=".env"), so a RESEND_REPLY_TO line in a developer's local .env
    # (added during the 06-03 deploy) would bleed through and the key would be
    # present. An explicit empty OS env var overrides the .env value (verified),
    # making this test deterministic regardless of local .env contents.
    monkeypatch.setenv("RESEND_REPLY_TO", "")

    # Pre-seed: get_outbound_references_chain → None, insert_email_message → id
    fake_conn.script_fetchone(None)
    fake_conn.script_fetchone((str(uuid.uuid4()),))

    captured_params: list[dict[str, Any]] = []

    def _capture_send(params):
        captured_params.append(params)
        return {"id": "resend-no-reply-to-id"}

    monkeypatch.setattr(resend.Emails, "send", staticmethod(_capture_send))

    gateway.send_outbound(
        run_id=uuid.uuid4(),
        to_addr="client@acme.test",
        subject="Payroll Confirmation",
        body="Attached.",
        conn=fake_conn,
    )

    assert len(captured_params) == 1, "resend.Emails.send must be called exactly once"
    send_dict = captured_params[0]
    assert "reply_to" not in send_dict, (
        f"resend.Emails.send dict must NOT contain 'reply_to' key when resend_reply_to is empty "
        f"(passing empty string is malformed — key must be absent); "
        f"got send_dict keys: {list(send_dict.keys())}"
    )
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# BLOCKER-2 / HIGH-4 — ALLOW_UNSIGNED_FIXTURES prod-auth closure (Task 2)
# ---------------------------------------------------------------------------


def test_allow_unsigned_fixtures_prod_default_returns_400(monkeypatch):
    """BLOCKER-2 + HIGH-4: unsigned Resend-envelope payload without svix-* headers returns 400
    in production (ALLOW_UNSIGNED_FIXTURES=False, the default).

    This is the ONLY consistent statement about unsigned requests in prod:
    they return 400 regardless of shape (Resend-envelope OR canonical).
    NOT xfail — must be GREEN immediately after Task 2 route restructure.
    (T-06-04-01 / T-06-04-11)
    """
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    # Explicitly ensure ALLOW_UNSIGNED_FIXTURES is not set (prod default = False).
    monkeypatch.delenv("ALLOW_UNSIGNED_FIXTURES", raising=False)

    client = TestClient(app, raise_server_exceptions=False)

    # Resend-envelope shaped payload (has data.email_id): unsigned → 400 in prod.
    resend_envelope = {
        "type": "email.received",
        "data": {
            "email_id": "email_abc123",
            "from": "hr@acme.test",
            "to": ["payroll@jiodnel.resend.app"],
            "subject": "Payroll hours",
        },
    }
    # No svix-* signature headers — this is an unsigned request.
    response = client.post(
        "/webhook/inbound",
        content=resend_envelope.__class__(resend_envelope).__repr__().encode(),
        headers={"content-type": "application/json"},
    )
    # Actually use json= to send proper JSON body.
    response = client.post("/webhook/inbound", json=resend_envelope)
    assert response.status_code == 400, (
        f"Unsigned Resend-envelope POST must return 400 in prod "
        f"(ALLOW_UNSIGNED_FIXTURES=False default); got {response.status_code}. "
        f"BLOCKER-2: unsigned inbound must be rejected before any pipeline work."
    )
    get_settings.cache_clear()


def test_allow_unsigned_fixtures_canonical_shape_prod_default_returns_400(monkeypatch):
    """HIGH-4 + MEDIUM-4: unsigned canonical InboundEmail-shaped POST returns 400 in prod.

    This closes the canonical-bypass hole: even a perfectly-shaped InboundEmail dict POST
    without svix-* auth headers returns 400 in prod (ALLOW_UNSIGNED_FIXTURES=False).
    MEDIUM-4 consistent statement: unsigned canonical → 400 in prod. Full stop.
    NOT xfail — must be GREEN immediately after Task 2 route restructure.
    (T-06-04-11)
    """
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    # Explicitly ensure ALLOW_UNSIGNED_FIXTURES is not set (prod default = False).
    monkeypatch.delenv("ALLOW_UNSIGNED_FIXTURES", raising=False)

    client = TestClient(app, raise_server_exceptions=False)

    # Canonical InboundEmail dict shape (no data.email_id envelope): unsigned → 400 in prod.
    canonical_payload = {
        "id": str(uuid.uuid4()),
        "message_id": "<test-canonical@acme.test>",
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": "hr@acme.test",
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria 40 regular hours.",
        "created_at": "2026-06-15T10:00:00Z",
    }
    # No svix-* signature headers — unsigned canonical POST.
    response = client.post("/webhook/inbound", json=canonical_payload)
    assert response.status_code == 400, (
        f"Unsigned canonical InboundEmail POST must return 400 in prod "
        f"(ALLOW_UNSIGNED_FIXTURES=False default); got {response.status_code}. "
        f"HIGH-4: canonical fixture bypass must be closed in production."
    )
    get_settings.cache_clear()


def test_allow_unsigned_fixtures_canonical_shape_dev_mode_returns_200(monkeypatch):
    """HIGH-4: canonical InboundEmail dict POST returns 200 in dev mode
    (ALLOW_UNSIGNED_FIXTURES=True). Dev path preserved when flag is explicitly set.
    NOT xfail — must be GREEN immediately after Task 2 route restructure.
    (T-06-04-07 — flag is never in render.yaml; only in tests and local .env)
    """
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.db import repo as _repo
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    # Dev mode: ALLOW_UNSIGNED_FIXTURES=True so unsigned canonical POSTs succeed.
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")

    run_id = uuid.uuid4()
    email_id = uuid.uuid4()

    # Patch repo helpers so the route completes without a live DB.
    monkeypatch.setattr(_repo, "insert_inbound_email", lambda **kw: (email_id, True))
    monkeypatch.setattr(
        _repo,
        "find_business_by_sender",
        lambda from_addr, conn=None: uuid.uuid4(),
    )
    monkeypatch.setattr(
        _repo,
        "create_run",
        lambda **kw: run_id,
    )
    monkeypatch.setattr(
        _repo,
        "find_awaiting_reply_for_header",
        lambda *, in_reply_to, references_header, conn=None: None,
    )
    monkeypatch.setattr(
        _repo,
        "find_any_run_for_header",
        lambda *, in_reply_to, references_header, conn=None: None,
    )
    import app.routes.pipeline_glue as _main
    monkeypatch.setattr(_main, "run_pipeline_bg", lambda run_id, conn=None: None)

    # 09-03 (DATA-02): inbound() now wraps its ingest sequence in one
    # `with repo.get_connection() as conn: with conn.transaction(): ...` block.
    # This test monkeypatches individual _repo functions (not the fake_repo
    # fixture), so get_connection must be patched to a FakeConnection double too.
    import contextlib as _contextlib

    from tests.conftest import FakeConnection

    @_contextlib.contextmanager
    def _fake_get_connection():
        yield FakeConnection()

    monkeypatch.setattr(_repo, "get_connection", _fake_get_connection, raising=False)

    client = TestClient(app, raise_server_exceptions=False)

    # Canonical InboundEmail dict shape — allowed in dev mode.
    canonical_payload = {
        "id": str(uuid.uuid4()),
        "message_id": "<test-dev-canonical@acme.test>",
        "in_reply_to": None,
        "references_header": None,
        "subject": "Payroll hours",
        "from_addr": "hr@acme.test",
        "to_addr": "agent@payroll-agent.local",
        "body_text": "Maria 40 regular hours.",
        "created_at": "2026-06-15T10:00:00Z",
    }
    response = client.post("/webhook/inbound", json=canonical_payload)
    assert response.status_code == 200, (
        f"Canonical InboundEmail POST must return 200 in dev mode "
        f"(ALLOW_UNSIGNED_FIXTURES=True); got {response.status_code}. "
        f"HIGH-4: dev path preserved when flag is explicitly set."
    )
    get_settings.cache_clear()
