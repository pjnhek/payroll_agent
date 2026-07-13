"""Comment-provenance guard: source text explains the code, never the project's history.

A comment earns its place by stating a CONSTRAINT — something a future reader could
otherwise break. A comment that cites the ticket, decision, review finding, or project
phase that caused the code to exist states nothing a reader can act on: the citation
points at a planning document the reader does not have, and it decays the moment that
document is archived. This scanner walks the source tree and flags any such citation,
in comments, docstrings, and runtime string literals alike (a ticket ID inside an
assertion message or an argparse description is the same decayed reference as one
inside a comment, and it is additionally user-visible).

The rule this enforces is NOT "delete the comment". It is "keep the constraint, drop
the label": `# CR-02: a column missing from RUN_COLS is invisible to load_run` becomes
`# A column missing from RUN_COLS is invisible to every load_run caller.` The reason
survives; the provenance pointer does not.

Two directions of the pattern table are executable, because a guard is only as
trustworthy as its own proof:

* `test_no_ticket_provenance_in_source_tree` runs the scanner over the LIVE tree and
  is the permanent gate. It also emits a machine-readable scan record (the enforced
  patterns, the file count, the excluded shapes) so a reader of the test output can
  see exactly what was and was not enforced without reading this source.
* `test_scanner_flags_every_blocked_shape_and_passes_legitimate_prose` proves the
  scanner FIRES: every entry in `BLOCKED_PATTERNS` is exercised against a synthetic
  file, and legitimate prose is proven not to trip it. Without this, a scanner that
  matched nothing at all would still pass the live gate.
* `test_editorial_only_shapes_are_not_guard_enforced` proves the scanner is SILENT on
  every shape in `EDITORIAL_ONLY_PATTERNS` — the shapes that were evaluated as
  candidate ticket patterns and deliberately left out of the gate because a legitimate
  use of each survives on the tree. Without this test, the narrowing would be a claim
  in prose rather than a fact about the code.

Scope note: unlike the private-import guard next door, this one DOES scan `tests/`,
and it scans non-Python surfaces too (the schema DDL, the dashboard templates, the
stylesheet, and the eval fixture notes). Provenance rot is a property of text, not of
Python, and it decayed in every one of those places.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The swept surface: every file whose text a maintainer reads. Globs rather than a
# recursive `.py` walk, because the rot reached the DDL comments, the Jinja templates,
# the stylesheet, and the eval fixture notes as well as the Python.
#
# The build/CI/config surface is in scope for the same reason the Python is: a maintainer
# reads `pyproject.toml` to learn why line-length is 100, and reads a workflow to learn why
# a job exists. A ticket ID there rots exactly as fast, and points at a document that has
# been archived. Excluding it is what let 17 references survive the phase-15 sweep.
#
# NOT in scope, deliberately: CLAUDE.md, AGENTS.md, README.md, docs/**. Narrating the
# project's history is the PURPOSE of those documents, not rot in them.
SCAN_GLOBS = (
    "app/**/*.py",
    "app/db/schema.sql",
    "app/templates/*.html",
    "app/static/*.css",
    "eval/**/*.py",
    "eval/fixtures/*.md",
    "scripts/*.py",
    "tests/**/*.py",
    ".github/workflows/*.yml",
    "Dockerfile",
    "pyproject.toml",
    "render.yaml",
    ".dockerignore",
    ".env.example",
)

# This file is the ONE file that must contain the forbidden shapes: its pattern table
# and its synthetic fixtures are made of them. Scanning itself would make the gate
# permanently and unfixably red. Named here rather than checked inline so the exemption
# is a single, greppable, obviously-scoped fact rather than a magic condition buried in
# the walker.
SELF_EXEMPT_FILENAME = "test_comment_provenance_guard.py"


# The gate. Every entry is a shape that carries project provenance and nothing else, and
# every entry was checked to produce ZERO false positives against the live tree — breadth
# is subordinate to that. Each is (name, regex, one-line description).
#
# On the word boundary in `decision-id`: it is load-bearing, not decoration. Without the
# leading `\b`, `D-[0-9]` matches INSIDE the requirement IDs this project must keep --
# BOUND-01 and FOUND-04 both end in "D" -- and the guard would fail CI on the very
# traceability it exists to protect. The synthetic fixtures pin that.
#
# On `phase-ref`: "Phase 3" is banned even when it labels an algorithm's own steps rather
# than a project phase, because the two are textually indistinguishable and only one of
# them is legitimate. The sanctioned way to enumerate steps is to number them ("1. detect
# / 2. backfill / 3. calculate"), which is unambiguous, survives a renumbered roadmap, and
# scans clean. The legitimate-prose fixture pins that form.
BLOCKED_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "decision-id",
        r"\bD-(?:[0-9]|[A-Z][0-9])[0-9A-Za-z.\-]*",
        "a design-decision citation (D-04, D-11-01, D-7.5-08, D-A3-05)",
    ),
    (
        # INFO must precede IN in the alternation for readability (the regex engine
        # backtracks and would match either way, but "IN" first reads like INFO is covered
        # by it, and it is NOT: "IN-" requires the hyphen immediately after "IN", so
        # INFO-02 slips through a table that lists only IN). This phase's own prompt-echo
        # finding was filed as INFO-02 — the family is real.
        #
        # The review-round prefix is R[0-9]+, NOT a hardcoded R2. Three cross-AI review
        # rounds have run against this project (R2-*, R3-* — 25 uses of R3 alone), and a
        # fourth would have slipped a table that only knew R2. Generalise the round number
        # rather than wait to be bitten by R4.
        #
        # This alternation is the complete set of families this project has actually used;
        # `test_every_historical_ticket_family_is_covered` below pins it against the real
        # inventory so a new family cannot be invented without failing a test. Requirement
        # IDs (BOUND, CI, COMM, POLISH, STRUCT, TYPE — the live REQUIREMENTS.md families)
        # are deliberately absent: those are traceability that must SURVIVE the sweep.
        "review-ticket",
        r"\b(?:WR|CR|CX|GAP|NEW|INFO|IN|BLOCKER|REVIEW|CHANGE|R[0-9]+|OPS[0-9]*)-[0-9]",
        "a review or gap ticket ID (WR-01, CR-02, CX-03, GAP-2, R3-1, INFO-02, IN-08, "
        "BLOCKER-2, REVIEW-2, CHANGE-5, OPS2-01)",
    ),
    (
        "fix-ticket",
        r"\bFIX[ -](?:[0-9]|[A-Z]\b)",
        "a numbered or lettered fix ID (FIX-5, FIX C)",
    ),
    (
        "pitfall-ref",
        r"\bPitfall\s*#?\s*[0-9]",
        "a citation of a numbered pitfall in a planning document",
    ),
    (
        "review-fix-phrase",
        r"(?i)\breview fix\b",
        "the phrase that attributes code to a review round instead of stating its reason",
    ),
    (
        "phase-ref",
        r"\bPhase [0-9]",
        "a capital-P project-phase reference (number the steps instead)",
    ),
    (
        "task-id",
        r"\bT-[0-9]+-[0-9]+",
        "a threat-model or task ID (T-8-07, T-15-01)",
    ),
    (
        # WARNING belongs here, with the other severities, not in the ticket table.
        # R[0-9]+ (not R[0-9]) for the same reason as review-ticket above: R10-HIGH must
        # match, and a hardcoded single digit would silently stop at round 9.
        "severity-label",
        r"\b(?:HIGH|MEDIUM|LOW|WARNING)-[0-9]|\bR[0-9]+-(?:HIGH|MEDIUM|LOW)\b",
        "a review-finding severity label (LOW-6, HIGH-2, WARNING-1, R2-MEDIUM)",
    ),
    (
        "reviewer-name",
        r"(?i)\bcodex\b",
        "the name of a review tool, which explains provenance rather than code",
    ),
    (
        "uat-ref",
        r"\bUAT\s*#\s*[0-9]",
        "a citation of a numbered acceptance-test item",
    ),
    (
        "finding-ref",
        r"(?i)\bfinding\s*#\s*[0-9]",
        "a citation of a numbered review finding",
    ),
    (
        "ui-spec-ref",
        r"\bUI-SPEC\b",
        "a citation of the UI design contract document",
    ),
    (
        "planning-doc-ref",
        r"\b(?:PATTERNS|CONTEXT|REQUIREMENTS|ROADMAP|UI-SPEC|PLAN|SUMMARY|REVIEW"
        r"|DISCUSSION-LOG|VERIFICATION|SKELETON|AI-SPEC)\.md\b",
        "a citation of a planning document the reader of this code does not have",
    ),
)


# The narrowing, made executable. Each entry is a shape that WAS evaluated as a candidate
# for the gate above and deliberately left out, because a legitimate use of it survives on
# the tree — enforcing it would fail CI on correct code. Each carries the shape, a real
# example of it, and the reason it is out.
#
# `test_editorial_only_shapes_are_not_guard_enforced` walks this table and proves each
# example scans clean. That is what makes the exclusions a property of the code rather
# than a sentence someone wrote once: delete an entry and the test stops exercising it;
# add a wrong one and the test fails.
#
# Entries are (name, shape regex, example line, reason).
EDITORIAL_ONLY_PATTERNS: tuple[tuple[str, str, str, str], ...] = (
    (
        "requirement-id",
        r"\b[A-Z]{4,}-[0-9]{2}\b",
        "# The roster contract is fixed by CALC-03, BOUND-01, COMM-01 and FOUND-04.",
        "Requirement IDs are LIVE traceability into the requirements register, not decayed "
        "history; they must never trip the gate.",
    ),
    (
        "research-derivation-citation",
        r"\bRESEARCH\.md\b",
        "# (1) Single/Standard/Weekly/$800 -- hand-computed, see RESEARCH.md worked example.",
        "The tax tests cite the research note as the DERIVATION RECORD for the transcribed "
        "2026 IRS bracket numbers -- a correctness citation of the same class as the "
        "irs.gov ones, deliberately kept.",
    ),
    (
        "suppression-code",
        r"#\s*(?:noqa|type:\s*ignore)",
        "raise SystemExit(1)  # noqa: BLE001 -- the gateway must never crash the pipeline",
        "A noqa/type-ignore code plus its mandatory plain-English reason is a live "
        "instruction to the linter, not provenance.",
    ),
    (
        "external-source-citation",
        r"\b(?:irs|ssa)\.gov\b",
        "# Bracket rows transcribed from irs.gov/pub/irs-pdf/p15t.pdf (2026 edition).",
        "An external authority for a money constant is exactly the kind of citation a "
        "reader CAN act on; the sweep preserved every one.",
    ),
)


def _iter_scan_files(repo_root: pathlib.Path) -> list[pathlib.Path]:
    """Every file in the swept surface, deduplicated and sorted, minus this guard itself."""
    found: set[pathlib.Path] = set()
    for glob in SCAN_GLOBS:
        found.update(p for p in repo_root.glob(glob) if p.is_file())
    return sorted(p for p in found if p.name != SELF_EXEMPT_FILENAME)


def scan_files_for_ticket_provenance(files: list[pathlib.Path]) -> list[str]:
    """Scan `files` line by line and return one `path:lineno: line` string per hit.

    Deliberately a plain text scan rather than an AST walk over comment tokens: the
    provenance rot lives in runtime strings (assertion messages, an argparse description,
    a user-visible template caption) just as much as in comments, and half the swept
    surface -- the DDL, the templates, the stylesheet, the fixture notes -- is not Python
    at all.
    """
    compiled = [(name, re.compile(pattern)) for name, pattern, _ in BLOCKED_PATTERNS]
    violations: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, regex in compiled:
                if regex.search(line):
                    violations.append(f"{path}:{lineno}: [{name}] {line.strip()}")
                    break
    return violations


def _scan_record(file_count: int) -> str:
    """The machine-readable record of what this run actually enforced.

    Printed by the live gate so that "the pattern table was tuned to zero false
    positives over N files" is something a reader of the test output can CHECK, rather
    than a claim they have to take on trust from a summary document.
    """
    lines = ["COMMENT-PROVENANCE SCAN RECORD", f"files_scanned: {file_count}"]
    lines.append(f"enforced_patterns: {len(BLOCKED_PATTERNS)}")
    for name, pattern, description in BLOCKED_PATTERNS:
        lines.append(f"  enforced  {name:20s} {pattern}   # {description}")
    lines.append(f"editorial_only_patterns: {len(EDITORIAL_ONLY_PATTERNS)}")
    for name, pattern, _example, reason in EDITORIAL_ONLY_PATTERNS:
        lines.append(f"  excluded  {name:20s} {pattern}   # {reason}")
    return "\n".join(lines)


def test_no_ticket_provenance_in_source_tree() -> None:
    """The permanent gate: no ticket, decision, finding, or phase citation anywhere in
    the swept surface. Emits the scan record (visible under `pytest -s` / `-rA`) so the
    enforced table, the excluded table, and the file count are evidence rather than
    narrative.
    """
    files = _iter_scan_files(REPO_ROOT)
    assert files, "the scan globs matched no files -- the guard would be vacuously green"

    record = _scan_record(len(files))
    print("\n" + record)

    violations = scan_files_for_ticket_provenance(files)
    assert not violations, (
        "Source text must explain the code, not cite the ticket that produced it. "
        "Keep the constraint, drop the label.\n"
        + "\n".join(violations)
        + "\n\n"
        + record
    )


def test_scanner_flags_every_blocked_shape_and_passes_legitimate_prose(
    tmp_path: pathlib.Path,
) -> None:
    """Prove the scanner fires -- on every blocked shape -- and only on those.

    The live gate above is green whenever the scanner finds nothing, INCLUDING when it
    finds nothing because it is broken. This is the test that tells those two apart, so
    it must exercise every row of the table (a row nothing pins can rot into a
    never-matching regex) and pin the legitimate prose that must survive.
    """
    # One synthetic file per blocked shape, each containing a realistic instance of it.
    samples: dict[str, str] = {
        "decision-id": "# Sequencing is fixed by D-11-01 and D-A3-05; do not reorder.",
        "review-ticket": "# Added for WR-01; see also CR-02, CX-03, GAP-2 and OPS2-01.",
        "fix-ticket": 'assert total > 0, "FIX C: the reconciliation must not be skipped"',
        "pitfall-ref": "# Guards against Pitfall #1 in the research note.",
        "review-fix-phrase": "# Column projection narrowed here (review fix).",
        "phase-ref": '_DESC = "Payroll Agent eval scorer -- Phase 4"',
        "task-id": "# Mitigates T-8-07: header injection via the employee name.",
        "severity-label": "# record_only passed straight through (LOW-6).",
        "reviewer-name": "# Codex flagged the fallback as unreachable.",
        "uat-ref": "# Covers UAT #3: the operator can reject a computed run.",
        "finding-ref": "# Structured return type (Finding #10).",
        "ui-spec-ref": "/* badge palette per UI-SPEC */",
        "planning-doc-ref": "# The invariant is spelled out in PATTERNS.md.",
    }
    table_names = [name for name, _, _ in BLOCKED_PATTERNS]
    assert sorted(samples) == sorted(table_names), (
        "every blocked pattern needs a synthetic sample -- an unexercised row can rot "
        "into a regex that never matches without anything failing"
    )

    for name, line in samples.items():
        probe = tmp_path / f"{name}.py"
        probe.write_text(line + "\n", encoding="utf-8")
        hits = scan_files_for_ticket_provenance([probe])
        assert hits, f"the {name!r} pattern failed to flag its own sample: {line!r}"

    # Legitimate prose: the shapes that LOOK ticketish and are not. Every line here is
    # modeled on real text the sweep deliberately kept.
    legit = tmp_path / "legit.py"
    legit.write_text(
        "\n".join(
            [
                "# Fix the rounding before comparing to the gross total.",
                "# This phase of parsing only splits the body; the next one classifies it.",
                "# Both phases run inside one transaction.",
                # The sanctioned algorithm-step form: numbered, not phase-labelled. The
                # orchestrator's own DETECT/BACKFILL/CALC ordering is written exactly
                # this way, and this fixture is what keeps the gate off it.
                "# 1. detect the reply round. 2. backfill the roster. 3. calculate.",
                "# Requirement IDs stay: CALC-03, BOUND-01, COMM-01, FOUND-04, CLAR-01.",
                "# Fixture f0000010 exercises the collision branch.",
                "value = round(gross, 2)  # noqa: BLE001 -- the gateway must never crash",
                "conn = pool.get()  # type: ignore[attr-defined]  # private re-export seam",
                "# Bracket rows transcribed from irs.gov/pub/irs-pdf/p15t.pdf (2026).",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hits = scan_files_for_ticket_provenance([legit])
    assert not hits, "legitimate prose was flagged:\n" + "\n".join(hits)


# Every ticket-ID family this project has ACTUALLY used, harvested from the full commit
# history and the planning archive:
#
#   git log --format=%B \
#     | grep -ohE '\b[A-Z][A-Z0-9]{1,8}-[0-9]+\b' | sed -E 's/-[0-9]+$//' | sort -u
#
# This inventory exists because the vocabulary was wrong three times in a row. Round 1 of
# the cross-AI review found `render.yaml` unscanned; round 2 found the `IN-NN` family
# missing; round 3 found `R3-NN` missing (the table hardcoded `R2`) along with BLOCKER,
# REVIEW, CHANGE, and WARNING. Each time the fix was to bolt on one more prefix and each
# time the next round found another. Enumerating the real inventory and asserting against
# it is the structural fix: a family cannot now be forgotten without failing a test.
_HISTORICAL_TICKET_FAMILIES = (
    "WR-01", "CR-02", "CX-03", "GAP-2", "FIX-5", "IN-08", "INFO-02", "NEW-1",
    "R2-1", "R3-3", "BLOCKER-2", "REVIEW-2", "CHANGE-5", "OPS2-01", "OPS-01",
    "HIGH-1", "MEDIUM-7", "LOW-6", "WARNING-1",
)

# The LIVE requirement families (the current REQUIREMENTS.md). These are traceability, not
# rot: they point at a document that still exists, so they MUST survive the sweep. The gate
# firing on any of these would fail CI on the very thing it is meant to protect.
_LIVE_REQUIREMENT_FAMILIES = (
    "BOUND-01", "FOUND-04", "COMM-01", "POLISH-02", "STRUCT-03", "TYPE-01", "CI-02",
)


def test_every_historical_ticket_family_is_covered() -> None:
    """The pattern table must cover every ticket family this project has ever used.

    Three review rounds each found a family the table had missed, because the table was
    grown by anecdote — someone noticed a shape and added it. This asserts it against the
    real inventory instead, so the failure mode ("we forgot a family") is now a red test
    rather than a silent hole a reviewer has to stumble on.
    """
    uncovered = [
        family
        for family in _HISTORICAL_TICKET_FAMILIES
        if not any(re.search(pattern, f"# {family}: a note") for _, pattern, _ in BLOCKED_PATTERNS)
    ]
    assert not uncovered, (
        "these ticket families are real (they appear in this project's commit history) but "
        f"no pattern in BLOCKED_PATTERNS matches them, so the guard is blind to them: {uncovered}"
    )


def test_live_requirement_ids_are_never_flagged() -> None:
    """The guard must not fire on the requirement IDs it is supposed to preserve.

    This is the other half of the contract and the easier one to break while widening the
    table: `D-[0-9]` without a word boundary matches inside BOUND-01 and FOUND-04, and an
    `OPS[0-9]*` pattern that is too greedy would eat a live OPS requirement. A guard that
    fails CI on legitimate traceability is worse than no guard, because the fix is to delete
    the traceability.
    """
    false_positives = [
        req
        for req in _LIVE_REQUIREMENT_FAMILIES
        if any(re.search(pattern, f"# {req}: a note") for _, pattern, _ in BLOCKED_PATTERNS)
    ]
    assert not false_positives, (
        "these are LIVE requirement IDs that must survive the sweep, but the guard flags "
        f"them as provenance rot: {false_positives}"
    )


def test_editorial_only_shapes_are_not_guard_enforced(tmp_path: pathlib.Path) -> None:
    """Prove every documented exclusion actually behaves as documented.

    `EDITORIAL_ONLY_PATTERNS` is the record of what the gate deliberately does NOT
    enforce. This walks it and proves each excluded shape scans clean -- so the narrowing
    is a checkable property of the code instead of an assertion in a summary. Each
    example is first checked to genuinely BE an instance of the shape it claims, so a
    mismatched example cannot make an entry vacuously pass.
    """
    assert EDITORIAL_ONLY_PATTERNS, (
        "the exclusion table must exist even when empty -- an empty tuple with a comment "
        "saying nothing was excluded is the honest form of 'nothing was excluded'"
    )

    for name, shape, example, reason in EDITORIAL_ONLY_PATTERNS:
        assert reason.strip(), f"exclusion {name!r} carries no reason"
        assert re.search(shape, example), (
            f"exclusion {name!r} has an example that is not an instance of its own shape: "
            f"{example!r} does not match {shape!r}"
        )
        probe = tmp_path / f"excluded_{name}.py"
        probe.write_text(example + "\n", encoding="utf-8")
        hits = scan_files_for_ticket_provenance([probe])
        assert not hits, (
            f"{name!r} is documented as editorial-only but the gate enforces it:\n"
            + "\n".join(hits)
        )
