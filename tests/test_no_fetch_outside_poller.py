"""GUARD-06's second, independent enforcement path -- the hermetic half.

What this guard establishes: no file under frontend/src, other than the single
sanctioned poller hook (frontend/src/hooks/usePoller.ts), references the browser
fetch API, the legacy XMLHttpRequest object, or the axios package. It walks every
.ts/.tsx file under frontend/src (excluding the allowlisted path and any dependency
directory) and text-scans its contents for those three tokens.

This runs in the existing hermetic pytest test job -- no Node required -- so
disabling, renaming, or misconfiguring the frontend CI job does not silently remove
the ban; the ban still fails a pull request from the Python side. The primary
enforcement layer is the ESLint no-restricted-globals/no-restricted-imports rules in
frontend/eslint.config.js, scoped to the same allowlisted path; this module is the
belt to that suspenders, not a replacement for it.

What this guard does NOT establish: it is a plain text scan over file contents, not a
real TypeScript parse -- Python's ast module cannot parse .ts/.tsx source at all, so
there is no AST-based alternative available the way there is for the Python-side
guards in this repository. A determined string-concatenation obfuscation (for example
window["fe" + "tch"]) would defeat a substring scan; that gap is accepted because
ESLint (which DOES parse the real TypeScript AST) is the primary enforcement layer,
and this module's job is redundancy against a disabled or misconfigured CI job, not a
standalone proof on its own.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# The one file this project has reviewed and sanctioned as a real network call site.
ALLOWED_POLLER_PATH = (FRONTEND_SRC / "hooks" / "usePoller.ts").resolve()

# Exact token list, matched by plain substring -- taken from this phase's own research
# note rather than invented fresh, so the hermetic half and the ESLint half agree on
# what they are banning.
BANNED_TOKENS: tuple[str, ...] = ("fetch(", "axios", "XMLHttpRequest")

# Directories that never carry hand-written source, even if they happen to exist
# somewhere under the scanned root (defensive -- frontend/src has no such directory
# today, but a build tool or a future dependency layout change should not need this
# guard's own logic to change).
_EXCLUDED_DIR_NAMES = frozenset({"node_modules", "dist"})


def scan_for_banned_tokens(
    root: pathlib.Path, allowed: frozenset[pathlib.Path]
) -> tuple[list[pathlib.Path], list[str]]:
    """Walk every .ts/.tsx file under `root`, skipping `allowed` paths and any
    dependency directory. Returns (every file visited, offending files relative to
    `root`) -- the visited list is what `test_scan_visited_a_non_zero_number_of_files`
    guards against a walk that silently matches nothing.
    """
    visited: list[pathlib.Path] = []
    offenders: list[str] = []
    for path in sorted(root.rglob("*.ts*")):
        if not path.is_file():
            continue
        if _EXCLUDED_DIR_NAMES & set(path.parts):
            continue
        visited.append(path)
        if path.resolve() in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in BANNED_TOKENS):
            offenders.append(str(path.relative_to(root)))
    return visited, offenders


# ---------------------------------------------------------------------------
# The guard itself, plus the two companion tests that close this repository's own
# recorded blind spot: a walk that silently matches nothing, or an allowlist entry
# that has gone stale, both pass their headline assertion vacuously.
# ---------------------------------------------------------------------------


def test_fetch_confined_to_poller_hook() -> None:
    _visited, offenders = scan_for_banned_tokens(
        FRONTEND_SRC, frozenset({ALLOWED_POLLER_PATH})
    )
    assert not offenders, (
        f"fetch/axios/XMLHttpRequest found outside usePoller.ts: {offenders}"
    )


def test_scan_visited_a_non_zero_number_of_files() -> None:
    """A walk that silently matches nothing would make the assertion above pass
    vacuously -- this repository has a recorded scar from exactly this shape of
    blind spot (a scoped search that matched nothing and stayed green for the wrong
    reason), so the walk's own reach is pinned here rather than trusted by
    inspection.
    """
    visited, _offenders = scan_for_banned_tokens(
        FRONTEND_SRC, frozenset({ALLOWED_POLLER_PATH})
    )
    assert visited, "the walk over frontend/src matched no .ts/.tsx files"


def test_allowlisted_poller_path_exists_on_disk() -> None:
    """A stale allowlist entry (for example after a rename) would mean the real call
    site goes unscanned while a renamed file with no fetch call sails through --
    pinning the allowlist path to a real file on disk closes that gap.
    """
    assert ALLOWED_POLLER_PATH.is_file(), (
        f"allowlisted poller path does not exist: {ALLOWED_POLLER_PATH}"
    )


def test_guard_reports_a_synthetic_offender_placed_in_a_temporary_directory(
    tmp_path: pathlib.Path,
) -> None:
    """The no-false-positive half: a pattern that never matches anything is exactly
    as useless as a walk that visits nothing. Places a genuine fetch() call in a
    throwaway tree (never touching frontend/src) and asserts the scanner reports it
    by name, so a future over-narrowing of BANNED_TOKENS or the walk itself is
    caught.
    """
    fake_src = tmp_path / "src"
    fake_src.mkdir()
    offending_file = fake_src / "Sneaky.tsx"
    offending_file.write_text(
        "export function Sneaky() {\n  return fetch('/x');\n}\n", encoding="utf-8"
    )

    visited, offenders = scan_for_banned_tokens(fake_src, frozenset())

    assert visited == [offending_file]
    assert offenders == ["Sneaky.tsx"]


def test_guard_reports_no_offender_for_a_clean_temporary_directory(
    tmp_path: pathlib.Path,
) -> None:
    """The negative control paired with the positive one above: a file that never
    references any banned token must not be reported, on the same scanning code
    path -- proving the previous test's positive result is a property of the fetch
    call, not of the temporary directory itself.
    """
    fake_src = tmp_path / "src"
    fake_src.mkdir()
    clean_file = fake_src / "Clean.tsx"
    clean_file.write_text(
        "export function Clean() {\n  return <div>hello</div>;\n}\n", encoding="utf-8"
    )

    visited, offenders = scan_for_banned_tokens(fake_src, frozenset())

    assert visited == [clean_file]
    assert offenders == []
