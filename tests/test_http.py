"""Block 2: MCP über Streamable HTTP — echter Server auf Zufallsport, echte HTTP-Anfragen."""
import http.client
import json
import threading

import pytest

from vi_mcp import memory as g
from vi_mcp import config, server, session


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    tok_a = config.create_instance("laptop", reflexes=True)
    tok_b = config.create_instance("fremd", reflexes=False)
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db")})
    cfg.write_text(json.dumps(raw))
    (s,) = server.build(config.load())
    th = threading.Thread(target=s.serve_forever, daemon=True)
    th.start()
    yield s.server_address[1], tok_a, tok_b
    s.shutdown()
    s.server_close()
    server.finish([s])


def request(port, method, req_body=None, token=None, sid=None, header=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(header or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if sid:
        h["Mcp-Session-Id"] = sid
    c.request(method, "/mcp", body=json.dumps(req_body) if req_body is not None else None, headers=h)
    r = c.getresponse()
    data = r.read()
    try:
        content = json.loads(data) if data else None
    except json.JSONDecodeError:
        content = data.decode()
    return r.status, dict(r.getheaders()), content


def init(port, token, name="pytest"):
    st, header, a = request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                         "params": {"protocolVersion": "2025-03-26", "clientInfo": {"name": name, "version": "1"},
                                                    "capabilities": {}}}, token)
    assert st == 200, a
    assert a["result"]["protocolVersion"] == "2025-03-26"
    # 0.20.7: Jeder Client bekommt die Regeln, wann er die VI befragt und wann er lernt
    assert "ASK" in a["result"]["instructions"] and "LEARN" in a["result"]["instructions"] and "Never learn" in a["result"]["instructions"]
    sid = header["Mcp-Session-Id"]
    st, _, _ = request(port, "POST", {"jsonrpc": "2.0", "method": "notifications/initialized"}, token, sid)
    assert st == 202
    return sid


def call_tool(port, token, sid, name, args, mid=2):
    st, _, a = request(port, "POST", {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": name, "arguments": args}}, token, sid)
    assert st == 200, a
    return a["result"]


def test_protection(srv):
    port, tok, _ = srv
    assert request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 401
    assert request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, "falsch")[0] == 401
    assert request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, tok, header={"Origin": "http://evil.example"})[0] == 403
    assert request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, tok)[0] == 400  # Sitzung fehlt
    assert request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, tok, "gibtsnicht")[0] == 404
    assert request(port, "GET", None, tok)[0] == 405
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", "/gesund")
    assert c.getresponse().status == 200


def test_two_sessions_two_conversations(srv):
    port, tok_a, tok_b = srv
    sa, sb = init(port, tok_a, "claude-code"), init(port, tok_b, "anderer-agent")
    st, _, listing = request(port, "POST", {"jsonrpc": "2.0", "id": 5, "method": "tools/list"}, tok_a, sa)
    names = {t["name"] for t in listing["result"]["tools"]}
    assert {"vi_before", "vi_after", "vi_recall"} <= names and "vi_erinnere" not in names  # 0.22.0: öffentlich englisch, deutsch nur noch Alias
    # Sitzung A meldet eine Handlung zweimal → beim 2. Mal aus dem Gedächtnis
    v = json.loads(call_tool(port, tok_a, sa, "vi_vorher", {"tool": "netbox_get_devices", "args": {"host": "web1"}})["content"][0]["text"])
    assert v["antwort"] is None
    call_tool(port, tok_a, sa, "vi_nachher", {"tool": "netbox_get_devices", "args": {"host": "web1"}, "ok": True, "dauer_ms": 40,
                                         "ergebnis": "web1: aktiv", "vorher_id": v["vorher_id"]})
    v2 = json.loads(call_tool(port, tok_b, sb, "vi_vorher", {"tool": "netbox_get_devices", "args": {"host": "web1"}})["content"][0]["text"])
    assert v2["antwort"] is None  # gemerkte Antworten sind privat je Instanz (können Zugangsdaten enthalten)
    sa2 = init(port, tok_a, "claude-code-2")  # neue Sitzung derselben Instanz → bekommt die Antwort
    v2b = json.loads(call_tool(port, tok_a, sa2, "vi_vorher", {"tool": "netbox_get_devices", "args": {"host": "web1"}})["content"][0]["text"])
    assert v2b["antwort"] == "web1: aktiv"
    # Gelerntes aus B erscheint vor der Handlung in A
    r = call_tool(port, tok_b, sb, "vi_lerne", {"text": "web1 antwortet nur über den Proxy", "hashtags": ["host:web1"],
                                            "quelle": "curl -v am 08.11."})
    assert not r["isError"], r
    v3 = json.loads(call_tool(port, tok_a, sa, "vi_vorher", {"tool": "checkmk_get_host", "args": {"host": "web1"}})["content"][0]["text"])
    assert any("Proxy" in h for h in v3["hinweise"])
    # Status nennt beide offenen Gespräche
    status = call_tool(port, tok_a, sa, "vi_status", {})["content"][0]["text"]
    assert "Offene Gespräche: 3" in status
    # Sitzung A beenden → Gespräch gesichert, Id danach unbekannt
    serial_a = session.find_without_touching(sa).serial
    assert request(port, "DELETE", None, tok_a, sa)[0] == 204
    assert request(port, "POST", {"jsonrpc": "2.0", "id": 9, "method": "ping"}, tok_a, sa)[0] == 404
    gs = g.load(f"gespraech:{serial_a}")
    # 2 Handlungen: eine mit nachher, eine nur mit vorher → ok:unbekannt, nicht verschwunden
    assert gs.data["zustand"] == "beendet" and gs.data["aufrufe"] == 2 and gs.data["ohne_ergebnis"] == 1
    assert [o.text for _, o, _g in g.recall("tool:checkmk_get_host ok:unbekannt")][0].endswith("(vi_after fehlt)")
    assert "instanz:laptop" in gs.hashtags and "host:web1" in gs.hashtags


