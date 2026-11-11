"""Setup — registers vi-mcp in Claude Code, Codex CLI and Hermes Agent. ANSI menu or switches, standard library + PyYAML only.

  vi-mcp setup                            menu
  vi-mcp setup --status                   state per program
  vi-mcp setup --claude --hermes --hook --url URL --token-file FILE   without menu
  vi-mcp setup --claude --uninstall

Started with sudo, it applies to the calling user; files are written with that user's rights.
If the server runs on the same machine and its configuration is writable, every program gets its own instance
with its own token (`<user>-claude`, …), and the service is restarted. Otherwise an existing token is used.
Before writing, it checks that the server accepts the token. A change is only written if the rest of the
file proves unchanged when read back. Every changed file gets a backup `<file>.bak-vi-mcp-<time>`.
Tokens never appear on a command line.
"""
from __future__ import annotations

import argparse
import copy
import getpass
import glob
import json
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__, config

NAME = "vi-mcp"
ENV_TOKEN = "VI_MCP_TOKEN"
LOCAL = ("127.0.0.1", "localhost", "::1")
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")
HINT = "Set up for Claude Code, Codex and Hermes:  sudo vi-mcp setup"


class Refused(Exception):
    """Something is deliberately not done; the text names the reason."""


@dataclass(frozen=True)
class TargetUser:
    name: str
    home: Path
    uid: int
    gid: int


WINDOWS = os.name == "nt"
try:  # POSIX only — on Windows the non-interactive setup works, the ANSI menu does not (0.27.0)
    import pwd
    import termios
    import tty as _tty
except ImportError:
    pwd = termios = _tty = None


def _caller():
    """Who is behind root: SUDO_USER, otherwise the login (rpm does not always pass the environment on to scriptlets)."""
    try:
        if (n := os.environ.get("SUDO_USER")) and n != "root":
            return pwd.getpwnam(n)
        uid = int(Path("/proc/self/loginuid").read_text())
        return pwd.getpwuid(uid) if 0 < uid < 4294967295 else None
    except (OSError, KeyError, ValueError):
        return None


def target() -> TargetUser:
    if WINDOWS:
        return TargetUser(getpass.getuser(), Path.home(), -1, -1)
    if os.geteuid() == 0 and (p := _caller()):
        return TargetUser(p.pw_name, Path(p.pw_dir), p.pw_uid, p.pw_gid)
    p = pwd.getpwuid(os.geteuid())
    return TargetUser(p.pw_name, Path.home(), p.pw_uid, p.pw_gid)


@contextmanager
def _as_user(z: TargetUser):
    """Work with the target user's rights so that owner and permissions of their files are right."""
    switch_user = not WINDOWS and os.geteuid() == 0 and z.uid != 0
    if switch_user:
        os.setegid(z.gid)
        os.seteuid(z.uid)
    try:
        yield
    finally:
        if switch_user:
            os.seteuid(0)
            os.setegid(0)


