"""Tests for compose_email field-regression copy (Phase 7.5 Plan 02).

N5 fix: field-regression lines in _template_body emitted UNCONDITIONALLY
(before the unresolved/missing fallback gate).

D-7.5-09 wording lock: 'Reply with the {field_name} hours for {submitted_name},
or 'none' to confirm zero.' — deterministic regardless of LLM draft path.

Finding 4 fix: deterministic D-7.5-09 wording is APPENDED after any LLM draft
body in compose_clarification — not only in _template_body fallback.

rsplit last-dot split: 'M. Chen.hours_overtime' -> ('M. Chen', 'hours_overtime').
"""
from __future__ import annotations

from typing import Any

from app.models.contracts import Decision
from app.pipeline.compose_email import compose_clarification

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decision(
    *,
    gate_reasons: list[str] | None = None,
    unresolved_names: list[str] | None = None,
    missing_fields: list[str] | None = None,
) -> Decision:
    gate_reasons = gate_reasons or []
    unresolved_names = unresolved_names or []
    missing_fields = missing_fields or []
    return Decision(
        final_action="request_clarification",
        gate_reasons=gate_reasons,
        unresolved_names=unresolved_names,
        missing_fields=missing_fields,
        resolutions=[],
    )


class _DraftLLM:
    """Scriptable call_text stand-in."""

    def __init__(self, body: str | None) -> None:
        self._body = body
        self.calls: list[tuple[Any, ...]] = []

    def call_text(
        self, tier: Any, messages: Any, temperature: float = 0.3, **kwargs: Any
    ) -> str | None:
        self.calls.append((tier, messages, temperature))
        return self._body


# ---------------------------------------------------------------------------
# N5 fix: field-regression lines emitted unconditionally (before fallback gate)
# ---------------------------------------------------------------------------


def test_field_regression_line_present_when_other_clarification_coexists():
    """N5 fix: field-regression line appears even when unresolved_names also exists.

    The field-regression block must fire BEFORE the unresolved/missing fallback gate,
    not inside the 'if not unresolved and not missing' branch.
    """
    decision = _decision(
        gate_reasons=[
            "Bob Smith: unresolved (no roster match)",
            "field regression: alice.hours_overtime",
        ],
        unresolved_names=["Bob Smith"],
    )
    llm = _DraftLLM(None)  # force template floor

    body = compose_clarification(decision, llm=llm)

    assert "Bob Smith" in body, "unresolved name must appear"
    assert "hours_overtime" in body, (
        "N5: field-regression line must appear even with unresolved names"
    )


def test_field_regression_line_dotted_submitted_name():
    """rsplit last-dot split: 'M. Chen.hours_overtime' → name='M. Chen', field='hours_overtime'.

    NOT first-dot split ('M' + '.Chen.hours_overtime').
    """
    decision = _decision(
        gate_reasons=["field regression: M. Chen.hours_overtime"],
    )
    llm = _DraftLLM(None)  # force template floor

    body = compose_clarification(decision, llm=llm)

    # Should contain 'M. Chen' as the name (rsplit on LAST dot)
    assert "M. Chen" in body, (
        "rsplit last-dot split: submitted name 'M. Chen' must appear intact, not 'M'"
    )
    assert "hours_overtime" in body, "field name must appear"
    # Ensure 'M' alone is NOT treated as the name (would happen with split('.', 1))
    assert "M\n" not in body and "M (" not in body, (
        "first-dot split would produce 'M' as submitted_name — rsplit must prevent this"
    )


def test_field_regression_line_exact_wording_in_template_path():
    """D-7.5-09 wording lock: exact phrasing in _template_body path (LLM returns empty)."""
    decision = _decision(
        gate_reasons=["field regression: Alice Johnson.hours_overtime"],
    )
    llm = _DraftLLM(None)  # force template floor

    body = compose_clarification(decision, llm=llm)

    assert (
        "Reply with the hours_overtime hours for Alice Johnson, or 'none' to confirm zero."
        in body
    ), "D-7.5-09 wording lock: exact question must appear in the template path"


def test_field_regression_wording_present_even_when_llm_draft_nonempty():
    """Finding 4 fix: deterministic D-7.5-09 line is APPENDED after any LLM draft body.

    When the LLM returns non-empty content, compose_clarification previously returned
    the draft directly — the field-regression question was silently omitted.
    This fix ensures the wording always appears on the real (LLM-draft) path.
    """
    decision = _decision(
        gate_reasons=["field regression: Alice.hours_overtime"],
    )
    # LLM returns a NON-EMPTY draft body (the real path)
    llm = _DraftLLM("Hi, please check your submission.")

    body = compose_clarification(decision, llm=llm)

    # The LLM draft was returned — verify it is present
    assert "please check your submission" in body, "LLM draft content must be present"

    # The D-7.5-09 deterministic line must ALSO be present (Finding 4 fix)
    assert "Reply with the hours_overtime hours for Alice, or 'none' to confirm zero." in body, (
        "Finding 4: deterministic D-7.5-09 wording must appear even when LLM draft is non-empty"
    )


def test_field_regression_line_only_gate_reason():
    """Standalone case: only a field-regression gate_reason (no unresolved/missing).

    _template_body fallback must emit the field-regression question even in the
    'if not unresolved and not missing' branch — or better yet in an unconditional
    block before that branch.
    """
    decision = _decision(
        gate_reasons=["field regression: Alice.hours_overtime"],
    )
    llm = _DraftLLM(None)  # force template floor

    body = compose_clarification(decision, llm=llm)

    assert "hours_overtime" in body, "standalone field-regression must appear in template"
    assert "Alice" in body, "submitted_name must appear"


def test_multiple_field_regression_lines():
    """Multiple field_regression gate_reasons → multiple lines in the email."""
    decision = _decision(
        gate_reasons=[
            "field regression: Alice.hours_overtime",
            "field regression: Alice.hours_vacation",
        ],
    )
    llm = _DraftLLM(None)

    body = compose_clarification(decision, llm=llm)

    assert "hours_overtime" in body
    assert "hours_vacation" in body
