"""0.71.0: the server serves its own client integration under /plugins (vi_mcp/plugins.py) — a client with only the URL and a token
installs the hooks. Checked against a real server on a random port: what is served, that it is deterministic, that the token never
appears in a served file, a URL or a log, and that the hook takes URL and token from the plugin options."""
import hashlib
import http.client
import importlib.util
import io
import json
import threading
import zipfile
from pathlib import Path

import pytest

from vi_mcp import __version__, config, plugins, server

HOOK = Path(__file__).parent.parent / "hook" / "vi_hook.py"


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    started = []

    def start(**extra):
        cfg = tmp_path / f"c{len(started)}.json"
        monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
        tok = config.create_instance("anna")
        raw = json.loads(cfg.read_text())
        raw.update({"port": 0, "db": str(tmp_path / f"vi{len(started)}.db"), "hold_back": 0, **extra})
        cfg.write_text(json.dumps(raw))
        (s,) = server.build(config.load())
        threading.Thread(target=s.serve_forever, daemon=True).start()
        started.append(s)
        return s.server_address[1], tok
    yield start
    for s in started:
        s.shutdown()
        s.server_close()
        server.finish([s])


def get(port, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict(r.getheaders()), data


def test_marketplace_points_at_an_archive_whose_sha256_matches(srv):
    port, _tok = srv(public_url="https://vi.example.org/vi-mcp/")
    st, hd, body = get(port, "/plugins/claude/marketplace.json")
    assert st == 200 and hd["Content-Type"] == "application/json"
    m = json.loads(body)
    (p,) = m["plugins"]
    src = p["source"]
    assert m["name"] == "vi-mcp" and p["name"] == "vi-mcp" and p["version"] == __version__
    assert src["source"] == "archive" and src["url"] == f"https://vi.example.org/vi-mcp/plugins/claude/vi-mcp-{__version__}.zip"
    assert len(src["sha256"]) == 64 and all(c in "0123456789abcdef" for c in src["sha256"])
    st, hd, data = get(port, src["url"].split("/vi-mcp", 1)[1])
    assert st == 200 and hd["Content-Type"] == "application/zip"
    assert hashlib.sha256(data).hexdigest() == src["sha256"] == hd["X-Content-SHA256"]
    assert get(port, f"/plugins/claude/vi-mcp-{__version__}.zip")[2] == data  # deterministic: same bytes on every request
    assert get(port, "/plugins/claude/vi-mcp-0.0.1.zip")[0] == 404


def test_the_archive_is_a_complete_claude_code_plugin(srv):
    port, _tok = srv(public_url="https://vi.example.org")
    data = get(port, f"/plugins/claude/vi-mcp-{__version__}.zip")[2]
    z = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(z.namelist()) == [".claude-plugin/plugin.json", ".mcp.json", "README.md", "hook/vi_hook.py", "hooks/hooks.json"]
    manifest = json.loads(z.read(".claude-plugin/plugin.json"))
    uc = manifest["userConfig"]
    assert uc["url"]["default"] == "https://vi.example.org/mcp" and uc["token"]["sensitive"] is True
    for option in uc.values():  # the docs make type, title and description required (manifest-reference, "User configuration")
        assert {"type", "title", "description"} <= option.keys()
    mcp = json.loads(z.read(".mcp.json"))["mcpServers"]["vi-mcp"]
    assert mcp == {"type": "http", "url": "${user_config.url}", "headers": {"Authorization": "Bearer ${user_config.token}"}}
    hooks = json.loads(z.read("hooks/hooks.json"))["hooks"]
    assert set(hooks) == {"PreToolUse", "PostToolUse", "PostToolUseFailure", "SessionStart", "SessionEnd", "UserPromptSubmit", "Stop"}
    command = hooks["PreToolUse"][0]["hooks"][0]["command"]
    assert "${CLAUDE_PLUGIN_ROOT}/hook/vi_hook.py" in command and "user_config" not in command  # a shell-form hook may not use it
    assert z.read("hook/vi_hook.py") == HOOK.read_bytes()
    assert z.getinfo("hook/vi_hook.py").date_time == (1980, 1, 1, 0, 0, 0)


def test_the_token_is_in_no_served_file_and_no_url(srv):
    port, tok = srv(public_url="https://vi.example.org")
    served = [get(port, p, {"Authorization": f"Bearer {tok}"}) for p in
              ("/plugins", "/plugins/claude/marketplace.json", f"/plugins/claude/vi-mcp-{__version__}.zip", "/plugins/hook/vi_hook.py")]
    assert all(st == 200 for st, _h, _d in served)
    for _st, hd, data in served:
        assert tok.encode() not in data and tok not in json.dumps(hd)
    z = zipfile.ZipFile(io.BytesIO(served[2][2]))
    assert not any(tok.encode() in z.read(n) for n in z.namelist())  # inside the deflated entries too
    assert tok not in json.dumps(plugins.marketplace("https://vi.example.org"))


def test_urls_follow_the_request_without_public_url(srv):
    port, _tok = srv()
    st, _h, body = get(port, "/plugins/claude/marketplace.json",
                       {"Host": "inner:8765", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "vi.example.org", "X-Forwarded-Prefix": "/vi"})
    assert st == 200 and json.loads(body)["plugins"][0]["source"]["url"].startswith("https://vi.example.org/vi/plugins/claude/")
    st, _h, body = get(port, "/plugins")
    assert st == 200 and f"http://127.0.0.1:{port}/plugins/claude/marketplace.json" in body.decode()
    assert "only over https" in body.decode()  # an http base is named, not silently unusable
    assert get(port, "/plugins/claude/marketplace.json", {"Host": "evil host/../x"})[0] == 400


def test_plugins_can_be_switched_off(srv):
    port, _tok = srv(plugins=False)
    assert get(port, "/plugins")[0] == 404 and get(port, "/plugins/hook/vi_hook.py")[0] == 404
    assert b"/plugins" not in get(port, "/nothing")[2]


def _hook_module(monkeypatch, tmp_path, **env):
    for k in ("VI_MCP_URL", "VI_MCP_TOKEN_FILE", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_OPTION_URL", "CLAUDE_PLUGIN_OPTION_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("VI_HOOK_STATE", str(tmp_path / "state"))
    spec = importlib.util.spec_from_file_location("vi_hook_plugin", HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_hook_takes_url_and_token_from_the_plugin_options(srv, monkeypatch, tmp_path):
    port, tok = srv()
    h = _hook_module(monkeypatch, tmp_path, CLAUDE_PLUGIN_ROOT=str(tmp_path), CLAUDE_PLUGIN_OPTION_URL=f"http://127.0.0.1:{port}/mcp",
                     CLAUDE_PLUGIN_OPTION_TOKEN=tok)
    assert h.URL == f"http://127.0.0.1:{port}/mcp" and h._token() == tok
    v = h.call_tool("cc-plugin", "/tmp", "vi_before", {"tool": "Bash", "args": {"command": "true"}})
    assert v.get("vorher_id")  # authenticated with the option token
    empty = _hook_module(monkeypatch, tmp_path, CLAUDE_PLUGIN_ROOT=str(tmp_path), CLAUDE_PLUGIN_OPTION_URL="http://x/mcp",
                         CLAUDE_PLUGIN_OPTION_TOKEN="")
    assert empty._token() is None  # empty option = an open server, no "Bearer " with nothing
    outside = _hook_module(monkeypatch, tmp_path, CLAUDE_PLUGIN_OPTION_URL="http://x/mcp")  # option without the plugin root: ignored
    assert outside.PLUGIN_TOKEN is None and outside.URL != "http://x/mcp"


def test_the_plugin_token_never_reaches_the_hook_log(srv, monkeypatch, tmp_path, capsys):
    tok = "plugin-secret-test-token-0123456789"
    h = _hook_module(monkeypatch, tmp_path, CLAUDE_PLUGIN_ROOT=str(tmp_path), CLAUDE_PLUGIN_OPTION_URL="http://127.0.0.1:1/mcp",
                     CLAUDE_PLUGIN_OPTION_TOKEN=tok)
    ev = {"hook_event_name": "PreToolUse", "session_id": "cc-log", "cwd": "/tmp", "tool_name": "Bash", "tool_input": {}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(ev)))
    assert h.main() == 0
    log = (tmp_path / "state" / "hook.log").read_text()
    assert "continuing without memory" in log and tok not in log and tok not in capsys.readouterr().out


def test_a_second_installed_copy_of_the_hook_does_not_report_twice(monkeypatch, tmp_path):
    h = _hook_module(monkeypatch, tmp_path)
    raw = json.dumps({"hook_event_name": "PreToolUse", "session_id": "s", "tool_use_id": "t1"}).encode()
    assert h.claim(raw) is True and h.claim(raw) is False  # the plugin's copy and the settings.json copy get the same event
    assert h.claim(raw.replace(b"t1", b"t2")) is True
    calls = []
    monkeypatch.setattr(h, "process", lambda e: calls.append(e) or None)
    other = json.dumps({"hook_event_name": "Stop", "session_id": "s2"})
    for _ in range(2):
        monkeypatch.setattr("sys.stdin", io.StringIO(other))
        assert h.main() == 0
    assert len(calls) == 1
