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


def test_zu_grosse_daten_bleiben_lesbar(gd):
    o = g.neues_objekt("erkenntnis", "viel Inhalt hier", ["thema:gross"], {"blob": "x" * (g.DATEN_MAX + 10)}, grund="T")
    d = g.lade(o.id).daten
    assert d["gekuerzt_zeichen"] > g.DATEN_MAX and "blob" not in d


def test_vollstaendiges_wissen_bleibt_erhalten(gd):
    """Code und API-Tabellen gehören ins Gedächtnis: nichts wird gekürzt, alles wird gefunden und wieder gelesen."""
    from vi_mcp import werkzeuge
    tabelle = "| GET | /api/hosts | Liste |\n" * 2000 + "\ndef baue_abfrage(token = lese_token()):\n    return Zaunkoenig(token)\n"
    r = werkzeuge.rufe("vi_lerne", {"text": "Die Hosts-API liefert Listen", "inhalt": tabelle, "hashtags": ["thema:api"], "quelle": "Handbuch Kapitel 3"}, "a", False)
    oid = next(w.strip("[]") for w in r.split() if w.startswith(("[erkenntnis:", "erkenntnis:")))
    voll = next(o for _, o, _g in g.erinnere("thema:api", betrachter=None))
    assert voll.daten["inhalt"] == tabelle.strip() and len(voll.text) < 100
    assert voll.id.startswith(oid[:20])
    assert tabelle.strip() in werkzeuge.rufe("vi_objekt", {"id": voll.id}, "a", False)
    assert [o.id for _, o, _g in g.erinnere("Zaunkoenig", betrachter=None)] == [voll.id]  # auch am Ende langer Texte gefunden


def test_zu_langer_text_wird_nicht_abgeschnitten(gd):
    from vi_mcp import werkzeuge
    lang = "Satz über die API. " * 200
    werkzeuge.rufe("vi_lerne", {"text": lang, "hashtags": ["thema:lang"], "quelle": "Handbuch Kapitel 3"}, "a", False)
    o = next(o for _, o, _g in g.erinnere("thema:lang", betrachter=None))
    assert o.daten["inhalt"] == lang.strip() and len(o.text) == werkzeuge.TEXT_MAX


def test_zu_grosser_inhalt_wird_mit_grund_abgelehnt(gd):
    from vi_mcp import werkzeuge
    with pytest.raises(werkzeuge.Abgelehnt, match="aufteilen"):
        werkzeuge.rufe("vi_lerne", {"text": "Eine Kernaussage hier", "inhalt": "x" * (g.INHALT_MAX + 1), "hashtags": ["thema:a"], "quelle": "Handbuch Kapitel 3"}, "a", False)


def test_skill_anleitung_bleibt_vollstaendig(gd):
    from vi_mcp import skills
    lang = "Schritt mit Befehl und Erklärung. " * 100
    o = skills.neu("langer weg", ["tool:x"], ["Bash"], lang, "weil gelöst", [], "a")
    assert o.daten["inhalt"] == lang.strip() and len(o.text) == 600


