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

# label: the exact operator-facing sentence rendered as the delivery-review card's
# "Safe failure category" value. Strings unchanged from the pre-existing
# app/routes/runs.py:_DELIVERY_REVIEW_CATEGORY_LABELS dict this module replaces, plus
# the new authorization_expired entry (the BUG-1 root-cause fix).
DELIVERY_REVIEW_CATEGORY_LABELS: dict[str, str] = {
    "transport": "Transport uncertainty",
    "provider_5xx": "Provider service failure",
    "rate_limited": "Provider rate limit",
    "payload_mismatch": "Frozen payload mismatch",
    "authorization": "Provider authorization issue",
    "validation": "Provider validation issue",
    "configuration": "Delivery configuration issue",
    "authorization_expired": "Delivery authorization expired",
    "final_attempt_lease_expired": "Final attempt lease expired",
    "unknown": "Unknown delivery outcome",
}
