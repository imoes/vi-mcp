"""0.13.0: Einrichten — Konfigurationen zusammenführen, ohne Fremdes zu berühren; Menü über ein echtes Pseudoterminal."""
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

from vi_mcp import einrichten as e
from vi_mcp import konfig, server

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


def test_codex_setzt_und_ersetzt_nur_eigene_tabelle():
    t = e.codex_setze(CODEX, "http://h/mcp", "tok")
    d = tomllib.loads(t)
    assert d["mcp_servers"]["vi-mcp"] == {"url": "http://h/mcp", "http_headers": {"Authorization": "Bearer tok"}}
    assert d["mcp_servers"]["skills"]["command"] == "python3" and "# Kommentar bleibt" in t
    t2 = e.codex_setze(t, "http://i/mcp", "neu")
    assert t2.count("[mcp_servers.vi-mcp]") == 1 and tomllib.loads(t2)["mcp_servers"]["vi-mcp"]["url"] == "http://i/mcp"
    assert tomllib.loads(e.codex_entferne(t2)) == tomllib.loads(CODEX)
    assert tomllib.loads(e.codex_setze("", "http://h/mcp", "t"))["mcp_servers"]["vi-mcp"]


def test_codex_kaputte_datei_bleibt():
    with pytest.raises(e.Verweigert, match="kein gültiges TOML"):
        e.codex_setze("a = [", "u", "t")


def test_hermes_setzt_ersetzt_entfernt():
    t = e.hermes_setze(HERMES, "http://h/mcp")
    d = yaml.safe_load(t)
    assert d["mcp_servers"]["vi-mcp"] == {"url": "http://h/mcp", "headers": {"Authorization": "Bearer ${VI_MCP_TOKEN}"}}
    assert set(d["mcp_servers"]) == {"andere", "zweite", "vi-mcp"} and d["tools"] == {"a": 1} and "# Notiz" in t
    t2 = e.hermes_setze(t, "http://i/mcp")
    assert t2.count("vi-mcp:") == 1 and yaml.safe_load(t2)["mcp_servers"]["vi-mcp"]["url"] == "http://i/mcp"
    assert yaml.safe_load(e.hermes_entferne(t2)) == yaml.safe_load(HERMES)


@pytest.mark.parametrize("text", ["", "a: 1\n", "a: 1\nmcp_servers: {}\nb: 2\n", "mcp_servers:\n", "a: 1\nmcp_servers: null\n", "mcp_servers:\n    x:\n        url: u\nb: 1\n"])
def test_hermes_randfaelle(text):
    d = yaml.safe_load(e.hermes_setze(text, "http://h/mcp"))
    alt = yaml.safe_load(text) or {}
    assert d["mcp_servers"]["vi-mcp"]["url"] == "http://h/mcp"
    assert {k: v for k, v in d.items() if k != "mcp_servers"} == {k: v for k, v in alt.items() if k != "mcp_servers"}
    if alt.get("mcp_servers"):
        assert d["mcp_servers"]["x"] == {"url": "u"}


def test_hermes_inline_wird_verweigert():
    with pytest.raises(e.Verweigert, match="Inline"):
        e.hermes_setze("mcp_servers: {a: {url: b}}\n", "u")


def test_env():
    t = e.env_setze("A=1\nVI_MCP_TOKEN=alt\n", "neu")
    assert t == "A=1\nVI_MCP_TOKEN=neu\n" and e.env_setze(t, None) == "A=1\n" and e.env_setze("", None) == ""


@pytest.fixture()
def ziel(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("SUDO_USER", raising=False)
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:/usr/bin:/bin")
    monkeypatch.setenv("VI_MCP_CONFIG", str(tmp_path / "gibtsnicht.json"))
    (tmp_path / "bin").mkdir()
    return e.ziel()


def _programm(tmp_path, name):
    p = tmp_path / "bin" / name
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)


