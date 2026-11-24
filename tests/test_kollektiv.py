"""Block 0.2.0: collective — private/shared, confirmation across instances, questions, collective rules, migration."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from vi_mcp import questions, intuition, main_loop, session, tools
from vi_mcp import memory as g
from conftest import sqlite_only  # noqa: E402


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
        k = g.new_object("insight", "x steht im Rack 4", ["host:x"], {"source": "Begehung"}, reason="T")
    assert g.load(e["erfahrung"]).instance == "a" and g.load(e["erfahrung"]).visibility == "private"
    assert k.instance == "a" and k.visibility == "shared" and "instance:a" in k.hashtags
    with session.on_behalf(b):
        assert [o.id for _, o, _g in g.recall("host:x")] == [k.id]  # insight yes, experience/answer no
        with pytest.raises(tools.Rejected, match="unknown"):
            tools.call_tool("vi_objekt", {"id": e["erfahrung"]}, "b", True)
    with session.on_behalf(a):
        assert len(g.recall("host:x")) == 2  # own experience + insight
        assert len(g.recall("kind:answer tool:netbox_get_vms")) == 1  # own remembered answer
    with session.on_behalf(b):
        assert not g.recall("kind:answer tool:netbox_get_vms")  # foreign remembered answer: invisible
    assert len(g.recall("tool:netbox_get_vms", viewer=None)) == 2  # the server sees experience + answer


def test_instance_hashtag_is_author_not_free(from_seq):
    a, _ = from_seq
    with session.on_behalf(a):
        o = g.new_object("insight", "versuchte fremde Urheberschaft", ["instance:b", "topic:t"], {"source": "x"}, reason="T")
        assert o.instance == "a" and "instance:b" not in o.hashtags
        with pytest.raises(tools.Rejected, match="is the author"):
            tools.call_tool("vi_markiere", {"id": o.id, "hinzu": ["instance:b"], "grund": "x"}, "a", True)


def test_confirmation_across_instances(from_seq):
    a, b = from_seq
    with session.on_behalf(a):
        o = g.new_object("insight", "Dienst y braucht 2 GB RAM", ["topic:y"], {"source": "free -m"}, reason="T")
    w0 = g.recall("topic:y", viewer=None)[0][2]["wichtigkeit"]
    o.confirm("ki@a", "nochmal gemessen", "a")  # self-confirmation: counts, but no bonus
    assert g.load(o.id).foreign_confirmations() == 0
    w1 = g.recall("topic:y", viewer=None)[0][2]["wichtigkeit"]
    g.load(o.id).confirm("ki@b", "bei mir auch", "b")
    w2 = g.recall("topic:y", viewer=None)[0][2]["wichtigkeit"]
    assert g.load(o.id).foreign_confirmations() == 1 and w2 - w1 >= g.BONUS_PER_INSTANCE - 0.01 and w1 >= w0
    assert "confirmed by 1 independent line" in intuition.before("t", {}, "c", context=["topic:y"])["hinweise"][0]


def test_contradiction_disputed_then_refuted(from_seq):
    with session.on_behalf(from_seq[0]):
        o = g.new_object("insight", "z läuft auf Port 80", ["topic:z"], {"source": "ss -ltn"}, reason="T")
    g.load(o.id).refute("ki@b", "bei mir Port 8080", "b")
    assert g.load(o.id).mode == "disputed"
    # 0.21.1: disputed items no longer appear unasked before actions — counted by name, still findable on request
    h = intuition.before("t", {}, "c", context=["topic:z"])["hinweise"]
    assert not any("Port 80" in x for x in h) and any("disputed or unconfirmed hypothesis, only on request" in x for x in h)
    assert any(x.id == o.id for _, x, _g in g.recall("topic:z", viewer=None))
    g.load(o.id).confirm("ki@c", "Port 80 gemessen", "c")
    assert g.load(o.id).mode == "active"  # a foreign confirmation ends the dispute
    g.load(o.id).refute("ki@d", "Port 8080", "d")
    assert g.load(o.id).mode == "refuted"  # two different contradicting instances (b, d)
    assert not g.recall("topic:z", viewer=None)
    with session.on_behalf(from_seq[0]):
        o2 = g.new_object("insight", "eigener Irrtum über Port", ["topic:q"], {"source": "x"}, reason="T")
    o2.refute("ki@a", "selbst falsch", "a")
    assert g.load(o2.id).mode == "withdrawn"  # 0.67.0: the author withdraws right away — taken back, not proven false
    assert not g.recall("topic:q", viewer=None)  # gone from searches like a refuted object


def test_withdrawn_and_refuted_are_two_modes(from_seq, tmp_path):
    """0.67.0 — the user: "teile widerlegt im Gedächtnis in zwei Begriffe auf". An author's refutation withdraws (zurueckgezogen);
    two foreign model families refute (widerlegt); a withdrawn object stays withdrawn after one foreign refutation and becomes
    refuted after two. The migration moves old author-only widerlegt objects, keeps the rest and names itself in the history."""
    import json
    with session.on_behalf(from_seq[0]):
        o = g.new_object("insight", "w läuft auf Port 81", ["topic:w"], {"source": "x"}, reason="T")
    o = g.load(o.id).refute("ki@a", "selbst falsch", "a")
    assert o.mode == "withdrawn"
    o = g.load(o.id).refute("ki@b", "auch falsch", "b", family="fam_b")
    assert o.mode == "withdrawn"  # one foreign family does not turn a withdrawal into a refutation
    o = g.load(o.id).refute("ki@c", "falsch gemessen", "c", family="fam_c")
    assert o.mode == "refuted"  # two independent foreign families: refuted
    assert g.refuted_mode("a", "active", {"refutations": [{"instanz": "b", "familie": "f"}, {"instanz": "c", "familie": "f"}]}) == "disputed"
    # migration: an old author-only widerlegt becomes zurueckgezogen; a refutation by two families stays widerlegt
    with session.on_behalf(from_seq[0]):
        old = g.new_object("insight", "alt vom Autor widerlegt", ["topic:m"], {"source": "x"}, reason="T")
        kept = g.new_object("insight", "alt von zwei Familien widerlegt", ["topic:m"], {"source": "x"}, reason="T")
    with g.lock:
        con = g.db()
        con.execute("UPDATE object SET mode = 'refuted', data = ? WHERE id = ?",
                    (json.dumps({"quelle": "x", "refuted_by": {"a": 1}, "refutations": [{"instanz": "a", "familie": "a"}]}), old.id))
        con.execute("UPDATE object SET mode = 'refuted', data = ? WHERE id = ?",
                    (json.dumps({"quelle": "x", "refuted_by": {"b": 1, "c": 1},
                                 "refutations": [{"instanz": "b", "familie": "fb"}, {"instanz": "c", "familie": "fc"}]}), kept.id))
        g._migrate(con)
        con.commit()
    assert g.load(old.id).mode == "withdrawn" and g.load(old.id).changes[-1]["what"] == "withdrawn"
    assert g.load(kept.id).mode == "refuted"
    with g.lock:
        g._migrate(g.db())  # idempotent: nothing left to move
    assert g.load(old.id).changes[-1]["what"] == "withdrawn" and len([c for c in g.load(old.id).changes if c["what"] == "withdrawn"]) == 1


def test_context_hashtags_as_triggers(gd):
    g.new_object("insight", "OOM auf web1 kommt vom Java-Heap", ["topic:oom"], {"source": "dmesg"}, reason="T")
    assert not intuition.before("Bash", {"command": "free"}, "a", False)["hinweise"]
    v = intuition.before("Bash", {"command": "free"}, "a", False, context=["topic:oom", "keinhashtag", "kind:x"])
    assert any("Java-Heap" in h for h in v["hinweise"]) and "topic:oom" in v["zugriff"]["triggers"]
    assert "kind:x" not in v["zugriff"]["triggers"] and "keinhashtag" not in v["zugriff"]["triggers"]


def test_question_between_instances(from_seq):
    a, b = from_seq
    r = as_user(a, "vi_frage", {"an": "b", "text": "Warum ist srv0111 nachts langsam?", "reize": ["host:srv0111"], "quelle": "Graylog"})
    fid = r.split()[1]
    assert g.load(fid).data["state"] == "open"
    own = as_user(a, "vi_frage", {"an": "a", "text": "Frage an die anderen Gespräche von a"})  # since Unreleased: a's other conversations
    assert "other conversations of this instance" in own
    with pytest.raises(ValueError, match="needs a conversation"):  # without a conversation there is nobody else to ask
        questions.ask("a", "a", "Frage ohne Gespräch gestellt", [], "")
    hb = intuition.before("x", {}, "b")["hinweise"]
    assert any(fid in h and "Question from a" in h for h in hb)
    assert g.load(fid).data["state"] == "delivered"
    assert not [h for h in intuition.before("x", {}, "b")["hinweise"] if "Question from" in h]  # only once per instance
    with pytest.raises(tools.Rejected, match="belege"):
        as_user(b, "vi_antwort", {"id": fid, "text": "Backup-Job um 2 Uhr", "belege": ""})
    with pytest.raises(tools.Rejected, match="your own question"):
        as_user(a, "vi_antwort", {"id": fid, "text": "weiß ich selbst", "belege": "keine Belege"})
    as_user(b, "vi_antwort", {"id": fid, "text": "Backup-Job um 2 Uhr belegt die Platte", "belege": "crontab -l auf srv0111"})
    assert not [h for h in intuition.before("x", {}, "a")["hinweise"] if "Answer from" in h]  # not to another of a's conversations…
    with session.on_behalf(a):
        ha = intuition.before("x", {}, "a")["hinweise"]  # …but to the asking one, which is still open
    assert any("Answer from b" in h and "Backup-Job" in h for h in ha)
    assert "answered" in as_user(a, "vi_fragen") and "Backup-Job" in as_user(a, "vi_fragen")


def test_question_expires(from_seq):
    as_user(from_seq[0], "vi_frage", {"an": "alle", "text": "Kennt jemand Host zz9 im Netz?"})
    old = (datetime.now(timezone.utc) - timedelta(days=questions.EXPIRY_DAYS + 1)).isoformat(timespec="seconds")
    with g.lock:
        g.db().execute("UPDATE object SET ts = ? WHERE kind = 'question'", (old,))
        g.db().commit()
    assert questions.let_expire() == 1
    assert "state:expired" in g.recall("kind:question", viewer=None)[0][1].hashtags


def test_collective_rule(gd):
    for inst in ("a", "a", "b"):
        v = intuition.before("graylog_search", {"q": inst}, inst)
        intuition.after("graylog_search", {"q": inst}, False, 1, "ConnectionError: refused 10.0.0.1", None, v["vorher_id"], inst)
    assert main_loop.step() == 1
    r = g.recall("kind:rule collective:yes", viewer=None)[0][1]
    assert r.instance == g.SERVER_INSTANCE and r.data["instances"] == ["a", "b"] and "at 2 instances" in r.text
    # stored English, not only found: the filter translates collective:yes, so a stored collective:ja passed the line above
    # (24.11.2026: the loop wrote ja/nein, and every start's migration renamed it again)
    assert "collective:yes" in r.hashtags and not any(t in r.hashtags for t in ("collective:ja", "collective:nein"))


def test_foreign_conversation_history_stays_private(from_seq):
    a, b = from_seq
    with session.on_behalf(a):
        v = intuition.before("t_x", {"passwort": "geheim"}, "a")
        intuition.after("t_x", {"passwort": "geheim"}, True, 1, None, "ok", v["vorher_id"], "a")
    session.persist(a)
    foreign = as_user(b, "vi_gespraech", {"serial": a.serial})
    assert "log private" in foreign and "geheim" not in foreign
    assert "t_x" in as_user(a, "vi_gespraech", {"serial": a.serial})


@sqlite_only
def test_migration_from_0_1(tmp_path):
    p = tmp_path / "alt.db"
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE objekt (id TEXT PRIMARY KEY, art TEXT NOT NULL, zeit TEXT NOT NULL, zuletzt TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '', daten TEXT NOT NULL DEFAULT '{}', wichtigkeit INTEGER NOT NULL DEFAULT 1,
            bestaetigt INTEGER NOT NULL DEFAULT 0, widerlegt INTEGER NOT NULL DEFAULT 0, zugriffe INTEGER NOT NULL DEFAULT 0,
            modus TEXT NOT NULL DEFAULT 'active', aenderungen TEXT NOT NULL DEFAULT '[]', gespraech TEXT);
        CREATE TABLE tag (objekt_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (objekt_id, tag));
        INSERT INTO objekt (id, art, zeit, zuletzt, text) VALUES ('erkenntnis:1', 'insight', '2026-11-08T00:00:00+00:00', '2026-11-08T00:00:00+00:00', 'alt');
        INSERT INTO objekt (id, art, zeit, zuletzt, text) VALUES ('antwort:1', 'answer', '2026-11-08T00:00:00+00:00', '2026-11-08T00:00:00+00:00', 'a');
        INSERT INTO tag VALUES ('erkenntnis:1', 'instance:anna'), ('erkenntnis:1', 'kind:erkenntnis'), ('antwort:1', 'frage:abc');
    """)
    con.commit()
    con.close()
    g.open_db(p)
    try:
        e, a = g.load("erkenntnis:1"), g.load("antwort:1")
        assert (e.instance, e.visibility) == ("anna", "shared") and (a.instance, a.visibility) == ("vi", "private")
        assert "cache:abc" in a.hashtags and not [t for t in a.hashtags if t.startswith("frage:")]
    finally:
        g.close_db()


