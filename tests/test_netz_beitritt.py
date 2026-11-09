"""0.15.0: Beitritt mit Code, selbstsigniertes TLS mit Pin, HTTPS-Proxy, Befehle für weitere Peers."""
import json
import select
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from vi_mcp import logbook as lb  # noqa: E402
from vi_mcp import net_cli  # noqa: E402
from vi_mcp import net_service as nd  # noqa: E402

from test_netz import FakeMemory, mem_object, net  # noqa: E402,F401


def test_code_round_trip():
    g = ["a" * 64]
    c = nd.build_code(g, "https://wissen.example/vi-p2p", "b" * 64, "geheim", time.time() + 60)
    d = nd.read_code(c)
    assert d["g"] == g and d["s"] == "https://wissen.example/vi-p2p" and d["p"] == "b" * 64 and d["n"] == "geheim"
    for broken, reason in ((c[:-6], "beschädigt|Gründer|Adresse"), ("xyz", "kein Beitrittscode"), (nd.build_code(g, "https://w.example", None, "n", time.time() - 1), "abgelaufen"),
                          (nd.build_code(["x"], "https://w.example", None, "n", time.time() + 9), "Gründer"), (nd.build_code(g, "https://w.example/", None, "n", time.time() + 9), "Adresse")):
        with pytest.raises(ValueError, match=reason):
            nd.read_code(broken)


def _cert(tmp_path, host="127.0.0.1"):
    c, k = tmp_path / "c.pem", tmp_path / "k.pem"
    net_cli._create_certificate(f"https://{host}:1", c, k)
    return str(c), str(k)


def test_join_via_tls_with_pin(net, tmp_path):
    cert, key = _cert(tmp_path)
    (sa, a_pub), (sb, b_pub) = net.key_(), net.key_()
    a = net.build(sa, [a_pub], tls_cert=cert, tls_key=key)
    a.mcp.mem_objects.append(mem_object(1))
    a.run_round()
    assert a.log.last_own_address()["pin"] == nd.certificate_pin(Path(cert))
    nonce = "einmal-und-nie-wieder"
    a.log.create_join(nonce, 60)
    b = net.build(sb, [a_pub], mode="peer")
    with pytest.raises(ValueError, match="CERTIFICATE_VERIFY_FAILED|certificate verify failed"):
        b._request(a.k.address, "POST", "/netz/beitritt", {"code": nonce})  # ohne Pin und ohne CA kein Vertrauen
    b.log.peer_remember(a.k.address, "beitritt", "f" * 64)
    with pytest.raises(ValueError, match="Pin"):
        b._request(a.k.address, "POST", "/netz/beitritt", {"code": nonce})
    b.log.peer_remember(a.k.address, "beitritt", nd.certificate_pin(Path(cert)))
    assert b._request(a.k.address, "POST", "/netz/beitritt", {"code": nonce}) == {"eingeladen": lb.pseudonym(b_pub)}
    with pytest.raises(ValueError, match="403.*schon benutzt"):
        b._request(a.k.address, "POST", "/netz/beitritt", {"code": nonce})
    assert a.log.is_member(b_pub)
    b.mcp.mem_objects.append(mem_object(2))
    b.run_round()
    a.run_round()
    assert b.mcp.texts() == [mem_object(1)["text"]] and a.mcp.texts() == [mem_object(2)["text"]]


def test_expired_code_and_missing_signature(net):
    (sa, a_pub), (sb, _b) = net.key_(), net.key_()
    a = net.build(sa, [a_pub])
    a.log.create_join("alt", -1)
    b = net.build(sb, [a_pub], mode="peer")
    with pytest.raises(ValueError, match="403.*abgelaufen"):
        b._request(a.k.address, "POST", "/netz/beitritt", {"code": "alt"})
    with pytest.raises(ValueError, match="403"):
        b._request(a.k.address, "POST", "/netz/beitritt", {"code": "gibtsnicht"})
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", a.port(), timeout=5)
    c.request("POST", "/netz/beitritt", body=b'{"code":"alt"}')
    assert c.getresponse().status == 401


def test_pin_moves_with_the_address(net, tmp_path):
    cert, key = _cert(tmp_path)
    (sa, a_pub), (sb, b_pub), (sc, c_pub) = net.key_(), net.key_(), net.key_()
    b = net.build(sb, [a_pub])  # b ist peerhost ohne eigenes TLS (lokal), a mit selbstsigniertem
    a = net.build(sa, [a_pub], tls_cert=cert, tls_key=key, start=[b.k.address])
    a.log.attach("einladung", {"pub": b_pub})
    a.log.attach("einladung", {"pub": c_pub})
    a.run_round()  # a schiebt sein Logbuch samt Adresse und Pin zu b
    c = net.build(sc, [a_pub], mode="peer", start=[b.k.address])
    c.run_round()
    assert c.log.pin(a.k.address) == nd.certificate_pin(Path(cert))
    a.mcp.mem_objects.append(mem_object(3))
    a.run_round()
    assert c.reconcile(a.k.address) >= 1 and mem_object(3)["text"] in c.mcp.texts() + [x["inhalt"]["text"] for x in c.log.read(a_pub, 0) if x["kopf"]["typ"] == "objekt"]


