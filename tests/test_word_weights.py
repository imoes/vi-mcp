"""0.62.0: weights per word — the meaning layer of VIL, exchanged between memories as signed ratings, the word never in clear."""
import pytest

pytest.importorskip("cryptography")

from vi_mcp import p2p, tools, word_weights  # noqa: E402
from vi_mcp import memory as g  # noqa: E402

from test_net_score import _pub, _rating  # noqa: E402
from test_p2p import _bundle, _key  # noqa: E402


def _k(text, tags, yes, no, **kw):
    return g.new_object("erkenntnis", text, tags, {"quelle": "t", "nuetzlich": {"ja": yes, "nein": no, "n": int(yes + no)}},
                        visibility=kw.pop("visibility", "intern"), instance="a", **kw)


def _seed():
    a = _k("reload nginx after a config change", ["tool:nginx", "host:web1.example", "answers:how"], 8, 2)
    b = _k("nginx config syntax check", ["tool:nginx", "answers:how"], 4, 0)
    c = _k("nginx version on web2", ["tool:nginx", "host:web2.example", "answers:what"], 1, 5)
    return a, b, c


def test_compute_own_weights_per_word_and_question_type(gd):
    _seed()
    r = word_weights.compute()
    assert r["woerter"] >= 5
    assert word_weights.own("tool:nginx") == (13.0, 7.0)
    assert word_weights.own("tool:nginx", "how") == (12.0, 2.0) and word_weights.own("tool:nginx", "what") == (1.0, 5.0)
    assert word_weights.combined("tool:nginx", "how")["gewicht"] == round(13 / 16, 3)


def test_outgoing_never_sends_host_names_or_internals_to_an_open_network(gd, monkeypatch):
    _seed()
    word_weights.compute()
    hosts = {word_weights.word_hash("host:web1.example", q) for q in ("any", "how")}
    open_ = {x["ziel"] for x in word_weights.outgoing("standard")}
    assert word_weights.word_hash("tool:nginx", "any") in open_ and not (hosts & open_)
    monkeypatch.setattr(p2p, "is_company", lambda net: True)
    company = {x["ziel"] for x in word_weights.outgoing("firma")}
    assert hosts & company
    assert all(set(x) == {"ziel", "gezeigt", "ja", "nein", "bestaetigt", "widerlegt"} for x in word_weights.outgoing("standard"))


def test_a_foreign_word_weight_arrives_signed_and_changes_the_combined_weight_and_the_order(gd, monkeypatch):
    monkeypatch.setattr(p2p, "config", {})
    a, b, c = _seed()
    word_weights.compute()
    h = word_weights.word_hash("host:web2.example", "how")
    other = _key()[0]
    unknown = "e" * 64  # a word we do not know: an ordinary content rating, as before
    r = p2p.inbox(_bundle(other, [_rating(word_weights.word_hash("host:web1.example", "how"), ja=0, nein=20), _rating(unknown, ja=1)],
                          type_="bewertung"), in_background=False)
    assert r["wortgewichte"] == 1 and r["bewertungen"] == 1
    w = word_weights.combined("host:web1.example", "how")
    assert w["netz"] == 1 and w["gewicht"] < round((1 + 8) / (2 + 10), 3)  # the other server found the word unhelpful for how-questions
    assert word_weights.own("host:web2.example", "how") == (0.0, 0.0) and not word_weights.known_hash(h)  # web2 has no how-knowledge
    assert word_weights.receive(_rating(word_weights.word_hash("host:web1.example", "how"), ja=99), _pub(other), "standard", 1)  # older seq
    assert word_weights.combined("host:web1.example", "how")["netz"] == 1


def test_word_weights_reorder_only_in_the_measuring_mode_and_vocabulary_shows_them(gd):
    from vi_mcp import vil
    good = _k("deploy with the pipeline", ["thema:deploy", "tool:gitlab"], 9, 1)
    poor = _k("deploy by hand over ssh", ["thema:deploy", "tool:scp"], 1, 9)
    word_weights.compute()
    ids = lambda t: [line.split("]")[0].strip(" [") for line in t.splitlines()[1:] if line.startswith("  [")]  # noqa: E731
    plain = tools.call_tool("vi_recall", {"filter": "deploy", "semantic": False, "reinforce": False}, "a", False)
    out = tools.call_tool("vi_recall", {"filter": "ask.what deploy", "semantic": False, "reinforce": False}, "a", False)
    assert ids(out) == ids(plain)  # default: the weights do not reorder (measured harmful on a production copy, vil.ORDER)
    hits = [(0, g.load(poor.id), 0), (0, g.load(good.id), 0)]
    assert [h[1].id for h in vil.order(hits, "what", "labels+weights")] == [good.id, poor.id]  # the measuring mode uses them
    # no word has a measurement for what-questions: the overall weight decides, not chance
    assert word_weights.hit_weight(g.load(good.id), "what") > word_weights.hit_weight(g.load(poor.id), "what")
    assert word_weights.weight_for("tool:gitlab", "what") == word_weights.combined("tool:gitlab", "any")["gewicht"]
    assert "tool:gitlab  (1)  · weight 0.833 (10 ratings)" in tools.call_tool("vi_vocabulary", {"word_kind": "tool"}, "a", False)
