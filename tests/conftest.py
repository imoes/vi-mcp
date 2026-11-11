import pytest

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
    yield tmp_path / "vi.db"
    session.end_all("unterbrochen")
    g.close_db()


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """No test may write the real configuration (~/.config/vi-mcp/config.json): net setup registers networks and live search there."""
    import os
    if not os.environ.get("VI_MCP_CONFIG"):
        monkeypatch.setenv("VI_MCP_CONFIG", str(tmp_path / "vi-mcp-config.json"))
