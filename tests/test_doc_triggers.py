"""0.26.0: documentation gets host:/thema: triggers from known hosts and topics, conservatively and without new edges."""
from vi_mcp import doc_triggers, intuition, session
from vi_mcp import memory as g


def _known():
    # outside the documentation: experiences name hosts, learned knowledge names topics (≥ THEMA_MIN objects)
    g.new_object("erfahrung", "Bash on db0137", ["tool:Bash", "host:db0137.example.org", "thema:for"], {"args": {}}, instance="a")
    for i in range(doc_triggers.THEMA_MIN):
        g.new_object("erkenntnis", f"mariadb tmpdir lesson {i}", ["thema:mariadb", "host:web7.example.org"], {"quelle": "x"}, instance="a")


def _doc(text, content, tag="art_wissen:firmendoku"):
    return g.new_object("erkenntnis", text, [tag, "space:002it", "quelle_art:confluence"], {"quelle": "wiki", "inhalt": content},
                        instance="m", visibility="intern")


def test_known_hosts_and_topics_become_triggers(gd):
    _known()
    d = _doc("Confluence IT: MariaDB tmpdir verlegen", "Auf db0137 liegt der tmpdir; web7.example.org nutzt ihn. for loop, newhost99.example.org")
    other = _doc("Confluence IT: Drucker im 3. Stock", "Nichts Technisches hier.")
    r = doc_triggers.run()
    o = g.load(d.id)
    assert {"host:db0137.example.org", "host:web7.example.org", "thema:mariadb"} <= set(o.hashtags)  # short name db0137 resolved
    assert "host:newhost99.example.org" not in o.hashtags  # unknown host: not guessed
    assert "thema:for" not in o.hashtags  # experiences are no topic source
    assert o.data["derived_triggers"]["version"] == doc_triggers.VERSION and any("derived triggers" in c["was"] for c in o.changes)
    assert g.load(other.id).data["derived_triggers"] == {"version": doc_triggers.VERSION, "host": [], "thema": []}
    assert r["geprueft"] == 2 and r["mit_host"] == 1 and r["offen"] == 0
    assert doc_triggers.run()["geprueft"] == 0  # idempotent


def test_no_new_edges_and_at_most_one_doc_hint(gd):
    _known()
    docs = [_doc(f"Confluence IT: MariaDB Seite {i}", "db0137 tmpdir") for i in range(3)]
    with g.lock:
        before = g.db().execute("SELECT COUNT(*) FROM kante").fetchone()[0]
    doc_triggers.run()
    with g.lock:
        assert g.db().execute("SELECT COUNT(*) FROM kante").fetchone()[0] == before
    s = session.begin("a", "t")
    with session.on_behalf(s):
        v = intuition.before("Bash", {"command": "mysql -h db0137.example.org"}, "a", False)
    shown_docs = [i for i in v["zugriff"]["gezeigt"] if i in {d.id for d in docs}]
    assert len(shown_docs) <= intuition.LOOKUP_MAX  # documentation takes at most one slot


def test_limits_per_object(gd):
    for i in range(8):
        g.new_object("erfahrung", f"x{i}", [f"host:app{i:02d}01.example.org"], {"args": {}}, instance="a")
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
