#!/usr/bin/env python3
"""vi_hook — reports every action of a Claude Code session to vi-mcp. Standard library only, one file.

Claude Code calls the script as a hook (event from stdin: `hook_event_name`):
  PreToolUse          → vi_before. Remembered answer (MCP tools only, read-only) → call denied, the answer
                        is the reason (hooks can allow/deny a call, not replace it). Hints of the VI
                        go to the model as context.
  PostToolUse         → vi_after with ok=true, result, duration.
  PostToolUseFailure  → vi_after with ok=false, error.
  SessionEnd          → end the conversation in vi-mcp (DELETE).
  UserPromptSubmit    → 0.44.0: vi_prompt_context with the prompt (secrets masked, at most 4,000 characters) — knowledge that
                        fits the question goes to the model as context, for follow-up questions too; the server does not store
                        the prompt. Besides, detects locally a correction ("nein, …", "no, …") or a grade (#gut, #schlecht,
                        #note 0.8); only that result goes to /signal.
Hermes Agent (0.44.0) calls the same script as a shell hook `pre_llm_call` with `--hermes`: payload {hook_event_name, session_id,
cwd, extra: {user_message, …}} on stdin, answer {"context": …}. URL and token file come from ~/.config/vi-mcp/hook-hermes.json (Hermes runs hook
commands without a shell, so no "VAR=value command").
Every Claude session (`session_id`) is exactly one conversation in vi-mcp; the Mcp-Session-Id is kept in a state file.

Outage: if vi-mcp is unreachable or answers wrongly, the call goes through (exit 0, no output) — and the
reason is in the log file (named, not silent). The memory's own tools (vi_*) are not reported.

Data minimisation: secrets in arguments and errors are masked before sending. Results go to the server only for
MCP tools, because only there a remembered answer is possible; built-in tools (Bash, Read, …) and
tools for credentials report only the outcome. Long arguments of built-in tools are truncated.

Environment:
  VI_MCP_URL         default http://127.0.0.1:8765/mcp
  VI_MCP_TOKEN_FILE  default ~/.config/vi-mcp/token-$USER  (bearer token of the instance, 0600). If the default file is missing,
                     the hook reports without a token (server with `offen`); an explicitly named file must be readable.
  VI_HOOK_STATE      default ~/.cache/vi-mcp/hook        (state per session and per tool_use_id, 0700)
  VI_HOOK_TIMEOUT    seconds per HTTP request, default 3
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

def _hook_config() -> None:
    if "--hermes" in sys.argv:  # 0.44.0: Hermes has its own instance and token
        try:
            c = json.loads((Path.home() / ".config" / "vi-mcp" / "hook-hermes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            c = {}
        if c.get("url"):
            os.environ["VI_MCP_URL"] = c["url"]
            os.environ["VI_MCP_TOKEN_FILE"] = c.get("token_file") or os.devnull
        return
    _hook_config_claude()


def _hook_config_claude() -> None:
    """0.27.0: without VI_MCP_URL in the environment, take URL and token files from ~/.config/vi-mcp/hook.json (written by vi-mcp setup on
    Windows, where cmd.exe knows no "VAR=value command"). The environment always wins; an empty token file means: no token."""
    if "VI_MCP_URL" in os.environ:
        return
    try:
        c = json.loads((Path.home() / ".config" / "vi-mcp" / "hook.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if c.get("url"):
        os.environ["VI_MCP_URL"] = c["url"]
        os.environ.setdefault("VI_MCP_TOKEN_FILE", c.get("token_file") or os.devnull)
        if c.get("signal_token_file"):
            os.environ.setdefault("VI_MCP_SIGNAL_TOKEN_FILE", c["signal_token_file"])


_hook_config()
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
    """vi-mcp not usable — the call goes through without memory, the reason is logged."""


def log_output(text: str) -> None:
    try:
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(STATE / "hook.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {text}\n")
    except OSError:
        pass


# ── Tool name: mcp__<server>__<tool> → <tool>, otherwise unchanged ─────────────

def tool_parts(tool_name: str) -> tuple[str, str | None]:
    """(tool name for the memory, MCP server or None). Pure."""
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__", 2)
        if len(parts) == 3 and parts[2]:
            return parts[2], parts[1]
    return tool_name, None


def read_only_hint(tool_name: str) -> bool | None:
    """Built-in tools (Bash, Read, Edit, …) are NEVER answered from memory — files and
    system state change between two calls. For MCP tools vi-mcp decides by the name."""
    return None if tool_name.startswith("mcp__") and not SECRET_TOOL.search(tool_name) else False


def mask(text: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize(value, max_length: int):
    """Mask secrets and truncate long texts, recursively. Pure."""
    if isinstance(value, str):
        return mask(value)[:max_length]
    if isinstance(value, dict):
        return {k: sanitize(v, max_length) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, max_length) for v in value[:50]]
    return value


# ── State: conversation per session, before-record per tool_use_id ──────────

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


# ── MCP over HTTP ─────────────────────────────────────────────────────────────

def _token() -> str | None:
    if "VI_MCP_TOKEN_FILE" not in os.environ and not TOKEN_FILE.exists():
        return None  # access without a token
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError as e:
        raise Outage(f"token file {TOKEN_FILE} not readable: {e}") from e


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
    """Call a tool in vi-mcp; on an unknown session (server restarted, expired) log in again once."""
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
    raise Outage(f"{name}: session still unknown after logging in again")


def signal_off(text: str) -> dict | None:
    """Pure and local: {art, note?} or None. An explicit grade takes precedence over the correction."""
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
        raise Outage(f"signal token {SIGNAL_TOKEN_FILE} not readable: {e}") from e
    req = urllib.request.Request(URL.rsplit("/mcp", 1)[0] + "/signal", data=json.dumps({**s, "mcp_session_id": z["mcp_session_id"]}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT).read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Outage(f"Signal: {type(e).__name__}: {e}") from e


def finish(claude_session: str) -> None:
    """SessionEnd has only 1.5 s by default in Claude Code — hence the short timeout. If the DELETE does not arrive,
    vi-mcp closes the conversation itself after 4 h idle (state `abgelaufen`)."""
    global TIMEOUT
    z = read("sitzung", claude_session)
    if z:
        TIMEOUT = min(TIMEOUT, 1.0)
        _post(None, z["mcp_session_id"], "DELETE")
        remove_entry("sitzung", claude_session)


# ── Events ────────────────────────────────────────────────────────────────────

def _result_text(answer) -> str:
    text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    return mask(text)[:MAX_RESULT]


def before_tool(e: dict) -> dict | None:
    """Returns the hook output (JSON for stdout) or None (nothing to say)."""
    tool_name = e.get("tool_name") or ""
    name, server = tool_parts(tool_name)
    args = sanitize(e.get("tool_input") or {}, MAX_ARG_MCP if server else MAX_ARG_BUILTIN)
    notify = {"tool": name, "args": args}
    read_only = read_only_hint(tool_name)
    if read_only is not None:
        notify["read_only"] = read_only
    v = call_tool(e["session_id"], e.get("cwd"), "vi_before", notify)
    if e.get("tool_use_id"):
        write("vorher", e["tool_use_id"], {"vorher_id": v.get("vorher_id"), "t0": time.time(), "tool": name, "args": v.get("args", args)})
    if v.get("antwort") is not None:
        reason = (f"[VI memory] The same request was answered {v.get('antwort_alter_s')} s ago (valid for "
                 f"{v.get('antwort_ttl_s')} s); here is the remembered answer instead of a new call. Force a fresh call: "
                 f"vi_forget(tool=\"{name}\").\n\n{v['antwort']}")
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": reason[:MAX_RESULT]}}
    hints = v.get("hinweise") or []
    if hints:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "additionalContext": "[VI memory before " + name + "]\n" + "\n".join(hints)}}
    return None


def after_tool(e: dict, ok: bool) -> dict | None:
    tool_name = e.get("tool_name") or ""
    name, server = tool_parts(tool_name)
    v = read("vorher", e.get("tool_use_id") or "") or {}
    remove_entry("vorher", e.get("tool_use_id") or "")
    # duration: measured by Claude Code (duration_ms, without permission prompts and PreToolUse hooks), else own timing
    duration = e.get("duration_ms")
    notify = {"tool": name, "args": v.get("args", sanitize(e.get("tool_input") or {}, MAX_ARG_MCP if server else MAX_ARG_BUILTIN)), "ok": ok,
             "duration_ms": int(duration) if isinstance(duration, (int, float)) else int((time.time() - v["t0"]) * 1000) if v.get("t0") else 0}
    if v.get("vorher_id"):
        notify["before_id"] = v["vorher_id"]
    read_only = read_only_hint(tool_name)
    if read_only is not None:
        notify["read_only"] = read_only
    if ok:
        if read_only is None:  # only here can an answer be remembered; otherwise the result stays in the session
            notify["result"] = _result_text(e.get("tool_response"))
    else:
        error = e.get("error") or e.get("tool_response") or "unbekannter Fehler"
        error = mask(error) if isinstance(error, str) else error
        notify["error"] = ("[abgebrochen] " if e.get("is_interrupt") else "") + _result_text(error)[:2000]
    n = call_tool(e["session_id"], e.get("cwd"), "vi_after", notify)
    hints = n.get("hinweise") or []
    if hints:
        return {"hookSpecificOutput": {"hookEventName": e.get("hook_event_name", "PostToolUse"),
                                       "additionalContext": "[VI memory after " + name + "]\n" + "\n".join(hints)}}
    return None


MAX_PROMPT = 4000
PROMPT_SHOWN_MAX = 200


def prompt_context(session: str, cwd: str | None, prompt: str) -> str | None:
    """0.44.0: hints for the user's question. Ids already shown in this session are not repeated."""
    text = (prompt or "").strip()
    if not text or text.startswith(("/", "<")):
        return None
    state = read("prompt", session) or {"gezeigt": []}
    v = call_tool(session, cwd, "vi_prompt_context", {"prompt": mask(text)[:MAX_PROMPT], "shown": state["gezeigt"][-PROMPT_SHOWN_MAX:]})
    hints = v.get("hinweise") or []
    if not hints:
        return None
    write("prompt", session, {"gezeigt": (state["gezeigt"] + list(v.get("ids") or []))[-PROMPT_SHOWN_MAX:]})
    return "[VI memory for this question — read and follow, or contradict with a reason]\n" + "\n".join(hints)


