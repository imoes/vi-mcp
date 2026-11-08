"""0.5.0: Lernen — Beobachtungen, Erkundung, Router-Modell (sklearn optional), Vorhersage ohne sklearn."""
import builtins
import json
import random

import pytest

from vi_mcp import intuition, lernen, schlaf, werkzeuge
from vi_mcp import gedaechtnis as g

try:
    import sklearn  # noqa: F401
    HAT_SKLEARN = True
except ImportError:
    HAT_SKLEARN = False

_n = iter(range(100_000))


def handlung(tool, host, ok, kontext=None, instanz="a"):
    args = {"host": host, "n": next(_n)}
    v = intuition.vorher(tool, args, instanz, kontext=kontext)
    intuition.nachher(tool, args, ok, 1, None if ok else "Fehler: x", "ok" if ok else None, v["vorher_id"], instanz)
    return v


def test_beobachtung_view_und_merkmale(gd):
    g.neues_objekt("erkenntnis", "web1 braucht Proxy", ["host:web1"], {"quelle": "x"}, grund="T")
    handlung("checkmk_get_host", "web1", True, kontext=["thema:oom"])
    handlung("checkmk_get_host", "web2", False)
    with g.sperre:
        rows = g.db().execute("SELECT tool, ok, hinweise_n, ueberraschung, router FROM beobachtung ORDER BY zeit").fetchall()
    assert rows[0][:3] == ("checkmk_get_host", 1, 1) and rows[1][:3] == ("checkmk_get_host", 0, 0) and rows[0][4] == "heuristik"
    b = lernen.beobachtungen()
    assert len(b) == 2  # ein Paar (mit Hinweis) + eine Basis (ohne)
    mit = next(m for m, y, _ in b if y == 1)
    assert "thema:oom" in mit and "hinweisart:erkenntnis" in mit and "hinweis_n:1" in mit and any(k.startswith("hinweis:erkenntnis:") for k in mit)
    ohne = next(m for m, y, _ in b if y == 0)
    assert "hinweis_n:0" in ohne and not any(k.startswith("hinweis:") for k in ohne)
    assert "thema:oom" in g.erinnere("tool:checkmk_get_host ok:ja", betrachter=None)[0][1].hashtags  # Kontext-Reiz ist Tag


def test_erkundung_wird_markiert(gd, monkeypatch):
    for i in range(8):
        g.neues_objekt("erkenntnis", f"Hinweis {i} zu web3", ["host:web3"], {"quelle": "x"}, grund="T")
    monkeypatch.setattr(lernen, "EPSILON", 1.0)
    v = intuition.vorher("Bash", {"host": "web3"}, "a", False)
    assert v["zugriff"]["exploration"] is True and len(v["zugriff"]["gezeigt"]) == intuition.HINWEIS_BUDGET
    assert any("(Erkundung)" in h for h in v["hinweise"]) and len(v["zugriff"]["kandidaten"]) == 8
    assert v["zugriff"]["gezeigt"][-1] not in v["zugriff"]["kandidaten"][:intuition.HINWEIS_BUDGET]
    monkeypatch.setattr(lernen, "EPSILON", 0.0)
    v = intuition.vorher("Bash", {"host": "web3"}, "a", False)
    assert v["zugriff"]["exploration"] is False and v["zugriff"]["router"] == "heuristik"


def test_vorhersage_ohne_sklearn_und_rangfolge(gd):
    m = g.neues_objekt("modell", "Testmodell", ["modell:router"],
                       {"zustand": "aktiv", "gewichte": {"hinweis:regel:gut": 2.0, "hinweis:erkenntnis:schlecht": -2.0, "skill:x": 0.5}, "achsenabschnitt": 0.0},
                       oid=lernen.MODELL, grund="T", instanz=g.SERVER_INSTANZ)
    p = lernen.vorhersage(m, {"skill:x": 1.0, "hinweis:regel:gut": 1.0})
    assert abs(p - 1 / (1 + 2.718281828 ** -2.5)) < 1e-6
    r = lernen.rangfolge(m, ["skill:x"], ["erkenntnis:schlecht", "erkenntnis:neutral", "regel:gut"])
    assert [h for h, _ in r] == ["regel:gut", "erkenntnis:neutral", "erkenntnis:schlecht"] and r[0][1] > 0 > r[2][1]