def test_reinforcement_only_on_success(gd):
    e = g.new_object("insight", "web2 braucht Proxy", ["host:web2"], {"source": "x"}, reason="T")
    v = intuition.before("checkmk_get_host", {"host": "web2"}, "a")
    assert e.id in v["zugriff"]["found"] and g.load(e.id).accesses == 0  # showing alone does not reinforce
    n = intuition.after("checkmk_get_host", {"host": "web2"}, False, 1, "Timeout", None, v["vorher_id"], "a")
    assert n["verstaerkt"] == 0 and g.load(e.id).accesses == 0  # failure does not reinforce
    v = intuition.before("checkmk_get_host", {"host": "web2"}, "a")
    n = intuition.after("checkmk_get_host", {"host": "web2"}, True, 1, None, "ok", v["vorher_id"], "a")
    assert n["verstaerkt"] == 1 and g.load(e.id).accesses == 1


def test_hint_budget(gd):
    for i in range(7):
        g.new_object("insight", f"Hinweis {i} zu web3", ["host:web3"], {"source": "x"}, reason="T")
    v = intuition.before("Bash", {"host": "web3"}, "a", False)
    h = v["hinweise"]
    assert len(h) == intuition.HINT_BUDGET + 2 and h[-1].startswith("… 3 more hits") and "vi_drilldown" in h[-1]
    assert h[-2].startswith("Did one of these help or mislead you?")  # 0.49.0: the feedback nudge
    assert f'vi_feedback(before_id="{v["vorher_id"]}", used=[' in h[-2] and "helped=" not in h[-2]  # Z7: bound to this action


