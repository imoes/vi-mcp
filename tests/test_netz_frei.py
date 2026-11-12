"""0.45.0: the free network (art frei) — anyone may join, no invitation; identity proof instead, growing quotas, local blocks,
peer exchange from a seed, a mesh that keeps running without its seed."""
import json
import time

import pytest

pytest.importorskip("cryptography")

from vi_mcp import logbook as lb, net_cli, net_service as nd, p2p  # noqa: E402
from vi_mcp import memory as g  # noqa: E402

from test_netz import mem_object, net, _log  # noqa: E402,F401

BITS = 8  # tests: cheap work; production default lb.DEFAULT_POW_BITS


def _free(net, start=(), mode="peerhost", **kw):
    seed, _pub = net.key_()
    return net.build(seed, [], mode=mode, start=list(start), kind="frei", net="welt", pow_bits=BITS, private_ok=True, **kw)


def _rounds(nodes, n=3):
    for _ in range(n):
        for x in nodes:
            x.run_round()


def test_proof_of_work():
    pub = "ab" * 32
    nonce = lb.solve_pow(pub, 12)
    assert lb.pow_ok(pub, nonce, 12) and not lb.pow_ok("cd" * 32, nonce, 12) and not lb.pow_ok(pub, nonce, 40)
    assert lb.valid_control_form("identitaet", {"pub": pub, "nonce": nonce, "bits": 12})
    assert not lb.valid_control_form("identitaet", {"pub": pub, "nonce": nonce + 1, "bits": 12}) or lb.pow_ok(pub, nonce + 1, 12)


def test_servers_join_without_invitation_and_find_each_other(net):
    a = _free(net)
    b = _free(net, start=[a.k.address])
    c = _free(net, start=[a.k.address])
    for x in (a, b, c):
        assert x.log.status()["identitaeten"] == 1  # the own identity proof is entry 1
    b.mcp.mem_objects.append(mem_object(1))
    _rounds([a, b, c])
    assert c.mcp.texts() == [mem_object(1)["text"]]  # nobody invited anybody
    assert b.k.address in {p["adresse"] for p in c.log.peers()}  # C learned B through the peer exchange with A
    assert {b.log.pub, c.log.pub, a.log.pub} <= a.log.members()


def test_the_mesh_runs_on_without_its_seed(net):
    a = _free(net)
    b = _free(net, start=[a.k.address])
    c = _free(net, start=[a.k.address])
    _rounds([a, b, c])
    a.stop_service()
    c.mcp.mem_objects.append(mem_object(2))
    for _ in range(3):
        b.run_round()
        c.run_round()
    assert b.mcp.texts() == [mem_object(2)["text"]]


def _entries(log, items):
    out, prev = [], None
    for seq, typ, content in items:
        h = {"v": 1, "pub": log.pub, "seq": seq, "vor": prev, "typ": typ, "sha": lb.sha256(content), "zeit": time.strftime("%Y-%m-%d", time.gmtime()),
             **({"netz_id": content["netz_id"], "loesch_hash": content["loesch_hash"]} if typ == "objekt" else {})}
        h["sig"] = log.k.sign(lb.canonical(h)).hex()
        out.append({"kopf": h, "inhalt": content})
        prev = lb.entry_hash(h)
    return out


def _free_log(tmp_path, name, **kw):
    seed = tmp_path / f"s{name}"
    lb.generate_keys(seed)
    return lb.Logbook(tmp_path / f"{name}.db", seed, [], free_bits=BITS, **kw)


def test_without_identity_proof_nothing_is_accepted(tmp_path):
    receiver = _free_log(tmp_path, "r")
    spammer = _free_log(tmp_path, "x")
    r = receiver.ingest(_entries(spammer, [(1, "objekt", mem_object(1))]))
    assert r["neu"] == 0 and "no identity proof" in r["gruende"][0]
    weak = {"pub": spammer.pub, "nonce": lb.solve_pow(spammer.pub, 2), "bits": 2}  # too little work for this network
    r = receiver.ingest(_entries(spammer, [(1, "identitaet", weak)]))
    assert r["neu"] == 0 and "unusable" in r["gruende"][0]
    good = {"pub": spammer.pub, "nonce": lb.solve_pow(spammer.pub, BITS), "bits": BITS}
    r = receiver.ingest(_entries(spammer, [(1, "identitaet", good), (2, "objekt", mem_object(1))]))
    assert r["neu"] == 2 and receiver.is_member(spammer.pub)


def test_unknown_publishers_get_a_small_quota_measured_useful_ones_the_full(tmp_path):
    trusted = set()
    receiver = _free_log(tmp_path, "r", quota_of=lambda pub: lb.MAX_PER_DAY if pub in trusted else 3)
    w = _free_log(tmp_path, "w")
    ident = {"pub": w.pub, "nonce": lb.solve_pow(w.pub, BITS), "bits": BITS}
    items = [(1, "identitaet", ident)] + [(i + 2, "objekt", mem_object(i)) for i in range(5)]
    r = receiver.ingest(_entries(w, items))
    assert r["neu"] == 3 and "daily quota" in r["gruende"][0]
    trusted.add(w.pub)
    assert receiver.ingest(_entries(w, items))["neu"] == 3  # the rest, once measured useful


