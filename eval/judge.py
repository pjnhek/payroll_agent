"""LLM-as-judge email quality scorer for clarification drafts.

Scores committed clarification draft text files (one per clarify-category fixture)
against a one-line rubric. This is a supplementary signal only -- the deterministic
metrics in run_eval.py carry the thesis.

Invariants:
- NEVER runs in CI (this file is referenced by no CI workflow) and is gated by
  ALLOW_LIVE_LLM -- it raises SystemExit if the flag is off, so it can never quietly
  bill a model run during a routine scoring pass.
- Scores are NOT broken out per category: n~=1 per category is not meaningful.
- Correctness floor: a draft naming a wrong real employee is capped at score 1 no matter
  how polished it reads. That "confident-LLM-wrongness" is precisely what this
  architecture exists to prevent, so it must never be able to score well.
- Uses tier="draft" (the drafting model), NOT the extraction tier, per the call_text()
  contract.
- Standalone script only; NOT called from run_eval.py main().

Usage (local only, requires ALLOW_LIVE_LLM=true + draft API key):
    uv run python eval/judge.py
    uv run python eval/judge.py --fixture-id 05_stored_alias_coastal

Draft files expected at: eval/drafts/{fixture_id}_draft.txt
Committed by the developer after running --record on clarify-category fixtures.
"""

import pathlib
import sys
from typing import TypedDict

from openai.types.chat import ChatCompletionMessageParam

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVAL_DIR = pathlib.Path(__file__).resolve().parent
DRAFTS_DIR = EVAL_DIR / "drafts"

# Rubric baked into the judge prompt. The correctness floor clause is load-bearing:
# without it a fluent email naming the WRONG employee can outscore a plain correct one.
RUBRIC = (
    "Score the clarification email 1-5 where: "
    "1=generic/names no specific employee; "
    "3=names the suggested employee and asks the precise question; "
    "5=specific+warm+actionable. "
    "CORRECTNESS FLOOR: if the email names a real employee by full_name but that "
    "employee is NOT the intended one for this fixture, cap the score at 1 "
    "regardless of all other quality aspects. "
    "Respond with a single integer 1-5 followed by a brief (one-sentence) explanation."
)


class JudgeResult(TypedDict):
    fixture_id: str
    raw_score: int
    final_score: int
    floor_applied: bool
    notes: str

# ---------------------------------------------------------------------------
# Core judge function
# ---------------------------------------------------------------------------


