"""Einrichten — trägt vi-mcp in Claude Code, Codex CLI und Hermes Agent ein. ANSI-Menü oder Schalter, nur Standardbibliothek + PyYAML.

  vi-mcp einrichten                       Menü
  vi-mcp einrichten --status              Zustand je Programm
  vi-mcp einrichten --claude --hermes --hook --url URL --token-datei DATEI   ohne Menü
  vi-mcp einrichten --claude --entfernen

Wird es mit sudo gestartet, gilt es für den aufrufenden Nutzer; Dateien werden mit dessen Rechten geschrieben.
Läuft der Server auf demselben Rechner und ist seine Konfiguration beschreibbar, bekommt jedes Programm eine eigene Instanz
mit eigenem Token (`<nutzer>-claude`, …), und der Dienst wird neu gestartet. Sonst wird ein vorhandenes Token verwendet.
Vor dem Schreiben wird geprüft, ob der Server das Token annimmt. Eine Änderung wird nur geschrieben, wenn sich der Rest der
jeweiligen Datei beim Nachlesen als unverändert erweist. Jede geänderte Datei bekommt eine Sicherung `<datei>.bak-vi-mcp-<zeit>`.
Tokens stehen nie auf einer Kommandozeile.
"""
from __future__ import annotations

import argparse
import copy
import getpass
import glob
import json
import os
import pwd
import re
import select
import shlex
import shutil
import subprocess
import sys
import termios
import time
import tomllib
import tty
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__, konfig

NAME = "vi-mcp"
ENV_TOKEN = "VI_MCP_TOKEN"
LOKAL = ("127.0.0.1", "localhost", "::1")
HOOK_EREIGNISSE = ("PreToolUse", "PostToolUse", "PostToolUseFailure")
HINWEIS = "Einrichten für Claude Code, Codex und Hermes:  sudo vi-mcp einrichten"


class Verweigert(Exception):
    """Etwas wird bewusst nicht getan; der Text nennt den Grund."""


@dataclass(frozen=True)
class Ziel:
    name: str
    home: Path
    uid: int
    gid: int


def _aufrufer() -> pwd.struct_passwd | None:
    """Wer hinter root steht: SUDO_USER, sonst die Anmeldung (rpm reicht die Umgebung nicht immer an Scriptlets weiter)."""
    try:
        if (n := os.environ.get("SUDO_USER")) and n != "root":
            return pwd.getpwnam(n)
        uid = int(Path("/proc/self/loginuid").read_text())
        return pwd.getpwuid(uid) if 0 < uid < 4294967295 else None
    except (OSError, KeyError, ValueError):
        return None


def ziel() -> Ziel:
    if os.geteuid() == 0 and (p := _aufrufer()):
        return Ziel(p.pw_name, Path(p.pw_dir), p.pw_uid, p.pw_gid)
    p = pwd.getpwuid(os.geteuid())
    return Ziel(p.pw_name, Path.home(), p.pw_uid, p.pw_gid)


@contextmanager
def _als(z: Ziel):
    """Mit den Rechten des Zielnutzers arbeiten, damit Eigentümer und Rechte seiner Dateien stimmen."""
    wechsel = os.geteuid() == 0 and z.uid != 0
    if wechsel:
        os.setegid(z.gid)
        os.seteuid(z.uid)
    try:
        yield
    finally:
        if wechsel:
            os.seteuid(0)
            os.setegid(0)


