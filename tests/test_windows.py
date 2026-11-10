"""0.27.0: Windows branches, simulated on Linux (the real check is the MSI on a Windows machine)."""
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

from vi_mcp import sandbox
from vi_mcp import setup as e


def test_setup_imports_without_posix_modules():
    """On Windows pwd, termios and tty do not exist — the module must still load (non-interactive setup)."""
    code = ("import sys; sys.modules['pwd'] = None; sys.modules['termios'] = None; sys.modules['tty'] = None\n"
            "import vi_mcp.setup as s; print(s.pwd is None and s.termios is None)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
    assert out.returncode == 0 and out.stdout.strip() == "True", out.stderr[-500:]


def test_windows_hook_entry_uses_hook_json(tmp_path, monkeypatch):
    monkeypatch.setattr(e, "WINDOWS", True)
    z = e.TargetUser("anna", tmp_path, -1, -1)
    e._hook_on(z, "https://vi.example/mcp", "tok123", None)
    cfg = json.loads((tmp_path / ".config" / "vi-mcp" / "hook.json").read_text())
    assert cfg == {"url": "https://vi.example/mcp", "token_file": str(tmp_path / ".config" / "vi-mcp" / "token-claude"), "signal_token_file": ""}
    cmd = json.loads((tmp_path / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd == f'"{sys.executable}" -I "{e._hook_script()}"' and "VI_MCP_URL=" not in cmd


def test_hook_reads_hook_json_and_environment_wins(tmp_path):
    (tmp_path / ".config" / "vi-mcp").mkdir(parents=True)
    (tmp_path / ".config" / "vi-mcp" / "hook.json").write_text(json.dumps({"url": "https://from-file/mcp", "token_file": ""}))
    hook = Path(__file__).resolve().parents[1] / "hook" / "vi_hook.py"
    probe = f"import runpy; g = runpy.run_path({str(hook)!r}, run_name='probe'); print(g['URL'], g['TOKEN_FILE'])"
    base = {k: v for k, v in os.environ.items() if not k.startswith("VI_MCP")} | {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    out = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, env=base)
    assert out.stdout.split() == ["https://from-file/mcp", os.devnull], out.stderr[-400:]  # empty token file = no token
    out = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, env=base | {"VI_MCP_URL": "https://env/mcp"})
    assert out.stdout.split()[0] == "https://env/mcp"


def test_reflex_code_never_runs_without_linux_sandbox(monkeypatch):
    monkeypatch.setattr(sandbox.sys, "platform", "win32")
    r = sandbox.run("def run(args): return 1", [])
    assert r["isolation"] == "keine" and "no sandbox on win32" in r["fehler"]


def test_windows_menu_points_to_flags(monkeypatch, capsys):
    monkeypatch.setattr(e, "WINDOWS", True)
    monkeypatch.setattr(e, "target", lambda: e.TargetUser("anna", Path("/nonexistent"), -1, -1))
    assert e.main(["--url", "http://127.0.0.1:8765/mcp"]) == 2
    assert "--claude --hook" in capsys.readouterr().err


def test_port_is_configurable(tmp_path, monkeypatch):
    """0.27.0: vi-mcp port [N] — show or set the server port; other keys and the file permissions stay."""
    from vi_mcp import config
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"bind": "127.0.0.1", "port": 8765, "instanzen": {"a": {"token_sha256": "x"}}}))
    os.chmod(p, 0o640)
    assert config.set_port(9100, p) == 8765
    raw = json.loads(p.read_text())
    assert raw["port"] == 9100 and raw["instanzen"] == {"a": {"token_sha256": "x"}} and (os.stat(p).st_mode & 0o777) == 0o640
    for bad in (80, 70000, "9000"):
        try:
            config.set_port(bad, p)
            raise AssertionError(f"{bad} accepted")
        except ValueError:
            pass
    out = subprocess.run([sys.executable, "-m", "vi_mcp", "port"], capture_output=True, text=True,
                         env={**os.environ, "VI_MCP_CONFIG": str(p)}, cwd=Path(__file__).resolve().parents[1])
    assert out.returncode == 0 and out.stdout.strip() == "9100"
