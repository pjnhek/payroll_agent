"""The clarification and confirmation drafting calls: the model writes prose, only prose.

When final_action == request_clarification, the cheap draft tier writes a human-readable
email asking the client to resolve whatever the code gate blocked. This is the ONE LLM call
that is not JSON mode — it is prose, so it goes through `client.call_text` (free text, no
schema, no reflective retry) and may run at a low non-zero temperature.

The model here only phrases the question. WHAT to ask was already decided in code by
decide(); the draft cannot add, drop, or soften a gate reason.

A draft failure must NEVER strand the run. `call_text` returns None on empty content, and
this module falls back to a deterministic templated body built from the Decision's gate
detail (gate_reasons / unresolved_names / missing_fields). The run always has a body to
send and always pauses cleanly at AWAITING_REPLY — a flaky model call must not be able to
leave a payroll in limbo.

PURE: typed Decision in, str out. No DB, no connection — the orchestrator owns the send and
the status transition.
"""
from __future__ import annotations

import logging
from typing import Any, cast

from app.llm import client as llm_client
from app.llm.prompts import clarify as clarify_prompt
from app.models.contracts import Decision, PaystubLineItem

logger = logging.getLogger("payroll_agent.compose_email")

_SUBJECT = "Quick question before we run your payroll"

# Every draft call MUST pass timeout_s. call_text has no app-level retry loop around it,
# so an unbounded call inherits the library's ~10-minute default and (with library retries)
# can hang a webhook request for half an hour. A clarification draft is free-text prose,
# lighter than the structured-JSON round trip (see client._STRUCTURED_TIMEOUT_S = 45.0),
# so it takes the lower bound of the sane range. Together with call_text's unconditional
# max_retries=0, the true worst case here is timeout_s x 1.
_CLARIFICATION_TIMEOUT_S = 30.0


def _field_regression_lines(gate_reasons: list[str]) -> list[str]:
    """Extract field-regression lines from gate_reasons using LAST-DOT SPLIT (rsplit).

    Gate-reason format: 'field regression: {submitted_name}.{field_name}'
    rsplit('.',1) correctly handles dotted submitted names like 'M. Chen.hours_overtime'
    → ('M. Chen', 'hours_overtime'), NOT ('M', 'Chen.hours_overtime').

    Returns one wording line per field-regression gate_reason.
    """
    lines: list[str] = []
    for reason in gate_reasons:
        if reason.startswith("field regression: "):
            qualified = reason[len("field regression: "):]
            # A malformed gate_reason (no dot separator) is SKIPPED, never allowed to
            # raise: a formatting quirk in one reason line must not crash the draft and
            # strand the whole run.
            parts = qualified.rsplit(".", 1)
            if len(parts) != 2:
                continue
            submitted_name, field_name = parts
            lines.append(
                f"  - Reply with the {field_name} hours for {submitted_name},"
                " or 'none' to confirm zero."
            )
    return lines


def _as_reply(subject: str, original_subject: str | None) -> str:
    """Prefix `Re: <original subject>` so mail clients group the thread (P6).

    Gmail and most clients thread on BOTH the RFC header chain (In-Reply-To /
    References — already set) AND a matching `Re:`-prefixed subject. Because the
    bot replies from a different From address (free-tier onboarding@resend.dev),
    the subject match is what visually coalesces the conversation in the client.

    Uses the original inbound subject when present (the true reply subject); falls
    back to the bot's own subject otherwise. Never double-prefixes ("Re: Re: ...").
    """
    base = (original_subject or "").strip() or subject
    if base[:3].lower() == "re:":
        return base
    return f"Re: {base}"


