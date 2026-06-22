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
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.models.contracts import InboundEmail, Extracted
from app.models.roster import Roster, NameMatchResult
from app.pipeline.reconcile_names import reconcile_names
from app.pipeline.validate import validate
from app.pipeline.decide import decide
from app.db.seed import seed

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"
SUMMARY_PATH = pathlib.Path(__file__).resolve().parent / "summary.json"
CHART_PATH = pathlib.Path(__file__).resolve().parent / "chart.svg"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    """casefold + collapse whitespace -- same normalization reconcile_names uses."""
    return " ".join(name.casefold().split())


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
    """Load an eval fixture, validate the InboundEmail input portion."""
    raw = json.loads(path.read_text())
    # Strip eval-only keys before Pydantic validation (extra="forbid" on InboundEmail).
    input_fields = {k: v for k, v in raw.items() if k not in ("expected", "fixture_category")}
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

    # PATH A -- run deterministic stages on the LABELED expected extraction.
    submitted_names = [e.submitted_name for e in expected_extracted.employees]
    matches: list[NameMatchResult] = reconcile_names(submitted_names, roster)
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
        joined = " ".join(decision.gate_reasons)
        gate_reasons_match = all(s in joined for s in gate_reasons_contains)
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
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
    # Lazy imports: live pieces only on the --record path (T-04-07)
    from app.pipeline.extract import extract  # noqa: PLC0415
    from app.llm.client import llm_client    # noqa: PLC0415
    import uuid as _uuid                     # noqa: PLC0415

    fixture_paths = sorted(FIXTURE_DIR.glob("*.json"))
    fixture_paths = [f for f in fixture_paths if "_extraction" not in f.name]

    recorded = 0
    for fp in fixture_paths:
        raw = _load_fixture(fp)
        roster = _load_roster_for_fixture(raw["from_addr"])
        # Build InboundEmail from the fixture (strip eval-only keys).
        email_fields = {
            k: v for k, v in raw.items() if k not in ("expected", "fixture_category")
        }
        email = InboundEmail.model_validate(email_fields)
        run_id = _uuid.uuid4()
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
    print("Run with --chart (04-03) to generate eval/chart.svg")


if __name__ == "__main__":
    main()
