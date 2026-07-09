"""Payroll Agent eval scorer -- Phase 4.

Scores 15 committed eval fixtures against the production pipeline stages.
Produces eval/summary.json with three core metrics:
  - Extraction precision/recall/F1 + field accuracy (D-06, EVAL-04)
  - Per-NAME reconciliation accuracy bucketed by category (D-03, D-02)
  - Two-level decision accuracy + confusion matrix with false_process headline (D-10, D-11)

Usage:
  uv run python eval/run_eval.py             # score + write summary.json
  uv run python eval/run_eval.py --check     # regression gate vs committed summary.json
  uv run python eval/run_eval.py --record    # LIVE re-record extraction caches (needs ALLOW_LIVE_LLM=true)

Design notes:
  - DB-FREE: no app.config import on the scoring/--check path (model id from env, no DATABASE_URL needed).
  - DRY seam: imports the SAME production pipeline functions (reconcile_names, validate, decide).
  - PATH A: labeled expected extraction feeds the deterministic stages (unconfounded by extraction noise, D-07).
  - CACHE: real committed extraction JSON feeds the extraction scoring ONLY (D-07 isolation).
  - --record: LIVE extraction via the production extract() -- gated by _require_live_llm() (D-05).
"""
import argparse
import json
import os
import pathlib
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

from app.db.seed import seed
from app.models.contracts import Extracted, InboundEmail
from app.models.roster import NameMatchResult, Roster
from app.pipeline.decide import decide
from app.pipeline.orchestrator import backfill_extracted
from app.pipeline.reconcile_names import _norm as _normalize
from app.pipeline.reconcile_names import reconcile_names
from app.pipeline.validate import detect_field_regression, validate

