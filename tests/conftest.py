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
    yield tmp_path / "vi.db"
    session.end_all("unterbrochen")
    g.close_db()