@pytest.mark.parametrize("kommando,erwartet", [
    ("vzdump 101 --mode snapshot", {"skill:proxmox", "thema:vzdump"}),
    ("ssh root@pve1.example 'qm list && pct list'", {"thema:ssh", "skill:proxmox", "thema:qm", "thema:pct", "host:pve1.example"}),
    # 0.19.4: jeder fachliche Befehl wird thema:, Shell-Alltag nicht; Argumente in Anführungszeichen sind keine Befehle
    ("sudo ipa-client-install --domain example.org", {"thema:ipa-client-install"}),
    ("ssh gpu1.example 'llama-server -m m.gguf --load-mode mlock'", {"thema:ssh", "thema:llama-server", "host:gpu1.example"}),
    ('sudo -u postgres psql -c "select 1"', {"skill:postgres", "thema:psql"}),
    ("grep 'vzdump' job.log && qm list", {"thema:grep", "skill:proxmox", "thema:qm"}),
    ("sudo sh -c 'apt-get update; pip3 install ansible'", {"thema:apt-get", "thema:pip3"}),
    ("ansible-playbook site.yml -l web1.example,web2.example", {"skill:ansible", "thema:ansible-playbook", "host:web1.example", "host:web2.example"}),
    ("ansible-playbook site.yml --limit 'sites_a:!zeit1.example'", {"skill:ansible", "thema:ansible-playbook"}),
    ('echo "a; qm b" | tee x', set()),
    # 0.20.2: Werkzeuge mit Fallstricken sind Reize, reiner Alltag nicht
    ('cd /tmp/x && pkill -f "python3 worker.py"; sleep 2', {"thema:pkill"}),
    ("find . -name '*.tmp' -exec rm {} +", {"thema:find"}),
    ("timeout 300 ssh web1.example 'vzdump 101'", {"thema:ssh", "host:web1.example", "skill:proxmox", "thema:vzdump"}),
    ("setsid nohup nice -n 10 pg_dump app", {"skill:postgres", "thema:pg_dump"}),
    # 0.20.1: Code in Anführungszeichen innerhalb eines ssh-Befehls ist kein Befehl
    ("""ssh web1.example 'curl -s http://x/slots | python3 -c "import json,sys; d=json.load(sys.stdin); print([s for s in d])"; top -bn1'""",
     {"thema:ssh", "thema:curl", "thema:top", "host:web1.example"}),
    ("""ssh web1.example 'sudo sh -c "apt-get update; qm list"'""", {"thema:ssh", "host:web1.example", "thema:apt-get", "skill:proxmox", "thema:qm"}),
    ("sudo -u postgres pg_dump app > /tmp/a.sql", {"skill:postgres", "thema:pg_dump"}),
    ("cd x; ansible-playbook -i hosts site.yml", {"skill:ansible", "thema:ansible-playbook"}),
    ("docker compose up -d", {"skill:docker", "thema:docker"}),
    ("echo qm ist kein Befehl hier | grep x", {"thema:grep"}),
    ("ls -la /var/log/qm", set()),
])
def test_befehle_werden_reize(kommando, erwartet):
    assert set(intuition.befehls_reize(kommando)) == erwartet


def test_shell_reize_nur_bei_shell(gd):
    assert "skill:proxmox" in intuition.reize("Bash", {"command": "vzdump 1"})
    assert "skill:proxmox" not in intuition.reize("netbox_get_vms", {"command": "vzdump 1"})


def test_angezeigte_ids_sind_nachschlagbar(gd):
    from vi_mcp import werkzeuge
    werkzeuge.rufe("vi_lerne", {"text": "Eine Erkenntnis zum Nachschlagen hier", "hashtags": ["thema:id"], "quelle": "Test 8.11."}, "a", False)
    liste = werkzeuge.rufe("vi_erinnere", {"filter": "thema:id"}, "a", False)
    oid = liste.split("[", 1)[1].split("]", 1)[0]
    assert "Nachschlagen" in werkzeuge.rufe("vi_objekt", {"id": oid}, "a", False)
    assert "Nachschlagen" in werkzeuge.rufe("vi_objekt", {"id": oid[:20]}, "a", False)  # gekürzt aus älteren Ausgaben
    with pytest.raises(werkzeuge.Abgelehnt):
        werkzeuge.rufe("vi_objekt", {"id": "erkenntnis:%"}, "a", False)


def test_passende_warnung_schlaegt_allgemeines(gd):
    from vi_mcp import werkzeuge
    for i in range(10):
        werkzeuge.rufe("vi_lerne", {"text": f"Allgemeine Ansible-Notiz Nummer {i} mit Inhalt", "hashtags": ["skill:ansible"], "quelle": "Doku 8.11."}, "a", False)
    werkzeuge.rufe("vi_lerne", {"text": "freeipa-client nie auf zeit1 laufen lassen", "hashtags": ["skill:ansible", "thema:ansible-playbook", "host:zeit1"],
                                "quelle": "Vorfall 13.10.", "wichtigkeit": 3}, "a", False)
    v = intuition.vorher("Bash", {"command": "ansible-playbook playbooks/freeipa-client.yml -l sites"}, "a", False)
    assert "zeit1" in v["hinweise"][0] or any("zeit1" in h for h in v["hinweise"][:2])


