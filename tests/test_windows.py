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
    assert cmd == f'"{sys.executable}" -I -X utf8 "{e._hook_script()}"' and "VI_MCP_URL=" not in cmd


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
    # 0.51.0: a German file is written back in English
    assert raw["port"] == 9100 and raw["instances"] == {"a": {"token_sha256": "x"}} and (os.stat(p).st_mode & 0o777) == 0o640
    for bad in (80, 70000, "9000"):
        try:
            config.set_port(bad, p)
            raise AssertionError(f"{bad} accepted")
        except ValueError:
            pass
    out = subprocess.run([sys.executable, "-m", "vi_mcp", "port"], capture_output=True, text=True,
                         env={**os.environ, "VI_MCP_CONFIG": str(p)}, cwd=Path(__file__).resolve().parents[1])
    assert out.returncode == 0 and out.stdout.strip() == "9100"


def test_windows_scripts_are_ascii():
    """Windows PowerShell 5.1 reads a .ps1 without BOM as Windows-1252: an em dash (E2 80 94) becomes â€” whose 0x94 is a curly quote,
    PowerShell treats it as a string delimiter and the script breaks (MSI error 1722, found in a Windows 11 VM, 10.11.2026)."""
    root = Path(__file__).resolve().parents[1] / "deploy" / "windows"
    for f in [*root.glob("*.ps1"), *root.glob("*.cmd")]:
        bad = sorted({c for c in f.read_text(encoding="utf-8") if ord(c) > 127})
        assert not bad, f"{f.name}: non-ASCII {bad}"


def test_config_with_bom_is_read(tmp_path):
    """0.28.1: PowerShell 5.1 `Set-Content -Encoding utf8` writes a BOM; config.load and set_port must still read the file."""
    from vi_mcp import config
    cfg = tmp_path / "config.json"
    cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps({"bind": "127.0.0.1", "port": 8766}).encode())
    assert config.load(cfg).port == 8766
    assert config.set_port(8770, cfg) == 8766 and config.load(cfg).port == 8770
    assert not cfg.read_bytes().startswith(b"\xef\xbb\xbf")  # written back without BOM


def test_installer_writes_config_without_bom():
    s = (Path(__file__).parent.parent / "deploy/windows/install.ps1").read_text()
    assert "UTF8Encoding($false)" in s and "Set-Content -Path $cfg" not in s


def test_windows_default_config_is_programdata(monkeypatch, tmp_path):
    """0.28.1: without VI_MCP_CONFIG (a process started before the MSI set it) Windows still finds the server configuration."""
    from vi_mcp import config
    monkeypatch.delenv("VI_MCP_CONFIG", raising=False)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("ProgramData", str(tmp_path))
    assert config.fpath() == tmp_path / "vi-mcp" / "config.json"
    monkeypatch.setattr(config.sys, "platform", "linux")
    assert config.fpath() == config.DEFAULT_PATH


def test_client_hangup_leaves_no_traceback(capsys):
    from vi_mcp import server
    s = server.Server.__new__(server.Server)
    try:
        raise ConnectionResetError(10054, "forcibly closed")
    except ConnectionResetError:
        s.handle_error(None, ("127.0.0.1", 1))
    assert "Traceback" not in capsys.readouterr().err


def test_hook_output_is_utf8_under_cp1252(tmp_path):
    """0.28.1: the hook writes UTF-8 even when the locale is cp1252 (Windows, stdout to a pipe)."""
    hook = Path(__file__).resolve().parents[1] / "hook" / "vi_hook.py"
    probe = ("import runpy, sys; g = runpy.run_path(%r, run_name='probe'); "
             "g['main'].__globals__['process'] = lambda e: {'hookSpecificOutput': {'additionalContext': 'nginx -t → reload, P ≤ 0.2'}}; "
             "sys.stdin = __import__('io').StringIO('{\"hook_event_name\": \"PreToolUse\"}'); sys.exit(g['main']())") % str(hook)
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "HOME": str(tmp_path), "VI_MCP_URL": "http://127.0.0.1:9/mcp"}
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr.decode(errors="replace")
    assert "→ reload, P ≤ 0.2" in r.stdout.decode("utf-8")


