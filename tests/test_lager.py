"""0.10.0: housekeeping — long-term archive in its own file, stubs, restore, deletion, evidence protection."""
import json
import os
import stat
import zlib
from datetime import datetime, timedelta, timezone

import pytest

from vi_mcp import intuition, archive, sleep_cycle, session, tools
from vi_mcp import memory as g

_n = iter(range(10_000))


def _age(oid, days):
    z = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="milliseconds")
    with g.lock:
        g.db().execute("UPDATE objekt SET zeit = ?, zuletzt = ? WHERE id = ?", (z, z, oid))
        g.db().commit()


def _exp(host, ok=True):
    args = {"host": host, "n": next(_n)}
    v = intuition.before("netbox_get_sites", args, "a")
    return intuition.after("netbox_get_sites", args, ok, 1, None if ok else "Fehler", "ok" if ok else None, v["vorher_id"], "a")["erfahrung"]


def _knowledge(text, tags, kind="erkenntnis", instance="a"):
    return g.new_object(kind, text, tags, {"quelle": "Test"}, reason="T", instance=instance)


def test_old_experience_archived_with_stub(gd):
    old, young = _exp("h1"), _exp("h3")
    _age(old, archive.DAYS["erfahrung"] + 1)
    b = sleep_cycle.run("Test").data["schritte"]["5_lager"]
    assert b["eingelagert"] == 1 and b["je_art"] == {"erfahrung": 1}
    s = g.load(old)
    assert s.mode == "archiviert" and "modus:archiviert" in s.hashtags and s.data["lager"] and "args" not in s.data
    assert g.load(young).mode == "aktiv"
    if g.backend() == "sqlite":  # PostgreSQL: the archive is a schema, no file
        assert stat.S_IMODE(os.stat(g.archive_path).st_mode) == 0o600 and g.archive_path != gd
    assert not [o for _, o, _g in g.recall("host:h1", viewer=None)]  # not in the foreground
    assert [o.id for _, o, _g in g.recall("host:h1 modus:archiviert", viewer=None)] == [old]  # but findable
    assert archive.content(old)["daten"]["args"]["host"] == "h1"
    assert sleep_cycle.run("Test 2").data["schritte"]["5_lager"]["eingelagert"] == 0  # idempotent


def test_only_real_evidence_protects(gd):
    k = _knowledge("h2 ist relevant", ["host:h2"])
    evidence, recalled = _exp("h2"), _exp("h2")
    g.load(evidence).link(k.id, "Beleg (Schlaf: Abstraktion)")
    assert any("recalled before the action" in gr for b, gr in g.load(recalled).edges() if b == k.id)
    for e in (evidence, recalled):
        _age(e, archive.DAYS["erfahrung"] + 1)
    archive.cleanup()
    assert g.load(evidence).mode == "aktiv" and g.load(recalled).mode == "archiviert"


def test_knowledge_only_after_long_disuse(gd):
    old = _knowledge("selten gebrauchtes Wissen zu h4", ["host:h4"])
    used = _knowledge("gezeigtes Wissen zu h5", ["host:h5"])
    fresh = _knowledge("neues Wissen zu h6", ["host:h6"])
    _age(old.id, archive.DAYS["erkenntnis"] + 1)
    _age(used.id, archive.DAYS["erkenntnis"] + 1)
    _age(fresh.id, archive.DAYS["erkenntnis"] - 1)
    v = intuition.before("Bash", {"host": "h5"}, "a", False)  # shown and rated → counts as used
    intuition.after("Bash", {"host": "h5"}, False, 1, "x", None, v["vorher_id"], "a", False)
    assert archive.cleanup()["je_art"] == {"erkenntnis": 1}
    assert g.load(old.id).mode == "archiviert" and g.load(used.id).mode == "aktiv" and g.load(fresh.id).mode == "aktiv"


def test_never_automatic(gd):
    ids = []
    for kind, tags in (("reflex", ["reflex:r"]), ("frage", ["an:b"]), ("modell", ["modell:m"])):
        d = {"name": "r", "art": "nachher", "code": "def run(t, a, e):\n    return None"} if kind == "reflex" else {"von": "a", "an": "b", "zustand": "offen", "zugestellt_an": [], "antworten": []}
        o = g.new_object(kind, "bleibt im aktiven Speicher", tags, d, reason="T")
        _age(o.id, 2000)
        ids.append(o.id)
    assert archive.cleanup()["eingelagert"] == 0 and all(g.load(i).mode != "archiviert" for i in ids)


