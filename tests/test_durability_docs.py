"""Rot guard for the published durability-evidence document.

`docs/DURABILITY-PROOFS.md` is a claim about the codebase, written in prose and
pasted transcripts rather than executable assertions. A claim like that decays
silently: a refactor moves the mutated line, a proof's registered assertion text
changes, or the README link rots, and nothing in the normal test suite would ever
notice — the document just quietly stops matching the code it describes. This
module is the cheap, hermetic backstop that would notice.

It binds the document to two machine-checkable sources of truth rather than
restating facts by hand: `scripts.check_proof_inventory.EXPECTED_PROOF_IDS` (the
canonical four proof ids) and `tests.test_proof_mutation_targets.MUTATION_TARGETS`
(the registry pinning each proof's real mutation target and its named failing
assertion, both already verified against live source by that module's own guard).
Importing both means this module and the registry it checks against cannot drift
apart from each other by hand-typo alone.

This module is deliberately outside the `proof` and `queueproof` marker
selections — it checks a document, not a durability property of the running
system, and tagging it would corrupt the exactly-once proof inventory the
completeness gate depends on.
"""

from __future__ import annotations

import pathlib
import re

from scripts.check_proof_inventory import EXPECTED_PROOF_IDS
from tests.test_proof_mutation_targets import MUTATION_TARGETS

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "DURABILITY-PROOFS.md"
README_PATH = REPO_ROOT / "README.md"

# The exact prerequisite marker every live-database command block must carry.
# Not a loose "DATABASE_URL" substring — that would also match a command that
# merely READS the variable name in prose without warning the reader it points
# at a throwaway database, which is the actual safety property this guards.
LIVE_DB_PREREQUISITE_MARKER = "DATABASE_URL=<throwaway-postgres-url>"

# A shell fenced code block is treated as "live-database" if it invokes the
# destructive, reset-guarded fixture path — the one signal every live-DB command
# in this document shares and no hermetic command carries.
_LIVE_DB_COMMAND_SIGNAL = "ALLOW_DB_RESET=1"

# Matches ANY fenced code block regardless of its language tag (```bash,
# ```diff, or a bare ```), pairing each opening fence to its own closing fence
# in document order. A pattern that only recognized ```bash/bare ``` openings
# would silently treat a ```diff block's closing fence as a new block's
# opening fence and pair it with the wrong closer — misaligning every block
# after the first ```diff in the document.
_FENCED_CODE_BLOCK = re.compile(r"```[\w-]*\n(.*?)\n```", re.DOTALL)

# A distinctive phrase from each of the three accepted limits the document
# states plainly alongside its claims, chosen so that deleting the residual's
# own sentence — not just some nearby text — reds this check.
_RESIDUAL_PHRASES = (
    "Two Generals problem",
    "auto-disables itself after sixty days",
    "operator retrigger can legitimately send a second email",
)


def _doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _readme_text() -> str:
    return README_PATH.read_text(encoding="utf-8")


class TestDocumentExistsWithAllSections:
    def test_document_exists(self) -> None:
        assert DOC_PATH.is_file(), f"expected {DOC_PATH} to exist"

    def test_document_contains_a_section_for_every_expected_proof_id(self) -> None:
        text = _doc_text()
        missing = [proof_id for proof_id in EXPECTED_PROOF_IDS if proof_id not in text]
        assert missing == [], f"document is missing sections for: {missing}"

    def test_document_contains_the_completeness_gate_section(self) -> None:
        text = _doc_text()
        assert "PROOF-05" in text
        assert "completeness gate" in text.lower()


class TestReadmeLinksTheDocument:
    def test_readme_contains_a_relative_link_that_resolves(self) -> None:
        text = _readme_text()
        match = re.search(r"\]\(([^)]*DURABILITY-PROOFS\.md)\)", text)
        assert match is not None, "README does not link docs/DURABILITY-PROOFS.md"
        link_target = match.group(1)
        assert not link_target.startswith(("http://", "https://")), (
            "the durability-proofs link must be relative, not an absolute URL"
        )
        resolved = (README_PATH.parent / link_target).resolve()
        assert resolved.is_file(), f"README link target does not exist: {resolved}"
        assert resolved == DOC_PATH.resolve()


