"""Hermetic half of SHELL-05's proof: the Vite manifest path resolves under the
existing `/static` mount, the loader fails closed when the file is absent, and
the committed fixture manifest's chunk shape matches the real build recorded in
frontend/MANIFEST-SHAPE.md -- so a fixture drift is caught here rather than
silently masking a loader change. The other (Docker-build) half of the proof is
a real `docker build` run recorded separately, not a pytest test -- no
hermetic test can prove an image actually contains a bundle.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from app.routes.templating import MANIFEST_PATH, ManifestMissingError, load_manifest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST_SHAPE_DOC = REPO_ROOT / "frontend" / "MANIFEST-SHAPE.md"
FIXTURE_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "vite_manifest.json"


def test_manifest_path_resolves_under_the_static_mount() -> None:
    """The manifest path constant used by the template layer must live under
    app/static -- the exact directory app/main.py's `/static` mount serves --
    so a built bundle is actually reachable by the browser, not just present
    somewhere on disk."""
    parts = MANIFEST_PATH.parts
    assert parts[:2] == ("app", "static"), (
        f"MANIFEST_PATH={MANIFEST_PATH} does not resolve under app/static/, "
        "the directory app/main.py mounts at /static"
    )


def test_static_mount_serves_app_static_directory() -> None:
    """Cross-check against the live route table: app/main.py's `/static` mount
    directory must literally be app/static, or the assertion above is checking
    the wrong thing."""
    from starlette.routing import Mount

    from app.main import app

    mounts = [route for route in app.routes if isinstance(route, Mount)]
    assert len(mounts) == 1, f"expected exactly one Mount, found {len(mounts)}"
    static_mount = mounts[0]
    assert static_mount.path == "/static"
    assert str(static_mount.app.directory) == "app/static"  # type: ignore[attr-defined]


def test_load_manifest_raises_when_file_absent(monkeypatch, tmp_path) -> None:
    """A missing manifest file fails closed rather than degrading to an empty
    or bundle-less shell."""
    from app.routes import templating

    monkeypatch.setattr(templating, "MANIFEST_PATH", tmp_path / "does-not-exist.json")
    templating.load_manifest.cache_clear()
    try:
        with pytest.raises(ManifestMissingError):
            templating.load_manifest()
    finally:
        templating.load_manifest.cache_clear()


def _real_build_chunk_shape() -> tuple[str, frozenset[str]]:
    """Parse the verbatim real-build manifest JSON block recorded in
    frontend/MANIFEST-SHAPE.md, returning (top_level_key, chunk_key_set)."""
    text = MANIFEST_SHAPE_DOC.read_text()
    match = re.search(
        r"Verbatim manifest JSON from the real build\s*```json\s*(\{.*?\})\s*```",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "could not find the 'Verbatim manifest JSON from the real build' fenced "
        "block in frontend/MANIFEST-SHAPE.md -- has the doc been reformatted?"
    )
    manifest = json.loads(match.group(1))
    assert len(manifest) == 1, "expected exactly one entry in the recorded real build"
    (top_level_key, chunk), = manifest.items()
    return top_level_key, frozenset(chunk)


def test_fixture_manifest_matches_the_real_build_chunk_shape() -> None:
    """The committed fixture manifest (tests/fixtures/vite_manifest.json) must
    carry the same top-level key form and the same chunk key set the real
    `npm run build` produced -- so a change to the real Vite output shape is
    caught here instead of silently drifting from what the hermetic suite
    exercises."""
    real_key, real_chunk_keys = _real_build_chunk_shape()
    fixture = json.loads(FIXTURE_MANIFEST.read_text())

    assert real_key in fixture, (
        f"fixture manifest is missing the real build's top-level key {real_key!r}"
    )
    fixture_chunk_keys = frozenset(fixture[real_key])
    assert fixture_chunk_keys == real_chunk_keys, (
        f"fixture chunk key set {sorted(fixture_chunk_keys)} does not match the "
        f"real build's {sorted(real_chunk_keys)} recorded in MANIFEST-SHAPE.md"
    )


def test_fixture_manifest_loads_through_the_real_loader(monkeypatch) -> None:
    """End-to-end sanity: load_manifest() against the committed fixture (the
    same one the whole suite's autouse fixture points at) resolves the exact
    entry render_react_page() looks up for /runs."""
    from app.routes import templating

    monkeypatch.setattr(templating, "MANIFEST_PATH", FIXTURE_MANIFEST)
    templating.load_manifest.cache_clear()
    try:
        manifest = load_manifest()
        assert "src/entries/runs.tsx" in manifest
        chunk = manifest["src/entries/runs.tsx"]
        assert chunk["isEntry"] is True
        assert isinstance(chunk["file"], str) and chunk["file"]
    finally:
        templating.load_manifest.cache_clear()
