"""Block 0.2.0: Kollektiv — privat/geteilt, Bestätigung über Instanzen, Rückfragen, kollektive Regeln, Migration."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from vi_mcp import fragen, intuition, schleife, sitzung, werkzeuge
from vi_mcp import gedaechtnis as g


@pytest.fixture()
def ab(gd):
    a, b = sitzung.beginne("a", "t"), sitzung.beginne("b", "t")
    return a, b


def als(s, name, args=None):
    with sitzung.im_auftrag(s):
        return werkzeuge.rufe(name, args or {}, s.instanz, True)


def test_privat_und_geteilt(ab):
    a, b = ab
    with sitzung.im_auftrag(a):
        v = intuition.vorher("netbox_get_vms", {"host": "x"}, "a")
        e = intuition.nachher("netbox_get_vms", {"host": "x"}, True, 3, None, "geheim: token=abc", v["vorher_id"], "a")
        k = g.neues_objekt("erkenntnis", "x steht im Rack 4", ["host:x"], {"quelle": "Begehung"}, grund="T")
    assert g.lade(e["erfahrung"]).instanz == "a" and g.lade(e["erfahrung"]).sicht == "privat"
    assert k.instanz == "a" and k.sicht == "geteilt" and "instanz:a" in k.hashtags
    with sitzung.im_auftrag(b):
        assert [o.id for _, o, _g in g.erinnere("host:x")] == [k.id]  # Erkenntnis ja, Erfahrung/Antwort nein
        with pytest.raises(werkzeuge.Abgelehnt, match="unbekannt"):
            werkzeuge.rufe("vi_objekt", {"id": e["erfahrung"]}, "b", True)
    with sitzung.im_auftrag(a):
        assert len(g.erinnere("host:x")) == 2  # eigene Erfahrung + Erkenntnis
        assert len(g.erinnere("art:antwort tool:netbox_get_vms")) == 1  # eigene gemerkte Antwort
    with sitzung.im_auftrag(b):
        assert not g.erinnere("art:antwort tool:netbox_get_vms")  # fremde gemerkte Antwort: unsichtbar
    assert len(g.erinnere("tool:netbox_get_vms", betrachter=None)) == 2  # der Server sieht Erfahrung + Antwort


def test_instanz_hashtag_ist_urheber_nicht_frei(ab):
    a, _ = ab
    with sitzung.im_auftrag(a):
        o = g.neues_objekt("erkenntnis", "versuchte fremde Urheberschaft", ["instanz:b", "thema:t"], {"quelle": "x"}, grund="T")
        assert o.instanz == "a" and "instanz:b" not in o.hashtags
        with pytest.raises(werkzeuge.Abgelehnt, match="Urheber"):
            werkzeuge.rufe("vi_markiere", {"id": o.id, "hinzu": ["instanz:b"], "grund": "x"}, "a", True)


def test_bestaetigung_ueber_instanzen(ab):
    a, b = ab
    with sitzung.im_auftrag(a):
        o = g.neues_objekt("erkenntnis", "Dienst y braucht 2 GB RAM", ["thema:y"], {"quelle": "free -m"}, grund="T")
    w0 = g.erinnere("thema:y", betrachter=None)[0][2]["wichtigkeit"]
    o.bestaetige("ki@a", "nochmal gemessen", "a")  # Selbstbestätigung: zählt, aber kein Bonus
    assert g.lade(o.id).fremde_bestaetigungen() == 0
    w1 = g.erinnere("thema:y", betrachter=None)[0][2]["wichtigkeit"]
    g.lade(o.id).bestaetige("ki@b", "bei mir auch", "b")
    w2 = g.erinnere("thema:y", betrachter=None)[0][2]["wichtigkeit"]
    assert g.lade(o.id).fremde_bestaetigungen() == 1 and w2 - w1 >= g.BONUS_JE_INSTANZ - 0.01 and w1 >= w0
    assert "bestätigt von 1 weiteren" in intuition.vorher("t", {}, "c", kontext=["thema:y"])["hinweise"][0]


def test_widerspruch_strittig_dann_widerlegt(ab):
    with sitzung.im_auftrag(ab[0]):
        o = g.neues_objekt("erkenntnis", "z läuft auf Port 80", ["thema:z"], {"quelle": "ss -ltn"}, grund="T")
    g.lade(o.id).widerlege("ki@b", "bei mir Port 8080", "b")
    assert g.lade(o.id).modus == "strittig"
    # 0.21.1: Strittiges erscheint nicht mehr ungefragt vor Handlungen — benannt mitgezählt, auf Nachfrage weiter auffindbar
    h = intuition.vorher("t", {}, "c", kontext=["thema:z"])["hinweise"]
    assert not any("Port 80" in x for x in h) and any("strittig oder unbestätigte Hypothese, nur auf Nachfrage" in x for x in h)
    assert any(x.id == o.id for _, x, _g in g.erinnere("thema:z", betrachter=None))
    g.lade(o.id).bestaetige("ki@c", "Port 80 gemessen", "c")
    assert g.lade(o.id).modus == "aktiv"  # fremde Bestätigung hebt den Streit auf
    g.lade(o.id).widerlege("ki@d", "Port 8080", "d")
    assert g.lade(o.id).modus == "widerlegt"  # zwei verschiedene widersprechende Instanzen (b, d)
    assert not g.erinnere("thema:z", betrachter=None)
    with sitzung.im_auftrag(ab[0]):
        o2 = g.neues_objekt("erkenntnis", "eigener Irrtum über Port", ["thema:q"], {"quelle": "x"}, grund="T")
    o2.widerlege("ki@a", "selbst falsch", "a")
    assert g.lade(o2.id).modus == "widerlegt"  # der Urheber darf sofort widerlegen


def test_kontext_hashtags_als_reize(gd):
    g.neues_objekt("erkenntnis", "OOM auf web1 kommt vom Java-Heap", ["thema:oom"], {"quelle": "dmesg"}, grund="T")
    assert not intuition.vorher("Bash", {"command": "free"}, "a", False)["hinweise"]
    v = intuition.vorher("Bash", {"command": "free"}, "a", False, kontext=["thema:oom", "keinhashtag", "art:x"])
    assert any("Java-Heap" in h for h in v["hinweise"]) and "thema:oom" in v["zugriff"]["reize"]
    assert "art:x" not in v["zugriff"]["reize"] and "keinhashtag" not in v["zugriff"]["reize"]


def test_rueckfrage_zwischen_instanzen(ab):
    a, b = ab
    r = als(a, "vi_frage", {"an": "b", "text": "Warum ist srv0111 nachts langsam?", "reize": ["host:srv0111"], "quelle": "Graylog"})
    fid = r.split()[1]
    assert g.lade(fid).daten["zustand"] == "offen"
    with pytest.raises(werkzeuge.Abgelehnt):
        als(a, "vi_frage", {"an": "a", "text": "Frage an mich selbst gestellt"})
    hb = intuition.vorher("x", {}, "b")["hinweise"]
    assert any(fid in h and "Rückfrage von a" in h for h in hb)
    assert g.lade(fid).daten["zustand"] == "zugestellt"
    assert not [h for h in intuition.vorher("x", {}, "b")["hinweise"] if "Rückfrage" in h]  # je Instanz nur einmal
    with pytest.raises(werkzeuge.Abgelehnt, match="belege"):
        als(b, "vi_antwort", {"id": fid, "text": "Backup-Job um 2 Uhr", "belege": ""})
    with pytest.raises(werkzeuge.Abgelehnt, match="eigene Frage"):
        als(a, "vi_antwort", {"id": fid, "text": "weiß ich selbst", "belege": "keine Belege"})
    als(b, "vi_antwort", {"id": fid, "text": "Backup-Job um 2 Uhr belegt die Platte", "belege": "crontab -l auf srv0111"})
    ha = intuition.vorher("x", {}, "a")["hinweise"]
    assert any("Antwort von b" in h and "Backup-Job" in h for h in ha)
    assert "beantwortet" in als(a, "vi_fragen") and "Backup-Job" in als(a, "vi_fragen")


def test_rueckfrage_laeuft_ab(ab):
    als(ab[0], "vi_frage", {"an": "alle", "text": "Kennt jemand Host zz9 im Netz?"})
    alt = (datetime.now(timezone.utc) - timedelta(days=fragen.ABLAUF_TAGE + 1)).isoformat(timespec="seconds")
    with g.sperre:
        g.db().execute("UPDATE objekt SET zeit = ? WHERE art = 'frage'", (alt,))
        g.db().commit()
    assert fragen.lass_ablaufen() == 1
    assert "zustand:abgelaufen" in g.erinnere("art:frage", betrachter=None)[0][1].hashtags


def test_kollektive_regel(gd):
    for inst in ("a", "a", "b"):
        v = intuition.vorher("graylog_search", {"q": inst}, inst)
        intuition.nachher("graylog_search", {"q": inst}, False, 1, "ConnectionError: refused 10.0.0.1", None, v["vorher_id"], inst)
    assert schleife.schritt() == 1
    r = g.erinnere("art:regel kollektiv:ja", betrachter=None)[0][1]
    assert r.instanz == g.SERVER_INSTANZ and r.daten["instanzen"] == ["a", "b"] and "bei 2 Instanzen" in r.text


def test_fremder_gespraechsverlauf_bleibt_privat(ab):
    a, b = ab
    with sitzung.im_auftrag(a):
        v = intuition.vorher("t_x", {"passwort": "geheim"}, "a")
        intuition.nachher("t_x", {"passwort": "geheim"}, True, 1, None, "ok", v["vorher_id"], "a")
    sitzung.sichere(a)
    fremd = als(b, "vi_gespraech", {"serial": a.serial})
    assert "Verlauf privat" in fremd and "geheim" not in fremd
    assert "t_x" in als(a, "vi_gespraech", {"serial": a.serial})


def test_migration_von_0_1(tmp_path):
    p = tmp_path / "alt.db"
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE objekt (id TEXT PRIMARY KEY, art TEXT NOT NULL, zeit TEXT NOT NULL, zuletzt TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '', daten TEXT NOT NULL DEFAULT '{}', wichtigkeit INTEGER NOT NULL DEFAULT 1,
            bestaetigt INTEGER NOT NULL DEFAULT 0, widerlegt INTEGER NOT NULL DEFAULT 0, zugriffe INTEGER NOT NULL DEFAULT 0,
            modus TEXT NOT NULL DEFAULT 'aktiv', aenderungen TEXT NOT NULL DEFAULT '[]', gespraech TEXT);
        CREATE TABLE tag (objekt_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (objekt_id, tag));
        INSERT INTO objekt (id, art, zeit, zuletzt, text) VALUES ('erkenntnis:1', 'erkenntnis', '2026-11-08T00:00:00+00:00', '2026-11-08T00:00:00+00:00', 'alt');
        INSERT INTO objekt (id, art, zeit, zuletzt, text) VALUES ('antwort:1', 'antwort', '2026-11-08T00:00:00+00:00', '2026-11-08T00:00:00+00:00', 'a');
        INSERT INTO tag VALUES ('erkenntnis:1', 'instanz:anna'), ('erkenntnis:1', 'art:erkenntnis'), ('antwort:1', 'frage:abc');
    """)
    con.commit()
    con.close()
    g.oeffne(p)
    try:
        e, a = g.lade("erkenntnis:1"), g.lade("antwort:1")
        assert (e.instanz, e.sicht) == ("anna", "geteilt") and (a.instanz, a.sicht) == ("vi", "privat")
        assert "cache:abc" in a.hashtags and not [t for t in a.hashtags if t.startswith("frage:")]
    finally:
        g.schliesse()