def _template_body(
    decision: Decision,
    suggestions: dict[str, str] | None = None,
) -> str:
    """A deterministic clarification body from the gate detail (fallback / floor).

    Surfaces exactly what the code gate blocked on so the client can resolve it, even when
    the draft model returns nothing at all.

    `suggestions` (submitted_name → suggested roster full_name) is advisory COPY. When a
    suggestion exists for an unresolved name, the line names the likely intended employee
    ("We could not match 'David Reyez' — did you mean David Reyes?") instead of the bare
    name. Threading suggestions through this deterministic floor (and not only the model
    draft) is what keeps the specific, useful ask alive even on total draft-tier failure.
    The suggestion is copy: it never feeds decide() or final_action.
    """
    suggestions = suggestions or {}
    lines = [
        "Hello,",
        "",
        "We started processing your payroll but need to confirm a few details "
        "before we can finish:",
        "",
    ]
    if decision.unresolved_names:
        # Split names with a suggestion (specific "did you mean ...?" line) from
        # those without (the generic bundled ask) — the suggestion is copy only.
        suggested_names = [n for n in decision.unresolved_names if suggestions.get(n)]
        plain_names = [n for n in decision.unresolved_names if not suggestions.get(n)]
        for name in suggested_names:
            lines.append(
                f"  - We could not match '{name}' — did you mean "
                f"{suggestions[name]}?"
            )
        if plain_names:
            lines.append(
                "  - We could not confidently match these names to an employee: "
                + ", ".join(plain_names)
                + "."
            )
    if decision.missing_fields:
        lines.append(
            "  - We are missing required information for: "
            + ", ".join(decision.missing_fields)
            + "."
        )
    # Field-regression lines are emitted UNCONDITIONALLY, before the raw-gate-reason
    # fallback below. If they were emitted only in the fallback branch, a run that ALSO
    # has unresolved names or missing fields would never ask about the dropped hours — the
    # client would answer the other questions and the regression would silently persist.
    fr_lines = _field_regression_lines(decision.gate_reasons)
    lines.extend(fr_lines)

    if not decision.unresolved_names and not decision.missing_fields and not fr_lines:
        # Fall back to the raw gate reasons if the structured lists are empty.
        for reason in decision.gate_reasons:
            lines.append(f"  - {reason}")
    lines += [
        "",
        "Could you please reply with the correct details so we can complete the "
        "run? Thank you!",
    ]
    return "\n".join(lines)


def compose_clarification(
    decision: Decision,
    *,
    suggestions: dict[str, str] | None = None,
    llm: Any = llm_client,
) -> str:
    """Draft a clarification email body for a gated run.

    Uses the draft tier's free-text path; on empty model content it falls back to a
    templated body so a draft failure never strands the run. Returns the body string the
    orchestrator hands to gateway.send_outbound.

    `suggestions` (submitted_name → suggested roster full_name) is advisory COPY, threaded
    into BOTH the draft prompt (so the model can write "did you mean David Reyes?") AND the
    deterministic template fallback (so the specific ask survives a draft failure). It is
    copy only — it never feeds decide() or final_action.
    """
    messages = clarify_prompt.build_messages(decision, suggestions)
    # The "a draft failure never strands the run" guarantee must cover BOTH empty content
    # AND an API error (auth, rate limit, etc.). call_text returns None on empty content
    # but RAISES on an API error — left unwrapped, that exception propagates out and routes
    # the run to ERROR instead of falling back to the template, turning a transient model
    # blip into a dead payroll. Wrap it so an API error also degrades to the templated body.
    # LOG every fallback: a misconfigured draft tier (wrong key or model id) would otherwise
    # silently template every clarification and look fine.
    api_error = False
    try:
        body = cast(
            str | None,
            llm.call_text(
                "draft", messages, temperature=0.3, timeout_s=_CLARIFICATION_TIMEOUT_S
            ),
        )
    except Exception as exc:  # noqa: BLE001 — a draft failure must never strand the run
        # Log the failure TYPE only, with no exc_info: a traceback can echo the prompt and
        # the submitted names, which are payroll PII and must not land in logs.
        logger.warning(
            "draft call failed (%s) — falling back to templated clarification body",
            type(exc).__name__,
        )
        body = None
        api_error = True
    if not body or not body.strip():
        # An API error was already logged above; log the empty-content case here so a
        # silently-templating draft tier is still visible (but don't double-log errors).
        if not api_error:
            logger.warning("draft returned empty content — using templated clarification body")
        return _template_body(decision, suggestions)

    # The deterministic field-regression question is APPENDED after the model's draft body,
    # so it is guaranteed to appear on the real (model-drafted) path and not only in the
    # _template_body fallback. Trusting the model to carry it would mean a drafted email
    # could quietly omit the one question about hours the client dropped.
    fr_lines = _field_regression_lines(decision.gate_reasons)
    if fr_lines:
        body = body.rstrip("\n") + "\n\n" + "\n".join(fr_lines)

    return body


def clarification_subject(original_subject: str | None = None) -> str:
    """The clarification email subject (kept here so the orchestrator stays thin).

    P6 threading: when the original inbound subject is supplied, returns
    `Re: <original subject>` so the clarification groups into the client's existing
    thread (the bot's differing From address means the subject match is what
    visually coalesces the conversation). With no original subject (in-app /
    Phase-2 callers, tests) it returns the bare clarification subject — backward
    compatible.
    """
    if original_subject:
        return _as_reply(_SUBJECT, original_subject)
    return _SUBJECT


