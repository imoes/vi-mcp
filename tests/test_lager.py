"""0.10.0: Housekeeping — Langzeitlager in eigener Datei, Stummel, Rückholung, Löschen, Beleg-Schutz."""
import json
import os
import stat
import zlib
from datetime import datetime, timedelta, timezone

import pytest

from vi_mcp import intuition, lager, schlaf, sitzung, werkzeuge
from vi_mcp import gedaechtnis as g

_n = iter(range(10_000))


def _alter(oid, tage):
    z = (datetime.now(timezone.utc) - timedelta(days=tage)).isoformat(timespec="milliseconds")
    with g.sperre:
        g.db().execute("UPDATE objekt SET zeit = ?, zuletzt = ? WHERE id = ?", (z, z, oid))
        g.db().commit()


def _erf(host, ok=True):
    args = {"host": host, "n": next(_n)}
    v = intuition.vorher("netbox_get_sites", args, "a")
    return intuition.nachher("netbox_get_sites", args, ok, 1, None if ok else "Fehler", "ok" if ok else None, v["vorher_id"], "a")["erfahrung"]


def _wissen(text, tags, art="erkenntnis", instanz="a"):
    return g.neues_objekt(art, text, tags, {"quelle": "Test"}, grund="T", instanz=instanz)


def test_alte_erfahrung_ins_lager_mit_stummel(gd):
    alt, jung = _erf("h1"), _erf("h3")
    _alter(alt, lager.TAGE["erfahrung"] + 1)
    b = schlaf.lauf("Test").daten["schritte"]["5_lager"]
    assert b["eingelagert"] == 1 and b["je_art"] == {"erfahrung": 1}
    s = g.lade(alt)
    assert s.modus == "archiviert" and "modus:archiviert" in s.hashtags and s.daten["lager"] and "args" not in s.daten
    assert g.lade(jung).modus == "aktiv"
    assert stat.S_IMODE(os.stat(g.lager_pfad).st_mode) == 0o600 and g.lager_pfad != gd
    assert not [o for _, o, _g in g.erinnere("host:h1", betrachter=None)]  # nicht im Vordergrund
    assert [o.id for _, o, _g in g.erinnere("host:h1 modus:archiviert", betrachter=None)] == [alt]  # aber auffindbar
    assert lager.inhalt(alt)["daten"]["args"]["host"] == "h1"
    assert schlaf.lauf("Test 2").daten["schritte"]["5_lager"]["eingelagert"] == 0  # idempotent


def test_nur_echte_belege_schuetzen(gd):
    k = _wissen("h2 ist relevant", ["host:h2"])
    beleg, erinnert = _erf("h2"), _erf("h2")
    g.lade(beleg).verknuepfe(k.id, "Beleg (Schlaf: Abstraktion)")
    assert any("vor der Handlung erinnert" in gr for b, gr in g.lade(erinnert).kanten() if b == k.id)
    for e in (beleg, erinnert):
        _alter(e, lager.TAGE["erfahrung"] + 1)
    lager.aufraeumen()
    assert g.lade(beleg).modus == "aktiv" and g.lade(erinnert).modus == "archiviert"


def test_wissen_erst_nach_langer_nichtnutzung(gd):
    alt = _wissen("selten gebrauchtes Wissen zu h4", ["host:h4"])
    genutzt = _wissen("gezeigtes Wissen zu h5", ["host:h5"])
    frisch = _wissen("neues Wissen zu h6", ["host:h6"])
    _alter(alt.id, lager.TAGE["erkenntnis"] + 1)
    _alter(genutzt.id, lager.TAGE["erkenntnis"] + 1)
    _alter(frisch.id, lager.TAGE["erkenntnis"] - 1)
    v = intuition.vorher("Bash", {"host": "h5"}, "a", False)  # gezeigt und bewertet → gilt als verwendet
    intuition.nachher("Bash", {"host": "h5"}, False, 1, "x", None, v["vorher_id"], "a", False)
    assert lager.aufraeumen()["je_art"] == {"erkenntnis": 1}
    assert g.lade(alt.id).modus == "archiviert" and g.lade(genutzt.id).modus == "aktiv" and g.lade(frisch.id).modus == "aktiv"


def test_nie_automatisch(gd):
    ids = []
    for art, tags in (("reflex", ["reflex:r"]), ("frage", ["an:b"]), ("modell", ["modell:m"])):
        d = {"name": "r", "art": "nachher", "code": "def run(t, a, e):\n    return None"} if art == "reflex" else {"von": "a", "an": "b", "zustand": "offen", "zugestellt_an": [], "antworten": []}
        o = g.neues_objekt(art, "bleibt im aktiven Speicher", tags, d, grund="T")
        _alter(o.id, 2000)
        ids.append(o.id)
    assert lager.aufraeumen()["eingelagert"] == 0 and all(g.lade(i).modus != "archiviert" for i in ids)


def test_vorher_nennt_gelagertes_und_rueckholung(gd):
    k = _wissen("cue9 braucht beim Neustart den Proxy", ["host:cue9"])
    bandit_vorher = k.daten
    _alter(k.id, lager.TAGE["erkenntnis"] + 1)
    lager.aufraeumen()
    h = intuition.vorher("Bash", {"host": "cue9"}, "b", False)["hinweise"]
    assert len(h) == 1 and h[0].startswith("Im Langzeitlager passen:") and k.id in h[0]
    assert "1 Einträge" in werkzeuge.rufe("vi_lager", {}, "a", True) and "Proxy" in werkzeuge.rufe("vi_lager", {"id": k.id}, "a", True)
    with pytest.raises(werkzeuge.Abgelehnt, match="Grund"):
        werkzeuge.rufe("vi_lager_hole", {"id": k.id, "grund": ""}, "a", True)
    assert "zurück" in werkzeuge.rufe("vi_lager_hole", {"id": k.id, "grund": "wird wieder gebraucht"}, "b", True)
    o = g.lade(k.id)
    assert o.modus == "aktiv" and o.text == "cue9 braucht beim Neustart den Proxy" and o.daten == bandit_vorher and "modus:archiviert" not in o.hashtags
    assert lager.inhalt(k.id) is None
    assert any("Proxy" in x for x in intuition.vorher("Bash", {"host": "cue9"}, "b", False)["hinweise"])
    with pytest.raises(werkzeuge.Abgelehnt, match="nicht im Langzeitlager"):
        werkzeuge.rufe("vi_lager_hole", {"id": k.id, "grund": "nochmal"}, "b", True)


