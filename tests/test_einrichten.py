"""0.13.0: setup — merge configurations without touching foreign entries; menu over a real pseudo-terminal."""
import json
import os
import pty
import select
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

import pytest

from vi_mcp import setup as e
from vi_mcp import config, server

yaml = pytest.importorskip("yaml")
REPO = Path(__file__).resolve().parents[1]
CODEX = '''# Kommentar bleibt
model = "gpt"

[projects."/a"]
trust_level = "trusted"

[mcp_servers.skills]
command = "python3"
args = ["/x"]
'''
HERMES = '''# Kopf
model:
  default: x

mcp_servers:
  andere:
    url: "http://a"
  # Notiz
  zweite:
    command: y

tools:
  a: 1
'''


def test_codex_sets_and_replaces_only_own_table():
    t = e.codex_set(CODEX, "http://h/mcp", "tok")
    d = tomllib.loads(t)
    assert d["mcp_servers"]["vi-mcp"] == {"url": "http://h/mcp", "http_headers": {"Authorization": "Bearer tok", "X-VI-Family": "gpt"}}
    assert d["mcp_servers"]["skills"]["command"] == "python3" and "# Kommentar bleibt" in t
    t2 = e.codex_set(t, "http://i/mcp", "neu")
    assert t2.count("[mcp_servers.vi-mcp]") == 1 and tomllib.loads(t2)["mcp_servers"]["vi-mcp"]["url"] == "http://i/mcp"
    assert tomllib.loads(e.codex_remove(t2)) == tomllib.loads(CODEX)
    assert tomllib.loads(e.codex_set("", "http://h/mcp", "t"))["mcp_servers"]["vi-mcp"]


def test_codex_broken_file_is_kept():
    with pytest.raises(e.Refused, match="is not valid TOML"):
        e.codex_set("a = [", "u", "t")


def test_hermes_sets_replaces_removes():
    t = e.hermes_set(HERMES, "http://h/mcp")
    d = yaml.safe_load(t)
    assert d["mcp_servers"]["vi-mcp"] == {"url": "http://h/mcp", "headers": {"Authorization": "Bearer ${VI_MCP_TOKEN}"}}
    assert set(d["mcp_servers"]) == {"andere", "zweite", "vi-mcp"} and d["tools"] == {"a": 1} and "# Notiz" in t
    t2 = e.hermes_set(t, "http://i/mcp")
    assert t2.count("vi-mcp:") == 1 and yaml.safe_load(t2)["mcp_servers"]["vi-mcp"]["url"] == "http://i/mcp"
    assert yaml.safe_load(e.hermes_remove(t2)) == yaml.safe_load(HERMES)


@pytest.mark.parametrize("text", ["", "a: 1\n", "a: 1\nmcp_servers: {}\nb: 2\n", "mcp_servers:\n", "a: 1\nmcp_servers: null\n", "mcp_servers:\n    x:\n        url: u\nb: 1\n"])
def test_hermes_edge_cases(text):
    d = yaml.safe_load(e.hermes_set(text, "http://h/mcp"))
    old = yaml.safe_load(text) or {}
    assert d["mcp_servers"]["vi-mcp"]["url"] == "http://h/mcp"
    assert {k: v for k, v in d.items() if k != "mcp_servers"} == {k: v for k, v in old.items() if k != "mcp_servers"}
    if old.get("mcp_servers"):
        assert d["mcp_servers"]["x"] == {"url": "u"}


def test_hermes_inline_is_refused():
    with pytest.raises(e.Refused, match="inline notation"):
        e.hermes_set("mcp_servers: {a: {url: b}}\n", "u")


def test_env():
    t = e.env_set("A=1\nVI_MCP_TOKEN=alt\n", "neu")
    assert t == "A=1\nVI_MCP_TOKEN=neu\n" and e.env_set(t, None) == "A=1\n" and e.env_set("", None) == ""


@pytest.fixture()
def target(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("SUDO_USER", raising=False)
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:/usr/bin:/bin")
    monkeypatch.setattr(e, "SYSTEM_BIN", [])
    monkeypatch.setenv("VI_MCP_CONFIG", str(tmp_path / "gibtsnicht.json"))
    (tmp_path / "bin").mkdir()
    return e.target()


def _program(tmp_path, name):
    p = tmp_path / "bin" / name
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)


