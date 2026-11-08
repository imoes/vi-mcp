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
    assert r.splitlines()[1].strip().startswith(f"[{a.id[:34]}]") and "semantisch (Embedding" in r
    assert "nichts im Gedächtnis" in werkzeuge.rufe("vi_erinnere", {"filter": "Verbindung haengt"}, "a", True)  # FTS findet es nicht
    with pytest.raises(werkzeuge.Abgelehnt, match="Freitext"):
        werkzeuge.rufe("vi_erinnere", {"filter": "host:cue1", "semantisch": True}, "a", True)