def hermes(e: dict) -> dict | None:
    """Hermes shell hook pre_llm_call: {"context": …} or nothing."""
    if e.get("hook_event_name") != "pre_llm_call" or not e.get("session_id"):
        return None
    # Hermes shell hooks get the event fields under "extra" (seen 11.11.2026: {hook_event_name, tool_name, tool_input, session_id,
    # cwd, extra: {user_message, …}}); plugin hooks get them at the top — both are accepted
    message = e.get("user_message") or (e.get("extra") or {}).get("user_message") or ""
    ctx = prompt_context("hermes-" + str(e["session_id"]), e.get("cwd"), message)
    return {"context": ctx} if ctx else None


def process(e: dict) -> dict | None:
    event = e.get("hook_event_name")
    if not e.get("session_id"):
        raise Outage("session_id missing in hook event")
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
        ctx = prompt_context(e["session_id"], e.get("cwd"), e.get("prompt") or "")
        try:
            notify_signal(e["session_id"], e.get("prompt") or "")
        except Outage as ex:  # a missing signal token must not cost the context
            log_output(f"UserPromptSubmit signal: {ex}")
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}} if ctx else None
    if event == "SessionEnd":
        finish(e["session_id"])
        return None
    return None


def main() -> int:
    try:
        e = json.load(sys.stdin)
    except json.JSONDecodeError as ex:
        log_output(f"no JSON on stdin: {ex}")
        return 0
    try:
        outputs = hermes(e) if "--hermes" in sys.argv else process(e)
    except Outage as ex:
        log_output(f"{e.get('hook_event_name')} {e.get('tool_name', '')}: continuing without memory — {ex}")
        return 0
    except Exception as ex:  # noqa: BLE001 — a hook error must never stop the session
        log_output(f"{e.get('hook_event_name')} {e.get('tool_name', '')}: internal error {type(ex).__name__}: {ex}")
        return 0
    if outputs:
        # UTF-8 bytes, whatever the locale: on Windows stdout to a pipe is cp1252, and "→" or "≤" in a hint raised UnicodeEncodeError (0.28.1)
        sys.stdout.buffer.write((json.dumps(outputs, ensure_ascii=False) + "\n").encode("utf-8"))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