def test_history_truncation_is_named(gd):
    o = g.new_object("insight", "lange Geschichte", ["topic:g"], {"source": "x"}, reason="T")
    for i in range(g.HISTORY_MAX + 4):
        o = g.load(o.id); o.confirm("ki@a", f"Grund {i}", "a")
    o = g.load(o.id)
    assert len(o.changes) == g.HISTORY_MAX and o.data["changes_trimmed"] == 5
    assert "5 older changes truncated" in tools.call_tool("vi_objekt", {"id": o.id}, "a", True)


def test_surprise_determines_importance(gd):
    def fail(i):
        v = intuition.before("graylog_search", {"q": i}, "a")
        return g.load(intuition.after("graylog_search", {"q": i}, False, 1, "ConnectionError: refused 10.0.0.9", None, v["vorher_id"], "a")["erfahrung"])
    levels = [fail(i).data["surprise"]["level"] for i in range(5)]
    assert levels == ["new", "repeated", "repeated", "chronic", "chronic"]
    assert g.recall("surprise:new", viewer=None)[0][1].importance == 3
    assert g.recall("surprise:chronic", viewer=None)[0][1].importance == 1
    v = intuition.before("graylog_search", {"q": "x"}, "a")
    e = g.load(intuition.after("graylog_search", {"q": "x"}, True, 1, None, "ok", v["vorher_id"], "a")["erfahrung"])
    assert e.data["surprise"]["level"] == "recovered" and e.importance == 2
    v = intuition.before("netbox_get_sites", {}, "a")
    e = g.load(intuition.after("netbox_get_sites", {}, True, 1, None, "ok", v["vorher_id"], "a")["erfahrung"])
    assert e.data["surprise"]["level"] == "none" and e.importance == 0


