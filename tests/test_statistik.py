"""0.21.0: Nutzungsstatistik — Aufrufe der VI-Werkzeuge, Regeln, Hinweise, Wissen, Suche, Aufräumen."""
from vi_mcp import intuition, statistik, werkzeuge
from vi_mcp import gedaechtnis as g


def _handlung(tool, args, ok, instanz):
    v = intuition.vorher(tool, args, instanz)
    intuition.nachher(tool, args, ok, 5, None if ok else "Fehler: x", "ok" if ok else None, v["vorher_id"], instanz)


def test_shell_befehle_werden_nach_wirkung_eingeordnet():
    assert statistik.aendernd("Bash", {"command": "sudo systemctl restart nginx"})
    assert statistik.aendernd("Bash", {"command": "ssh web1 'apt-get install -y curl'"})
    assert statistik.aendernd("Bash", {"command": "ansible-playbook site.yml -l web1"})
    assert not statistik.aendernd("Bash", {"command": "ansible-playbook site.yml --check -l web1"})
    assert not statistik.aendernd("Bash", {"command": "grep -n foo datei.txt | head"})
    assert statistik.aendernd("Write", {"file_path": "/tmp/x"}) and not statistik.aendernd("Read", {"file_path": "/tmp/x"})


def test_statistik_zaehlt_aufrufe_regeln_und_suchen(gd):
    g.neues_objekt("erkenntnis", "nginx auf web1 vor Neustart mit nginx -t prüfen", ["host:web1", "thema:nginx"], {"quelle": "x"}, grund="T")
    # Instanz a sucht vorher, Instanz b nicht
    text = werkzeuge.rufe("vi_erinnere", {"filter": "nginx"}, "a", True)
    statistik.zeichne("a", "claude-code", "vi_erinnere", "ok", 12, text)
    statistik.zeichne("a", "claude-code", "vi_erinnere", "ok", 9, "0 Objekte zu „gibtsnicht“")
    statistik.zeichne("b", "codex", "vi_lerne", "abgelehnt", 3)
    _handlung("Bash", {"command": "sudo systemctl restart nginx"}, True, "a")
    _handlung("Bash", {"command": "sudo systemctl restart nginx"}, False, "b")
    _handlung("Bash", {"command": "ls -la"}, True, "b")
    d = statistik.daten(1)
    assert d["nutzung"]["je_werkzeug"]["vi_erinnere"]["n"] == 2 and d["nutzung"]["je_werkzeug"]["vi_lerne"]["abgelehnt"] == 1
    assert d["nutzung"]["clients"] == ["claude-code", "codex"]
    assert d["regeln"]["aendernd"] == 2 and d["regeln"]["vorbereitet"] == 1  # nur a hat vorher gesucht; ls zählt nicht als Änderung
    assert d["suche"]["n"] == 2 and d["suche"]["ohne_treffer"] == 1
    b = werkzeuge.rufe("vi_statistik", {"tage": 1}, "a", True)
    for teil in ("A Nutzung", "B Regeln", "C Hinweise", "D Wissen", "E Suche", "F Aufräumen", "1 von 2"):
        assert teil in b, teil


def test_aufraeumen_loescht_alte_eintraege(gd):
    statistik.zeichne("a", None, "vi_status", "ok", 1)
    with g.sperre:
        g.db().execute("UPDATE nutzung SET zeit = '2020-01-01T00:00:00+00:00'")
    assert statistik.aufraeumen() == 1
