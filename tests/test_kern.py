"""Block 1: memory, sessions, reflexes, intuition — without network."""
import os
import stat
import threading

import pytest

from vi_mcp import memory as g
from vi_mcp import intuition, reflexes, session


def test_parse_filter():
    assert g.parse_filter("(a:1 OR b:2) c:3 !d:4 wort") == ([["a:1", "b:2"], ["c:3"]], ["d:4"], ["wort"])
    assert g.parse_filter("") == ([], [], [])


def test_file_only_for_owner(gd):
    g.new_object("erkenntnis", "irgendein Text", ["thema:x"], reason="Test")
    for f in (gd, gd.with_name("vi.db-wal")):
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600, f


def test_object_reason_required_and_history(gd):
    o = g.new_object("erkenntnis", "Timeout bei host a", ["host:a", "thema:timeout"], reason="Test")
    with pytest.raises(ValueError):
        o.confirm("ki", "")
    o.confirm("ki", "zweimal gesehen")
    o2 = g.load(o.id)
    assert o2.confirmed == 1 and o2.changes[-1]["grund"] == "zweimal gesehen"
    with pytest.raises(ValueError):
        o2.tag(["art:x"], [], "ki", "fest")


def test_recall_filter_fulltext_and_link(gd):
    a = g.new_object("erkenntnis", "Disk voll auf web1", ["host:web1", "thema:disk"], reason="T")
    b = g.new_object("erkenntnis", "Disk langsam auf web1", ["host:web1", "thema:disk"], reason="T")
    g.new_object("erkenntnis", "Timeout auf db1", ["host:db1", "thema:timeout"], reason="T")
    ids = [o.id for _, o, _g in g.recall("host:web1")]
    assert set(ids) == {a.id, b.id}
    assert [o.id for _, o, _g in g.recall("(host:web1 OR host:db1) !thema:disk")][0].startswith("erkenntnis:")
    assert len(g.recall("(host:web1 OR host:db1) !thema:disk")) == 1
    assert [o.id for _, o, _g in g.recall("langsam")] == [b.id]
    assert (a.id, "2 shared hashtags") in b.edges()
    b.refute("ki", "falsch")
    assert [o.id for _, o, _g in g.recall("host:web1")] == [a.id]


def test_drilldown_funnel(gd):
    for i in range(3):
        g.new_object("erkenntnis", f"Fall {i}", ["host:web1", "thema:disk", f"nr:{i}"], reason="T")
    g.new_object("erkenntnis", "anderes", ["host:web1", "thema:netz"], reason="T")
    levels = g.drilldown("host:web1")
    assert levels[0]["naechster"] == "thema:disk"
    assert levels[1]["filter"] == "host:web1 thema:disk" and levels[1]["gesamt"] == 3


def test_access_counts_relatively(gd):
    o = g.new_object("erkenntnis", "x y z", ["thema:x"], reason="T")
    backup_copy = g.load(o.id)
    o.access()
    backup_copy.access()  # a stale state in memory must not reset the counter
    assert g.load(o.id).accesses == 2


def test_serials_unique_in_parallel(gd):
    res, error = [], []

    def run():
        try:
            res.append(session.new_serial())
        except Exception as e:  # noqa: BLE001
            error.append(e)

    th = [threading.Thread(target=run) for _ in range(20)]
    [t.start() for t in th]
    [t.join() for t in th]
    assert not error and len(set(res)) == 20


def test_serial_above_999(gd):
    tag = session.new_serial()[:8]
    with g.lock:
        g.db().execute("INSERT INTO objekt (id, art, zeit, zuletzt) VALUES (?, 'gespraech', '', '')", (f"gespraech:{tag}999",))
        g.db().commit()
    assert session.new_serial() == f"{tag}1000"
    assert session.new_serial() == f"{tag}1001"


def test_session_conversation_and_persist(gd):
    s = session.begin("test", "pytest")
    with session.on_behalf(s):
        v = intuition.before("netbox_get_devices", {"host": "Web1"})
        intuition.after("netbox_get_devices", v["args"], True, 12, None, "[1,2]", v["vorher_id"])
        o = g.new_object("erkenntnis", "im Gespräch gelernt", ["thema:x"], reason="T")
    assert o.conversation == s.serial
    assert session.finish(s.id)
    gs = g.load(f"gespraech:{s.serial}")
    assert gs.data["aufrufe"] == 1 and gs.data["zustand"] == "beendet"
    assert {"tool:netbox_get_devices", "host:web1", "instanz:test", "zustand:beendet", "ok:ja"} <= set(gs.hashtags)
    assert session.find(s.id) is None


