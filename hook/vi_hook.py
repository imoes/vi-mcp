#!/usr/bin/env python3
"""vi_hook — meldet jede Handlung einer Claude-Code-Sitzung an vi-mcp. Nur Standardbibliothek, eine Datei.

Claude Code ruft das Skript als Hook auf (Ereignis aus stdin: `hook_event_name`):
  PreToolUse          → vi_vorher. Gemerkte Antwort (nur MCP-Werkzeuge, nur lesend) → Aufruf verweigert, die Antwort
                        ist der Grund (Hooks können einen Aufruf erlauben/verweigern, nicht ersetzen). Hinweise der VI
                        gehen als Kontext an das Modell.
  PostToolUse         → vi_nachher mit ok=true, Ergebnis, Dauer.
  PostToolUseFailure  → vi_nachher mit ok=false, Fehler.
  SessionEnd          → Gespräch in vi-mcp beenden (DELETE).
  UserPromptSubmit    → erkennt lokal eine Korrektur („nein, …“) oder eine Note (#gut, #schlecht, #note 0.8). Gesendet wird
                        nur dieses Ergebnis, nie der Text.
Jede Claude-Sitzung (`session_id`) ist in vi-mcp genau ein Gespräch; die Mcp-Session-Id liegt in einer Zustandsdatei.

Ausfall: ist vi-mcp nicht erreichbar oder antwortet falsch, läuft der Aufruf durch (Exit 0, keine Ausgabe) — und der
Grund steht in der Protokolldatei (benannt, nicht still). Werkzeuge des Gedächtnisses selbst (vi_*) werden nicht gemeldet.

Datensparsamkeit: Geheimnisse in Argumenten und Fehlern werden vor dem Senden maskiert. Ergebnisse gehen nur bei
MCP-Werkzeugen an den Server, weil nur dort eine gemerkte Antwort möglich ist; eingebaute Werkzeuge (Bash, Read, …) und
Werkzeuge für Zugangsdaten melden nur den Ausgang. Lange Argumente eingebauter Werkzeuge werden gekürzt.

Umgebung:
  VI_MCP_URL         Standard http://127.0.0.1:8765/mcp
  VI_MCP_TOKEN_FILE  Standard ~/.config/vi-mcp/token-$USER  (Bearer-Token der Instanz, 0600). Fehlt die Standarddatei,
                     meldet der Hook ohne Token (Server mit `offen`); eine ausdrücklich genannte Datei muss lesbar sein.
  VI_HOOK_STATE      Standard ~/.cache/vi-mcp/hook        (Zustand je Sitzung und je tool_use_id, 0700)
  VI_HOOK_TIMEOUT    Sekunden je HTTP-Anfrage, Standard 3
"""
from __future__ import annotations

import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = os.environ.get("VI_MCP_URL", "http://127.0.0.1:8765/mcp")
TOKEN_FILE = Path(os.environ.get("VI_MCP_TOKEN_FILE", f"~/.config/vi-mcp/token-{getpass.getuser()}")).expanduser()
STATE = Path(os.environ.get("VI_HOOK_STATE", "~/.cache/vi-mcp/hook")).expanduser()
TIMEOUT = float(os.environ.get("VI_HOOK_TIMEOUT", "3"))
SIGNAL_TOKEN_FILE = Path(os.environ.get("VI_MCP_SIGNAL_TOKEN_FILE", "~/.config/vi-mcp/token-nutzer")).expanduser()
CORRECTION = re.compile(r"^\s*(nein\b|falsch\b|das (ist|war) falsch\b|das stimmt nicht\b|nicht so\b|stop+\b|doch nicht\b|no\b[,.! ]|wrong\b|that'?s (wrong|not)\b)", re.I)
GRADE = re.compile(r"(?:^|\s)#note\s+(0(?:[.,]\d+)?|1(?:[.,]0+)?)(?=\s|$)", re.I)
GOOD, BAD = re.compile(r"(?:^|\s)#gut(?=\s|$)", re.I), re.compile(r"(?:^|\s)#schlecht(?=\s|$)", re.I)
MAX_RESULT = 200_000
MAX_ARG_BUILTIN = 300
MAX_ARG_MCP = 2000
SECRET_TOOL = re.compile(r"pwdepot|passw|secret|credential|_auth_|token", re.I)
SECRET_PATTERNS = [
    (re.compile(r"(?i)\bbearer\s+[^\s\"']+"), "Bearer ***"),
    (re.compile(r"(sshpass\s+-p\s*)\S+"), r"\1***"),
    (re.compile(r"(\s-u\s+[^:\s]+:)\S+"), r"\1***"),
    (re.compile(r"(://[^/\s:@]+:)[^@/\s]+@"), r"\1***@"),
    (re.compile(r"(?i)((?:passwor[dt]|passwd|pwd|secret|token|api[_-]?key)[\"']?\s*[:=]\s*[\"']?)[^\s\"'&,;]+"), r"\1***"),
]


