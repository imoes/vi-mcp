"""0.20.0: Training bei Bedarf statt nur nachts; Nähe-Kanten inkrementell."""
import time

import pytest

from vi_mcp import bedarf, intuition, vektor, werkzeuge
from vi_mcp import gedaechtnis as g

from test_vektor import fake_einbetten


@pytest.fixture()
def fake(gd, monkeypatch):
    monkeypatch.setattr(vektor, "einbetten_fn", fake_einbetten)
    monkeypatch.setattr(vektor, "konfig", {"modell": "fake"})
    bedarf.stand.update({"laeufe": 0, "angestossen": 0, "vektoren_seit_kmeans": 0})
    yield
    monkeypatch.setattr(vektor, "einbetten_fn", None)


def test_erfahrung_und_wissen_stossen_training_an(fake):
    vor = bedarf.stand["angestossen"]
    v = intuition.vorher("Bash", {"command": "ls"}, "a")
    intuition.nachher("Bash", {"command": "ls"}, True, 5, None, "ok", v["vorher_id"], "a")
    werkzeuge.rufe("vi_lerne", {"text": "Proxy-Timeout auf web1 nach 30 s", "hashtags": ["host:web1"], "quelle": "Beobachtung 9.11."}, "a", True)
    assert bedarf.stand["angestossen"] == vor + 2


def test_lauf_bettet_ein_und_trainiert_mit_dauer(fake):
    a = g.neues_objekt("erkenntnis", "Proxy timeout auf web1", ["host:web1"], {"quelle": "x"}, grund="T")
    r = bedarf.lauf("Test")
    assert set(r["schritte"]) >= {"vektoren", "naehe", "hinweise", "lernen"}
    assert all("ms" in s for s in r["schritte"].values())
    assert vektor.lade(a.id) is not None and r["vektoren_offen"] == 0
    assert "Training bei Bedarf: 1 Läufe" in bedarf.zeile()
    assert "Training bei Bedarf" in werkzeuge.rufe("vi_status", {}, "a", True)


def test_naehe_kanten_vergleichen_nur_neue(fake):
    a = g.neues_objekt("erkenntnis", "Proxy timeout auf web1", ["host:web1"], {"quelle": "x"}, grund="T", instanz="a")
    g.neues_objekt("erkenntnis", "Disk voll auf web2", ["host:web2"], {"quelle": "y"}, grund="T")
    vektor.nachziehen(max_s=60)
    assert vektor.naehe_kanten()["neu_verglichen"] == 2
    assert vektor.naehe_kanten()["neu_verglichen"] == 0  # nichts Neues: kein Vergleich
    b = g.neues_objekt("erkenntnis", "Verbindung haengt am Proxy", ["host:web3"], {"quelle": "z"}, grund="T", instanz="b")
    vektor.nachziehen(max_s=60)
    r = vektor.naehe_kanten()
    assert r["neu_verglichen"] == 1 and r["kanten_neu"] == 1
    assert any(x == b.id for x, _gr in g.lade(a.id).kanten())


def test_hintergrund_thread_laeuft_nach_anstoss(fake, monkeypatch):
    monkeypatch.setattr(bedarf, "ABSTAND_S", 0)
    th = bedarf.starte()
    try:
        bedarf.anstossen("Test")
        ende = time.time() + 10
        while bedarf.stand["laeufe"] == 0 and time.time() < ende:
            time.sleep(0.05)
        assert bedarf.stand["laeufe"] >= 1 and "Test" in bedarf.stand["grund"]
    finally:
        bedarf.halte()
        th.join(timeout=10)