# ---------------------------------------------------------------------------
# Eval-only fixture keys — must be stripped before InboundEmail validation.
# (extra="forbid" on InboundEmail rejects unknown keys.)
#
# WR-04 FIX: one constant shared by BOTH _load_fixture and _record_extraction
# so the two strip sets cannot diverge. Adding a new eval-only key requires
# exactly ONE edit here.
# ---------------------------------------------------------------------------
_EVAL_ONLY_KEYS: frozenset[str] = frozenset(
    {"expected", "fixture_category", "prior_extracted", "prior_matches"}
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"
SUMMARY_PATH = pathlib.Path(__file__).resolve().parent / "summary.json"
CHART_PATH = pathlib.Path(__file__).resolve().parent / "chart.svg"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_live_llm() -> None:
    """Gate for --record mode: checks allow_live_llm flag + api key.

    Imports app.config ONLY inside this function so the scoring/--check paths
    never trigger the DATABASE_URL fail-fast (T-04-07).
    """
    from app.config import get_settings  # lazy import -- DB-free guard

    settings = get_settings()
    if not settings.allow_live_llm:
        raise SystemExit(
            "Re-record requires ALLOW_LIVE_LLM=true in the environment. "
            "Set it explicitly to re-record the extraction cache."
        )
    if not settings.extraction_api_key:
        raise SystemExit(
            "EXTRACTION_API_KEY must be set for --record mode. "
            "Set it in the environment or .env file."
        )


def _extraction_model_id() -> str:
    """Resolve the pinned extraction model id WITHOUT importing app.config.

    Reads EXTRACTION_MODEL env var; defaults to the same value Settings uses.
    This keeps the summary writer DB-free (no DATABASE_URL required, T-04-07).
    """
    return os.environ.get("EXTRACTION_MODEL", "deepseek-v4-flash")


def _load_roster_for_fixture(from_addr: str) -> Roster:
    """Build the business roster from seed data (no live DB)."""
    seeded = seed(dry_run=True)
    try:
        biz = next(b for b in seeded.businesses if b["contact_email"] == from_addr)
    except StopIteration:
        raise ValueError(
            f"from_addr {from_addr!r} not found in seeded businesses. "
            "Check that the fixture from_addr matches a seeded business contact_email."
        )
    employees = [e for e in seeded.employees if e.business_id == biz["id"]]
    return Roster(business_id=biz["id"], employees=employees)


def _load_fixture(path: pathlib.Path) -> dict:
    """Load an eval fixture, validate the InboundEmail input portion.

    Strips eval-only keys (expected, fixture_category, prior_extracted, prior_matches)
    before InboundEmail validation. The raw dict (including prior_extracted and
    prior_matches) is returned for use by _score_fixture (D-7.5-10 three-phase path).
    """
    raw = json.loads(path.read_text())
    # WR-04 FIX: use the module-level _EVAL_ONLY_KEYS constant (shared with
    # _record_extraction) so the two strip sets cannot diverge.
    input_fields = {k: v for k, v in raw.items() if k not in _EVAL_ONLY_KEYS}
    InboundEmail.model_validate(input_fields)  # raises ValidationError on schema drift
    return raw


def _load_extraction_cache(fixture_path: pathlib.Path) -> Extracted:
    """Load the committed extraction cache beside the fixture."""
    cache_path = fixture_path.parent / (fixture_path.stem + "_extraction.json")
    if not cache_path.exists():
        raise FileNotFoundError(
            f"Extraction cache not found: {cache_path}. "
            "Run 'uv run python eval/run_eval.py --record' first to generate it."
        )
    return Extracted.model_validate(json.loads(cache_path.read_text()))


def _expected_to_extracted(raw: dict) -> Extracted:
    """Build an Extracted from the LABELED expected block (PATH A, D-07).

    Used for isolated deterministic scoring -- NOT the cache. Feeds labeled
    truth into reconcile/validate/decide so extraction noise doesn't confound
    the deterministic metrics.
    """
    exp = raw["expected"]["extracted"]
    return Extracted.model_validate(
        {
            "run_id": "00000000-0000-0000-0000-000000000000",
            "employees": exp["employees"],
            "pay_period_start": exp["pay_period_start"],
            "pay_period_end": exp.get("pay_period_end"),
        }
    )


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------


def _score_fixture(raw: dict, fixture_path: pathlib.Path) -> dict:
    """Score one fixture. Returns a per-fixture result dict.

    D-07 split:
      PATH A -- labeled expected extraction -> deterministic stages (the thesis metric)
      CACHE  -- real recorded extraction -> extraction scoring ONLY (not conflated)
    """
    roster = _load_roster_for_fixture(raw["from_addr"])

    # D-07: build BOTH extraction inputs, keep them separate.
    expected_extracted = _expected_to_extracted(raw)     # labeled truth: drives PATH A
    cached_extracted = _load_extraction_cache(fixture_path)  # real model output: drives extraction scoring

    # D-7.5-10 three-phase path: deserialize prior_extracted + prior_matches if present.
    # Fixtures 16 and 17 have no prior_extracted → else branch fires (no regression possible).
    # Fixture 18 (MONEY-03 field-drop) has both → detect_field_regression called on raw extracted
    # BEFORE validate, mirroring the production three-phase ordering (detect → validate → decide).
    prior_extracted_raw = raw.get("prior_extracted")
    prior_matches_raw = raw.get("prior_matches")

    prior_extracted: Extracted | None = (
        Extracted.model_validate(prior_extracted_raw)
        if prior_extracted_raw is not None else None
    )
    prior_matches: list[NameMatchResult] | None = (
        [NameMatchResult.model_validate(m) for m in prior_matches_raw]
        if prior_matches_raw is not None else None
    )

    # PATH A -- run deterministic stages on the LABELED expected extraction.
    submitted_names = [e.submitted_name for e in expected_extracted.employees]
    matches: list[NameMatchResult] = reconcile_names(submitted_names, roster)

    if prior_extracted is not None:
        # WR-03 FIX: honor production three-phase ordering: detect → backfill → validate.
        # Production _run_stages runs: detect_field_regression (on RAW) → backfill_extracted
        # → validate(on BACKFILLED, with raw_drops + prior/prior_matches) → decide.
        # The old eval code skipped backfill and passed neither prior= nor prior_matches=
        # into validate, so a Round-2 carry-forward fixture would be scored as "missing"
        # by the eval while production processes it cleanly — a silent eval/production gap.
        #
        # Note: detect raw_drops is still computed on RAW (pre-backfill) expected_extracted,
        # exactly as in production (the drop must be visible before backfill fills it).
        raw_drops = detect_field_regression(
            prior_extracted, expected_extracted, prior_matches, matches
        )
        # Backfill phase: fill silence fields from the snapshot, mirroring production.
        # resolved_drops=None: eval has no backfill_skip concept (only scoring, not classify).
        expected_extracted = backfill_extracted(
            expected_extracted, prior_extracted, prior_matches, matches, resolved_drops=None
        )
        # Validate on BACKFILLED extraction with prior context for N8 suppression.
        # raw_field_drops= feeds the pre-backfill drops (Phase 1); prior_matches= threads
        # the snapshot-round reconciliation for the N8 guard — mirrors production exactly.
        issues = validate(
            expected_extracted,
            roster,
            matches,
            prior=prior_extracted,
            prior_matches=prior_matches,
            raw_field_drops=raw_drops,
        )
        # Note: the eval does not have a suppress_detection set (classify-first is an
        # orchestrator concern, not a scoring concern). The eval currently covers only
        # the Round-1 detect-and-clarify path (fixture 18). Round-2 carry-forward →
        # paystub outcomes are covered by the integration tests in test_resume_pipeline.py.
        # A future Round-2 fixture (e.g. 19_*) would exercise the full path here.
    else:
        issues = validate(expected_extracted, roster, matches)

    decision = decide(expected_extracted, matches, issues)

    # -----------------------------------------------------------------------
    # EXTRACTION SCORING (D-06) -- multiset alignment so duplicates count as FP
    # Score against the CACHED real extraction (not PATH A).
    # -----------------------------------------------------------------------
    actual_counts = Counter(
        _normalize(e.submitted_name) for e in cached_extracted.employees
    )
    expected_counts = Counter(
        _normalize(e["submitted_name"])
        for e in raw["expected"]["extracted"]["employees"]
    )

    true_positives = sum((actual_counts & expected_counts).values())   # multiset intersection
    false_positives = sum((actual_counts - expected_counts).values())  # extras + duplicates
    false_negatives = sum((expected_counts - actual_counts).values())  # dropped employees

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 1.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 1.0
    )
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # FIELD ACCURACY (EVAL-04) -- for employees matched by normalized name
    # Score per-field correctness on the matched employees.
    HOUR_FIELDS = [
        "hours_regular", "hours_overtime", "hours_vacation",
        "hours_sick", "hours_holiday", "contribution_401k_override",
    ]
    actual_by_name = {_normalize(e.submitted_name): e for e in cached_extracted.employees}
    expected_emps = {
        _normalize(e["submitted_name"]): e
        for e in raw["expected"]["extracted"]["employees"]
    }

    field_correct = 0
    field_total = 0
    for norm_name, exp_emp in expected_emps.items():
        act_emp = actual_by_name.get(norm_name)
        if act_emp is None:
            continue  # no match -- field accuracy not scored for this employee
        for field in HOUR_FIELDS:
            exp_val = exp_emp.get(field)
            act_val = getattr(act_emp, field, None)
            field_total += 1
            if exp_val is None and act_val is None:
                field_correct += 1
            elif exp_val is not None and act_val is not None:
                # Decimal exact equality -- never float (D-06)
                try:
                    if Decimal(str(act_val)) == Decimal(str(exp_val)):
                        field_correct += 1
                except Exception:
                    pass  # unparseable value counts as wrong

    extraction_scores = {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "field_accuracy": field_correct / field_total if field_total > 0 else 1.0,
        "field_correct": field_correct,
        "field_total": field_total,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }

    # -----------------------------------------------------------------------
    # RECONCILIATION SCORING (D-03, D-02) -- per-NAME from PATH A matches
    # A wrong-but-real match FAILS: source + resolved + matched_employee_id must all match.
    # -----------------------------------------------------------------------
    match_by_name = {_normalize(m.submitted_name): m for m in matches}
    reconciliation_results = []

    for entry in raw["expected"]["reconciliation"]:
        submitted = entry["submitted_name"]
        name_cat = entry["name_category"]
        expected_source = entry["expected_source"]
        expected_resolved = entry["expected_resolved"]
        expected_matched_id = entry.get("expected_matched_employee_id")

        actual = match_by_name.get(_normalize(submitted))
        if actual is None:
            # Name in expected but not in PATH A matches (shouldn't happen)
            reconciliation_results.append({
                "submitted_name": submitted,
                "name_category": name_cat,
                "correct": False,
                "actual_source": None,
                "actual_resolved": None,
                "actual_matched_employee_id": None,
                "expected_matched_employee_id": expected_matched_id,
            })
            continue

        source_match = (actual.source == expected_source)
        resolved_match = (actual.resolved == expected_resolved)
        # D-02: matched_employee_id must equal the labeled intended id.
        # A wrong-but-REAL match (matching a different employee) is a FAIL.
        if expected_matched_id is not None:
            id_match = (
                str(actual.matched_employee_id) == str(expected_matched_id)
            )
        else:
            id_match = (actual.matched_employee_id is None)

        correct = source_match and resolved_match and id_match

        reconciliation_results.append({
            "submitted_name": submitted,
            "name_category": name_cat,
            "correct": correct,
            "actual_source": actual.source,
            "actual_resolved": actual.resolved,
            "actual_matched_employee_id": (
                str(actual.matched_employee_id) if actual.matched_employee_id else None
            ),
            "expected_matched_employee_id": expected_matched_id,
        })

    # -----------------------------------------------------------------------
    # DECISION SCORING -- two levels (D-10)
    # -----------------------------------------------------------------------
    exp_dec = raw["expected"]["decision"]
    action_correct = (decision.final_action == exp_dec["final_action"])

    gate_reasons_contains = exp_dec.get("gate_reasons_contains", [])
    if gate_reasons_contains:
        # Match each expected substring against a SINGLE gate reason, never the
        # space-joined blob -- joining lets an expected substring straddle two
        # adjacent reasons and match spuriously (WR-01).
        gate_reasons_match = all(
            any(s in reason for reason in decision.gate_reasons)
            for s in gate_reasons_contains
        )
    else:
        gate_reasons_match = (
            set(decision.gate_reasons) == set(exp_dec.get("gate_reasons", []))
        )

    unresolved_match = (
        set(decision.unresolved_names) == set(exp_dec.get("unresolved_names", []))
    )
    missing_match = (
        set(decision.missing_fields) == set(exp_dec.get("missing_fields", []))
    )
    gate_struct_ok = gate_reasons_match and unresolved_match and missing_match

    decision_scores = {
        "action_correct": action_correct,
        "gate_struct_ok": gate_struct_ok,
        "final_action": decision.final_action,
        "expected_final_action": exp_dec["final_action"],
    }

    return {
        "fixture_id": raw["id"],
        "fixture_path": str(fixture_path.name),
        "fixture_category": raw["fixture_category"],
        "extraction": extraction_scores,
        "reconciliation": reconciliation_results,
        "decision": decision_scores,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _aggregate(fixture_results: list[dict]) -> dict:
    """Compute per-category metrics and confusion matrix from per-fixture results."""

    # -----------------------------------------------------------------------
    # EXTRACTION per-category + overall
    # -----------------------------------------------------------------------
    per_cat_extraction: dict[str, list] = {}
    for r in fixture_results:
        cat = r["fixture_category"]
        per_cat_extraction.setdefault(cat, []).append(r["extraction"])

    per_category_extraction = {}
    all_f1s = []
    all_field_accuracies = []
    for cat, scores_list in per_cat_extraction.items():
        cat_f1 = sum(s["f1"] for s in scores_list) / len(scores_list)
        cat_fa = sum(s["field_accuracy"] for s in scores_list) / len(scores_list)
        per_category_extraction[cat] = {"f1": cat_f1, "field_accuracy": cat_fa}
        all_f1s.extend(s["f1"] for s in scores_list)
        all_field_accuracies.extend(s["field_accuracy"] for s in scores_list)

    extraction_overall_f1 = sum(all_f1s) / len(all_f1s) if all_f1s else 0.0
    extraction_overall_field_accuracy = (
        sum(all_field_accuracies) / len(all_field_accuracies)
        if all_field_accuracies
        else 1.0
    )

    # -----------------------------------------------------------------------
    # RECONCILIATION per-NAME-category (D-12: fractions, not %)
    # -----------------------------------------------------------------------
    cat_recon: dict[str, dict] = {}
    for r in fixture_results:
        for entry in r["reconciliation"]:
            name_cat = entry["name_category"]
            if name_cat not in cat_recon:
                cat_recon[name_cat] = {"correct": 0, "total": 0}
            cat_recon[name_cat]["total"] += 1
            if entry["correct"]:
                cat_recon[name_cat]["correct"] += 1

    per_category_reconciliation = []
    for cat, counts in cat_recon.items():
        k, n = counts["correct"], counts["total"]
        per_category_reconciliation.append({
            "category": cat,
            "correct": k,
            "total": n,
            "accuracy": k / n if n > 0 else 0.0,
        })

    # -----------------------------------------------------------------------
    # DECISION confusion matrix (D-11, D-12)
    # -----------------------------------------------------------------------
    true_process = 0
    false_process = 0  # THE HEADLINE: leaked through, pays wrong person
    false_clarify = 0  # annoying, not dangerous
    true_clarify = 0

    for r in fixture_results:
        actual = r["decision"]["final_action"]
        expected = r["decision"]["expected_final_action"]
        if actual == "process" and expected == "process":
            true_process += 1
        elif actual == "process" and expected == "request_clarification":
            false_process += 1
        elif actual == "request_clarification" and expected == "process":
            false_clarify += 1
        else:  # actual == "request_clarification" and expected == "request_clarification"
            true_clarify += 1

    expected_clarify_total = false_process + true_clarify
    actual_process_total = false_process + true_process

    # PRIMARY: risk rate -- "of cases that SHOULD clarify, how many leaked through"
    false_process_rate = (
        false_process / expected_clarify_total if expected_clarify_total > 0 else 0.0
    )
    # SECONDARY: precision rate -- "of cases we DID process, how many were wrong"
    false_process_precision_rate = (
        false_process / actual_process_total if actual_process_total > 0 else 0.0
    )

    confusion_matrix = {
        "true_process": true_process,
        "false_process": false_process,
        "false_clarify": false_clarify,
        "true_clarify": true_clarify,
        "false_process_rate": false_process_rate,
        "false_process_precision_rate": false_process_precision_rate,
    }

    # -----------------------------------------------------------------------
    # Per-fixture-category decision (D-12: k/n fractions)
    # -----------------------------------------------------------------------
    per_cat_dec: dict[str, dict] = {}
    for r in fixture_results:
        cat = r["fixture_category"]
        if cat not in per_cat_dec:
            per_cat_dec[cat] = {"correct": 0, "total": 0}
        per_cat_dec[cat]["total"] += 1
        if r["decision"]["action_correct"]:
            per_cat_dec[cat]["correct"] += 1

    per_category_decision = {}
    for cat, counts in per_cat_dec.items():
        k, n = counts["correct"], counts["total"]
        per_category_decision[cat] = {
            "correct": k,
            "total": n,
            "fraction": f"{k}/{n}",  # D-12: honest at small n
        }

    # -----------------------------------------------------------------------
    # Gate-structure accuracy (rigor layer)
    # -----------------------------------------------------------------------
    gate_struct_correct = sum(
        1 for r in fixture_results if r["decision"]["gate_struct_ok"]
    )
    rigor_gate_struct_accuracy = (
        gate_struct_correct / len(fixture_results) if fixture_results else 0.0
    )

    return {
        "extraction_overall_f1": extraction_overall_f1,
        "extraction_overall_field_accuracy": extraction_overall_field_accuracy,
        "per_category_extraction": per_category_extraction,
        "per_category_reconciliation": per_category_reconciliation,
        "confusion_matrix": confusion_matrix,
        "per_category_decision": per_category_decision,
        "rigor_gate_struct_accuracy": rigor_gate_struct_accuracy,
    }


# ---------------------------------------------------------------------------
# Summary JSON writer
# ---------------------------------------------------------------------------


def _write_summary_json(
    fixture_results: list[dict], aggregated: dict, suite_run_id: str
) -> None:
    """Write eval/summary.json. suite_run_id threaded from main() so 04-04 can reuse it."""
    summary = {
        "schema_version": "1",
        "suite_run_id": suite_run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "extraction_model_id": _extraction_model_id(),  # env-resolved, NO app.config import
        "false_process_rate": aggregated["confusion_matrix"]["false_process_rate"],
        "confusion_matrix": aggregated["confusion_matrix"],
        "extraction_overall_f1": aggregated["extraction_overall_f1"],
        "extraction_overall_field_accuracy": aggregated["extraction_overall_field_accuracy"],
        "per_category_extraction": aggregated["per_category_extraction"],
        "per_category_reconciliation": aggregated["per_category_reconciliation"],
        "per_category_decision": aggregated["per_category_decision"],
        "rigor_gate_struct_accuracy": aggregated["rigor_gate_struct_accuracy"],
        "per_fixture": fixture_results,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# --check regression gate (D-17)
# ---------------------------------------------------------------------------


def _round4(v) -> float:
    """Round a float/int to 4 decimal places for stable comparison."""
    return round(float(v), 4)


def _assert_regression(fresh: dict, committed: dict) -> None:
    """Compare fresh scoring against committed summary.json (parsed+rounded, not bytes).

    Covers ALL scored metrics so no regression can slip through CI (D-17).
    Prints a descriptive diff and raises SystemExit(1) on any mismatch.
    """
    mismatches = []

    def _check(field: str, fresh_val, committed_val) -> None:
        if fresh_val != committed_val:
            mismatches.append(
                f"  {field}: {committed_val!r} -> {fresh_val!r}"
            )

    # --- confusion matrix: all four counts (integers) + both rates ---
    fresh_cm = fresh["confusion_matrix"]
    comm_cm = committed.get("confusion_matrix", {})

    for count_key in ("true_process", "false_process", "false_clarify", "true_clarify"):
        _check(
            f"confusion_matrix.{count_key}",
            int(fresh_cm[count_key]),
            int(comm_cm.get(count_key, -1)),
        )

    _check(
        "confusion_matrix.false_process_rate",
        _round4(fresh_cm["false_process_rate"]),
        _round4(comm_cm.get("false_process_rate", -1)),
    )
    _check(
        "confusion_matrix.false_process_precision_rate",
        _round4(fresh_cm["false_process_precision_rate"]),
        _round4(comm_cm.get("false_process_precision_rate", -1)),
    )

    # --- extraction overall ---
    _check(
        "extraction_overall_f1",
        _round4(fresh["extraction_overall_f1"]),
        _round4(committed.get("extraction_overall_f1", -1)),
    )
    _check(
        "extraction_overall_field_accuracy",
        _round4(fresh["extraction_overall_field_accuracy"]),
        _round4(committed.get("extraction_overall_field_accuracy", -1)),
    )

    # --- per-category extraction ---
    fresh_pce = fresh.get("per_category_extraction", {})
    comm_pce = committed.get("per_category_extraction", {})
    all_cats = set(fresh_pce) | set(comm_pce)
    for cat in sorted(all_cats):
        fresh_cat = fresh_pce.get(cat, {})
        comm_cat = comm_pce.get(cat, {})
        _check(
            f"per_category_extraction.{cat}.f1",
            _round4(fresh_cat.get("f1", -1)),
            _round4(comm_cat.get("f1", -1)),
        )
        _check(
            f"per_category_extraction.{cat}.field_accuracy",
            _round4(fresh_cat.get("field_accuracy", -1)),
            _round4(comm_cat.get("field_accuracy", -1)),
        )

    # --- per-category reconciliation (correct/total counts + accuracy) ---
    fresh_pcr = {e["category"]: e for e in fresh.get("per_category_reconciliation", [])}
    comm_pcr = {e["category"]: e for e in committed.get("per_category_reconciliation", [])}
    all_recon_cats = set(fresh_pcr) | set(comm_pcr)
    for cat in sorted(all_recon_cats):
        fr = fresh_pcr.get(cat, {})
        cr = comm_pcr.get(cat, {})
        _check(f"per_category_reconciliation.{cat}.correct", int(fr.get("correct", -1)), int(cr.get("correct", -1)))
        _check(f"per_category_reconciliation.{cat}.total", int(fr.get("total", -1)), int(cr.get("total", -1)))
        _check(
            f"per_category_reconciliation.{cat}.accuracy",
            _round4(fr.get("accuracy", -1)),
            _round4(cr.get("accuracy", -1)),
        )

    # --- per-category decision (correct/total counts) ---
    fresh_pcd = fresh.get("per_category_decision", {})
    comm_pcd = committed.get("per_category_decision", {})
    all_dec_cats = set(fresh_pcd) | set(comm_pcd)
    for cat in sorted(all_dec_cats):
        fr = fresh_pcd.get(cat, {})
        cr = comm_pcd.get(cat, {})
        _check(f"per_category_decision.{cat}.correct", int(fr.get("correct", -1)), int(cr.get("correct", -1)))
        _check(f"per_category_decision.{cat}.total", int(fr.get("total", -1)), int(cr.get("total", -1)))

    # --- gate-structure accuracy ---
    _check(
        "rigor_gate_struct_accuracy",
        _round4(fresh.get("rigor_gate_struct_accuracy", -1)),
        _round4(committed.get("rigor_gate_struct_accuracy", -1)),
    )

    if mismatches:
        print("REGRESSION DETECTED -- the following metrics changed:", file=sys.stderr)
        for m in mismatches:
            print(m, file=sys.stderr)
        raise SystemExit(
            "Regression detected. Re-record or fix the scoring. "
            "Run without --check to regenerate summary.json."
        )

    print("--check passed: no regression against committed summary.json")


# ---------------------------------------------------------------------------
# --record mode: LIVE extraction (D-05)
# ---------------------------------------------------------------------------


def _record_extraction() -> None:
    """Re-record extraction caches via LIVE extraction.

    Imports the live pieces INSIDE this function (keeps them off the
    scoring/--check import path -- lazy-import discipline, T-04-07).

    Called only when args.record is set, AFTER _require_live_llm() passes.
    Re-recording OVERWRITES synthetic day-one caches (04-01) with genuine
    model output. The 04-01 divergence validator runs against the COMMITTED
    day-one caches, not post-record output -- so this is not a regression.
    """
    # Lazy imports: live pieces only on the --record path (T-04-07).
    # uuid is already imported at module level -- no lazy re-import needed (IN-01).
    from app.llm.client import llm_client  # noqa: PLC0415
    from app.pipeline.extract import extract  # noqa: PLC0415

    fixture_paths = sorted(FIXTURE_DIR.glob("*.json"))
    fixture_paths = [f for f in fixture_paths if "_extraction" not in f.name]

    recorded = 0
    for fp in fixture_paths:
        raw = _load_fixture(fp)
        roster = _load_roster_for_fixture(raw["from_addr"])
        # WR-04 FIX: use the shared _EVAL_ONLY_KEYS constant (same as _load_fixture).
        # The old code stripped only ("expected", "fixture_category"), so fixtures
        # 16/17/18 with prior_extracted/prior_matches caused ValidationError here
        # (InboundEmail is extra="forbid"). Unifying the strip set fixes --record mode.
        email_fields = {
            k: v for k, v in raw.items() if k not in _EVAL_ONLY_KEYS
        }
        email = InboundEmail.model_validate(email_fields)
        run_id = uuid.uuid4()
        # LIVE extraction: the SAME production extractor, real DeepSeek call.
        extracted = extract(email, roster, run_id=run_id, llm=llm_client)
        cache_path = fp.parent / (fp.stem + "_extraction.json")
        cache_path.write_text(extracted.model_dump_json(indent=2))
        print(f"recorded {cache_path.name}")
        recorded += 1

    print(
        f"Live re-record complete: {recorded} caches written "
        f"(model: {_extraction_model_id()})."
    )


# ---------------------------------------------------------------------------
# SVG chart writer (D-08, D-11, D-12, D-13)
# ---------------------------------------------------------------------------


def _write_svg_chart(fixture_results: list[dict], aggregated: dict) -> None:
    """Generate eval/chart.svg from in-memory scoring results.

    3-subplot layout:
      Subplot 1 -- Extraction field accuracy + employee-set F1 per fixture category
      Subplot 2 -- Reconciliation accuracy per name-category (k/n fractions, D-12)
      Subplot 3 -- Decision confusion matrix 2x2 + false-process headline (D-11)

    matplotlib imported inside this function only (NOT at module top level) to
    keep it off the --check/scoring import path (CI has the dep only for chart
    generation, not the regression gate).
    """
    # Local imports only -- never at module level (T-04-11, D-08)
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")                      # non-interactive backend, safe on CI/server
    import matplotlib.pyplot as plt  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 14))

    # -----------------------------------------------------------------------
    # Subplot 1 -- Extraction: field accuracy + F1 per fixture category (grouped bars)
    # -----------------------------------------------------------------------
    pce = aggregated["per_category_extraction"]
    categories = list(pce.keys())
    field_values = [pce[c]["field_accuracy"] for c in categories]
    f1_values = [pce[c]["f1"] for c in categories]

    y = np.arange(len(categories))
    h = 0.38
    bars_fa = ax1.barh(y - h / 2, field_values, height=h, color="steelblue", label="field accuracy")
    bars_f1 = ax1.barh(y + h / 2, f1_values, height=h, color="#9ecae1", label="employee-set F1")

    ax1.set_yticks(y)
    ax1.set_yticklabels(categories)
    ax1.set_xlabel("Score")
    ax1.set_xlim(0, 1.05)
    overall_fa = aggregated["extraction_overall_field_accuracy"]
    overall_f1 = aggregated["extraction_overall_f1"]
    ax1.set_title(
        f"Extraction: field accuracy + employee-set F1 per fixture category\n"
        f"(overall: field_accuracy={overall_fa:.3f}, F1={overall_f1:.3f})"
    )
    ax1.legend(loc="lower right")

    # Annotate each field-accuracy bar
    for bar, val in zip(bars_fa, field_values):
        ax1.text(
            min(val + 0.005, 1.03),
            bar.get_y() + bar.get_height() / 2,
            f"{val:.3f}",
            va="center",
            ha="left",
            fontsize=8,
        )
    # Annotate each F1 bar
    for bar, val in zip(bars_f1, f1_values):
        ax1.text(
            min(val + 0.005, 1.03),
            bar.get_y() + bar.get_height() / 2,
            f"{val:.3f}",
            va="center",
            ha="left",
            fontsize=8,
        )

    # -----------------------------------------------------------------------
    # Subplot 2 -- Reconciliation accuracy per NAME-category (k/n fractions, D-12)
    # -----------------------------------------------------------------------
    rec_data = aggregated["per_category_reconciliation"]
    # Sort by category name for stable ordering
    rec_data_sorted = sorted(rec_data, key=lambda r: r["category"])
    cat_labels = [f'{r["category"]}\n(n={r["total"]})' for r in rec_data_sorted]
    acc_values = [r["accuracy"] for r in rec_data_sorted]

    bars_rec = ax2.barh(cat_labels, acc_values, color="seagreen")
    ax2.set_xlabel("Accuracy on fixtures of category X")  # D-13 exact label wording
    ax2.set_title(
        "Name-reconciliation accuracy by name category\n"
        "(resolver returns none for all 4 unresolved categories -- these are coverage buckets)"
    )
    ax2.set_xlim(0, 1.05)

    # Annotate each bar with "k/n" fraction (D-12)
    for bar, r in zip(bars_rec, rec_data_sorted):
        label = f'{r["correct"]}/{r["total"]}'
        ax2.text(
            min(r["accuracy"] + 0.005, 1.03),
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center",
            ha="left",
            fontsize=9,
        )

    # -----------------------------------------------------------------------
    # Subplot 3 -- Decision confusion matrix 2x2 + false-process headline
    # -----------------------------------------------------------------------
    cm = aggregated["confusion_matrix"]
    ax3.axis("off")
    matrix_data = [
        ["", "Expected: process", "Expected: clarify"],
        ["Actual: process", str(cm["true_process"]), str(cm["false_process"])],
        ["Actual: clarify", str(cm["false_clarify"]), str(cm["true_clarify"])],
    ]
    table = ax3.table(cellText=matrix_data, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1, 1.8)

    # Highlight the FALSE-PROCESS cell (row 1, col 2) -- the dangerous error:
    # "Actual: process" row x "Expected: clarify" col = pays the wrong person.
    # Row 0 = header; row 1 = "Actual: process"; col 2 = "Expected: clarify".
    # (Codex HIGH fix: prior [2,2] highlighted true-clarify, the SAFE cell.)
    table[1, 2].set_facecolor("#FFCCCC")

    ax3.set_title(
        f"Decision Confusion Matrix\n"
        f"FALSE-PROCESS (pays wrong person): "
        f"{cm['false_process']} of {cm['false_process'] + cm['true_clarify']} "
        f"should-clarify cases  ({cm['false_process_rate']:.1%})",
        fontsize=13,
        fontweight="bold",
    )

    # -----------------------------------------------------------------------
    # Honesty caption (Codex partial-fix #1 -- don't overclaim extraction bars)
    # -----------------------------------------------------------------------
    model_id = _extraction_model_id()
    fig.text(
        0.5,
        0.01,
        (
            "Extraction scored against committed extraction caches (replayed, not a live model run); "
            "deterministic stages (reconcile/validate/decide) scored on labeled expected extraction. "
            f"Model: {model_id}"
        ),
        ha="center",
        fontsize=8,
        color="gray",
        wrap=True,
    )

    plt.tight_layout(pad=2.0)
    plt.savefig(str(CHART_PATH), format="svg", bbox_inches="tight")
    plt.close()
    print(f"eval/chart.svg written ({CHART_PATH.stat().st_size} bytes)")