def test_verstaerkung_erst_bei_erfolg(gd):
    e = g.neues_objekt("erkenntnis", "web2 braucht Proxy", ["host:web2"], {"quelle": "x"}, grund="T")
    v = intuition.vorher("checkmk_get_host", {"host": "web2"}, "a")
    assert e.id in v["zugriff"]["gefunden"] and g.lade(e.id).zugriffe == 0  # Zeigen allein verstärkt nicht
    n = intuition.nachher("checkmk_get_host", {"host": "web2"}, False, 1, "Timeout", None, v["vorher_id"], "a")
    assert n["verstaerkt"] == 0 and g.lade(e.id).zugriffe == 0  # Misserfolg verstärkt nicht
    v = intuition.vorher("checkmk_get_host", {"host": "web2"}, "a")
    n = intuition.nachher("checkmk_get_host", {"host": "web2"}, True, 1, None, "ok", v["vorher_id"], "a")
    assert n["verstaerkt"] == 1 and g.lade(e.id).zugriffe == 1


def test_hinweisbudget(gd):
    for i in range(7):
        g.neues_objekt("erkenntnis", f"Hinweis {i} zu web3", ["host:web3"], {"quelle": "x"}, grund="T")
    h = intuition.vorher("Bash", {"host": "web3"}, "a", False)["hinweise"]
    assert len(h) == intuition.HINWEIS_BUDGET + 1 and h[-1].startswith("… 3 weitere Treffer") and "vi_vertiefe" in h[-1]


