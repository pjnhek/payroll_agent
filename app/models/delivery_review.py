"""Single source of truth for the delivery-review failure-category vocabulary.

The failure category a delivery attempt lands in (``transport``, ``validation``,
``authorization_expired``, ...) is produced in exactly one place
(``app/db/repo/job_settlement.py::_delivery_failure_category``), persisted verbatim
into ``outbound_delivery_attempts.failure_category`` and ``payroll_runs.error_detail``
(``delivery_review:<category>``), and rendered in exactly one place
(``app/routes/runs.py``). Before this module existed those two ends, plus the two SQL
CHECK constraints on ``outbound_delivery_attempts.failure_category``
(``app/db/schema.sql``), could drift independently — a producer emitting a category the
renderer's dict did not recognise silently dead-ended an operator on an actionless card
(the BUG-1 root cause). ``tests/test_status_drift.py`` pins all of these together.

This module holds ONLY the vocabulary. It has stdlib-only imports so nothing that
imports it can accidentally pull in the DB layer, and every string here is treated as
"hostile until proven fixed" downstream: a category key is reduced through this dict
before ever reaching a template, so an unrecognised value renders nothing rather than
an attacker- or bug-chosen string.
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class DeliveryReviewCategory:
    """One delivery-review failure category's operator-facing facts.

    replay_same_ok: can replaying the IDENTICAL frozen email under the SAME
        idempotency key (see gateway.py's message_id-keyed Idempotency-Key)
        succeed.
    fresh_send_ok: can a NEW slot (new Message-ID, new idempotency key, same
        frozen content) succeed.
    blocker: what must change out of band before either can succeed; None
        exactly when both flags are True. "authorization", "configuration",
        and "validation" are NOT "can never succeed" -- they are "will fail
        identically until something out of band changes" -- so this field
        names the specific thing, never a bare impossibility claim.
    """

    label: str
    uncertainty: str
    replay_same_ok: bool
    fresh_send_ok: bool
    blocker: str | None


# The table. Ten rows, one dict, table-driven-tested in
# tests/test_delivery_review_categories.py. Two booleans instead of a single
# `retryable: bool` because the two retry paths are genuinely different
# questions: payload_mismatch and final_attempt_lease_expired are retryable
# ONLY by a fresh slot, never by replaying the same frozen email under its
# existing key -- a single boolean gets exactly those two backwards.
DELIVERY_REVIEW_CATEGORIES: dict[str, DeliveryReviewCategory] = {
    "transport": DeliveryReviewCategory(
        label="Transport uncertainty",
        uncertainty=(
            "A network problem interrupted the send before the provider "
            "confirmed whether it was received."
        ),
        replay_same_ok=True,
        fresh_send_ok=True,
        blocker=None,
    ),
    "provider_5xx": DeliveryReviewCategory(
        label="Provider service failure",
        uncertainty=(
            "The provider failed while processing the send, so it is "
            "unclear whether the email went out."
        ),
        replay_same_ok=True,
        fresh_send_ok=True,
        blocker=None,
    ),
    "rate_limited": DeliveryReviewCategory(
        label="Provider rate limit",
        uncertainty=(
            "The provider throttled the send before confirming whether it "
            "went out."
        ),
        replay_same_ok=True,
        fresh_send_ok=True,
        blocker=None,
    ),
    "authorization_expired": DeliveryReviewCategory(
        label="Delivery authorization expired",
        uncertainty=(
            "The authorization window for this send closed before the "
            "provider confirmed whether it was received."
        ),
        replay_same_ok=True,
        fresh_send_ok=True,
        blocker=None,
    ),
    # unknown fails OPEN on purpose: it is the unclassified catch-all
    # (PipelineReason.DELIVERY_PROVIDER_FAILURE), and suppressing an action
    # that MIGHT work is a different failure than offering one that cannot.
    "unknown": DeliveryReviewCategory(
        label="Unknown delivery outcome",
        uncertainty=(
            "The failure did not match a known provider category, so what "
            "happened to this send is unclassified."
        ),
        replay_same_ok=True,
        fresh_send_ok=True,
        blocker=None,
    ),
    "payload_mismatch": DeliveryReviewCategory(
        label="Frozen payload mismatch",
        uncertainty=(
            "The provider rejected a replay because the frozen payload no "
            "longer matches its reserved idempotency key."
        ),
        replay_same_ok=False,
        fresh_send_ok=True,
        blocker=(
            "the frozen payload no longer matches its reserved key; only a "
            "new slot mints a fresh one"
        ),
    ),
    "final_attempt_lease_expired": DeliveryReviewCategory(
        label="Final attempt lease expired",
        uncertainty=(
            "The automatic retry budget for this reservation was spent "
            "before the provider confirmed the send."
        ),
        replay_same_ok=False,
        fresh_send_ok=True,
        blocker="the replay budget for this reservation is spent",
    ),
    "authorization": DeliveryReviewCategory(
        label="Provider authorization issue",
        uncertainty="The provider rejected the credentials or sender permission for this send.",
        replay_same_ok=False,
        fresh_send_ok=False,
        blocker=(
            "the provider rejected the credentials or the sender "
            "permission; the API key or sending domain must change first"
        ),
    ),
    "validation": DeliveryReviewCategory(
        label="Provider validation issue",
        uncertainty=(
            "The provider rejected the message itself, most often because "
            "the recipient address could not accept mail."
        ),
        replay_same_ok=False,
        fresh_send_ok=False,
        blocker=(
            "the provider rejected the message itself, most often an "
            "undeliverable recipient address; the recipient or sender "
            "configuration must change first"
        ),
    ),
    "configuration": DeliveryReviewCategory(
        label="Delivery configuration issue",
        uncertainty="Delivery is not configured for this deployment.",
        replay_same_ok=False,
        fresh_send_ok=False,
        blocker="delivery is not configured (no provider API key is set)",
    ),
}

# Backward-compatible flat view (category -> label only), DERIVED from the table
# above so it cannot drift from it. app/routes/runs.py's existing category-membership
# guard and its "Safe failure category" display both consume this.
DELIVERY_REVIEW_CATEGORY_LABELS: dict[str, str] = {
    key: category.label for key, category in DELIVERY_REVIEW_CATEGORIES.items()
}