# ---------------------------------------------------------------------------
# D-14: Optional DB write -- derives from eval/summary.json (never in-memory)
# ---------------------------------------------------------------------------


def _write_db_results() -> None:
    """Write per-fixture/per-metric rows to eval_results from eval/summary.json.

    Design notes (D-14):
    - Reads os.environ directly BEFORE any app.config import to avoid the
      required-field fail-fast in Settings (DATABASE_URL has no default).
    - Only proceeds when DATABASE_URL is a real DSN (not absent, not the
      CI/dev "placeholder" sentinel).
    - Derives suite_run_id and all rows from the committed eval/summary.json
      so the DB rows can never diverge from the published artifact.
    - psycopg imported inside this function (local import, not at module level).
    - On psycopg.Error: warns and returns -- DB write is optional, never crashes eval.
    """
    # CRITICAL: check os.environ BEFORE importing app.config (Codex R4 LOW fix).
    # Settings.database_url is a REQUIRED field with no default; calling
    # get_settings() when DATABASE_URL is absent raises ValidationError.
    db_url = os.environ.get("DATABASE_URL")

    if not db_url or db_url == "placeholder":
        print("DB write skipped (DATABASE_URL unset or placeholder)")
        return

    if not SUMMARY_PATH.exists():
        print(
            "DB write skipped (no eval/summary.json -- run the scorer first)"
        )
        return

    # summary.json is authoritative: read from disk, not in-memory state.
    summary = json.loads(SUMMARY_PATH.read_text())

    suite_run_id = summary["suite_run_id"]

    # Build per-fixture, per-metric rows.
    rows: list[tuple] = []
    for entry in summary.get("per_fixture", []):
        fixture_id = entry["fixture_id"]
        details_json = json.dumps(entry)

        # Derive each metric value explicitly (per-fixture shape from 04-02).
        metrics: dict[str, float] = {
            "extraction_f1": float(entry["extraction"]["f1"]),
            "extraction_field_accuracy": float(entry["extraction"]["field_accuracy"]),
            # reconciliation is a list; derive a scalar per-fixture accuracy.
            "reconciliation_accuracy": (
                sum(1 for r in entry["reconciliation"] if r["correct"])
                / len(entry["reconciliation"])
            )
            if entry.get("reconciliation")
            else 1.0,
            "decision_action_correct": 1.0 if entry["decision"]["action_correct"] else 0.0,
            "decision_gate_struct_ok": 1.0 if entry["decision"]["gate_struct_ok"] else 0.0,
        }

        for metric_name, value in metrics.items():
            rows.append((suite_run_id, fixture_id, metric_name, value, details_json))

    # Import psycopg inside the function -- keeps it off the scoring path.
    import psycopg  # noqa: PLC0415

    try:
        with psycopg.connect(db_url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO eval_results
                            (suite_run_id, fixture_id, metric_name, value, details)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        rows,
                    )
        print(
            f"DB write complete: {len(rows)} rows inserted "
            f"(suite_run_id={suite_run_id})"
        )
    except psycopg.Error as exc:
        print(f"DB write warning: {exc} -- skipping (DB write is optional)")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Payroll Agent eval scorer -- Phase 4"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regression gate: compare scoring against committed eval/summary.json",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help=(
            "Re-record extraction caches via LIVE extraction "
            "(requires ALLOW_LIVE_LLM=true + EXTRACTION_API_KEY)"
        ),
    )
    parser.add_argument(
        "--chart",
        action="store_true",
        help="Generate eval/chart.svg from scoring results (requires matplotlib dev dep)",
    )
    parser.add_argument(
        "--db",
        action="store_true",
        help=(
            "Write eval results to eval_results table from eval/summary.json "
            "(requires real DATABASE_URL)"
        ),
    )
    args = parser.parse_args()

    if args.record:
        _require_live_llm()
        _record_extraction()
        print(
            "Live re-record complete. "
            "Review the regenerated *_extraction.json, "
            "then re-run without --record to re-score."
        )
        sys.exit(0)

    # Generate a suite_run_id once -- threaded into summary.json and (04-04) the DB write.
    suite_run_id = str(uuid.uuid4())

    fixture_paths = sorted(FIXTURE_DIR.glob("*.json"))
    fixture_paths = [f for f in fixture_paths if "_extraction" not in f.name]

    fixture_results = []
    for fp in fixture_paths:
        raw = _load_fixture(fp)
        result = _score_fixture(raw, fp)
        fixture_results.append(result)

    aggregated = _aggregate(fixture_results)

    if args.check:
        if not SUMMARY_PATH.exists():
            print(
                "No committed eval/summary.json found. "
                "Run without --check first to generate it.",
                file=sys.stderr,
            )
            sys.exit(1)
        committed = json.loads(SUMMARY_PATH.read_text())
        _assert_regression(aggregated, committed)
        sys.exit(0)

    _write_summary_json(fixture_results, aggregated, suite_run_id)
    cm = aggregated["confusion_matrix"]
    print(
        f"eval/summary.json written. "
        f"false_process_count={cm['false_process']} (HEADLINE), "
        f"false_process_rate={cm['false_process_rate']:.4f}"
    )
    print(
        f"extraction_overall_f1={aggregated['extraction_overall_f1']:.4f}, "
        f"field_accuracy={aggregated['extraction_overall_field_accuracy']:.4f}"
    )
    if args.db:
        _write_db_results()
    if args.chart:
        _write_svg_chart(fixture_results, aggregated)
    else:
        print("Run with --chart to generate eval/chart.svg")


if __name__ == "__main__":
    main()
