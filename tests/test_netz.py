"""0.14.0: logbook, membership, network service over real HTTP, TLS, forgetting across several hops, torrent."""
import datetime
import hashlib
import http.client
import ipaddress
import json
import time

import pytest

pytest.importorskip("cryptography")

from vi_mcp import logbook as lb  # noqa: E402
from vi_mcp import net_service as nd  # noqa: E402


def mem_object(i, token=None):
    return {"art": "erkenntnis", "text": f"Wissen Nummer {'abcdefghijklmnop'[i % 16]}{i} über den Eingang des Dienstes", "hashtags": ["thema:eingang"], "quelle": "Messung vom 2.11.",
            "wichtigkeit": 1, "zeit": "2026-11-08", "netz_id": hashlib.md5(str(i).encode()).hexdigest(), "loesch_hash": hashlib.sha256((token or f"t{i}").encode()).hexdigest()}


class FakeMemory:
    def __init__(self):
        self.mem_objects, self.revocations, self.receive, self.outage = [], [], [], False

    def outbox(self, state=None):
        self.state = state
        if self.outage:
            raise OSError("weg")
        return {"objekte": list(self.mem_objects), "widerrufe": list(self.revocations)}

    def answer_search(self, query, n):
        self.asked = getattr(self, "asked", []) + [query]
        return [o for o in getattr(self, "answers", []) if any(w.lower() in o["text"].lower() for w in query.split())][:n]

    def inbox(self, e):
        if self.outage:
            raise OSError("weg")
        self.receive += e
        return {}

    def texts(self):
        return sorted(x["inhalt"]["text"] for x in self.receive if x["kopf"]["typ"] == "objekt")

    def targets(self):
        return [x["inhalt"]["ziel"] for x in self.receive if x["kopf"]["typ"] == "widerruf"]


@pytest.fixture()
def net(tmp_path):
    nodes = []

    class N:
        def __init__(self):
            self.n = 0

        def key_(self):
            self.n += 1
            seed = tmp_path / f"seed{self.n}"
            return seed, lb.generate_keys(seed)

        def build(self, seed, founders, mode="peerhost", start=(), **kw):
            db = tmp_path / f"{seed.name}.db"
            k = nd.NetConfig(mode=mode, db=str(db), seed=str(seed), bind="127.0.0.1", port=0, founders=founders, startpeers=list(start), min_round_s=0, **kw)
            d = nd.NetService(k, FakeMemory())
            if mode == "peerhost":
                d.start_server()
                k.address = f"{'https' if k.tls_cert else 'http'}://127.0.0.1:{d.port()}"
            nodes.append(d)
            return d
    yield N()
    for d in nodes:
        d.stop_service()


def _log(tmp_path, name="a", founders=None):
    seed = tmp_path / f"s{name}"
    pub = lb.generate_keys(seed)
    return lb.Logbook(tmp_path / f"{name}.db", seed, founders if founders is not None else [pub])