def test_hint_lift_measurement_point(gd):
    from vi_mcp import metrics
    g.new_object("insight", "web9 nur über Proxy", ["host:web9"], {"source": "x"}, reason="T")
    for i in range(12):  # with hint (host:web9) → 10/12 ok
        v = intuition.before("checkmk_get_host", {"host": "web9", "i": i}, "a")
        intuition.after("checkmk_get_host", {"host": "web9", "i": i}, i < 10, 1, None if i < 10 else "Timeout", "ok" if i < 10 else None, v["vorher_id"], "a")
    for i in range(12):  # without hint → 4/12 ok
        v = intuition.before("checkmk_get_host", {"host": "web8", "i": i}, "a")
        intuition.after("checkmk_get_host", {"host": "web8", "i": i}, i < 4, 1, None if i < 4 else "Timeout", "ok" if i < 4 else None, v["vorher_id"], "a")
    l = metrics.hint_lift(24, viewer=None)
    assert l["mit"] == {"n": 12, "ok": 10} and l["ohne"] == {"n": 12, "ok": 4} and l["urteil"].startswith("higher with hints — raw")
    assert "+50 points" in metrics.line(l)
    assert "too little data" in metrics.hint_lift(24, tool="gibtsnicht", viewer=None)["urteil"]
    assert "Hint lift" in tools.call_tool("vi_status", {}, "a", True)


