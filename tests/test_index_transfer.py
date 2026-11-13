"""0.62.0: an index into a signed file and back — the same content measured on two servers, compared per content."""
import json

import pytest

from vi_mcp import index_transfer as it
from vi_mcp import indexes, net_score, p2p
from vi_mcp import memory as g


def _knowledge(text, index, yes=0.0, no=0.0, **kw):
    o = g.new_object("erkenntnis", text, ["thema:deploy", "tool:dpkg"], {"quelle": "test 2026-11-13", "inhalt": f"full content of: {text}",
                                                                          "nuetzlich": {"ja": yes, "nein": no, "n": int(yes + no)}},
                     index=index, visibility=kw.pop("visibility", "intern"), instance=kw.pop("instance", "claude-code"), **kw)
    return o


def _set_measurement(oid, yes, no):
    o = g.load(oid)
    o.data = {**o.data, "nuetzlich": {"ja": yes, "nein": no, "n": int(yes + no)}}
    g.save(o)


@pytest.fixture()
def two(tmp_path, monkeypatch):
    """Two servers in turn: switch(name) opens that server's database and export key."""
    def switch(name):
        g.close_db()
        monkeypatch.setenv("VI_MCP_EXPORT_KEY", str(tmp_path / f"{name}.key"))
        g.open_db(tmp_path / f"{name}.db")
    monkeypatch.setenv("VI_MCP_EXPORT_KEY", str(tmp_path / "a.key"))
    g.open_db(tmp_path / "a.db")
    yield switch
    g.close_db()


def test_export_holds_only_the_knowledge_of_the_index_and_counts_the_rest(two, tmp_path):
    good = _knowledge("vi-mcp deploy: back up config and database before dpkg -i", "proj", 12, 1)
    _knowledge("other project knowledge", "other")
    g.new_object("erkenntnis", "a private note", ["thema:deploy"], {"quelle": "t"}, index="proj", visibility="privat")
    g.new_object("erkenntnis", "def f(): pass", ["art_wissen:code", "datei:x.py"], {"quelle": "t"}, index="proj", visibility="intern")
    g.new_object("erfahrung", "Bash ok", ["tool:Bash"], {"quelle": "t"}, index="proj")
    r = it.export("proj", tmp_path / "proj.json")
    assert r["eintraege"] == 1 and r["eigen"] == 1
    assert r["ausgelassen"] == {"private": 1, "code piece (index import-code brings code)": 1, "kind erfahrung is not exported": 1}
    doc = json.loads((tmp_path / "proj.json").read_text())
    assert doc["eintraege"][0]["form"]["text"] == good.text and doc["eintraege"][0]["messung"]["ja"] == 12
    assert doc["eintraege"][0]["inhalt_sha"] == net_score.content_hash(net_score.local_form(g.load(good.id)))
    # internal file: no instance name, no conversation, no index-internal ids leave the server
    raw = (tmp_path / "proj.json").read_text()
    assert "claude-code" not in raw and good.id not in raw and "netz_id" not in raw
    assert (tmp_path / "proj.json").stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="nothing to export"):
        it.export("empty", tmp_path / "e.json")


def test_a_changed_file_is_refused_before_anything_is_stored(two, tmp_path):
    _knowledge("vi-mcp deploy: back up config and database before dpkg -i", "proj", 12, 1)
    it.export("proj", tmp_path / "proj.json")
    doc = json.loads((tmp_path / "proj.json").read_text())
    doc["eintraege"][0]["messung"]["ja"] = 999
    (tmp_path / "bad.json").write_text(json.dumps(doc))
    two("b")
    with pytest.raises(ValueError, match="signature invalid"):
        it.import_file(tmp_path / "bad.json", "proj-b")
    with g.lock:
        assert g.db().execute("SELECT COUNT(*) FROM objekt WHERE idx = 'proj-b'").fetchone()[0] == 0
    two("a")
    with pytest.raises(ValueError, match="comes from this server"):
        it.import_file(tmp_path / "proj.json", "proj2")


def test_import_quarantines_internal_and_books_the_origin_measurement_once(two, tmp_path):
    _knowledge("vi-mcp deploy: back up config and database before dpkg -i", "proj", 12, 1)
    indexes.describe("proj", "the vi-mcp project", ["python", "mcp"], "projekt")
    it.export("proj", tmp_path / "proj.json")
    two("b")
    r = it.import_file(tmp_path / "proj.json", "proj-b", in_background=False)
    assert (r["neu"], r["dedupliziert"], r["bewertungen"], r["abgelehnt"]) == (1, 0, 1, 0)
    with g.lock:
        oid = g.db().execute("SELECT id FROM objekt WHERE idx = 'proj-b' AND art = 'erkenntnis'").fetchone()[0]
    o = g.load(oid)
    assert o.mode == "quarantaene" and o.visibility == "intern" and o.data["herkunft"]["netz"] == p2p.FILE_NET
    reg = indexes.registry()["proj-b"]
    assert reg["beschreibung"] == "the vi-mcp project" and reg["tags"] == ["mcp", "python"] and reg["quelle"].startswith("import vi-")
    again = it.import_file(tmp_path / "proj.json", "proj-b", in_background=False)
    assert (again["neu"], again["dedupliziert"]) == (0, 1)
    with g.lock:
        assert g.db().execute("SELECT COUNT(*) FROM objekt WHERE idx = 'proj-b' AND art = 'erkenntnis'").fetchone()[0] == 1
    # the exporter wrote it: a holder, so its own measurement does not count in the network score
    s = net_score.score(net_score.hash_of(oid), o)
    assert s["halter"] == 1 and s["selbstbewertungen_ignoriert"] == 1