def _ui_rows():
    """Rows of ui.sql per table, parsed from the INSERT statements (no msitools needed)."""
    import re
    rows: dict[str, list[dict]] = {}
    for line in (Path(__file__).parent.parent / "deploy/windows/ui.sql").read_text().splitlines():
        m = re.match(r"INSERT INTO `(\w+)` \((.*?)\) VALUES \((.*)\)$", line)
        if not m:
            assert not line.strip() or line.startswith("CREATE TABLE"), line[:80]
            continue
        cols = [c.strip(" `") for c in m.group(2).split(",")]
        vals = [v.strip().strip("'") for v in re.findall(r"'(?:[^']|'')*'|-?\d+", m.group(3))]
        assert len(cols) == len(vals), line[:120]
        rows.setdefault(m.group(1), []).append(dict(zip(cols, vals)))
    return rows


def test_msi_ui_is_consistent():
    """0.34.0: every dialog in the UI sequence exists, every event and condition names a control of its dialog, buttons chain."""
    r = _ui_rows()
    dialogs = {d["Dialog"] for d in r["Dialog"]}
    controls = {(c["Dialog_"], c["Control"]) for c in r["Control"]}
    assert {"WelcomeDlg", "MaintenanceDlg", "ProgressDlg", "ExitDialog", "UserExit", "FatalError"} == dialogs
    assert {s["Action"] for s in r["InstallUISequence"]} - {"VI_SetUpdate"} == dialogs
    for d in r["Dialog"]:
        for k in ("Control_First", "Control_Default", "Control_Cancel"):
            assert (d["Dialog"], d[k]) in controls, (d["Dialog"], k)
    for t in ("ControlEvent", "ControlCondition", "EventMapping"):
        for e in r[t]:
            assert (e["Dialog_"], e["Control_"]) in controls, (t, e)
    for c in r["Control"]:
        if c.get("Control_Next"):
            assert (c["Dialog_"], c["Control_Next"]) in controls, c
    welcome = {c["Control"]: c for c in r["Control"] if c["Dialog_"] == "WelcomeDlg"}
    assert welcome["Go"]["Text"] == "[VI_GO]" and welcome["ProxyEdit"]["Property"] == "PROXY"
    assert any(a["Action"] == "VI_SetUpdate" and a["Condition"] == "WIX_UPGRADE_DETECTED" for a in r["InstallUISequence"])


def test_msi_update_is_transactional_and_remembers_options():
    """0.34.0: the old version is removed inside the transaction (a failed update rolls back to it), and server mode and proxy of the
    previous installation are reused when not given — found in the Windows 11 test VM, 10.11.2026."""
    root = Path(__file__).parent.parent / "deploy/windows"
    assert "SET Sequence = 1501 WHERE Action = 'RemoveExistingProducts'" in (root / "patch-msi.sh").read_text()
    build = (root / "build.sh").read_text()
    assert '<Property Id="SERVER"' not in build and "-WindowStyle Hidden" in build and "ui.sql" in build
    ps = (root / "install.ps1").read_text()
    assert "install-options.json" in ps and "$previous.proxy" in ps and "$previous.server" in ps
    assert "Invoke-Logged $vpy ($pipArgs + $Packages)" in ps and "& $vpy @pipArgs" not in ps