def judge_draft(
    draft_text: str,
    fixture_id: str,
    expected_employee_full_name: str | None,
) -> JudgeResult:
    """Score a single clarification draft using the LLM-as-judge rubric.

    Args:
        draft_text: The full text of the clarification email draft.
        fixture_id: Identifier of the fixture this draft was generated for.
        expected_employee_full_name: The intended employee for this fixture
            (used to enforce the correctness floor). None if not applicable.

    Returns:
        dict with keys: fixture_id, raw_score, final_score, floor_applied, notes.

    Raises:
        SystemExit: if allow_live_llm is False or the draft API key is absent.
    """
    # Check ALLOW_LIVE_LLM via os.environ directly BEFORE any app.config import.
    # app.config.Settings.database_url is a REQUIRED field with no default; calling
    # get_settings() when DATABASE_URL is absent raises ValidationError -- which
    # would produce a confusing error on the "not allowed" path. Reading
    # os.environ avoids the fail-fast and keeps the gate message clean.
    import os  # noqa: PLC0415

    allow_live_llm_raw = os.environ.get("ALLOW_LIVE_LLM", "").strip().lower()
    allow_live_llm = allow_live_llm_raw in ("1", "true", "yes")
    if not allow_live_llm:
        raise SystemExit(
            "judge_draft requires ALLOW_LIVE_LLM=true in the environment. "
            "Set it explicitly to run the LLM judge. "
            "The judge is local-only and never runs in CI."
        )

    # Import call_text inside this function -- keeps it off any non-judge import path.
    from app.llm.client import call_text  # noqa: PLC0415

    messages: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": "You are a payroll email quality evaluator. " + RUBRIC,
        },
        {
            "role": "user",
            "content": (
                f"Fixture: {fixture_id}\n"
                f"Intended employee: {expected_employee_full_name or 'not specified'}\n\n"
                f"Draft clarification email:\n---\n{draft_text}\n---\n\n"
                "Score (1-5) and one-sentence explanation:"
            ),
        },
    ]

    response = call_text(tier="draft", messages=messages, temperature=0.3)

    # Parse integer score from response (first integer found, 1-5).
    raw_score = 0
    notes = ""
    if response:
        notes = response.strip()
        for token in response.split():
            cleaned = token.strip(".,;:\"'()")
            if cleaned.isdigit():
                candidate = int(cleaned)
                if 1 <= candidate <= 5:
                    raw_score = candidate
                    break

    # -----------------------------------------------------------------------
    # Correctness floor: a wrong real employee named in the draft caps the score at 1.
    # This runs in code, not in the prompt, because the judge model cannot be trusted to
    # enforce the one rule that matters most.
    # -----------------------------------------------------------------------
    floor_applied = False
    final_score = raw_score

    if raw_score > 1 and expected_employee_full_name:
        # Load all roster full_names via seed (dry_run=True -- no DB needed).
        from app.db.seed import seed  # noqa: PLC0415

        seeded = seed(dry_run=True)
        roster_names = [e.full_name for e in seeded.employees]

        draft_lower = draft_text.casefold()
        for roster_name in roster_names:
            # Skip the intended employee -- naming the right person is correct.
            if roster_name.casefold() == expected_employee_full_name.casefold():
                continue
            # If any OTHER real roster full_name appears in the draft, apply floor.
            if roster_name.casefold() in draft_lower:
                final_score = min(raw_score, 1)
                floor_applied = True
                print(
                    f"  [correctness floor] Draft names '{roster_name}' but intended "
                    f"'{expected_employee_full_name}' -- capping score at 1 "
                    f"(raw={raw_score})"
                )
                break

    return {
        "fixture_id": fixture_id,
        "raw_score": raw_score,
        "final_score": final_score,
        "floor_applied": floor_applied,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Standalone script entry point (local-only, never CI)
# ---------------------------------------------------------------------------


def _load_draft_files() -> list[tuple[str, pathlib.Path]]:
    """Return (fixture_id, draft_path) pairs from eval/drafts/."""
    if not DRAFTS_DIR.exists():
        print(
            f"eval/drafts/ directory not found at {DRAFTS_DIR}. "
            "Create it and place *_draft.txt files for each clarify-category fixture."
        )
        return []

    draft_files = sorted(DRAFTS_DIR.glob("*_draft.txt"))
    if not draft_files:
        print(
            "No *_draft.txt files found in eval/drafts/. "
            "Run --record on clarify-category fixtures to generate them, "
            "then hand-verify and commit."
        )
        return []

    return [(f.stem.removesuffix("_draft"), f) for f in draft_files]


def _load_fixture_expected_employee(fixture_id: str) -> str | None:
    """Load the expected employee name for a fixture from eval/fixtures/."""
    fixture_dir = EVAL_DIR / "fixtures"
    import json  # noqa: PLC0415

    # Match fixture file by id field or filename.
    for fixture_path in sorted(fixture_dir.glob("*.json")):
        if "_extraction" in fixture_path.name:
            continue
        try:
            raw = json.loads(fixture_path.read_text())
            if raw.get("id") == fixture_id or fixture_path.stem == fixture_id:
                # Find first unresolved name with an expected_matched_employee_id.
                for entry in raw.get("expected", {}).get("reconciliation", []):
                    emp_id = entry.get("expected_matched_employee_id")
                    if emp_id:
                        # Look up full_name from seed.
                        from app.db.seed import seed  # noqa: PLC0415

                        seeded = seed(dry_run=True)
                        for emp in seeded.employees:
                            if str(emp.id) == str(emp_id):
                                return emp.full_name
        except (json.JSONDecodeError, KeyError):
            # Malformed fixture or missing key -- skip this fixture only.
            continue
        except Exception as exc:  # noqa: BLE001
            # An unexpected failure here returns None, which DISABLES the correctness
            # floor for this draft. Never swallow it silently: a swallowed bug would let
            # a draft naming the wrong real employee score 5 with nobody the wiser.
            print(
                f"WARNING: unexpected error loading expected employee from "
                f"{fixture_path.name}: {exc!r}",
                file=sys.stderr,
            )
            continue
    return None


def main() -> None:
    """Score committed draft files in eval/drafts/ and print a results table."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description=(
            "LLM-as-judge email quality scorer (local-only, never CI). "
            "Scores *_draft.txt files in eval/drafts/ using the Kimi draft tier. "
            "Requires ALLOW_LIVE_LLM=true."
        )
    )
    parser.add_argument(
        "--fixture-id",
        default=None,
        help="Score only the draft for this fixture_id (default: score all drafts).",
    )
    args = parser.parse_args()

    draft_pairs = _load_draft_files()
    if not draft_pairs:
        sys.exit(0)

    if args.fixture_id:
        draft_pairs = [(fid, p) for fid, p in draft_pairs if fid == args.fixture_id]
        if not draft_pairs:
            print(f"No draft found for fixture_id={args.fixture_id!r}")
            sys.exit(1)

    print(f"\nScoring {len(draft_pairs)} draft(s)...\n")
    print(f"{'Fixture ID':<35} {'Raw':>3} {'Final':>5} {'Floor':>5}  Notes")
    print("-" * 80)

    for fixture_id, draft_path in draft_pairs:
        draft_text = draft_path.read_text()
        expected_employee = _load_fixture_expected_employee(fixture_id)

        result = judge_draft(draft_text, fixture_id, expected_employee)

        floor_marker = "YES" if result["floor_applied"] else "no"
        note_preview = result["notes"][:60].replace("\n", " ") if result["notes"] else "-"
        print(
            f"{fixture_id:<35} {result['raw_score']:>3} {result['final_score']:>5} "
            f"{floor_marker:>5}  {note_preview}"
        )

    print("\nDone. Judge results above are supplementary -- the 3 deterministic")
    print("metrics (extraction F1, reconciliation accuracy, decision accuracy)")
    print("carry the thesis.")


if __name__ == "__main__":
    main()
