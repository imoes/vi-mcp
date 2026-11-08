"""Block 4: Claude-Code-Hook gegen echten vi-mcp-Server (Hook-Ereignisse als JSON wie von Claude Code)."""
import importlib.util
import json
from pathlib import Path

import pytest

from vi_mcp import gedaechtnis as g

from test_http import srv  # noqa: F401 — Fixture: echter Server auf Zufallsport

_spec = importlib.util.spec_from_file_location("vi_hook", Path(__file__).parent.parent / "hook" / "vi_hook.py")
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


@pytest.fixture()
def h(srv, tmp_path, monkeypatch):  # noqa: F811
    port, tok, _ = srv
    (tmp_path / "token").write_text(tok + "\n")
    monkeypatch.setattr(hook, "URL", f"http://127.0.0.1:{port}/mcp")
    monkeypatch.setattr(hook, "TOKEN_DATEI", tmp_path / "token")
    monkeypatch.setattr(hook, "ZUSTAND", tmp_path / "hook")
    return hook


def ev(name, sitzung="cc-1", **kw):
    return {"hook_event_name": name, "session_id": sitzung, "cwd": "/tmp", **kw}


def test_werkzeugname_und_lesend():
    assert hook.werkzeug("mcp__skills__netbox_get_devices") == ("netbox_get_devices", "skills")
    assert hook.werkzeug("Bash") == ("Bash", None)
    assert hook.lesend_angabe("Read") is False and hook.lesend_angabe("mcp__x__y") is None


def test_vorher_nachher_und_gemerkte_antwort(h):
    t = "mcp__skills__netbox_get_devices"
    assert h.verarbeite(ev("PreToolUse", tool_name=t, tool_input={"host": "web1"}, tool_use_id="u1")) is None
    h.verarbeite(ev("PostToolUse", tool_name=t, tool_input={"host": "web1"}, tool_use_id="u1",
                    tool_response={"content": [{"type": "text", "text": "web1 aktiv"}]}))
    e = [o for _, o, _g in g.erinnere("tool:netbox_get_devices art:erfahrung ok:ja")]
    assert len(e) == 1 and e[0].daten["vorher"]["reize"][:3] == ["tool:netbox_get_devices", "skill:netbox", "host:web1"]
    # zweiter gleicher Aufruf (andere Claude-Sitzung): aus dem Gedächtnis → verweigert mit der Antwort als Grund
    aus = h.verarbeite(ev("PreToolUse", "cc-2", tool_name=t, tool_input={"host": "web1"}, tool_use_id="u2"))
    hs = aus["hookSpecificOutput"]
    assert hs["permissionDecision"] == "deny" and "web1 aktiv" in hs["permissionDecisionReason"]


def test_eingebaute_werkzeuge_nie_aus_gedaechtnis(h):
    for uid in ("r1", "r2"):
        aus = h.verarbeite(ev("PreToolUse", tool_name="Read", tool_input={"file_path": "/etc/hosts"}, tool_use_id=uid))
        assert aus is None
        h.verarbeite(ev("PostToolUse", tool_name="Read", tool_input={"file_path": "/etc/hosts"}, tool_use_id=uid, tool_response="inhalt"))
    assert len(g.erinnere("tool:Read art:erfahrung")) == 2 and not g.erinnere("tool:Read art:antwort")


def test_fehler_hinweis_und_eigene_werkzeuge(h):
    h.verarbeite(ev("PreToolUse", tool_name="Bash", tool_input={"command": "x"}, tool_use_id="b1"))
    h.verarbeite(ev("PostToolUseFailure", tool_name="Bash", tool_input={"command": "x"}, tool_use_id="b1", error="Exit 127: x: not found"))
    assert [o.text for _, o, _g in g.erinnere("tool:Bash ok:nein")][0].startswith("Bash(")
    g.neues_objekt("erkenntnis", "Bash hier ohne Proxy-Variablen", ["tool:Bash"], {"quelle": "Test"}, grund="T")
    aus = h.verarbeite(ev("PreToolUse", tool_name="Bash", tool_input={"command": "y"}, tool_use_id="b2"))
    assert "ohne Proxy-Variablen" in aus["hookSpecificOutput"]["additionalContext"]
    assert h.verarbeite(ev("PreToolUse", tool_name="mcp__vi-mcp__vi_status", tool_input={}, tool_use_id="v1")) is None
    assert not g.erinnere("tool:vi_status")


