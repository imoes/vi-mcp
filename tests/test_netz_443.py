"""0.40.0: every network on one TLS port (443 in production) — each under /vi-p2p/<network> behind the reverse proxy, services on localhost."""
import http.client
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("cryptography")

from vi_mcp import net_cli  # noqa: E402

from test_netz import mem_object, net  # noqa: E402,F401
from test_netz_beitritt import _cert  # noqa: E402


def test_public_address_is_https_on_443_only():
    assert net_cli.public_address("https://wiki.example.org", "firma") == "https://wiki.example.org/vi-p2p/firma"
    assert net_cli.public_address("https://wiki.example.org:443/", "standard") == "https://wiki.example.org/vi-p2p/standard"
    for bad in ("http://wiki.example.org", "https://wiki.example.org:8443", "https://wiki.example.org/sub", "wiki.example.org", "https://:443"):
        with pytest.raises(ValueError, match="443"):
            net_cli.public_address(bad, "firma")


def test_free_port_and_proxy_config(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(net_cli, "_bound", lambda port: False)
    assert net_cli.free_port({8766, 8767}) == 8768
    # 0.51.0: 8767 is the embedding service's default port — a new network never takes it; a port something listens on neither
    assert net_cli.free_port({8766}) == 8768
    monkeypatch.undo()
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        sk.listen()
        taken = sk.getsockname()[1]
        assert net_cli._bound(taken) and net_cli.free_port(set(), taken) != taken
    (tmp_path / "config.json").write_text(json.dumps({"modus": "peerhost", "adresse": "https://w.example/vi-p2p/standard", "port": 8766, "bind": "127.0.0.1"}))
    (tmp_path / "firma.json").write_text(json.dumps({"modus": "peerhost", "adresse": "https://w.example/vi-p2p/firma", "port": 8767, "art": "firma"}))
    (tmp_path / "alt.json").write_text(json.dumps({"modus": "peerhost", "adresse": "https://w.example:8766", "port": 8768}))  # own TLS: not proxied
    confs = net_cli.network_configs(tmp_path)
    assert set(confs) == {"standard", "firma", "alt"}
    s = net_cli.nginx_snippet(confs)
    assert "location /vi-p2p/standard/ {" in s and "proxy_pass http://127.0.0.1:8766/;" in s
    assert "location /vi-p2p/firma/ {  # network firma (company)" in s and "proxy_pass http://127.0.0.1:8767/;" in s
    assert "8768" not in s and "client_max_body_size 2m" in s
    assert "no network is published" in net_cli.nginx_snippet({})


class _Proxy:
    """What nginx does on 443: TLS ends here, /vi-p2p/<network>/… goes to that network's service on localhost, prefix stripped."""

    def __init__(self, cert, key, routes: dict):
        proxy = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def _forward(self):
                parts = self.path.split("/", 3)  # "", "vi-p2p", name, rest
                port = routes.get(parts[2]) if len(parts) > 3 and parts[1] == "vi-p2p" else None
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if not port:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                proxy.seen.append(parts[2])
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                c.request(self.command, "/" + parts[3], body=body or None, headers={k: v for k, v in self.headers.items() if k.lower() in ("authorization", "content-type")})
                r = c.getresponse()
                raw = r.read()
                c.close()
                self.send_response(r.status)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(raw)
            do_GET = do_POST = _forward

        self.seen = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.srv.socket = ctx.wrap_socket(self.srv.socket, server_side=True)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


def test_two_networks_share_one_tls_port(net, tmp_path):
    cert, key = _cert(tmp_path)
    routes = {}
    proxy = _Proxy(cert, key, routes)
    try:
        nets = {}
        for name, kind in (("standard", "offen"), ("firma", "firma")):
            (sa, a_pub), (sb, b_pub) = net.key_(), net.key_()
            a = net.build(sa, [a_pub], kind=kind, net=name)  # peerhost on localhost, plain HTTP behind the proxy
            routes[name] = a.port()
            public = f"https://127.0.0.1:{proxy.port}/vi-p2p/{name}"
            a.k.address = public
            a.log.attach("einladung", {"pub": b_pub})
            b = net.build(sb, [a_pub], mode="peer", start=[public], kind=kind, net=name, ca_file=cert)
            nets[name] = (a, b)
        o_open = mem_object(1)
        o_company = {**mem_object(2), "text": "Backup of db01.corp.example runs nightly via borg", "hashtags": ["host:db01", "thema:backup"]}
        nets["standard"][0].mcp.mem_objects.append(o_open)
        nets["firma"][0].mcp.mem_objects.append(o_company)
        for a, b in nets.values():
            a.run_round()
            b.run_round()
        assert nets["standard"][1].mcp.texts() == [o_open["text"]]
        assert nets["firma"][1].mcp.texts() == [o_company["text"]]
        assert set(proxy.seen) == {"standard", "firma"}  # both went through the one TLS port
        a_addr = {p["adresse"] for p in nets["firma"][1].log.peers()}
        assert f"https://127.0.0.1:{proxy.port}/vi-p2p/firma" in a_addr
    finally:
        proxy.stop()


def test_setup_public_and_proxy_config_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VI_MCP_KEIN_DIENST", "1")
    monkeypatch.setattr(net_cli, "_bound", lambda port: False)  # the ports of this machine must not decide the test
    token = tmp_path / "mcp-token"
    token.write_text("t\n")
    monkeypatch.setenv("VI_P2P_CONFIG", str(tmp_path / "config.json"))
    (tmp_path / "config.json").write_text(json.dumps({"db": str(tmp_path / "std" / "netz.db"), "seed": str(tmp_path / "std" / "schluessel"),
                                                      "mcp_token_datei": str(token), "port": 8766}))
    (tmp_path / "firma.json").write_text(json.dumps({"db": str(tmp_path / "firma" / "netz.db"), "seed": str(tmp_path / "firma" / "schluessel"),
                                                     "mcp_token_datei": str(token)}))
    assert net_cli.main(["--network", "firma", "setup", "--mode", "peerhost", "--found", "--kind", "firma", "--public", "https://wiki.example.org:8443"]) == 2
    assert net_cli.main(["--network", "firma", "setup", "--mode", "peerhost", "--found", "--kind", "firma", "--public", "https://wiki.example.org"]) == 0
    raw = json.loads((tmp_path / "firma.json").read_text())
    assert raw["address"] == "https://wiki.example.org/vi-p2p/firma" and raw["bind"] == "127.0.0.1" and raw["port"] == 8768  # 8766 is taken, 8767 is the embedding service's
    assert raw["net"] == "firma" and raw["kind"] == "company" and "Network firma (company)" in capsys.readouterr().out
    assert net_cli.main(["proxy-config"]) == 0
    out = capsys.readouterr().out
    assert "location /vi-p2p/firma/ {" in out and "proxy_pass http://127.0.0.1:8768/;" in out
    monkeypatch.setenv("VI_P2P_CONFIG", str(tmp_path / "config.json"))  # --network set it to firma.json for that call
    assert net_cli.main(["setup", "--mode", "peerhost", "--found", "--kind", "firma", "--public", "https://wiki.example.org"]) == 2  # standard stays open


def test_setup_for_a_memory_in_another_container(tmp_path, monkeypatch, capsys):
    """0.62.6, reported from CentralStation: memory and network service run in separate containers; join wrote the network's instance
    and live-search token into a memory config the memory never read. --memory-config/--memory-url/--local-bind/--local-host make it
    explicit, and a split setup without the memory's config is refused instead of writing a stray one."""
    monkeypatch.setenv("VI_MCP_KEIN_DIENST", "1")
    monkeypatch.setattr(net_cli, "_bound", lambda port: False)
    monkeypatch.setenv("VI_P2P_CONFIG", str(tmp_path / "firma.json"))
    (tmp_path / "firma.json").write_text(json.dumps({"db": str(tmp_path / "firma" / "netz.db"), "seed": str(tmp_path / "firma" / "schluessel"),
                                                     "mcp_token_file": str(tmp_path / "firma-mcp-token")}))
    memory = tmp_path / "memory" / "config.json"
    args = ["--network", "firma", "setup", "--mode", "peer", "--kind", "company", "--founder", "ab" * 32,
            "--memory-config", str(memory), "--memory-url", "http://vi-mcp:8765/mcp", "--local-bind", "0.0.0.0", "--local-host", "vi-p2p-firma"]
    assert net_cli.main(args) == 2 and "does not exist here" in capsys.readouterr().err  # not mounted: refused, nothing written
    assert not memory.exists()
    memory.parent.mkdir()
    memory.write_text(json.dumps({"port": 8765, "instances": {}}))
    assert net_cli.main(args) == 0
    out = capsys.readouterr().out
    assert "restart the memory" in out and "http://vi-p2p-firma:" in out and "listener bound to 0.0.0.0" in out
    raw = json.loads((tmp_path / "firma.json").read_text())
    assert raw["mcp_url"] == "http://vi-mcp:8765/mcp" and raw["local_bind"] == "0.0.0.0" and raw["local_token_sha256"]
    m = json.loads(memory.read_text())
    assert "netz-firma" in m["instances"] and m["p2p"]["networks"]["firma"]["kind"] == "company"
    assert m["p2p"]["networks"]["firma"]["local"]["url"] == f"http://vi-p2p-firma:{raw['local_port']}"
    assert (tmp_path / "firma-mcp-token").exists()  # the network's own token file, not standard's


def test_setup_again_wires_a_live_search_the_memory_never_got(tmp_path, monkeypatch, capsys):
    """0.62.6: the service had a token hash, the memory no entry (a first setup in another container) — setup again wires it."""
    monkeypatch.setenv("VI_MCP_KEIN_DIENST", "1")
    monkeypatch.setattr(net_cli, "_bound", lambda port: False)
    monkeypatch.setenv("VI_P2P_CONFIG", str(tmp_path / "config.json"))
    token = tmp_path / "mcp-token"
    token.write_text("t\n")
    (tmp_path / "config.json").write_text(json.dumps({"db": str(tmp_path / "std" / "netz.db"), "seed": str(tmp_path / "std" / "schluessel"),
                                                      "mcp_token_file": str(token), "local_port": 9765, "local_token_sha256": "orphaned"}))
    memory = tmp_path / "memory.json"
    memory.write_text(json.dumps({"port": 8765, "instances": {}}))
    assert net_cli.main(["setup", "--mode", "peer", "--founder", "ab" * 32, "--memory-config", str(memory), "--memory-url", "http://vi-mcp:8765/mcp"]) == 0
    m = json.loads(memory.read_text())
    raw = json.loads((tmp_path / "config.json").read_text())
    assert m["p2p"]["local"]["url"] == "http://127.0.0.1:9765" and raw["local_token_sha256"] != "orphaned"
    assert "Live search wired" in capsys.readouterr().out