def test_chain_is_checked(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    for i in range(3):
        a.attach("objekt", mem_object(i), mem_object(i)["netz_id"], mem_object(i)["loesch_hash"])
    assert b.ingest(a.read(a.pub, 0))["neu"] == 3
    assert b.ingest(a.read(a.pub, 0))["bekannt"] == 3
    assert b.headers() == {a.pub: 3}
    c = _log(tmp_path, "c", [a.pub])
    r = c.ingest(a.read(a.pub, 1))
    assert r["neu"] == 0 and "chain broken" in r["gruende"][0]  # gap at the start
    d = _log(tmp_path, "d", [a.pub])
    forged = a.read(a.pub, 0)
    forged[1]["kopf"]["zeit"] = "2020-01-01"
    r = d.ingest(forged)
    assert r["neu"] == 1 and "signature" in r["gruende"][0]


def test_fork_blocks_the_publisher(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    a.attach("adresse", {"adresse": "https://eins.example"})
    one = a.read(a.pub, 0)
    b.ingest(one)
    header = {**one[0]["kopf"], "sha": lb.sha256({"adresse": "https://zwei.example"})}
    header.pop("sig")
    header["sig"] = a.k.sign(lb.canonical(header)).hex()
    r = b.ingest([{"kopf": header, "inhalt": {"adresse": "https://zwei.example"}}])
    assert "fork at number 1" in r["gruende"][0]
    a.attach("adresse", {"adresse": "https://drei.example"})
    assert "fork known" in b.ingest(a.read(a.pub, 1))["gruende"][0] and b.status()["gabelungen"] == 1


def test_membership_follows_invitations(tmp_path):
    a = _log(tmp_path, "a")
    b, c = _log(tmp_path, "b", [a.pub]), _log(tmp_path, "c", [a.pub])
    b.attach("adresse", {"adresse": "https://b.example"})
    z = _log(tmp_path, "z", [a.pub])
    assert "not a member" in z.ingest(b.read(b.pub, 0))["gruende"][0]
    a.attach("einladung", {"pub": b.pub})
    z.ingest(a.read(a.pub, 0))
    assert z.ingest(b.read(b.pub, 0))["neu"] == 1
    b.attach("einladung", {"pub": c.pub})
    z.ingest(b.read(b.pub, 1))
    assert z.members() == {a.pub, b.pub, c.pub}
    a.attach("ausschluss", {"pub": b.pub})
    z.ingest(a.read(a.pub, 1))
    assert z.members() == {a.pub}  # whoever came only via b drops out as well


def test_only_inviters_and_founders_may_exclude(tmp_path):
    a = _log(tmp_path, "a")
    b, c = _log(tmp_path, "b", [a.pub]), _log(tmp_path, "c", [a.pub])
    a.attach("einladung", {"pub": b.pub})
    a.attach("einladung", {"pub": c.pub})
    b.attach("ausschluss", {"pub": c.pub})
    b.attach("ausschluss", {"pub": a.pub})
    z = _log(tmp_path, "z", [a.pub])
    z.ingest(a.read(a.pub, 0))
    z.ingest(b.read(b.pub, 0))
    assert z.members() == {a.pub, b.pub, c.pub}


def test_internals_are_not_forwarded(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    o = {**mem_object(1), "text": "Der Rechner 10.1.2.3 fällt immer wieder aus"}
    a.attach("objekt", o, o["netz_id"], o["loesch_hash"])
    a.attach("objekt", mem_object(2), mem_object(2)["netz_id"], mem_object(2)["loesch_hash"])
    assert b.ingest(a.read(a.pub, 0))["neu"] == 2  # the chain stays intact
    e = b.read(a.pub, 0)
    assert e[0]["inhalt"] is None and e[1]["inhalt"] and b.status()["verstoesse"] == 1


def test_forget_in_logbook(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    o = mem_object(1, "geheim")
    a.attach("objekt", o, o["netz_id"], o["loesch_hash"])
    b.ingest(a.read(a.pub, 0))
    x = _log(tmp_path, "x", [a.pub])
    a.attach("widerruf", {"ziel": o["netz_id"], "token": "falsch"}, o["netz_id"])
    b.ingest(a.read(a.pub, 1))
    assert b.read(a.pub, 0)[0]["inhalt"]  # a false proof changes nothing
    a2 = len(a.read(a.pub, 0))
    a.attach("widerruf", {"ziel": o["netz_id"], "token": "geheim"}, o["netz_id"])
    b.ingest(a.read(a.pub, a2))
    assert b.read(a.pub, 0)[0]["inhalt"] is None and b.status()["grabsteine"] == 1
    # the chain stays verifiable, even for someone who joins only later
    assert x.ingest(b.read(a.pub, 0))["neu"] == 3
    assert x.read(a.pub, 0)[0]["inhalt"] is None
    # if the content comes from a peer with an old state, it stays away
    x.ingest([{"kopf": a.read(a.pub, 0)[0]["kopf"], "inhalt": o}])
    assert x.read(a.pub, 0)[0]["inhalt"] is None


def test_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "MAX_PER_DAY", 2)
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    for i in range(3):
        a.attach("adresse", {"adresse": f"https://x{i}.example"})
    r = b.ingest(a.read(a.pub, 0))
    assert r["neu"] == 2 and "daily quota" in r["gruende"][0]


def _three(net):
    (sa, a_pub), (sb, b_pub), (sc, c_pub) = net.key_(), net.key_(), net.key_()
    g = [a_pub]
    a = net.build(sa, g)
    a.log.attach("einladung", {"pub": b_pub})
    a.log.attach("einladung", {"pub": c_pub})
    b = net.build(sb, g, start=[a.k.address])
    c = net.build(sc, g, mode="peer", start=[b.k.address])
    return a, b, c


def test_knowledge_travels_over_several_stations(net):
    a, b, c = _three(net)
    a.mcp.mem_objects.append(mem_object(1))
    c.mcp.mem_objects.append(mem_object(2))
    for _ in range(3):
        a.run_round(), b.run_round(), c.run_round()
    assert c.mcp.texts() == [mem_object(1)["text"]]
    assert a.mcp.texts() == [mem_object(2)["text"]]  # from the peer behind the firewall, pushed via b
    assert sorted(b.mcp.texts()) == sorted([mem_object(1)["text"], mem_object(2)["text"]])


def test_forget_reaches_all_stations(net):
    a, b, c = _three(net)
    a.mcp.mem_objects.append(mem_object(1, "geheim"))
    for _ in range(3):
        a.run_round(), b.run_round(), c.run_round()
    nid = mem_object(1)["netz_id"]
    a.mcp.mem_objects.clear()
    a.mcp.revocations.append({"netz_id": nid, "token": "geheim"})
    for _ in range(3):
        a.run_round(), b.run_round(), c.run_round()
    for d in (a, b, c):
        assert d.log.read(a.log.pub, 0)[2]["inhalt"] is None, d.k.mode
        assert d.log.status()["grabsteine"] == 1
    assert c.mcp.targets() == [nid] and b.mcp.targets() == [nid]


def test_peers_find_each_other_via_logbook(net):
    a, b, c = _three(net)
    for _ in range(3):
        b.run_round(), a.run_round(), c.run_round()
    (sd, d_pub) = net.key_()
    a.log.attach("einladung", {"pub": d_pub})
    d = net.build(sd, a.k.founders, mode="peer", start=[a.k.address])
    d.run_round()
    assert b.k.address in [r[0] for r in d.log.db.execute("SELECT adresse FROM peer WHERE quelle = 'logbuch'")]


def test_nudge_wakes_the_neighbors(net):
    a, b, c = _three(net)
    b.run_round()
    a.awake.clear()
    b.mcp.mem_objects.append(mem_object(5))
    b.run_round()
    assert a.awake.is_set()


def _raw(d, method, fpath, header=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", d.port(), timeout=5)
    c.request(method, fpath, body=body, headers=header or {})
    r = c.getresponse()
    r.read()
    return r.status


def test_only_members_get_an_answer(net):
    (sa, a_pub), (_sz, _z) = net.key_(), net.key_()
    a = net.build(sa, [a_pub])
    assert _raw(a, "GET", "/netz/gesund") == 200
    assert _raw(a, "GET", f"/netz/log/{a_pub}?ab=0") == 401
    foreign = lb.private(_sz)
    assert _raw(a, "GET", f"/netz/log/{a_pub}?ab=0", {"Authorization": nd._sign(foreign, "GET", f"/netz/log/{a_pub}?ab=0", b"")}) == 403
    own = a.log.k
    assert _raw(a, "GET", f"/netz/log/{a_pub}?ab=0", {"Authorization": nd._sign(own, "GET", f"/netz/log/{a_pub}?ab=0", b"")}) == 200
    assert _raw(a, "GET", f"/netz/log/{a_pub}?ab=5", {"Authorization": nd._sign(own, "GET", f"/netz/log/{a_pub}?ab=0", b"")}) == 401  # the signature is valid only for this path
    value = nd._sign(own, "GET", "/netz/segmente/x", b"").split()
    value[2] = str(int(time.time()) - 900)
    value[3] = own.sign("\n".join(("GET", "/netz/segmente/x", value[2], hashlib.sha256(b"").hexdigest())).encode()).hex()
    assert _raw(a, "GET", "/netz/segmente/x", {"Authorization": " ".join(value)}) == 401  # outdated


def test_peer_outage_and_fallback(net):
    a, b, c = _three(net)
    b.log.peer_remember("http://127.0.0.1:1", "start")
    b.reconcile("http://127.0.0.1:1")
    z = b.log.db.execute("SELECT fehler, naechster FROM peer WHERE adresse = 'http://127.0.0.1:1'").fetchone()
    assert z[0] == 1 and z[1] > time.time()
    assert "http://127.0.0.1:1" not in b.log.choose_peers(10)


def test_memory_gone_does_not_stop_the_net(net):
    a, b, c = _three(net)
    a.mcp.mem_objects.append(mem_object(1))
    a.run_round()
    b.mcp.outage = True
    b.run_round()
    assert b.log.headers()[a.log.pub] >= 3 and not b.mcp.receive  # carried, not yet handed over
    b.mcp.outage = False
    b.run_round()
    assert b.mcp.texts() == [mem_object(1)["text"]]


def test_only_believed_publishers_reach_memory(net):
    (sa, a_pub), (sb, _b) = net.key_(), net.key_()
    a = net.build(sa, [a_pub])
    a.log.attach("einladung", {"pub": _b})
    b = net.build(sb, [a_pub], start=[a.k.address], believe=[])
    a.mcp.mem_objects.append(mem_object(1))
    a.mcp.revocations.append({"netz_id": "e" * 32, "token": "x"})
    a.run_round()
    b.run_round()
    assert b.mcp.texts() == [] and b.mcp.targets() == ["e" * 32]  # carried, not believed; the forgetting applies anyway


def test_http_to_foreign_host_is_forbidden(net):
    (sa, a_pub) = net.key_()
    a = net.build(sa, [a_pub], mode="peer")
    with pytest.raises(ValueError, match="unencrypted"):
        a._request("http://peer.example", "GET", "/netz/gesund")


def _certificate(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False).add_extension(x509.BasicConstraints(ca=True, path_length=None), True).sign(key, hashes.SHA256()))
    c, k = tmp_path / "c.pem", tmp_path / "k.pem"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return str(c), str(k)


def test_reconcile_via_tls(net, tmp_path):
    cert, key = _certificate(tmp_path)
    (sa, a_pub), (sb, b_pub), (sc, c_pub) = net.key_(), net.key_(), net.key_()
    a = net.build(sa, [a_pub], tls_cert=cert, tls_key=key)
    a.log.attach("einladung", {"pub": b_pub})
    a.log.attach("einladung", {"pub": c_pub})
    a.mcp.mem_objects.append(mem_object(1))
    a.run_round()
    assert a.k.address.startswith("https://")
    b = net.build(sb, [a_pub], mode="peer", start=[a.k.address], ca_file=cert)
    b.run_round()
    assert b.mcp.texts() == [mem_object(1)["text"]]
    c = net.build(sc, [a_pub], mode="peer", start=[a.k.address])  # without a trusted certificate
    c.run_round()
    assert c.log.headers() == {}


def test_torrent_fetches_large_backlogs(net, tmp_path):
    pytest.importorskip("libtorrent")
    (sa, a_pub), (sb, b_pub) = net.key_(), net.key_()
    t = {"aktiv": True, "port": 0, "segment": 10, "ab": 5, "warte_s": 30}
    a = net.build(sa, [a_pub], torrent={**t, "verzeichnis": str(tmp_path / "ta")})
    a.log.attach("einladung", {"pub": b_pub})
    a.mcp.mem_objects.extend(mem_object(i) for i in range(25))
    a.run_round()
    assert a.log.status()["segmente"] >= 1 and a.log.segments(a.log.pub)[0]["von"] == 1
    b = net.build(sb, [a_pub], mode="peer", start=[a.k.address], torrent={**t, "verzeichnis": str(tmp_path / "tb")})
    b.run_round()
    assert b.usage_stats["per_torrent"] >= 10 and b.log.headers()[a.log.pub] == a.log.headers()[a.log.pub]
    assert len(b.mcp.texts()) == 25
    # a forgotten object makes the segment disappear
    nid = mem_object(3)["netz_id"]
    a.mcp.mem_objects = [o for o in a.mcp.mem_objects if o["netz_id"] != nid]
    a.mcp.revocations.append({"netz_id": nid, "token": "t3"})
    assert a.outbox() == 1
    assert all(not (s["von"] <= 5 <= s["bis"]) for s in a.log.segments(a.log.pub))


def test_without_libtorrent_stays_https(net, tmp_path, monkeypatch):
    from vi_mcp import net_torrent
    monkeypatch.setattr(net_torrent, "available", lambda: False)
    (sa, a_pub) = net.key_()
    a = net.build(sa, [a_pub], torrent={"aktiv": True})
    assert a.swarm is None


def test_address_behind_reverse_proxy():
    assert lb.valid_control_form("adresse", {"adresse": "https://wissen.example/vi-p2p"})
    assert lb.valid_control_form("adresse", {"adresse": "https://wissen.example:8443/a/b"})
    for wrong in ("https://wissen.example/", "https://wissen.example/x?y=1", "ftp://wissen.example", "https://wissen.example/../x y"):
        assert not lb.valid_control_form("adresse", {"adresse": wrong}), wrong


def test_reconcile_via_path_prefix(net):
    """As behind nginx: the peer reaches the service at /vi-p2p, the service sees /netz/…"""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    (sa, a_pub), (sb, b_pub) = net.key_(), net.key_()
    a = net.build(sa, [a_pub])
    a.log.attach("einladung", {"pub": b_pub})
    a.mcp.mem_objects.append(mem_object(1))
    a.run_round()
    target = a.port()

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _forward(self):
            assert self.path.startswith("/vi-p2p/")
            c = http.client.HTTPConnection("127.0.0.1", target, timeout=10)
            req_body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            c.request(self.command, self.path[len("/vi-p2p"):], body=req_body or None, headers={k: v for k, v in self.headers.items() if k.lower() in ("authorization", "content-type")})
            r = c.getresponse()
            d = r.read()
            self.send_response(r.status)
            self.send_header("Content-Length", str(len(d)))
            self.end_headers()
            self.wfile.write(d)
        do_GET = do_POST = _forward
    p = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=p.serve_forever, daemon=True).start()
    try:
        b = net.build(sb, [a_pub], mode="peer", start=[f"http://127.0.0.1:{p.server_address[1]}/vi-p2p"])
        b.run_round()
        assert b.mcp.texts() == [mem_object(1)["text"]]
    finally:
        p.shutdown()
        p.server_close()


def test_config_file_keeps_german_keys(capsys):
    """The config file is a stored format: existing installations write German keys, which must all arrive."""
    import vi_mcp.net_service as ns
    stored = {"modus": "peer", "adresse": "https://a:1", "ca_datei": "/x/ca.pem", "gruender": ["f"], "takt_s": 60, "min_runde_s": 1,
              "nachbarn": 3, "http_erlaubt": True, "glauben": ["a"], "mcp_token_datei": "/x/t", "kein_proxy": ["intern"], "proxy": "http://p:1"}
    k = ns.from_file(stored)
    assert (k.mode, k.address, k.ca_file, k.founders, k.tick_s, k.min_round_s, k.neighbors, k.http_allowed, k.believe, k.mcp_token_file, k.no_proxy, k.proxy) == \
        ("peer", "https://a:1", "/x/ca.pem", ["f"], 60, 1, 3, True, ["a"], "/x/t", ["intern"], "http://p:1")
    assert ns.from_file({"mode": "peer", "address": "https://b:2"}).address == "https://b:2"
    ns.from_file({"modus": "peer", "tippfehler": 1})
    assert "unknown keys ignored: tippfehler" in capsys.readouterr().err


def test_net_cli_accepts_english_options_and_german_aliases(monkeypatch):
    from vi_mcp import net_cli
    seen = []
    monkeypatch.setattr(net_cli, "setup", lambda o: seen.append((o.command, o.mode, o.address, o.ca_file, o.found, o.founders, o.no_proxy)) or 0)
    assert net_cli.main(["setup", "--mode", "peer", "--address", "https://a:1", "--ca-file", "c", "--found", "--founder", "k", "--no-proxy", "d"]) == 0
    assert net_cli.main(["einrichten", "--modus", "peer", "--adresse", "https://a:1", "--ca-datei", "c", "--gruenden", "--gruender", "k", "--kein-proxy", "d"]) == 0
    assert seen[0] == seen[1] == ("setup", "peer", "https://a:1", "c", True, ["k"], ["d"])
