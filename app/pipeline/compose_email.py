"""The clarification drafting call (CLAR-01, AI-SPEC §1 Drafting call).

When final_action == request_clarification, the cheap DRAFT_* tier drafts a
human-readable clarification email asking the client to resolve what the code gate
blocked. This is the ONE LLM call that is NOT JSON mode — it is prose, so it goes
through `client.call_text` (free text, no schema, no reflective retry) and may run
a low non-zero temperature.

A draft failure must NEVER strand the run: `call_text` returns None on empty
content, and this module falls back to a deterministic templated body built from
the Decision's gate detail (gate_reasons / unresolved_names / missing_fields). So
the run always has a body to send and always pauses cleanly at AWAITING_REPLY.

PURE: typed Decision in, str out. No DB, no connection — the orchestrator owns the
send + status transition.
"""
from __future__ import annotations

import logging

from app.llm import client as llm_client
from app.llm.prompts import clarify as clarify_prompt
from app.models.contracts import Decision, PaystubLineItem

logger = logging.getLogger("payroll_agent.compose_email")

_SUBJECT = "Quick question before we run your payroll"


def _template_body(
    decision: Decision,
    suggestions: dict[str, str] | None = None,
) -> str:
    """A deterministic clarification body from the gate detail (fallback / floor).

    Surfaces exactly what the code gate blocked on so the client can resolve it,
    even when the draft model returns nothing.

    `suggestions` (submitted_name → suggested roster full_name) is advisory COPY
    from the suggestion call (D-21-05). When a suggestion exists for an unresolved
    name, the line names the likely intended employee ("We could not match
    'David Reyez' — did you mean David Reyes?") instead of the bare name. This is
    the DETERMINISTIC floor of the new Phase 2 hero, so the specific ask survives
    even a total draft-tier failure (WR-03).
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
    if not decision.unresolved_names and not decision.missing_fields:
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
    llm=llm_client,
) -> str:
    """Draft a clarification email body for a gated run (CLAR-01).

    Uses the DRAFT_* tier free-text path; on empty model content falls back to a
    templated body so a draft failure never strands the run. Returns the body
    string the orchestrator hands to gateway.send_outbound.

    `suggestions` (submitted_name → suggested roster full_name) is advisory COPY
    from the suggestion call (D-21-05), threaded into BOTH the draft prompt (so the
    model can write "did you mean David Reyes?") AND the deterministic template
    fallback (so the specific ask survives a draft failure, WR-03). It is copy
    only — it never feeds decide / final_action.
    """
    messages = clarify_prompt.build_messages(decision, suggestions)
    # WR-03: the "draft failure never strands the run" guarantee must cover BOTH
    # empty content AND an API error (auth/rate-limit/etc.). call_text returns None
    # on empty content but RAISES on an API error — unwrapped, that exception would
    # propagate out through _clarify and route the run to ERROR instead of falling
    # back to the template. Wrap it so an API error also degrades to the templated
    # body, and LOG every fallback so a misconfigured draft tier (wrong key/model)
    # is VISIBLE rather than silently templating every clarification.
    api_error = False
    try:
        body = llm.call_text("draft", messages, temperature=0.3)
    except Exception as exc:  # noqa: BLE001 — a draft failure must never strand the run (CLAR-01)
        # Log the failure TYPE only — no exc_info (a traceback can echo the prompt /
        # submitted names — payroll PII — review fix).
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
    return body


def clarification_subject() -> str:
    """The clarification email subject (kept here so the orchestrator stays thin).

    WR-05: takes NO arguments. It previously accepted a `decision` it ignored
    entirely — a misleading signature implying the subject reflected the decision.
    The subject is a constant in Phase 2; a real provider's subject-based threading
    fallback is a deferred P6 concern. Drop the dead parameter (the honest minimum).
    """
    return _SUBJECT


# ---------------------------------------------------------------------------
# Confirmation email (HITL-02) — approved-run path
# ---------------------------------------------------------------------------


def _confirmation_template_body(
    paystubs: list[PaystubLineItem],
    run: dict,
) -> str:
    """Deterministic confirmation floor — fires when draft times out or fails (D-10).

    Never strands the send, even on total draft failure. Per UI-SPEC copywriting
    contract (Confirmation Email Subject / Template Floor body):
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


def confirmation_subject(run: dict) -> str:
    """The confirmation email subject line (HITL-02, UI-SPEC Copywriting Contract).

    Format: "Payroll Confirmation — {business_name} — {pay_period_label}"
    run is a dict from repo.load_run; uses .get() with safe fallbacks so a
    missing key never raises here.
    """
    business_name = run.get("business_name", "Payroll Run")
    pay_period_label = run.get("pay_period_label", "")
    return f"Payroll Confirmation — {business_name} — {pay_period_label}"


def compose_confirmation(
    paystubs: list[PaystubLineItem],
    run: dict,
    *,
    llm=llm_client,
    timeout_s: float = 3.0,
) -> str:
    """Draft a confirmation email body for an approved run (HITL-02).

    Mirrors compose_clarification exactly — uses the DRAFT_* tier free-text path;
    on any LLM error or empty content falls back to _confirmation_template_body so
    a draft failure never strands the approval (D-10, T-05-11).

    `timeout_s` (D-10b): hard ~3s timeout on the LLM call bounds cold-dyno latency;
    a timeout exception is caught by the broad except clause and falls to the floor.
    Passed to llm.call_text as a keyword argument — test fakes must accept **kwargs
    or the "uses_draft_when_present" test gets a spurious TypeError (T-05-11b).
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
    # D-10 / WR-03 analog: the "draft failure never strands the run" guarantee must
    # cover BOTH empty content AND an API error (auth/rate-limit/timeout/etc.).
    # call_text returns None on empty content but RAISES on an API error — unwrapped,
    # that exception would propagate through _deliver and ERROR the run instead of
    # falling back to the template floor. Broad except so a timeout also degrades.
    api_error = False
    try:
        body = llm.call_text("draft", messages, temperature=0.3, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001 — a draft failure must never strand the run (D-10)
        # Log the failure TYPE only — no exc_info (traceback can echo PII, D-A1-03).
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
