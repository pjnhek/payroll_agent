"""One allow-listed operator-notice mechanism for every redirect-after-POST outcome.

A server-rendered form's only channel to explain WHY a POST did nothing is a 303
redirect back to the same page. Several handlers across this router used to 303
silently on a guard rejection, reading to the operator as "the button is broken".
One codebase precedent already solved this for `simulate_reply` (the three
`?simulate_reply_error=<code>` codes this module absorbs and deletes); this module
generalizes that shape to the whole app behind a single `?notice=<code>` query
param.

Every code here is "hostile until proven fixed": a value is reduced to its fixed
label through `notice_label` (or the allow-list check inside `notice_url` /
`notice_redirect`) BEFORE it ever reaches a template, so a hand-crafted URL
renders no banner rather than an attacker-chosen string. Never interpolate a
caller-supplied string directly into a page.
"""
from __future__ import annotations

from fastapi.responses import RedirectResponse

# Fixed, safe vocabulary for the whole app's `?notice=<code>` query param. Every
# operator-facing handler that needs to explain a silent redirect adds ONE code
# here -- never a bespoke per-route query flag (that is exactly the
# `demo_queue_error` / `resolution_superseded` proliferation this module ends).
NOTICE_LABELS: dict[str, str] = {
    "reply_no_proof": (
        "This clarification question has not been confirmed sent yet. "
        "Wait a moment and try again."
    ),
    "reply_missing_source": (
        "The original email for this run could not be loaded, so no reply could be built."
    ),
    "reply_enqueue_failed": "The reply could not be durably recorded. Try again.",
    "retrigger_delivery_review": (
        "This run is held by a delivery review. Resolve the delivery review "
        "below before re-triggering."
    ),
    "retrigger_active_handoff": (
        "A send for this run is still in flight with the email provider. "
        "Wait for it to settle, then try again."
    ),
    "retry_missing": "There is no send job left for this frozen email.",
    "retry_expired": "The 20-hour replay window for this reservation has closed.",
    "retry_not_pending": "A send for this email is already in flight.",
    "retry_unavailable": "Could not reach the database. Try again.",
    "review_unavailable": "This run no longer has a loadable delivery review.",
    "review_state_changed": (
        "This run's state changed while you were reading. Reload and check "
        "the current status."
    ),
    "resolve_not_needs_operator": (
        "This run is no longer awaiting an operator resolution. Nothing was applied."
    ),
    "resolve_delivery_review": (
        "This run is held by a delivery review, not a name resolution. Resolve "
        "the delivery review below instead."
    ),
    "resolve_nothing_unresolved": "There is nothing to resolve for this run.",
    "resolve_roster_unavailable": (
        "The employee roster could not be loaded. Try again."
    ),
    "resolve_invalid_employee": (
        "One or more names were not mapped to a valid employee, so nothing was "
        "applied. Select an employee for every name and resubmit."
    ),
    "resolve_superseded_conflict": (
        "Another resolution for this run was already accepted. This "
        "submission was not applied."
    ),
    "authorize_bad_ack": (
        "The acknowledgement phrase did not match. Type "
        "AUTHORIZE A NEW CONFIRMATION exactly, then submit again."
    ),
    "approve_claim_lost": (
        "This run is no longer awaiting approval. It may already have been "
        "approved in another tab. No second approval was recorded."
    ),
    "demo_unknown_business": (
        "That business is not part of the demo. Choose one of the listed "
        "businesses and try again."
    ),
    "demo_too_long": (
        "The submission was too long (max 4000 characters for the body, 200 "
        "for the subject) and was not sent. Shorten it and try again."
    ),
    "demo_queue_error": (
        "Couldn't start this payroll run. Pyrl's free hosting sleeps after "
        "15 idle minutes and can take up to a minute to wake, so a first "
        "attempt right after arriving can fail. Wait a moment and try again."
    ),
}


def notice_label(code: str) -> str | None:
    """Reduce a caller-supplied code to its fixed label, or None if unrecognised."""
    return NOTICE_LABELS.get(code)


def notice_url(base: str, code: str) -> str:
    """Build a `?notice=<code>` URL against `base`.

    `base` is a path, not a run id, so this same function serves every
    consumer -- run detail, the dashboard index, and the runs list. Raises
    `KeyError` on an unrecognised code so a call-site typo fails loudly at the
    point it is introduced rather than shipping a link nobody can read; the
    AST drift pin in tests/test_operator_feedback.py additionally proves every
    static call site in the router modules passes a real code.
    """
    if code not in NOTICE_LABELS:
        raise KeyError(code)
    return f"{base}?notice={code}"


def notice_redirect(base: str, code: str, *, status_code: int = 303) -> RedirectResponse:
    """Return a redirect to `base` carrying `?notice=<code>` (default 303).

    Raises `KeyError` on an unrecognised code -- see `notice_url`.
    """
    return RedirectResponse(url=notice_url(base, code), status_code=status_code)