def test_claude_und_hook_lassen_fremdes_stehen(ziel):
    (ziel.home / ".claude").mkdir()
    (ziel.home / ".claude.json").write_text(json.dumps({"numStartups": 7, "mcpServers": {"x": {"command": "y"}}}))
    (ziel.home / ".claude/settings.json").write_text(json.dumps({"model": "m", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "fremd"}]}]}}))
    e._claude_ein(ziel, "http://h/mcp", "tok")
    d = json.loads((ziel.home / ".claude.json").read_text())
    assert d["numStartups"] == 7 and d["mcpServers"]["x"] == {"command": "y"} and d["mcpServers"]["vi-mcp"]["headers"]["Authorization"] == "Bearer tok"
    assert oct((ziel.home / ".claude.json").stat().st_mode)[-3:] == "600" and list(ziel.home.glob(".claude.json.bak-vi-mcp-*"))
    assert e._hook_ein(ziel, "http://h/mcp", "tok", None).endswith("ohne Korrektur-Erkennung (kein Signal-Token)")
    e._hook_ein(ziel, "http://i/mcp", "tok", "sig")
    s = json.loads((ziel.home / ".claude/settings.json").read_text())
    assert len(s["hooks"]["PreToolUse"]) == 2 and s["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "fremd" and "http://i/mcp" in s["hooks"]["PreToolUse"][1]["hooks"][0]["command"]
    assert len(s["hooks"]["UserPromptSubmit"]) == 1 and "tok" not in s["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"].replace("token", "")
    assert (ziel.home / ".config/vi-mcp/token-nutzer").read_text() == "sig\n"
    e._hook_aus(ziel)
    s = json.loads((ziel.home / ".claude/settings.json").read_text())
    assert list(s["hooks"]) == ["PreToolUse"] and len(s["hooks"]["PreToolUse"]) == 1 and s["model"] == "m"
    assert not (ziel.home / ".config/vi-mcp/token-nutzer").exists()


def test_kaputtes_json_wird_nicht_ueberschrieben(ziel):
    p = ziel.home / ".claude.json"
    p.write_text("{kaputt")
    with pytest.raises(e.Verweigert):
        e._claude_ein(ziel, "u", "t")
    assert p.read_text() == "{kaputt"


def test_symlink_bleibt_symlink(ziel, tmp_path):
    echt = tmp_path / "echt.json"
    echt.write_text("{}")
    (ziel.home / ".claude.json").symlink_to(echt)
    e._claude_ein(ziel, "u", "t")
    assert (ziel.home / ".claude.json").is_symlink() and "vi-mcp" in echt.read_text()


def test_stand_benennt_jeden_fall(ziel, tmp_path):
    _programm(tmp_path, "claude")
    (ziel.home / ".codex").mkdir()
    s = {x.key: x for x in e.stand(ziel)}
    assert s["claude"].vorhanden == "installiert" and s["codex"].vorhanden == "nur_konfiguration" and s["hermes"].vorhanden == "fehlt" and "nicht gefunden" in s["hermes"].text
    assert s["hook"].vorhanden == "installiert"


def _menue(staende, token="t", server=("token_ok", "ok"), auto=False):
    return e.Menue("n", "http://h/mcp", token, auto, server, staende, zeilen=e.zeilen_fuer(staende, "einrichten"))


STAENDE = [e.Stand("claude", "Claude Code", "installiert", False, "noch nicht eingerichtet"), e.Stand("codex", "Codex CLI", "fehlt", False, "nicht gefunden: codex"),
           e.Stand("hermes", "Hermes Agent", "installiert", True, "eingerichtet: u"), e.Stand("hook", "Claude-Code-Hook", "installiert", False, "meldet")]


def test_menue_vorbelegung_und_gesperrtes():
    m = _menue(STAENDE)
    assert [z.an for z in m.zeilen] == [True, False, False, True]
    e.taste(m, "runter")
    e.taste(m, " ")
    assert not m.zeilen[1].an and "nicht gefunden" in m.meldung  # nicht wählbar, mit Grund
    assert "[-]" in e.zeichne(m, farbe=False)


def test_menue_enter_nennt_den_grund():
    m = _menue(STAENDE, token=None, server=("nicht_erreichbar", "refused"))
    assert e.taste(m, "enter") is None and "refused" in m.meldung
    m = _menue(STAENDE, token=None, server=("nicht_erreichbar", "x"), auto=True)  # frisch installiert: Dienst startet erst mit Tokens
    assert e.taste(m, "enter") == "los" and "läuft noch nicht" in e.zeichne(m, farbe=False)
    m = _menue(STAENDE, token="falsch", server=("token_abgelehnt", "HTTP 401"))
    e.taste(m, "enter")
    assert "401" in m.meldung
    for z in (m := _menue(STAENDE)).zeilen:
        z.an = False
    assert e.hindernis(m) == "nichts ausgewählt"


def test_menue_entfernen_nur_was_da_ist():
    m = _menue(STAENDE)
    e.taste(m, "e")
    assert m.modus == "entfernen" and [z.waehlbar for z in m.zeilen] == [False, False, True, False] and not any(z.an for z in m.zeilen)


def test_schmale_zeichnung_laeuft_nicht_ueber():
    assert all(len(z) <= 39 for z in e.zeichne(_menue(STAENDE), breite=40, farbe=False).split("\r\n"))


@pytest.fixture()
def laufend(tmp_path, monkeypatch):
    cfg = tmp_path / "srv.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    tok = konfig.instanz_anlegen("a")
    roh = json.loads(cfg.read_text())
    roh.update({"port": 0, "db": str(tmp_path / "vi.db")})
    cfg.write_text(json.dumps(roh))
    (s,) = server.baue(konfig.lade())
    threading.Thread(target=s.serve_forever, daemon=True).start()
    monkeypatch.delenv("VI_MCP_CONFIG")
    yield f"http://127.0.0.1:{s.server_address[1]}/mcp", tok
    s.shutdown()
    s.server_close()
    server.beende([s])


def test_pruefe(laufend):
    url, tok = laufend
    assert e.pruefe(url, tok)[0] == "token_ok"
    assert e.pruefe(url, "falsch") == ("token_abgelehnt", "Server lehnt das Token ab (HTTP 401)")
    assert e.pruefe(url, None)[0] == "erreichbar"
    assert e.pruefe("http://127.0.0.1:1/mcp", "t")[0] == "nicht_erreichbar"
    assert e.pruefe("kaputt", "t")[0] == "nicht_erreichbar"


def test_falsches_token_wird_nicht_eingetragen(laufend, ziel):
    url, tok = laufend
    r = e.einrichten(["claude"], ziel, url, "falsch")
    assert not r[0].ok and "401" in r[0].text and not (ziel.home / ".claude.json").exists()
    assert e.einrichten(["claude", "codex"], ziel, url, tok)[1].ok and tomllib.loads((ziel.home / ".codex/config.toml").read_text())


def test_automatische_tokens_auf_dem_server(laufend, ziel, tmp_path, monkeypatch):
    url, _ = laufend
    cfg = tmp_path / "auto.json"
    cfg.write_text("{}")
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    monkeypatch.setattr(e, "_neustart", lambda: "kein Dienst")
    r = e.einrichten(["claude"], ziel, url, None)
    assert not r[0].ok and "nicht neu gestartet" in r[0].text and not (ziel.home / ".claude.json").exists()
    monkeypatch.setattr(e, "_neustart", lambda: None)
    monkeypatch.setattr(e, "pruefe", lambda u, t, timeout=4: ("erreichbar", "x") if t is None else ("token_ok", "x"))
    r = e.einrichten(["claude", "hook"], ziel, url, None)
    assert all(x.ok for x in r), r
    inst = json.loads(cfg.read_text())["instanzen"]
    assert set(inst) == {f"{ziel.name}-claude", f"{ziel.name}-nutzer"} and inst[f"{ziel.name}-nutzer"]["mensch"] and not inst[f"{ziel.name}-claude"]["mensch"]
    assert (ziel.home / ".config/vi-mcp/token-claude").read_text().strip() == e._claude_token(ziel)  # Hook und MCP dieselbe Instanz


def _pty_lauf(args, env, tasten, zeit=20):
    herr, knecht = pty.openpty()
    p = subprocess.Popen([sys.executable, "-m", "vi_mcp", "einrichten", *args], stdin=knecht, stdout=knecht, stderr=knecht, env=env, cwd=REPO, close_fds=True, start_new_session=True)
    os.close(knecht)
    aus, ende, i = b"", time.time() + zeit, 0
    naechste = time.time() + 1.2
    while time.time() < ende:
        r, _, _ = select.select([herr], [], [], 0.1)
        if r:
            try:
                d = os.read(herr, 65536)
            except OSError:
                break
            if not d:
                break
            aus += d
        if i < len(tasten) and time.time() > naechste and b"Enter:" in aus:
            os.write(herr, tasten[i])
            i += 1
            naechste = time.time() + 0.25
        if p.poll() is not None and not r:
            break
    p.wait(timeout=5)
    os.close(herr)
    return p.returncode, aus.decode("utf-8", "replace")


def test_menue_im_pseudoterminal(laufend, ziel, tmp_path):
    url, tok = laufend
    _programm(tmp_path, "claude")
    (tmp_path / "t").write_text(tok)
    env = {**os.environ, "PYTHONPATH": str(REPO), "TERM": "xterm"}
    code, aus = _pty_lauf(["--url", url, "--token-datei", str(tmp_path / "t")], env, [b"\x1b[B", b"\x1b[B", b"\x1b[B", b" ", b"\r"])
    assert code == 0, aus
    assert "\x1b[?1049h" in aus and "\x1b[?1049l" in aus and "\x1b[?25h" in aus and "✓ Claude Code" in aus and "Hook" not in aus.split("\x1b[?1049l")[-1]
    assert json.loads((ziel.home / ".claude.json").read_text())["mcpServers"]["vi-mcp"]["url"] == url


def test_menue_endet_im_leerlauf(ziel):
    code, aus = _pty_lauf(["--url", "http://127.0.0.1:1/mcp", "--leerlauf", "1"], {**os.environ, "PYTHONPATH": str(REPO), "TERM": "xterm"}, [], zeit=15)
    assert code == 0 and "sudo vi-mcp einrichten" in aus and "\x1b[?25h" in aus


def test_ohne_terminal_kommt_der_hinweis(ziel):
    r = subprocess.run([sys.executable, "-m", "vi_mcp", "einrichten"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env={**os.environ, "PYTHONPATH": str(REPO)}, cwd=REPO)
    assert r.returncode == 2 and "Kein Terminal" in r.stderr
