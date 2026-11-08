"""0.16.0: Bedeutungsnähe und Inhaltsgruppen als Merkmale des Routers; Schlaf läuft nie doppelt und blockiert keinen Proxy."""
import random
import threading
import time

import numpy as np
import pytest

from vi_mcp import inhalt, intuition, lernen, schlaf, vektor, werkzeuge
from vi_mcp import gedaechtnis as g

pytest.importorskip("sklearn")


def _vec(richtung: int, rausch: float = 0.05, dim: int = 16, rng=random.Random(3)):
    v = np.array([rng.gauss(0, rausch) for _ in range(dim)])
    v[richtung] += 1.0
    return v.tolist()


@pytest.fixture()
def wissen(gd, monkeypatch):
    monkeypatch.setattr(vektor, "konfig", {"modell": "fake"})
    ids = {}
    for thema, richtung in (("tls", 0), ("disk", 1), ("netz", 2)):
        for i in range(8):
            o = g.neues_objekt("erkenntnis", f"Wissen {thema} Nummer {i} ausführlich", [f"thema:{thema}", "tool:Bash"], {"quelle": "Test 2.11."}, grund="T", instanz="a")
            vektor.speichere(o.id, _vec(richtung), "m")
            ids.setdefault(thema, []).append(o.id)
    inhalt.vergiss_cache()
    return ids


def test_berechne_und_naehe(wissen):
    r = inhalt.berechne()
    assert r["zustand"] == "fertig" and r["zentren"] == 4 and r["gruppen"] >= 2
    tls, disk = wissen["tls"][0], wissen["disk"][0]
    assert inhalt.naehe(tls, ["thema:tls"]) > 0.9  # passt zum Inhalt der Situation, auch ohne sich selbst
    assert inhalt.naehe(disk, ["thema:tls"]) < 0.2
    assert inhalt.naehe(tls, ["thema:unbekannt"]) is None and inhalt.naehe("erkenntnis:gibtsnicht", ["thema:tls"]) is None
    assert len({inhalt.gruppe(i) for i in wissen["tls"]}) == 1 and inhalt.gruppe(tls) != inhalt.gruppe(disk)
    assert "thema:tls" in inhalt.gruppen_name(inhalt.gruppe(tls)) and "Bedeutungsgruppen" in inhalt.zeile()


def test_sich_selbst_herausgerechnet(gd, monkeypatch):
    monkeypatch.setattr(vektor, "konfig", {"modell": "fake"})
    a = g.neues_objekt("erkenntnis", "Einziger Hinweis zum Thema A hier", ["thema:a"], {"quelle": "x"}, grund="T")
    vektor.speichere(a.id, _vec(0), "m")
    for i in range(3):
        o = g.neues_objekt("erkenntnis", f"Anderer Inhalt {i} zum Thema A", ["thema:a"], {"quelle": "x"}, grund="T")
        vektor.speichere(o.id, _vec(5), "m")
    inhalt.vergiss_cache()
    inhalt.berechne()
    assert inhalt.naehe(a.id, ["thema:a"]) < 0.3  # ohne Herausrechnen wäre er durch sich selbst ähnlich


def test_merkmale_und_schalter(wissen, monkeypatch):
    inhalt.berechne()
    m = lernen.merkmale_hinweis(wissen["tls"][0], ["thema:tls", "stunde:3"])
    assert "naehe" in m and any(k.startswith("inhalt:") for k in m)
    monkeypatch.setattr(lernen, "INHALT", False)
    assert set(lernen.merkmale_hinweis(wissen["tls"][0], ["thema:tls"])) == {f"hinweis:{wissen['tls'][0]}", "hinweisart:erkenntnis"}


def test_modell_lernt_den_inhalt(wissen, monkeypatch):
    """Hinweise zu TLS helfen, zu Disk nicht, und kein einzelner Hinweis ist oft genug für ein eigenes Gewicht: Nur der Inhalt kann es erklären."""
    inhalt.berechne()
    rng = random.Random(9)
    monkeypatch.setattr(lernen, "MIN_EREIGNISSE", 20)
    for n in range(400):
        thema = rng.choice(["tls", "disk"])
        hid = rng.choice(wissen[thema])
        ok = rng.random() < (0.9 if thema == "tls" else 0.2)
        g.neues_objekt("erfahrung", "Bash", ["tool:Bash", f"thema:{thema}", "ok:ja" if ok else "ok:nein"],
                       {"vorher": {"reize": ["tool:Bash", f"thema:{thema}"], "gezeigt": [hid]}, "args": {"n": n}}, grund="T", instanz="a")
    b = lernen.trainiere("Test")
    w = lernen.modell().daten["gewichte"]
    assert b["zustand"] == "aktiv", b
    gt, gd_ = inhalt.gruppe(wissen["tls"][0]), inhalt.gruppe(wissen["disk"][0])
    assert w.get(f"inhalt:{gt}", 0) > w.get(f"inhalt:{gd_}", 0)
    neu = g.neues_objekt("erkenntnis", "Ganz neuer Hinweis zu Zertifikaten", ["thema:tls", "tool:Bash"], {"quelle": "x"}, grund="T")
    vektor.speichere(neu.id, _vec(0), "m")
    alt_disk = wissen["disk"][0]
    inhalt.berechne()
    lernen.trainiere("Test 2")
    rang = [h for h, _ in lernen.rangfolge(lernen.modell(), ["tool:Bash"], [alt_disk, neu.id])]
    assert rang[0] == neu.id  # ein neuer Hinweis erbt das Gewicht seines Inhalts
    assert "Bedeutungs" in lernen.erklaerung() or "inhalt:" in lernen.erklaerung()


def test_schlaf_nie_doppelt_und_ohne_proxy_abbruch(gd, monkeypatch):
    halt = threading.Event()
    original = schlaf._lauf

    def langsam(grund):
        halt.wait(5)
        return original(grund)
    monkeypatch.setattr(schlaf, "_lauf", langsam)
    monkeypatch.setattr(schlaf, "WARTE_S", 0.3)
    t0 = time.monotonic()
    try:
        _schlaf_pruefen(halt, t0)
    finally:
        halt.set()
        for _ in range(80):
            if not schlaf._laeuft.locked():
                break
            time.sleep(0.1)
    assert schlaf.letzter() is not None and "7c_inhalt" in schlaf.letzter().daten["schritte"]


def _schlaf_pruefen(halt, t0):
    a = werkzeuge.rufe("vi_schlaf", {"jetzt": True}, "a", True)
    assert "läuft noch" in a and time.monotonic() - t0 < 2
    assert "läuft bereits" in werkzeuge.rufe("vi_schlaf", {"jetzt": True}, "a", True)
    with pytest.raises(schlaf.LaeuftBereits):
        schlaf.lauf("Loop")