def test_geschichte_kuerzung_benannt(gd):
    o = g.neues_objekt("erkenntnis", "lange Geschichte", ["thema:g"], {"quelle": "x"}, grund="T")
    for i in range(g.GESCHICHTE_MAX + 4):
        o = g.lade(o.id); o.bestaetige("ki@a", f"Grund {i}", "a")
    o = g.lade(o.id)
    assert len(o.aenderungen) == g.GESCHICHTE_MAX and o.daten["aenderungen_gekuerzt"] == 5
    assert "5 ältere Änderungen gekürzt" in werkzeuge.rufe("vi_objekt", {"id": o.id}, "a", True)


def test_ueberraschung_bestimmt_wichtigkeit(gd):
    def fehl(i):
        v = intuition.vorher("graylog_search", {"q": i}, "a")
        return g.lade(intuition.nachher("graylog_search", {"q": i}, False, 1, "ConnectionError: refused 10.0.0.9", None, v["vorher_id"], "a")["erfahrung"])
    stufen = [fehl(i).daten["ueberraschung"]["stufe"] for i in range(5)]
    assert stufen == ["neu", "wiederholt", "wiederholt", "chronisch", "chronisch"]
    assert g.erinnere("ueberraschung:neu", betrachter=None)[0][1].wichtigkeit == 3
    assert g.erinnere("ueberraschung:chronisch", betrachter=None)[0][1].wichtigkeit == 1
    v = intuition.vorher("graylog_search", {"q": "x"}, "a")
    e = g.lade(intuition.nachher("graylog_search", {"q": "x"}, True, 1, None, "ok", v["vorher_id"], "a")["erfahrung"])
    assert e.daten["ueberraschung"]["stufe"] == "erholt" and e.wichtigkeit == 2
    v = intuition.vorher("netbox_get_sites", {}, "a")
    e = g.lade(intuition.nachher("netbox_get_sites", {}, True, 1, None, "ok", v["vorher_id"], "a")["erfahrung"])
    assert e.daten["ueberraschung"]["stufe"] == "keine" and e.wichtigkeit == 0


