"""0.7.0: Vektoren — Einbettung im Schlaf, Nähe-Kanten, Dubletten, semantische Suche (ohne Netz: Fake-Einbettung)."""
import math

import pytest

from vi_mcp import schlaf, vektor, werkzeuge
from vi_mcp import gedaechtnis as g

WORTE = ["timeout", "disk", "voll", "proxy", "netz"]
SYNONYME = {"haengt": "timeout", "verbindung": "timeout"}


def fake_einbetten(texte):
    """Deterministische Bag-of-Words-Einbettung; 'haengt' und 'verbindung' zählen als 'timeout' (Synonyme)."""
    aus = []
    for t in texte:
        t = t.lower()
        v = [0.0] * len(WORTE)
        for i, w in enumerate(WORTE):
            if w in t or any(syn in t for syn, ziel in SYNONYME.items() if ziel == w):
                v[i] = 1.0
        aus.append(v)
    return aus


@pytest.fixture()
def fake(gd, monkeypatch):
    monkeypatch.setattr(vektor, "einbetten_fn", fake_einbetten)
    monkeypatch.setattr(vektor, "konfig", {"modell": "fake"})
    yield
    monkeypatch.setattr(vektor, "einbetten_fn", None)


def test_ohne_dienst_benannt_uebersprungen(gd, monkeypatch):
    monkeypatch.setattr(vektor, "einbetten_fn", None)
    monkeypatch.setattr(vektor, "konfig", None)
    b = schlaf.lauf("Test")
    assert b.daten["schritte"]["7_vektoren"]["zustand"] == "uebersprungen" and b.daten["schritte"]["7b_naehe"]["zustand"] == "uebersprungen"
    with pytest.raises(werkzeuge.Abgelehnt, match="kein Embedding-Dienst"):
        werkzeuge.rufe("vi_erinnere", {"filter": "timeout", "semantisch": True}, "a", True)


def test_vektoren_im_schlaf_und_naehe_kanten(fake):
    a = g.neues_objekt("erkenntnis", "graylog Timeout auf cue1", ["host:cue1"], {"quelle": "x"}, grund="T", instanz="a")
    b = g.neues_objekt("erkenntnis", "Verbindung zu cue1 haengt", ["host:cue1"], {"quelle": "y"}, grund="T", instanz="b")
    c = g.neues_objekt("erkenntnis", "Disk voll auf web1", ["host:web1"], {"quelle": "z"}, grund="T")
    bericht = schlaf.lauf("Test")
    s7 = bericht.daten["schritte"]["7_vektoren"]
    assert s7["zustand"] == "fertig" and s7["neu"] == 3 and vektor.lade(a.id) is not None
    assert math.isclose(vektor.kosinus(vektor.lade(a.id), vektor.lade(b.id)), 1.0, abs_tol=1e-6)  # Synonyme → identischer Vektor
    s7b = bericht.daten["schritte"]["7b_naehe"]
    assert s7b["kanten_neu"] == 1 and s7b["dubletten_moeglich"] == 1
    assert any("semantisch ähnlich" in gr for _, gr in g.lade(a.id).kanten())
    assert "dublette:moeglich" in g.lade(a.id).hashtags and "dublette:moeglich" in g.lade(b.id).hashtags
    assert "dublette:moeglich" not in g.lade(c.id).hashtags
    assert schlaf.lauf("Test 2").daten["schritte"]["7_vektoren"]["neu"] == 0  # idempotent


def test_semantische_suche(fake):
    a = g.neues_objekt("erkenntnis", "graylog Timeout auf cue1", ["host:cue1"], {"quelle": "x"}, grund="T")
    g.neues_objekt("erkenntnis", "Disk voll auf web1", ["host:web1"], {"quelle": "z"}, grund="T")
    schlaf.lauf("Test")
    r = werkzeuge.rufe("vi_erinnere", {"filter": "Verbindung haengt", "semantisch": True}, "a", True)
    assert r.splitlines()[1].strip().startswith(f"[{a.id}]") and "semantisch hybrid (Embedding" in r
    assert "nichts im Gedächtnis" in werkzeuge.rufe("vi_erinnere", {"filter": "Verbindung haengt"}, "a", True)  # FTS findet es nicht
    with pytest.raises(werkzeuge.Abgelehnt, match="Freitext"):
        werkzeuge.rufe("vi_erinnere", {"filter": "host:cue1", "semantisch": True}, "a", True)


def test_nachziehen_nennt_den_echten_rest(gd, monkeypatch):
    monkeypatch.setattr(vektor, "einbetten_fn", lambda texte: [[1.0, 0.0] for _ in texte])
    monkeypatch.setattr(vektor, "BATCH", 2)
    for i in range(5):
        g.neues_objekt("erkenntnis", f"Wissen Nummer {i} zum Einbetten", ["thema:a"], {"quelle": "x"}, grund="T")
    r = vektor.nachziehen(max_s=0)  # Zeit schon um: nichts eingebettet, alles offen
    assert r == {"zustand": "fertig", "neu": 0, "offen": 5, "pause_s": 0.0}
    r = vektor.nachziehen()
    assert r["neu"] == 5 and r["offen"] == 0