class TestMutationTargetsAreDescribedInProse:
    def test_every_registry_entrys_file_and_function_are_mentioned(self) -> None:
        text = _doc_text()
        missing: list[str] = []
        for proof_id, entry in MUTATION_TARGETS.items():
            if entry.file not in text:
                missing.append(f"{proof_id}: file {entry.file!r} not mentioned")
            if entry.function_name not in text:
                missing.append(f"{proof_id}: function {entry.function_name!r} not mentioned")
        assert missing == [], missing

    def test_every_registry_entrys_named_assertion_text_is_published(self) -> None:
        """The rot guard for a corrected-but-not-republished assertion.

        If a future correction updates `MUTATION_TARGETS`' recorded assertion for
        some proof and the published prose keeps the old text, this document is
        publishing a falsification claim that no longer matches what the registry
        (itself verified against live source) says actually reddened. That is
        exactly the failure shape this document exists to prevent, one level up.
        """
        text = _doc_text()
        missing = [
            f"{proof_id}: {entry.assertion_text!r} not found in document"
            for proof_id, entry in MUTATION_TARGETS.items()
            if entry.assertion_text not in text
        ]
        assert missing == [], missing


class TestResidualsSectionIsPresent:
    def test_all_three_residual_phrases_are_present(self) -> None:
        text = _doc_text()
        missing = [phrase for phrase in _RESIDUAL_PHRASES if phrase not in text]
        assert missing == [], f"residuals section is missing: {missing}"

    def test_deleting_one_residual_phrase_reds(self) -> None:
        # Proves the check above is not vacuously true against an empty document —
        # each phrase is checked independently, so dropping exactly one reds.
        text = _doc_text()
        assert _RESIDUAL_PHRASES[0] in text
        without_first = text.replace(_RESIDUAL_PHRASES[0], "")
        missing = [phrase for phrase in _RESIDUAL_PHRASES if phrase not in without_first]
        assert missing == [_RESIDUAL_PHRASES[0]]


class TestNoPlanningPathLeaksIntoThePublishedDocument:
    def test_document_contains_no_planning_directory_reference(self) -> None:
        text = _doc_text()
        assert ".planning/" not in text


class TestLiveDatabaseCommandsCarryThePrerequisiteMarker:
    def test_every_live_db_code_block_carries_the_database_url_marker(self) -> None:
        text = _doc_text()
        blocks = _FENCED_CODE_BLOCK.findall(text)
        live_db_blocks = [block for block in blocks if _LIVE_DB_COMMAND_SIGNAL in block]
        assert live_db_blocks, (
            "expected at least one live-database command block "
            f"(containing {_LIVE_DB_COMMAND_SIGNAL!r}) in the document"
        )
        unmarked = [
            block for block in live_db_blocks if LIVE_DB_PREREQUISITE_MARKER not in block
        ]
        assert unmarked == [], (
            "found a live-database command block missing the "
            f"{LIVE_DB_PREREQUISITE_MARKER!r} prerequisite marker:\n" + "\n---\n".join(unmarked)
        )

    def test_hermetic_command_blocks_do_not_require_the_marker(self) -> None:
        # The completeness gate and the mutation-target registry are hermetic
        # (no DATABASE_URL needed at all) — confirms the check above is
        # discriminating on the live-DB signal, not flagging every code block.
        text = _doc_text()
        blocks = _FENCED_CODE_BLOCK.findall(text)
        hermetic_marker = "check_proof_inventory"
        hermetic_blocks = [
            block
            for block in blocks
            if hermetic_marker in block and _LIVE_DB_COMMAND_SIGNAL not in block
        ]
        assert hermetic_blocks, "expected at least one hermetic command block"