def test_foreign_session_and_reflex_permission(srv):
    port, tok_a, tok_b = srv
    sa, sb = init(port, tok_a), init(port, tok_b)
    assert request(port, "POST", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, tok_b, sa)[0] == 404  # nicht seine Sitzung
    code = "def run(tool, args, ergebnis):\n    return 'gesehen: ' + tool"
    r = call_tool(port, tok_b, sb, "vi_reflex_lerne", {"name": "echo", "art": "nachher", "code": code,
                                                   "beschreibung": "meldet jedes Werkzeug", "quelle": "Test Reflex-Recht"})
    assert r["isError"] and "kein Reflex-Recht" in r["content"][0]["text"]
    r = call_tool(port, tok_a, sa, "vi_reflex_lerne", {"name": "echo", "art": "nachher", "code": code,
                                                   "beschreibung": "meldet jedes Werkzeug", "quelle": "Test Reflex-Recht"})
    assert not r["isError"], r
    n = json.loads(call_tool(port, tok_b, sb, "vi_nachher", {"tool": "x_y", "ok": True, "ergebnis": "e"})["content"][0]["text"])
    assert n["hinweise"] == ["Reflex echo (test): gesehen: x_y"]


def test_stack_and_unknown(srv):
    port, tok, _ = srv
    sid = init(port, tok)
    st, _, a = request(port, "POST", [{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                      {"jsonrpc": "2.0", "id": 2, "method": "gibts/nicht"},
                                      {"jsonrpc": "2.0", "method": "notifications/irgendwas"}], tok, sid)
    assert st == 200 and len(a) == 2 and a[0]["result"] == {} and a[1]["error"]["code"] == -32601
    st, _, a = request(port, "POST", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nix"}}, tok, sid)
    assert a["error"]["code"] == -32602


def test_several_addresses_one_memory(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    tok = config.create_instance("x")
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db"), "bind": ["127.0.0.1", "127.0.0.2"]})
    cfg.write_text(json.dumps(raw))
    srvs = server.build(config.load())
    assert [s.server_address[0] for s in srvs] == ["127.0.0.1", "127.0.0.2"] and srvs[0].request_queue_size == 64
    for s in srvs:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        sids = []
        for s in srvs:
            c = http.client.HTTPConnection(s.server_address[0], s.server_address[1], timeout=5)
            c.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
            r = c.getresponse(); r.read()
            sids.append(r.getheader("Mcp-Session-Id"))
        # beide Adressen, ein Prozess: zwei Gespräche im selben Gedächtnis
        assert len([o for _, o, _g in g.recall("art:gespraech instanz:x")]) == 2
    finally:
        for s in srvs:
            s.shutdown(); s.server_close()
        server.finish(srvs)


def test_http_calls_land_in_usage_stats(srv):
    """0.21.0: Der Server zählt jeden Aufruf eines VI-Werkzeugs mit Instanz und Client — auch abgelehnte."""
    from vi_mcp import usage_stats
    port, tok_a, _tok_b = srv
    sa = init(port, tok_a, "statistik-client")
    call_tool(port, tok_a, sa, "vi_erinnere", {"filter": "nichtsdergleichen"})  # alter deutscher Name (Alias) …
    assert call_tool(port, tok_a, sa, "vi_recall", {"text": "falsch benannt"})["isError"]  # … und der englische zählen unter einem Namen
    d = usage_stats.data(1)["nutzung"]
    assert d["je_werkzeug"]["vi_recall"]["n"] == 2 and d["je_werkzeug"]["vi_recall"]["abgelehnt"] == 1
    assert any(c.startswith("statistik-client") for c in d["clients"])
