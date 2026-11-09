"""0.9.0: Sandbox — Reflexe laufen im eigenen Prozess; Grenzen greifen; Reflex-Vertrag unverändert."""
import time

from vi_mcp import reflexes, sandbox, tools
from vi_mcp import memory as g


def test_run_and_schema():
    code = "import json\nTOOL = {'description': 'zählt', 'inputSchema': {'type': 'object', 'properties': {}}}\ndef run(args):\n    return json.dumps({'n': len(args)})"
    res = sandbox.run(code, [{"a": 1, "b": 2}])
    assert res["wert"] == '{"n": 2}' and res["isolation"].startswith("landlock-abi") and res["dauer_ms"] >= 0
    assert sandbox.run(code, [], schema_only=True)["schema"]["description"] == "zählt"


def test_endless_loop_is_stopped():
    t0 = time.monotonic()
    res = sandbox.run("def run(a):\n    while True:\n        pass", [{}], wallclock_s=1.5)
    assert "Zeitlimit" in res["fehler"] and time.monotonic() - t0 < 5


def test_errors_and_memory():
    assert "ZeroDivisionError" in sandbox.run("def run(a):\n    return 1/0", [{}])["fehler"]
    res = sandbox.run("def run(a):\n    x = bytearray(600 * 1024 * 1024)\n    return len(x)", [{}])
    assert "MemoryError" in res["fehler"]


def test_isolation_is_effective_and_named():
    assert sandbox.run("def run(a):\n    return 1", [{}])["isolation"].startswith("landlock-abi")


def _attempt(expression, tmp_path=None):
    """Der Code umgeht bewusst die AST-Prüfung: die Sandbox muss allein halten."""
    return sandbox.run(f"import os, socket\ndef run(a):\n    return {expression}", [{}])


def test_file_read_write_truncate_blocked(tmp_path):
    secret = tmp_path / "geheim.db"
    secret.write_text("zugangsdaten")
    p = str(secret)
    assert "PermissionError" in sandbox.run(f"def run(a):\n    return open({p!r}).read()", [{}])["fehler"]
    assert "PermissionError" in sandbox.run(f"def run(a):\n    return open({p!r}, 'w').close()", [{}])["fehler"]  # kürzen
    assert secret.read_text() == "zugangsdaten"
    assert "PermissionError" in sandbox.run(f"def run(a):\n    return open({str(tmp_path / 'neu')!r}, 'w').close()", [{}])["fehler"]
    assert not (tmp_path / "neu").exists()
    assert "PermissionError" in sandbox.run("def run(a):\n    return open('/etc/passwd').read()", [{}])["fehler"]


def test_network_and_processes_blocked():
    assert "PermissionError" in _attempt("socket.socket(socket.AF_INET, socket.SOCK_DGRAM)")["fehler"]  # UDP
    assert "PermissionError" in _attempt("socket.socket(socket.AF_UNIX)")["fehler"]
    assert "PermissionError" in _attempt("os.fork()")["fehler"]
    assert _attempt("os.system('true')")["wert"] != 0  # system() kann nicht forken: Rückgabe -1/Fehler, kein Lauf


def test_output_flood_is_stopped():
    res = sandbox.run("import os\ndef run(a):\n    while True:\n        os.write(1, b'x' * 65536)", [{}], wallclock_s=8)
    assert "Ausgabe über" in res["fehler"]


def test_without_sandbox_nothing_runs(monkeypatch):
    monkeypatch.setattr(sandbox, "RUNNER", sandbox.RUNNER.replace("    abi = landlock()", "    raise RuntimeError('Kernel ohne Landlock')"))
    res = sandbox.run("def run(a):\n    return 'gelaufen'", [{}])
    assert res["isolation"] == "keine" and "nicht ausgeführt" in res["fehler"] and "wert" not in res


def test_no_access_to_server_state():
    # Der Reflex sieht keine Server-Module: vi_mcp ist nicht importierbar (-I -S, leerer Pfad, anderes cwd)
    res = sandbox.run("import vi_mcp\ndef run(a):\n    return 'drin'", [{}])
    assert "ModuleNotFoundError" in res["fehler"]


def test_reflex_contract_in_sandbox(gd):
    g.new_object("reflex", "meldet das Werkzeug", ["reflex:echo", "reflexart:nachher", "modus:test"],
                   {"name": "echo", "art": "nachher", "code": "def run(tool, args, ergebnis):\n    return 'gesehen: ' + tool"},
                   oid="reflex:echo", mode="test", reason="T")
    g.new_object("reflex", "Werkzeug", ["reflex:summe", "reflexart:werkzeug", "modus:aktiv"],
                   {"name": "summe", "art": "werkzeug", "code": "TOOL = {'description': 'summiert', 'inputSchema': {'type': 'object', 'properties': {'zahlen': {'type': 'array'}}}}\ndef run(args):\n    return str(sum(args.get('zahlen', [])))"},
                   oid="reflex:summe", mode="aktiv", reason="T")
    loaded = reflexes.load_all()
    assert set(loaded) == {"echo", "summe"} and "run" not in loaded["echo"]  # keine Funktion im Serverprozess
    assert reflexes.after("x_y", {}, "e") == ["Reflex echo (test): gesehen: x_y"]
    assert reflexes.as_tool("vi_reflex_summe", {"zahlen": [1, 2, 3]}) == "6"
    assert any(t["name"] == "vi_reflex_summe" for t in reflexes.tool_schemas())
    assert g.load("reflex:echo").data["isolation"].startswith("landlock-abi")
    assert "Reflex-Sandbox: eigener Prozess" in tools.call_tool("vi_status", {}, "a", True)
