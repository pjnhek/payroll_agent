"""Clarification-SUGGESTION prompt (LLM-05).

For a name the DETERMINISTIC resolver could NOT resolve, this prompt asks the cheap
(draft) tier which roster employee the client most likely meant, so the clarification
email can be specific ("did you mean David Reyes?"). This is where nickname knowledge
(Bob→Robert) beats plain string distance — the LLM doing real judgment beyond
extraction.

CRITICAL: the suggestion is advisory COPY only. It is produced AFTER the deterministic
gate has already decided request_clarification, and it NEVER feeds `decide` /
`final_action`. Wiring it into the decision would hand a money-moving name match back
to the model — the exact thing the deterministic resolver exists to prevent. The system
prompt states this explicitly so the model understands it is helping write an email,
not deciding anything.

Unlike the free-text clarify-DRAFTING prompt, this is a JSON-mode STRUCTURED call
(call_structured against NameSuggestionResponse), so it carries the literal word "json"
plus an example shape. That is the DeepSeek json_object convention, kept even though the
draft tier is Kimi, so there is one consistent JSON-mode discipline across all structured
calls.
"""
from __future__ import annotations

from openai.types.chat import ChatCompletionMessageParam

from app.models.roster import Roster

_SYSTEM = (
    "You are helping a payroll assistant write a clarification email. The client "
    "emailed some employee names that did NOT match the business's roster (typos, "
    "nicknames, or shorthand). Given the unmatched submitted names and the full "
    "roster, suggest which roster employee each submitted name most likely meant "
    "(use nickname and typo knowledge — e.g. 'Bob' likely means 'Robert', "
    "'David Reyez' likely means 'David Reyes'). If a submitted name does not "
    "plausibly match ANY roster employee, return null for it — do NOT guess "
    "wildly. IMPORTANT: this is for EMAIL COPY ONLY. It does NOT decide anything "
    "and does NOT process any payroll — a human still confirms every name. "
    'Respond ONLY with a json object of this shape: '
    '{"suggestions": [{"submitted_name": "David Reyez", '
    '"suggested_full_name": "David Reyes"}, '
    '{"submitted_name": "Xyz", "suggested_full_name": null}]}. '
    "suggested_full_name MUST be an EXACT full_name from the roster, or null."
)


def build_messages(
    unresolved_names: list[str], roster: Roster
) -> list[ChatCompletionMessageParam]:
    """Build the suggestion chat messages from the unresolved names + roster.

    The roster full_names are listed so the model can only choose among real
    employees (the caller additionally drops any suggestion not on the roster).
    """
    roster_lines = "\n".join(f"- {e.full_name}" for e in roster.employees) or "- (empty roster)"
    names_lines = "\n".join(f"- {n}" for n in unresolved_names)
    user = (
        "Roster employees (the only valid suggestions):\n"
        f"{roster_lines}\n\n"
        "Submitted names that did NOT match the roster:\n"
        f"{names_lines}\n\n"
        "Return the json object mapping each submitted name to the roster "
        "full_name it most likely meant, or null if there is no plausible match."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
