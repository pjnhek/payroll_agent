"""Throwaway bootstrap drafting aid — NOT a production generator.

Prompts the Kimi draft model to produce candidate messy payroll emails for
the builder to hand-edit and hand-label into eval/fixtures/. The committed
fixtures are the source of truth; this script just provides phrasing variety.
Delete or ignore after the fixture corpus is built.
"""
# Imports are lazy (inside __main__) so this module can be imported without
# DATABASE_URL set, consistent with the other eval scripts.
from openai.types.chat import ChatCompletionMessageParam


def _require_live_llm() -> None:
    from app.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    if not settings.allow_live_llm:
        raise SystemExit("Set ALLOW_LIVE_LLM=true to use this drafting helper.")
    if not settings.draft_api_key:
        raise SystemExit("DRAFT_API_KEY must be set to use this drafting helper.")


if __name__ == "__main__":
    from app.llm.client import call_text  # noqa: PLC0415

    _require_live_llm()
    messages: list[ChatCompletionMessageParam] = [
        {
            "role": "user",
            "content": (
                "Draft a realistic but intentionally messy payroll email for a "
                "small business. Include at least one name abbreviation or nickname "
                "that might not match the employee's full name. Be casual and "
                "informal, like a real small-business payroll submission. Include a "
                "random mix of regular/OT hours. Sign off with a name."
            ),
        }
    ]
    draft = call_text(
        tier="draft",
        messages=messages,
        temperature=0.9,
    )
    print(draft or "No content returned — retry or hand-write the fixture.")
