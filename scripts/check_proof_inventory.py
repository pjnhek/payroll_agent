"""Selection-layer completeness gate for the four PROOF-01..04 durability proofs.

`.github/workflows/concurrency-proof.yml`'s own "Run the queue durability proofs"
step comment names a gap its execution-layer log guard cannot see: a typo'd
`queueproof` marker on one newly-added test, while the other queueproof tests still
pass, leaves the CI log reading "N passed" while the new proof silently never ran.
That gap lives at the *selection* layer — which test ids pytest's `-m` expression
actually picks up — not the execution layer, so no amount of watching pytest's exit
code or "N passed"/"N skipped" text can close it.

This module closes it with a pure decision function, `evaluate_inventory`, over
pytest collection data: for each of the four canonical proof ids it expects exactly
one test to be selected by the intersection pytest's CI step actually runs —
`queueproof and proof(id='PROOF-0N')` — and it separately catches a proof-tagged
test whose id typo'd past all four (`all_marked` minus `queueproof_marked` minus
every `per_id` entry), and a proof-tagged test that is well-formed but simply
missing the `queueproof` marker CI selects on (`all_marked` minus
`queueproof_marked`). `proof` and `queueproof` are two INDEPENDENT registered
markers (pyproject.toml); carrying `proof(id=...)` alone does not imply a test is
ever selected by CI.

`evaluate_inventory` performs no I/O and starts no subprocess, so it is red-proofed
hermetically (tests/test_proof_inventory.py) against every failure shape it claims
to catch, before this module is ever wired into a CI step (that wiring is plan
21-09's job, after the four proofs are tagged in waves 2-3).
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence

EXPECTED_PROOF_IDS: tuple[str, str, str, str] = (
    "PROOF-01",
    "PROOF-02",
    "PROOF-03",
    "PROOF-04",
)

# A pytest node id under `tests/`, anchored at both ends: a path ending in `.py`,
# `::`, a test (or Class::method) name, optionally followed by a `[...]`
# parametrization suffix. Deliberately NOT "any line starting with tests/" — that
# heuristic is brittle under parametrization and under a pytest collection-rendering
# change, and a parsing miss would silently understate the inventory. Exported so
# tests/test_proof_inventory.py can pin the grammar directly.
NODE_ID_PATTERN: re.Pattern[str] = re.compile(
    r"^tests/(?:[\w.-]+/)*[\w.-]+\.py::[\w]+(?:::[\w]+)*(?:\[[^\]]*\])?$"
)

# pytest's own trailing collection-count summary line, e.g.
# "11 tests collected in 0.04s", "63/1289 tests collected (1226 deselected) in
# 0.74s", or "no tests collected (1289 deselected) in 4.48s" — a legitimately
# ignorable line, not a broken/unparseable one.
_TRAILING_SUMMARY_PATTERN = re.compile(
    r"^(?:no tests collected|\d+(?:/\d+)? tests? collected)"
    r"(?: \(\d+ deselected\))? in [\d.]+s$"
)

# The warnings-summary block pytest emits is bounded by these two exact markers;
# everything between them (inclusive) is ignorable regardless of its own content,
# since a warning's text varies per dependency/version and cannot be pattern-pinned
# the way a node id or the trailing summary can.
_WARNINGS_BLOCK_START = re.compile(r"^=+ warnings summary =+$")
_WARNINGS_BLOCK_END_PREFIX = "-- Docs: "

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def evaluate_inventory(
    per_id: Mapping[str, Sequence[str]],
    all_marked: Sequence[str],
    queueproof_marked: Sequence[str],
    expected_ids: Sequence[str],
) -> list[str]:
    """Pure decision core. No I/O, no subprocess.

    `per_id` maps each expected proof id to the node ids collected for it under the
    CI-executed intersection selection (`queueproof and proof(id=...)`); `all_marked`
    is the bare `proof` marker's collected node ids; `queueproof_marked` is the bare
    `queueproof` marker's collected node ids. Returns a list of human-readable
    violations, empty when the inventory conforms.

    Detects four independent shapes (a conforming inventory can trip zero, a broken
    one can trip several at once for the same underlying test):
      1. an expected id whose selection is empty (missing);
      2. an expected id whose selection has more than one node id (duplicate,
         reporting every node id);
      3. a `proof`-marked node id, itself selected by `queueproof`, that appears
         under none of the expected ids' selections — the stray/typo'd-id shape
         (`id="PROOF-3"`, `id="PROOF-O1"`);
      4. a `proof`-marked node id absent from the `queueproof` selection — a proof
         with a syntactically fine `id=...` that CI's actual `-m queueproof` step
         will never run, independent of whether that id is even valid.
    """
    violations: list[str] = []

    accounted: set[str] = set()
    for proof_id in expected_ids:
        nodes = list(per_id.get(proof_id, ()))
        accounted.update(nodes)
        if not nodes:
            violations.append(
                f"PROOF id '{proof_id}' matched no test under the CI-executed selection "
                f"\"queueproof and proof(id='{proof_id}')\" — expected exactly one"
            )
        elif len(nodes) > 1:
            violations.append(
                f"PROOF id '{proof_id}' matched {len(nodes)} tests under the CI-executed "
                f"selection \"queueproof and proof(id='{proof_id}')\", expected exactly "
                f"one: {nodes}"
            )

    queueproof_set = set(queueproof_marked)
    seen: set[str] = set()
    for node_id in all_marked:
        if node_id in seen:
            continue
        seen.add(node_id)
        if node_id not in queueproof_set:
            violations.append(
                f"node '{node_id}' carries @pytest.mark.proof but is absent from the "
                "queueproof selection — it will never execute in CI's 'Run the queue "
                "durability proofs (real Postgres)' step in "
                ".github/workflows/concurrency-proof.yml; add @pytest.mark.queueproof"
            )
            continue
        if node_id not in accounted:
            violations.append(
                f"node '{node_id}' carries @pytest.mark.proof with an id that matches "
                f"none of the expected ids {tuple(expected_ids)} — check for a typo'd id"
            )

    return violations


def _parse_node_ids(output: str) -> list[str]:
    """Parse `pytest ... --collect-only -q` stdout into a list of node ids.

    Any collected line that is neither a full `NODE_ID_PATTERN` match nor a
    recognizably ignorable line (blank, the trailing collection-count summary, or a
    warnings-block line) raises — an unparseable collection output is a broken gate,
    not an empty inventory, and silently dropping it would understate the inventory.
    """
    node_ids: list[str] = []
    in_warnings_block = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if in_warnings_block:
            if line.startswith(_WARNINGS_BLOCK_END_PREFIX):
                in_warnings_block = False
            continue
        if _WARNINGS_BLOCK_START.match(line):
            in_warnings_block = True
            continue
        if line == "":
            continue
        if _TRAILING_SUMMARY_PATTERN.match(line):
            continue
        if NODE_ID_PATTERN.match(line):
            node_ids.append(line)
            continue
        raise ValueError(
            "unparseable pytest --collect-only line (not a node id, blank, trailing "
            f"summary, or warnings-block line): {raw_line!r}"
        )
    return node_ids


def _run_collect_only(marker_expression: str) -> list[str]:
    """Run one `--collect-only` selection and parse its node ids.

    Pytest's no-tests-collected exit code (5) is a legitimate empty result — exactly
    the missing-id shape `evaluate_inventory` must report — not a crash. Any other
    non-zero, non-5 exit code raises: a broken collection is not the same fact as an
    absent proof.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "-m",
            marker_expression,
            "--collect-only",
            "-q",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 5):
        raise RuntimeError(
            f"pytest --collect-only for marker expression {marker_expression!r} exited "
            f"{result.returncode} (expected 0 or pytest's no-tests-collected code 5).\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return _parse_node_ids(result.stdout)


def collect_inventory(
    expected_ids: Sequence[str],
) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Thin, impure collector. Runs the selection CI actually executes.

    For each expected id, runs the intersection `queueproof and proof(id='<ID>')` —
    the exact selection `.github/workflows/concurrency-proof.yml`'s queue-durability
    step executes. Then runs the bare `proof` selection for `all_marked` and the bare
    `queueproof` selection for `queueproof_marked`. Returns
    `(per_id, all_marked, queueproof_marked)`.
    """
    per_id = {
        proof_id: _run_collect_only(f"queueproof and proof(id='{proof_id}')")
        for proof_id in expected_ids
    }
    all_marked = _run_collect_only("proof")
    queueproof_marked = _run_collect_only("queueproof")
    return per_id, all_marked, queueproof_marked


def main() -> int:
    per_id, all_marked, queueproof_marked = collect_inventory(EXPECTED_PROOF_IDS)
    violations = evaluate_inventory(per_id, all_marked, queueproof_marked, EXPECTED_PROOF_IDS)
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