def _write(p: Path, content: str) -> str:
    """Atomic, 0600 (the files carry tokens). Returns a description with the path of the backup."""
    p = Path(os.path.realpath(p))
    old = p.read_text() if p.exists() else None
    if old == content:
        return f"{p} unchanged"
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    text = f"{p} created"
    if old is not None:
        backup_copy = Path(f"{p}.bak-vi-mcp-{time.strftime('%Y%m%d-%H%M%S')}")
        fd = os.open(backup_copy, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(old)
        text = f"{p} changed (backup {backup_copy.name})"
    tmp = Path(f"{p}.vi-mcp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, p)
    return text


def _text(p: Path) -> str:
    return p.read_text() if p.exists() else ""


def _json(p: Path) -> dict:
    try:
        d = json.loads(_text(p) or "{}")
    except json.JSONDecodeError as e:
        raise Refused(f"{p} is not valid JSON ({e.msg}, line {e.lineno}); nothing changed") from e
    if not isinstance(d, dict):
        raise Refused(f"{p} contains no JSON object; nothing changed")
    return d


def _without_entry(d: dict) -> dict:
    d = copy.deepcopy(d)
    if isinstance(d.get("mcp_servers"), dict):
        d["mcp_servers"].pop(NAME, None)
    if not d.get("mcp_servers"):
        d.pop("mcp_servers", None)
    return d


def _only_entry_differs(old: dict, new: dict, desired: dict | None, p: Path) -> None:
    if _without_entry(old) != _without_entry(new) or (new.get("mcp_servers") or {}).get(NAME) != desired:
        raise Refused(f"{p}: the change would have touched more than the entry {NAME}; nothing changed")


# ---- Claude Code: ~/.claude.json (mcpServers) and ~/.claude/settings.json (hook) ----

def _claude_file(z: TargetUser) -> Path:
    return z.home / ".claude.json"


def _claude_entry(z: TargetUser) -> dict | None:
    return _json(_claude_file(z)).get("mcpServers", {}).get(NAME)


def _claude_on(z: TargetUser, url: str, token: str) -> str:
    p = _claude_file(z)
    d = _json(p)
    # 0.34.0: X-VI-Family announces the model family (confirmations of one family count as one independent line)
    d.setdefault("mcpServers", {})[NAME] = {"type": "http", "url": url,
                                            "headers": {**({"Authorization": f"Bearer {token}"} if token else {}), "X-VI-Family": "claude"}}
    return _write(p, json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def _claude_off(z: TargetUser) -> str:
    p = _claude_file(z)
    d = _json(p)
    d.get("mcpServers", {}).pop(NAME, None)
    return _write(p, json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def _token_from_claude(z: TargetUser) -> str | None:
    with _as_user(z):
        return _claude_token(z)


def _claude_token(z: TargetUser) -> str | None:
    e = _claude_entry(z) or {}
    value = (e.get("headers") or {}).get("Authorization", "")
    return value[7:] if value.startswith("Bearer ") else None


def _hook_script() -> Path:
    package = Path("/usr/share/vi-mcp/hook/vi_hook.py")
    return package if package.exists() else Path(__file__).resolve().parents[1] / "hook" / "vi_hook.py"


def _settings(z: TargetUser) -> Path:
    return z.home / ".claude" / "settings.json"


def _is_ours(block: dict) -> bool:
    return any("vi_hook.py" in h.get("command", "") for h in block.get("hooks", []))


def _hook_active(z: TargetUser) -> bool:
    return any(_is_ours(b) for blocks in _json(_settings(z)).get("hooks", {}).values() for b in blocks)


def _hook_without(d: dict) -> None:
    hooks = d.get("hooks", {})
    for event in list(hooks):
        hooks[event] = [b for b in hooks[event] if not _is_ours(b)]
        if not hooks[event]:
            del hooks[event]
    if "hooks" in d and not d["hooks"]:
        del d["hooks"]


def _hook_on(z: TargetUser, url: str, token: str, signal: str | None) -> str:
    dir_path = z.home / ".config" / "vi-mcp"
    environment = f"VI_MCP_URL={shlex.quote(url)}"
    if token:
        _write(dir_path / "token-claude", token + "\n")
        environment += " VI_MCP_TOKEN_FILE=$HOME/.config/vi-mcp/token-claude"
    else:  # open server: the hook reports without a token, an old token file must not interfere
        environment += " VI_MCP_TOKEN_FILE=/dev/null"
    if signal:
        _write(dir_path / "token-nutzer", signal + "\n")
        environment += " VI_MCP_SIGNAL_TOKEN_FILE=$HOME/.config/vi-mcp/token-nutzer"
    command = f"{environment} python3 -I {shlex.quote(str(_hook_script()))}"
    if WINDOWS:  # no "VAR=value command" in cmd.exe: the hook reads URL and token files from hook.json (0.27.0)
        _write(dir_path / "hook.json", json.dumps({"url": url, "token_file": str(dir_path / "token-claude") if token else "",
                                                   "signal_token_file": str(dir_path / "token-nutzer") if signal else ""}, indent=2) + "\n")
        command = f'"{sys.executable}" -I -X utf8 "{_hook_script()}"'
    p = _settings(z)
    d = _json(p)
    _hook_without(d)
    h = d.setdefault("hooks", {})
    for e in HOOK_EVENTS:
        h.setdefault(e, []).append({"matcher": "*", "hooks": [{"type": "command", "command": command, "timeout": 5}]})
    # UserPromptSubmit always since 0.44.0: memory for every question, follow-ups included (the user decided, 11.11.2026)
    for e in ("SessionEnd", "UserPromptSubmit"):
        h.setdefault(e, []).append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})
    text = _write(p, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return text + ("" if signal else "; without correction detection (no signal token)")


def _hook_off(z: TargetUser) -> str:
    p = _settings(z)
    d = _json(p)
    _hook_without(d)
    for name in ("token-claude", "token-nutzer"):
        (z.home / ".config" / "vi-mcp" / name).unlink(missing_ok=True)
    return _write(p, json.dumps(d, indent=2, ensure_ascii=False) + "\n")


# ---- Codex CLI: ~/.codex/config.toml, table [mcp_servers.vi-mcp] ----

_TOML_HEADER = re.compile(r"^\s*\[+\s*([^\]]+?)\s*\]+")


def _codex_file(z: TargetUser) -> Path:
    return z.home / ".codex" / "config.toml"


def _toml(text: str, p: Path) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Refused(f"{p} is not valid TOML ({e}); nothing changed") from e


def _toml_without(text: str) -> str:
    outputs, remove = [], False
    for line in text.splitlines(keepends=True):
        if m := _TOML_HEADER.match(line):
            key_ = re.sub(r"[\"'\s]", "", m[1])
            remove = key_ == f"mcp_servers.{NAME}" or key_.startswith(f"mcp_servers.{NAME}.")
        if not remove:
            outputs.append(line)
    return "".join(outputs)


def codex_set(text: str, url: str, token: str, p: Path = Path("config.toml")) -> str:
    """Pure. json.dumps produces valid TOML strings here (ASCII only, with \\uXXXX)."""
    old = _toml(text, p)
    body_text = _toml_without(text).rstrip("\n")
    auth = f'Authorization = {json.dumps("Bearer " + token)}, ' if token else ""
    block = f'[mcp_servers.{NAME}]\nurl = {json.dumps(url)}\nhttp_headers = {{ {auth}"X-VI-Family" = "gpt" }}\n'  # 0.34.0: model family
    new = (body_text + "\n\n" if body_text else "") + block
    _only_entry_differs(old, _toml(new, p), {"url": url, "http_headers": {**({"Authorization": f"Bearer {token}"} if token else {}), "X-VI-Family": "gpt"}}, p)
    return new


def codex_remove(text: str, p: Path = Path("config.toml")) -> str:
    old = _toml(text, p)
    new = _toml_without(text).rstrip("\n") + "\n"
    _only_entry_differs(old, _toml(new, p), None, p)
    return new


def _codex_on(z: TargetUser, url: str, token: str) -> str:
    p = _codex_file(z)
    return _write(p, codex_set(_text(p), url, token, p))


def _codex_off(z: TargetUser) -> str:
    p = _codex_file(z)
    return _write(p, codex_remove(_text(p), p))


def _codex_entry(z: TargetUser) -> dict | None:
    p = _codex_file(z)
    return _toml(_text(p), p).get("mcp_servers", {}).get(NAME)


# ---- Hermes Agent: ~/.hermes/config.yaml (mcp_servers) and ~/.hermes/.env (token) ----

def _hermes_dir(z: TargetUser) -> Path:
    e = os.environ.get("HERMES_HOME", "").strip()
    return Path(e) if e else z.home / ".hermes"


def _yaml(text: str, p: Path) -> dict:
    try:
        import yaml
    except ImportError as e:
        raise Refused("PyYAML missing (python3-yaml), the Hermes configuration cannot be checked") from e
    try:
        d = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise Refused(f"{p} is not valid YAML; nothing changed ({str(e)[:120]})") from e
    if not isinstance(d, dict):
        raise Refused(f"{p} contains no mapping; nothing changed")
    return d


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _content(line: str) -> bool:
    return bool(line.strip()) and not line.lstrip().startswith("#")


def _yaml_section(lines: list[str]) -> tuple[int, int] | None:
    """Header line and end of the mcp_servers section; None if there is none."""
    for i, z in enumerate(lines):
        if re.match(r"^mcp_servers:\s*(#.*)?$", z):
            end = next((j for j in range(i + 1, len(lines)) if _content(lines[j]) and _indent(lines[j]) == 0), len(lines))
            while end > i + 1 and not _content(lines[end - 1]):
                end -= 1
            return i, end
    return None


def _yaml_without(lines: list[str]) -> list[str]:
    from_seq = _yaml_section(lines)
    if not from_seq:
        return lines
    header, end = from_seq
    start = next((i for i in range(header + 1, end) if re.match(rf"^\s+{re.escape(NAME)}:\s*(#.*)?$", lines[i])), None)
    if start is None:
        return lines
    depth = _indent(lines[start])
    stop = next((j for j in range(start + 1, end) if _content(lines[j]) and _indent(lines[j]) <= depth), end)
    return lines[:start] + lines[stop:]


def hermes_set(text: str, url: str, p: Path = Path("config.yaml"), with_token: bool = True) -> str:
    """Pure. The token is not here but in ~/.hermes/.env; Hermes substitutes ${VAR} when connecting."""
    old = _yaml(text, p)
    lines = text.splitlines()
    for i, z in enumerate(lines):
        if m := re.match(r"^mcp_servers:\s*(\S.*)$", z):
            if m[1].split("#")[0].strip() in ("{}", "null", "~", ""):
                lines[i] = "mcp_servers:"
            elif not m[1].startswith("#"):
                raise Refused(f"{p}: mcp_servers is in inline notation; please add the entry by hand, nothing changed")
    lines = _yaml_without(lines)
    from_seq = _yaml_section(lines)
    if not from_seq:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "mcp_servers:"] if lines else ["mcp_servers:"]
        from_seq = (len(lines) - 1, len(lines))
    header, end = from_seq
    depth = next((_indent(lines[i]) for i in range(header + 1, end) if _content(lines[i])), 2)
    margin = " " * depth
    block = [f"{margin}{NAME}:", f"{margin}  url: {json.dumps(url)}"] + ([f"{margin}  headers:", f'{margin}    Authorization: "Bearer ${{{ENV_TOKEN}}}"'] if with_token else [])
    new = "\n".join(lines[:end] + block + lines[end:]) + "\n"
    _only_entry_differs(old, _yaml(new, p), {"url": url, **({"headers": {"Authorization": f"Bearer ${{{ENV_TOKEN}}}"}} if with_token else {})}, p)
    return new


def hermes_remove(text: str, p: Path = Path("config.yaml")) -> str:
    old = _yaml(text, p)
    new = "\n".join(_yaml_without(text.splitlines())) + "\n"
    _only_entry_differs(old, _yaml(new, p), None, p)
    return new


def env_set(text: str, token: str | None) -> str:
    """Pure. token None removes the line."""
    lines = [z for z in text.splitlines() if not z.startswith(f"{ENV_TOKEN}=")]
    if token:
        lines.append(f"{ENV_TOKEN}={token}")
    return "\n".join(lines) + "\n" if lines else ""


# 0.44.0: Hermes shell hook pre_llm_call — memory for every user prompt (the user decided, 11.11.2026)
HERMES_HOOK_EVENT = "pre_llm_call"


def _hook_items(lines: list[str], start: int, end: int) -> list[tuple[int, int]]:
    """(first, end) of every list item between start and end at the item indentation of the first '- '."""
    idx = [i for i in range(start, end) if lines[i].lstrip().startswith("- ")]
    if not idx:
        return []
    depth = _indent(lines[idx[0]])
    idx = [i for i in idx if _indent(lines[i]) == depth]
    out = []
    for n, i in enumerate(idx):
        stop = idx[n + 1] if n + 1 < len(idx) else next((j for j in range(i + 1, end) if _content(lines[j]) and _indent(lines[j]) <= depth and not lines[j].lstrip().startswith("- ")), end)
        out.append((i, stop))
    return out


def _top_section(lines: list[str], key: str) -> tuple[int, int] | None:
    for i, z in enumerate(lines):
        if re.match(rf"^{re.escape(key)}:\s*(#.*)?$", z):
            end = next((j for j in range(i + 1, len(lines)) if _content(lines[j]) and _indent(lines[j]) == 0), len(lines))
            while end > i + 1 and not _content(lines[end - 1]):
                end -= 1
            return i, end
    return None


def _without_hermes_hook(lines: list[str]) -> list[str]:
    sec = _top_section(lines, "hooks")
    if not sec:
        return lines
    h, end = sec
    ev = next((i for i in range(h + 1, end) if re.match(rf"^\s+{HERMES_HOOK_EVENT}:\s*(#.*)?$", lines[i])), None)
    if ev is None:
        return lines
    depth = _indent(lines[ev])
    ev_end = next((j for j in range(ev + 1, end) if _content(lines[j]) and _indent(lines[j]) <= depth and not lines[j].lstrip().startswith("- ")), end)
    drop = [(a, b) for a, b in _hook_items(lines, ev + 1, ev_end) if any("vi_hook.py" in lines[k] for k in range(a, b))]
    for a, b in reversed(drop):
        lines = lines[:a] + lines[b:]
        ev_end -= b - a
    if not any(_content(lines[k]) for k in range(ev + 1, ev_end)):  # nothing left under the event: remove the key
        lines = lines[:ev] + lines[ev_end:]
        sec = _top_section(lines, "hooks")
        if sec and not any(_content(lines[k]) for k in range(sec[0] + 1, sec[1])):
            lines = lines[:sec[0]] + lines[sec[1]:]
    return lines


def hermes_hook_set(text: str, command: str, p: Path = Path("config.yaml")) -> str:
    """Pure. Adds (or replaces) our pre_llm_call shell hook; everything else stays as it is, comments included."""
    old = _yaml(text, p)
    present = [x for x in ((old.get("hooks") or {}).get(HERMES_HOOK_EVENT) or []) if "vi_hook.py" in str((x or {}).get("command", ""))]
    if present == [{"command": command, "timeout": 10}]:
        return text if text.endswith("\n") else text + "\n"  # already there: unchanged
    lines = text.splitlines()
    for i, z in enumerate(lines):
        if m := re.match(r"^hooks:\s*(\S.*)$", z):
            if m[1].split("#")[0].strip() in ("{}", "null", "~", ""):
                lines[i] = "hooks:"
            elif not m[1].startswith("#"):
                raise Refused(f"{p}: hooks is in inline notation; please add the hook by hand, nothing changed")
    lines = _without_hermes_hook(lines)
    item = [f"- command: {json.dumps(command)}", "  timeout: 10"]
    sec = _top_section(lines, "hooks")
    if not sec:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ([""] if lines else []) + ["hooks:", f"  {HERMES_HOOK_EVENT}:"] + [f"    {x}" for x in item]
    else:
        h, end = sec
        ev = next((i for i in range(h + 1, end) if re.match(rf"^\s+{HERMES_HOOK_EVENT}:\s*(#.*)?$", lines[i])), None)
        if ev is None:
            depth = next((_indent(lines[i]) for i in range(h + 1, end) if _content(lines[i])), 2)
            lines = lines[:end] + [" " * depth + f"{HERMES_HOOK_EVENT}:"] + [" " * (depth + 2) + x for x in item] + lines[end:]
        else:
            depth = _indent(lines[ev])
            ev_end = next((j for j in range(ev + 1, end) if _content(lines[j]) and _indent(lines[j]) <= depth and not lines[j].lstrip().startswith("- ")), end)
            items = _hook_items(lines, ev + 1, ev_end)
            ind = _indent(lines[items[0][0]]) if items else depth + 2
            lines = lines[:ev_end] + [" " * ind + x for x in item] + lines[ev_end:]
    new = "\n".join(lines) + "\n"
    d_old, d_new = dict(old), _yaml(new, p)
    ours = [x for x in ((d_new.get("hooks") or {}).get(HERMES_HOOK_EVENT) or []) if "vi_hook.py" in str((x or {}).get("command", ""))]
    strip = lambda d: {**d, "hooks": {k: [x for x in (v or []) if "vi_hook.py" not in str((x or {}).get("command", ""))] if k == HERMES_HOOK_EVENT else v
                                       for k, v in (d.get("hooks") or {}).items()}}  # noqa: E731
    clean = lambda d: {k: v for k, v in strip(d).items() if not (k == "hooks" and not any(v.values()))}  # noqa: E731
    if ours != [{"command": command, "timeout": 10}] or clean(d_old) != clean(d_new):
        raise Refused(f"{p}: the change would have touched more than our hook; nothing changed")
    return new


def hermes_hook_remove(text: str, p: Path = Path("config.yaml")) -> str:
    _yaml(text, p)
    return "\n".join(_without_hermes_hook(text.splitlines())) + "\n"


def _hermes_hook_command() -> str:
    return f"python3 -I {_hook_script()} --hermes"


def _hermes_on(z: TargetUser, url: str, token: str) -> str:
    v = _hermes_dir(z)
    p = v / "config.yaml"
    new = hermes_set(_text(p), url, p, with_token=bool(token))
    new = hermes_hook_set(new, _hermes_hook_command(), p)
    _write(v / ".env", env_set(_text(v / ".env"), token or None))
    dir_path = z.home / ".config" / "vi-mcp"  # the hook runs without a shell: URL and token file from its own config
    if token:
        _write(dir_path / "token-hermes", token + "\n")
    _write(dir_path / "hook-hermes.json", json.dumps({"url": url, "token_file": str(dir_path / "token-hermes") if token else ""}, indent=2) + "\n")
    return _write(p, new) + ("; hook pre_llm_call: Hermes asks once for consent at the next start (or hermes --accept-hooks)")


def _hermes_off(z: TargetUser) -> str:
    v = _hermes_dir(z)
    p = v / "config.yaml"
    new = hermes_hook_remove(hermes_remove(_text(p), p), p)
    _write(v / ".env", env_set(_text(v / ".env"), None))
    for name in ("token-hermes", "hook-hermes.json"):
        (z.home / ".config" / "vi-mcp" / name).unlink(missing_ok=True)
    return _write(p, new)


def _hermes_entry(z: TargetUser) -> dict | None:
    p = _hermes_dir(z) / "config.yaml"
    return (_yaml(_text(p), p).get("mcp_servers") or {}).get(NAME)


# ---- Overview ----

@dataclass(frozen=True)
class SockFprog:
    key: str
    title: str
    command: str
    directory: Callable[[TargetUser], Path]
    entry: Callable[[TargetUser], dict | None]
    on: Callable[[TargetUser, str, str], str]
    outputs: Callable[[TargetUser], str]


PROGRAMS = (
    SockFprog("claude", "Claude Code", "claude", lambda z: z.home / ".claude", _claude_entry, _claude_on, _claude_off),
    SockFprog("codex", "Codex CLI", "codex", lambda z: z.home / ".codex", _codex_entry, _codex_on, _codex_off),
    SockFprog("hermes", "Hermes Agent", "hermes", _hermes_dir, _hermes_entry, _hermes_on, _hermes_off),
)


#: system-wide directories searched besides PATH (tests empty it, so a program installed on the build host does not leak in)
SYSTEM_BIN = ["/usr/local/bin"]


def _find(command: str, z: TargetUser) -> str | None:
    if WINDOWS:
        return shutil.which(command, path=os.pathsep.join([os.environ.get("PATH", ""), str(z.home / "AppData" / "Roaming" / "npm"),
                                                           str(z.home / ".local" / "bin")]))
    paths = [*os.environ.get("PATH", "").split(":"), str(z.home / ".local/bin"), str(z.home / ".npm-global/bin"), str(z.home / "bin"), *SYSTEM_BIN,
             *glob.glob(str(z.home / ".nvm/versions/node/*/bin"))]
    return shutil.which(command, path=":".join(paths))


@dataclass
class SetupStatus:
    key: str
    title: str
    present: str  # installiert | nur_konfiguration | fehlt
    configured: bool
    text: str


def progress(z: TargetUser) -> list[SetupStatus]:
    outputs = []
    with _as_user(z):
        for p in PROGRAMS:
            location = _find(p.command, z)
            v = "installiert" if location else "nur_konfiguration" if p.directory(z).exists() else "fehlt"
            try:
                e = p.entry(z)
                configured, part = bool(e), (f"set up: {e.get('url')}" if e else "not set up yet")
            except Refused as ex:
                configured, part = False, f"configuration unreadable: {ex}"
            text = {"installiert": part, "nur_konfiguration": f"program not in PATH, configuration present; {part}",
                    "fehlt": f"not found: {p.command} not in PATH, {p.directory(z)} missing"}[v]
            outputs.append(SetupStatus(p.key, p.title, v, configured, text))
        c = outputs[0]
        try:
            h = _hook_active(z)
        except Refused:
            h = False
    if c.present == "fehlt":
        hv, ht = "fehlt", "needs Claude Code"
    else:
        hv, ht = "installiert", "set up" if h else "reports every action to the server (arguments masked)"
    return outputs + [SetupStatus("hook", "Claude Code hook", hv, h, ht)]


# ---- Server ----

def _local(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "") in LOCAL


def _urlopen(req: urllib.request.Request, timeout: float):
    """Direct first, then via the proxy of the environment. An HTTP answer (even an error) ends the search."""
    last: Exception | None = None
    for op in (urllib.request.build_opener(urllib.request.ProxyHandler({})), None if _local(req.full_url) else urllib.request.build_opener()):
        if op is None:
            break
        try:
            return op.open(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last = e
    raise last  # type: ignore[misc]


def check(url: str, token: str | None, timeout: float = 4) -> tuple[str, str]:
    """(kind, text); kind ∈ token_ok, offen (usable without a token), token_abgelehnt, erreichbar, nicht_erreichbar, keine_mcp_antwort."""
    if not re.match(r"^https?://[^/\s]+/\S*$", url):
        return "nicht_erreichbar", "URL does not have the form http(s)://host/…/mcp"
    if not token:
        kind, text = _initialize(url, {}, timeout)
        if kind == "token_ok":
            return "offen", text.replace("token valid", "open, usable without a token")
        try:
            with _urlopen(urllib.request.Request(url.rsplit("/mcp", 1)[0] + "/gesund"), timeout) as a:
                return "erreichbar", a.read(200).decode("utf-8", "replace").strip()
        except urllib.error.HTTPError as e:
            return "keine_mcp_antwort", f"HTTP {e.code} on /gesund"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            return "nicht_erreichbar", str(getattr(e, "reason", e))[:160]
    return _initialize(url, {"Authorization": f"Bearer {token}"}, timeout)


def _initialize(url: str, auth: dict, timeout: float) -> tuple[str, str]:
    header = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **auth}
    req_body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "vi-mcp-einrichten", "version": __version__}}}
    try:
        with _urlopen(urllib.request.Request(url, data=json.dumps(req_body).encode(), headers=header), timeout) as a:
            sid = a.headers.get("Mcp-Session-Id")
            info = json.loads(a.read())["result"]["serverInfo"]
    except urllib.error.HTTPError as e:
        return ("token_abgelehnt", f"server refuses the token (HTTP {e.code})") if e.code in (401, 403) else ("keine_mcp_antwort", f"HTTP {e.code}")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return "nicht_erreichbar", str(getattr(e, "reason", e))[:160]
    except (json.JSONDecodeError, KeyError, TypeError):
        return "keine_mcp_antwort", "answer is not MCP"
    if sid:
        try:
            _urlopen(urllib.request.Request(url, headers={**header, "Mcp-Session-Id": sid}, method="DELETE"), timeout).close()
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
    return "token_ok", f"{info.get('name')} {info.get('version')}, token valid"


