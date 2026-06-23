"""Wave 0 RED stubs: compose_confirmation behavior (HITL-02).

Mirrors the structure of tests/test_clarify.py (compose_clarification tests).
These tests will fail RED until Wave 2 creates/extends app/pipeline/compose_email.py
with a `compose_confirmation` function.

CRITICAL **kwargs fix (MEDIUM finding): both _DraftLLM and _RaisingDraftLLM stubs
define call_text with `**kwargs` in their signature so that `timeout_s=3.0` (passed
by compose_confirmation) does NOT raise TypeError — a stub without **kwargs would
make test_compose_confirmation_uses_draft_when_present a false-positive failure.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

# This import FAILS RED until Wave 2 adds compose_confirmation to compose_email.py.
from app.pipeline.compose_email import compose_confirmation

from app.models.contracts import PaystubLineItem


# ---------------------------------------------------------------------------
# Fake LLM stubs — MUST accept **kwargs so timeout_s does not raise TypeError
# ---------------------------------------------------------------------------


class _DraftLLM:
    """call_text stand-in returning a scripted body (or None for empty content).

    MANDATORY: **kwargs in the signature absorbs `timeout_s=3.0` from
    compose_confirmation without raising TypeError (MEDIUM finding fix).
    """

    def __init__(self, body):
        self._body = body
        self.calls: list[tuple] = []

    def call_text(self, tier, messages, **kwargs):
        self.calls.append((tier, messages, kwargs))
        return self._body


class _RaisingDraftLLM:
    """call_text stand-in that RAISES (simulates API error: auth, rate limit, etc.).

    MANDATORY: **kwargs in the signature absorbs `timeout_s=3.0` from
    compose_confirmation without raising TypeError (MEDIUM finding fix).
    """

    def __init__(self, exc=None):
        self._exc = exc or RuntimeError("simulated draft API error (401/429/bad model)")
        self.calls = 0

    def call_text(self, tier, messages, **kwargs):
        self.calls += 1
        raise self._exc


# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------


def _minimal_paystub(net_pay: Decimal = Decimal("1234.56")) -> PaystubLineItem:
    """A minimal PaystubLineItem for compose_confirmation tests."""
    now = datetime.now(timezone.utc)
    return PaystubLineItem(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        submitted_name="Maria Chen",
        hours_regular=Decimal("40"),
        hours_overtime=Decimal("0"),
        hours_vacation=Decimal("0"),
        hours_sick=Decimal("0"),
        hours_holiday=Decimal("0"),
        gross_pay=Decimal("1600.00"),
        pretax_401k=Decimal("0"),
        fica_ss=Decimal("99.20"),
        fica_medicare=Decimal("23.20"),
        federal_withholding=Decimal("0"),
        state_withholding=None,
        net_pay=net_pay,
        created_at=now,
        additional_medicare_not_modeled=False,
    )


def _minimal_run() -> dict:
    """A minimal run dict for compose_confirmation (template floor uses these keys)."""
    return {
        "business_name": "Acme Corp",
        "pay_period_label": "Week of 2026-06-15",
    }


# ---------------------------------------------------------------------------
# Test 1: template floor fires on LLM exception
# ---------------------------------------------------------------------------


def test_compose_confirmation_template_floor_on_llm_exception(caplog):
    """WR-03 analog: an API error in the draft call must fall back to the templated
    confirmation body (not raise), so a draft failure never strands the run.

    Will fail RED until Wave 2 adds compose_confirmation to compose_email.py.
    """
    paystubs = [_minimal_paystub()]
    run = _minimal_run()
    llm = _RaisingDraftLLM()

    with caplog.at_level(logging.WARNING):
        result = compose_confirmation(paystubs, run, llm=llm)

    assert llm.calls == 1, "the draft call was attempted once"
    assert isinstance(result, str) and result, (
        "an API error must fall back to a non-empty templated body, not raise"
    )


# ---------------------------------------------------------------------------
# Test 2: template floor on empty/None draft
# ---------------------------------------------------------------------------


def test_compose_confirmation_template_floor_on_empty_draft(caplog):
    """Empty or None model content → a non-empty templated body (never empty string).

    Will fail RED until Wave 2 adds compose_confirmation to compose_email.py.
    """
    paystubs = [_minimal_paystub()]
    run = _minimal_run()

    for empty_val in ("", None):
        llm = _DraftLLM(empty_val)
        with caplog.at_level(logging.WARNING):
            result = compose_confirmation(paystubs, run, llm=llm)
        assert isinstance(result, str) and result, (
            f"empty draft content ({empty_val!r}) must fall back to a non-empty "
            "templated body"
        )


# ---------------------------------------------------------------------------
# Test 3: uses draft when present
# ---------------------------------------------------------------------------


def test_compose_confirmation_uses_draft_when_present():
    """When the LLM returns a non-empty body, compose_confirmation returns it.

    CRITICAL: _DraftLLM must accept **kwargs (MEDIUM finding fix) or this test
    would FAIL due to TypeError even though the implementation is correct.

    Will fail RED until Wave 2 adds compose_confirmation to compose_email.py.
    """
    paystubs = [_minimal_paystub()]
    run = _minimal_run()
    llm = _DraftLLM("Your payroll has been approved. Net pay: $1,234.56.")

    result = compose_confirmation(paystubs, run, llm=llm)

    assert result == "Your payroll has been approved. Net pay: $1,234.56.", (
        "when the LLM returns a non-empty body, compose_confirmation must use it"
    )
    assert llm.calls, "compose_confirmation must call the draft LLM"


# ---------------------------------------------------------------------------
# Test 4: floor string contains net pay
# ---------------------------------------------------------------------------


def test_confirmation_floor_contains_net_pay():
    """The template floor string must contain each employee's net_pay formatted as
    a dollar amount (HITL-02 — the operator-approved result reaches the client).

    Will fail RED until Wave 2 adds compose_confirmation to compose_email.py.
    """
    net = Decimal("1234.56")
    paystubs = [_minimal_paystub(net_pay=net)]
    run = _minimal_run()
    llm = _DraftLLM(None)  # force the template floor

    result = compose_confirmation(paystubs, run, llm=llm)

    # The floor must mention the dollar amount in some readable form.
    assert "1234" in result or "1,234" in result, (
        "the confirmation template floor must include each employee's net_pay "
        f"(expected '1234' or '1,234' in the result; got: {result!r})"
    )
