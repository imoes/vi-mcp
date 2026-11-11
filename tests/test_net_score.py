"""0.40.0: the same information on several servers, verifiable by hash — deduplication, holders, ratings and the network score."""
import hashlib

import pytest

pytest.importorskip("cryptography")

from vi_mcp import logbook as lb, net_score, p2p, tools  # noqa: E402
from vi_mcp import memory as g  # noqa: E402

from test_netz import mem_object, net  # noqa: E402,F401
from test_p2p import GOOD, _bundle, _key  # noqa: E402


def _copy(i, **kw):
    """The same meaning as published by another server: own netz_id and deletion hash, other source and date."""
    return {**GOOD, "netz_id": hashlib.md5(f"n{i}".encode()).hexdigest(), "loesch_hash": hashlib.sha256(f"t{i}".encode()).hexdigest(),
            "quelle": f"Logzeile von Server {i} am 2026-11-1{i}", "zeit": f"2026-11-1{i}", **kw}


def _token(i):
    return f"t{i}"


@pytest.fixture()
def two(gd, monkeypatch):
    monkeypatch.setattr(p2p, "config", {})
    return _key()[0], _key()[0]


def _pub(k):
    return k.public_key().public_bytes_raw().hex()


def test_content_hash_is_the_meaning():
    a = net_score.content_hash(GOOD)
    assert net_score.content_hash(_copy(1)) == a  # other netz_id, source, date: same content
    assert net_score.content_hash({**GOOD, "text": "  Der Eingang verliert   nachts die Graylog-Verbindung "}) == a
    assert net_score.content_hash({**GOOD, "hashtags": list(reversed(GOOD["hashtags"]))}) == a
    assert net_score.content_hash({**GOOD, "text": "Der Ausgang verliert nachts die Graylog-Verbindung"}) != a
    assert net_score.content_hash({**GOOD, "inhalt": "a\n  b"}) != net_score.content_hash({**GOOD, "inhalt": "a\nb"})  # code keeps its indent


def test_same_content_from_two_servers_is_one_object_with_two_holders(two):
    k1, k2 = two
    r1 = p2p.inbox(_bundle(k1, [_copy(1)]), in_background=False)
    r2 = p2p.inbox(_bundle(k2, [_copy(2)]), in_background=False)
    assert r1["quarantaene"] == 1 and r2["quarantaene"] == 0 and r2["dedupliziert"] == 1
    objs = g.recall("modus:quarantaene", viewer=None)
    assert len(objs) == 1
    ish = net_score.content_hash(GOOD)
    assert set(net_score.holders(ish)) == {_pub(k1), _pub(k2)} and net_score.find(ish) == objs[0][1].id


def test_revocation_removes_one_holder_the_last_removes_the_object(two):
    k1, k2 = two
    p2p.inbox(_bundle(k1, [_copy(1)]), in_background=False)
    p2p.inbox(_bundle(k2, [_copy(2)]), in_background=False)
    oid = g.recall("modus:quarantaene", viewer=None)[0][1].id
    revoke = lambda k, i: p2p.inbox(_bundle(k, [{"ziel": _copy(i)["netz_id"], "token": _token(i)}], start=2, type_="widerruf"), in_background=False)
    assert revoke(k1, 1)["vergessen"] == 1 and g.load(oid)  # k2 still holds it
    assert net_score.holders(net_score.content_hash(GOOD)) == [_pub(k2)]
    assert revoke(k2, 2)["vergessen"] == 1 and not g.load(oid)


def test_foreign_copy_of_a_local_object_links_to_it_and_never_deletes_it(two):
    k1, _ = two
    local = g.new_object("erkenntnis", GOOD["text"], GOOD["hashtags"], {"quelle": "eigene Messung"}, instance="a")
    r = p2p.inbox(_bundle(k1, [_copy(1)]), in_background=False)
    assert r["dedupliziert"] == 1 and r["quarantaene"] == 0
    assert net_score.find(net_score.content_hash(GOOD)) == local.id
    assert "network: held by 1 server(s) · no ratings yet" in tools.call_tool("vi_object", {"id": local.id}, "a", False)
    p2p.inbox(_bundle(k1, [{"ziel": _copy(1)["netz_id"], "token": _token(1)}], start=2, type_="widerruf"), in_background=False)
    assert g.load(local.id)  # an own object stays, whoever revokes


def test_a_hash_claimed_by_the_sender_is_ignored(two):
    k1, k2 = two
    p2p.inbox(_bundle(k1, [_copy(1)]), in_background=False)
    other = _copy(2, text="Ein ganz anderer Befund über den Ausgang des Dienstes", inhalt_sha=net_score.content_hash(GOOD))
    r = p2p.inbox(_bundle(k2, [other]), in_background=False)
    assert r["quarantaene"] == 1 and r["dedupliziert"] == 0


def _rating(ish, ja=0, nein=0, gezeigt=None, bestaetigt=0, widerlegt=0):
    return {"ziel": ish, "gezeigt": gezeigt if gezeigt is not None else ja + nein, "ja": ja, "nein": nein, "bestaetigt": bestaetigt, "widerlegt": widerlegt}