class ConnectProxy:
    """Ein winziger HTTPS-Proxy: merkt sich jedes CONNECT-Ziel und leitet an 127.0.0.1 weiter."""

    def __init__(self):
        self.targets = []
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(8)
        self.port = self.s.getsockname()[1]
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                k, _ = self.s.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(k,), daemon=True).start()

    def _one(self, k):
        header = b""
        while b"\r\n\r\n" not in header:
            header += k.recv(4096)
        target = header.split(b" ")[1].decode()
        self.targets.append(target)
        z = socket.create_connection(("127.0.0.1", int(target.rsplit(":", 1)[1])))
        k.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        try:
            while True:
                r, _, _ = select.select([k, z], [], [], 10)
                if not r:
                    break
                for q in r:
                    d = q.recv(65536)
                    if not d:
                        return
                    (z if q is k else k).sendall(d)
        finally:
            k.close()
            z.close()


def test_https_via_proxy(net, tmp_path):
    cert, key = _cert(tmp_path, "peer.wissen.test")
    (sa, a_pub), (sb, b_pub) = net.key_(), net.key_()
    a = net.build(sa, [a_pub], tls_cert=cert, tls_key=key)
    a.log.attach("einladung", {"pub": b_pub})
    a.mcp.mem_objects.append(mem_object(4))
    a.run_round()
    p = ConnectProxy()
    remote = f"https://peer.wissen.test:{a.port()}"  # nur über den Proxy erreichbar: der Name existiert nicht
    b = net.build(sb, [a_pub], mode="peer", proxy=f"http://127.0.0.1:{p.port}")
    b.log.peer_remember(remote, "beitritt", nd.certificate_pin(Path(cert)))
    b.run_round()
    assert b.mcp.texts() == [mem_object(4)["text"]] and f"peer.wissen.test:{a.port()}" in p.targets
    b.k.no_proxy = ["wissen.test"]
    with pytest.raises(OSError):  # ohne Proxy ist der Name nicht auflösbar
        b._request(remote, "POST", "/netz/koepfe", {"koepfe": {}})
    p.s.close()


def test_commands_end_to_end(tmp_path, monkeypatch, capsys):
    """einrichten --tls-selbst → einladung → beitreten → peers, wie auf echten Servern, nur ohne systemd."""
    monkeypatch.setenv("VI_MCP_KEIN_DIENST", "1")
    token = tmp_path / "mcp-token"
    token.write_text("t\n")
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()

    def conf(name, **kw):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps({"db": str(tmp_path / name / "netz.db"), "seed": str(tmp_path / name / "schluessel"), "mcp_token_datei": str(token), **kw}))
        (tmp_path / name).mkdir()
        monkeypatch.setenv("VI_P2P_CONFIG", str(p))
        return p
    conf("a", bind="127.0.0.1", port=port)
    assert net_cli.main(["einrichten", "--modus", "peerhost", "--gruenden", "--adresse", f"https://127.0.0.1:{port}", "--tls-selbst"]) == 0
    ka = nd.load()
    assert ka.tls_cert and Path(ka.tls_cert).exists()
    a = nd.NetService(ka, FakeMemory())
    a.start_server()
    try:
        a.run_round()
        capsys.readouterr()
        assert net_cli.main(["einladung", "--stunden", "1"]) == 0
        code = capsys.readouterr().out.strip()
        assert code.startswith("vinetz1.") and nd.read_code(code)["p"] == nd.certificate_pin(Path(ka.tls_cert))
        conf("b")
        assert net_cli.main(["beitreten", code]) == 0
        assert "Aufgenommen als vi-" in capsys.readouterr().out
        kb = nd.load()
        assert kb.mode == "peer" and kb.founders == ka.founders and kb.startpeers == [f"https://127.0.0.1:{port}"]
        assert net_cli.main(["beitreten", code]) == 1  # zweimal geht nicht
        b = nd.NetService(kb, FakeMemory())
        a.mcp.mem_objects.append(mem_object(5))
        a.run_round()
        b.run_round()
        assert b.mcp.texts() == [mem_object(5)["text"]]
        b.stop_service()
        capsys.readouterr()
        assert net_cli.main(["peers"]) == 0
        assert "Pin " in capsys.readouterr().out
        monkeypatch.setenv("VI_P2P_CONFIG", str(tmp_path / "a.json"))
        assert net_cli.main(["einrichten", "--modus", "peer", "--gruender", "a" * 64, "--tls-selbst"]) == 2
    finally:
        a.stop_service()