def test_the_way_back_compares_both_places_and_moves_the_priority(two, tmp_path):
    a = _knowledge("vi-mcp deploy: back up config and database before dpkg -i", "proj", 30, 1)
    it.export("proj", tmp_path / "a.json")
    two("b")
    it.import_file(tmp_path / "a.json", "proj-b", in_background=False)
    with g.lock:
        oid_b = g.db().execute("SELECT id FROM objekt WHERE idx = 'proj-b' AND art = 'erkenntnis'").fetchone()[0]
    o = g.load(oid_b)
    o.mode = "aktiv"  # what the reviewer's release does
    g.save(o)
    _set_measurement(oid_b, 1, 25)  # at B the same content does not help
    r = it.compare("proj-b")
    assert r["klassen"]["nur_ursprung"] == 1 and r["vorrang_aus_neu"] == 1
    o = g.load(oid_b)
    assert o.data["vorrang_aus"]["grund"].startswith("good only at its origin")
    assert not indexes.first(o, "proj-b") and indexes.first(g.load(oid_b), None) is False
    assert any("index files: 1 content(s) imported" in z for z in indexes.lines())
    exp_b = it.export("proj-b", tmp_path / "b.json")
    assert exp_b["eintraege"] == 1 and exp_b["eigen"] == 0
    two("a")
    back = it.import_file(tmp_path / "b.json", "proj", in_background=False)
    assert (back["neu"], back["dedupliziert"], back["bewertungen"]) == (0, 1, 1)  # no copy, only B's measurement
    ra = it.compare("proj")
    assert ra["klassen"]["nur_ursprung"] == 1 and ra["vorrang_aus_neu"] == 0  # the origin keeps its priority
    s = net_score.score(net_score.hash_of(a.id), g.load(a.id))
    assert s["bewerter"] == 1 and s["score"] < 0.2  # B's measurement counts in the score …
    assert not s["ausgeblendet"] and not net_score.hidden(g.load(a.id))  # … but never hides A's own knowledge at A
    assert "nur_ursprung 1" in it.stats_line()
    # B recovers: the next comparison gives the priority back
    two("b")
    _set_measurement(oid_b, 30, 2)
    r2 = it.compare("proj-b")
    assert r2["klassen"]["allgemein"] == 1 and r2["vorrang_wieder_an"] == 1 and "vorrang_aus" not in g.load(oid_b).data


@pytest.mark.parametrize("origin, target, cls", [
    ((30, 1), (25, 2), "allgemein"),
    ((30, 1), (1, 25), "nur_ursprung"),
    ((1, 25), (30, 1), "nur_ziel"),
    ((1, 25), (2, 30), "schwach"),
    ((6, 5), (30, 1), "unentschieden"),
    ((3, 2), (30, 1), "zu_wenig"),
])
def test_classes(origin, target, cls):
    assert it.classify(origin, target) == cls


def test_the_way_back_finds_own_contents_that_share_a_generic_text(two, tmp_path):
    """Found in the real test (13.11.2026): 40 of 180 contents came back as copies — many objects shared the text "What is missing",
    and find_local checked only the first 20 with that text. Now content narrows it first."""
    for i in range(25):
        g.new_object("erkenntnis", "vi-mcp changelog: What is missing", ["thema:vi-mcp"],
                     {"quelle": "CHANGELOG.md", "inhalt": f"gap number {i}", "nuetzlich": {"ja": 12, "nein": 1, "n": 13}},
                     index="proj", visibility="intern", instance="claude-code")
    it.export("proj", tmp_path / "a.json")
    two("b")
    it.import_file(tmp_path / "a.json", "proj-b", in_background=False)
    with g.lock:
        for (oid,) in g.db().execute("SELECT id FROM objekt WHERE idx = 'proj-b' AND art = 'erkenntnis'").fetchall():
            o = g.load(oid)
            o.mode = "aktiv"
            g.save(o)
    it.export("proj-b", tmp_path / "b.json")
    two("a")
    back = it.import_file(tmp_path / "b.json", "proj", in_background=False)
    assert (back["neu"], back["dedupliziert"]) == (0, 25)
