"""BOUND-01 regression guard: no cross-module private-name coupling.

An AST-walking static scanner over `app/`, `eval/`, `scripts/` that flags any
cross-module reference to a private name (leading underscore, not dunder), in
either of two forms:

1. `ast.ImportFrom` — `from module import _name`, whether at module level or
   inside a function body, whether absolute (`node.level == 0`) or relative
   (`node.level > 0`, resolved against the importing file's own module name
   and its `is_package` status).
2. `ast.Attribute` access — `module._name` where `module` is a name bound to a
   first-party module object, by EITHER binding form: `ast.Import` (`import X`
   / `import X as Y`) or `ast.ImportFrom` whose imported name resolves to a
   first-party module file/package (`from app.db import repo`, `from
   app.db.repo import runs as repo_runs` — the codebase's dominant idiom,
   WR-02). EXCEPT when the bound target is itself a package `__init__.py`
   (the declared facade-boundary exemption: a package deliberately re-exporting
   a private name via its own `__init__.py` is the facade pattern working as
   designed, not a violation of it).

`tests/` is intentionally NOT scanned (D-14): tests routinely reach into a
module's own internals for unit-testing purposes, which is same-module by
construction and outside this guard's cross-module scope.

Both the scanner's helper functions and its two pytest entry points live in
this one file: `test_no_cross_module_private_imports` runs the scanner against
the LIVE repository tree (the permanent CI gate); `test_scanner_detects_synthetic_violation`
proves the scanner's own detection logic against a constructed tmp_path fixture
covering every violation shape and every legitimate-pattern exemption (the
permanent replacement for a one-time manual scratch-file check).
"""

from __future__ import annotations

import ast
import pathlib

SCAN_ROOTS = ["app", "eval", "scripts"]

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# D-01/D-03 (13-01-SUMMARY.md): `app/db/repo/` is a package whose internal
# plumbing module (`_shared.py`, holding `_conn_ctx`/`_nulltx`) is DELIBERATELY
# imported directly by its sibling aggregate modules ("submodules import
# siblings directly" — D-03), and whose own `__init__.py` facade DELIBERATELY
# re-exports a full live attribute surface INCLUDING private names
# (`_conn_ctx`, `_scrub`, `_TERMINAL_STATUSES`, `_ACCENT_CLASS_MAP`,
# `_pad_references`, `_HEADER_MATCH_PREDICATE`, `_nulltx`) so that
# `monkeypatch.setattr(repo, "_scrub", ...)`-style seams keep working
# unchanged post-split (D-01). This is the ONE declared, documented exception
# to BOUND-01's cross-module-private-import rule — narrowly scoped to this one
# package, not a general "same top-level package is fine" carve-out (compare
# `app.routes.runs` importing `app.routes.templating`'s private badge filters,
# which IS a genuine violation this guard correctly flags despite also being
# "same package").
_DECLARED_INTERNAL_PLUMBING_PACKAGE = "app.db.repo"


def _in_declared_plumbing_package(own_module: str, target_module: str) -> bool:
    """True when BOTH the importing file and the import target live inside the
    one package (`app.db.repo`) whose internal-plumbing/facade-re-export
    pattern is explicitly declared legitimate design (D-01/D-03), not an
    accidental BOUND-01 violation.
    """
    prefix = _DECLARED_INTERNAL_PLUMBING_PACKAGE
    same_package = (own_module == prefix or own_module.startswith(prefix + ".")) and (
        target_module == prefix or target_module.startswith(prefix + ".")
    )
    return same_package


def _is_private(name: str) -> bool:
    """True for a leading-underscore name that is NOT a dunder (e.g. `__init__`)."""
    return name.startswith("_") and not name.startswith("__")