def test_sitzungsende_und_neustart_des_servers(h):
    h.verarbeite(ev("PreToolUse", "cc-9", tool_name="Grep", tool_input={"pattern": "a"}, tool_use_id="g1"))
    serial = [o for _, o, _g in g.erinnere("art:gespraech instanz:laptop")][0].daten["serial"]
    h.verarbeite(ev("SessionEnd", "cc-9", reason="exit"))
    gs = g.lade(f"gespraech:{serial}")
    assert gs.daten["zustand"] == "beendet" and gs.daten["ohne_ergebnis"] == 1  # vorher ohne nachher: benannt
    # Zustandsdatei zeigt auf eine unbekannte Sitzung (Server neu gestartet) → Hook meldet sich neu an
    h.schreibe("sitzung", "cc-10", {"mcp_session_id": "veraltet"})
    assert h.verarbeite(ev("PreToolUse", "cc-10", tool_name="Glob", tool_input={"pattern": "*"}, tool_use_id="g2")) is None
    assert h.lies("sitzung", "cc-10")["mcp_session_id"] != "veraltet"


def test_ausfall_laeuft_durch(h, monkeypatch, capsys):
    monkeypatch.setattr(h, "URL", "http://127.0.0.1:1/mcp")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(ev("PreToolUse", tool_name="Bash", tool_input={}))))
    assert h.main() == 0
    assert capsys.readouterr().out == ""
    assert "ohne Gedächtnis weiter" in (h.ZUSTAND / "hook.log").read_text()


def test_maskierung_und_kuerzung():
    a = hook.bereinige({"command": "sshpass -p geheim1 ssh x; curl -H 'Authorization: Bearer abc123' https://u:pw2@h/ ; PASSWORD=xyz; curl -u a:b9 h", "n": 3, "l": ["token=t0k"]}, 300)
    for geheim in ("geheim1", "abc123", "pw2", "xyz", "b9", "t0k"):
        assert geheim not in json.dumps(a), geheim
    assert a["n"] == 3 and "ssh x" in a["command"]
    assert len(hook.bereinige({"content": "x" * 5000}, 300)["content"]) == 300
    assert hook.lesend_angabe("mcp__skills__pwdepot_search_entries") is False and hook.lesend_angabe("mcp__skills__netbox_get_vms") is None


def test_ergebnis_nur_bei_mcp(h, monkeypatch):
    gesendet = {}
    echt = h.rufe

    def spion(s, c, name, args):
        gesendet[(name, args["tool"])] = args
        return echt(s, c, name, args)
    monkeypatch.setattr(h, "rufe", spion)
    for tool, uid in (("Read", "e1"), ("mcp__skills__netbox_get_vms", "e2"), ("mcp__skills__pwdepot_search_entries", "e3")):
        h.verarbeite(ev("PreToolUse", tool_name=tool, tool_input={"q": uid}, tool_use_id=uid))
        h.verarbeite(ev("PostToolUse", tool_name=tool, tool_input={"q": uid}, tool_use_id=uid, tool_response="INHALT"))
    assert "ergebnis" not in gesendet[("vi_nachher", "Read")]
    assert "ergebnis" not in gesendet[("vi_nachher", "pwdepot_search_entries")]
    assert gesendet[("vi_nachher", "netbox_get_vms")]["ergebnis"] == "INHALT"
    assert h.verarbeite(ev("PreToolUse", tool_name="mcp__skills__vi_status", tool_input={}, tool_use_id="v2")) is None
