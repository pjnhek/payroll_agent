"""Guards that guard the harness — no DB, no worker module.

Two classes of failure this file makes structurally impossible to
reintroduce silently:

1. A method defined on `tests/conftest.py`'s `InMemoryRepo` (or
   `tests/test_threading.py`'s `_MiniStore`) that shadows a real
   `app.db.repo` name, but is missing from the monkeypatch NAME TUPLE that
   wires it in. The `if hasattr(store, name)` guard at the patch site makes
   that miss SILENT — no AttributeError, no failed test — the real
   DB-backed function keeps running against a `FakeCursor`, and whatever it
   writes vanishes. This is a silent-corruption bug, not a test failure, and
   this repo has shipped it before.

2. A leaked `queue-worker-*` daemon thread surviving a test — the suite-wide
   autouse leak guard defined in `tests/conftest.py`, proven here.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import threading

import pytest

_RETIRED_RECOVERY_SYMBOLS = {
    "sweep_stranded_runs",
    "find_stranded_unconsumed_replies",
}
_DURABLE_RECOVERY_SYMBOLS = {
    "get_inbound_email_by_id",
    "create_operator_resume_resolution",
    "load_operator_resume_resolution",
    "enqueue_classified_retry",
    "enqueue_operator_resume_retry",
    "settle_pipeline_job",
    "settle_outbound_delivery_job",
    "settle_background_terminal",
    "settle_infrastructure_failure",
    "reap_expired_final_attempt",
}


def _assert_durable_recovery_pairs(repo_mod, store) -> None:
    assert _DURABLE_RECOVERY_SYMBOLS, "durable recovery inventory must not be empty"
    for name in sorted(_DURABLE_RECOVERY_SYMBOLS):
        facade_member = getattr(repo_mod, name, None)
        assert callable(facade_member), f"durable facade seam is missing: {name}"
        assert getattr(facade_member, "__self__", None) is store, (
            f"durable fake seam is not paired through fake_repo: {name}"
        )


def _defined_or_exported_names(source: str) -> set[str]:
    """Return concrete definitions, imports, assignments, and ``__all__`` names."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            names.update(
                item.value
                for item in ast.walk(node.value)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return names


def test_retired_recovery_symbols_are_absent_from_nonempty_production_sources() -> None:
    """The queue is the only automatic recovery policy left in production."""
    app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
    source_files = sorted(
        path
        for pattern in ("*.py", "*.html", "*.sql")
        for path in app_root.rglob(pattern)
        if "__pycache__" not in path.parts
    )
    assert source_files, "production source inventory must not be empty"

    raw_matches: dict[str, list[str]] = {}
    symbol_matches: dict[str, list[str]] = {}
    nonempty_sources = 0
    for path in source_files:
        source = path.read_text(encoding="utf-8")
        if not source.strip():
            continue
        nonempty_sources += 1
        retired_in_text = sorted(
            name for name in _RETIRED_RECOVERY_SYMBOLS if name in source
        )
        if retired_in_text:
            raw_matches[str(path.relative_to(app_root.parent))] = retired_in_text
        if path.suffix == ".py":
            retired_in_symbols = sorted(
                _RETIRED_RECOVERY_SYMBOLS.intersection(
                    _defined_or_exported_names(source)
                )
            )
            if retired_in_symbols:
                symbol_matches[str(path.relative_to(app_root.parent))] = (
                    retired_in_symbols
                )

    assert nonempty_sources, "production source inventory contains no content"
    assert not raw_matches, f"retired recovery text remains: {raw_matches}"
    assert not symbol_matches, (
        "retired recovery definitions/exports remain: " f"{symbol_matches}"
    )


def test_retired_recovery_inventory_detects_reintroduced_definition_and_export() -> None:
    """Prove the negative inventory reds on either public reintroduction shape."""
    synthetic = """
def sweep_stranded_runs():
    pass

__all__ = ["find_stranded_unconsumed_replies"]
"""
    assert _defined_or_exported_names(synthetic) >= _RETIRED_RECOVERY_SYMBOLS


def test_durable_recovery_facade_and_fake_surfaces_remain_paired(fake_repo) -> None:
    """Deletion cannot subtract the persisted-context or settlement replacements."""
    from app.db import repo as repo_mod

    _assert_durable_recovery_pairs(repo_mod, fake_repo)


def test_durable_recovery_pairing_guard_detects_one_unpaired_facade_method(
    fake_repo,
    monkeypatch,
) -> None:
    """The positive pairing inventory must red if one facade seam escapes the fake."""
    from app.db import repo as repo_mod

    monkeypatch.setattr(repo_mod, "settle_pipeline_job", lambda *_a, **_kw: None)
    with pytest.raises(AssertionError, match="settle_pipeline_job"):
        _assert_durable_recovery_pairs(repo_mod, fake_repo)


def test_retired_recovery_fakes_and_patch_names_are_absent(fake_repo) -> None:
    """Strict fakes reject retired calls instead of recreating a fallback policy."""
    from app.db import repo as repo_mod
    from tests.conftest import InMemoryRepo

    conftest_path = pathlib.Path(inspect.getsourcefile(InMemoryRepo) or "")
    assert conftest_path.is_file(), "InMemoryRepo source inventory must exist"
    conftest_source = conftest_path.read_text(encoding="utf-8")
    fake_methods = {
        name
        for name, _member in inspect.getmembers(
            InMemoryRepo, predicate=inspect.isfunction
        )
    }
    patch_names = set().union(
        *(names for _line, names in _monkeypatch_name_tuples(conftest_path))
    )

    assert not (_RETIRED_RECOVERY_SYMBOLS & fake_methods)
    assert not (_RETIRED_RECOVERY_SYMBOLS & patch_names)
    assert all(name not in conftest_source for name in _RETIRED_RECOVERY_SYMBOLS)
    for name in _RETIRED_RECOVERY_SYMBOLS:
        assert not hasattr(fake_repo, name)
        assert not hasattr(repo_mod, name)


