"""Block 1: Gedächtnis, Sitzungen, Reflexe, Intuition — ohne Netz."""
import os
import stat
import threading

import pytest

from vi_mcp import gedaechtnis as g
from vi_mcp import intuition, reflexe, sitzung


def test_filter_lesen():
    assert g.lies_filter("(a:1 OR b:2) c:3 !d:4 wort") == ([["a:1", "b:2"], ["c:3"]], ["d:4"], ["wort"])
    assert g.lies_filter("") == ([], [], [])


def test_datei_nur_fuer_eigentuemer(gd):
    g.neues_objekt("erkenntnis", "irgendein Text", ["thema:x"], grund="Test")
    for f in (gd, gd.with_name("vi.db-wal")):
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600, f


def test_objekt_grund_pflicht_und_geschichte(gd):
    o = g.neues_objekt("erkenntnis", "Timeout bei host a", ["host:a", "thema:timeout"], grund="Test")
    with pytest.raises(ValueError):
        o.bestaetige("ki", "")
    o.bestaetige("ki", "zweimal gesehen")
    o2 = g.lade(o.id)
    assert o2.bestaetigt == 1 and o2.aenderungen[-1]["grund"] == "zweimal gesehen"
    with pytest.raises(ValueError):
        o2.markiere(["art:x"], [], "ki", "fest")


def test_erinnern_filter_volltext_und_verknuepfung(gd):
    a = g.neues_objekt("erkenntnis", "Disk voll auf web1", ["host:web1", "thema:disk"], grund="T")
    b = g.neues_objekt("erkenntnis", "Disk langsam auf web1", ["host:web1", "thema:disk"], grund="T")
    g.neues_objekt("erkenntnis", "Timeout auf db1", ["host:db1", "thema:timeout"], grund="T")
    ids = [o.id for _, o, _g in g.erinnere("host:web1")]
    assert set(ids) == {a.id, b.id}
    assert [o.id for _, o, _g in g.erinnere("(host:web1 OR host:db1) !thema:disk")][0].startswith("erkenntnis:")
    assert len(g.erinnere("(host:web1 OR host:db1) !thema:disk")) == 1
    assert [o.id for _, o, _g in g.erinnere("langsam")] == [b.id]
    assert (a.id, "2 gemeinsame Hashtags") in b.kanten()
    b.widerlege("ki", "falsch")
    assert [o.id for _, o, _g in g.erinnere("host:web1")] == [a.id]


def test_vertiefen_trichter(gd):
    for i in range(3):
        g.neues_objekt("erkenntnis", f"Fall {i}", ["host:web1", "thema:disk", f"nr:{i}"], grund="T")
    g.neues_objekt("erkenntnis", "anderes", ["host:web1", "thema:netz"], grund="T")
    stufen = g.vertiefe("host:web1")
    assert stufen[0]["naechster"] == "thema:disk"
    assert stufen[1]["filter"] == "host:web1 thema:disk" and stufen[1]["gesamt"] == 3


def test_zugriff_zaehlt_relativ(gd):
    o = g.neues_objekt("erkenntnis", "x y z", ["thema:x"], grund="T")
    kopie = g.lade(o.id)
    o.zugriff()
    kopie.zugriff()  # veralteter Stand im Speicher darf den Zähler nicht zurücksetzen
    assert g.lade(o.id).zugriffe == 2


def test_seriennummern_eindeutig_parallel(gd):
    erg, fehler = [], []

    def lauf():
        try:
            erg.append(sitzung.neue_seriennummer())
        except Exception as e:  # noqa: BLE001
            fehler.append(e)

    th = [threading.Thread(target=lauf) for _ in range(20)]
    [t.start() for t in th]
    [t.join() for t in th]
    assert not fehler and len(set(erg)) == 20


def test_seriennummer_ueber_999(gd):
    tag = sitzung.neue_seriennummer()[:8]
    with g.sperre:
        g.db().execute("INSERT INTO objekt (id, art, zeit, zuletzt) VALUES (?, 'gespraech', '', '')", (f"gespraech:{tag}999",))
        g.db().commit()
    assert sitzung.neue_seriennummer() == f"{tag}1000"
    assert sitzung.neue_seriennummer() == f"{tag}1001"


def test_sitzung_gespraech_und_sichern(gd):
    s = sitzung.beginne("test", "pytest")
    with sitzung.im_auftrag(s):
        v = intuition.vorher("netbox_get_devices", {"host": "Web1"})
        intuition.nachher("netbox_get_devices", v["args"], True, 12, None, "[1,2]", v["vorher_id"])
        o = g.neues_objekt("erkenntnis", "im Gespräch gelernt", ["thema:x"], grund="T")
    assert o.gespraech == s.serial
    assert sitzung.beende(s.id)
    gs = g.lade(f"gespraech:{s.serial}")
    assert gs.daten["aufrufe"] == 1 and gs.daten["zustand"] == "beendet"
    assert {"tool:netbox_get_devices", "host:web1", "instanz:test", "zustand:beendet", "ok:ja"} <= set(gs.hashtags)
    assert sitzung.finde(s.id) is None