def _module_name_and_is_package(
    py_file: pathlib.Path, root_parent: pathlib.Path
) -> tuple[str, bool]:
    """Compute a file's own dotted module name and whether it IS a package `__init__.py`.

    Module name is relative to `root_parent` (the scan root's PARENT directory),
    with `__init__.py` normalized away: `app/routes/__init__.py` -> `app.routes`,
    NOT `app.routes.__init__`. `is_package` is True exactly when the file IS an
    `__init__.py`.
    """
    rel = py_file.relative_to(root_parent)
    parts = list(rel.with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def _resolve_import_from_target(
    node: ast.ImportFrom, own_module: str, own_is_package: bool
) -> str | None:
    """Resolve an `ast.ImportFrom` node to a single target-module dotted string.

    Absolute (`node.level == 0`): the target is `node.module` directly.

    Relative (`node.level > 0`): resolve by walking UP from the IMPORTING
    FILE's own module name `node.level` times, honoring `is_package` — a
    package's `__init__.py` module name already points AT the package, so a
    `level=1` relative import inside it resolves relative to that SAME name,
    not one level further up (dropping the `__init__` segment during module-name
    computation already accounted for one level of nesting).
    """
    if node.level == 0:
        return node.module

    own_parts = own_module.split(".") if own_module else []
    # own_is_package: own_module already points AT the package; level=1 resolves
    # relative to it directly, level=2 walks up one more, etc. Otherwise,
    # own_module points at a submodule inside its package; level=1 resolves
    # relative to its immediate parent package.
    trim = node.level - 1 if own_is_package else node.level
    base_parts = own_parts[: len(own_parts) - trim] if trim <= len(own_parts) else []
    base = ".".join(base_parts)
    if node.module:
        return f"{base}.{node.module}" if base else node.module
    return base or None


def _type_checking_only_nodes(tree: ast.AST) -> set[ast.AST]:
    """Return every node that lives inside an `if TYPE_CHECKING:` block's body.

    A `TYPE_CHECKING`-guarded import is never executed at runtime — it exists
    solely so a static type checker can resolve an annotation string/forward
    reference. This guard's purpose (T-13-13: catch a runtime private-name
    coupling that could silently break a monkeypatch seam) does not apply to
    code that never runs, so these nodes are exempted from the ImportFrom scan.
    """
    guarded: set[ast.AST] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_type_checking_test = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )
        if not is_type_checking_test:
            continue
        for child in node.body:
            for sub in ast.walk(child):
                guarded.add(sub)
    return guarded


