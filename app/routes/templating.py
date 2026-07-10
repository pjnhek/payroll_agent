"""Shared Jinja2Templates instance + badge class/label filters (D-08).

Carved out of app/main.py (Phase 13 Plan 03) — every router that renders a
TemplateResponse imports `templates` from this module, so there is exactly
one Jinja2Templates instance for the whole app.
"""
from __future__ import annotations

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")

# Badge class mapping (UI-SPEC Badge Contract)
# needs_operator (D-11-06): its own distinct attention-drawing class — "pending"
# is already taken by awaiting_approval (a routine settled gate state) and
# "bad" is already taken by rejected/error (failure states); needs_operator is
# neither routine nor a failure, it is an explicit escalation that needs the
# operator's attention NOW, so it gets "escalate" (own CSS rule below).
_BADGE_CLASS: dict[str, str] = {
    "received": "neutral",
    "extracting": "neutral",
    "computing": "neutral",
    "awaiting_reply": "neutral",
    "approved": "neutral",
    "computed": "neutral",
    "awaiting_approval": "pending",
    "sent": "good",
    "reconciled": "good",
    "rejected": "bad",
    "error": "bad",
    "needs_operator": "escalate",
}

# Badge label mapping (UI-SPEC Badge Contract copywriting)
_BADGE_LABEL: dict[str, str] = {
    "received": "Received",
    "extracting": "Extracting",
    "computing": "Computing",
    "awaiting_reply": "Awaiting Reply",
    "awaiting_approval": "Needs Approval",
    "approved": "Approved",
    "computed": "Computed",
    "sent": "Sent",
    "reconciled": "Complete",
    "rejected": "Rejected",
    "error": "Error",
    "needs_operator": "Needs Operator",
}


def badge_class_filter(status: str) -> str:
    """Map a payroll_runs.status to a CSS badge class suffix (UI-SPEC Badge Contract)."""
    return _BADGE_CLASS.get(str(status), "neutral")


def badge_label_filter(status: str) -> str:
    """Map a payroll_runs.status to its display label (UI-SPEC Copywriting Contract)."""
    return _BADGE_LABEL.get(str(status), str(status).replace("_", " ").title())


templates.env.filters["badge_class"] = badge_class_filter
templates.env.filters["badge_label"] = badge_label_filter