def test_delete_conversation_tombstone(from_seq):
    a, b = from_seq
    with session.on_behalf(a):
        v = intuition.before("t_x", {"passwort": "geheim123"}, "a")
        e = intuition.after("t_x", {"passwort": "geheim123"}, True, 1, None, "geheimes Ergebnis", v["vorher_id"], "a")["erfahrung"]
        k = g.new_object("insight", "aus dem Gespräch gelernt", ["topic:l"], {"source": "x"}, reason="T")
    with pytest.raises(tools.Rejected, match="still open"):
        as_user(a, "vi_loesche_gespraech", {"serial": a.serial, "grund": "Test"})
    session.finish(a.id)
    with pytest.raises(tools.Rejected, match="belongs to instance a"):
        as_user(b, "vi_loesche_gespraech", {"serial": a.serial, "grund": "fremd"})
    r = as_user(a, "vi_loesche_gespraech", {"serial": a.serial, "grund": "Zugangsdaten im Verlauf"})
    assert "2 private objects" in r
    assert g.load(e) is None and g.load(k.id) is not None  # private gone, shared knowledge stays
    with g.lock:
        assert g.db().execute("SELECT COUNT(*) FROM conversation_raw WHERE serial = ?", (a.serial,)).fetchone()[0] == 0
        assert g.db().execute("SELECT COUNT(*) FROM edge WHERE a = ? OR b = ?", (e, e)).fetchone()[0] == 0
    gs = g.load_keyed("conversation", a.serial)
    assert gs.data["state"] == "deleted" and gs.data["deleted"]["objekte"] == 2 and "state:deleted" in gs.hashtags
    assert "geheim" not in gs.text and "Zugangsdaten im Verlauf" in gs.text
    with pytest.raises(tools.Rejected, match="already deleted"):
        as_user(a, "vi_loesche_gespraech", {"serial": a.serial, "grund": "nochmal"})
    session.finish(b.id)
    r = session.delete_instance_data("b", "Admin: Instanz aufgelöst")  # admin path (CLI): all conversations → tombstones
    assert r["gespraeche"] == 1 and g.load_keyed("conversation", b.serial).data["state"] == "deleted"



def test_llm_hypothesis_hint_only_after_foreign_confirmation(gd):
    """0.21.1: an unconfirmed sleep hypothesis was the most-shown hint (719×). Only a foreign confirmation makes it a hint."""
    o = g.new_object("insight", "Auf Host web4 deuten Latenzen auf Instabilität hin", ["host:web4", "origin:sleep-llm"],
                       {"source": "Schlaf-Reflexion"}, reason="T", instance="vi")
    assert not any("web4 deuten" in x for x in intuition.before("Bash", {"command": "ssh web4 uptime"}, "a")["hinweise"])
    g.load(o.id).confirm("ki@b", "Latenz selbst gemessen", "b")
    assert any("web4 deuten" in x for x in intuition.before("Bash", {"command": "ssh web4 uptime"}, "a")["hinweise"])