def test_hinweis_lift_messpunkt(gd):
    from vi_mcp import messung
    g.neues_objekt("erkenntnis", "web9 nur über Proxy", ["host:web9"], {"quelle": "x"}, grund="T")
    for i in range(12):  # mit Hinweis (host:web9) → 10/12 ok
        v = intuition.vorher("checkmk_get_host", {"host": "web9", "i": i}, "a")
        intuition.nachher("checkmk_get_host", {"host": "web9", "i": i}, i < 10, 1, None if i < 10 else "Timeout", "ok" if i < 10 else None, v["vorher_id"], "a")
    for i in range(12):  # ohne Hinweis → 4/12 ok
        v = intuition.vorher("checkmk_get_host", {"host": "web8", "i": i}, "a")
        intuition.nachher("checkmk_get_host", {"host": "web8", "i": i}, i < 4, 1, None if i < 4 else "Timeout", "ok" if i < 4 else None, v["vorher_id"], "a")
    l = messung.hinweis_lift(24, betrachter=None)
    assert l["mit"] == {"n": 12, "ok": 10} and l["ohne"] == {"n": 12, "ok": 4} and l["urteil"] == "Hinweise nützen"
    assert "+50 Punkte" in messung.zeile(l)
    assert "zu wenig Daten" in messung.hinweis_lift(24, tool="gibtsnicht", betrachter=None)["urteil"]
    assert "Hinweis-Lift" in werkzeuge.rufe("vi_status", {}, "a", True)