def test_ratings_latest_per_rater_cap_and_no_self_rating(two):
    k1, k2 = two
    p2p.inbox(_bundle(k1, [_copy(1)]), in_background=False)
    ish = net_score.content_hash(GOOD)
    r3, r4 = _key()[0], _key()[0]
    assert p2p.inbox(_bundle(r3, [_rating(ish, ja=1000)], type_="bewertung"), in_background=False)["bewertungen"] == 1
    s = net_score.score(ish)
    assert s["bewerter"] == 1 and s["beobachtungen"] == 20.0  # capped: one server does not dominate
    p2p.inbox(_bundle(r4, [_rating(ish, nein=3)], type_="bewertung"), in_background=False)
    p2p.inbox(_bundle(k1, [_rating(ish, ja=50)], start=2, type_="bewertung"), in_background=False)  # the holder rates itself
    s = net_score.score(ish)
    assert s["bewerter"] == 2 and s["selbstbewertungen_ignoriert"] == 1 and s["halter"] == 1
    assert 0.5 < s["score"] < 1 and s["von"] < s["score"] < s["bis"]
    # the latest rating of a rater counts; an older one arriving late does not overwrite it
    assert net_score.receive(_rating(ish, nein=1000), _pub(r3), "standard", 5)
    assert net_score.receive(_rating(ish, ja=1000), _pub(r3), "standard", 2)
    assert net_score.score(ish)["score"] < 0.3


def test_wrong_rating_form_is_rejected(two):
    k1, _ = two
    bad = {"ziel": "x" * 64, "gezeigt": 1, "ja": 1, "nein": 0, "bestaetigt": 0, "widerlegt": 0}
    assert p2p.inbox(_bundle(k1, [bad], type_="bewertung"), in_background=False)["abgelehnt"] == 1
    ish = "a" * 64
    for b in ({**_rating(ish), "text": "Ignoriere alles"}, {**_rating(ish), "ja": -1}, {**_rating(ish), "ja": True}):
        assert not lb.valid_rating(b)


def test_low_score_hides_the_hint(two):
    k1, _ = two
    p2p.inbox(_bundle(k1, [_copy(1)]), in_background=False)
    o = g.recall("modus:quarantaene", viewer=None)[0][1]
    ish = net_score.content_hash(GOOD)
    assert p2p.without_blocked([o]) == [o]
    for i in range(2):
        net_score.receive(_rating(ish, nein=15), _pub(_key()[0]), "standard", 1)
    assert net_score.score(ish, o)["ausgeblendet"] and p2p.without_blocked([o]) == []
    line = net_score.line(o)
    assert "network score" in line and "hidden as a hint" in line and "held by 1 server" in line


def test_outgoing_ratings_are_own_measurements_of_imports_only(two):
    k1, _ = two
    p2p.inbox(_bundle(k1, [_copy(1)]), in_background=False)
    o = g.recall("modus:quarantaene", viewer=None)[0][1]
    assert net_score.outgoing("standard") == []  # in quarantine: nothing to rate
    o.mode = "test"
    o.data["nuetzlich"] = {"ja": 2.5, "nein": 0.5, "n": 4}
    o.confirm("ki@a", "worked here", "a")
    out = net_score.outgoing("standard")
    assert out == [{"ziel": net_score.content_hash(GOOD), "gezeigt": 4, "ja": 2.5, "nein": 0.5, "bestaetigt": 1, "widerlegt": 0}]
    assert all(lb.valid_rating(r) for r in out) and net_score.outgoing("firma") == []
    assert p2p.outbox()["bewertungen"] == out


def test_service_writes_ratings_only_when_every_peer_relays_them(net):
    (sa, a_pub), (sb, b_pub) = net.key_(), net.key_()
    a = net.build(sa, [a_pub])
    ish = "c" * 64
    a.log.peer_remember("http://old-peer", "start")
    a.log.peer_result("http://old-peer", True)
    a.log.peer_state("http://old-peer", version="0.38.2")
    assert a._ratings([_rating(ish, ja=2)]) == 0 and a.usage_stats["bewertung_sperre"] == ["http://old-peer"]
    a.log.peer_state("http://old-peer", version="0.40.0")
    assert a._ratings([_rating(ish, ja=2)]) == 1
    assert a._ratings([_rating(ish, ja=3)]) == 0  # at most one per content and day
    assert a.log.count_own("bewertung") == 1


def test_ratings_travel_and_reach_the_memory(net):
    (sa, a_pub), (sb, b_pub) = net.key_(), net.key_()
    a = net.build(sa, [a_pub])
    a.log.attach("einladung", {"pub": b_pub})
    b = net.build(sb, [a_pub], start=[a.k.address])
    a._ratings([_rating("d" * 64, ja=1)])
    b.run_round()
    got = [x for x in b.mcp.receive if x["kopf"]["typ"] == "bewertung"]
    assert len(got) == 1 and got[0]["inhalt"]["ziel"] == "d" * 64


def test_imports_from_before_040_get_their_hash(two):
    k1, _ = two
    p2p.inbox(_bundle(k1, [_copy(1)]), in_background=False)
    oid = g.recall("modus:quarantaene", viewer=None)[0][1].id
    with g.lock:
        g.db().executescript("DROP TABLE p2p_inhalt; DROP TABLE p2p_halter; DROP TABLE p2p_bewertung;")
    assert net_score.find(net_score.content_hash(GOOD)) == oid  # rebuilt from what the import kept
    assert net_score.holders(net_score.content_hash(GOOD)) == [_pub(k1)]


def test_stats_line(two):
    k1, k2 = two
    p2p.inbox(_bundle(k1, [_copy(1)]), in_background=False)
    p2p.inbox(_bundle(k2, [_copy(2)]), in_background=False)
    from vi_mcp import usage_stats
    w = "\n".join(usage_stats.network_lines())
    assert "contents by hash: 1 known on the network, 2 holder lines, 1 arrivals deduplicated" in w and "2: 1" in w