def test_remembered_answer_read_only(gd):
    v1 = intuition.before("netbox_get_devices", {"q": 1})
    assert v1["antwort"] is None
    intuition.after("netbox_get_devices", {"q": 1}, True, 5, None, "ERGEBNIS", v1["vorher_id"])
    v2 = intuition.before("netbox_get_devices", {"q": 1})
    assert v2["antwort"] == "ERGEBNIS" and v2["zugriff"]["aus_gedaechtnis"]
    # writing: never from memory
    v3 = intuition.before("jira_create_ticket", {"q": 1})
    intuition.after("jira_create_ticket", {"q": 1}, True, 5, None, "OK", v3["vorher_id"])
    assert intuition.before("jira_create_ticket", {"q": 1})["antwort"] is None
    # the client's explicit statement beats the name pattern
    v4 = intuition.before("Read", {"f": "a"}, is_read_only=False)
    intuition.after("Read", {"f": "a"}, True, 1, None, "inhalt", v4["vorher_id"], is_read_only=False)
    assert intuition.before("Read", {"f": "a"}, is_read_only=False)["antwort"] is None


def test_insight_as_hint_before(gd):
    g.new_object("erkenntnis", "web1 antwortet nur über Proxy", ["host:web1"], {"quelle": "Messung"}, reason="T")
    v = intuition.before("checkmk_get_host", {"host": "web1"})
    assert any("nur über Proxy" in h for h in v["hinweise"])


def test_reflex_checks():
    assert "not allowed" in reflexes.check("import os\ndef run(a): return 1", "nachher")
    assert "not allowed" in reflexes.check("def run(a): return open('x')", "nachher")
    assert "not allowed" in reflexes.check("def run(a): return ().__class__", "nachher")
    assert "run" in reflexes.check("x = 1", "nachher")
    assert "TOOL" in reflexes.check("def run(a): return 1", "werkzeug")
    assert reflexes.check("import json\ndef run(t, a, e): return json.dumps(a)", "nachher") == ""


def test_reflex_defective_after_three_errors(gd):
    g.new_object("reflex", "wirft immer", ["reflex:kaputt", "reflexart:nachher", "modus:test"],
                   {"name": "kaputt", "art": "nachher", "code": "def run(t, a, e):\n    raise ValueError('x')"},
                   oid="reflex:kaputt", mode="test", reason="T")
    reflexes.load_all()
    for _ in range(3):
        h = reflexes.after("t", {}, "e")
        assert "failed" in h[0]
    assert g.load("reflex:kaputt").mode == "defekt"
    assert "kaputt" not in reflexes.loaded and reflexes.after("t", {}, "e") == []


def test_loop_error_becomes_rule_and_hint(gd):
    from vi_mcp import main_loop
    for i in range(3):
        v = intuition.before("graylog_search", {"q": i})
        intuition.after("graylog_search", {"q": i}, False, 30000, f"TimeoutError: read timed out after {30 + i} s", None, v["vorher_id"])
    assert main_loop.step() == 1
    assert main_loop.step() == 0  # idempotent: the same rule not twice
    rule = [o for _, o, _g in g.recall("art:regel regelart:wiederholter-fehler")][0]
    assert rule.mode == "test" and rule.data["treffer"] == 3 and rule.conversation is None
    v = intuition.before("graylog_search", {"q": "neu"})
    assert any(h.startswith("Rule [") and "failed 3×" in h for h in v["hinweise"])


def test_before_without_after_does_not_vanish(gd):
    s = session.begin("test", "pytest")
    with session.on_behalf(s):
        intuition.before("netbox_get_vms", {"host": "a"})
    session.finish(s.id)
    e = [o for _, o, _g in g.recall("tool:netbox_get_vms ok:unbekannt")]
    assert len(e) == 1 and e[0].conversation == s.serial and e[0].data["vorher"]["ohne_nachher"]