def test_handbuch_absaetze_verdraengen_keine_erfahrung(gd):
    """0.19.3: vor `docker logs` belegten vier Docker-Doku-Absätze alle Plätze; der passende ssh-Hinweis fiel heraus."""
    from vi_mcp import werkzeuge
    for i in range(6):
        werkzeuge.rufe("vi_lerne", {"text": f"Docker-Doku, Abschnitt {i}: allgemeiner Text", "hashtags": ["skill:docker", "art_wissen:doku-extern"],
                                    "quelle": "Herstellerdoku"}, "a", False)
    werkzeuge.rufe("vi_lerne", {"text": "ssh nach web1 nur mit Schlüssel und BatchMode", "hashtags": ["host:web1.example", "tool:ssh"], "quelle": "Erfahrung"}, "a", False)
    h = intuition.vorher("Bash", {"command": "ssh web1.example 'docker logs nginx'"}, "a", False)["hinweise"]
    assert any("Schlüssel" in x for x in h)
    assert sum("Docker-Doku" in x for x in h) <= intuition.NACHSCHLAG_MAX + 1  # +1: ein Erkundungsplatz darf einen weiteren zeigen
    gesucht = werkzeuge.rufe("vi_erinnere", {"filter": "Docker-Doku"}, "a", False)
    assert gesucht.count("Docker-Doku, Abschnitt") >= 6  # in der Suche bleibt alles


def test_inhaltsleerer_auto_skill_wird_widerlegt(gd):
    from vi_mcp import skills
    o = skills.neu("auto-test1", ["tool:Bash"], ["Bash", "AskUserQuestion", "Write"], "Bash scheiterte und gelang danach im selben Gespräch", "Schlaf", [], g.SERVER_INSTANZ, wer="vi")
    echt = skills.neu("auto-test2", ["tool:Bash"], ["Bash", "netbox_get_vms"], "Bash scheiterte, netbox_get_vms half", "Schlaf", [], g.SERVER_INSTANZ, wer="vi")
    assert skills.inhaltsleer(o) and not skills.inhaltsleer(echt)
    skills.bewerte()
    assert g.lade(o.id).modus == "widerlegt" and g.lade(echt.id).modus != "widerlegt"


def test_fehlendes_pflichtfeld_wird_abgelehnt_statt_still_beantwortet(gd):
    """0.20.4: vi_erinnere mit „text“ statt „filter“ lieferte die wichtigsten Objekte, als wäre gesucht worden."""
    import pytest
    from vi_mcp import werkzeuge
    with pytest.raises(werkzeuge.Abgelehnt, match="Pflichtfeld fehlt: filter — übergeben, aber unbekannt: text"):
        werkzeuge.rufe("vi_erinnere", {"text": "Lizenz Dongle"}, "a", True)
    werkzeuge.rufe("vi_erinnere", {"filter": "Lizenz"}, "a", True)  # richtig benannt: geht
    with pytest.raises(werkzeuge.Abgelehnt, match="Pflichtfeld fehlt: id$"):
        werkzeuge.rufe("vi_objekt", {}, "a", True)


def test_zustandsabhaengige_werkzeuge_werden_nie_gemerkt(gd):
    """0.21.2: browser_wait_for(time=5) bekam die gemerkte Antwort von vor 53 s (andere Seiten-URL), statt zu warten."""
    from vi_mcp import intuition
    for tool in ("browser_wait_for", "browser_snapshot", "browser_take_screenshot", "browser_evaluate", "openclaw_health"):
        assert intuition.zustandsabhaengig(tool), tool
        args = {"time": 5, "n": tool}
        v = intuition.vorher(tool, args, "a", True)
        intuition.nachher(tool, args, True, 5000, None, "Seite geladen: https://x/a", v["vorher_id"], "a", True)
        assert intuition.vorher(tool, args, "a", True)["antwort"] is None, tool
    for tool in ("netbox_get_devices", "checkmk_get_hosts", "Read"):
        assert not intuition.zustandsabhaengig(tool), tool