def test_long_questions_and_answers_are_kept_whole_and_readable(from_seq):
    """Found 14.11.2026 between Claude and Codex: questions were cut to 1000 and answers to 2000 characters without notice — a review
    answer ended mid-sentence and Codex had to ask for the full question. Now both are stored whole (answers up to 20,000
    characters, evidence up to 2000; longer is refused with the reason), vi_questions(id=…) shows one question and every answer
    completely, and shortened lines say where the full text is."""
    a, b = from_seq
    question = "Please review these findings. " + " ".join(f"finding {i}: detail text for the reviewer." for i in range(90))
    assert len(question) > 3000
    fid = as_user(a, "vi_ask", {"to": "b", "text": question, "source": "review"}).split()[1]
    full_q = as_user(b, "vi_questions", {"id": fid})
    assert "finding 89: detail text" in full_q
    answer = "Review result. " + " ".join(f"point {i}: agreed with evidence in file.py:{i}." for i in range(200))
    assert 2000 < len(answer) < 20000
    as_user(b, "vi_answer", {"id": fid, "text": answer, "evidence": "git show; " + "x" * 900})
    full = as_user(a, "vi_questions", {"id": fid})
    assert "point 199: agreed" in full and "x" * 900 in full
    assert f"vi_questions(id={fid})" in as_user(a, "vi_questions")   # the listing says where the full text is
    with pytest.raises(tools.Rejected, match="20000"):
        as_user(b, "vi_answer", {"id": fid, "text": "y" * 20001, "evidence": "measured"})


def test_vi_questions_by_id_respects_quarantine_and_answers_never_vanish(from_seq):
    """Codex's review without sandbox (14.11.2026): (1) vi_questions(id=…) only checked visibility, so a question held by the fixed
    rules could be read through it; (2) many long answers could push the question past the object size limit, where the generic
    shortening drops the oldest half of the longest list — the answers. Now (1) the same read rule as vi_object applies and (2) an
    answer that would not fit is refused with the reason before anything is shortened."""
    a, b = from_seq
    fid = as_user(a, "vi_ask", {"to": "b", "text": "Please check the deployment notes for web1 carefully.", "source": "x"}).split()[1]
    o = g.load(fid)
    o.mode, o.data["review"] = "quarantine", {"verdacht": ["instruction"]}
    g.save(o)
    with pytest.raises(tools.Rejected, match="held in quarantine"):
        as_user(b, "vi_questions", {"id": fid})
    o = g.load(fid)
    o.mode, o.data["review"] = "aktiv", {}
    g.save(o)
    answers = 0
    while True:
        try:
            as_user(b, "vi_answer", {"id": fid, "text": f"answer {answers} " + "z" * 19900, "evidence": "measured"})
            answers += 1
        except tools.Rejected as e:
            assert "does not fit" in str(e)
            break
    full = as_user(a, "vi_questions", {"id": fid})
    assert answers >= 10 and all(f"answer {i} " in full for i in range(answers))   # every stored answer is still there


def test_a_pending_network_question_is_not_readable_before_release(from_seq):
    """Codex's review: network questions arrive with an='alle' in quarantine without a fixed-rule suspicion (forum.py); they are not
    delivered before review, so vi_questions(id) refuses them for ordinary instances, and vi_object marks them as unreviewed data."""
    a, b = from_seq
    o = g.new_object("question", "How do I rotate the backup keys on db1?", ["to:all", "state:open"],
                     {"from": "x@net", "to": "alle", "state": "offen", "source": "net", "delivered_to": [], "answers": [], "reported": 0,
                      "review": {"rules": [], "reviewer": None}}, mode="quarantine", instance="p2p-peer", reason="import")
    with pytest.raises(tools.Rejected, match="not delivered yet"):
        as_user(b, "vi_questions", {"id": o.id})
    assert as_user(b, "vi_object", {"id": o.id}).startswith("UNREVIEWED — waits in quarantine")