def test_local_block_and_memory_measured_harm(net):
    a = _free(net)
    bad = _free(net, start=[a.k.address])
    _rounds([a, bad])
    a._trust({"bewaehrt": [], "gesperrt": [bad.log.pub]})  # the memory measured its hints as harmful
    assert not a.log.is_member(bad.log.pub)
    with pytest.raises(ValueError, match="403.*blocked"):
        bad._request(a.k.address, "GET", "/netz/peers")
    seed, _ = net.key_()
    c = net.build(seed, [], kind="frei", net="welt", pow_bits=BITS, private_ok=True, blocked=[a.log.pub])
    assert a.log.pub in c.log.blocked and a.log.pub not in c.log.members()


def test_no_connections_to_private_addresses_learned_from_others(net):
    seed, _ = net.key_()
    strict = net.build(seed, [], mode="peer", kind="frei", net="welt", pow_bits=BITS, private_ok=False)
    with pytest.raises(ValueError, match="not a public address"):
        strict._request("http://127.0.0.1:9", "GET", "/netz/health")
    with pytest.raises(ValueError, match="not a public address"):
        strict._request("https://10.1.2.3", "GET", "/netz/health")


def test_closed_networks_stay_closed(net):
    (sa, a_pub), (sx, _x) = net.key_(), net.key_()
    a = net.build(sa, [a_pub])
    x = net.build(sx, [a_pub], mode="peer")
    with pytest.raises(ValueError, match="403"):
        x._request(a.k.address, "GET", "/netz/peers")


def test_identity_must_be_entry_one(tmp_path):
    log = _free_log(tmp_path, "o")
    log.ensure_identity(BITS)
    assert log.ensure_identity(BITS) is None  # exists
    closed_seed = tmp_path / "sc"
    lb.generate_keys(closed_seed)
    old = lb.Logbook(tmp_path / "c.db", closed_seed, [], free_bits=BITS)
    old.attach("adresse", {"adresse": "https://x.example"})
    with pytest.raises(ValueError, match="entry 1"):
        old.ensure_identity(BITS)


def test_memory_tells_whom_it_trusts(gd, monkeypatch):
    monkeypatch.setattr(p2p, "config", {"netze": {"welt": {"art": "frei", "instanz": "netz-welt"}}})
    assert p2p.networks()["welt"]["kind"] == "free" and not p2p.is_company("welt")
    good_pub, bad_pub = "a" * 64, "b" * 64
    for pub, ja, nein in ((good_pub, 30, 2), (bad_pub, 1, 30)):
        name = lb.pseudonym(pub)
        o = g.new_object("erkenntnis", f"knowledge from {name} about backups", ["thema:backup", "herkunft:p2p", f"herausgeber:{name}"],
                         {"quelle": "import", "herkunft": {"herausgeber": name, "pubkey": pub}, "nuetzlich": {"ja": ja, "nein": nein, "n": ja + nein}}, instance=f"p2p-{name}")
        g.save(o)
    t = p2p.trust()
    assert t == {"bewaehrt": [good_pub], "gesperrt": [bad_pub]}
    assert p2p.outbox("welt")["vertrauen"] == t


def test_setup_free_network_without_founder_and_block_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VI_MCP_KEIN_DIENST", "1")
    token = tmp_path / "mcp-token"
    token.write_text("t\n")
    monkeypatch.setenv("VI_P2P_CONFIG", str(tmp_path / "config.json"))
    (tmp_path / "welt.json").write_text(json.dumps({"db": str(tmp_path / "welt" / "netz.db"), "seed": str(tmp_path / "welt" / "schluessel"), "mcp_token_datei": str(token)}))
    assert net_cli.main(["--network", "welt", "setup", "--mode", "peer", "--kind", "frei"]) == 2  # needs a start address
    assert net_cli.main(["--network", "welt", "setup", "--mode", "peer", "--kind", "frei", "--start", "https://vinetz.example/vi-p2p/welt"]) == 0
    raw = json.loads((tmp_path / "welt.json").read_text())
    assert raw["kind"] == "free" and "founders" not in raw and raw["pow_bits"] == lb.DEFAULT_POW_BITS
    assert nd.load(tmp_path / "welt.json").kind == "free"
    assert net_cli.main(["--network", "welt", "block", "c" * 64]) == 0
    assert json.loads((tmp_path / "welt.json").read_text())["blocked"] == ["c" * 64]
    assert net_cli.main(["--network", "welt", "unblock", "c" * 64]) == 0
    assert json.loads((tmp_path / "welt.json").read_text())["blocked"] == []