def test_semantische_suche_prueft_alle_vektoren_nicht_nur_die_neuesten(fake):
    """0.19.2: Kandidaten waren die 200 zuletzt benutzten Objekte — ältere Doku wurde nie verglichen (gemessen am Vergleich mit der AIKB)."""
    alt = g.neues_objekt("erkenntnis", "Proxy-Doku: Verbindung über den Proxy", ["doku:x"], {"quelle": "alt"}, grund="T")
    g.db().execute("UPDATE objekt SET zuletzt = '2020-01-01T00:00:00+00:00', zeit = '2020-01-01T00:00:00+00:00' WHERE id = ?", (alt.id,))
    for i in range(260):
        g.neues_objekt("erkenntnis", f"Disk voll auf web{i}", [f"host:web{i}"], {"quelle": "neu"}, grund="T")
    vektor.nachziehen(max_s=600)
    r = werkzeuge.rufe("vi_erinnere", {"filter": "proxy netz", "semantisch": True, "limit": 3}, "a", True)
    assert r.splitlines()[1].strip().startswith(f"[{alt.id}]"), r
    assert "261 von 261 Kandidaten mit Vektor" in r


def test_semantische_suche_nennt_objekte_ohne_vektor(fake):
    g.neues_objekt("erkenntnis", "proxy timeout", ["host:a"], {"quelle": "x"}, grund="T")
    vektor.nachziehen(max_s=600)
    g.neues_objekt("erkenntnis", "proxy disk", ["host:b"], {"quelle": "y"}, grund="T")  # noch ohne Vektor
    r = werkzeuge.rufe("vi_erinnere", {"filter": "proxy", "semantisch": True}, "a", True)
    assert "1 von 2 Kandidaten mit Vektor" in r


def test_frisch_gelerntes_ohne_vektor_findet_die_hybride_suche(fake):
    """0.19.5: Neues hat bis zum nächsten Schlaf keinen Vektor. Die Bedeutungssuche allein fand es nicht (Lerntest 09.11.: 1 von 8 vorher und nachher)."""
    for i in range(30):
        g.neues_objekt("erkenntnis", f"Disk voll auf web{i}", [f"host:web{i}"], {"quelle": "alt"}, grund="T")
    vektor.nachziehen(max_s=600)
    neu = g.neues_objekt("erkenntnis", "ipa-client-install scheitert mit TypeError IPACertificate, Ursache pip-cryptography", ["thema:ipa-client-install"],
                         {"quelle": "neu"}, grund="T")
    r = werkzeuge.rufe("vi_erinnere", {"filter": "ipa-client-install TypeError IPACertificate", "semantisch": True, "limit": 3}, "a", True)
    assert neu.id in r and "nur über Volltext" in r, r


def test_volltext_faellt_auf_oder_zurueck_und_sagt_es(gd):
    """0.19.2: FTS5 verknüpft Wörter mit UND — ein Füllwort der Frage („anzuhalten“) ergab 0 Treffer."""
    a = g.neues_objekt("erkenntnis", "vzdump im Modus snapshot sichert laufende VMs", ["skill:proxmox"], {"quelle": "x"}, grund="T")
    b = g.neues_objekt("erkenntnis", "vzdump sichert VMs", ["skill:proxmox"], {"quelle": "y"}, grund="T")
    r = werkzeuge.rufe("vi_erinnere", {"filter": "vzdump snapshot laufende anzuhalten"}, "a", True)
    assert "ODER-Suche" in r and r.splitlines()[1].strip().startswith(f"[{a.id}]") and b.id in r
    voll = werkzeuge.rufe("vi_erinnere", {"filter": "vzdump snapshot"}, "a", True)  # alle Wörter da, genug Treffer bei limit 1
    assert "ODER-Suche" not in werkzeuge.rufe("vi_erinnere", {"filter": "vzdump sichert", "limit": 1}, "a", True) and a.id in voll
    # interne Aufrufer behalten UND
    assert g.erinnere("vzdump snapshot anzuhalten") == [] and g.wortsuche.get() == "und"


def test_volltext_mit_hashtag_filter_sucht_nur_im_gefilterten(gd):
    """FTS lief vorher global mit LIMIT 500 und wurde erst danach gefiltert: passende Objekte hinter 500 fremden Treffern fehlten."""
    for i in range(520):
        g.neues_objekt("erkenntnis", f"timeout auf web{i}", [f"host:web{i}"], {"quelle": "x"}, grund="T")
    ziel = g.neues_objekt("erkenntnis", "timeout auf cue1", ["host:cue1"], {"quelle": "x"}, grund="T")
    assert [o.id for _, o, _g in g.erinnere("host:cue1 timeout")] == [ziel.id]
