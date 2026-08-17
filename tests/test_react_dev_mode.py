"""The fail-closed dev-server branch in render_react_page().

Asserts the four required mitigations for the dev-server render branch plus
the production fail-closed property it must not weaken:

1. Default settings never emit a developer-host URL (no `localhost`, no
   reference to the dev-server env var's configured value).
2. Default settings + a missing manifest still raise ManifestMissingError --
   adding the dev branch did not weaken the existing production fail-closed
   path.
3. The dev setting explicitly enabled emits the Vite dev client module and
   the entry's raw source path from that origin, and never reads the
   manifest at all.
4. The image build (Dockerfile) never sets the dev-server env var, so the
   dev branch is structurally unreachable in a deployed container.

`TestClient` never executes JavaScript, so these tests assert on the
server-rendered HTML markup only -- exactly the same boundary
tests/test_react_page_render.py already exercises for the production branch.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routes import templating
from app.routes.templating import ManifestMissingError

_DEV_ORIGIN = "http://localhost:5173"


@pytest.fixture
def _dev_mode_enabled(monkeypatch: pytest.MonkeyPatch):
    """Enable the dev-server render branch for one test, then restore the
    production-safe default so no other test in the suite inherits a
    dev-mode render.

    Mirrors the settings-cache-clearing idiom already used elsewhere in the
    suite (tests/test_webhook.py's `client` fixture) when varying Settings.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("VITE_DEV_SERVER_URL", _DEV_ORIGIN)
    get_settings.cache_clear()
    yield _DEV_ORIGIN
    get_settings.cache_clear()


def test_default_settings_render_emits_no_developer_host_url(client, fake_repo):
    """A default-settings render of /runs must never carry a developer-host
    URL -- neither the literal substring `localhost` nor the configured
    dev-server origin's value."""
    get_settings.cache_clear()
    business_id = next(iter(fake_repo.contact_to_business.values()))
    fake_repo.create_run(business_id=business_id, source_email_id=None)

    response = client.get("/runs")

    assert response.status_code == 200
    assert "localhost" not in response.text
    assert _DEV_ORIGIN not in response.text


def test_default_settings_missing_manifest_still_raises(
    fake_repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The production fail-closed manifest behaviour is unchanged by the dev
    branch's existence -- default settings, no dev origin configured, and a
    missing manifest still raise ManifestMissingError rather than rendering
    a bundle-less shell."""
    get_settings.cache_clear()
    business_id = next(iter(fake_repo.contact_to_business.values()))
    fake_repo.create_run(business_id=business_id, source_email_id=None)

    monkeypatch.setattr(templating, "MANIFEST_PATH", tmp_path / "does-not-exist.json")
    templating.load_manifest.cache_clear()

    strict_client = TestClient(app, raise_server_exceptions=True)
    with pytest.raises(ManifestMissingError):
        strict_client.get("/runs")

    templating.load_manifest.cache_clear()


def test_dev_setting_enabled_renders_dev_client_and_skips_manifest(
    _dev_mode_enabled: str, fake_repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """With the dev setting explicitly configured, the render emits the Vite
    dev client module and the entry's source path from that origin, and
    never reads the manifest at all -- proved by pointing the manifest path
    at a nonexistent file and confirming the render still succeeds."""
    business_id = next(iter(fake_repo.contact_to_business.values()))
    fake_repo.create_run(business_id=business_id, source_email_id=None)

    monkeypatch.setattr(templating, "MANIFEST_PATH", tmp_path / "does-not-exist.json")
    templating.load_manifest.cache_clear()

    strict_client = TestClient(app, raise_server_exceptions=True)
    response = strict_client.get("/runs")

    templating.load_manifest.cache_clear()

    assert response.status_code == 200
    assert (
        f'<script type="module" src="{_dev_mode_enabled}/@vite/client"></script>'
        in response.text
    )
    assert (
        f'<script type="module" src="{_dev_mode_enabled}/src/entries/runs.tsx"></script>'
        in response.text
    )
    # No manifest-resolved hashed asset path leaked into the dev-mode render.
    assert "/static/dist/" not in response.text


def test_dockerfile_never_sets_the_dev_server_env_var():
    """The image build must never set the dev-server env var, so the dev
    branch is structurally unreachable in a deployed container -- asserted
    by reading the tracked Dockerfile text."""
    dockerfile_text = Path("Dockerfile").read_text()
    assert "VITE_DEV_SERVER_URL" not in dockerfile_text
