"""0.9.0: Sandbox — Reflexe laufen im eigenen Prozess; Grenzen greifen; Reflex-Vertrag unverändert."""
import time

from vi_mcp import reflexe, sandbox, werkzeuge
from vi_mcp import gedaechtnis as g


def test_lauf_und_schema():
    code = "import json\nTOOL = {'description': 'zählt', 'inputSchema': {'type': 'object', 'properties': {}}}\ndef run(args):\n    return json.dumps({'n': len(args)})"
    erg = sandbox.lauf(code, [{"a": 1, "b": 2}])
    assert erg["wert"] == '{"n": 2}' and erg["isolation"].startswith("landlock-abi") and erg["dauer_ms"] >= 0
    assert sandbox.lauf(code, [], nur_schema=True)["schema"]["description"] == "zählt"


def test_endlosschleife_wird_beendet():
    t0 = time.monotonic()
    erg = sandbox.lauf("def run(a):\n    while True:\n        pass", [{}], wanduhr_s=1.5)
    assert "Zeitlimit" in erg["fehler"] and time.monotonic() - t0 < 5


def test_fehler_und_speicher():
    assert "ZeroDivisionError" in sandbox.lauf("def run(a):\n    return 1/0", [{}])["fehler"]
    erg = sandbox.lauf("def run(a):\n    x = bytearray(600 * 1024 * 1024)\n    return len(x)", [{}])
    assert "MemoryError" in erg["fehler"]


def test_isolation_ist_wirksam_und_benannt():
    assert sandbox.lauf("def run(a):\n    return 1", [{}])["isolation"].startswith("landlock-abi")


def _versuch(ausdruck, tmp_path=None):
    """Der Code umgeht bewusst die AST-Prüfung: die Sandbox muss allein halten."""
    return sandbox.lauf(f"import os, socket\ndef run(a):\n    return {ausdruck}", [{}])


def test_datei_lesen_schreiben_kuerzen_gesperrt(tmp_path):
    geheim = tmp_path / "geheim.db"
    geheim.write_text("zugangsdaten")
    p = str(geheim)
    assert "PermissionError" in sandbox.lauf(f"def run(a):\n    return open({p!r}).read()", [{}])["fehler"]
    assert "PermissionError" in sandbox.lauf(f"def run(a):\n    return open({p!r}, 'w').close()", [{}])["fehler"]  # kürzen
    assert geheim.read_text() == "zugangsdaten"
    assert "PermissionError" in sandbox.lauf(f"def run(a):\n    return open({str(tmp_path / 'neu')!r}, 'w').close()", [{}])["fehler"]
    assert not (tmp_path / "neu").exists()
    assert "PermissionError" in sandbox.lauf("def run(a):\n    return open('/etc/passwd').read()", [{}])["fehler"]


def test_netz_und_prozesse_gesperrt():
    assert "PermissionError" in _versuch("socket.socket(socket.AF_INET, socket.SOCK_DGRAM)")["fehler"]  # UDP
    assert "PermissionError" in _versuch("socket.socket(socket.AF_UNIX)")["fehler"]
    assert "PermissionError" in _versuch("os.fork()")["fehler"]
    assert _versuch("os.system('true')")["wert"] != 0  # system() kann nicht forken: Rückgabe -1/Fehler, kein Lauf


def test_ausgabeflut_wird_beendet():
    erg = sandbox.lauf("import os\ndef run(a):\n    while True:\n        os.write(1, b'x' * 65536)", [{}], wanduhr_s=8)
    assert "Ausgabe über" in erg["fehler"]


def test_ohne_sandbox_laeuft_nichts(monkeypatch):
    monkeypatch.setattr(sandbox, "LAEUFER", sandbox.LAEUFER.replace("    abi = landlock()", "    raise RuntimeError('Kernel ohne Landlock')"))
    erg = sandbox.lauf("def run(a):\n    return 'gelaufen'", [{}])
    assert erg["isolation"] == "keine" and "nicht ausgeführt" in erg["fehler"] and "wert" not in erg


def test_kein_zugriff_auf_server_zustand():
    # Der Reflex sieht keine Server-Module: vi_mcp ist nicht importierbar (-I -S, leerer Pfad, anderes cwd)
    erg = sandbox.lauf("import vi_mcp\ndef run(a):\n    return 'drin'", [{}])
    assert "ModuleNotFoundError" in erg["fehler"]


def test_reflex_vertrag_in_sandbox(gd):
    g.neues_objekt("reflex", "meldet das Werkzeug", ["reflex:echo", "reflexart:nachher", "modus:test"],
                   {"name": "echo", "art": "nachher", "code": "def run(tool, args, ergebnis):\n    return 'gesehen: ' + tool"},
                   oid="reflex:echo", modus="test", grund="T")
    g.neues_objekt("reflex", "Werkzeug", ["reflex:summe", "reflexart:werkzeug", "modus:aktiv"],
                   {"name": "summe", "art": "werkzeug", "code": "TOOL = {'description': 'summiert', 'inputSchema': {'type': 'object', 'properties': {'zahlen': {'type': 'array'}}}}\ndef run(args):\n    return str(sum(args.get('zahlen', [])))"},
                   oid="reflex:summe", modus="aktiv", grund="T")
    geladen = reflexe.lade_alle()
    assert set(geladen) == {"echo", "summe"} and "run" not in geladen["echo"]  # keine Funktion im Serverprozess
    assert reflexe.nachher("x_y", {}, "e") == ["Reflex echo (test): gesehen: x_y"]
    assert reflexe.als_werkzeug("vi_reflex_summe", {"zahlen": [1, 2, 3]}) == "6"
    assert any(t["name"] == "vi_reflex_summe" for t in reflexe.werkzeug_schemas())
    assert g.lade("reflex:echo").daten["isolation"].startswith("landlock-abi")
    assert "Reflex-Sandbox: eigener Prozess" in werkzeuge.rufe("vi_status", {}, "a", True)
