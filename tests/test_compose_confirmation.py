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

# Test doubles intentionally expose only the draft-provider surface.
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.models.contracts import PaystubLineItem

# This import FAILS RED until Wave 2 adds compose_confirmation to compose_email.py.
from app.pipeline.compose_email import compose_confirmation

# ---------------------------------------------------------------------------
# Fake LLM stubs — MUST accept **kwargs so timeout_s does not raise TypeError
# ---------------------------------------------------------------------------


class _DraftLLM:
    """call_text stand-in returning a scripted body (or None for empty content).

    MANDATORY: **kwargs in the signature absorbs `timeout_s=3.0` from
    compose_confirmation without raising TypeError (MEDIUM finding fix).
    """

    def __init__(self, body: str | None) -> None:
        self._body = body
        self.calls: list[tuple[Any, ...]] = []

    def call_text(self, tier: str, messages: Any, **kwargs: Any) -> str | None:
        self.calls.append((tier, messages, kwargs))
        return self._body


class _RaisingDraftLLM:
    """call_text stand-in that RAISES (simulates API error: auth, rate limit, etc.).

    MANDATORY: **kwargs in the signature absorbs `timeout_s=3.0` from
    compose_confirmation without raising TypeError (MEDIUM finding fix).
    """

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or RuntimeError("simulated draft API error (401/429/bad model)")
        self.calls = 0

    def call_text(self, tier: str, messages: Any, **kwargs: Any) -> str | None:
        self.calls += 1
        raise self._exc


# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------


def _minimal_paystub(net_pay: Decimal = Decimal("1234.56")) -> PaystubLineItem:
    """A minimal PaystubLineItem for compose_confirmation tests."""
    now = datetime.now(UTC)
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


def _minimal_run() -> dict[str, str]:
    """A minimal run dict for compose_confirmation (template floor uses these keys)."""
    return {
        "business_name": "Acme Corp",
        "pay_period_label": "Week of 2026-06-15",
    }


# ---------------------------------------------------------------------------
# Test 1: template floor fires on LLM exception
# ---------------------------------------------------------------------------


