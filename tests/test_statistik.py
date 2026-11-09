"""0.21.0: Nutzungsstatistik — Aufrufe der VI-Werkzeuge, Regeln, Hinweise, Wissen, Suche, Aufräumen."""
from vi_mcp import intuition, usage_stats, tools
from vi_mcp import memory as g


def _action(tool, args, ok, instance):
    v = intuition.before(tool, args, instance)
    intuition.after(tool, args, ok, 5, None if ok else "Fehler: x", "ok" if ok else None, v["vorher_id"], instance)


def test_shell_commands_classified_by_effect():
    assert usage_stats.mutating("Bash", {"command": "sudo systemctl restart nginx"})
    assert usage_stats.mutating("Bash", {"command": "ssh web1 'apt-get install -y curl'"})
    assert usage_stats.mutating("Bash", {"command": "ansible-playbook site.yml -l web1"})
    assert not usage_stats.mutating("Bash", {"command": "ansible-playbook site.yml --check -l web1"})
    assert not usage_stats.mutating("Bash", {"command": "grep -n foo datei.txt | head"})
    assert usage_stats.mutating("Write", {"file_path": "/tmp/x"}) and not usage_stats.mutating("Read", {"file_path": "/tmp/x"})


def test_usage_stats_count_calls_rules_and_searches(gd):
    g.new_object("erkenntnis", "nginx auf web1 vor Neustart mit nginx -t prüfen", ["host:web1", "thema:nginx"], {"quelle": "x"}, reason="T")
    # Instanz a sucht vorher, Instanz b nicht
    text = tools.call_tool("vi_erinnere", {"filter": "nginx"}, "a", True)
    usage_stats.record("a", "claude-code", "vi_recall", "ok", 12, text)
    usage_stats.record("a", "claude-code", "vi_recall", "ok", 9, "0 Objekte zu „gibtsnicht“")
    usage_stats.record("b", "codex", "vi_learn", "abgelehnt", 3)
    _action("Bash", {"command": "sudo systemctl restart nginx"}, True, "a")
    _action("Bash", {"command": "sudo systemctl restart nginx"}, False, "b")
    _action("Bash", {"command": "ls -la"}, True, "b")
    d = usage_stats.data(1)
    assert d["nutzung"]["je_werkzeug"]["vi_recall"]["n"] == 2 and d["nutzung"]["je_werkzeug"]["vi_learn"]["abgelehnt"] == 1
    assert d["nutzung"]["clients"] == ["claude-code", "codex"]
    assert d["regeln"]["aendernd"] == 2 and d["regeln"]["vorbereitet"] == 1  # nur a hat vorher gesucht; ls zählt nicht als Änderung
    assert d["suche"]["n"] == 2 and d["suche"]["ohne_treffer"] == 1
    b = tools.call_tool("vi_stats", {"days": 1}, "a", True)
    for part in ("A Nutzung", "B Regeln", "C Hinweise", "D Wissen", "E Suche", "F Aufräumen", "1 von 2"):
        assert part in b, part


def test_cleanup_deletes_old_entries(gd):
    usage_stats.record("a", None, "vi_status", "ok", 1)
    with g.lock:
        g.db().execute("UPDATE nutzung SET zeit = '2020-01-01T00:00:00+00:00'")
    assert usage_stats.cleanup() == 1
