"""D-09 decide->calculate WIRING smoke test (Codex Round-3 fix).

Round-2 only called calculate() directly, which merely duplicated the Phase-3
calculate golden and tested NONE of the wiring D-09 exists to prove. This version
drives the 12_exact_process_summit fixture through the SAME production spine --
reconcile_names -> validate -> decide -> _compute_line_items -> calculate -- and
asserts the resulting Thomas Bergmann paystub equals the Phase-3 golden. It closes
the join between the eval (which otherwise stops at decide) and the 'computes
payroll' headline, reusing the golden already trusted (no second net_pay oracle).
"""
import json
import pathlib
from decimal import Decimal

import pytest

from app.db.seed import seed
from app.models.contracts import Extracted
from app.models.roster import Roster
from app.pipeline.reconcile_names import reconcile_names
from app.pipeline.validate import validate
from app.pipeline.decide import decide
from app.pipeline.orchestrator import _compute_line_items


# ---------------------------------------------------------------------------
# Fixture: load Summit Tech roster + fixture 12 (Thomas Bergmann exact match)
# ---------------------------------------------------------------------------

_FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "eval"
    / "fixtures"
    / "12_exact_process_summit.json"
)


@pytest.fixture()
def summit_roster_and_fixture():
    seeded = seed(dry_run=True)
    raw = json.loads(_FIXTURE_PATH.read_text())
    biz = next(b for b in seeded.businesses if b["contact_email"] == raw["from_addr"])
    roster = Roster(
        business_id=biz["id"],
        employees=[e for e in seeded.employees if e.business_id == biz["id"]],
    )
    return raw, roster


# ---------------------------------------------------------------------------
# D-09 wiring smoke test
# ---------------------------------------------------------------------------


def test_decide_to_calculate_wiring_thomas_bergmann(summit_roster_and_fixture):
    """D-09: drives 12_exact_process_summit through reconcile->validate->decide->
    _compute_line_items and asserts == Phase-3 golden (penny-exact).

    The LABELED expected extraction (PATH A, D-07) feeds the deterministic stages
    so the test is unconfounded by extraction noise. _compute_line_items is the
    EXACT production code that joins decide's resolved matches to calculate() --
    importing it is what makes this a WIRING test, not a mere calculate() test.
    """
    raw, roster = summit_roster_and_fixture

    # Build the labeled expected extraction (PATH A -- D-07).
    # Use the fixture's expected block (Thomas Bergmann salaried, all hours null).
    exp = raw["expected"]["extracted"]
    extracted = Extracted.model_validate(
        {
            "run_id": "00000000-0000-0000-0000-000000000000",
            "employees": exp["employees"],
            "pay_period_start": exp["pay_period_start"],
            "pay_period_end": exp.get("pay_period_end"),
        }
    )

    # Run the deterministic spine (mirrors _run_stages exactly, no LLM).
    submitted_names = [e.submitted_name for e in extracted.employees]
    matches = reconcile_names(submitted_names, roster)
    issues = validate(extracted, roster, matches)
    decision = decide(extracted, matches, issues)

    # D-09 precondition: the clean exact fixture must gate to process so calculate runs.
    assert decision.final_action == "process", (
        "D-09 precondition: the clean exact fixture must gate to process so calculate runs"
    )

    # THE WIRING under test: the production join from decide's resolved matches
    # to calculate(). Do NOT call calculate() directly -- that would retest the
    # Phase-3 golden but prove NONE of the reconcile->_compute_line_items join.
    items = _compute_line_items(
        "00000000-0000-0000-0000-000000000000", extracted, matches, roster
    )

    assert len(items) == 1
    item = items[0]

    # Phase-3 golden values (test_federal_withholding.py:1131-1137, paycheckcity.com
    # verified penny-exact). Thomas Bergmann: annual=$240k, biweekly/26, MFJ, 8% 401k,
    # ytd_ss_wages=$183,900 (remaining SS cap = $600).
    assert item.gross_pay == Decimal("9230.77"), "D-09 wiring: gross_pay"
    assert item.pretax_401k == Decimal("738.46"), "D-09 wiring: pretax_401k"
    assert item.federal_withholding == Decimal("881.39"), (
        "D-09 wiring: federal_withholding (Phase-3 golden, paycheckcity.com verified)"
    )
    assert item.fica_ss == Decimal("37.20"), (
        "D-09 wiring: fica_ss (SS-straddle remaining_cap=600 -> 600*0.062=37.20)"
    )
    # Independent oracle (WR-04): Medicare is 1.45% of full gross, no cap, no 401k
    # exemption -> money(9230.77 * 0.0145) = 133.85. Net ties the reconciliation:
    # gross - pretax_401k - fica_ss - fica_medicare - federal_withholding.
    assert item.fica_medicare == Decimal("133.85"), (
        "D-09 wiring: fica_medicare (9230.77 * 0.0145 = 133.85)"
    )
    assert item.net_pay == Decimal("7439.87"), (
        "D-09 wiring: net_pay (9230.77 - 738.46 - 37.20 - 133.85 - 881.39 = 7439.87)"
    )


# ---------------------------------------------------------------------------
# C-4 eval _normalize parity RED test (Wave 1 — RESEARCH.md §Target 9)
#
# This test FAILS RED until Plan 07-02 updates run_eval.py:_normalize to use
# NFC normalization matching the new _norm in reconcile_names.
# The current _normalize does casefold().split() without NFC.
# ---------------------------------------------------------------------------


def test_eval_normalize_nfd_matches_nfc():
    """C-4 RED: eval's _normalize must treat NFD and NFC forms of a name identically.

    RESEARCH.md §Target 9 / Correction C-4: run_eval.py defines its own _normalize
    (line 51) that does `casefold().split()` without unicodedata.normalize. After
    MONEY-02 fixes reconcile_names._norm to NFC(casefold(NFC(s))), the eval's
    _normalize is left behind -- it produces different output for NFD vs NFC inputs,
    causing NFD-name fixtures to score incorrectly (false eval regressions, Pitfall 5).

    RED because current _normalize(NFD) != _normalize(NFC) -- the two forms produce
    different casefold byte sequences without NFC pre-normalization.
    Plan 07-02 fixes _normalize to match the new _norm form.
    """
    import unicodedata

    from eval.run_eval import _normalize  # noqa: PLC0415 -- intentional late import

    nfc_form = unicodedata.normalize("NFC", "Jos\xe9 Mart\xednez")
    nfd_form = unicodedata.normalize("NFD", nfc_form)

    # Sanity: the two forms must be byte-distinct (otherwise the test is vacuous).
    assert nfc_form != nfd_form, (
        "NFC and NFD forms must differ to exercise the normalization gap"
    )

    assert _normalize(nfd_form) == _normalize(nfc_form), (
        f"C-4 RED: _normalize(NFD) != _normalize(NFC) -- "
        f"got {_normalize(nfd_form)!r} vs {_normalize(nfc_form)!r}. "
        "Plan 07-02 must update run_eval.py:_normalize to NFC(casefold(NFC(s))) "
        "matching the new reconcile_names._norm (RESEARCH.md §Target 9 CORRECTION)"
    )
