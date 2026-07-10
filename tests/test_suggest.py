"""Suggestion-only call tests (LLM-05, D-21-05) — the NEW Phase 2 hero copy.

`suggest_employees(unresolved_names, roster, llm=...)` makes ONE cheap-tier
(`draft`) structured call to suggest the most likely intended roster employee for
each name the deterministic resolver could NOT resolve. The result is advisory
COPY only — it is used solely to make the clarification email specific ("did you
mean David Reyes?") and NEVER feeds `decide` / `final_action` (D-21-05).

Invariants pinned here:
  - a scripted suggestion maps the submitted name → a roster full_name;
  - an EMPTY unresolved list makes NO LLM call (nothing to suggest);
  - any failure (API error, empty content, parse/validation, or the model
    returning null/unknown) degrades to NO entry for that name and NEVER raises —
    a suggestion failure can never strand the run (mirrors compose_email's WR-03);
  - `decide.py` never imports / references `suggest` — the suggestion is
    structurally walled off from the money-moving decision (T-021-06).
"""
from __future__ import annotations

import json
import pathlib
import uuid
from decimal import Decimal
from typing import Any

from app.models.roster import Employee, Roster
from app.pipeline.suggest import NameSuggestionResponse, suggest_employees

# ---------------------------------------------------------------------------
# A scriptable structured-call stand-in (mirrors the call_structured surface)
# ---------------------------------------------------------------------------


class _StructuredLLM:
    """A `call_structured` stand-in: returns a scripted JSON string parsed into
    `response_model`, or raises a scripted exception, recording every call."""

    def __init__(self, *, content: str | None = None, exc: BaseException | None = None) -> None:
        self._content = content
        self._exc = exc
        self.calls: list[tuple[Any, ...]] = []

    def call_structured(self, tier: Any, messages: Any, response_model: Any) -> Any:
        self.calls.append((tier, messages, response_model))
        if self._exc is not None:
            raise self._exc
        assert self._content is not None
        return response_model.model_validate_json(self._content)


def _roster() -> Roster:
    biz = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    david = Employee(
        id=uuid.UUID("e0000003-0000-0000-0000-000000000003"),
        business_id=biz,
        full_name="David Reyes",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("25"),
        retirement_contribution_pct=Decimal("0"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=52,
    )
    priya = Employee(
        id=uuid.UUID("e0000004-0000-0000-0000-000000000004"),
        business_id=biz,
        full_name="Priya Nair",
        known_aliases=[],
        pay_type="hourly",
        hourly_rate=Decimal("30"),
        retirement_contribution_pct=Decimal("0"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=52,
    )
    return Roster(business_id=biz, employees=[david, priya])


def _scripted(mapping: dict[str, str | None]) -> str:
    """A scripted NameSuggestionResponse JSON for a submitted→suggested mapping."""
    return json.dumps(
        {
            "suggestions": [
                {"submitted_name": k, "suggested_full_name": v}
                for k, v in mapping.items()
            ]
        }
    )


# ---------------------------------------------------------------------------
# Happy path — a scripted suggestion maps the unresolved name to a roster name
# ---------------------------------------------------------------------------


def test_suggests_roster_full_name_for_unresolved():
    """A typo'd "David Reyez" maps back to the roster's "David Reyes" via the
    cheap (draft) tier. The mapping is submitted_name → suggested_full_name."""
    llm = _StructuredLLM(content=_scripted({"David Reyez": "David Reyes"}))
    out = suggest_employees(["David Reyez"], _roster(), llm=llm)

    assert out == {"David Reyez": "David Reyes"}
    assert llm.calls, "an unresolved name must trigger the suggestion call"
    tier, _messages, model = llm.calls[0]
    assert tier == "draft", "the suggestion rides the cheap (draft) tier (D-21-05)"
    assert model is NameSuggestionResponse


def test_empty_unresolved_makes_no_llm_call():
    """Nothing unresolved → no LLM call, empty mapping (no work to do)."""
    llm = _StructuredLLM(content=_scripted({}))
    out = suggest_employees([], _roster(), llm=llm)

    assert out == {}
    assert llm.calls == [], "an empty unresolved list must make NO LLM call"


def test_model_returns_null_suggestion_yields_no_entry():
    """When the model returns null/unknown for a name, that name gets NO entry so
    the caller falls back to the generic ask (a non-suggestion is not invented)."""
    llm = _StructuredLLM(content=_scripted({"Zzzz Unknown": None}))
    out = suggest_employees(["Zzzz Unknown"], _roster(), llm=llm)

    assert out == {}, "a null suggestion must not produce a mapping entry"


def test_suggested_name_not_in_roster_is_dropped():
    """A suggestion that is NOT a real roster full_name is advisory copy we refuse
    to surface — the suggestion must name an ACTUAL employee or be dropped (so the
    clarification can never claim a non-existent employee)."""
    llm = _StructuredLLM(content=_scripted({"David Reyez": "Some Ghost"}))
    out = suggest_employees(["David Reyez"], _roster(), llm=llm)

    assert out == {}, "a suggested name absent from the roster must be dropped"


# ---------------------------------------------------------------------------
# Failure degradation — never raises, always {} (mirrors WR-03)
# ---------------------------------------------------------------------------


def test_api_error_degrades_to_empty_mapping():
    """An API error (auth/rate-limit/bad model) degrades to {} — it never raises
    out of this stage (a suggestion failure can never strand the run)."""
    llm = _StructuredLLM(exc=RuntimeError("simulated suggestion API error (401/429)"))
    out = suggest_employees(["David Reyez"], _roster(), llm=llm)

    assert out == {}, "an API error must degrade to an empty mapping, not raise"
    assert llm.calls, "the call was attempted before degrading"


def test_parse_failure_degrades_to_empty_mapping():
    """Malformed/garbled model output (a ValidationError on parse) degrades to {}
    rather than raising."""
    llm = _StructuredLLM(content="not json at all")
    out = suggest_employees(["David Reyez"], _roster(), llm=llm)

    assert out == {}, "a parse failure must degrade to an empty mapping, not raise"


def test_empty_content_degrades_to_empty_mapping():
    """Empty-content from the model degrades to {} (the WR-03 empty-content path)."""
    llm = _StructuredLLM(content="")
    out = suggest_employees(["David Reyez"], _roster(), llm=llm)

    assert out == {}, "empty content must degrade to an empty mapping"


# ---------------------------------------------------------------------------
# T-021-06 — the suggestion is structurally walled off from the decision
# ---------------------------------------------------------------------------


def test_decide_never_references_suggest():
    """decide.py must NEVER import or reference `suggest` — the suggestion is copy
    only and can never reach the money-moving decision (D-21-05, T-021-06)."""
    from app.pipeline import decide as decide_mod

    src = pathlib.Path(decide_mod.__file__).read_text()
    # Strip comment lines so a stray word in prose can't trip this; assert the
    # CODE never references suggest.
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "suggest" not in code.lower(), (
        "decide.py must not reference suggest — the suggestion never feeds the "
        "deterministic decision (D-21-05, T-021-06)"
    )
