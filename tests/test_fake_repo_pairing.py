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