def test_claude_and_hook_leave_foreign_entries_alone(target):
    (target.home / ".claude").mkdir()
    (target.home / ".claude.json").write_text(json.dumps({"numStartups": 7, "mcpServers": {"x": {"command": "y"}}}))
    (target.home / ".claude/settings.json").write_text(json.dumps({"model": "m", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "fremd"}]}]}}))
    e._claude_on(target, "http://h/mcp", "tok")
    d = json.loads((target.home / ".claude.json").read_text())
    assert d["numStartups"] == 7 and d["mcpServers"]["x"] == {"command": "y"} and d["mcpServers"]["vi-mcp"]["headers"]["Authorization"] == "Bearer tok"
    assert oct((target.home / ".claude.json").stat().st_mode)[-3:] == "600" and list(target.home.glob(".claude.json.bak-vi-mcp-*"))
    assert e._hook_on(target, "http://h/mcp", "tok", None).endswith("without correction detection (no signal token)")
    e._hook_on(target, "http://i/mcp", "tok", "sig")
    s = json.loads((target.home / ".claude/settings.json").read_text())
    assert len(s["hooks"]["PreToolUse"]) == 2 and s["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "fremd" and "http://i/mcp" in s["hooks"]["PreToolUse"][1]["hooks"][0]["command"]
    assert len(s["hooks"]["UserPromptSubmit"]) == 1 and "tok" not in s["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"].replace("token", "")
    assert (target.home / ".config/vi-mcp/token-nutzer").read_text() == "sig\n"
    e._hook_off(target)
    s = json.loads((target.home / ".claude/settings.json").read_text())
    assert list(s["hooks"]) == ["PreToolUse"] and len(s["hooks"]["PreToolUse"]) == 1 and s["model"] == "m"
    assert not (target.home / ".config/vi-mcp/token-nutzer").exists()


def test_broken_json_is_not_overwritten(target):
    p = target.home / ".claude.json"
    p.write_text("{kaputt")
    with pytest.raises(e.Refused):
        e._claude_on(target, "u", "t")
    assert p.read_text() == "{kaputt"


def test_symlink_stays_symlink(target, tmp_path):
    real = tmp_path / "echt.json"
    real.write_text("{}")
    (target.home / ".claude.json").symlink_to(real)
    e._claude_on(target, "u", "t")
    assert (target.home / ".claude.json").is_symlink() and "vi-mcp" in real.read_text()


def test_status_names_every_case(target, tmp_path):
    _program(tmp_path, "claude")
    (target.home / ".codex").mkdir()
    s = {x.key: x for x in e.progress(target)}
    assert s["claude"].present == "installiert" and s["codex"].present == "nur_konfiguration" and s["hermes"].present == "fehlt" and "not found" in s["hermes"].text
    assert s["hook"].present == "installiert"


def _menu(statuses, token="t", server=("token_ok", "ok"), auto=False):
    return e.Menu("n", "http://h/mcp", token, auto, server, statuses, lines=e.lines_for(statuses, "einrichten"))


STATUSES = [e.SetupStatus("claude", "Claude Code", "installiert", False, "noch nicht eingerichtet"), e.SetupStatus("codex", "Codex CLI", "fehlt", False, "nicht gefunden: codex"),
           e.SetupStatus("hermes", "Hermes Agent", "installiert", True, "eingerichtet: u"), e.SetupStatus("hook", "Claude-Code-Hook", "installiert", False, "meldet")]


def test_menu_defaults_and_disabled_items():
    m = _menu(STATUSES)
    assert [z.to for z in m.lines] == [True, False, False, True]
    e.keystroke(m, "runter")
    e.keystroke(m, " ")
    assert not m.lines[1].to and "nicht gefunden" in m.notice  # not selectable, with reason
    assert "[-]" in e.record(m, color=False)


def test_menu_enter_names_the_reason():
    m = _menu(STATUSES, token=None, server=("nicht_erreichbar", "refused"))
    assert e.keystroke(m, "enter") is None and "refused" in m.notice
    m = _menu(STATUSES, token=None, server=("nicht_erreichbar", "x"), auto=True)  # freshly installed: service starts only with tokens
    assert e.keystroke(m, "enter") == "los" and "not running yet" in e.record(m, color=False)
    m = _menu(STATUSES, token="falsch", server=("token_abgelehnt", "HTTP 401"))
    e.keystroke(m, "enter")
    assert "401" in m.notice
    for z in (m := _menu(STATUSES)).lines:
        z.to = False
    assert e.obstacle(m) == "nothing selected"


def test_menu_remove_only_what_exists():
    m = _menu(STATUSES)
    e.keystroke(m, "e")
    assert m.mode == "entfernen" and [z.selectable for z in m.lines] == [False, False, True, False] and not any(z.to for z in m.lines)


def test_narrow_rendering_does_not_overflow():
    assert all(len(z) <= 39 for z in e.record(_menu(STATUSES), width=40, color=False).split("\r\n"))


@pytest.fixture()
def ongoing(tmp_path, monkeypatch):
    cfg = tmp_path / "srv.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    tok = config.create_instance("a")
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db")})
    cfg.write_text(json.dumps(raw))
    (s,) = server.build(config.load())
    threading.Thread(target=s.serve_forever, daemon=True).start()
    monkeypatch.delenv("VI_MCP_CONFIG")
    yield f"http://127.0.0.1:{s.server_address[1]}/mcp", tok
    s.shutdown()
    s.server_close()
    server.finish([s])


def test_check(ongoing):
    url, tok = ongoing
    assert e.check(url, tok)[0] == "token_ok"
    assert e.check(url, "falsch") == ("token_abgelehnt", "server refuses the token (HTTP 401)")
    assert e.check(url, None)[0] == "erreichbar"
    assert e.check("http://127.0.0.1:1/mcp", "t")[0] == "nicht_erreichbar"
    assert e.check("kaputt", "t")[0] == "nicht_erreichbar"


def test_wrong_token_is_not_registered(ongoing, target):
    url, tok = ongoing
    r = e.setup(["claude"], target, url, "falsch")
    assert not r[0].ok and "401" in r[0].text and not (target.home / ".claude.json").exists()
    assert e.setup(["claude", "codex"], target, url, tok)[1].ok and tomllib.loads((target.home / ".codex/config.toml").read_text())


def test_automatic_tokens_on_the_server(ongoing, target, tmp_path, monkeypatch):
    url, _ = ongoing
    cfg = tmp_path / "auto.json"
    cfg.write_text("{}")
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    monkeypatch.setattr(e, "_restart", lambda: "kein Dienst")
    r = e.setup(["claude"], target, url, None)
    assert not r[0].ok and "not restarted" in r[0].text and not (target.home / ".claude.json").exists()
    monkeypatch.setattr(e, "_restart", lambda: None)
    monkeypatch.setattr(e, "check", lambda u, t, timeout=4: ("erreichbar", "x") if t is None else ("token_ok", "x"))
    r = e.setup(["claude", "hook"], target, url, None)
    assert all(x.ok for x in r), r
    inst = json.loads(cfg.read_text())["instances"]
    assert set(inst) == {f"{target.name}-claude", f"{target.name}-nutzer"} and inst[f"{target.name}-nutzer"]["human"] and not inst[f"{target.name}-claude"]["human"]
    assert (target.home / ".config/vi-mcp/token-claude").read_text().strip() == e._claude_token(target)  # hook and MCP use the same instance


def _pty_run(args, env, keystrokes, ts=20):
    pty_master, pty_slave = pty.openpty()
    p = subprocess.Popen([sys.executable, "-m", "vi_mcp", "einrichten", *args], stdin=pty_slave, stdout=pty_slave, stderr=pty_slave, env=env, cwd=REPO, close_fds=True, start_new_session=True)
    os.close(pty_slave)
    outputs, end, i = b"", time.time() + ts, 0
    upcoming = time.time() + 1.2
    while time.time() < end:
        r, _, _ = select.select([pty_master], [], [], 0.1)
        if r:
            try:
                d = os.read(pty_master, 65536)
            except OSError:
                break
            if not d:
                break
            outputs += d
        if i < len(keystrokes) and time.time() > upcoming and b"Enter:" in outputs:
            os.write(pty_master, keystrokes[i])
            i += 1
            upcoming = time.time() + 0.25
        if p.poll() is not None and not r:
            break
    p.wait(timeout=5)
    os.close(pty_master)
    return p.returncode, outputs.decode("utf-8", "replace")


def test_menu_in_pseudoterminal(ongoing, target, tmp_path):
    url, tok = ongoing
    _program(tmp_path, "claude")
    (tmp_path / "t").write_text(tok)
    env = {**os.environ, "PYTHONPATH": str(REPO), "TERM": "xterm"}
    code, outputs = _pty_run(["--url", url, "--token-datei", str(tmp_path / "t")], env, [b"\x1b[B", b"\x1b[B", b"\x1b[B", b" ", b"\r"])
    assert code == 0, outputs
    assert "\x1b[?1049h" in outputs and "\x1b[?1049l" in outputs and "\x1b[?25h" in outputs and "✓ Claude Code" in outputs and "Hook" not in outputs.split("\x1b[?1049l")[-1]
    assert json.loads((target.home / ".claude.json").read_text())["mcpServers"]["vi-mcp"]["url"] == url


def test_menu_ends_when_idle(target):
    code, outputs = _pty_run(["--url", "http://127.0.0.1:1/mcp", "--leerlauf", "1"], {**os.environ, "PYTHONPATH": str(REPO), "TERM": "xterm"}, [], ts=15)
    assert code == 0 and "sudo vi-mcp setup" in outputs and "\x1b[?25h" in outputs


def test_without_terminal_the_hint_appears(target):
    r = subprocess.run([sys.executable, "-m", "vi_mcp", "einrichten"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env={**os.environ, "PYTHONPATH": str(REPO)}, cwd=REPO)
    assert r.returncode == 2 and "No terminal" in r.stderr