class Outage(Exception):
    """vi-mcp nicht nutzbar — der Aufruf läuft ohne Gedächtnis durch, der Grund wird protokolliert."""


def log_output(text: str) -> None:
    try:
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(STATE / "hook.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {text}\n")
    except OSError:
        pass


# ── Werkzeugname: mcp__<server>__<werkzeug> → <werkzeug>, sonst unverändert ─────

def tool_parts(tool_name: str) -> tuple[str, str | None]:
    """(Werkzeugname für das Gedächtnis, MCP-Server oder None). Rein."""
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__", 2)
        if len(parts) == 3 and parts[2]:
            return parts[2], parts[1]
    return tool_name, None


def read_only_hint(tool_name: str) -> bool | None:
    """Eingebaute Werkzeuge (Bash, Read, Edit, …) werden NIE aus dem Gedächtnis beantwortet — Dateien und
    Systemzustand ändern sich zwischen zwei Aufrufen. Bei MCP-Werkzeugen entscheidet vi-mcp nach dem Namen."""
    return None if tool_name.startswith("mcp__") and not SECRET_TOOL.search(tool_name) else False


def mask(text: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize(value, max_length: int):
    """Geheimnisse maskieren und lange Texte kürzen, rekursiv. Rein."""
    if isinstance(value, str):
        return mask(value)[:max_length]
    if isinstance(value, dict):
        return {k: sanitize(v, max_length) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, max_length) for v in value[:50]]
    return value


# ── Zustand: Gespräch je Sitzung, Vorher je tool_use_id ───────────────────────

def _file(kind: str, key_: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key_)[:120]
    return STATE / kind / f"{safe}.json"


def read(kind: str, key_: str) -> dict | None:
    try:
        return json.loads(_file(kind, key_).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def write(kind: str, key_: str, data: dict) -> None:
    p = _file(kind, key_)
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    old_umask_value = os.umask(0o077)
    try:
        tmp.write_text(json.dumps(data))
    finally:
        os.umask(old_umask_value)
    os.replace(tmp, p)


def remove_entry(kind: str, key_: str) -> None:
    try:
        _file(kind, key_).unlink()
    except OSError:
        pass


# ── MCP über HTTP ─────────────────────────────────────────────────────────────

def _token() -> str | None:
    if "VI_MCP_TOKEN_FILE" not in os.environ and not TOKEN_FILE.exists():
        return None  # Zugang ohne Token
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError as e:
        raise Outage(f"Token-Datei {TOKEN_FILE} nicht lesbar: {e}") from e


def _post(req_body: dict | None, sid: str | None = None, method: str = "POST") -> tuple[int, dict, dict | None]:
    token = _token()
    header = {**({"Authorization": f"Bearer {token}"} if token else {}), "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}
    if sid:
        header["Mcp-Session-Id"] = sid
    data = json.dumps(req_body).encode() if req_body is not None else None
    req = urllib.request.Request(URL, data=data, headers=header, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            return r.status, dict(r.headers), (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise Outage(f"{URL}: {type(e).__name__}: {e}") from e


def _init_session(claude_session: str, cwd: str | None) -> str:
    st, header, a = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "claude-code-hook", "version": "1",
                                                   "claude_session": claude_session, "cwd": cwd}}})
    sid = next((v for k, v in header.items() if k.lower() == "mcp-session-id"), None)
    if st != 200 or not sid:
        raise Outage(f"initialize: HTTP {st}")
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    write("sitzung", claude_session, {"mcp_session_id": sid, "seit": time.time()})
    return sid


