"""0.26.0: documentation gets host:/thema: triggers from known hosts and topics, conservatively and without new edges."""
from vi_mcp import doc_triggers, intuition, session
from vi_mcp import memory as g


def _known():
    # outside the documentation: experiences name hosts, learned knowledge names topics (≥ THEMA_MIN objects)
    g.new_object("experience", "Bash on db0137", ["tool:Bash", "host:db0137.example.org", "topic:for"], {"args": {}}, instance="a")
    for i in range(doc_triggers.THEMA_MIN):
        g.new_object("insight", f"mariadb tmpdir lesson {i}", ["topic:mariadb", "host:web7.example.org"], {"source": "x"}, instance="a")


def _doc(text, content, tag="knowledge_kind:company-docs"):
    return g.new_object("insight", text, [tag, "space:002it", "source_kind:confluence"], {"source": "wiki", "content": content},
                        instance="m", visibility="internal")


def test_known_hosts_and_topics_become_triggers(gd):
    _known()
    d = _doc("Confluence IT: MariaDB tmpdir verlegen", "Auf db0137 liegt der tmpdir; web7.example.org nutzt ihn. for loop, newhost99.example.org")
    other = _doc("Confluence IT: Drucker im 3. Stock", "Nichts Technisches hier.")
    r = doc_triggers.run()
    o = g.load(d.id)
    assert {"host:db0137.example.org", "host:web7.example.org", "topic:mariadb"} <= set(o.hashtags)  # short name db0137 resolved
    assert "host:newhost99.example.org" not in o.hashtags  # unknown host: not guessed
    assert "topic:for" not in o.hashtags  # experiences are no topic source
    assert o.data["derived_triggers"]["version"] == doc_triggers.VERSION and any("derived triggers" in c["what"] for c in o.changes)
    assert g.load(other.id).data["derived_triggers"] == {"version": doc_triggers.VERSION, "host": [], "topic": []}
    assert r["geprueft"] == 2 and r["mit_host"] == 1 and r["offen"] == 0
    assert doc_triggers.run()["geprueft"] == 0  # idempotent


def test_no_new_edges_and_at_most_one_doc_hint(gd):
    _known()
    docs = [_doc(f"Confluence IT: MariaDB Seite {i}", "db0137 tmpdir") for i in range(3)]
    with g.lock:
        before = g.db().execute("SELECT COUNT(*) FROM edge").fetchone()[0]
    doc_triggers.run()
    with g.lock:
        assert g.db().execute("SELECT COUNT(*) FROM edge").fetchone()[0] == before
    s = session.begin("a", "t")
    with session.on_behalf(s):
        v = intuition.before("Bash", {"command": "mysql -h db0137.example.org"}, "a", False)
    shown_docs = [i for i in v["zugriff"]["shown"] if i in {d.id for d in docs}]
    assert len(shown_docs) <= intuition.LOOKUP_MAX  # documentation takes at most one slot


def test_limits_per_object(gd):
    for i in range(8):
        g.new_object("experience", f"x{i}", [f"host:app{i:02d}01.example.org"], {"args": {}}, instance="a")
    d = _doc("Confluence IT: viele Hosts", " ".join(f"app{i:02d}01.example.org" for i in range(8)))
    doc_triggers.run()
    assert len([t for t in g.load(d.id).hashtags if t.startswith("host:")]) == doc_triggers.HOST_MAX


def test_too_common_triggers_and_link_hosts_are_skipped(gd, monkeypatch):
    _known()
    monkeypatch.setattr(doc_triggers, "DF_MIN_DOCS", 10)
    docs = [_doc(f"Stibo DX – mariadb: Seite {i}", f"see https://web7.example.org/page{i} for details") for i in range(60)]
    special = _doc("Confluence IT: db0137 Wartung", "db0137 tmpdir")
    r = doc_triggers.run()
    assert "mariadb" in r["zu_haeufig"]  # in every Stibo title: says nothing specific
    assert not any(t.startswith("host:") for t in g.load(docs[0].id).hashtags)  # host only in a link
    assert "host:db0137.example.org" in g.load(special.id).hashtags


def test_imported_docs_only_via_exploration_manuals_regularly(gd, monkeypatch):
    # 0.57.1: company and vendor documentation is no regular hint before an action (measured negative), a skill manual still is
    import random
    monkeypatch.setattr(random, "random", lambda: 0.99)  # no exploration in this action
    _known()
    company = _doc("Confluence IT: db0137 Wartung", "db0137 wird freitags gewartet")
    company.hashtags = company.hashtags + ["topic:mysql"]
    g.save(company)
    manual = g.new_object("insight", "Handbuch mysql: Verbindung zu db0137", ["knowledge_kind:manual", "topic:mysql"], {"source": "skills"}, instance="m")
    s = session.begin("a", "t")
    with session.on_behalf(s):
        v = intuition.before("Bash", {"command": "mysql -h db0137.example.org"}, "a", False)
    assert manual.id in v["zugriff"]["shown"] and company.id not in v["zugriff"]["shown"]
    assert company.id in v["zugriff"]["offer"] and 0 < v["zugriff"]["offer"][company.id] < 1  # offered with a propensity: still measured


def test_system_topics_are_never_derived_and_never_a_users_decision(gd):
    """0.70.10: topic:requirement means "the user decided" (rule 6). Learned knowledge uses it, so before, every page with the word
    "requirement" got it (production 19.11.2026: Stack Exchange questions filled the index section of the user's decisions)."""
    from vi_mcp import index
    for i in range(doc_triggers.THEMA_MIN):
        g.new_object("insight", f"user requirement {i}: always ask before pushing", ["topic:requirement", "topic:mariadb"], {"source": "x"},
                     instance="a")
    d = _doc("Stack Exchange ops: mariadb tee with echo as per this requirement", "the requirement is to append a variable")
    doc_triggers.run()
    o = g.load(d.id)
    assert "topic:mariadb" in o.hashtags and "topic:requirement" not in o.hashtags
    # an older derivation that set it is taken off on the next refresh
    o.hashtags = sorted(set(o.hashtags) | {"topic:requirement"})
    o.data["derived_triggers"] = {"version": 2, "host": [], "topic": ["requirement", "mariadb"]}
    g.save(o)
    assert doc_triggers.run()["geprueft"] == 1 and "topic:requirement" not in g.load(d.id).hashtags  # sleep takes it along
    assert doc_triggers.run()["geprueft"] == 0  # and only once
    o = g.load(d.id)
    o.hashtags = sorted(set(o.hashtags) | {"topic:requirement"})
    o.data["derived_triggers"] = {"version": 2, "host": [], "topic": ["requirement", "mariadb"]}
    g.save(o)
    assert "-topic:requirement" in doc_triggers.refresh(g.load(d.id)) and "topic:requirement" not in g.load(d.id).hashtags
    # a page tagged topic:requirement by hand keeps it (not derived), is not taken again by sleep, and never fills the decisions section
    o = g.load(d.id)
    o.hashtags = sorted(set(o.hashtags) | {"topic:requirement"})
    g.save(o)
    assert doc_triggers.run()["geprueft"] == 0 and "topic:requirement" in g.load(d.id).hashtags
    req = [x.id for x in index.sections("a")["vorgaben"]]
    assert d.id not in req and len(req) >= 1