def can_create_tokens(url: str) -> bool:
    return _local(url) and config.fpath().exists() and os.access(config.fpath(), os.W_OK)


def _restart() -> str | None:
    """The service reads instances only at start. None = success, otherwise the reason."""
    if WINDOWS:  # the MSI runs the server as scheduled task "vi-mcp"
        for command in (["schtasks", "/End", "/TN", "vi-mcp"], ["schtasks", "/Run", "/TN", "vi-mcp"]):
            try:
                r = subprocess.run(command, capture_output=True, text=True, timeout=45)
            except (OSError, subprocess.TimeoutExpired) as e:
                return f"{' '.join(command)}: {e}"
            if r.returncode != 0 and command[1] == "/Run":
                return f"{' '.join(command)}: {(r.stderr or r.stdout).strip()[:200]}"
        return None
    command = ["systemctl", "restart", "vi-mcp"] if os.geteuid() == 0 else ["systemctl", "--user", "restart", "vi-mcp"]
    try:
        r = subprocess.run(command, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"{' '.join(command)}: {e}"
    return None if r.returncode == 0 else f"{' '.join(command)}: {r.stderr.strip()[:200]}"


def _wait(url: str, seconds: float = 15) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if check(url, None, 2)[0] == "erreichbar":
            return True
        time.sleep(0.3)
    return False


@dataclass
class Result:
    key: str
    title: str
    ok: bool
    text: str


def default_url(z: TargetUser) -> str:
    if u := os.environ.get("VI_MCP_URL"):
        return u
    with _as_user(z):
        for p in PROGRAMS:
            try:
                if (e := p.entry(z)) and e.get("url"):
                    return e["url"]
            except Refused:
                pass
    try:
        port = json.loads(config.fpath().read_text(encoding="utf-8-sig")).get("port", 8765)
    except (OSError, json.JSONDecodeError):
        port = 8765
    return f"http://127.0.0.1:{port}/mcp"


def _title(key: str) -> str:
    return "Claude Code hook" if key == "hook" else next(p.title for p in PROGRAMS if p.key == key)


def uninstall(choice: list[str], z: TargetUser) -> list[Result]:
    outputs = []
    for key in choice:
        try:
            with _as_user(z):
                text = _hook_off(z) if key == "hook" else next(p for p in PROGRAMS if p.key == key).outputs(z)
            outputs.append(Result(key, _title(key), True, text))
        except (Refused, OSError) as e:
            outputs.append(Result(key, _title(key), False, str(e)))
    return outputs


def setup(choice: list[str], z: TargetUser, url: str, token: str | None, signal: str | None = None, unchecked: bool = False) -> list[Result]:
    """Get tokens → ask the server → write. What could not be checked is not written."""
    tokens: dict[str, str] = {}
    if token:
        tokens = {k: token for k in choice}
    elif can_create_tokens(url):
        short = re.sub(r"[^A-Za-z0-9_.-]", "-", z.name)
        for k in choice:
            if k == "hook":
                continue
            tokens[k] = config.create_instance(f"{short}-{k}")
        if "hook" in choice:
            with _as_user(z):
                present = _claude_token(z)
            tokens["hook"] = tokens.get("claude") or present or config.create_instance(f"{short}-claude")
            signal = signal or config.create_instance(f"{short}-nutzer", human=True)
        if reason := _restart():
            return [Result(k, _title(k), False, f"service not restarted, nothing registered: {reason}") for k in choice]
        if not _wait(url):
            return [Result(k, _title(k), False, "server does not answer after the restart, nothing registered") for k in choice]
    elif "hook" in choice and len(choice) == 1 and (present := _token_from_claude(z)):
        tokens["hook"] = present
    elif unchecked or check(url, None)[0] == "offen":
        tokens = {k: "" for k in choice}  # open server: register without a token
    outputs = []
    for k in choice:
        t = tokens.get(k)
        if t is None:
            outputs.append(Result(k, _title(k), False, "no token: pass it with --token-file or run with sudo on the server"))
            continue
        if not unchecked:
            kind, text = check(url, t or None)
            if kind not in ("token_ok", "offen"):
                outputs.append(Result(k, _title(k), False, f"not registered: {text}"))
                continue
        try:
            with _as_user(z):
                text = _hook_on(z, url, t, signal) if k == "hook" else next(p for p in PROGRAMS if p.key == k).on(z, url, t)
            outputs.append(Result(k, _title(k), True, text))
        except (Refused, OSError) as e:
            outputs.append(Result(k, _title(k), False, str(e)))
    return outputs


# ---- Menu: state and rendering are pure, only _run talks to the terminal ----

@dataclass
class MenuLine:
    key: str
    title: str
    info: str
    selectable: bool
    to: bool


@dataclass
class Menu:
    username: str
    url: str
    token: str | None
    auto: bool
    server: tuple[str, str]
    statuses: list[SetupStatus] = field(default_factory=list)
    mode: str = "einrichten"
    lines: list[MenuLine] = field(default_factory=list)
    pos: int = 0
    notice: str = ""


def lines_for(statuses: list[SetupStatus], mode: str) -> list[MenuLine]:
    outputs = []
    for s in statuses:
        if mode == "einrichten":
            outputs.append(MenuLine(s.key, s.title, s.text, s.present != "fehlt", s.present != "fehlt" and not s.configured))
        else:
            outputs.append(MenuLine(s.key, s.title, s.text if s.configured else "nothing to remove: not set up", s.configured, False))
    return outputs


def obstacle(m: Menu) -> str | None:
    if not any(z.to for z in m.lines):
        return "nothing selected"
    if m.mode == "entfernen":
        return None
    kind, text = m.server
    if m.token:
        return None if kind == "token_ok" else f"server check failed: {text}"
    if m.auto or kind == "offen":
        return None
    if kind == "nicht_erreichbar":
        return f"server not reachable: {text}"
    return "no token: enter it with t or run with sudo on the server"


def _server_line(m: Menu) -> str:
    kind, text = m.server
    if m.auto and kind != "erreichbar":
        return "not running yet; starts once the tokens are created"
    return text


def record(m: Menu, width: int = 80, color: bool = True) -> str:
    def f(code: str, s: str) -> str:
        return f"\x1b[{code}m{s}\x1b[0m" if color else s

    def k(s: str) -> str:
        return s if len(s) <= width - 1 else s[:width - 2] + "…"
    good = m.server[0] in ("token_ok", "erreichbar", "offen") or m.auto
    tok = "entered" if m.token else "created per program" if m.auto else "not needed (open server)" if m.server[0] == "offen" else "missing"
    z = [f("1;36", k(f" vi-mcp setup  {__version__}")), "",
         k(f" User     {m.username}"), k(f" Server   {m.url}"), f("32" if good else "31", k(f"          {_server_line(m)}")),
         k(f" Token    {tok}"), k(f" Action   {MODE_LABEL[m.mode]}"), f("2", k(" " + "─" * min(width - 2, 70)))]
    for i, r in enumerate(m.lines):
        marker = "▸" if i == m.pos else " "
        checkbox = "[x]" if r.to else "[ ]" if r.selectable else "[-]"
        text = k(f" {marker} {checkbox} {r.title:17} {r.info}")
        z.append(f("7" if i == m.pos else "0", text) if r.selectable else f("2;7" if i == m.pos else "2", text))
    z.append(f("2", k(" " + "─" * min(width - 2, 70))))
    h = obstacle(m)
    z.append(f("2", k(f" Enter: blocked, {h}")) if h else f("1;32", k(f" Enter: {MODE_LABEL[m.mode]}")))
    z.append(k(" ↑↓ select · space on/off · u URL · t token · e action · q quit"))
    if m.notice:
        z += ["", f("33", k(f" {m.notice}"))]
    return "\r\n".join(z)


def keystroke(m: Menu, k: str) -> str | None:
    """Changes the state; returns url, token, los (go) or ende (end) when the loop must act."""
    m.notice = ""
    if k in ("hoch", "k"):
        m.pos = (m.pos - 1) % len(m.lines)
    elif k in ("runter", "j"):
        m.pos = (m.pos + 1) % len(m.lines)
    elif k == " ":
        z = m.lines[m.pos]
        if z.selectable:
            z.to = not z.to
        else:
            m.notice = f"{z.title}: {z.info}"
    elif k == "e":
        m.mode = "entfernen" if m.mode == "einrichten" else "einrichten"
        m.lines = lines_for(m.statuses, m.mode)
    elif k == "u":
        return "url"
    elif k == "t":
        return "token"
    elif k == "enter":
        h = obstacle(m)
        if h:
            m.notice = h
            return None
        return "los"
    elif k in ("q", "esc"):
        return "ende"
    return None


#: Menu modes (internal value → shown label)
MODE_LABEL = {"einrichten": "set up", "entfernen": "remove"}
KEYSTROKES = {b"\x1b[A": "hoch", b"\x1bOA": "hoch", b"\x1b[B": "runter", b"\x1bOB": "runter", b"\r": "enter", b"\n": "enter", b"\x1b": "esc"}


def _run(z: TargetUser, url: str, token: str | None, signal: str | None, idle: float | None) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("No terminal for the menu. Without the menu: vi-mcp setup --claude --url URL --token-file FILE", file=sys.stderr)
        return 2
    color = "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
    statuses = progress(z)
    m = Menu(z.name, url, token, not token and can_create_tokens(url), check(url, token), statuses, lines=lines_for(statuses, "einrichten"))
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    outputs = sys.stdout

    def image() -> None:
        outputs.write("\x1b[H\x1b[2J" + record(m, shutil.get_terminal_size((80, 24)).columns, color))
        outputs.flush()

    def line(prompt: str, hidden: bool) -> str | None:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        outputs.write("\x1b[?25h\r\n")
        outputs.flush()
        try:
            return (getpass.getpass(prompt) if hidden else input(prompt)).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        finally:
            _tty.setcbreak(fd)
            outputs.write("\x1b[?25l")
            outputs.flush()
    go = False
    try:
        _tty.setcbreak(fd)
        outputs.write("\x1b[?1049h\x1b[?25l")
        while True:
            image()
            ready, _, _ = select.select([fd], [], [], idle)
            if not ready:
                break
            raw = os.read(fd, 16)
            if not raw:
                break
            k = KEYSTROKES.get(raw, raw.decode("utf-8", "ignore"))
            r = keystroke(m, k)
            if r == "ende":
                break
            if r == "los":
                go = True
                break
            if r == "url" and (w := line(f" Server URL [{m.url}]: ", False)):
                m.url = w
            if r == "token" and (w := line(" Token (input hidden): ", True)):
                m.token = w
            if r in ("url", "token"):
                m.auto = not m.token and can_create_tokens(m.url)
                m.server = check(m.url, m.token)
    finally:
        outputs.write("\x1b[?25h\x1b[?1049l")
        outputs.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if not go:
        print(HINT)
        return 0
    choice = [r.key for r in m.lines if r.to]
    return _report(uninstall(choice, z) if m.mode == "entfernen" else setup(choice, z, m.url, m.token, signal))


def _report(results: list[Result]) -> int:
    for e in results:
        print(f"{'✓' if e.ok else '✗'} {e.title}: {e.text}")
    if any(e.ok for e in results):
        print("Restart running sessions of the configured programs so they see the server.")
    return 0 if all(e.ok for e in results) else 1


def _file(fpath: str | None) -> str | None:
    if fpath is None:
        return None
    value = sys.stdin.read() if fpath == "-" else Path(fpath).read_text()
    return value.strip() or None


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser(prog="vi-mcp setup", description="register vi-mcp in Claude Code, Codex CLI and Hermes Agent")
    for k in ("claude", "codex", "hermes", "hook"):
        a.add_argument(f"--{k}", action="store_true")
    a.add_argument("--url")
    a.add_argument("--token-file", "--token-datei", dest="token_file", help="file containing the token, - for standard input")
    a.add_argument("--signal-token-file", "--signal-token-datei", dest="signal_token_file",
                   help="token of an instance with the --human right, for the hook's correction detection")
    a.add_argument("--uninstall", "--entfernen", dest="uninstall", action="store_true")
    a.add_argument("--status", action="store_true")
    a.add_argument("--skip-check", "--ohne-pruefung", dest="skip_check", action="store_true",
                   help="register even if the server cannot confirm the token right now")
    a.add_argument("--idle", "--leerlauf", dest="idle", type=float, help="end the menu after this many seconds without a key press")
    o = a.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    z = target()
    if o.status:
        for s in progress(z):
            print(f"{s.title:18} {s.text}")
        return 0
    url = o.url or default_url(z)
    token, signal = _file(o.token_file), _file(o.signal_token_file)
    choice = [k for k in ("claude", "codex", "hermes", "hook") if getattr(o, k)]
    try:
        if not choice:
            if WINDOWS:
                print("The interactive menu needs a Unix terminal. On Windows: vi-mcp setup --claude --hook --url URL --token-file FILE "
                      "(see vi-mcp setup --help)", file=sys.stderr)
                return 2
            return _run(z, url, token, signal, o.idle)
        return _report(uninstall(choice, z) if o.uninstall else setup(choice, z, url, token, signal, o.skip_check))
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 130