def _scan_import_from_violations(
    tree: ast.AST, py_file: pathlib.Path, own_module: str, own_is_package: bool
) -> list[str]:
    violations: list[str] = []
    type_checking_nodes = _type_checking_only_nodes(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node in type_checking_nodes:
            continue
        target_module = _resolve_import_from_target(node, own_module, own_is_package)
        if target_module is None or target_module == own_module:
            continue
        if _in_declared_plumbing_package(own_module, target_module):
            continue
        for alias in node.names:
            if _is_private(alias.name):
                violations.append(
                    f"{py_file}:{node.lineno} imports private '{alias.name}' "
                    f"via '{target_module}'"
                )
    return violations


def _is_package_import_target(module_dotted: str, root_parents: list[pathlib.Path]) -> bool:
    """True if `module_dotted` resolves to a package (has its own `__init__.py`).

    `root_parents` entries are each the PARENT directory of a scan root (the
    directory a dotted module name is relative to), NOT the scan roots
    themselves — for `app.db.repo` the probe is `<root_parent>/app/db/repo/
    __init__.py`. Passing the scan roots here (WR-01, Phase 13 review) probed
    the never-existing `<root>/app/...` and made the facade exemption dead code.
    """
    rel_path = pathlib.Path(*module_dotted.split("."))
    for root_parent in root_parents:
        candidate = root_parent / rel_path / "__init__.py"
        if candidate.is_file():
            return True
    return False


def _is_first_party_module(module_dotted: str, root_parents: list[pathlib.Path]) -> bool:
    """True if `module_dotted` resolves to a first-party MODULE under one of
    `root_parents` — either a plain `.py` file or a package directory with its
    own `__init__.py`. Used to distinguish an `ast.ImportFrom` alias that binds
    a module object (`from app.db import repo`) from one that binds an ordinary
    name (`from app.db.repo import get_connection`)."""
    rel_path = pathlib.Path(*module_dotted.split("."))
    for root_parent in root_parents:
        if (root_parent / rel_path).with_suffix(".py").is_file():
            return True
        if (root_parent / rel_path / "__init__.py").is_file():
            return True
    return False


def _scan_attribute_violations(
    tree: ast.AST,
    py_file: pathlib.Path,
    own_module: str,
    own_is_package: bool,
    root_parents: list[pathlib.Path],
) -> list[str]:
    """Flag `module._private` where `module` is a name bound to a first-party
    module under one of SCAN_ROOTS that is NOT itself a package (`__init__.py`)
    — package imports are the declared facade-boundary exemption, and the
    `app.db.repo`-internal plumbing accesses are the declared D-01/D-03 one.
    """
    violations: list[str] = []
    type_checking_nodes = _type_checking_only_nodes(tree)

    # Map local bound name -> bound dotted module, walking the WHOLE tree
    # (module level and function bodies alike), for BOTH module-binding forms:
    #   * `ast.Import` — `import X` / `import X as Y`;
    #   * `ast.ImportFrom` — `from P import M [as Y]` where `P.M` resolves to a
    #     first-party module file or package (WR-02, Phase 13 review: this is
    #     the codebase's DOMINANT module-binding idiom — every production module
    #     does `from app.db import repo` — and was previously invisible here,
    #     letting a whole class of `bound_module._private` accesses escape the
    #     gate). Relative forms resolve against the importing file's own module
    #     name; TYPE_CHECKING-guarded imports never run at runtime and are
    #     skipped, mirroring the ImportFrom scan's exemption.
    bound_modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                bound_modules[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node not in type_checking_nodes:
            base = _resolve_import_from_target(node, own_module, own_is_package)
            if base is None:
                continue
            for alias in node.names:
                dotted = f"{base}.{alias.name}"
                if _is_first_party_module(dotted, root_parents):
                    bound_modules[alias.asname or alias.name] = dotted

    if not bound_modules:
        return violations

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not _is_private(node.attr):
            continue
        if not isinstance(node.value, ast.Name):
            continue
        local_name = node.value.id
        target_module = bound_modules.get(local_name)
        if target_module is None:
            continue
        if target_module == own_module:
            continue
        # D-01/D-03 declared exemption: `app.db.repo`-internal files reaching
        # sibling plumbing (e.g. a submodule binding `_shared` and calling
        # `_shared._conn_ctx`) is the package's documented internal design,
        # mirroring the same exemption in the ImportFrom scan.
        if _in_declared_plumbing_package(own_module, target_module):
            continue
        # Facade-boundary exemption: importing a PACKAGE (its __init__.py IS the
        # declared facade) is out of scope; importing a SUBMODULE is not exempt.
        if _is_package_import_target(target_module, root_parents):
            continue
        violations.append(
            f"{py_file}:{node.lineno} accesses private '{node.attr}' via '{target_module}'"
        )
    return violations


def scan_tree_for_violations(
    scan_roots: list[pathlib.Path], root_parent: pathlib.Path
) -> list[str]:
    """Walk every `.py` file under `scan_roots` and return all BOUND-01 violations
    (both ImportFrom and attribute-access forms), as human-readable strings.
    """
    violations: list[str] = []
    for root in scan_roots:
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob("*.py")):
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
            own_module, own_is_package = _module_name_and_is_package(py_file, root_parent)
            violations.extend(
                _scan_import_from_violations(tree, py_file, own_module, own_is_package)
            )
            # WR-01 (Phase 13 review): the attribute scan's package-exemption
            # probe resolves dotted module names against root PARENTS — passing
            # `scan_roots` here probed `<root>/app/...` (never exists) and made
            # the facade exemption dead code, false-positiving the blessed
            # `import app.db.repo as repo_mod` pattern.
            violations.extend(
                _scan_attribute_violations(
                    tree, py_file, own_module, own_is_package, [root_parent]
                )
            )
    return violations


def test_no_cross_module_private_imports() -> None:
    """The permanent CI gate: scans the LIVE app/, eval/, scripts/ trees and
    asserts zero cross-module private-name references remain, in either the
    ImportFrom (absolute + resolved-relative) or attribute-access form.
    """
    scan_roots = [REPO_ROOT / name for name in SCAN_ROOTS]
    violations = scan_tree_for_violations(scan_roots, REPO_ROOT)
    assert not violations, "BOUND-01 violation(s) found:\n" + "\n".join(violations)


def test_scanner_detects_synthetic_violation(tmp_path: pathlib.Path) -> None:
    """Prove the scanner's own detection logic against synthetic fixtures BEFORE
    trusting it as a permanent gate — covers every violation shape (absolute
    ImportFrom, relative ImportFrom crossing a real package boundary,
    attribute-access via BOTH `ast.Import`- and `ast.ImportFrom`-bound
    modules) and every legitimate-pattern exemption (same-module
    reference, bare relative module import, a level-1 relative import inside a
    package's own `__init__.py`, and the facade-boundary exemption for a
    private attribute reached through an imported PACKAGE).
    """
    pkgroot = tmp_path / "pkgroot"
    pkgroot.mkdir()

    (pkgroot / "module_a.py").write_text("_private_thing = 1\n", encoding="utf-8")

    (pkgroot / "module_b.py").write_text(
        "def use_private_via_function_body():\n"
        "    from pkgroot.module_a import _private_thing\n"
        "    return _private_thing\n"
        "\n"
        "\n"
        "import pkgroot.module_a as mod_a\n"
        "\n"
        "\n"
        "def use_private_via_attribute_access():\n"
        "    return mod_a._private_thing\n",
        encoding="utf-8",
    )

    (pkgroot / "module_c.py").write_text(
        "_local_helper = 1\n"
        "\n"
        "\n"
        "def use_same_module():\n"
        "    return _local_helper\n"
        "\n"
        "\n"
        "from . import module_a\n"
        "\n"
        "\n"
        "def use_bare_relative_module_import():\n"
        "    return module_a\n",
        encoding="utf-8",
    )

    sub = pkgroot / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text("", encoding="utf-8")
    (sub / "module_d.py").write_text(
        "def reach_into_parent_package():\n"
        "    from ..module_a import _private_thing\n"
        "    return _private_thing\n",
        encoding="utf-8",
    )

    (pkgroot / "__init__.py").write_text("from . import module_a\n", encoding="utf-8")

    # module_e.py: the facade-boundary exemption branch (WR-01, Phase 13
    # review). `import pkgroot as pkg_facade` binds the PACKAGE (its
    # `__init__.py` IS the declared facade), so `pkg_facade._private_thing`
    # is exempt — in contrast to module_b's `import pkgroot.module_a as
    # mod_a`, a plain SUBMODULE import whose private access IS flagged. This
    # pins the exemption the live gate blesses for `import app.db.repo as
    # repo_mod`, which shipped dead (probed the wrong path root) precisely
    # because no fixture exercised it.
    (pkgroot / "module_e.py").write_text(
        "import pkgroot as pkg_facade\n"
        "\n"
        "\n"
        "def use_facade_reexported_private():\n"
        "    return pkg_facade._private_thing\n",
        encoding="utf-8",
    )

    # module_f.py: the `ast.ImportFrom` module-binding forms (WR-02, Phase 13
    # review — previously a scanner blind spot). `from pkgroot import module_a
    # as bound_mod` binds a plain SUBMODULE object, so `bound_mod
    # ._private_thing` MUST be flagged (this is the shape that let
    # `from app.db import repo` bindings escape the gate entirely). `from
    # pkgroot import sub` binds a PACKAGE, so `sub._sub_private` hits the
    # facade-boundary exemption — proving the (WR-01-fixed) exemption also
    # applies to ImportFrom-resolved targets.
    (pkgroot / "module_f.py").write_text(
        "from pkgroot import module_a as bound_mod\n"
        "from pkgroot import sub\n"
        "\n"
        "\n"
        "def use_private_via_importfrom_bound_module():\n"
        "    return bound_mod._private_thing\n"
        "\n"
        "\n"
        "def use_private_via_importfrom_bound_package():\n"
        "    return sub._sub_private\n",
        encoding="utf-8",
    )

    scan_roots = [tmp_path / "pkgroot"]
    violations = scan_tree_for_violations(scan_roots, tmp_path)

    violation_text = "\n".join(violations)

    module_b_file = str(pkgroot / "module_b.py")
    module_d_file = str(sub / "module_d.py")
    module_c_file = str(pkgroot / "module_c.py")
    module_e_file = str(pkgroot / "module_e.py")
    module_f_file = str(pkgroot / "module_f.py")
    init_file = str(pkgroot / "__init__.py")

    # module_b.py: BOTH violations must be detected (function-body absolute
    # ImportFrom + module-attribute-access).
    assert any(
        v.startswith(module_b_file) and "_private_thing" in v and "imports" in v
        for v in violations
    ), f"expected module_b.py ImportFrom violation, got:\n{violation_text}"
    assert any(
        v.startswith(module_b_file) and "_private_thing" in v and "accesses" in v
        for v in violations
    ), f"expected module_b.py attribute-access violation, got:\n{violation_text}"

    # module_d.py: the level-2 relative import crossing OUT of `sub` back into
    # `pkgroot` to reach a private name MUST be detected.
    assert any(
        v.startswith(module_d_file) and "_private_thing" in v for v in violations
    ), f"expected module_d.py relative-import violation, got:\n{violation_text}"

    # module_c.py: zero violations (same-module reference + bare relative
    # module import, neither of which references a private symbol FROM another
    # module).
    assert not any(
        v.startswith(module_c_file) for v in violations
    ), f"module_c.py should have zero violations, got:\n{violation_text}"

    # pkgroot/__init__.py: zero violations (level-1 relative import of a
    # sibling module, resolved correctly relative to `pkgroot` itself, not one
    # level further up to tmp_path, proving the is_package handling).
    assert not any(
        v.startswith(init_file) for v in violations
    ), f"pkgroot/__init__.py should have zero violations, got:\n{violation_text}"

    # module_e.py: zero violations — the PACKAGE import (`import pkgroot as
    # pkg_facade`) hits the facade-boundary exemption even though the accessed
    # attribute is private (WR-01: the exemption branch must actually fire).
    assert not any(
        v.startswith(module_e_file) for v in violations
    ), f"module_e.py (facade package import) should be exempt, got:\n{violation_text}"

    # module_f.py: exactly ONE violation — the ImportFrom-bound SUBMODULE's
    # private access is flagged (WR-02: the previously-invisible binding form),
    # while the ImportFrom-bound PACKAGE's private access is facade-exempt.
    assert any(
        v.startswith(module_f_file)
        and "_private_thing" in v
        and "accesses" in v
        and "pkgroot.module_a" in v
        for v in violations
    ), f"expected module_f.py ImportFrom-bound-module violation, got:\n{violation_text}"
    assert not any(
        v.startswith(module_f_file) and "_sub_private" in v for v in violations
    ), f"module_f.py's ImportFrom-bound PACKAGE access should be exempt, got:\n{violation_text}"

    # Exactly the four expected violations total (2 from module_b.py, 1 from
    # module_d.py, 1 from module_f.py; module_e.py's facade access and
    # module_f.py's package-bound access are exempt) -- confirms no unexpected
    # false positives elsewhere in the synthetic tree.
    assert len(violations) == 4, f"expected exactly 4 violations, got:\n{violation_text}"