def call_tool(claude_session: str, cwd: str | None, name: str, args: dict) -> dict:
    """Werkzeug in vi-mcp aufrufen; bei unbekannter Sitzung (Server neu gestartet, abgelaufen) einmal neu anmelden."""
    z = read("sitzung", claude_session)
    sid = z["mcp_session_id"] if z else _init_session(claude_session, cwd)
    for attempt in range(2):
        st, _k, a = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args}}, sid)
        if st == 404 and attempt == 0:
            sid = _init_session(claude_session, cwd)
            continue
        if st != 200 or not a or "result" not in a:
            raise Outage(f"{name}: HTTP {st} {json.dumps(a)[:200] if a else ''}")
        text = a["result"]["content"][0]["text"]
        if a["result"].get("isError"):
            raise Outage(f"{name}: {text[:200]}")
        return json.loads(text)
    raise Outage(f"{name}: Sitzung nach Neuanmeldung weiter unbekannt")


def signal_off(text: str) -> dict | None:
    """Rein und lokal: {art, note?} oder None. Eine ausdrückliche Note hat Vorrang vor der Korrektur."""
    if not text or text.lstrip().startswith(("/", "<")):
        return None
    if m := GRADE.search(text):
        return {"art": "note", "note": float(m.group(1).replace(",", "."))}
    if GOOD.search(text):
        return {"art": "note", "note": 1.0}
    if BAD.search(text):
        return {"art": "note", "note": 0.0}
    return {"art": "korrektur"} if CORRECTION.match(text) else None


def notify_signal(claude_session: str, text: str) -> None:
    s = signal_off(text)
    z = read("sitzung", claude_session)
    if not s or not z:
        return
    try:
        token = SIGNAL_TOKEN_FILE.read_text().strip()
    except OSError as e:
        raise Outage(f"Signal-Token {SIGNAL_TOKEN_FILE} nicht lesbar: {e}") from e
    req = urllib.request.Request(URL.rsplit("/mcp", 1)[0] + "/signal", data=json.dumps({**s, "mcp_session_id": z["mcp_session_id"]}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT).read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Outage(f"Signal: {type(e).__name__}: {e}") from e


def finish(claude_session: str) -> None:
    """SessionEnd hat in Claude Code standardmäßig nur 1,5 s — deshalb kurzer Timeout. Kommt das DELETE nicht an,
    schließt vi-mcp das Gespräch nach 4 h Leerlauf selbst (Zustand `abgelaufen`)."""
    global TIMEOUT
    z = read("sitzung", claude_session)
    if z:
        TIMEOUT = min(TIMEOUT, 1.0)
        _post(None, z["mcp_session_id"], "DELETE")
        remove_entry("sitzung", claude_session)


# ── Ereignisse ────────────────────────────────────────────────────────────────

def _result_text(answer) -> str:
    text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    return mask(text)[:MAX_RESULT]


def before_tool(e: dict) -> dict | None:
    """Liefert die Hook-Ausgabe (JSON für stdout) oder None (nichts zu sagen)."""
    tool_name = e.get("tool_name") or ""
    name, server = tool_parts(tool_name)
    args = sanitize(e.get("tool_input") or {}, MAX_ARG_MCP if server else MAX_ARG_BUILTIN)
    notify = {"tool": name, "args": args}
    read_only = read_only_hint(tool_name)
    if read_only is not None:
        notify["lesend"] = read_only
    v = call_tool(e["session_id"], e.get("cwd"), "vi_vorher", notify)
    if e.get("tool_use_id"):
        write("vorher", e["tool_use_id"], {"vorher_id": v.get("vorher_id"), "t0": time.time(), "tool": name, "args": v.get("args", args)})
    if v.get("antwort") is not None:
        reason = (f"[VI-Gedächtnis] Dieselbe Anfrage wurde vor {v.get('antwort_alter_s')} s beantwortet (gilt "
                 f"{v.get('antwort_ttl_s')} s); hier die gemerkte Antwort statt eines neuen Aufrufs. Frisch erzwingen: "
                 f"vi_vergiss(tool=\"{name}\").\n\n{v['antwort']}")
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": reason[:MAX_RESULT]}}
    hints = v.get("hinweise") or []
    if hints:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "additionalContext": "[VI-Gedächtnis vor " + name + "]\n" + "\n".join(hints)}}
    return None


