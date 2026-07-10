import pathlib

import app.db.bootstrap as bootstrap
import psycopg


def test_bootstrap_timeout_constants_defined():
    assert bootstrap.LOCK_TIMEOUT_MS == 10000
    assert bootstrap.STATEMENT_TIMEOUT_MS == 60000


def test_bootstrap_sets_timeouts_before_ddl(monkeypatch):
    executed: list[str] = []

    class _FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, *args, **kw):
            executed.append(str(sql))
            return self
        def commit(self): pass

    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: _FakeConn())
    monkeypatch.setattr(bootstrap, "get_settings", lambda: type("S", (), {"database_url": "postgresql://x/y"})())
    # pathlib.Path instances don't support instance-attribute assignment
    # (PosixPath has no __dict__ override for methods), so the stub must be
    # applied at the class level rather than on the bootstrap._SCHEMA_SQL
    # instance directly.
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self: "-- noop schema")

    bootstrap.bootstrap(reset=False)

    joined = "\n".join(executed)
    assert "lock_timeout" in joined
    assert "statement_timeout" in joined
    # timeouts must precede the schema apply
    assert joined.index("lock_timeout") < joined.index("noop schema")
