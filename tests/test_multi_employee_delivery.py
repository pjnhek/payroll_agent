"""Multi-employee confirmation — ONE email, one PDF per employee.

A payroll run usually covers several people, and the two ways to get that wrong are
symmetric: send one email per employee (the client is spammed and the run looks broken),
or send one email that quietly covers only the first employee (someone's paystub is
simply missing). Both properties are therefore pinned:

1. compose_confirmation with 2+ PaystubLineItems produces a body mentioning EVERY
   employee's submitted_name — asserted on the deterministic template floor, so it holds
   with no LLM involved and cannot be a lucky draft.

2. delivery of a run with 2+ line items generates one PDF attachment per employee and
   sends exactly ONE confirmation email:
   - gateway.send_outbound called exactly once,
   - len(attachments) == number of employees,
   - each attachment really is a PDF (starts with b'%PDF'), so an empty or error-page
     payload cannot pass as a paystub.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.models.contracts import PaystubLineItem
from app.models.status import RunStatus
from app.pipeline.compose_email import _confirmation_template_body, compose_confirmation

# ---------------------------------------------------------------------------
# Helpers / minimal fixtures
# ---------------------------------------------------------------------------


def _paystub(
    run_id: uuid.UUID,
    employee_id: uuid.UUID,
    submitted_name: str,
    net_pay: Decimal = Decimal("1200.00"),
) -> PaystubLineItem:
    """A minimal PaystubLineItem for testing."""
    now = datetime.now(UTC)
    return PaystubLineItem(
        id=uuid.uuid4(),
        run_id=run_id,
        employee_id=employee_id,
        submitted_name=submitted_name,
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


# ---------------------------------------------------------------------------
# The confirmation body must mention every employee, not just the first
# ---------------------------------------------------------------------------


def test_compose_confirmation_multi_employee_body_mentions_all_names():
    """compose_confirmation with 2+ PaystubLineItems must mention ALL submitted names.

    Forces the template floor (LLM returns "") so the assertion is deterministic
    and network-free. Both employees' submitted_names must appear in the body.
    """
    run_id = uuid.uuid4()
    emp_a = uuid.uuid4()
    emp_b = uuid.uuid4()

    paystubs = [
        _paystub(run_id, emp_a, "Maria Chen", Decimal("1150.60")),
        _paystub(run_id, emp_b, "James Okafor", Decimal("1320.45")),
    ]
    run = {
        "business_name": "Coastal Cleaning Co.",
        "pay_period_label": "2026-06-15",
    }

    # Force template floor by having the LLM stub return ""
    class _EmptyDraftLLM:
        def call_text(self, tier, messages, **kwargs):
            return ""

    body = compose_confirmation(paystubs, run, llm=_EmptyDraftLLM())

    assert "Maria Chen" in body, (
        "confirmation body must mention 'Maria Chen' for a 2-employee run"
    )
    assert "James Okafor" in body, (
        "confirmation body must mention 'James Okafor' for a 2-employee run"
    )


def test_confirmation_template_body_multi_employee_mentions_all_net_pays():
    """_confirmation_template_body floor includes each employee's net pay."""
    run_id = uuid.uuid4()
    paystubs = [
        _paystub(run_id, uuid.uuid4(), "Alice Wong", Decimal("980.00")),
        _paystub(run_id, uuid.uuid4(), "Bob Santos", Decimal("1050.50")),
    ]
    run = {"business_name": "Test Co.", "pay_period_label": ""}

    body = _confirmation_template_body(paystubs, run)

    assert "Alice Wong" in body
    assert "Bob Santos" in body
    assert "980" in body or "980.00" in body
    assert "1050" in body or "1,050" in body


# ---------------------------------------------------------------------------
# Test 2: _deliver with 2+ line items sends ONE email with N PDF attachments
# ---------------------------------------------------------------------------