def test_create_instance_keeps_permissions(tmp_path):
    from vi_mcp import config
    p = tmp_path / "config.json"
    config.create_instance("a", p=p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    os.chmod(p, 0o640)
    config.create_instance("b", p=p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o640 and set(config.load(p).instances) == {"a", "b"}


def test_too_large_data_stays_readable(gd):
    o = g.new_object("erkenntnis", "viel Inhalt hier", ["thema:gross"], {"blob": "x" * (g.DATA_MAX + 10)}, reason="T")
    d = g.load(o.id).data
    assert d["gekuerzt_zeichen"] > g.DATA_MAX and "blob" not in d


def test_complete_knowledge_is_preserved(gd):
    """Code and API tables belong in the memory: nothing is shortened, everything is found and read back."""
    from vi_mcp import tools
    table = "| GET | /api/hosts | Liste |\n" * 2000 + "\ndef baue_abfrage(token = lese_token()):\n    return Zaunkoenig(token)\n"
    r = tools.call_tool("vi_lerne", {"text": "Die Hosts-API liefert Listen", "inhalt": table, "hashtags": ["thema:api"], "quelle": "Handbuch Kapitel 3"}, "a", False)
    oid = next(w.strip("[]") for w in r.split() if w.startswith(("[erkenntnis:", "erkenntnis:")))
    full = next(o for _, o, _g in g.recall("thema:api", viewer=None))
    assert full.data["inhalt"] == table.strip() and len(full.text) < 100
    assert full.id.startswith(oid[:20])
    assert table.strip() in tools.call_tool("vi_objekt", {"id": full.id}, "a", False)
    assert [o.id for _, o, _g in g.recall("Zaunkoenig", viewer=None)] == [full.id]  # found even at the end of long texts


def test_too_long_text_is_not_cut_off(gd):
    from vi_mcp import tools
    long = "Satz über die API. " * 200
    tools.call_tool("vi_lerne", {"text": long, "hashtags": ["thema:lang"], "quelle": "Handbuch Kapitel 3"}, "a", False)
    o = next(o for _, o, _g in g.recall("thema:lang", viewer=None))
    assert o.data["inhalt"] == long.strip() and len(o.text) == tools.TEXT_MAX


def test_too_large_content_rejected_with_reason(gd):
    from vi_mcp import tools
    with pytest.raises(tools.Rejected, match="split it"):
        tools.call_tool("vi_lerne", {"text": "Eine Kernaussage hier", "inhalt": "x" * (g.CONTENT_MAX + 1), "hashtags": ["thema:a"], "quelle": "Handbuch Kapitel 3"}, "a", False)


def test_skill_instructions_stay_complete(gd):
    from vi_mcp import skills
    long = "Schritt mit Befehl und Erklärung. " * 100
    o = skills.new("langer weg", ["tool:x"], ["Bash"], long, "weil gelöst", [], "a")
    assert o.data["inhalt"] == long.strip() and len(o.text) == 600


@pytest.mark.parametrize("cli_command,expected", [
    ("vzdump 101 --mode snapshot", {"skill:proxmox", "thema:vzdump"}),
    ("ssh root@pve1.example 'qm list && pct list'", {"thema:ssh", "skill:proxmox", "thema:qm", "thema:pct", "host:pve1.example"}),
    # 0.19.4: every domain command becomes thema:, everyday shell commands do not; quoted arguments are not commands
    ("sudo ipa-client-install --domain example.org", {"thema:ipa-client-install"}),
    ("ssh gpu1.example 'llama-server -m m.gguf --load-mode mlock'", {"thema:ssh", "thema:llama-server", "host:gpu1.example"}),
    ('sudo -u postgres psql -c "select 1"', {"skill:postgres", "thema:psql"}),
    ("grep 'vzdump' job.log && qm list", {"thema:grep", "skill:proxmox", "thema:qm"}),
    ("sudo sh -c 'apt-get update; pip3 install ansible'", {"thema:apt-get", "thema:pip3"}),
    ("ansible-playbook site.yml -l web1.example,web2.example", {"skill:ansible", "thema:ansible-playbook", "host:web1.example", "host:web2.example"}),
    ("ansible-playbook site.yml --limit 'sites_a:!zeit1.example'", {"skill:ansible", "thema:ansible-playbook"}),
    ('echo "a; qm b" | tee x', set()),
    # 0.20.2: tools with pitfalls are stimuli, plain everyday ones are not
    ('cd /tmp/x && pkill -f "python3 worker.py"; sleep 2', {"thema:pkill"}),
    ("find . -name '*.tmp' -exec rm {} +", {"thema:find"}),
    ("timeout 300 ssh web1.example 'vzdump 101'", {"thema:ssh", "host:web1.example", "skill:proxmox", "thema:vzdump"}),
    ("setsid nohup nice -n 10 pg_dump app", {"skill:postgres", "thema:pg_dump"}),
    # 0.20.1: quoted code inside an ssh command is not a command
    ("""ssh web1.example 'curl -s http://x/slots | python3 -c "import json,sys; d=json.load(sys.stdin); print([s for s in d])"; top -bn1'""",
     {"thema:ssh", "thema:curl", "thema:top", "host:web1.example"}),
    ("""ssh web1.example 'sudo sh -c "apt-get update; qm list"'""", {"thema:ssh", "host:web1.example", "thema:apt-get", "skill:proxmox", "thema:qm"}),
    ("sudo -u postgres pg_dump app > /tmp/a.sql", {"skill:postgres", "thema:pg_dump"}),
    ("cd x; ansible-playbook -i hosts site.yml", {"skill:ansible", "thema:ansible-playbook"}),
    ("docker compose up -d", {"skill:docker", "thema:docker"}),
    ("echo qm ist kein Befehl hier | grep x", {"thema:grep"}),
    ("ls -la /var/log/qm", set()),
])
def test_commands_become_triggers(cli_command, expected):
    assert set(intuition.command_triggers(cli_command)) == expected


def test_shell_triggers_only_for_shell(gd):
    assert "skill:proxmox" in intuition.triggers("Bash", {"command": "vzdump 1"})
    assert "skill:proxmox" not in intuition.triggers("netbox_get_vms", {"command": "vzdump 1"})


def test_shown_ids_can_be_looked_up(gd):
    from vi_mcp import tools
    tools.call_tool("vi_lerne", {"text": "Eine Erkenntnis zum Nachschlagen hier", "hashtags": ["thema:id"], "quelle": "Test 8.11."}, "a", False)
    listing = tools.call_tool("vi_erinnere", {"filter": "thema:id"}, "a", False)
    oid = listing.split("[", 1)[1].split("]", 1)[0]
    assert "Nachschlagen" in tools.call_tool("vi_objekt", {"id": oid}, "a", False)
    assert "Nachschlagen" in tools.call_tool("vi_objekt", {"id": oid[:20]}, "a", False)  # shortened, from older outputs
    with pytest.raises(tools.Rejected):
        tools.call_tool("vi_objekt", {"id": "erkenntnis:%"}, "a", False)


def test_matching_warning_beats_general(gd):
    from vi_mcp import tools
    for i in range(10):
        tools.call_tool("vi_lerne", {"text": f"Allgemeine Ansible-Notiz Nummer {i} mit Inhalt", "hashtags": ["skill:ansible"], "quelle": "Doku 8.11."}, "a", False)
    tools.call_tool("vi_lerne", {"text": "freeipa-client nie auf zeit1 laufen lassen", "hashtags": ["skill:ansible", "thema:ansible-playbook", "host:zeit1"],
                                "quelle": "Vorfall 13.10.", "wichtigkeit": 3}, "a", False)
    v = intuition.before("Bash", {"command": "ansible-playbook playbooks/freeipa-client.yml -l sites"}, "a", False)
    assert "zeit1" in v["hinweise"][0] or any("zeit1" in h for h in v["hinweise"][:2])


def test_manual_paragraphs_do_not_displace_experience(gd):
    """0.19.3: before `docker logs` four Docker doc paragraphs took all slots; the matching ssh hint dropped out."""
    from vi_mcp import tools
    for i in range(6):
        tools.call_tool("vi_lerne", {"text": f"Docker-Doku, Abschnitt {i}: allgemeiner Text", "hashtags": ["skill:docker", "art_wissen:doku-extern"],
                                    "quelle": "Herstellerdoku"}, "a", False)
    tools.call_tool("vi_lerne", {"text": "ssh nach web1 nur mit Schlüssel und BatchMode", "hashtags": ["host:web1.example", "tool:ssh"], "quelle": "Erfahrung"}, "a", False)
    h = intuition.before("Bash", {"command": "ssh web1.example 'docker logs nginx'"}, "a", False)["hinweise"]
    assert any("Schlüssel" in x for x in h)
    assert sum("Docker-Doku" in x for x in h) <= intuition.LOOKUP_MAX + 1  # +1: an exploration slot may show one more
    searched = tools.call_tool("vi_erinnere", {"filter": "Docker-Doku"}, "a", False)
    assert searched.count("Docker-Doku, Abschnitt") >= 6  # the search keeps everything


def test_content_empty_auto_skill_is_refuted(gd):
    from vi_mcp import skills
    o = skills.new("auto-test1", ["tool:Bash"], ["Bash", "AskUserQuestion", "Write"], "Bash scheiterte und gelang danach im selben Gespräch", "Schlaf", [], g.SERVER_INSTANCE, who="vi")
    real = skills.new("auto-test2", ["tool:Bash"], ["Bash", "netbox_get_vms"], "Bash scheiterte, netbox_get_vms half", "Schlaf", [], g.SERVER_INSTANCE, who="vi")
    assert skills.content_empty(o) and not skills.content_empty(real)
    skills.rate()
    assert g.load(o.id).mode == "widerlegt" and g.load(real.id).mode != "widerlegt"


def test_missing_required_field_rejected_not_silently_answered(gd):
    """0.20.4: vi_erinnere with "text" instead of "filter" returned the most important objects as if it had searched."""
    import pytest
    from vi_mcp import tools
    with pytest.raises(tools.Rejected, match="vi_recall: required field missing: filter — passed but unknown: text"):
        tools.call_tool("vi_erinnere", {"text": "Lizenz Dongle"}, "a", True)
    tools.call_tool("vi_erinnere", {"filter": "Lizenz"}, "a", True)  # correctly named: works
    with pytest.raises(tools.Rejected, match="required field missing: id$"):
        tools.call_tool("vi_objekt", {}, "a", True)


def test_state_dependent_tools_are_never_remembered(gd):
    """0.21.2: browser_wait_for(time=5) got the remembered answer from 53 s earlier (other page URL) instead of waiting."""
    from vi_mcp import intuition
    for tool in ("browser_wait_for", "browser_snapshot", "browser_take_screenshot", "browser_evaluate", "openclaw_health"):
        assert intuition.state_dependent(tool), tool
        args = {"time": 5, "n": tool}
        v = intuition.before(tool, args, "a", True)
        intuition.after(tool, args, True, 5000, None, "Seite geladen: https://x/a", v["vorher_id"], "a", True)
        assert intuition.before(tool, args, "a", True)["antwort"] is None, tool
    for tool in ("netbox_get_devices", "checkmk_get_hosts", "Read"):
        assert not intuition.state_dependent(tool), tool


def test_colon_words_without_known_kind_are_free_text(gd):
    """0.26.0: "Hosts: 62.153.216.33" emptied the search silently — a colon word is a condition only as kind:value with a known kind."""
    o = g.new_object("erkenntnis", "Die Hosts der Range 62.153.216.33 bis 62.153.216.46 sind Mailrelays", ["thema:netz"], {"quelle": "x"})
    assert g.parse_filter("Hosts: 62.153.216.33", frozenset({"thema", "art"})) == ([], [], ["Hosts:", "62.153.216.33"])
    assert g.parse_filter("um 10:30 thema:netz", frozenset({"thema"})) == ([["thema:netz"]], [], ["um", "10:30"])
    assert g.parse_filter("foo:bar thema:netz", frozenset({"thema"})) == ([["thema:netz"]], [], ["foo:bar"])  # unknown kind
    assert [x.id for _, x, _g in g.recall("Hosts: 62.153.216.33", viewer=None)] == [o.id]
    from vi_mcp import tools
    out = tools.call_tool("vi_recall", {"filter": "Hosts: 62.153.216.33"}, "a", True)
    assert o.id in out and "searched as text, no hashtag kind: Hosts:" in out


def test_recall_without_reinforcement(gd):
    """0.31.0: reinforce=false for measurements — access count and last use stay as they were, and the answer says so."""
    from vi_mcp import tools
    o = g.new_object("erkenntnis", "nginx reload only after nginx -t", ["thema:nginx"], {"quelle": "x"}, reason="T")
    before = g.load(o.id)
    out = tools.call_tool("vi_recall", {"filter": "thema:nginx", "reinforce": False}, "a", False)
    after = g.load(o.id)
    assert o.id in out and "read only (reinforce=false)" in out
    assert (after.accesses, after.last_at) == (before.accesses, before.last_at)
    tools.call_tool("vi_recall", {"filter": "thema:nginx"}, "a", False)  # default: reinforced as before
    assert g.load(o.id).accesses == before.accesses + 1
