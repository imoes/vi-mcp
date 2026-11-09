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


def test_einbettung_pausiert_zwischen_batches(fake, monkeypatch):
    """0.20.5: Für geteilte Embedding-Dienste: nach jedem Batch eine Pause in Länge seiner Dauer (pause_anteil 1.0); Standard ungedrosselt."""
    assert vektor.PAUSE_ANTEIL == 0
    def langsam(texte):
        time.sleep(0.05)
        return fake_einbetten(texte)
    monkeypatch.setattr(vektor, "einbetten_fn", langsam)
    monkeypatch.setattr(vektor, "BATCH", 1)
    monkeypatch.setattr(vektor, "konfig", {"modell": "fake", "pause_anteil": 1.0})
    for i in range(3):
        g.neues_objekt("erkenntnis", f"Proxy timeout Nummer {i} auf web{i}", [f"host:web{i}"], {"quelle": "x"}, grund="T")
    t0 = time.monotonic()
    r = vektor.nachziehen(max_s=60)
    assert r["neu"] == 3 and r["pause_s"] >= 0.09  # zwei Pausen (nach dem letzten Batch keine)
    assert time.monotonic() - t0 >= 0.24
    monkeypatch.setattr(vektor, "konfig", {"modell": "fake", "pause_anteil": 0})
    g.neues_objekt("erkenntnis", "Disk voll auf web9", ["host:web9"], {"quelle": "y"}, grund="T")
    assert vektor.nachziehen(max_s=60)["pause_s"] == 0


def test_schlaf_haelt_den_loop_nicht_an(gd, monkeypatch):
    """0.20.5: Der Schlaf lief synchron im Loop (gemessen 429–530 s) und hielt Loop und Training bei Bedarf an."""
    from vi_mcp import schlaf, schleife
    import threading
    gestartet, frei = threading.Event(), threading.Event()

    def lauf(grund):
        with schlaf._laeuft:
            gestartet.set()
            frei.wait(5)
        return g.neues_objekt("schlaf", "Testschlaf", ["zustand:fertig"], {}, grund="T")
    monkeypatch.setattr(schlaf, "faellig", lambda: "Test")
    monkeypatch.setattr(schlaf, "lauf", lauf)
    t0 = time.monotonic()
    schleife.schritt()
    assert gestartet.wait(2) and time.monotonic() - t0 < 1.5
    aufrufe = []
    monkeypatch.setattr(schlaf, "faellig", lambda: aufrufe.append(1) or "Test")
    schleife.schritt()  # läuft noch: kein zweiter Schlaf, faellig wird gar nicht erst gefragt
    assert aufrufe == [] and schlaf.laeuft()
    frei.set()


def test_semantische_kanten_haben_eine_obergrenze(fake, monkeypatch):
    """0.20.6: Fast gleiche Vorlagenseiten verbanden sich alle miteinander (2,24 Mio. Kanten, bis 1.316 je Objekt)."""
    monkeypatch.setattr(vektor, "einbetten_fn", lambda texte: [[1.0, 0.0] for _ in texte])  # alle identisch: cos 1.0
    monkeypatch.setattr(vektor, "NAEHE_MAX", 3)
    objs = [g.neues_objekt("erkenntnis", f"Vorlage Server {i}: Hier können Notizen stehen", [f"seite:{i}"], {"quelle": "x"}, grund="T")
            for i in range(12)]
    vektor.nachziehen(max_s=60)
    vektor.naehe_kanten()
    sem = lambda o: [b for b, gr in g.lade(o.id).kanten() if gr.startswith("semantisch")]
    assert max(len(sem(o)) for o in objs) <= 3  # gegenseitige nächste Nachbarn: streng begrenzt
    belegt = objs[0]
    belegt.verknuepfe(objs[11].id, "Beleg (Test)")
    # Altbestand ohne Grenze (wie vor 0.20.6): von Hand alle Paare verbinden, dann kappen
    for a in objs:
        for b in objs:
            if a.id < b.id:
                a.verknuepfe(b.id, "semantisch ähnlich (cos 1.00)")
    vorher = sum(len(sem(o)) for o in objs)
    weg = vektor.kappen(3)
    assert weg > 0 and sum(len(sem(o)) for o in objs) == vorher - weg
    assert max(len(sem(o)) for o in objs) <= 3
    assert any(b == objs[11].id and gr.startswith("Beleg") for b, gr in g.lade(belegt.id).kanten())  # Beleg bleibt
    assert vektor.kappen(3) == 0  # schon begrenzt
