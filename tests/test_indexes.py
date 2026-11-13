"""0.61.0: indexes — every object belongs to exactly one index (column objekt.idx), global unless a project or an explicit index says
otherwise. Block 1: the column, its migration, names and the default."""
import sqlite3

import pytest

from conftest import sqlite_only
from vi_mcp import indexes, tools
from vi_mcp import memory as g


def test_names_are_checked_and_projects_map_to_indexes():
    assert indexes.normalize(" Cue-Print ") == "cue-print" and indexes.normalize("") is None and indexes.normalize(None) is None
    with pytest.raises(ValueError, match="allowed are"):
        indexes.normalize("kunde x/geheim")
    cfg = {"map": {"repo": "cue-stack"}, "ignore": ["scratch"]}
    assert indexes.from_project("cue-print", cfg) == "cue-print"
    assert indexes.from_project("repo", cfg) == "cue-stack"  # mapped
    assert indexes.from_project("scratch", cfg) == indexes.GLOBAL  # ignored by the user
    assert indexes.from_project(".playwright-mcp", cfg) == indexes.GLOBAL  # hidden directories are no projects
    assert indexes.from_project("tmp", cfg) == indexes.GLOBAL and indexes.from_project(None, cfg) == indexes.GLOBAL
    assert indexes.index_for("ansible", "cue-print", cfg) == "ansible"  # explicit wins


def test_new_objects_land_in_global_or_the_given_index(gd):
    a = g.new_object("erkenntnis", "general knowledge", ["thema:a"], {"quelle": "t"})
    b = g.new_object("erkenntnis", "project knowledge", ["thema:a"], {"quelle": "t"}, index="Cue-Print")
    token = g.current_index.set("ansible")
    try:
        c = g.new_object("erkenntnis", "special knowledge", ["thema:a"], {"quelle": "t"})
    finally:
        g.current_index.reset(token)
    assert (g.load(a.id).idx, g.load(b.id).idx, g.load(c.id).idx) == ("global", "cue-print", "ansible")
    assert "index cue-print" in tools.call_tool("vi_object", {"id": b.id}, "a", False)


