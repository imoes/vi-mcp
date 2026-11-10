"""0.36.0: MCP over stdio — a bridge to the service's local socket; the kernel names the user, config `lokal` maps it to an instance."""
import json
import os
import pwd
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from vi_mcp import config, server, session
from vi_mcp import memory as g

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="local socket needs Linux (SO_PEERCRED)")
ME = pwd.getpwuid(os.getuid()).pw_name
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def local(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    monkeypatch.delenv("VI_MCP_SOCKET", raising=False)
    config.create_instance("anna")
    sock = str(tmp_path / "mcp.sock")
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db"), "socket": sock})
    cfg.write_text(json.dumps(raw))

    def start(mapping):
        raw.update({"lokal": mapping})
        cfg.write_text(json.dumps(raw))
        srvs = server.build(config.load())
        for s in srvs:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        started.append(srvs)
        return sock
    started = []
    yield start
    for srvs in started:
        for s in srvs:
            s.shutdown()
            s.server_close()
        server.finish(srvs)


def bridge(sock, messages):
    """Run `vi-mcp stdio` with these messages on stdin; the answers, one JSON object per line."""
    stdin = "".join(json.dumps(m) + "\n" for m in messages)
    r = subprocess.run([sys.executable, "-m", "vi_mcp", "stdio", "--socket", sock], input=stdin.encode(), capture_output=True,
                       cwd=ROOT, timeout=60, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0, r.stderr.decode()
    return [json.loads(line) for line in r.stdout.decode().splitlines()], r.stderr.decode()


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "claude-code", "version": "9"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def call(i, name, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}


def test_local_user_reads_internal_knowledge_without_a_token(local):
    sock = local({ME: "anna"})
    o = g.new_object("erkenntnis", "Internal runbook: restart the VPN concentrator with vpnctl restart", ["thema:vpn"],
                     {"quelle": "runbook 10.11.2026"}, instance="anna", visibility="intern")
    out, _err = bridge(sock, [INIT, INITIALIZED, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                              call(3, "vi_recall", {"filter": "thema:vpn"}),
                              call(4, "vi_learn", {"text": "learned over stdio, without any token", "hashtags": ["thema:stdio"], "source": "test 10.11.2026"})])
    assert [m["id"] for m in out] == [1, 2, 3, 4]  # the notification got no answer; stdout is JSON-RPC only
    assert "instance anna" in out[0]["result"]["instructions"]
    assert "vi_confirm" in {t["name"] for t in out[1]["result"]["tools"]}  # a real instance, not the open guest
    assert o.id in out[2]["result"]["content"][0]["text"]  # internal knowledge visible
    learned = g.load(out[3]["result"]["content"][0]["text"].split()[1])
    assert learned.instance == "anna"
    conv = g.recall("art:gespraech instanz:anna", viewer=None)
    assert conv and conv[0][1].data.get("familie") == "claude"  # family from the client name, as over HTTP


def test_unlisted_local_user_is_refused_with_the_reason(local):
    sock = local({"somebody-else": "anna"})
    out, _ = bridge(sock, [INIT])
    assert out[0]["id"] == 1 and out[0]["error"]["code"] == -32000
    assert f"local user {ME} has no instance on this socket" in out[0]["error"]["message"]
    assert f"vi-mcp local {ME} INSTANCE" in out[0]["error"]["message"]


def test_socket_open_to_all_users_but_only_mapped_ones_get_in(local):
    sock = local({ME: "anna"})
    assert oct(os.stat(sock).st_mode & 0o777) == "0o666"


def test_service_restart_renews_the_session_transparently(local):
    sock = local({ME: "anna"})
    from vi_mcp.stdio_bridge import Bridge
    import io
    out = io.BytesIO()
    b = Bridge(sock, out)
    b.handle(json.dumps(INIT).encode())
    first = b.sid
    session.end_all("unterbrochen")  # what a restart does to the sessions
    b.handle(json.dumps(call(2, "vi_status", {})).encode())
    answers = [json.loads(x) for x in out.getvalue().decode().splitlines()]
    assert answers[1]["id"] == 2 and "result" in answers[1] and b.sid and b.sid != first
    b.close()


def test_service_not_running_and_bad_json_are_answered(tmp_path):
    out, _ = bridge(str(tmp_path / "nothing.sock"), [INIT])
    assert "vi-mcp service not reachable" in out[0]["error"]["message"]
    r = subprocess.run([sys.executable, "-m", "vi_mcp", "stdio", "--socket", str(tmp_path / "x.sock")], input=b"{not json\n",
                       capture_output=True, cwd=ROOT, timeout=30, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert json.loads(r.stdout)["error"]["code"] == -32700


def test_set_local_checks_the_instance(tmp_path, monkeypatch):
    cfg = tmp_path / "c.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    config.create_instance("anna")
    with pytest.raises(ValueError, match="unknown"):
        config.set_local(ME, "bert")
    assert config.set_local(ME, "anna") is None and config.load().local == {ME: "anna"}
    assert config.set_local(ME, None) == "anna" and config.load().local == {}


def test_unit_opens_the_socket():
    unit = (ROOT / "deploy/debian/vi-mcp.service").read_text()
    assert "Environment=VI_MCP_SOCKET=/run/vi-mcp/mcp.sock" in unit and "RuntimeDirectory=vi-mcp" in unit and "RuntimeDirectoryMode=0755" in unit
    assert "AF_UNIX" in unit  # RestrictAddressFamilies must keep allowing it


def test_socket_that_cannot_be_opened_does_not_stop_the_service(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    config.create_instance("anna")
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db"), "socket": str(tmp_path / "missing-dir" / "mcp.sock")})
    cfg.write_text(json.dumps(raw))
    srvs = server.build(config.load())
    try:
        assert len(srvs) == 1  # HTTP only
    finally:
        for s in srvs:
            s.server_close()
        server.finish(srvs)
