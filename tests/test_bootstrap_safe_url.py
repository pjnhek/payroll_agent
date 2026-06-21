"""Unit tests for bootstrap._safe_db_url — pure, no DB connection (WR-05).

The redaction helper must:
- strip the password when present (the original behavior, kept),
- return a reconstructed URL for ALL parseable cases, including valid
  password-less URLs (the WR-05 fix — these used to fall through to
  '<unparseable url>' and mislead an operator during connection
  troubleshooting),
- reserve '<unparseable url>' for genuinely unparseable / scheme-less input.
"""

import pytest

from app.db.bootstrap import _safe_db_url


def test_strips_password() -> None:
    assert (
        _safe_db_url("postgresql://user:secret@host:6543/db")
        == "postgresql://user:***@host:6543/db"
    )


def test_passwordless_url_with_user_is_returned_verbatim() -> None:
    """A valid password-less URL must NOT be reported as '<unparseable url>'."""
    url = "postgresql://user@host:6543/db"
    assert _safe_db_url(url) == url


def test_passwordless_url_without_user_is_returned_verbatim() -> None:
    url = "postgresql://host:5432/db"
    assert _safe_db_url(url) == url


@pytest.mark.parametrize("bad", ["", "not a url", "   "])
def test_unparseable_input_returns_sentinel(bad: str) -> None:
    assert _safe_db_url(bad) == "<unparseable url>"


def test_password_is_never_leaked() -> None:
    """The literal password must not appear in the redacted output."""
    out = _safe_db_url("postgresql://user:hunter2@host:6543/db")
    assert "hunter2" not in out
    assert "***" in out