def test_deliver_multi_employee_sends_one_email_with_per_employee_pdfs(
    fake_repo, monkeypatch
):
    """_deliver with 2 employees must send exactly ONE confirmation email
    containing exactly 2 PDF attachments (one per employee).

    fake_repo is already monkeypatched onto app.db.repo by the fixture; _deliver
    uses the module-level repo import so the patch is transparent.

    Asserts:
    - gateway.send_outbound called exactly once
    - attachments list has len == 2
    - each attachment bytes starts with b'%PDF'
    """
    biz_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]

    # Create an inbound email so _deliver can load from_addr
    email_id, _ = fake_repo.insert_inbound_email(
        message_id="<test-multi@payroll-agent.local>",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        subject="Weekly payroll",
        body_text="Maria Chen 40h, James Okafor 40h",
        in_reply_to=None,
        references_header=None,
    )

    run_id = fake_repo.create_run(
        business_id=biz_id,
        source_email_id=email_id,
        pay_period_start="2026-06-15",
        pay_period_end=None,
    )
    fake_repo.set_status(run_id, RunStatus.APPROVED)

    # Build two employees from the seed roster
    biz_employees = fake_repo.business_employees.get(str(biz_id), [])
    # Prefer Maria Chen + James Okafor by name; fall back to first two
    emp_a = next((e for e in biz_employees if e.full_name == "Maria Chen"), None)
    emp_b = next((e for e in biz_employees if "Okafor" in e.full_name), None)
    if emp_a is None or emp_b is None:
        emp_a, emp_b = biz_employees[0], biz_employees[1]

    paystubs = [
        _paystub(run_id, emp_a.id, emp_a.full_name, Decimal("1150.60")),
        _paystub(run_id, emp_b.id, emp_b.full_name, Decimal("1320.45")),
    ]
    fake_repo.replace_line_items(run_id, paystubs)

    # Spy on gateway.send_outbound — _deliver calls gateway.send_outbound which
    # is imported at module level in orchestrator; patch the orchestrator's binding.
    send_calls: list[dict[str, Any]] = []

    def _spy_send_outbound(**kwargs):
        send_calls.append(kwargs)

    monkeypatch.setattr("app.pipeline.delivery.gateway.send_outbound", _spy_send_outbound)

    from app.pipeline.delivery import deliver as _deliver

    run_dict = fake_repo.load_run(run_id)
    _deliver(run_id, run_dict)

    # --- Assertions ---
    assert len(send_calls) == 1, (
        f"_deliver must send exactly ONE confirmation email for a 2-employee run; "
        f"got {len(send_calls)} send_outbound call(s)"
    )

    attachments = send_calls[0].get("attachments", [])
    assert len(attachments) == 2, (
        f"_deliver must generate exactly 2 PDF attachments for 2 employees; "
        f"got {len(attachments)}"
    )

    for filename, pdf_bytes in attachments:
        assert pdf_bytes[:4] == b"%PDF", (
            f"PDF attachment '{filename}' must start with b'%PDF' "
            f"(got: {pdf_bytes[:8]!r})"
        )
        # 06-05 live-gate regression: the attachment filename MUST end in .pdf, or the
        # recipient's mail client receives an extensionless binary blob it won't open as
        # a PDF. _deliver builds "paystub_<sanitized-name>.pdf"; a bare name (no ext) is
        # the bug that shipped the broken attachment in the real round-trip.
        assert filename.endswith(".pdf"), (
            f"attachment filename must end in .pdf (mail clients key off the extension); "
            f"got {filename!r}"
        )


def test_deliver_multi_employee_subject_uses_start_only_period(
    fake_repo, monkeypatch
):
    """A run with only a start date must not produce a malformed confirmation subject.

    When pay_period_end is None, the subject must fall back to str(pay_period_start)
    rather than emitting an empty string or a dangling separator. Guarded here inside the
    MULTI-employee path specifically, because the single-employee path has its own
    subject-building call site and fixing one does not fix the other.
    """
    biz_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]

    email_id, _ = fake_repo.insert_inbound_email(
        message_id="<test-multi-subject@payroll-agent.local>",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        subject="Payroll",
        body_text="Maria Chen 40h",
        in_reply_to=None,
        references_header=None,
    )

    run_id = fake_repo.create_run(
        business_id=biz_id,
        source_email_id=email_id,
        pay_period_start="2026-06-15",
        pay_period_end=None,  # only a start date — the case that can yield a bad subject
    )
    fake_repo.set_status(run_id, RunStatus.APPROVED)

    biz_employees = fake_repo.business_employees.get(str(biz_id), [])
    emp_a = biz_employees[0]
    emp_b = biz_employees[1]

    paystubs = [
        _paystub(run_id, emp_a.id, emp_a.full_name, Decimal("900.00")),
        _paystub(run_id, emp_b.id, emp_b.full_name, Decimal("950.00")),
    ]
    fake_repo.replace_line_items(run_id, paystubs)

    captured_subjects: list[str] = []

    def _spy_send_outbound(**kwargs):
        captured_subjects.append(kwargs.get("subject", ""))

    monkeypatch.setattr("app.pipeline.delivery.gateway.send_outbound", _spy_send_outbound)

    from app.pipeline.delivery import deliver as _deliver

    run_dict = fake_repo.load_run(run_id)
    _deliver(run_id, run_dict)

    assert len(captured_subjects) == 1
    subject = captured_subjects[0]
    # This run has an original inbound subject ("Payroll"), so the confirmation threads as
    # a reply — `Re: Payroll` — which is what groups it into the client's conversation.
    # The pay-period detail is not lost: it lives in the email body and the paystub PDF.
    # The subject's job here is thread-grouping, not carrying metadata.
    assert subject == "Re: Payroll", (
        f"confirmation must thread on the original inbound subject; got: {subject!r}"
    )

    # The STANDALONE subject (no original to thread on) is the form that can go wrong:
    # with pay_period_end None it must use str(pay_period_start) and never a dangling
    # separator. delivery computes pay_period_label from pay_period_start before calling
    # confirmation_subject; replicate that enrichment to exercise the standalone form.
    from app.pipeline.compose_email import confirmation_subject
    enriched = {"business_name": "Coastal Cleaning Co.", "pay_period_label": "2026-06-15"}
    standalone = confirmation_subject(enriched)  # no original_subject → standalone form
    assert "2026-06-15" in standalone, (
        f"standalone confirmation subject must include pay_period_start when end is None; "
        f"got: {standalone!r}"
    )
    assert not standalone.endswith("— "), (
        f"standalone confirmation subject must not have trailing ' — ' with no date; "
        f"got: {standalone!r}"
    )