def test_server_imports_without_unix_sockets():
    """0.38.2: Windows has no socketserver.UnixStreamServer — the server must import and run without it (the MSI rolled back on
    0.36.0–0.38.1 because `import vi_mcp.server` raised AttributeError)."""
    import subprocess, sys
    code = ("import socketserver, socket\n"
            "del socketserver.UnixStreamServer\n"
            "import vi_mcp.server as s\n"
            "assert s.LocalServer is None\n"
            "print('ok')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


def test_install_checks_that_the_server_imports():
    """0.38.2: the MSI's import check covers vi_mcp.server — a server that cannot start must roll the installation back."""
    ps = (Path(__file__).resolve().parent.parent / "deploy/windows/install.ps1").read_text()
    assert "import vi_mcp, vi_mcp.server, vi_mcp.tools" in ps and 'throw "vi_mcp (server) is not importable' in ps
    assert ps.isascii()


# ---- 0.54.0: the network services on Windows (the MSI joins the wiki network like the Linux packages)

def test_net_cli_imports_without_pwd():
    code = "import sys; sys.modules['pwd'] = None\nimport vi_mcp.net_cli as n; print(n.pwd is None and n._root() in (True, False))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
    assert out.returncode == 0 and out.stdout.strip() == "True", out.stderr[-500:]


def test_network_paths_on_windows(monkeypatch):
    from vi_mcp import net_service as nd
    monkeypatch.delenv("VI_P2P_DIR", raising=False)
    monkeypatch.setenv("ProgramData", "/ProgramData")
    monkeypatch.setattr(nd, "WINDOWS", True)
    try:
        assert nd.etc_dir() == Path("/ProgramData") / "vi-mcp" / "p2p" == nd.var_dir()
        k = nd.NetConfig()
        assert Path(k.db).parent == nd.etc_dir() and Path(k.mcp_token_file) == nd.etc_dir() / "mcp-token"
    finally:
        monkeypatch.setattr(nd, "WINDOWS", False)
    assert nd.etc_dir() == Path("/etc/vi-p2p") and nd.var_dir() == Path("/var/lib/vi-p2p")


def test_service_control_on_windows_uses_scheduled_tasks(tmp_path, monkeypatch):
    from vi_mcp import net_cli
    assert net_cli.task_name("vi-p2p@wiki") == "vi-p2p-wiki" and net_cli.task_name("vi-mcp") == "vi-mcp"
    calls = []
    monkeypatch.delenv("VI_MCP_KEIN_DIENST", raising=False)
    monkeypatch.setattr(net_cli.subprocess, "run", lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "running\n", ""))
    monkeypatch.setattr(net_cli.sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(net_cli.nd, "WINDOWS", True)
    try:
        assert net_cli._service("enable", "vi-p2p@wiki") == f"{tmp_path / 'vi-p2p.cmd'} missing (installed by the MSI)" and not calls
        (tmp_path / "vi-p2p.cmd").write_text("@echo off\n")
        assert net_cli._service("enable", "vi-p2p@wiki") is None
        assert net_cli._service("restart", "vi-mcp") is None
        assert net_cli._service("disable", "--now", "vi-p2p@wiki") is None
        assert net_cli.service_state("vi-p2p@wiki") == "running"
    finally:
        monkeypatch.setattr(net_cli.nd, "WINDOWS", False)
    enable, restart, disable, state = (c[-1] for c in calls)
    assert all(c[0] == "powershell.exe" for c in calls)
    assert "Register-ScheduledTask -TaskName 'vi-p2p-wiki'" in enable and f"-Execute '{tmp_path / 'vi-p2p.cmd'}' -Argument 'wiki'" in enable
    assert "S-1-5-18" in enable and "-AtStartup" in enable
    assert "Start-ScheduledTask -TaskName 'vi-mcp'" in restart
    assert "Disable-ScheduledTask -TaskName 'vi-p2p-wiki'" in disable and "Get-ScheduledTask -TaskName 'vi-p2p-wiki'" in state


def test_msi_carries_the_network_service():
    root = Path(__file__).resolve().parents[1] / "deploy" / "windows"
    build, ps, un = ((root / f).read_text() for f in ("build.sh", "install.ps1", "uninstall.ps1"))
    assert "deploy/windows/vi-p2p.cmd" in build and "wiki=[WIKI]" in build and "WIKI" in (root / "patch-msi.sh").read_text()
    assert '"net", "wiki", "on"' in ps and '"wiki" { if ($v) { $Wiki = $v } }' in ps and 'Get-ScheduledTask -TaskName "vi-p2p*"' in un
    # 0.54.1: the setup dialog names the wiki server (property WIKI, remembered like the proxy), 0 = none
    ui = (root / "ui.sql").read_text()
    assert "'WikiEdit', 'Edit'" in ui and "'WIKI', '{200}'" in ui and "'Cancel', 'WikiEdit')" in ui
    assert '"--start", $Wiki' in ps and "wiki = $Wiki" in ps and '"net", "wiki", "off"' in ps and "$previous.wiki" in ps and '-not $wikiTask' in ps
    cmd = (root / "vi-p2p.cmd").read_text()
    assert "-m vi_mcp net run" in cmd and r"%ProgramData%\vi-mcp\p2p\%N%.json" in cmd
    for text in (ps, un, cmd):
        assert text.isascii()  # Windows PowerShell 5.1 reads a file without BOM as ANSI