# ---------------------------------------------------------------------------
# Confirmation email (HITL-02) — approved-run path
# ---------------------------------------------------------------------------


def _confirmation_template_body(
    paystubs: list[PaystubLineItem],
    run: dict[str, Any],
) -> str:
    """Deterministic confirmation floor — fires when the draft call times out or fails.

    Never strands the send, even on total draft failure: the operator already approved this
    payroll, so it must go out whether or not the model can write a nice sentence about it.
    The required copy shape is:
      - Opens: "Your payroll run has been reviewed and approved..."
      - One line per employee with net pay
      - Closes: "Please contact us if you have any questions."
    """
    lines = [
        "Your payroll run has been reviewed and approved. "
        "Please find the paystub PDFs attached.",
        "",
    ]
    for item in paystubs:
        lines.append(f"- {item.submitted_name}: ${item.net_pay:,.2f} net")
    lines += ["", "Please contact us if you have any questions."]
    return "\n".join(lines)


def confirmation_subject(
    run: dict[str, Any], original_subject: str | None = None
) -> str:
    """The confirmation email subject line.

    Format: "Payroll Confirmation — {business_name} — {pay_period_label}".
    run is a dict from repo.load_run; uses .get() with safe fallbacks so a missing key can
    never raise here and kill an approved send over a subject line.

    Threading: when the original inbound subject is supplied, the line is prefixed
    `Re: <original subject>` so the confirmation lands in the client's existing thread. The
    bot replies from a different From address, so the subject match is what groups the
    conversation for the client. With no original subject it returns the standalone
    confirmation subject.
    """
    business_name = run.get("business_name", "Payroll Run")
    pay_period_label = run.get("pay_period_label", "")
    standalone = f"Payroll Confirmation — {business_name} — {pay_period_label}"
    if original_subject:
        return _as_reply(standalone, original_subject)
    return standalone


def compose_confirmation(
    paystubs: list[PaystubLineItem],
    run: dict[str, Any],
    *,
    llm: Any = llm_client,
    timeout_s: float = 3.0,
) -> str:
    """Draft a confirmation email body for an approved run.

    Mirrors compose_clarification: uses the draft tier's free-text path, and on any LLM
    error or empty content falls back to _confirmation_template_body, so a draft failure
    never strands an approval the operator already gave.

    `timeout_s`: a hard, short timeout bounds cold-start latency on the send path — the
    client is waiting on an approved payroll, not on prose. A timeout is caught by the
    broad except below and falls through to the template floor. It is passed to
    llm.call_text as a KEYWORD argument, so test fakes must accept **kwargs or they raise
    a spurious TypeError instead of exercising the draft path.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a payroll assistant. Write a brief, warm confirmation email "
                "telling the client their payroll run has been approved. Include the "
                "per-employee net pay summary. Keep it professional and concise."
            ),
        },
        {
            "role": "user",
            "content": (
                "Approved payroll run for "
                + run.get("business_name", "the client")
                + ".\n\nPer-employee net pay:\n"
                + "\n".join(
                    f"- {item.submitted_name}: ${item.net_pay:,.2f} net"
                    for item in paystubs
                )
            ),
        },
    ]
    # Same guarantee as compose_clarification: "a draft failure never strands the run" must
    # cover BOTH empty content AND an API error (auth, rate limit, timeout). call_text
    # returns None on empty content but RAISES on an API error — left unwrapped, that
    # exception propagates through _deliver and ERRORs a run the operator already approved,
    # instead of falling back to the template floor. The except is deliberately broad so a
    # timeout degrades the same way.
    api_error = False
    try:
        body = cast(
            str | None,
            llm.call_text("draft", messages, temperature=0.3, timeout_s=timeout_s),
        )
    except Exception as exc:  # noqa: BLE001 — a draft failure must never strand the run
        # Log the failure TYPE only, with no exc_info: a traceback can echo payroll PII.
        logger.warning(
            "confirmation draft call failed (%s) — falling back to templated confirmation body",
            type(exc).__name__,
        )
        body = None
        api_error = True
    if not body or not body.strip():
        if not api_error:
            logger.warning(
                "confirmation draft returned empty content — using templated confirmation body"
            )
        return _confirmation_template_body(paystubs, run)
    return body