def test_compose_confirmation_template_floor_on_llm_exception(caplog):
    """An API error in the draft call must fall back to the templated confirmation
    body rather than raising, so a draft failure never strands the run.
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

    assert result.startswith("Your payroll has been approved. Net pay: $1,234.56."), (
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


# ---------------------------------------------------------------------------
# Test 5 (BUG-13): drafted body can never carry a Subject: line or a bracket
# placeholder token, even when the model ignores the prompt's format guard.
# ---------------------------------------------------------------------------


def test_compose_confirmation_strips_subject_line_and_placeholder():
    """A real send carried a literal `Subject: ...` line inside the body AND a
    `[Your Name]` sign-off placeholder (BUG-13). The prompt now asks the model not
    to do either, but a request is not a guarantee — this asserts the guard makes
    the violation IMPOSSIBLE by driving a stubbed LLM that ignores the prompt and
    returns both violations anyway.
    """
    paystubs = [_minimal_paystub()]
    run = _minimal_run()
    placeholder_body = (
        "Subject: Payroll Run Approval - Acme Corp.\n\n"
        "Hi there,\n\n"
        "Your payroll run has been approved. Net pay: $1,234.56.\n\n"
        "Best,\n[Your Name]"
    )
    llm = _DraftLLM(placeholder_body)

    result = compose_confirmation(paystubs, run, llm=llm)

    assert not any(
        line.strip().lower().startswith("subject:") for line in result.splitlines()
    ), f"drafted confirmation body must not contain a literal Subject: line; got: {result!r}"
    assert "[" not in result and "]" not in result, (
        "drafted confirmation body must not contain a bracket placeholder token "
        f"(e.g. [Your Name]); got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 6 (BUG-13 round 2): removing the placeholder TOKEN is not the fix. The
# original guard deleted `[Your Name]` and left "Best regards," dangling over
# nothing, which is the same broken-looking close BUG-13 was reported for.
# ---------------------------------------------------------------------------


def test_compose_confirmation_removes_the_whole_sign_off_not_just_the_placeholder():
    """The sign-off BLOCK must go, not just its bracket token.

    Deleting `[Your Name]` in place left the body ending "Best regards," with
    nothing under it. The client still sees a broken sign-off, so the violation
    was never actually fixed — only made harder to grep for.
    """
    paystubs = [_minimal_paystub()]
    run = _minimal_run()
    llm = _DraftLLM(
        "Hi Acme Corp,\n\n"
        "Your payroll run has been approved.\n\n"
        "- Maria Chen: $1,234.56 net\n\n"
        "Best regards,\n[Your Name]\nPayroll Team"
    )

    result = compose_confirmation(paystubs, run, llm=llm)

    assert "Best regards" not in result, (
        f"the sign-off line must be truncated, not left dangling; got: {result!r}"
    )
    assert "Payroll Team" not in result, (
        "everything below the sign-off is signature material and goes with it; "
        f"got: {result!r}"
    )
    assert "- Maria Chen: $1,234.56 net" in result, (
        f"the net pay summary above the sign-off must survive; got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 7 (BUG-13 round 2): a bracketed span is NOT deleted in place. Silent
# content deletion from a money-approved client email is the wrong failure.
# ---------------------------------------------------------------------------


def test_compose_confirmation_never_silently_deletes_bracketed_prose():
    """A residual placeholder disqualifies the draft; it never edits it.

    The old guard turned "net pay for [pay period ending 2026-06-15] is below"
    into "net pay for  is below" — a mangled sentence in an email the client
    reads after money was approved. Falling back to the deterministic template
    is the correct failure: it is complete, correct, and already the documented
    floor.
    """
    paystubs = [_minimal_paystub()]
    run = _minimal_run()
    mangling_body = (
        "Hi there,\n\n"
        "Your net pay for [pay period ending 2026-06-15] is below.\n\n"
        "- Maria Chen: $1,234.56 net"
    )
    llm = _DraftLLM(mangling_body)

    result = compose_confirmation(paystubs, run, llm=llm)

    assert "net pay for  is below" not in result, (
        "the guard must never leave a sentence with its middle deleted"
    )
    assert "[" not in result and "]" not in result, (
        f"no placeholder may survive to the client; got: {result!r}"
    )
    assert result == _template_floor(paystubs, run), (
        "a draft that cannot be repaired without deleting content must fall back "
        f"to the template floor verbatim; got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 8 (BUG-13 round 2): the prompt tells the model "the system appends its
# own closing line, so end the email right after the net pay summary". Nothing
# appended anything, so the drafted path ended abruptly on a dollar figure while
# the FALLBACK path was the only one that closed properly.
# ---------------------------------------------------------------------------


def test_compose_confirmation_appends_the_closing_line_the_prompt_promises():
    paystubs = [_minimal_paystub()]
    run = _minimal_run()
    llm = _DraftLLM(
        "Your payroll run has been approved.\n\n- Maria Chen: $1,234.56 net"
    )

    result = compose_confirmation(paystubs, run, llm=llm)

    assert result.endswith("Please contact us if you have any questions."), (
        "the drafted body must end with the same closing line the template floor "
        f"uses, or the prompt's instruction to omit one is a lie; got: {result!r}"
    )


def test_compose_confirmation_does_not_double_the_closing_line():
    """The model sometimes writes the closing itself. Appending blindly would
    print it twice."""
    paystubs = [_minimal_paystub()]
    run = _minimal_run()
    llm = _DraftLLM(
        "Your payroll run has been approved.\n\n"
        "- Maria Chen: $1,234.56 net\n\n"
        "Please contact us if you have any questions."
    )

    result = compose_confirmation(paystubs, run, llm=llm)

    assert result.count("Please contact us if you have any questions.") == 1, (
        f"the closing line must appear exactly once; got: {result!r}"
    )


def test_template_floor_and_drafted_path_close_identically():
    """One closing constant, two consumers. If they drift, a client can receive
    two differently-ending confirmations depending on whether the model was up."""
    paystubs = [_minimal_paystub()]
    run = _minimal_run()

    floor = compose_confirmation(paystubs, run, llm=_DraftLLM(None))
    drafted = compose_confirmation(
        paystubs, run, llm=_DraftLLM("Approved. - Maria Chen: $1,234.56 net")
    )

    closing = "Please contact us if you have any questions."
    assert floor.endswith(closing) and drafted.endswith(closing)


def _template_floor(paystubs: list[PaystubLineItem], run: dict[str, str]) -> str:
    """The floor body, obtained through the public entry point (empty draft)."""
    return compose_confirmation(paystubs, run, llm=_DraftLLM(None))
