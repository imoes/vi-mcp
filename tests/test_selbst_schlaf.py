"""0.4.0: Selbst, Schlaf (Konsolidierung), Archiv, Potenzgesetz-Verfall."""
from datetime import datetime, timedelta, timezone

import pytest

from vi_mcp import intuition, schlaf, selbst, sitzung, werkzeuge
from vi_mcp import gedaechtnis as g


def _alter(oid: str, tage: float) -> None:
    z = (datetime.now(timezone.utc) - timedelta(days=tage)).isoformat(timespec="seconds")
    with g.sperre:
        g.db().execute("UPDATE objekt SET zeit = ?, zuletzt = ? WHERE id = ?", (z, z, oid))
        g.db().commit()


_n = iter(range(10_000))


def _erfahrung(tool, host, ok, instanz="a", fehler=None):
    """Eine echte Handlung je Aufruf: eindeutige Argumente, sonst beantwortet der Antwort-Cache ab dem 2. Mal
    aus dem Gedächtnis und zählt eine zweite Erfahrung (gewollt in der VI, hier nicht gewollt)."""
    args = {"host": host, "n": next(_n)}
    v = intuition.vorher(tool, args, instanz)
    return intuition.nachher(tool, args, ok, 1, fehler, "ok" if ok else None, v["vorher_id"], instanz)["erfahrung"]


def test_selbst_kern_und_erzaehlung(gd):
    k = selbst.kern()
    assert k.id == selbst.KERN and k.daten["version"] == 1 and k.instanz == g.SERVER_INSTANZ and k.sicht == "geteilt"
    assert "Selbst v1" in k.daten["erzaehlung"] and "Grenzen:" in k.daten["erzaehlung"]
    assert len(k.daten["erzaehlung"].split()) <= 151
    assert selbst.kern().id == k.id  # idempotent
    assert len(selbst.versionen()) == sum(len(v) for v in selbst.STANDARD_SOLL.values())


def test_selbst_vorschlag_braucht_belege_und_fremde_vertraute_instanz(gd):
    a, b, c = sitzung.beginne("a", "t"), sitzung.beginne("b", "t"), sitzung.beginne("c", "t")
    belege = []
    for i in range(3):
        o = g.neues_objekt("erkenntnis", f"Beleg {i} für Vorsicht bei Nachtarbeit", ["thema:nacht"], {"quelle": "x"}, grund="T")
        belege.append(o.id)
    with sitzung.im_auftrag(a):
        with pytest.raises(werkzeuge.Abgelehnt, match="mindestens 3 Belege"):
            werkzeuge.rufe("vi_selbst_vorschlag", {"bereich": "werte", "satz": "Nachts keine riskanten Änderungen", "grund": "drei Vorfälle", "belege": belege[:2]}, "a", True)
        with pytest.raises(werkzeuge.Abgelehnt, match="verschiedenen Tagen"):
            werkzeuge.rufe("vi_selbst_vorschlag", {"bereich": "werte", "satz": "Nachts keine riskanten Änderungen", "grund": "drei Vorfälle", "belege": belege}, "a", True)
    _alter(belege[0], 2)
    with sitzung.im_auftrag(a):
        r = werkzeuge.rufe("vi_selbst_vorschlag", {"bereich": "werte", "satz": "Nachts keine riskanten Änderungen", "grund": "drei Vorfälle", "belege": belege}, "a", True)
    vid = r.split()[1]
    assert g.lade(vid).modus == "test" and selbst.kern().daten["version"] == 1
    with sitzung.im_auftrag(a), pytest.raises(werkzeuge.Abgelehnt, match="Selbstbestätigung"):
        werkzeuge.rufe("vi_bestaetige", {"id": vid, "grund": "ich selbst"}, "a", True)
    with sitzung.im_auftrag(b), pytest.raises(werkzeuge.Abgelehnt, match="nicht vertraut"):
        werkzeuge.rufe("vi_bestaetige", {"id": vid, "grund": "finde ich gut"}, "b", False)
    with sitzung.im_auftrag(c):
        r = werkzeuge.rufe("vi_bestaetige", {"id": vid, "grund": "vom Menschen freigegeben"}, "c", True)
    assert "Version 2" in r
    k = selbst.kern()
    assert k.daten["version"] == 2 and any("Nachts keine" in s["satz"] for s in k.daten["soll"]["werte"])
    assert "Nachts keine" in k.daten["erzaehlung"] and g.lade(vid).modus == "aktiv"
    assert selbst.versionen()[0][3] == "werte" and "vom Menschen freigegeben" in selbst.versionen()[0][5]
    assert "Version 2" in werkzeuge.rufe("vi_selbst", {"versionen": True}, "a", True)