def _schreibe(p: Path, inhalt: str) -> str:
    """Atomar, 0600 (die Dateien tragen Tokens). Liefert eine Beschreibung mit dem Pfad der Sicherung."""
    p = Path(os.path.realpath(p))
    alt = p.read_text() if p.exists() else None
    if alt == inhalt:
        return f"{p} unverändert"
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    text = f"{p} neu angelegt"
    if alt is not None:
        kopie = Path(f"{p}.bak-vi-mcp-{time.strftime('%Y%m%d-%H%M%S')}")
        fd = os.open(kopie, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(alt)
        text = f"{p} geändert (Sicherung {kopie.name})"
    tmp = Path(f"{p}.vi-mcp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(inhalt)
    os.replace(tmp, p)
    return text


def _text(p: Path) -> str:
    return p.read_text() if p.exists() else ""


def _json(p: Path) -> dict:
    try:
        d = json.loads(_text(p) or "{}")
    except json.JSONDecodeError as e:
        raise Verweigert(f"{p} ist kein gültiges JSON ({e.msg}, Zeile {e.lineno}); nichts geändert") from e
    if not isinstance(d, dict):
        raise Verweigert(f"{p} enthält kein JSON-Objekt; nichts geändert")
    return d


def _ohne_eintrag(d: dict) -> dict:
    d = copy.deepcopy(d)
    if isinstance(d.get("mcp_servers"), dict):
        d["mcp_servers"].pop(NAME, None)
    if not d.get("mcp_servers"):
        d.pop("mcp_servers", None)
    return d


def _nur_eintrag_anders(alt: dict, neu: dict, soll: dict | None, p: Path) -> None:
    if _ohne_eintrag(alt) != _ohne_eintrag(neu) or (neu.get("mcp_servers") or {}).get(NAME) != soll:
        raise Verweigert(f"{p}: die Änderung hätte mehr als den Eintrag {NAME} berührt; nichts geändert")


# ---- Claude Code: ~/.claude.json (mcpServers) und ~/.claude/settings.json (Hook) ----

def _claude_datei(z: Ziel) -> Path:
    return z.home / ".claude.json"


def _claude_eintrag(z: Ziel) -> dict | None:
    return _json(_claude_datei(z)).get("mcpServers", {}).get(NAME)


def _claude_ein(z: Ziel, url: str, token: str) -> str:
    p = _claude_datei(z)
    d = _json(p)
    d.setdefault("mcpServers", {})[NAME] = {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {token}"}}
    return _schreibe(p, json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def _claude_aus(z: Ziel) -> str:
    p = _claude_datei(z)
    d = _json(p)
    d.get("mcpServers", {}).pop(NAME, None)
    return _schreibe(p, json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def _claude_token(z: Ziel) -> str | None:
    e = _claude_eintrag(z) or {}
    wert = (e.get("headers") or {}).get("Authorization", "")
    return wert[7:] if wert.startswith("Bearer ") else None


def _hook_skript() -> Path:
    paket = Path("/usr/share/vi-mcp/hook/vi_hook.py")
    return paket if paket.exists() else Path(__file__).resolve().parents[1] / "hook" / "vi_hook.py"


def _einstellungen(z: Ziel) -> Path:
    return z.home / ".claude" / "settings.json"


def _ist_unser(block: dict) -> bool:
    return any("vi_hook.py" in h.get("command", "") for h in block.get("hooks", []))


def _hook_aktiv(z: Ziel) -> bool:
    return any(_ist_unser(b) for bloecke in _json(_einstellungen(z)).get("hooks", {}).values() for b in bloecke)


def _hook_ohne(d: dict) -> None:
    hooks = d.get("hooks", {})
    for ereignis in list(hooks):
        hooks[ereignis] = [b for b in hooks[ereignis] if not _ist_unser(b)]
        if not hooks[ereignis]:
            del hooks[ereignis]
    if "hooks" in d and not d["hooks"]:
        del d["hooks"]


def _hook_ein(z: Ziel, url: str, token: str, signal: str | None) -> str:
    verz = z.home / ".config" / "vi-mcp"
    _schreibe(verz / "token-claude", token + "\n")
    umgebung = f"VI_MCP_URL={shlex.quote(url)} VI_MCP_TOKEN_FILE=$HOME/.config/vi-mcp/token-claude"
    if signal:
        _schreibe(verz / "token-nutzer", signal + "\n")
        umgebung += " VI_MCP_SIGNAL_TOKEN_FILE=$HOME/.config/vi-mcp/token-nutzer"
    befehl = f"{umgebung} python3 -I {shlex.quote(str(_hook_skript()))}"
    p = _einstellungen(z)
    d = _json(p)
    _hook_ohne(d)
    h = d.setdefault("hooks", {})
    for e in HOOK_EREIGNISSE:
        h.setdefault(e, []).append({"matcher": "*", "hooks": [{"type": "command", "command": befehl, "timeout": 5}]})
    for e in ("SessionEnd", *(("UserPromptSubmit",) if signal else ())):
        h.setdefault(e, []).append({"hooks": [{"type": "command", "command": befehl, "timeout": 5}]})
    text = _schreibe(p, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return text + ("" if signal else "; ohne Korrektur-Erkennung (kein Signal-Token)")


def _hook_aus(z: Ziel) -> str:
    p = _einstellungen(z)
    d = _json(p)
    _hook_ohne(d)
    for name in ("token-claude", "token-nutzer"):
        (z.home / ".config" / "vi-mcp" / name).unlink(missing_ok=True)
    return _schreibe(p, json.dumps(d, indent=2, ensure_ascii=False) + "\n")


# ---- Codex CLI: ~/.codex/config.toml, Tabelle [mcp_servers.vi-mcp] ----

_TOML_KOPF = re.compile(r"^\s*\[+\s*([^\]]+?)\s*\]+")


def _codex_datei(z: Ziel) -> Path:
    return z.home / ".codex" / "config.toml"


def _toml(text: str, p: Path) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Verweigert(f"{p} ist kein gültiges TOML ({e}); nichts geändert") from e


def _toml_ohne(text: str) -> str:
    aus, weg = [], False
    for zeile in text.splitlines(keepends=True):
        if m := _TOML_KOPF.match(zeile):
            schluessel = re.sub(r"[\"'\s]", "", m[1])
            weg = schluessel == f"mcp_servers.{NAME}" or schluessel.startswith(f"mcp_servers.{NAME}.")
        if not weg:
            aus.append(zeile)
    return "".join(aus)


def codex_setze(text: str, url: str, token: str, p: Path = Path("config.toml")) -> str:
    """Rein. json.dumps erzeugt hier gültige TOML-Zeichenketten (nur ASCII mit \\uXXXX)."""
    alt = _toml(text, p)
    rumpf = _toml_ohne(text).rstrip("\n")
    block = f'[mcp_servers.{NAME}]\nurl = {json.dumps(url)}\nhttp_headers = {{ Authorization = {json.dumps("Bearer " + token)} }}\n'
    neu = (rumpf + "\n\n" if rumpf else "") + block
    _nur_eintrag_anders(alt, _toml(neu, p), {"url": url, "http_headers": {"Authorization": f"Bearer {token}"}}, p)
    return neu


def codex_entferne(text: str, p: Path = Path("config.toml")) -> str:
    alt = _toml(text, p)
    neu = _toml_ohne(text).rstrip("\n") + "\n"
    _nur_eintrag_anders(alt, _toml(neu, p), None, p)
    return neu


def _codex_ein(z: Ziel, url: str, token: str) -> str:
    p = _codex_datei(z)
    return _schreibe(p, codex_setze(_text(p), url, token, p))


def _codex_aus(z: Ziel) -> str:
    p = _codex_datei(z)
    return _schreibe(p, codex_entferne(_text(p), p))


def _codex_eintrag(z: Ziel) -> dict | None:
    p = _codex_datei(z)
    return _toml(_text(p), p).get("mcp_servers", {}).get(NAME)


# ---- Hermes Agent: ~/.hermes/config.yaml (mcp_servers) und ~/.hermes/.env (Token) ----

def _hermes_verz(z: Ziel) -> Path:
    e = os.environ.get("HERMES_HOME", "").strip()
    return Path(e) if e else z.home / ".hermes"


def _yaml(text: str, p: Path) -> dict:
    try:
        import yaml
    except ImportError as e:
        raise Verweigert("PyYAML fehlt (python3-yaml), die Hermes-Konfiguration lässt sich nicht prüfen") from e
    try:
        d = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise Verweigert(f"{p} ist kein gültiges YAML; nichts geändert ({str(e)[:120]})") from e
    if not isinstance(d, dict):
        raise Verweigert(f"{p} enthält keine Zuordnung; nichts geändert")
    return d


def _einzug(zeile: str) -> int:
    return len(zeile) - len(zeile.lstrip(" "))


def _inhalt(zeile: str) -> bool:
    return bool(zeile.strip()) and not zeile.lstrip().startswith("#")


def _yaml_abschnitt(zeilen: list[str]) -> tuple[int, int] | None:
    """Kopfzeile und Ende des Abschnitts mcp_servers; None, wenn es ihn nicht gibt."""
    for i, z in enumerate(zeilen):
        if re.match(r"^mcp_servers:\s*(#.*)?$", z):
            ende = next((j for j in range(i + 1, len(zeilen)) if _inhalt(zeilen[j]) and _einzug(zeilen[j]) == 0), len(zeilen))
            while ende > i + 1 and not _inhalt(zeilen[ende - 1]):
                ende -= 1
            return i, ende
    return None


def _yaml_ohne(zeilen: list[str]) -> list[str]:
    ab = _yaml_abschnitt(zeilen)
    if not ab:
        return zeilen
    kopf, ende = ab
    start = next((i for i in range(kopf + 1, ende) if re.match(rf"^\s+{re.escape(NAME)}:\s*(#.*)?$", zeilen[i])), None)
    if start is None:
        return zeilen
    tiefe = _einzug(zeilen[start])
    stop = next((j for j in range(start + 1, ende) if _inhalt(zeilen[j]) and _einzug(zeilen[j]) <= tiefe), ende)
    return zeilen[:start] + zeilen[stop:]


def hermes_setze(text: str, url: str, p: Path = Path("config.yaml")) -> str:
    """Rein. Das Token steht nicht hier, sondern in ~/.hermes/.env; Hermes setzt ${VAR} beim Verbinden ein."""
    alt = _yaml(text, p)
    zeilen = text.splitlines()
    for i, z in enumerate(zeilen):
        if m := re.match(r"^mcp_servers:\s*(\S.*)$", z):
            if m[1].split("#")[0].strip() in ("{}", "null", "~", ""):
                zeilen[i] = "mcp_servers:"
            elif not m[1].startswith("#"):
                raise Verweigert(f"{p}: mcp_servers ist in Inline-Schreibweise; bitte von Hand eintragen, nichts geändert")
    zeilen = _yaml_ohne(zeilen)
    ab = _yaml_abschnitt(zeilen)
    if not ab:
        while zeilen and not zeilen[-1].strip():
            zeilen.pop()
        zeilen += ["", "mcp_servers:"] if zeilen else ["mcp_servers:"]
        ab = (len(zeilen) - 1, len(zeilen))
    kopf, ende = ab
    tiefe = next((_einzug(zeilen[i]) for i in range(kopf + 1, ende) if _inhalt(zeilen[i])), 2)
    rand = " " * tiefe
    block = [f"{rand}{NAME}:", f"{rand}  url: {json.dumps(url)}", f"{rand}  headers:", f'{rand}    Authorization: "Bearer ${{{ENV_TOKEN}}}"']
    neu = "\n".join(zeilen[:ende] + block + zeilen[ende:]) + "\n"
    _nur_eintrag_anders(alt, _yaml(neu, p), {"url": url, "headers": {"Authorization": f"Bearer ${{{ENV_TOKEN}}}"}}, p)
    return neu


def hermes_entferne(text: str, p: Path = Path("config.yaml")) -> str:
    alt = _yaml(text, p)
    neu = "\n".join(_yaml_ohne(text.splitlines())) + "\n"
    _nur_eintrag_anders(alt, _yaml(neu, p), None, p)
    return neu


def env_setze(text: str, token: str | None) -> str:
    """Rein. token None entfernt die Zeile."""
    zeilen = [z for z in text.splitlines() if not z.startswith(f"{ENV_TOKEN}=")]
    if token:
        zeilen.append(f"{ENV_TOKEN}={token}")
    return "\n".join(zeilen) + "\n" if zeilen else ""


def _hermes_ein(z: Ziel, url: str, token: str) -> str:
    v = _hermes_verz(z)
    p = v / "config.yaml"
    neu = hermes_setze(_text(p), url, p)
    _schreibe(v / ".env", env_setze(_text(v / ".env"), token))
    return _schreibe(p, neu)


def _hermes_aus(z: Ziel) -> str:
    v = _hermes_verz(z)
    p = v / "config.yaml"
    neu = hermes_entferne(_text(p), p)
    _schreibe(v / ".env", env_setze(_text(v / ".env"), None))
    return _schreibe(p, neu)


def _hermes_eintrag(z: Ziel) -> dict | None:
    p = _hermes_verz(z) / "config.yaml"
    return (_yaml(_text(p), p).get("mcp_servers") or {}).get(NAME)


# ---- Übersicht ----

@dataclass(frozen=True)
class Programm:
    key: str
    titel: str
    befehl: str
    verzeichnis: Callable[[Ziel], Path]
    eintrag: Callable[[Ziel], dict | None]
    ein: Callable[[Ziel, str, str], str]
    aus: Callable[[Ziel], str]


PROGRAMME = (
    Programm("claude", "Claude Code", "claude", lambda z: z.home / ".claude", _claude_eintrag, _claude_ein, _claude_aus),
    Programm("codex", "Codex CLI", "codex", lambda z: z.home / ".codex", _codex_eintrag, _codex_ein, _codex_aus),
    Programm("hermes", "Hermes Agent", "hermes", _hermes_verz, _hermes_eintrag, _hermes_ein, _hermes_aus),
)


def _finde(befehl: str, z: Ziel) -> str | None:
    pfade = [*os.environ.get("PATH", "").split(":"), str(z.home / ".local/bin"), str(z.home / ".npm-global/bin"), str(z.home / "bin"), "/usr/local/bin",
             *glob.glob(str(z.home / ".nvm/versions/node/*/bin"))]
    return shutil.which(befehl, path=":".join(pfade))


@dataclass
class Stand:
    key: str
    titel: str
    vorhanden: str  # installiert | nur_konfiguration | fehlt
    eingerichtet: bool
    text: str


def stand(z: Ziel) -> list[Stand]:
    aus = []
    with _als(z):
        for p in PROGRAMME:
            ort = _finde(p.befehl, z)
            v = "installiert" if ort else "nur_konfiguration" if p.verzeichnis(z).exists() else "fehlt"
            try:
                e = p.eintrag(z)
                eingerichtet, teil = bool(e), (f"eingerichtet: {e.get('url')}" if e else "noch nicht eingerichtet")
            except Verweigert as ex:
                eingerichtet, teil = False, f"Konfiguration unlesbar: {ex}"
            text = {"installiert": teil, "nur_konfiguration": f"Programm nicht im PATH, Konfiguration vorhanden; {teil}",
                    "fehlt": f"nicht gefunden: {p.befehl} nicht im PATH, {p.verzeichnis(z)} fehlt"}[v]
            aus.append(Stand(p.key, p.titel, v, eingerichtet, text))
        c = aus[0]
        try:
            h = _hook_aktiv(z)
        except Verweigert:
            h = False
    if c.vorhanden == "fehlt":
        hv, ht = "fehlt", "braucht Claude Code"
    else:
        hv, ht = "installiert", "eingerichtet" if h else "meldet jede Handlung an den Server (Argumente maskiert)"
    return aus + [Stand("hook", "Claude-Code-Hook", hv, h, ht)]


# ---- Server ----

def _lokal(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "") in LOKAL


def _oeffne(req: urllib.request.Request, timeout: float):
    """Erst direkt, dann über den Proxy der Umgebung. Eine HTTP-Antwort (auch ein Fehler) beendet die Suche."""
    letzter: Exception | None = None
    for op in (urllib.request.build_opener(urllib.request.ProxyHandler({})), None if _lokal(req.full_url) else urllib.request.build_opener()):
        if op is None:
            break
        try:
            return op.open(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            letzter = e
    raise letzter  # type: ignore[misc]


def pruefe(url: str, token: str | None, timeout: float = 4) -> tuple[str, str]:
    """(art, text); art ∈ token_ok, token_abgelehnt, erreichbar, nicht_erreichbar, keine_mcp_antwort."""
    if not re.match(r"^https?://[^/\s]+/\S*$", url):
        return "nicht_erreichbar", "URL hat nicht die Form http(s)://host/…/mcp"
    if not token:
        try:
            with _oeffne(urllib.request.Request(url.rsplit("/mcp", 1)[0] + "/gesund"), timeout) as a:
                return "erreichbar", a.read(200).decode("utf-8", "replace").strip()
        except urllib.error.HTTPError as e:
            return "keine_mcp_antwort", f"HTTP {e.code} auf /gesund"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            return "nicht_erreichbar", str(getattr(e, "reason", e))[:160]
    kopf = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": f"Bearer {token}"}
    koerper = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "vi-mcp-einrichten", "version": __version__}}}
    try:
        with _oeffne(urllib.request.Request(url, data=json.dumps(koerper).encode(), headers=kopf), timeout) as a:
            sid = a.headers.get("Mcp-Session-Id")
            info = json.loads(a.read())["result"]["serverInfo"]
    except urllib.error.HTTPError as e:
        return ("token_abgelehnt", f"Server lehnt das Token ab (HTTP {e.code})") if e.code in (401, 403) else ("keine_mcp_antwort", f"HTTP {e.code}")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return "nicht_erreichbar", str(getattr(e, "reason", e))[:160]
    except (json.JSONDecodeError, KeyError, TypeError):
        return "keine_mcp_antwort", "Antwort ist kein MCP"
    if sid:
        try:
            _oeffne(urllib.request.Request(url, headers={**kopf, "Mcp-Session-Id": sid}, method="DELETE"), timeout).close()
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
    return "token_ok", f"{info.get('name')} {info.get('version')}, Token gültig"


def kann_tokens_anlegen(url: str) -> bool:
    return _lokal(url) and konfig.pfad().exists() and os.access(konfig.pfad(), os.W_OK)


def _neustart() -> str | None:
    """Der Dienst liest Instanzen nur beim Start. None = erfolgreich, sonst der Grund."""
    befehl = ["systemctl", "restart", "vi-mcp"] if os.geteuid() == 0 else ["systemctl", "--user", "restart", "vi-mcp"]
    try:
        r = subprocess.run(befehl, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"{' '.join(befehl)}: {e}"
    return None if r.returncode == 0 else f"{' '.join(befehl)}: {r.stderr.strip()[:200]}"


def _warte(url: str, sekunden: float = 15) -> bool:
    ende = time.time() + sekunden
    while time.time() < ende:
        if pruefe(url, None, 2)[0] == "erreichbar":
            return True
        time.sleep(0.3)
    return False


@dataclass
class Ergebnis:
    key: str
    titel: str
    ok: bool
    text: str


def standard_url(z: Ziel) -> str:
    if u := os.environ.get("VI_MCP_URL"):
        return u
    with _als(z):
        for p in PROGRAMME:
            try:
                if (e := p.eintrag(z)) and e.get("url"):
                    return e["url"]
            except Verweigert:
                pass
    try:
        port = json.loads(konfig.pfad().read_text()).get("port", 8765)
    except (OSError, json.JSONDecodeError):
        port = 8765
    return f"http://127.0.0.1:{port}/mcp"


def _titel(key: str) -> str:
    return "Claude-Code-Hook" if key == "hook" else next(p.titel for p in PROGRAMME if p.key == key)


def entfernen(wahl: list[str], z: Ziel) -> list[Ergebnis]:
    aus = []
    for key in wahl:
        try:
            with _als(z):
                text = _hook_aus(z) if key == "hook" else next(p for p in PROGRAMME if p.key == key).aus(z)
            aus.append(Ergebnis(key, _titel(key), True, text))
        except (Verweigert, OSError) as e:
            aus.append(Ergebnis(key, _titel(key), False, str(e)))
    return aus


def einrichten(wahl: list[str], z: Ziel, url: str, token: str | None, signal: str | None = None, ungeprueft: bool = False) -> list[Ergebnis]:
    """Tokens beschaffen → Server fragen → schreiben. Was nicht geprüft werden konnte, wird nicht geschrieben."""
    tokens: dict[str, str] = {}
    if token:
        tokens = {k: token for k in wahl}
    elif kann_tokens_anlegen(url):
        kurz = re.sub(r"[^A-Za-z0-9_.-]", "-", z.name)
        for k in wahl:
            if k == "hook":
                continue
            tokens[k] = konfig.instanz_anlegen(f"{kurz}-{k}")
        if "hook" in wahl:
            with _als(z):
                vorhanden = _claude_token(z)
            tokens["hook"] = tokens.get("claude") or vorhanden or konfig.instanz_anlegen(f"{kurz}-claude")
            signal = signal or konfig.instanz_anlegen(f"{kurz}-nutzer", mensch=True)
        if grund := _neustart():
            return [Ergebnis(k, _titel(k), False, f"Dienst nicht neu gestartet, nichts eingetragen: {grund}") for k in wahl]
        if not _warte(url):
            return [Ergebnis(k, _titel(k), False, "Server antwortet nach dem Neustart nicht, nichts eingetragen") for k in wahl]
    elif "hook" in wahl and len(wahl) == 1:
        with _als(z):
            if vorhanden := _claude_token(z):
                tokens["hook"] = vorhanden
    aus = []
    for k in wahl:
        t = tokens.get(k)
        if not t:
            aus.append(Ergebnis(k, _titel(k), False, "kein Token: mit --token-datei angeben oder auf dem Server mit sudo starten"))
            continue
        if not ungeprueft:
            art, text = pruefe(url, t)
            if art != "token_ok":
                aus.append(Ergebnis(k, _titel(k), False, f"nicht eingetragen: {text}"))
                continue
        try:
            with _als(z):
                text = _hook_ein(z, url, t, signal) if k == "hook" else next(p for p in PROGRAMME if p.key == k).ein(z, url, t)
            aus.append(Ergebnis(k, _titel(k), True, text))
        except (Verweigert, OSError) as e:
            aus.append(Ergebnis(k, _titel(k), False, str(e)))
    return aus


# ---- Menü: Zustand und Darstellung sind rein, nur _lauf spricht mit dem Terminal ----

@dataclass
class Zeile:
    key: str
    titel: str
    info: str
    waehlbar: bool
    an: bool


@dataclass
class Menue:
    nutzer: str
    url: str
    token: str | None
    auto: bool
    server: tuple[str, str]
    staende: list[Stand] = field(default_factory=list)
    modus: str = "einrichten"
    zeilen: list[Zeile] = field(default_factory=list)
    pos: int = 0
    meldung: str = ""


def zeilen_fuer(staende: list[Stand], modus: str) -> list[Zeile]:
    aus = []
    for s in staende:
        if modus == "einrichten":
            aus.append(Zeile(s.key, s.titel, s.text, s.vorhanden != "fehlt", s.vorhanden != "fehlt" and not s.eingerichtet))
        else:
            aus.append(Zeile(s.key, s.titel, s.text if s.eingerichtet else "nichts zu entfernen: nicht eingerichtet", s.eingerichtet, False))
    return aus


def hindernis(m: Menue) -> str | None:
    if not any(z.an for z in m.zeilen):
        return "nichts ausgewählt"
    if m.modus == "entfernen":
        return None
    art, text = m.server
    if m.token:
        return None if art == "token_ok" else f"Server prüft nicht erfolgreich: {text}"
    if m.auto:
        return None
    if art == "nicht_erreichbar":
        return f"Server nicht erreichbar: {text}"
    return "kein Token: mit t eingeben oder auf dem Server mit sudo starten"


def _server_zeile(m: Menue) -> str:
    art, text = m.server
    if m.auto and art != "erreichbar":
        return "läuft noch nicht; startet nach dem Anlegen der Tokens"
    return text


def zeichne(m: Menue, breite: int = 80, farbe: bool = True) -> str:
    def f(code: str, s: str) -> str:
        return f"\x1b[{code}m{s}\x1b[0m" if farbe else s

    def k(s: str) -> str:
        return s if len(s) <= breite - 1 else s[:breite - 2] + "…"
    gut = m.server[0] in ("token_ok", "erreichbar") or m.auto
    tok = "eingegeben" if m.token else "wird je Programm angelegt" if m.auto else "fehlt"
    z = [f("1;36", k(f" vi-mcp einrichten  {__version__}")), "",
         k(f" Nutzer   {m.nutzer}"), k(f" Server   {m.url}"), f("32" if gut else "31", k(f"          {_server_zeile(m)}")),
         k(f" Token    {tok}"), k(f" Aktion   {m.modus}"), f("2", k(" " + "─" * min(breite - 2, 70)))]
    for i, r in enumerate(m.zeilen):
        marke = "▸" if i == m.pos else " "
        kasten = "[x]" if r.an else "[ ]" if r.waehlbar else "[-]"
        text = k(f" {marke} {kasten} {r.titel:17} {r.info}")
        z.append(f("7" if i == m.pos else "0", text) if r.waehlbar else f("2;7" if i == m.pos else "2", text))
    z.append(f("2", k(" " + "─" * min(breite - 2, 70))))
    h = hindernis(m)
    z.append(f("2", k(f" Enter: gesperrt, {h}")) if h else f("1;32", k(f" Enter: {m.modus}")))
    z.append(k(" ↑↓ wählen · Leertaste an/aus · u URL · t Token · e Aktion · q Ende"))
    if m.meldung:
        z += ["", f("33", k(f" {m.meldung}"))]
    return "\r\n".join(z)


def taste(m: Menue, k: str) -> str | None:
    """Ändert den Zustand; liefert url, token, modus, los oder ende, wenn die Schleife handeln muss."""
    m.meldung = ""
    if k in ("hoch", "k"):
        m.pos = (m.pos - 1) % len(m.zeilen)
    elif k in ("runter", "j"):
        m.pos = (m.pos + 1) % len(m.zeilen)
    elif k == " ":
        z = m.zeilen[m.pos]
        if z.waehlbar:
            z.an = not z.an
        else:
            m.meldung = f"{z.titel}: {z.info}"
    elif k == "e":
        m.modus = "entfernen" if m.modus == "einrichten" else "einrichten"
        m.zeilen = zeilen_fuer(m.staende, m.modus)
    elif k == "u":
        return "url"
    elif k == "t":
        return "token"
    elif k == "enter":
        h = hindernis(m)
        if h:
            m.meldung = h
            return None
        return "los"
    elif k in ("q", "esc"):
        return "ende"
    return None


TASTEN = {b"\x1b[A": "hoch", b"\x1bOA": "hoch", b"\x1b[B": "runter", b"\x1bOB": "runter", b"\r": "enter", b"\n": "enter", b"\x1b": "esc"}


def _lauf(z: Ziel, url: str, token: str | None, signal: str | None, leerlauf: float | None) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Kein Terminal für das Menü. Ohne Menü: vi-mcp einrichten --claude --url URL --token-datei DATEI", file=sys.stderr)
        return 2
    farbe = "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
    staende = stand(z)
    m = Menue(z.name, url, token, not token and kann_tokens_anlegen(url), pruefe(url, token), staende, zeilen=zeilen_fuer(staende, "einrichten"))
    fd = sys.stdin.fileno()
    alt = termios.tcgetattr(fd)
    aus = sys.stdout

    def bild() -> None:
        aus.write("\x1b[H\x1b[2J" + zeichne(m, shutil.get_terminal_size((80, 24)).columns, farbe))
        aus.flush()

    def zeile(prompt: str, verdeckt: bool) -> str | None:
        termios.tcsetattr(fd, termios.TCSADRAIN, alt)
        aus.write("\x1b[?25h\r\n")
        aus.flush()
        try:
            return (getpass.getpass(prompt) if verdeckt else input(prompt)).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        finally:
            tty.setcbreak(fd)
            aus.write("\x1b[?25l")
            aus.flush()
    los = False
    try:
        tty.setcbreak(fd)
        aus.write("\x1b[?1049h\x1b[?25l")
        while True:
            bild()
            bereit, _, _ = select.select([fd], [], [], leerlauf)
            if not bereit:
                break
            roh = os.read(fd, 16)
            if not roh:
                break
            k = TASTEN.get(roh, roh.decode("utf-8", "ignore"))
            r = taste(m, k)
            if r == "ende":
                break
            if r == "los":
                los = True
                break
            if r == "url" and (w := zeile(f" Server-URL [{m.url}]: ", False)):
                m.url = w
            if r == "token" and (w := zeile(" Token (Eingabe verdeckt): ", True)):
                m.token = w
            if r in ("url", "token"):
                m.auto = not m.token and kann_tokens_anlegen(m.url)
                m.server = pruefe(m.url, m.token)
    finally:
        aus.write("\x1b[?25h\x1b[?1049l")
        aus.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, alt)
    if not los:
        print(HINWEIS)
        return 0
    wahl = [r.key for r in m.zeilen if r.an]
    return _bericht(entfernen(wahl, z) if m.modus == "entfernen" else einrichten(wahl, z, m.url, m.token, signal))


def _bericht(ergebnisse: list[Ergebnis]) -> int:
    for e in ergebnisse:
        print(f"{'✓' if e.ok else '✗'} {e.titel}: {e.text}")
    if any(e.ok for e in ergebnisse):
        print("Laufende Sitzungen der eingerichteten Programme neu starten, damit sie den Server sehen.")
    return 0 if all(e.ok for e in ergebnisse) else 1


def _datei(pfad: str | None) -> str | None:
    if pfad is None:
        return None
    wert = sys.stdin.read() if pfad == "-" else Path(pfad).read_text()
    return wert.strip() or None


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser(prog="vi-mcp einrichten", description="vi-mcp in Claude Code, Codex CLI und Hermes Agent eintragen")
    for k in ("claude", "codex", "hermes", "hook"):
        a.add_argument(f"--{k}", action="store_true")
    a.add_argument("--url")
    a.add_argument("--token-datei", help="Datei mit dem Token, - für die Standardeingabe")
    a.add_argument("--signal-token-datei", help="Token einer Instanz mit Recht --mensch, für die Korrektur-Erkennung des Hooks")
    a.add_argument("--entfernen", action="store_true")
    a.add_argument("--status", action="store_true")
    a.add_argument("--ohne-pruefung", action="store_true", help="eintragen, auch wenn der Server das Token gerade nicht bestätigen kann")
    a.add_argument("--leerlauf", type=float, help="Menü nach so vielen Sekunden ohne Taste beenden")
    o = a.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    z = ziel()
    if o.status:
        for s in stand(z):
            print(f"{s.titel:18} {s.text}")
        return 0
    url = o.url or standard_url(z)
    token, signal = _datei(o.token_datei), _datei(o.signal_token_datei)
    wahl = [k for k in ("claude", "codex", "hermes", "hook") if getattr(o, k)]
    try:
        if not wahl:
            return _lauf(z, url, token, signal, o.leerlauf)
        return _bericht(entfernen(wahl, z) if o.entfernen else einrichten(wahl, z, url, token, signal, o.ohne_pruefung))
    except KeyboardInterrupt:
        print("abgebrochen", file=sys.stderr)
        return 130