@sqlite_only
def test_an_old_database_gets_the_column(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.executescript("""CREATE TABLE objekt (id TEXT PRIMARY KEY, art TEXT NOT NULL, zeit TEXT NOT NULL, zuletzt TEXT NOT NULL,
        text TEXT NOT NULL DEFAULT '', daten TEXT NOT NULL DEFAULT '{}', wichtigkeit INTEGER NOT NULL DEFAULT 1,
        bestaetigt INTEGER NOT NULL DEFAULT 0, widerlegt INTEGER NOT NULL DEFAULT 0, zugriffe INTEGER NOT NULL DEFAULT 0,
        modus TEXT NOT NULL DEFAULT 'aktiv', aenderungen TEXT NOT NULL DEFAULT '[]', gespraech TEXT,
        instanz TEXT NOT NULL DEFAULT 'vi', sicht TEXT NOT NULL DEFAULT 'geteilt');
        INSERT INTO objekt (id, art, zeit, zuletzt, text) VALUES ('erkenntnis:old', 'erkenntnis', '2026-01-01', '2026-01-01', 'old');""")
    con.commit()
    con.close()
    g.open_db(p)
    try:
        assert g.load("erkenntnis:old").idx == "global"
        assert g.db().execute("SELECT name FROM sqlite_master WHERE type='index' AND name='objekt_idx'").fetchone()
    finally:
        g.close_db()


def test_a_project_session_puts_its_experiences_and_knowledge_into_its_index(gd, monkeypatch):
    from vi_mcp import intuition, session
    monkeypatch.setattr(indexes, "_config", lambda: {"ignore": ["scratch"]})
    s = session.begin("a", "claude-code-hook 1", "Cue-Print")
    with session.on_behalf(s):
        r = intuition.before("Bash", {"command": "ls"}, "a", False)
        intuition.after("Bash", {"command": "ls"}, True, 5, None, "ok", r["vorher_id"], "a", False)
        k = g.new_object("erkenntnis", "learned in the project", ["thema:a"], {"quelle": "t"}, instance="a")
    e = [o for _, o, _g in g.recall("art:erfahrung", limit=5, viewer=None)][0]
    assert e.idx == "cue-print" and g.load(k.id).idx == "cue-print"
    t = session.begin("a", "claude-code-hook 1", "scratch")
    with session.on_behalf(t):
        assert g.new_object("erkenntnis", "learned in an ignored dir", ["thema:a"], {"quelle": "t"}, instance="a").idx == "global"


def test_vi_learn_takes_index_or_the_project_the_hook_sent(gd, monkeypatch):
    monkeypatch.setattr(indexes, "_config", lambda: {"map": {"repo": "cue-stack"}})
    base = {"text": "a fact worth keeping", "hashtags": ["thema:a"], "source": "unit test of indexes"}
    out = tools.call_tool("vi_learn", {**base, "index": "Ansible"}, "a", False)
    assert g.load(out.split()[1]).idx == "ansible"
    out = tools.call_tool("vi_learn", {**base, "text": "another fact", "project": "repo"}, "a", False)
    assert g.load(out.split()[1]).idx == "cue-stack"
    out = tools.call_tool("vi_lerne", {**base, "text": "third fact", "projekt": "cue-print"}, "a", False)  # German alias
    assert g.load(out.split()[1]).idx == "cue-print"
    out = tools.call_tool("vi_learn", {**base, "text": "fourth fact"}, "a", False)
    assert g.load(out.split()[1]).idx == "global"


def test_search_restricts_to_an_index_or_puts_the_project_first(gd):
    a = g.new_object("erkenntnis", "rsync resume with partial transfers", ["tool:rsync"], {"quelle": "t"}, index="global")
    b = g.new_object("erkenntnis", "rsync resume in the cue project needs partial", ["tool:rsync"], {"quelle": "t"}, index="cue-print")
    only = tools.call_tool("vi_recall", {"filter": "rsync resume", "index": "cue-print", "semantic": False}, "a", False)
    assert b.id in only and a.id not in only and "only index cue-print" in only
    mixed = tools.call_tool("vi_recall", {"filter": "rsync resume", "project": "cue-print", "semantic": False}, "a", False)
    assert mixed.index(b.id) < mixed.index(a.id) and "from index cue-print first" in mixed  # both visible, the project's first
    plain = tools.call_tool("vi_recall", {"filter": "rsync", "semantic": False}, "a", False)
    assert a.id in plain and b.id in plain


def test_hints_before_an_action_put_the_project_first_and_record_it(gd, monkeypatch):
    from vi_mcp import intuition, session
    monkeypatch.setattr(indexes, "_config", lambda: {})
    gen = g.new_object("erkenntnis", "rsync over ssh needs the key file", ["tool:rsync", "thema:ssh"], {"quelle": "t"}, index="global")
    own = g.new_object("erkenntnis", "rsync in cue-print goes through the jump host", ["tool:rsync"], {"quelle": "t"}, index="cue-print")
    s = session.begin("a", "claude-code-hook 1", "cue-print")
    with session.on_behalf(s):
        z = intuition.before("rsync", {"src": "a"}, "a", False)["zugriff"]
    assert z["gezeigt"][0] == own.id and gen.id in z["gezeigt"]  # first, not alone
    assert z["idx"] == "cue-print" and z["idx_vorrang"] == 1


def test_the_agent_session_gets_the_project_the_hook_noted_just_before(gd, monkeypatch):
    # the agent's own MCP session does not know its working directory; the hook calls vi_context right before vi_learn/vi_recall
    from vi_mcp import session
    monkeypatch.setattr(indexes, "_config", lambda: {})
    hook_s = session.begin("a", "claude-code-hook 1", "cue-print")
    agent_s = session.begin("a", "claude-code 2.1", None)
    with session.on_behalf(hook_s):
        assert "noted" in tools.call_tool("vi_context", {}, "a", False)
    base = {"text": "learned by the agent session", "hashtags": ["thema:a"], "source": "unit test of indexes"}
    with session.on_behalf(agent_s):
        out = tools.call_tool("vi_learn", base, "a", False)
    assert g.load(out.split()[1]).idx == "cue-print"
    monkeypatch.setattr(session, "RECENT_S", 0.0)  # too long ago: global, never a guess
    session._recent["a"] = (0.0, "cue-print")
    with session.on_behalf(agent_s):
        out = tools.call_tool("vi_learn", {**base, "text": "learned much later by the agent"}, "a", False)
    assert g.load(out.split()[1]).idx == "global"


def _actions(index, n, hint_helps, h_id, rng):
    """n rsync actions in `index`, half with hint h shown; success depends on whether the hint helps there."""
    for i in range(n):
        shown = i % 2 == 0
        p = 0.9 if (shown and hint_helps) else 0.45 if shown else 0.7
        ok = rng.random() < p
        o = g.new_object("erfahrung", f"rsync {index} {i}", ["tool:rsync", f"ok:{'ja' if ok else 'nein'}"],
                         {"vorher": {"reize": ["tool:rsync"], "gezeigt": [h_id] if shown else []}}, instance="a", index=index)
        assert o.idx == index


def test_an_index_gets_its_own_model_only_when_it_beats_the_shared_one(gd):
    pytest.importorskip("sklearn")
    import random
    from vi_mcp import learning
    rng = random.Random(3)
    h = g.new_object("erkenntnis", "use the jump host for rsync", ["tool:rsync"], {"quelle": "t"}, instance="x")
    _actions("global", 3000, False, h.id, rng)   # elsewhere the hint hurts
    _actions("cue-print", 1200, True, h.id, rng)  # in cue-print it helps
    r = learning.train_index("cue-print", "test")
    assert r["zustand"] == "aktiv", r.get("urteil")
    assert r["gegen_gemeinsam"]["differenz"] < 0 and learning.active("cue-print").id == "modell:router@cue-print"
    assert g.load("modell:router@cue-print").idx == "cue-print"
    small = learning.train_index("tiny", "test")
    assert small["zustand"] == "zu_wenig_daten" and learning.active("tiny") is None
    assert [x["index"] for x in learning.train_indexes("test")] == ["cue-print"]  # global is the shared model, not an index model


def test_an_index_like_all_others_keeps_the_shared_model_and_the_project_ranks_with_its_own(gd, monkeypatch):
    pytest.importorskip("sklearn")
    import random
    from vi_mcp import intuition, learning, session
    monkeypatch.setattr(indexes, "_config", lambda: {})
    rng = random.Random(5)
    h = g.new_object("erkenntnis", "use the jump host for rsync", ["tool:rsync"], {"quelle": "t"}, instance="x")
    _actions("global", 3000, True, h.id, rng)
    _actions("same", 1200, True, h.id, rng)  # behaves like everything else: nothing to gain from an own model
    r = learning.train_index("same", "test")
    assert r["zustand"] == "test" and "not better than the shared model" in r["urteil"] and learning.active("same") is None
    _actions("cue-print", 1200, False, h.id, rng)  # here the hint hurts, unlike elsewhere
    assert learning.train_index("cue-print", "test")["zustand"] == "aktiv"
    s = session.begin("a", "claude-code-hook 1", "cue-print")
    with session.on_behalf(s):
        z = intuition.before("rsync", {"src": "a"}, "a", False)["zugriff"]
    assert z["router"] == "modell@cue-print"


def test_backfill_puts_old_project_data_into_its_index_and_rename_merges(gd, monkeypatch):
    from vi_mcp import session
    monkeypatch.setattr(indexes, "_config", lambda: {"ignore": ["scratch"]})
    s = session.begin("a", "claude-code-hook 1", "cue-print")  # before 0.61.0 the session recorded its project, objects stayed global
    t = session.begin("a", "claude-code-hook 1", "scratch")
    e1 = g.new_object("erfahrung", "rsync 1", ["tool:rsync", "ok:ja"], {}, instance="a", conversation=s.serial, index="global")
    k1 = g.new_object("erkenntnis", "learned in cue-print", ["thema:a"], {"quelle": "t"}, instance="a", conversation=s.serial, index="global")
    e2 = g.new_object("erfahrung", "rsync 2", ["tool:rsync", "ok:ja"], {}, instance="a", conversation=t.serial, index="global")
    dry = indexes.backfill()
    assert dry == {"angewendet": False, "objekte": 2, "je_index": {"cue-print": {"erfahrung": 1, "erkenntnis": 1}}}
    assert g.load(e1.id).idx == "global"  # counting changes nothing
    indexes.backfill(apply=True)
    assert (g.load(e1.id).idx, g.load(k1.id).idx, g.load(e2.id).idx) == ("cue-print", "cue-print", "global")
    assert indexes.rename("cue-print", "cue", "admin", "short name").startswith("2 object(s) moved from index cue-print to cue") and g.load(k1.id).idx == "cue"
    listing = tools.call_tool("vi_indexes", {}, "a", False)
    assert "cue " in listing and "global" in listing
    assert "index cue → ansible" in indexes.move(k1.id, "ansible", "admin", "belongs to the special VI")
    with pytest.raises(ValueError, match="reason"):
        indexes.rename("cue", "x", "admin", "")


def test_the_index_table_has_a_row_for_every_index_with_description_and_tags(gd):
    # the user (13.11.2026): a primary key for the index, one index per object, and a table that gives each index tags and a description
    g.new_object("erkenntnis", "project knowledge", ["thema:a"], {"quelle": "t"}, index="cue-print")
    reg = indexes.registry()
    assert reg["global"]["art"] == "global" and reg["cue-print"]["art"] == "projekt"
    with g.lock:
        orphans = g.db().execute("SELECT DISTINCT idx FROM objekt WHERE idx NOT IN (SELECT name FROM vi_index)").fetchall()
    assert orphans == []  # every index an object refers to has its row
    out = tools.call_tool("vi_indexes", {"index": "ansible", "description": "Ansible roles and playbooks", "tags": ["Team:IT", "ansible"],
                                         "kind": "spezial"}, "a", False)
    assert out == "index ansible (spezial): Ansible roles and playbooks · tags ansible, team:it"
    listing = tools.call_tool("vi_indexes", {}, "a", False)
    assert "ansible" in listing and "(spezial)" in listing and "[tags: ansible, team:it]" in listing  # listed although it holds nothing yet
    with pytest.raises(tools.Rejected, match="kind must be"):
        tools.call_tool("vi_indexes", {"index": "x", "kind": "global"}, "a", False)
    indexes.describe("cue-print", "CUE print stack")
    indexes.rename("cue-print", "cue", "admin", "shorter")
    reg = indexes.registry()
    assert "cue-print" not in reg and reg["cue"]["beschreibung"] == "CUE print stack"  # the row moved with its description
