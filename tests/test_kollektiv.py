"""Block 0.2.0: collective — private/shared, confirmation across instances, questions, collective rules, migration."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from vi_mcp import questions, intuition, main_loop, session, tools
from vi_mcp import memory as g


@pytest.fixture()
def from_seq(gd):
    a, b = session.begin("a", "t"), session.begin("b", "t")
    return a, b


def as_user(s, name, args=None):
    with session.on_behalf(s):
        return tools.call_tool(name, args or {}, s.instance, True)


def test_private_and_shared(from_seq):
    a, b = from_seq
    with session.on_behalf(a):
        v = intuition.before("netbox_get_vms", {"host": "x"}, "a")
        e = intuition.after("netbox_get_vms", {"host": "x"}, True, 3, None, "geheim: token=abc", v["vorher_id"], "a")
        k = g.new_object("erkenntnis", "x steht im Rack 4", ["host:x"], {"quelle": "Begehung"}, reason="T")
    assert g.load(e["erfahrung"]).instance == "a" and g.load(e["erfahrung"]).visibility == "privat"
    assert k.instance == "a" and k.visibility == "geteilt" and "instanz:a" in k.hashtags
    with session.on_behalf(b):
        assert [o.id for _, o, _g in g.recall("host:x")] == [k.id]  # insight yes, experience/answer no
        with pytest.raises(tools.Rejected, match="unknown"):
            tools.call_tool("vi_objekt", {"id": e["erfahrung"]}, "b", True)
    with session.on_behalf(a):
        assert len(g.recall("host:x")) == 2  # own experience + insight
        assert len(g.recall("art:antwort tool:netbox_get_vms")) == 1  # own remembered answer
    with session.on_behalf(b):
        assert not g.recall("art:antwort tool:netbox_get_vms")  # foreign remembered answer: invisible
    assert len(g.recall("tool:netbox_get_vms", viewer=None)) == 2  # the server sees experience + answer


def test_instance_hashtag_is_author_not_free(from_seq):
    a, _ = from_seq
    with session.on_behalf(a):
        o = g.new_object("erkenntnis", "versuchte fremde Urheberschaft", ["instanz:b", "thema:t"], {"quelle": "x"}, reason="T")
        assert o.instance == "a" and "instanz:b" not in o.hashtags
        with pytest.raises(tools.Rejected, match="is the author"):
            tools.call_tool("vi_markiere", {"id": o.id, "hinzu": ["instanz:b"], "grund": "x"}, "a", True)


def test_confirmation_across_instances(from_seq):
    a, b = from_seq
    with session.on_behalf(a):
        o = g.new_object("erkenntnis", "Dienst y braucht 2 GB RAM", ["thema:y"], {"quelle": "free -m"}, reason="T")
    w0 = g.recall("thema:y", viewer=None)[0][2]["wichtigkeit"]
    o.confirm("ki@a", "nochmal gemessen", "a")  # self-confirmation: counts, but no bonus
    assert g.load(o.id).foreign_confirmations() == 0
    w1 = g.recall("thema:y", viewer=None)[0][2]["wichtigkeit"]
    g.load(o.id).confirm("ki@b", "bei mir auch", "b")
    w2 = g.recall("thema:y", viewer=None)[0][2]["wichtigkeit"]
    assert g.load(o.id).foreign_confirmations() == 1 and w2 - w1 >= g.BONUS_PER_INSTANCE - 0.01 and w1 >= w0
    assert "confirmed by 1 independent line" in intuition.before("t", {}, "c", context=["thema:y"])["hinweise"][0]


def test_contradiction_disputed_then_refuted(from_seq):
    with session.on_behalf(from_seq[0]):
        o = g.new_object("erkenntnis", "z läuft auf Port 80", ["thema:z"], {"quelle": "ss -ltn"}, reason="T")
    g.load(o.id).refute("ki@b", "bei mir Port 8080", "b")
    assert g.load(o.id).mode == "strittig"
    # 0.21.1: disputed items no longer appear unasked before actions — counted by name, still findable on request
    h = intuition.before("t", {}, "c", context=["thema:z"])["hinweise"]
    assert not any("Port 80" in x for x in h) and any("disputed or unconfirmed hypothesis, only on request" in x for x in h)
    assert any(x.id == o.id for _, x, _g in g.recall("thema:z", viewer=None))
    g.load(o.id).confirm("ki@c", "Port 80 gemessen", "c")
    assert g.load(o.id).mode == "aktiv"  # a foreign confirmation ends the dispute
    g.load(o.id).refute("ki@d", "Port 8080", "d")
    assert g.load(o.id).mode == "widerlegt"  # two different contradicting instances (b, d)
    assert not g.recall("thema:z", viewer=None)
    with session.on_behalf(from_seq[0]):
        o2 = g.new_object("erkenntnis", "eigener Irrtum über Port", ["thema:q"], {"quelle": "x"}, reason="T")
    o2.refute("ki@a", "selbst falsch", "a")
    assert g.load(o2.id).mode == "widerlegt"  # the author may refute right away


def test_context_hashtags_as_triggers(gd):
    g.new_object("erkenntnis", "OOM auf web1 kommt vom Java-Heap", ["thema:oom"], {"quelle": "dmesg"}, reason="T")
    assert not intuition.before("Bash", {"command": "free"}, "a", False)["hinweise"]
    v = intuition.before("Bash", {"command": "free"}, "a", False, context=["thema:oom", "keinhashtag", "art:x"])
    assert any("Java-Heap" in h for h in v["hinweise"]) and "thema:oom" in v["zugriff"]["reize"]
    assert "art:x" not in v["zugriff"]["reize"] and "keinhashtag" not in v["zugriff"]["reize"]


def test_question_between_instances(from_seq):
    a, b = from_seq
    r = as_user(a, "vi_frage", {"an": "b", "text": "Warum ist srv0111 nachts langsam?", "reize": ["host:srv0111"], "quelle": "Graylog"})
    fid = r.split()[1]
    assert g.load(fid).data["zustand"] == "offen"
    with pytest.raises(tools.Rejected):
        as_user(a, "vi_frage", {"an": "a", "text": "Frage an mich selbst gestellt"})
    hb = intuition.before("x", {}, "b")["hinweise"]
    assert any(fid in h and "Question from a" in h for h in hb)
    assert g.load(fid).data["zustand"] == "zugestellt"
    assert not [h for h in intuition.before("x", {}, "b")["hinweise"] if "Question from" in h]  # only once per instance
    with pytest.raises(tools.Rejected, match="belege"):
        as_user(b, "vi_antwort", {"id": fid, "text": "Backup-Job um 2 Uhr", "belege": ""})
    with pytest.raises(tools.Rejected, match="your own question"):
        as_user(a, "vi_antwort", {"id": fid, "text": "weiß ich selbst", "belege": "keine Belege"})
    as_user(b, "vi_antwort", {"id": fid, "text": "Backup-Job um 2 Uhr belegt die Platte", "belege": "crontab -l auf srv0111"})
    ha = intuition.before("x", {}, "a")["hinweise"]
    assert any("Answer from b" in h and "Backup-Job" in h for h in ha)
    assert "beantwortet" in as_user(a, "vi_fragen") and "Backup-Job" in as_user(a, "vi_fragen")


def test_question_expires(from_seq):
    as_user(from_seq[0], "vi_frage", {"an": "alle", "text": "Kennt jemand Host zz9 im Netz?"})
    old = (datetime.now(timezone.utc) - timedelta(days=questions.EXPIRY_DAYS + 1)).isoformat(timespec="seconds")
    with g.lock:
        g.db().execute("UPDATE objekt SET zeit = ? WHERE art = 'frage'", (old,))
        g.db().commit()
    assert questions.let_expire() == 1
    assert "zustand:abgelaufen" in g.recall("art:frage", viewer=None)[0][1].hashtags


def test_collective_rule(gd):
    for inst in ("a", "a", "b"):
        v = intuition.before("graylog_search", {"q": inst}, inst)
        intuition.after("graylog_search", {"q": inst}, False, 1, "ConnectionError: refused 10.0.0.1", None, v["vorher_id"], inst)
    assert main_loop.step() == 1
    r = g.recall("art:regel kollektiv:ja", viewer=None)[0][1]
    assert r.instance == g.SERVER_INSTANCE and r.data["instanzen"] == ["a", "b"] and "at 2 instances" in r.text


def test_foreign_conversation_history_stays_private(from_seq):
    a, b = from_seq
    with session.on_behalf(a):
        v = intuition.before("t_x", {"passwort": "geheim"}, "a")
        intuition.after("t_x", {"passwort": "geheim"}, True, 1, None, "ok", v["vorher_id"], "a")
    session.persist(a)
    foreign = as_user(b, "vi_gespraech", {"serial": a.serial})
    assert "log private" in foreign and "geheim" not in foreign
    assert "t_x" in as_user(a, "vi_gespraech", {"serial": a.serial})


def test_migration_from_0_1(tmp_path):
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
    g.open_db(p)
    try:
        e, a = g.load("erkenntnis:1"), g.load("antwort:1")
        assert (e.instance, e.visibility) == ("anna", "geteilt") and (a.instance, a.visibility) == ("vi", "privat")
        assert "cache:abc" in a.hashtags and not [t for t in a.hashtags if t.startswith("frage:")]
    finally:
        g.close_db()


def test_reinforcement_only_on_success(gd):
    e = g.new_object("erkenntnis", "web2 braucht Proxy", ["host:web2"], {"quelle": "x"}, reason="T")
    v = intuition.before("checkmk_get_host", {"host": "web2"}, "a")
    assert e.id in v["zugriff"]["gefunden"] and g.load(e.id).accesses == 0  # showing alone does not reinforce
    n = intuition.after("checkmk_get_host", {"host": "web2"}, False, 1, "Timeout", None, v["vorher_id"], "a")
    assert n["verstaerkt"] == 0 and g.load(e.id).accesses == 0  # failure does not reinforce
    v = intuition.before("checkmk_get_host", {"host": "web2"}, "a")
    n = intuition.after("checkmk_get_host", {"host": "web2"}, True, 1, None, "ok", v["vorher_id"], "a")
    assert n["verstaerkt"] == 1 and g.load(e.id).accesses == 1


def test_hint_budget(gd):
    for i in range(7):
        g.new_object("erkenntnis", f"Hinweis {i} zu web3", ["host:web3"], {"quelle": "x"}, reason="T")
    h = intuition.before("Bash", {"host": "web3"}, "a", False)["hinweise"]
    assert len(h) == intuition.HINT_BUDGET + 1 and h[-1].startswith("… 3 more hits") and "vi_drilldown" in h[-1]


def test_history_truncation_is_named(gd):
    o = g.new_object("erkenntnis", "lange Geschichte", ["thema:g"], {"quelle": "x"}, reason="T")
    for i in range(g.HISTORY_MAX + 4):
        o = g.load(o.id); o.confirm("ki@a", f"Grund {i}", "a")
    o = g.load(o.id)
    assert len(o.changes) == g.HISTORY_MAX and o.data["aenderungen_gekuerzt"] == 5
    assert "5 older changes truncated" in tools.call_tool("vi_objekt", {"id": o.id}, "a", True)


def test_surprise_determines_importance(gd):
    def fail(i):
        v = intuition.before("graylog_search", {"q": i}, "a")
        return g.load(intuition.after("graylog_search", {"q": i}, False, 1, "ConnectionError: refused 10.0.0.9", None, v["vorher_id"], "a")["erfahrung"])
    levels = [fail(i).data["ueberraschung"]["stufe"] for i in range(5)]
    assert levels == ["neu", "wiederholt", "wiederholt", "chronisch", "chronisch"]
    assert g.recall("ueberraschung:neu", viewer=None)[0][1].importance == 3
    assert g.recall("ueberraschung:chronisch", viewer=None)[0][1].importance == 1
    v = intuition.before("graylog_search", {"q": "x"}, "a")
    e = g.load(intuition.after("graylog_search", {"q": "x"}, True, 1, None, "ok", v["vorher_id"], "a")["erfahrung"])
    assert e.data["ueberraschung"]["stufe"] == "erholt" and e.importance == 2
    v = intuition.before("netbox_get_sites", {}, "a")
    e = g.load(intuition.after("netbox_get_sites", {}, True, 1, None, "ok", v["vorher_id"], "a")["erfahrung"])
    assert e.data["ueberraschung"]["stufe"] == "keine" and e.importance == 0


def test_hint_lift_measurement_point(gd):
    from vi_mcp import metrics
    g.new_object("erkenntnis", "web9 nur über Proxy", ["host:web9"], {"quelle": "x"}, reason="T")
    for i in range(12):  # with hint (host:web9) → 10/12 ok
        v = intuition.before("checkmk_get_host", {"host": "web9", "i": i}, "a")
        intuition.after("checkmk_get_host", {"host": "web9", "i": i}, i < 10, 1, None if i < 10 else "Timeout", "ok" if i < 10 else None, v["vorher_id"], "a")
    for i in range(12):  # without hint → 4/12 ok
        v = intuition.before("checkmk_get_host", {"host": "web8", "i": i}, "a")
        intuition.after("checkmk_get_host", {"host": "web8", "i": i}, i < 4, 1, None if i < 4 else "Timeout", "ok" if i < 4 else None, v["vorher_id"], "a")
    l = metrics.hint_lift(24, viewer=None)
    assert l["mit"] == {"n": 12, "ok": 10} and l["ohne"] == {"n": 12, "ok": 4} and l["urteil"] == "hints help"
    assert "+50 points" in metrics.line(l)
    assert "too little data" in metrics.hint_lift(24, tool="gibtsnicht", viewer=None)["urteil"]
    assert "Hint lift" in tools.call_tool("vi_status", {}, "a", True)


def test_delete_conversation_tombstone(from_seq):
    a, b = from_seq
    with session.on_behalf(a):
        v = intuition.before("t_x", {"passwort": "geheim123"}, "a")
        e = intuition.after("t_x", {"passwort": "geheim123"}, True, 1, None, "geheimes Ergebnis", v["vorher_id"], "a")["erfahrung"]
        k = g.new_object("erkenntnis", "aus dem Gespräch gelernt", ["thema:l"], {"quelle": "x"}, reason="T")
    with pytest.raises(tools.Rejected, match="still open"):
        as_user(a, "vi_loesche_gespraech", {"serial": a.serial, "grund": "Test"})
    session.finish(a.id)
    with pytest.raises(tools.Rejected, match="belongs to instance a"):
        as_user(b, "vi_loesche_gespraech", {"serial": a.serial, "grund": "fremd"})
    r = as_user(a, "vi_loesche_gespraech", {"serial": a.serial, "grund": "Zugangsdaten im Verlauf"})
    assert "2 private objects" in r
    assert g.load(e) is None and g.load(k.id) is not None  # private gone, shared knowledge stays
    with g.lock:
        assert g.db().execute("SELECT COUNT(*) FROM gespraech_roh WHERE serial = ?", (a.serial,)).fetchone()[0] == 0
        assert g.db().execute("SELECT COUNT(*) FROM kante WHERE a = ? OR b = ?", (e, e)).fetchone()[0] == 0
    gs = g.load(f"gespraech:{a.serial}")
    assert gs.data["zustand"] == "geloescht" and gs.data["geloescht"]["objekte"] == 2 and "zustand:geloescht" in gs.hashtags
    assert "geheim" not in gs.text and "Zugangsdaten im Verlauf" in gs.text
    with pytest.raises(tools.Rejected, match="already deleted"):
        as_user(a, "vi_loesche_gespraech", {"serial": a.serial, "grund": "nochmal"})
    session.finish(b.id)
    r = session.delete_instance_data("b", "Admin: Instanz aufgelöst")  # admin path (CLI): all conversations → tombstones
    assert r["gespraeche"] == 1 and g.load(f"gespraech:{b.serial}").data["zustand"] == "geloescht"



def test_llm_hypothesis_hint_only_after_foreign_confirmation(gd):
    """0.21.1: an unconfirmed sleep hypothesis was the most-shown hint (719×). Only a foreign confirmation makes it a hint."""
    o = g.new_object("erkenntnis", "Auf Host web4 deuten Latenzen auf Instabilität hin", ["host:web4", "herkunft:schlaf-llm"],
                       {"quelle": "Schlaf-Reflexion"}, reason="T", instance="vi")
    assert not any("web4 deuten" in x for x in intuition.before("Bash", {"command": "ssh web4 uptime"}, "a")["hinweise"])
    g.load(o.id).confirm("ki@b", "Latenz selbst gemessen", "b")
    assert any("web4 deuten" in x for x in intuition.before("Bash", {"command": "ssh web4 uptime"}, "a")["hinweise"])