def test_before_names_archived_and_retrieval(gd):
    k = _knowledge("cue9 braucht beim Neustart den Proxy", ["host:cue9"])
    bandit_before = k.data
    _age(k.id, archive.DAYS["erkenntnis"] + 1)
    archive.cleanup()
    h = intuition.before("Bash", {"host": "cue9"}, "b", False)["hinweise"]
    assert len(h) == 1 and h[0].startswith("Matching in the long-term archive:") and k.id in h[0]
    assert "1 entries" in tools.call_tool("vi_lager", {}, "a", True) and "Proxy" in tools.call_tool("vi_lager", {"id": k.id}, "a", True)
    with pytest.raises(tools.Rejected, match="reason"):
        tools.call_tool("vi_lager_hole", {"id": k.id, "grund": ""}, "a", True)
    assert "back in active memory" in tools.call_tool("vi_lager_hole", {"id": k.id, "grund": "wird wieder gebraucht"}, "b", True)
    o = g.load(k.id)
    assert o.mode == "aktiv" and o.text == "cue9 braucht beim Neustart den Proxy" and o.data == bandit_before and "modus:archiviert" not in o.hashtags
    assert archive.content(k.id) is None
    assert any("Proxy" in x for x in intuition.before("Bash", {"host": "cue9"}, "b", False)["hinweise"])
    with pytest.raises(tools.Rejected, match="not in the long-term archive"):
        tools.call_tool("vi_lager_hole", {"id": k.id, "grund": "nochmal"}, "b", True)


def test_private_stays_private_and_delete_works_in_archive(gd):
    a, b = session.begin("a", "t"), session.begin("b", "t")
    with session.on_behalf(a):
        v = intuition.before("t_x", {"host": "p1"}, "a")
        e = intuition.after("t_x", {"host": "p1"}, True, 1, None, "ok", v["vorher_id"], "a")["erfahrung"]
    session.finish(a.id)
    _age(e, archive.DAYS["erfahrung"] + 1)
    _age(f"gespraech:{a.serial}", archive.DAYS_RAW + 1)
    r = archive.cleanup()
    assert r["rohverlaeufe"] == 1 and g.load(e).mode == "archiviert"
    with g.lock:
        assert g.db().execute("SELECT COUNT(*) FROM gespraech_roh WHERE serial = ?", (a.serial,)).fetchone()[0] == 0
    assert "t_x" in tools.call_tool("vi_gespraech", {"serial": a.serial}, "a", True)  # log comes from the archive
    with session.on_behalf(b), pytest.raises(tools.Rejected, match="unknown"):
        tools.call_tool("vi_lager", {"id": e}, "b", True)
    with session.on_behalf(b), pytest.raises(tools.Rejected, match="unknown"):
        tools.call_tool("vi_lager_hole", {"id": e, "grund": "fremd"}, "b", True)
    tools.call_tool("vi_loesche_gespraech", {"serial": a.serial, "grund": "Datenschutz"}, "a", True)
    assert g.load(e) is None and archive.content(e) is None and archive.raw(a.serial) is None
    session.finish(b.id)


def test_open_conversation_stays(gd):
    s = session.begin("a", "t")
    with session.on_behalf(s):
        v = intuition.before("t_y", {}, "a")
        intuition.after("t_y", {}, True, 1, None, "ok", v["vorher_id"], "a")
    session.persist(s)
    _age(f"gespraech:{s.serial}", archive.DAYS_RAW + 1)
    assert archive.cleanup()["rohverlaeufe"] == 0


def test_condense_and_status(gd):
    ids = [_knowledge("x" * 5000 + str(i), [f"thema:t{i}"]).id for i in range(40)]
    for i in ids:
        _age(i, archive.DAYS["erkenntnis"] + 1)
    r = archive.cleanup()
    assert r["eingelagert"] == 40 and r["verdichtet"] is (g.backend() == "sqlite")  # PostgreSQL: autovacuum, no VACUUM
    assert len(archive.content(ids[0])["text"]) > 5000 and len(g.load(ids[0]).text) == archive.STUB_CHARS
    assert "Archive: 40 entries" in tools.call_tool("vi_status", {}, "a", True)


def test_crash_between_files_loses_nothing(gd):
    k = _knowledge("überlebt den Absturz", ["thema:a"])
    with g.lock:
        archive.db().execute("INSERT INTO objekt (id, art, instanz, sicht, eingelagert, modus_vorher, grund, roh) VALUES (?,?,?,?,?,?,?,?)",
                           (k.id, k.kind, k.instance, k.visibility, g.now(), "aktiv", "Absturztest", zlib.compress(json.dumps({"text": "alt", "daten": {}, "hashtags": []}).encode())))
        archive.db().commit()
    assert g.load(k.id).mode == "aktiv"  # source unchanged
    archive.store_in_archive(g.load(k.id), "Wiederholung")  # next run overwrites the duplicate
    assert archive.content(k.id)["text"] == "überlebt den Absturz"


def test_evidence_replaces_automatic_edge_not_vice_versa(gd):
    a = _knowledge("Objekt A zu h8", ["host:h8"])
    b = _knowledge("Objekt B zu h9", ["host:h9"])
    a.link(b.id, "vor der Handlung erinnert")
    a.link(b.id, "Beleg (Test)")
    a.link(b.id, "2 gemeinsame Hashtags")
    assert a.edges() == [(b.id, "Beleg (Test)")]


def test_learn_with_outcome(gd):
    r = tools.call_tool("vi_lerne", {"text": "web7 ist nachts gestört", "hashtags": ["host:web7"], "quelle": "Befund 4711", "ausgang": "schlecht"}, "a", True)
    assert g.load(r.split()[1]).data["ausgang"] == "schlecht"
    with pytest.raises(tools.Rejected, match="outcome"):
        tools.call_tool("vi_lerne", {"text": "web7 ist nachts gestört", "hashtags": ["host:web7"], "quelle": "Befund 4711", "ausgang": "egal"}, "a", True)
