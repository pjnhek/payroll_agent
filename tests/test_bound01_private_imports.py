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
   app.db.repo import runs as repo_runs` — the codebase's dominant idiom). The
   receiver may be a bare bound name OR a dotted attribute chain rooted at one:
   `import app.db.repo.runs` binds only the root name `app`, so
   `app.db.repo.runs._scrub` reaches the scanner as a NESTED `ast.Attribute`
   chain that must be walked back to its root `ast.Name` and reconstructed into
   the full dotted module path. EXCEPT when the bound target is itself a package
   `__init__.py` (the declared facade-boundary exemption: a package deliberately
   re-exporting a private name via its own `__init__.py` is the facade pattern
   working as designed, not a violation of it).

Both receiver shapes and both binding forms are covered deliberately: each one
this scanner fails to resolve is a silent hole, and a guard with a hole reads
green while the coupling it exists to prevent goes on spreading.

`tests/` is intentionally NOT scanned: tests routinely reach into a module's own
internals for unit-testing purposes, which is same-module by construction and
outside this guard's cross-module scope.

Both the scanner's helper functions and its two pytest entry points live in this
one file. `test_no_cross_module_private_imports` runs the scanner against the LIVE
repository tree (the permanent CI gate); `test_scanner_detects_synthetic_violation`
proves the scanner's own detection logic against a constructed tmp_path fixture
covering every violation shape and every legitimate-pattern exemption — without it,
a scanner that detects nothing at all would still pass the live gate.
"""

from __future__ import annotations

import ast
import pathlib

SCAN_ROOTS = ["app", "eval", "scripts"]

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# `app/db/repo/` is a package whose internal plumbing module (`_shared.py`, holding
# `_conn_ctx`/`_nulltx`) is DELIBERATELY imported directly by its sibling aggregate
# modules, and whose own `__init__.py` facade DELIBERATELY re-exports a full live
# attribute surface INCLUDING private names (`_conn_ctx`, `_scrub`,
# `_TERMINAL_STATUSES`, `_ACCENT_CLASS_MAP`, `_pad_references`,
# `_HEADER_MATCH_PREDICATE`, `_nulltx`) so that `monkeypatch.setattr(repo, "_scrub",
# ...)`-style test seams keep working against the facade.
#
# This is the ONE declared exception to BOUND-01's cross-module-private-import rule,
# and it is narrowly scoped to this single package — NOT a general "same top-level
# package is fine" carve-out. `app.routes.runs` importing `app.routes.templating`'s
# private badge filters is a genuine violation this guard correctly flags, even though
# it is also "same package".
_DECLARED_INTERNAL_PLUMBING_PACKAGE = "app.db.repo"


def _in_declared_plumbing_package(own_module: str, target_module: str) -> bool:
    """True when BOTH the importing file and the import target live inside the one
    package (`app.db.repo`) whose internal-plumbing/facade-re-export pattern is
    declared legitimate design rather than an accidental BOUND-01 violation.
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
    reference. This guard exists to catch RUNTIME private-name coupling that
    could silently break a monkeypatch seam, which code that never runs cannot
    do, so these nodes are exempted from the ImportFrom scan.
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
    __init__.py`. Passing the scan roots themselves would probe the never-existing
    `<root>/app/...`, silently returning False for every package and turning the
    facade exemption into dead code that false-positives the blessed
    `import app.db.repo as repo_mod` pattern.
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


def _receiver_dotted_path(node: ast.expr) -> str | None:
    """Walk an attribute receiver back to its root `ast.Name` and return the
    full dotted path (`app.db.repo.runs` for the receiver of
    `app.db.repo.runs._scrub`), or None when any link in the chain is not a
    plain Name/Attribute (calls, subscripts, literals — not module paths).

    This walk is what makes the unaliased-dotted-import shape visible.
    `import app.pipeline.orchestrator` binds only the ROOT name `app`, so
    `app.pipeline.orchestrator._x` reaches the scanner as a NESTED `ast.Attribute`
    chain. A receiver check that only handled a bare `ast.Name` would never resolve
    it, letting this completely standard import form bypass the gate entirely.
    """
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _scan_attribute_violations(
    tree: ast.AST,
    py_file: pathlib.Path,
    own_module: str,
    own_is_package: bool,
    root_parents: list[pathlib.Path],
) -> list[str]:
    """Flag `module._private` where `module` is a name bound to a first-party
    module under one of SCAN_ROOTS that is NOT itself a package (`__init__.py`).

    Package imports are the declared facade-boundary exemption, and the
    `app.db.repo`-internal plumbing accesses are the other declared exemption.
    """
    violations: list[str] = []
    type_checking_nodes = _type_checking_only_nodes(tree)

    # Map local bound name -> bound dotted module, walking the WHOLE tree
    # (module level and function bodies alike), for BOTH module-binding forms:
    #   * `ast.Import` — `import X` / `import X as Y`;
    #   * `ast.ImportFrom` — `from P import M [as Y]` where `P.M` resolves to a
    #     first-party module file or package. This is the codebase's DOMINANT
    #     module-binding idiom — every production module does `from app.db import
    #     repo` — so a scanner that only handled `ast.Import` would let an entire
    #     class of `bound_module._private` accesses escape the gate.
    # Relative forms resolve against the importing file's own module name;
    # TYPE_CHECKING-guarded imports never run at runtime and are skipped, mirroring
    # the ImportFrom scan's exemption.
    bound_modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bound_modules[alias.asname] = alias.name
                else:
                    # Python semantics: `import a.b.c` binds the local name `a` to the
                    # ROOT package `a`; `a.b.c` is only reachable as an attribute CHAIN
                    # through that root. Mapping the root name straight to the full
                    # dotted target would both misattribute a bare `a._x` access to
                    # `a.b.c` and leave the dotted `a.b.c._x` receiver unresolvable.
                    # Bind root to root; the dotted receiver walk below reconstructs
                    # the full module path.
                    root = alias.name.split(".")[0]
                    bound_modules[root] = root
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
        # The receiver may be a bare bound name (`runs._scrub`) or a dotted chain
        # rooted at one (`app.db.repo.runs._scrub` after a plain
        # `import app.db.repo.runs`). Walk the chain to its root `ast.Name`,
        # substitute the root's binding, and resolve the full dotted path the
        # same way aliased/ImportFrom bindings are resolved.
        receiver = _receiver_dotted_path(node.value)
        if receiver is None:
            continue
        root_name, _, rest = receiver.partition(".")
        bound_target = bound_modules.get(root_name)
        if bound_target is None:
            continue
        target_module = f"{bound_target}.{rest}" if rest else bound_target
        if rest and not _is_first_party_module(target_module, root_parents):
            # A dotted chain that does NOT land on a first-party module file/
            # package is an ordinary object-attribute walk (`mod.SomeClass._x`,
            # `pathlib.Path._flavour`), not a cross-module private access.
            continue
        if target_module == own_module:
            continue
        # Declared exemption: `app.db.repo`-internal files reaching sibling plumbing
        # (e.g. a submodule binding `_shared` and calling `_shared._conn_ctx`) is the
        # package's documented internal design, mirroring the same exemption in the
        # ImportFrom scan.
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
            # The attribute scan's package-exemption probe resolves dotted module
            # names against root PARENTS, so `root_parent` is what must be passed
            # here — passing `scan_roots` would probe `<root>/app/...`, which never
            # exists, making the facade exemption dead code.
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
    """Prove the scanner's own detection logic against synthetic fixtures.

    The live gate above passes when the scanner finds nothing — including when the
    scanner finds nothing because it is broken. This test is what makes that
    distinguishable, so it must cover every violation shape (absolute ImportFrom,
    relative ImportFrom crossing a real package boundary, and attribute access via
    `ast.Import`-bound, `ast.ImportFrom`-bound, and unaliased-dotted-import-bound
    modules — the nested-`ast.Attribute` receiver chain) AND every legitimate-pattern
    exemption (same-module reference, bare relative module import, a level-1 relative
    import inside a package's own `__init__.py`, and the facade-boundary exemption for
    a private attribute reached through an imported PACKAGE, in aliased, ImportFrom,
    and dotted-chain receiver forms alike).
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

    # module_e.py: the facade-boundary exemption branch. `import pkgroot as
    # pkg_facade` binds the PACKAGE (its `__init__.py` IS the declared facade), so
    # `pkg_facade._private_thing` is exempt — in contrast to module_b's
    # `import pkgroot.module_a as mod_a`, a plain SUBMODULE import whose private
    # access IS flagged. This pins the exemption the live gate blesses for
    # `import app.db.repo as repo_mod`: with no fixture exercising it, the exemption
    # branch could probe the wrong path root and be dead code without anything failing.
    (pkgroot / "module_e.py").write_text(
        "import pkgroot as pkg_facade\n"
        "\n"
        "\n"
        "def use_facade_reexported_private():\n"
        "    return pkg_facade._private_thing\n",
        encoding="utf-8",
    )

    # module_f.py: the `ast.ImportFrom` module-binding forms. `from pkgroot import
    # module_a as bound_mod` binds a plain SUBMODULE object, so
    # `bound_mod._private_thing` MUST be flagged — this is the shape that would let
    # every `from app.db import repo` binding escape the gate. `from pkgroot import
    # sub` binds a PACKAGE, so `sub._sub_private` hits the facade-boundary exemption,
    # proving the exemption also applies to ImportFrom-resolved targets.
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

    # module_g.py: the unaliased dotted-import shape. `import pkgroot.module_a` binds
    # only the root name `pkgroot`, so `pkgroot.module_a._private_thing` arrives as a
    # nested `ast.Attribute` chain that a bare-`ast.Name` receiver check would never
    # resolve — it MUST be flagged. `pkgroot.sub` resolves to a PACKAGE
    # (`sub/__init__.py`), so `pkgroot.sub._sub_private` hits the facade-boundary
    # exemption, proving the exemption also applies to dotted-chain receivers (the
    # `import app.db.repo` + `app.db.repo._conn_ctx` pattern the live facade blesses).
    (pkgroot / "module_g.py").write_text(
        "import pkgroot.module_a\n"
        "import pkgroot.sub\n"
        "\n"
        "\n"
        "def use_private_via_unaliased_dotted_import():\n"
        "    return pkgroot.module_a._private_thing\n"
        "\n"
        "\n"
        "def use_private_via_unaliased_dotted_package_import():\n"
        "    return pkgroot.sub._sub_private\n",
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
    module_g_file = str(pkgroot / "module_g.py")
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
    # attribute is private. The exemption branch must actually fire, not merely exist.
    assert not any(
        v.startswith(module_e_file) for v in violations
    ), f"module_e.py (facade package import) should be exempt, got:\n{violation_text}"

    # module_f.py: exactly ONE violation — the ImportFrom-bound SUBMODULE's private
    # access is flagged, while the ImportFrom-bound PACKAGE's private access is
    # facade-exempt.
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

    # module_g.py: exactly ONE violation — the unaliased dotted import's private
    # access is flagged (the nested `ast.Attribute` receiver chain), while the
    # dotted-chain access landing on a PACKAGE is facade-exempt.
    assert any(
        v.startswith(module_g_file)
        and "_private_thing" in v
        and "accesses" in v
        and "pkgroot.module_a" in v
        for v in violations
    ), f"expected module_g.py unaliased-dotted-import violation, got:\n{violation_text}"
    assert not any(
        v.startswith(module_g_file) and "_sub_private" in v for v in violations
    ), f"module_g.py's dotted-chain PACKAGE access should be exempt, got:\n{violation_text}"

    # Exactly the five expected violations total (2 from module_b.py, 1 from
    # module_d.py, 1 from module_f.py, 1 from module_g.py; module_e.py's
    # facade access, module_f.py's package-bound access, and module_g.py's
    # dotted-chain package access are exempt) -- confirms no unexpected
    # false positives elsewhere in the synthetic tree.
    assert len(violations) == 5, f"expected exactly 5 violations, got:\n{violation_text}"