def test_privates_bleibt_privat_und_loeschen_wirkt_im_lager(gd):
    a, b = sitzung.beginne("a", "t"), sitzung.beginne("b", "t")
    with sitzung.im_auftrag(a):
        v = intuition.vorher("t_x", {"host": "p1"}, "a")
        e = intuition.nachher("t_x", {"host": "p1"}, True, 1, None, "ok", v["vorher_id"], "a")["erfahrung"]
    sitzung.beende(a.id)
    _alter(e, lager.TAGE["erfahrung"] + 1)
    _alter(f"gespraech:{a.serial}", lager.TAGE_ROH + 1)
    r = lager.aufraeumen()
    assert r["rohverlaeufe"] == 1 and g.lade(e).modus == "archiviert"
    with g.sperre:
        assert g.db().execute("SELECT COUNT(*) FROM gespraech_roh WHERE serial = ?", (a.serial,)).fetchone()[0] == 0
    assert "t_x" in werkzeuge.rufe("vi_gespraech", {"serial": a.serial}, "a", True)  # Verlauf kommt aus dem Lager
    with sitzung.im_auftrag(b), pytest.raises(werkzeuge.Abgelehnt, match="unbekannt"):
        werkzeuge.rufe("vi_lager", {"id": e}, "b", True)
    with sitzung.im_auftrag(b), pytest.raises(werkzeuge.Abgelehnt, match="unbekannt"):
        werkzeuge.rufe("vi_lager_hole", {"id": e, "grund": "fremd"}, "b", True)
    werkzeuge.rufe("vi_loesche_gespraech", {"serial": a.serial, "grund": "Datenschutz"}, "a", True)
    assert g.lade(e) is None and lager.inhalt(e) is None and lager.roh(a.serial) is None
    sitzung.beende(b.id)


def test_offenes_gespraech_bleibt(gd):
    s = sitzung.beginne("a", "t")
    with sitzung.im_auftrag(s):
        v = intuition.vorher("t_y", {}, "a")
        intuition.nachher("t_y", {}, True, 1, None, "ok", v["vorher_id"], "a")
    sitzung.sichere(s)
    _alter(f"gespraech:{s.serial}", lager.TAGE_ROH + 1)
    assert lager.aufraeumen()["rohverlaeufe"] == 0


def test_verdichten_und_status(gd):
    ids = [_wissen("x" * 5000 + str(i), [f"thema:t{i}"]).id for i in range(40)]
    for i in ids:
        _alter(i, lager.TAGE["erkenntnis"] + 1)
    r = lager.aufraeumen()
    assert r["eingelagert"] == 40 and r["verdichtet"] is True
    assert len(lager.inhalt(ids[0])["text"]) > 5000 and len(g.lade(ids[0]).text) == lager.STUMMEL_ZEICHEN
    assert "Langzeitlager: 40 Einträge" in werkzeuge.rufe("vi_status", {}, "a", True)


def test_absturz_zwischen_den_dateien_verliert_nichts(gd):
    k = _wissen("überlebt den Absturz", ["thema:a"])
    with g.sperre:
        lager.db().execute("INSERT INTO objekt (id, art, instanz, sicht, eingelagert, modus_vorher, grund, roh) VALUES (?,?,?,?,?,?,?,?)",
                           (k.id, k.art, k.instanz, k.sicht, g.jetzt(), "aktiv", "Absturztest", zlib.compress(json.dumps({"text": "alt", "daten": {}, "hashtags": []}).encode())))
        lager.db().commit()
    assert g.lade(k.id).modus == "aktiv"  # Quelle unverändert
    lager.einlagern(g.lade(k.id), "Wiederholung")  # nächster Lauf überschreibt die Dublette
    assert lager.inhalt(k.id)["text"] == "überlebt den Absturz"


def test_beleg_ersetzt_automatische_kante_nicht_umgekehrt(gd):
    a = _wissen("Objekt A zu h8", ["host:h8"])
    b = _wissen("Objekt B zu h9", ["host:h9"])
    a.verknuepfe(b.id, "vor der Handlung erinnert")
    a.verknuepfe(b.id, "Beleg (Test)")
    a.verknuepfe(b.id, "2 gemeinsame Hashtags")
    assert a.kanten() == [(b.id, "Beleg (Test)")]


def test_lerne_mit_ausgang(gd):
    r = werkzeuge.rufe("vi_lerne", {"text": "web7 ist nachts gestört", "hashtags": ["host:web7"], "quelle": "Befund 4711", "ausgang": "schlecht"}, "a", True)
    assert g.lade(r.split()[1]).daten["ausgang"] == "schlecht"
    with pytest.raises(werkzeuge.Abgelehnt, match="ausgang"):
        werkzeuge.rufe("vi_lerne", {"text": "web7 ist nachts gestört", "hashtags": ["host:web7"], "quelle": "Befund 4711", "ausgang": "egal"}, "a", True)
