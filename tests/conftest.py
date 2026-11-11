import os

import pytest

#: 0.50.0: tests about SQLite files (permissions, migration of old files, VACUUM) do not apply to PostgreSQL
sqlite_only = pytest.mark.skipif(bool(os.environ.get("VI_MCP_TEST_PG")), reason="SQLite file behaviour; the suite runs against PostgreSQL")

from vi_mcp import memory as g
from vi_mcp import intuition, reflexes, session


@pytest.fixture()
def gd(tmp_path):
    """Frisches Gedächtnis je Test, ohne Sitzungen, ohne Reflexe."""
    g.open_db(tmp_path / "vi.db")
    session.end_all("unterbrochen")
    reflexes.loaded.clear()
    intuition.ttl_per_tool.clear()
    intuition._daily.clear()  # 0.49.0: the daily cap is module state — it must not leak from one test into the next
    from vi_mcp import capabilities
    capabilities._cache.clear()  # 0.53.0: the skill table is cached per instance
    yield tmp_path / "vi.db"
    session.end_all("unterbrochen")
    g.close_db()


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """No test may write the real configuration (~/.config/vi-mcp/config.json): net setup registers networks and live search there."""
    import os
    if not os.environ.get("VI_MCP_CONFIG"):
        monkeypatch.setenv("VI_MCP_CONFIG", str(tmp_path / "vi-mcp-config.json"))


@pytest.fixture(autouse=True)
def _postgres_backend(monkeypatch):
    """0.50.0: with VI_MCP_TEST_PG=postgresql://… the whole suite runs against PostgreSQL — every database file becomes its own schema."""
    import hashlib
    import os
    base = os.environ.get("VI_MCP_TEST_PG")
    if not base:
        return
    from vi_mcp import db as dbmod
    original = g.open_db

    def open_pg(fpath):
        if dbmod.is_url(fpath):
            return original(fpath)
        schema = "t_" + hashlib.md5(str(fpath).encode()).hexdigest()[:20]
        return original(f"{base}{'&' if '?' in base else '?'}options=-csearch_path%3D{schema}")
    open_pg.original = original  # tests that build a SQLite file on purpose (migration)
    monkeypatch.setattr(g, "open_db", open_pg)
    from vi_mcp import logbook as lb
    log_init = lb.Logbook.__init__

    def logbook_pg(self, fpath, *a, **kw):
        if not dbmod.is_url(fpath):
            kw["schema"] = "l_" + hashlib.md5(str(fpath).encode()).hexdigest()[:20]
            fpath = base
        return log_init(self, fpath, *a, **kw)
    monkeypatch.setattr(lb.Logbook, "__init__", logbook_pg)