def test_selbst_in_initialize_und_wiederholung(gd):
    s = sitzung.beginne("a", "t")
    with sitzung.im_auftrag(s):
        for i in range(selbst.WIEDERHOLUNG_JE - 1):
            assert not any(h.startswith("[Selbst]") for h in intuition.vorher("Bash", {"i": i}, "a", False)["hinweise"])
        assert any(h.startswith("[Selbst]") for h in intuition.vorher("Bash", {}, "a", False)["hinweise"])
    assert selbst.hinweis().startswith("[Selbst] Ich bin die VI")


def test_verfall_potenzgesetz(gd):
    o = g.neues_objekt("erkenntnis", "alt aber wichtig", ["thema:v"], {"quelle": "x"}, grund="T")
    assert g.erinnere("thema:v", betrachter=None)[0][2]["aktualitaet"] == 1.0
    _alter(o.id, 30)
    a30 = g.erinnere("thema:v", betrachter=None)[0][2]["aktualitaet"]
    assert 0.12 < a30 < 0.16  # (1+720)^-0.3 ≈ 0.139; exponentiell wären es 0,03
    _alter(o.id, 365)
    assert g.erinnere("thema:v", betrachter=None)[0][2]["aktualitaet"] > 0.06


def test_schlaf_abstraktion_schema_konflikt_und_bericht(gd):
    # Cluster (host:web5, skill:checkmk): 4 Handlungen an 2 Tagen, alle ok → Erkenntnis (test) mit Belegkanten
    ids = [_erfahrung("checkmk_get_host", "web5", True) for _ in range(4)]
    _alter(ids[0], 1); _alter(ids[1], 1)
    assert schlaf.faellig(datetime(2026, 11, 9, 3, 5, tzinfo=timezone.utc)) == "Nachtlauf 03:00 UTC (kein Schlaf in 24 h)"
    assert schlaf.faellig(datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)) is None  # Wichtigkeit 0, keine Nacht
    b = schlaf.lauf("Test")
    assert b.art == "schlaf" and "zustand:fertig" in b.hashtags and b.daten["schritte"]["4_abstraktion"] == 1
    e = [o for _, o, _g in g.erinnere("herkunft:schlaf", betrachter=None)][0]
    assert e.modus == "test" and e.daten["ausgang"] == "gut" and "web5" in e.text and len(e.kanten()) == 4
    assert b.text.startswith("Schlaf fertig") and schlaf.letzter().id == b.id
    # zweiter Lauf, derselbe Cluster mit gegenteiligem Ausgang → Konflikt, keine stille Änderung
    for _ in range(3):
        _erfahrung("checkmk_get_host", "web5", False, fehler="Timeout: 30 s")
    b2 = schlaf.lauf("Test 2")
    assert b2.daten["schritte"]["3_schema"]["konflikte"] == 1 and b2.daten["schritte"]["4_abstraktion"] == 0
    e = g.lade(e.id)
    assert "konflikt:offen" in e.hashtags and e.modus == "test" and e.daten["konflikte"][0]["ausgang"] == "schlecht"
    # Schlaf-Bestätigung zählt nicht als fremde Instanz
    assert e.fremde_bestaetigungen() == 0
    assert "Schlaf fertig" in werkzeuge.rufe("vi_status", {}, "a", True)
    assert "Konflikte" in werkzeuge.rufe("vi_schlaf", {}, "a", True)
    with pytest.raises(werkzeuge.Abgelehnt, match="nicht vertraut"):
        werkzeuge.rufe("vi_schlaf", {"jetzt": True}, "b", False)


def test_schlaf_selbst_ist(gd):
    for i in range(5):
        _erfahrung("netbox_get_vms", "h9", i < 4)
    schlaf.lauf("Test")
    ist = selbst.kern().daten["ist"]
    assert ist["kompetenz"][0] == {"bereich": "skill:netbox", "erfahrungen": 5, "erfolgsquote": 0.8, "zeitraum": "30 d"}
    assert "Erfahren in: skill:netbox (5 Handlungen, 80 % ok, 30 d)" in selbst.kern().daten["erzaehlung"]


def test_nachtlauf_nur_wenn_24_h_kein_schlaf(gd):
    """0.20.3: Ein Schlaf am selben Kalendertag (00:28) ließ den Nachtlauf still ausfallen; jetzt ist der Nachtlauf Sicherheitsnetz für ruhige Tage."""
    b = schlaf.lauf("Wichtigkeit")
    jetzt = datetime.fromisoformat(b.zeit)
    um_drei = jetzt.replace(hour=3, minute=5) if jetzt.hour >= 3 else jetzt.replace(hour=3, minute=5)
    assert schlaf.faellig(um_drei + timedelta(days=0 if um_drei > jetzt else 1)) is None  # Schlaf liegt < 24 h zurück
    assert schlaf.faellig(um_drei + timedelta(days=2)).startswith("Nachtlauf")       # > 24 h ohne Schlaf