def test_zu_wenig_daten_und_fehlendes_sklearn(gd, monkeypatch):
    handlung("t_a", "h", True)
    b = lernen.trainiere("Test")
    if HAT_SKLEARN:
        assert b["zustand"] == "zu_wenig_daten" and g.lade(lernen.MODELL).modus == "test" and lernen.aktiv() is None
        assert "zu_wenig_daten" in werkzeuge.rufe("vi_modell", {}, "a", True)
    else:
        assert b["zustand"] == "uebersprungen" and "python3-sklearn" in b["grund"]
    echt = builtins.__import__

    def ohne(name, *a, **k):
        if name.startswith("sklearn"):
            raise ImportError(name="sklearn")
        return echt(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", ohne)
    b = lernen.trainiere("Test")
    assert b["zustand"] == "uebersprungen" and "sklearn" in b["grund"]


@pytest.mark.skipif(not HAT_SKLEARN, reason="scikit-learn nicht installiert (.venv nutzen)")
def test_router_lernt_welcher_hinweis_nuetzt(gd):
    """Synthetik: Hinweis R (Regel) → ok 90 %; Hinweis E (Erkenntnis) → ok 20 %. Jede Handlung bekommt genau einen
    der beiden gezeigt (wie bei Budget 1 / Erkundung). Nach dem Training: Gewicht(R) > 0 > Gewicht(E), R zuerst."""
    random.seed(7)
    r = g.neues_objekt("regel", "vor graylog_search Zeitraum setzen", ["skill:graylog"], {"quelle": "x"}, grund="T")
    e = g.neues_objekt("erkenntnis", "graylog ist immer schnell", ["skill:graylog"], {"quelle": "x"}, grund="T")
    for i in range(400):
        args = {"q": i}
        v = intuition.vorher("graylog_search", args, "a")
        intuition.nachher("graylog_search", args, True, 1, None, "ok", v["vorher_id"], "a")
    with g.sperre:  # „gezeigt“ auf genau einen Hinweis setzen und das Label danach würfeln
        rows = g.db().execute("SELECT id, daten FROM objekt WHERE art = 'erfahrung'").fetchall()
        for i, (oid, daten) in enumerate(rows):
            d = json.loads(daten)
            nur = [r.id] if i % 2 == 0 else [e.id]
            ok_neu = random.random() < (0.9 if nur == [r.id] else 0.2)
            d["vorher"]["gezeigt"] = nur
            g.db().execute("UPDATE objekt SET daten = ? WHERE id = ?", (json.dumps(d), oid))
            g.db().execute("DELETE FROM tag WHERE objekt_id = ? AND tag IN ('ok:ja', 'ok:nein')", (oid,))
            g.db().execute("INSERT INTO tag VALUES (?, ?)", (oid, "ok:ja" if ok_neu else "ok:nein"))
        g.db().commit()
    b = lernen.trainiere("Test")
    assert b["zustand"] == "aktiv", b
    m = lernen.aktiv()
    assert m and m.daten["gewichte"][f"hinweis:{r.id}"] > 0 > m.daten["gewichte"][f"hinweis:{e.id}"]
    rf = lernen.rangfolge(m, ["tool:graylog_search", "skill:graylog"], [e.id, r.id])
    assert rf[0][0] == r.id and rf[0][1] > 0.3
    v = intuition.vorher("graylog_search", {"q": "neu"}, "a")
    assert v["zugriff"]["router"] == "modell" and v["zugriff"]["gezeigt"][0] == r.id
    assert "Router-Modell (aktiv)" in werkzeuge.rufe("vi_modell", {}, "a", True)
    assert schlaf.lauf("Test").daten["schritte"]["8_lernen"]["zustand"] == "aktiv"