def after_tool(e: dict, ok: bool) -> dict | None:
    tool_name = e.get("tool_name") or ""
    name, server = tool_parts(tool_name)
    v = read("vorher", e.get("tool_use_id") or "") or {}
    remove_entry("vorher", e.get("tool_use_id") or "")
    # Dauer: von Claude Code gemessen (duration_ms, ohne Rückfragen und PreToolUse-Hooks), sonst eigene Zeitnahme
    duration = e.get("duration_ms")
    notify = {"tool": name, "args": v.get("args", sanitize(e.get("tool_input") or {}, MAX_ARG_MCP if server else MAX_ARG_BUILTIN)), "ok": ok,
             "dauer_ms": int(duration) if isinstance(duration, (int, float)) else int((time.time() - v["t0"]) * 1000) if v.get("t0") else 0}
    if v.get("vorher_id"):
        notify["vorher_id"] = v["vorher_id"]
    read_only = read_only_hint(tool_name)
    if read_only is not None:
        notify["lesend"] = read_only
    if ok:
        if read_only is None:  # nur hier kann eine Antwort gemerkt werden; sonst bleibt das Ergebnis in der Sitzung
            notify["ergebnis"] = _result_text(e.get("tool_response"))
    else:
        error = e.get("error") or e.get("tool_response") or "unbekannter Fehler"
        error = mask(error) if isinstance(error, str) else error
        notify["fehler"] = ("[abgebrochen] " if e.get("is_interrupt") else "") + _result_text(error)[:2000]
    n = call_tool(e["session_id"], e.get("cwd"), "vi_nachher", notify)
    hints = n.get("hinweise") or []
    if hints:
        return {"hookSpecificOutput": {"hookEventName": e.get("hook_event_name", "PostToolUse"),
                                       "additionalContext": "[VI-Gedächtnis nach " + name + "]\n" + "\n".join(hints)}}
    return None


def process(e: dict) -> dict | None:
    event = e.get("hook_event_name")
    if not e.get("session_id"):
        raise Outage("session_id fehlt im Hook-Ereignis")
    name, server = tool_parts(e.get("tool_name") or "")
    if event in ("PreToolUse", "PostToolUse", "PostToolUseFailure") and server and name.startswith("vi_"):
        return None
    if event == "PreToolUse":
        return before_tool(e)
    if event == "PostToolUse":
        return after_tool(e, ok=True)
    if event == "PostToolUseFailure":
        return after_tool(e, ok=False)
    if event == "UserPromptSubmit":
        notify_signal(e["session_id"], e.get("prompt") or "")
        return None
    if event == "SessionEnd":
        finish(e["session_id"])
        return None
    return None


def main() -> int:
    try:
        e = json.load(sys.stdin)
    except json.JSONDecodeError as ex:
        log_output(f"kein JSON auf stdin: {ex}")
        return 0
    try:
        outputs = process(e)
    except Outage as ex:
        log_output(f"{e.get('hook_event_name')} {e.get('tool_name', '')}: ohne Gedächtnis weiter — {ex}")
        return 0
    except Exception as ex:  # noqa: BLE001 — ein Hook-Fehler darf die Sitzung nie aufhalten
        log_output(f"{e.get('hook_event_name')} {e.get('tool_name', '')}: interner Fehler {type(ex).__name__}: {ex}")
        return 0
    if outputs:
        print(json.dumps(outputs, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