def test_gespraech_loeschen_grabstein(ab):
    a, b = ab
    with sitzung.im_auftrag(a):
        v = intuition.vorher("t_x", {"passwort": "geheim123"}, "a")
        e = intuition.nachher("t_x", {"passwort": "geheim123"}, True, 1, None, "geheimes Ergebnis", v["vorher_id"], "a")["erfahrung"]
        k = g.neues_objekt("erkenntnis", "aus dem Gespräch gelernt", ["thema:l"], {"quelle": "x"}, grund="T")
    with pytest.raises(werkzeuge.Abgelehnt, match="noch offen"):
        als(a, "vi_loesche_gespraech", {"serial": a.serial, "grund": "Test"})
    sitzung.beende(a.id)
    with pytest.raises(werkzeuge.Abgelehnt, match="gehört Instanz a"):
        als(b, "vi_loesche_gespraech", {"serial": a.serial, "grund": "fremd"})
    r = als(a, "vi_loesche_gespraech", {"serial": a.serial, "grund": "Zugangsdaten im Verlauf"})
    assert "2 private Objekte" in r
    assert g.lade(e) is None and g.lade(k.id) is not None  # privat weg, geteiltes Wissen bleibt
    with g.sperre:
        assert g.db().execute("SELECT COUNT(*) FROM gespraech_roh WHERE serial = ?", (a.serial,)).fetchone()[0] == 0
        assert g.db().execute("SELECT COUNT(*) FROM kante WHERE a = ? OR b = ?", (e, e)).fetchone()[0] == 0
    gs = g.lade(f"gespraech:{a.serial}")
    assert gs.daten["zustand"] == "geloescht" and gs.daten["geloescht"]["objekte"] == 2 and "zustand:geloescht" in gs.hashtags
    assert "geheim" not in gs.text and "Zugangsdaten im Verlauf" in gs.text
    with pytest.raises(werkzeuge.Abgelehnt, match="bereits gelöscht"):
        als(a, "vi_loesche_gespraech", {"serial": a.serial, "grund": "nochmal"})
    sitzung.beende(b.id)
    r = sitzung.loesche_instanz_daten("b", "Admin: Instanz aufgelöst")  # Admin-Weg (CLI): alle Gespräche → Grabsteine
    assert r["gespraeche"] == 1 and g.lade(f"gespraech:{b.serial}").daten["zustand"] == "geloescht"



def test_sprachmodell_hypothese_erst_nach_fremder_bestaetigung_als_hinweis(gd):
    """0.21.1: Eine unbestätigte Schlaf-Hypothese war der meistgezeigte Hinweis (719×). Erst eine fremde Bestätigung macht sie zum Hinweis."""
    o = g.neues_objekt("erkenntnis", "Auf Host web4 deuten Latenzen auf Instabilität hin", ["host:web4", "herkunft:schlaf-llm"],
                       {"quelle": "Schlaf-Reflexion"}, grund="T", instanz="vi")
    assert not any("web4 deuten" in x for x in intuition.vorher("Bash", {"command": "ssh web4 uptime"}, "a")["hinweise"])
    g.lade(o.id).bestaetige("ki@b", "Latenz selbst gemessen", "b")
    assert any("web4 deuten" in x for x in intuition.vorher("Bash", {"command": "ssh web4 uptime"}, "a")["hinweise"])