def test_every_inmemory_method_that_shadows_a_real_repo_name_is_actually_patched(
    fake_repo,
) -> None:
    """Inside the fake_repo fixture's active patch, every PUBLIC callable
    attribute of InMemoryRepo that ALSO exists on app.db.repo must resolve,
    through the facade, back to THIS store's bound method — not to the real
    module-level function.
    """
    from app.db import repo as repo_mod
    from tests.conftest import InMemoryRepo

    store = fake_repo
    unpatched: list[str] = []
    for name, _member in inspect.getmembers(InMemoryRepo, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        if not hasattr(repo_mod, name):
            continue
        current = getattr(repo_mod, name)
        if getattr(current, "__self__", None) is not store:
            unpatched.append(name)

    assert not unpatched, (
        "these methods are defined on InMemoryRepo but missing from the "
        "fake_repo name tuple, so the REAL DB-backed function is running "
        "against a FakeCursor -- a silent-corruption bug, not a test "
        f"failure: {sorted(unpatched)}"
    )


def _monkeypatch_name_tuples(source_path: pathlib.Path) -> list[tuple[int, set[str]]]:
    """Find every `for name in (...)` loop in `source_path` whose body drives
    a `monkey.setattr(...)` call, and return (line number, {names}) for each.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    found: list[tuple[int, set[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not (isinstance(node.target, ast.Name) and node.target.id == "name"):
            continue
        if not isinstance(node.iter, (ast.Tuple, ast.List)):
            continue
        names_in_tuple = {
            elt.value
            for elt in node.iter.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        }
        if not names_in_tuple:
            continue
        drives_setattr = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "setattr"
            for n in ast.walk(node)
        )
        if drives_setattr:
            found.append((node.lineno, names_in_tuple))
    return found


def test_threading_ministore_patch_sets_are_complete() -> None:
    """A STATIC guard for tests/test_threading.py's two OTHER monkeypatch name
    tuples: every public method _MiniStore defines that also shadows a real
    app.db.repo name must appear in EVERY registered tuple that follows it.

    This is the mechanised form of "three tuples, not one" — a future
    contributor who adds a _MiniStore method and forgets to register it gets
    a red test here instead of a silently vanished write.
    """
    import tests.test_threading as tt_mod
    from app.db import repo as repo_mod

    ministore_names = {
        name
        for name, _m in inspect.getmembers(tt_mod._MiniStore, predicate=inspect.isfunction)
        if not name.startswith("_") and hasattr(repo_mod, name)
    }

    source_path = pathlib.Path(tt_mod.__file__)
    registered_tuples = _monkeypatch_name_tuples(source_path)

    assert len(registered_tuples) == 2, (
        "expected exactly two monkeypatch name tuples in "
        f"tests/test_threading.py; found {len(registered_tuples)} at lines "
        f"{[ln for ln, _ in registered_tuples]}"
    )

    for lineno, names_in_tuple in registered_tuples:
        missing = ministore_names - names_in_tuple
        assert not missing, (
            f"the monkeypatch tuple at tests/test_threading.py:{lineno} is "
            f"missing _MiniStore method(s) that also shadow an app.db.repo "
            f"name: {sorted(missing)} -- a method defined on _MiniStore but "
            "missing from its tuple silently falls through to the real "
            "DB-backed repo."
        )


# ---------------------------------------------------------------------------
# The suite-wide daemon-worker leak guard (tests/conftest.py)
# ---------------------------------------------------------------------------


def test_the_leak_guard_fails_on_a_surviving_worker_thread() -> None:
    """A bare thread named queue-worker-* that is still alive must be caught
    by fail_on_leaked_queue_workers(); once joined, the guard must return
    cleanly -- a real liveness check, not a latch that reds every subsequent
    test. The sentinel is joined INSIDE this test body, or the very fixture
    this test proves would (correctly) fail this test.
    """
    from tests.conftest import fail_on_leaked_queue_workers, live_queue_worker_threads

    release = threading.Event()
    sentinel = threading.Thread(
        name="queue-worker-leak-sentinel", target=release.wait, daemon=True
    )
    sentinel.start()
    try:
        assert sentinel in live_queue_worker_threads()
        with pytest.raises(pytest.fail.Exception, match="queue-worker-leak-sentinel"):
            fail_on_leaked_queue_workers()
    finally:
        release.set()
        sentinel.join(timeout=5)

    assert not sentinel.is_alive()
    fail_on_leaked_queue_workers()  # must now return cleanly


def test_the_leak_guard_is_wired_into_an_autouse_fixture() -> None:
    """The guard must be DEFINED AND CALLED from an autouse fixture's
    teardown -- a guard that is only defined is decorative.

    pytest's own fixture-marker attribute name has moved across major
    versions (`_pytestfixturefunction` -> `_fixture_function_marker`); check
    both so this assertion tracks the installed pytest rather than one
    version's internals.
    """
    from tests.conftest import _no_leaked_queue_workers

    marker = getattr(
        _no_leaked_queue_workers,
        "_fixture_function_marker",
        getattr(_no_leaked_queue_workers, "_pytestfixturefunction", None),
    )
    assert marker is not None and marker.autouse is True

    wrapped = getattr(_no_leaked_queue_workers, "_get_wrapped_function", None)
    fn = wrapped() if callable(wrapped) else _no_leaked_queue_workers
    source = inspect.getsource(fn)
    assert "fail_on_leaked_queue_workers()" in source