def test_gemerkte_antwort_nur_lesend(gd):
    v1 = intuition.vorher("netbox_get_devices", {"q": 1})
    assert v1["antwort"] is None
    intuition.nachher("netbox_get_devices", {"q": 1}, True, 5, None, "ERGEBNIS", v1["vorher_id"])
    v2 = intuition.vorher("netbox_get_devices", {"q": 1})
    assert v2["antwort"] == "ERGEBNIS" and v2["zugriff"]["aus_gedaechtnis"]
    # schreibend: nie aus dem Gedächtnis
    v3 = intuition.vorher("jira_create_ticket", {"q": 1})
    intuition.nachher("jira_create_ticket", {"q": 1}, True, 5, None, "OK", v3["vorher_id"])
    assert intuition.vorher("jira_create_ticket", {"q": 1})["antwort"] is None
    # ausdrückliche Angabe des Clients schlägt das Namensmuster
    v4 = intuition.vorher("Read", {"f": "a"}, ist_lesend=False)
    intuition.nachher("Read", {"f": "a"}, True, 1, None, "inhalt", v4["vorher_id"], ist_lesend=False)
    assert intuition.vorher("Read", {"f": "a"}, ist_lesend=False)["antwort"] is None


def test_erkenntnis_als_hinweis_vorher(gd):
    g.neues_objekt("erkenntnis", "web1 antwortet nur über Proxy", ["host:web1"], {"quelle": "Messung"}, grund="T")
    v = intuition.vorher("checkmk_get_host", {"host": "web1"})
    assert any("nur über Proxy" in h for h in v["hinweise"])


def test_reflex_pruefung():
    assert "nicht erlaubt" in reflexe.pruefe("import os\ndef run(a): return 1", "nachher")
    assert "nicht erlaubt" in reflexe.pruefe("def run(a): return open('x')", "nachher")
    assert "nicht erlaubt" in reflexe.pruefe("def run(a): return ().__class__", "nachher")
    assert "run" in reflexe.pruefe("x = 1", "nachher")
    assert "TOOL" in reflexe.pruefe("def run(a): return 1", "werkzeug")
    assert reflexe.pruefe("import json\ndef run(t, a, e): return json.dumps(a)", "nachher") == ""


def test_reflex_defekt_nach_drei_fehlern(gd):
    g.neues_objekt("reflex", "wirft immer", ["reflex:kaputt", "reflexart:nachher", "modus:test"],
                   {"name": "kaputt", "art": "nachher", "code": "def run(t, a, e):\n    raise ValueError('x')"},
                   oid="reflex:kaputt", modus="test", grund="T")
    reflexe.lade_alle()
    for _ in range(3):
        h = reflexe.nachher("t", {}, "e")
        assert "scheiterte" in h[0]
    assert g.lade("reflex:kaputt").modus == "defekt"
    assert "kaputt" not in reflexe.geladen and reflexe.nachher("t", {}, "e") == []


def test_loop_fehler_wird_regel_und_hinweis(gd):
    from vi_mcp import schleife
    for i in range(3):
        v = intuition.vorher("graylog_search", {"q": i})
        intuition.nachher("graylog_search", {"q": i}, False, 30000, f"TimeoutError: read timed out after {30 + i} s", None, v["vorher_id"])
    assert schleife.schritt() == 1
    assert schleife.schritt() == 0  # idempotent: dieselbe Regel nicht doppelt
    regel = [o for _, o, _g in g.erinnere("art:regel regelart:wiederholter-fehler")][0]
    assert regel.modus == "test" and regel.daten["treffer"] == 3 and regel.gespraech is None
    v = intuition.vorher("graylog_search", {"q": "neu"})
    assert any(h.startswith("Regel [") and "scheiterte 3×" in h for h in v["hinweise"])


def test_vorher_ohne_nachher_verschwindet_nicht(gd):
    s = sitzung.beginne("test", "pytest")
    with sitzung.im_auftrag(s):
        intuition.vorher("netbox_get_vms", {"host": "a"})
    sitzung.beende(s.id)
    e = [o for _, o, _g in g.erinnere("tool:netbox_get_vms ok:unbekannt")]
    assert len(e) == 1 and e[0].gespraech == s.serial and e[0].daten["vorher"]["ohne_nachher"]


def test_instanz_anlegen_behaelt_rechte(tmp_path):
    from vi_mcp import konfig
    p = tmp_path / "config.json"
    konfig.instanz_anlegen("a", p=p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    os.chmod(p, 0o640)
    konfig.instanz_anlegen("b", p=p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o640 and set(konfig.lade(p).instanzen) == {"a", "b"}
