"""decide -> calculate WIRING smoke test.

The eval scores the judgment stages and stops at decide; the calculate golden tests
calculate() in isolation. Neither one exercises the JOIN between them, so a break in
_compute_line_items — the production code that hands decide's resolved matches to
calculate() — would leave both suites green while the paystub numbers went wrong.

This module closes that gap: it drives the 12_exact_process_summit fixture through the
SAME production spine (reconcile_names -> validate -> decide -> _compute_line_items ->
calculate) and asserts the resulting Thomas Bergmann paystub equals the already-trusted
calculate golden. Reusing that golden is deliberate — inventing a second net_pay oracle
here would just be a second chance to be wrong.

Calling calculate() directly instead would prove nothing about the join, and is exactly
the mistake this test exists to avoid.
"""
# The eval harness exposes private helpers used by these wiring tests.
import json
import pathlib
import uuid
from decimal import Decimal

import pytest

from app.db.seed import seed
from app.models.contracts import Extracted
from app.models.roster import Roster
from app.pipeline.decide import decide
from app.pipeline.orchestrator import _compute_line_items
from app.pipeline.reconcile_names import reconcile_names
from app.pipeline.validate import validate

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
# The wiring smoke test
# ---------------------------------------------------------------------------


def test_decide_to_calculate_wiring_thomas_bergmann(summit_roster_and_fixture):
    """Drive the fixture through the real spine and assert the paystub is penny-exact.

    The LABELED expected extraction feeds the deterministic stages, so a flaky
    extraction cannot confound the result — the only thing under test is the join.
    _compute_line_items is imported from production rather than reimplemented: a local
    copy would pass while the shipping code was broken.
    """
    raw, roster = summit_roster_and_fixture

    # Use the fixture's labeled expected block (Thomas Bergmann salaried, hours null)
    # rather than a live extraction, so extraction noise cannot fail this test.
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

    # Precondition: the clean exact fixture must gate to process, or calculate never
    # runs and every assertion below would be vacuously unreached.
    assert decision.final_action == "process", (
        "precondition: the clean exact fixture must gate to process so calculate runs"
    )

    # THE WIRING under test: the production join from decide's resolved matches to
    # calculate(). Calling calculate() directly here would retest the calculate golden
    # and prove nothing about the reconcile -> _compute_line_items join.
    items = _compute_line_items(
        uuid.UUID("00000000-0000-0000-0000-000000000000"), extracted, matches, roster
    )

    assert len(items) == 1
    item = items[0]

    # The trusted golden values (mirrored from the federal-withholding suite, verified
    # penny-exact against paycheckcity.com). Thomas Bergmann: annual=$240k, biweekly/26,
    # MFJ, 8% 401k, ytd_ss_wages=$183,900 — which leaves only $600 of SS cap remaining,
    # so this fixture also exercises the Social-Security wage-base straddle.
    assert item.gross_pay == Decimal("9230.77"), "wiring: gross_pay"
    assert item.pretax_401k == Decimal("738.46"), "wiring: pretax_401k"
    assert item.federal_withholding == Decimal("881.39"), (
        "wiring: federal_withholding (golden, paycheckcity.com verified)"
    )
    assert item.fica_ss == Decimal("37.20"), (
        "wiring: fica_ss (SS straddle — only 600 of cap remains, 600 * 0.062 = 37.20)"
    )
    # Medicare is checked against an independent hand-computed oracle rather than the
    # engine's own logic: 1.45% of the FULL gross, no cap and no 401k exemption ->
    # money(9230.77 * 0.0145) = 133.85. Net then ties the reconciliation identity:
    # gross - pretax_401k - fica_ss - fica_medicare - federal_withholding.
    assert item.fica_medicare == Decimal("133.85"), (
        "wiring: fica_medicare (9230.77 * 0.0145 = 133.85)"
    )
    assert item.net_pay == Decimal("7439.87"), (
        "wiring: net_pay (9230.77 - 738.46 - 37.20 - 133.85 - 881.39 = 7439.87)"
    )


# ---------------------------------------------------------------------------
# The eval's name normalizer must stay in lockstep with production's.
#
# The eval scores production's judgment functions, so any normalization the eval does
# on its own must match theirs exactly. If the eval's _normalize drifts from
# reconcile_names._norm, accented-name fixtures score as failures that production
# handles correctly — the chart reports a regression that does not exist.
# ---------------------------------------------------------------------------


def test_eval_normalize_nfd_matches_nfc():
    """The eval's _normalize must treat NFD and NFC forms of a name identically.

    Production's reconcile_names._norm is double-NFC — NFC(casefold(NFC(s))) — so that
    visually identical names in different Unicode normalization forms resolve to the
    same employee. A plain casefold().split() in the eval does NOT: NFD and NFC inputs
    casefold to different byte sequences, so the eval would mis-score every accented
    name and report false regressions against a production path that is working.
    """
    import unicodedata

    # Import run_eval's own private binding rather than the defining module: that is
    # what proves the EVAL uses the NFC-correct normalizer, which is the whole point.
    # mypy cannot see a private re-export, hence the ignore.
    from eval.run_eval import (  # type: ignore[attr-defined]  # private re-export, invisible to mypy
        _normalize,  # noqa: PLC0415 -- intentional late import of a private re-export
    )

    nfc_form = unicodedata.normalize("NFC", "Jos\xe9 Mart\xednez")
    nfd_form = unicodedata.normalize("NFD", nfc_form)

    # Sanity: the two forms must be byte-distinct (otherwise the test is vacuous).
    assert nfc_form != nfd_form, (
        "NFC and NFD forms must differ to exercise the normalization gap"
    )

    assert _normalize(nfd_form) == _normalize(nfc_form), (
        f"_normalize(NFD) != _normalize(NFC) -- "
        f"got {_normalize(nfd_form)!r} vs {_normalize(nfc_form)!r}. "
        "run_eval.py:_normalize must be NFC(casefold(NFC(s))), matching "
        "reconcile_names._norm, or accented-name fixtures score as false regressions"
    )


def test_record_extraction_llm_client_import_resolves(tmp_path, monkeypatch):
    """The --record lazy-import path must resolve the live client module."""
    from eval import run_eval  # noqa: PLC0415 -- exercise the lazy-import caller

    monkeypatch.setattr(run_eval, "FIXTURE_DIR", tmp_path)

    run_eval._record_extraction()
