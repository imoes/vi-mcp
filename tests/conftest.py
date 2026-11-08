import pytest

from vi_mcp import gedaechtnis as g
from vi_mcp import intuition, reflexe, sitzung


@pytest.fixture()
def gd(tmp_path):
    """Frisches Gedächtnis je Test, ohne Sitzungen, ohne Reflexe."""
    g.oeffne(tmp_path / "vi.db")
    sitzung.alle_beenden("unterbrochen")
    reflexe.geladen.clear()
    intuition.ttl_je_werkzeug.clear()
    yield tmp_path / "vi.db"
    sitzung.alle_beenden("unterbrochen")
    g.schliesse()
