"""0.48.0: configuring the server after installation — one catalogue of questions, two front ends.

Decided by the user (11.11.2026): Debian gets real debconf (dialogs, `dpkg-reconfigure vi-mcp`, preseeding); RPM gets an own ANSI menu
(`vi-mcp configure`). Both ask at the first installation, and on an update only questions that were never answered. Settings: server
(port, addresses, access without a token), networks (the wiki network, a further network), web page and instances, language model,
reviewer and embedding.

  QUESTIONS        the catalogue: key, kind, default, choices, priority, check, current value
  apply()          applies answers — only what differs from the running configuration; restarts the service once if needed
  debconf_*()      the build writes DEBIAN/templates and DEBIAN/config from the catalogue; postinst hands the answers to `--apply-json`
  menu()           the ANSI menu (arrow keys, Enter, Esc), standard library only
  answered state   /etc/vi-mcp/configure.json {"beantwortet": [keys]} — what an update still has to ask

Unattended (as the Wazuh agent: WAZUH_MANAGER=… apt-get install …): every question has an environment variable VI_MCP_<KEY>, e.g.
  sudo VI_MCP_PORT=9000 VI_MCP_WIKI=false VI_MCP_INSTANCE=claude-code DEBIAN_FRONTEND=noninteractive apt-get install ./vi-mcp_….deb
  sudo VI_MCP_WEB=true VI_MCP_NET_NAME=company VI_MCP_NET_KIND=company VI_MCP_NET_START=vinetz1.… dnf install ./vi-mcp-….rpm
What is set is taken without asking (debconf marks it seen); what is not set is asked, or without a terminal takes its default.

Never shown, never stored in debconf: tokens. A new instance's token goes to TOKEN_DIR/vi-mcp-token-<name> (0600, root) and only the
path is named.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config

STATE = Path(os.environ.get("VI_MCP_CONFIGURE_STATE", "/etc/vi-mcp/configure.json"))
TOKEN_DIR = Path(os.environ.get("VI_MCP_TOKEN_DIR", "/root"))
SECTIONS = ("Server", "Networks", "Web page and instances", "Language model and embedding")


@dataclass
class Q:
    key: str
    section: str
    kind: str  # string | boolean | select
    title: str
    text: str
    default: str = ""
    choices: tuple = ()
    priority: str = "medium"  # debconf: high is asked at installation, medium/low by dpkg-reconfigure
    check: Callable[[str], str | None] = field(default=lambda v: None)
    once: bool = False  # an action, not a setting: reset after it ran (creating an instance, joining a network)

    @property
    def env(self) -> str:
        return "VI_MCP_" + self.key.upper()


def _port(v):
    return None if v.isdigit() and 1024 <= int(v) <= 65535 else "a number from 1024 to 65535"


def _addresses(v):
    import ipaddress
    try:
        for a in [x.strip() for x in v.split(",") if x.strip()]:
            ipaddress.ip_address(a)
    except ValueError:
        return "IP addresses separated by commas, e.g. 127.0.0.1 or 127.0.0.1,172.19.0.1"
    return None if v.strip() else "at least one address"


def _url_or_empty(v):
    return None if not v or re.fullmatch(r"https?://[^\s]+", v) else "empty or an http(s) URL"


def _name_or_empty(v):
    return None if not v or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,40}", v) else "letters, digits, . _ - (or empty)"


def _net_name_or_empty(v):
    return None if not v or (re.fullmatch(r"[a-z][a-z0-9-]{1,30}", v) and v not in ("standard", "config", "wiki")) else "a-z, 0-9, - (not standard, config, wiki) or empty"


def _path_or_empty(v):
    return None if not v or v.startswith("/") else "an absolute path or empty"


def _base(v):
    return None if re.fullmatch(r"(/[A-Za-z0-9._-]+)+", v or "") else "a path like /web or /vi-mcp/web"


def _db(v):
    if not v:
        return None
    if not re.fullmatch(r"postgres(ql)?://\S+", v):
        return "empty (SQLite file) or a postgresql:// URL"
    if re.search(r"://[^/@:]+:[^@]*@", v):
        return "no password in the URL — ~/.pgpass of the service user, PGPASSFILE or peer authentication over the socket"
    return None


def _start(v):
    return None if not v or v.startswith("vinetz1.") or re.fullmatch(r"https?://[^\s]+", v) else "empty, an https:// address or a join code vinetz1.…"


QUESTIONS = [
    Q("port", "Server", "string", "Port of the VI server", "The port the server listens on (HTTP; TLS comes from the reverse proxy).", "8765", priority="high", check=_port),
    Q("bind", "Server", "string", "Addresses the server listens on",
      "Comma-separated. 127.0.0.1 = this machine only. Add the gateway of a Docker network if nginx runs in a container.", "127.0.0.1", check=_addresses),
    Q("db", "Server", "string", "Database (empty = SQLite file)",
      "Empty: the SQLite file (default, no server needed). Or a PostgreSQL URL, e.g. postgresql://vi-mcp@/vi-mcp?host=/var/run/postgresql — "
      "needs python3-psycopg; move the data first with vi-mcp db migrate --to URL (an empty database is refused).", "", check=_db),
    Q("open", "Server", "boolean", "Access without a token (open wiki mode)",
      "Anyone who reaches the server may read shared knowledge and propose new knowledge (which goes into quarantine). Internal knowledge "
      "always needs a token.", "false"),
    Q("wiki", "Networks", "boolean", "Join the public wiki network vi-wiki.org",
      "Proven, shared knowledge leaves this server anonymised; reviewed knowledge, wiki pages and questions of other servers come in. "
      "Outgoing connections only. The AI tells its users and can switch it off (vi_net_switch).", "true", priority="high"),
    Q("net_name", "Networks", "string", "A further network: name (empty = none)",
      "E.g. company for a company network. Leave empty to skip.", "", check=_net_name_or_empty, once=True),
    Q("net_kind", "Networks", "select", "A further network: kind",
      "free = anyone may join, anonymised · open = by invitation, anonymised · company = by invitation, internal knowledge, one organisation.",
      "company", choices=("free", "open", "company"), once=True),
    Q("net_mode", "Networks", "select", "A further network: mode",
      "peer = outgoing only (behind a firewall) · peerhost = also reachable by others.", "peer", choices=("peer", "peerhost"), once=True),
    Q("net_public", "Networks", "string", "A further network: public address (peerhost, empty = none)",
      "https://HOST — the network is then reachable as https://HOST/vi-p2p/<name> on 443 behind the reverse proxy.", "", check=_url_or_empty, once=True),
    Q("net_start", "Networks", "string", "A further network: start address or join code",
      "Free network: the address of one of its servers. Closed network: the join code (vinetz1.…). Empty with peerhost = found a new network.",
      "", check=_start, once=True),
    Q("web", "Web page and instances", "boolean", "Read-only web page of the free and open networks",
      "Search, wiki, forum and knowledge of the free and open networks under /web — never company networks or internal knowledge.", "false", priority="high"),
    Q("web_base", "Web page and instances", "string", "Path of the web page as the browser sees it",
      "/web, or /vi-mcp/web if it goes through the existing /vi-mcp/ location of the reverse proxy.", "/web", check=_base),
    Q("instance", "Web page and instances", "string", "Create an instance (empty = none)",
      "A name for an AI client or a person, e.g. claude-code or max. The token is written to /root/vi-mcp-token-<name> (only root reads it) "
      "and never shown here.", "", priority="high", check=_name_or_empty, once=True),
    Q("instance_family", "Web page and instances", "select", "Model family of the new instance",
      "Confirmations by the same model family count as one independent line.", "undeclared", choices=("undeclared", "claude", "gpt", "qwen", "gemini", "other"), once=True),
    Q("llm_url", "Language model and embedding", "string", "URL of the language model (empty = none)",
      "OpenAI-compatible chat endpoint for sleep and the reviewer, e.g. http://127.0.0.1:8080/v1/chat/completions.", "", check=_url_or_empty),
    Q("llm_model", "Language model and embedding", "string", "Model name for the language model (empty = server default)", "", ""),
    Q("reviewer_prompt", "Language model and embedding", "string", "Reviewer prompt file (empty = none)",
      "Absolute path of the prompt the reviewer uses for foreign content; without it imports wait for a person.", "", check=_path_or_empty),
    Q("embed_url", "Language model and embedding", "string", "URL of the embedding service (empty = none)",
      "OpenAI-compatible /v1/embeddings for the semantic search.", "", check=_url_or_empty),
]
BY_KEY = {q.key: q for q in QUESTIONS}


# ---- current values from the running configuration ----

def current() -> dict[str, str]:
    p = config.fpath()
    raw = config.read_raw(p)
    b = raw.get("bind", "127.0.0.1")
    wiki = _net_dir() / "wiki.json"
    db = str(raw.get("db") or "")
    return {"port": str(raw.get("port", 8765)), "bind": ",".join([b] if isinstance(b, str) else b), "open": _b(raw.get("open", False)),
            "db": db if db.startswith(("postgresql://", "postgres://")) else "",
            "wiki": _b(wiki.exists()), "web": _b(raw.get("web", False)), "web_base": raw.get("web_base") or "/web",
            "llm_url": (raw.get("llm") or {}).get("url", ""), "llm_model": (raw.get("llm") or {}).get("model", ""),
            "reviewer_prompt": raw.get("reviewer_prompt") or "", "embed_url": (raw.get("embed") or {}).get("url", ""),
            **{q.key: q.default for q in QUESTIONS if q.once}}


def _net_dir() -> Path:
    from . import net_service
    return net_service.etc_dir()


def _b(v) -> str:
    return "true" if v else "false"


def answered() -> set[str]:
    try:
        return set(json.loads(STATE.read_text()).get("beantwortet") or [])
    except (OSError, ValueError):
        return set()


def mark_answered(keys) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"beantwortet": sorted(answered() | set(keys))}, indent=1) + "\n")


def unanswered() -> list[Q]:
    done = answered()
    return [q for q in QUESTIONS if q.key not in done]


TRUE, FALSE = ("1", "true", "yes", "on", "ja", "y"), ("0", "false", "no", "off", "nein", "n")


def env_answers(environ=None) -> dict[str, str]:
    """Answers from VI_MCP_<KEY> (unattended installation). Booleans accept 1/0, true/false, yes/no, on/off, ja/nein.
    VI_MCP_KEIN_WIKI (0.47.0) still means VI_MCP_WIKI=false."""
    env = os.environ if environ is None else environ
    out = {}
    for q in QUESTIONS:
        if q.env in env:
            v = str(env[q.env]).strip()
            if q.kind == "boolean":
                v = "true" if v.lower() in TRUE else "false" if v.lower() in FALSE else v
            if q.key == "net_kind":
                v = config.net_kind(v.lower())  # 0.51.0: frei/offen/firma still mean free/open/company
            out[q.key] = v
    if env.get("VI_MCP_KEIN_WIKI") and "wiki" not in out:
        out["wiki"] = "false"
    return out


def validate(answers: dict[str, str]) -> dict[str, str]:
    """key → reason, for every answer that does not fit."""
    out = {}
    for k, v in answers.items():
        q = BY_KEY.get(k)
        if not q:
            out[k] = "unknown setting"
        elif q.kind == "boolean" and v not in ("true", "false"):
            out[k] = "true or false"
        elif q.kind == "select" and v not in q.choices:
            out[k] = " or ".join(q.choices)
        elif q.kind == "string" and (reason := q.check(v.strip())):
            out[k] = reason
    return out


# ---- applying ----

def _db_target_not_ready(url: str, raw: dict) -> str | None:
    """Switching to PostgreSQL only onto data: the target must hold at least as many objects as the SQLite file (vi-mcp db migrate)."""
    import sqlite3
    from . import db as dbmod
    src = Path(str(raw.get("db") or config.Config().db)).expanduser()
    try:
        con = dbmod.connect(url)
    except Exception as exc:  # noqa: BLE001 — every reason is named
        return f"PostgreSQL not reachable ({type(exc).__name__}: {str(exc).splitlines()[0][:160]})"
    try:
        has = con.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'objekt'").fetchone()
        target = con.execute("SELECT COUNT(*) FROM objekt").fetchone()[0] if has else 0
    finally:
        con.close()
    if not src.exists():
        return None  # a new installation: nothing to move
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        source = s.execute("SELECT COUNT(*) FROM objekt").fetchone()[0]
    except sqlite3.Error:
        source = 0
    finally:
        s.close()
    if target < source:
        return f"the PostgreSQL database holds {target} objects, the SQLite file {source} — run vi-mcp db migrate --to URL first"
    return None


def migrate_configs() -> list[str]:
    """0.51.0, at every package install/update: rewrite configuration files that still use German keys or network kinds in English.
    A copy of each old file stays next to it (<file>.bak-<time>-german-keys). Returns one line per rewritten file."""
    import time
    from . import net_cli, net_service as nd
    out = []
    notes = config.migrate_file()
    if notes:
        out.append(f"{config.fpath()}: keys in English ({len(notes)} renamed: {', '.join(notes[:6])}{' …' if len(notes) > 6 else ''})")
    d = _net_dir()
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            old = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        new = nd.english_file(old)
        if new != old:
            backup = f.with_name(f"{f.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}-german-keys")
            backup.write_bytes(f.read_bytes())
            os.chmod(backup, os.stat(f).st_mode & 0o777)
            net_cli._write(f, new)
            out.append(f"{f}: keys in English")
    return out


def apply(answers: dict[str, str], restart: bool = True) -> list[str]:
    """Apply answers; only what differs from the running configuration. Returns what was done (for the screen and the log)."""
    answers = {k: str(v).strip() for k, v in answers.items() if k in BY_KEY}
    if "net_kind" in answers:
        answers["net_kind"] = config.net_kind(answers["net_kind"])  # 0.51.0: German kinds of older answers and debconf databases
    bad = validate(answers)
    if bad:
        raise ValueError("; ".join(f"{k}: {r}" for k, r in bad.items()))
    cur = current()
    done, need_restart = [], False
    p = config.fpath()
    raw = config.read_raw(p)
    changed_raw = False

    def setraw(key, value, label):
        nonlocal changed_raw, need_restart
        if raw.get(key) != value:
            raw[key] = value
            changed_raw = need_restart = True
            done.append(label)

    if "port" in answers and answers["port"] != cur["port"]:
        setraw("port", int(answers["port"]), f"port {cur['port']} → {answers['port']}")
    if "bind" in answers and answers["bind"] != cur["bind"]:
        addrs = [a.strip() for a in answers["bind"].split(",") if a.strip()]
        setraw("bind", addrs[0] if len(addrs) == 1 else addrs, f"addresses → {', '.join(addrs)}")
    if "db" in answers and answers["db"] != cur["db"]:  # 0.50.0
        if answers["db"]:
            why = _db_target_not_ready(answers["db"], raw)
            if why:
                raise ValueError(f"db: {why}")
            setraw("db", answers["db"], "database → PostgreSQL")
        else:
            raw.pop("db", None)
            changed_raw = need_restart = True
            done.append("database → SQLite file (its content is as old as the last migration)")
    if "open" in answers and answers["open"] != cur["open"]:
        setraw("open", answers["open"] == "true", f"access without a token {'on' if answers['open'] == 'true' else 'off'}")
    if "web" in answers and answers["web"] != cur["web"]:
        setraw("web", answers["web"] == "true", f"web page {'on' if answers['web'] == 'true' else 'off'}")
    if "web_base" in answers and answers["web_base"].rstrip("/") != cur["web_base"]:
        setraw("web_base", answers["web_base"].rstrip("/"), f"web page path → {answers['web_base']}")
    for key, section, label in (("llm_url", "llm", "language model"), ("embed_url", "embed", "embedding service")):
        if key in answers and answers[key] != cur[key]:
            if answers[key]:
                setraw(section, {**(raw.get(section) or {}), "url": answers[key]}, f"{label} → {answers[key]}")
            elif raw.get(section):
                raw.pop(section)
                changed_raw = need_restart = True
                done.append(f"{label} removed")
    if "llm_model" in answers and answers["llm_model"] != cur["llm_model"] and (raw.get("llm") or answers.get("llm_url")):
        llm = dict(raw.get("llm") or {})
        if answers["llm_model"]:
            llm["model"] = answers["llm_model"]
        else:
            llm.pop("model", None)
        setraw("llm", llm, f"model name → {answers['llm_model'] or 'server default'}")
    if "reviewer_prompt" in answers and answers["reviewer_prompt"] != cur["reviewer_prompt"]:
        if answers["reviewer_prompt"]:
            setraw("reviewer_prompt", answers["reviewer_prompt"], f"reviewer prompt → {answers['reviewer_prompt']}")
        elif "reviewer_prompt" in raw:
            raw.pop("reviewer_prompt")
            changed_raw = need_restart = True
            done.append("reviewer prompt removed")
    if changed_raw:
        config._save_raw(raw, p)
    if answers.get("instance"):
        name = answers["instance"]
        if name in (raw.get("instances") or {}):
            done.append(f"instance {name} exists — not renewed here (a new token would lock its clients out: vi-mcp instance {name})")
        else:
            token = config.create_instance(name)
            if answers.get("instance_family", "undeclared") not in ("undeclared", "other"):
                r2 = config.read_raw(p)
                r2["instances"][name]["family"] = answers["instance_family"]
                config._save_raw(r2, p)
            tf = TOKEN_DIR / f"vi-mcp-token-{name}"
            fd = os.open(tf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(token + "\n")
            need_restart = True
            done.append(f"instance {name} created — its token is in {tf} (only root reads it; hand it over safely, then delete the file)")
    from . import net_cli
    if "wiki" in answers and answers["wiki"] != cur["wiki"]:
        if (os.environ.get("VI_MCP_KEIN_WIKI") or str(os.environ.get("VI_MCP_WIKI", "")).lower() in FALSE) and answers["wiki"] == "true":
            done.append("wiki network not joined (VI_MCP_WIKI=false)")
        else:
            code = net_cli.main(["wiki", "on" if answers["wiki"] == "true" else "off"])
            done.append(f"wiki network {'joined' if answers['wiki'] == 'true' else 'left'}" + ("" if code == 0 else f" — failed (exit {code})"))
    if answers.get("net_name"):
        n, kind, mode = answers["net_name"], answers.get("net_kind", "company"), answers.get("net_mode", "peer")
        start, public = answers.get("net_start", ""), answers.get("net_public", "")
        if start.startswith("vinetz1."):
            argv = ["--network", n, "join", start, "--mode", mode, "--kind", kind] + (["--public", public] if public else [])
        else:
            argv = ["--network", n, "setup", "--kind", kind, "--mode", mode] + (["--public", public] if public else []) + (["--start", start] if start else [])
            if not start and kind != "free":
                argv.append("--found")
        code = net_cli.main(argv)
        done.append(f"network {n} ({kind}, {mode}) " + ("set up" if code == 0 else f"— setup failed (exit {code})"))
    if restart and need_restart:
        from . import setup
        reason = setup._restart()
        done.append("service restarted" if not reason else f"service not restarted: {reason}")
    mark_answered(answers)
    return done or ["nothing changed"]


# ---- debconf (Debian) ----

def debconf_templates() -> str:
    """DEBIAN/templates. Descriptions: a short line and the long text; English like every user-facing text."""
    out = []
    for q in QUESTIONS:
        t = {"string": "string", "boolean": "boolean", "select": "select"}[q.kind]
        out.append(f"Template: vi-mcp/{q.key}\nType: {t}\n" + (f"Choices: {', '.join(q.choices)}\n" if q.choices else "")
                   + f"Default: {q.default}\nDescription: {q.title}\n " + (q.text or q.title).replace("\n", "\n ") + "\n")
    return "\n".join(out)


def debconf_config() -> str:
    """DEBIAN/config: ask through debconf. If the package is already installed, the current values become the defaults first (as postfix
    reads main.cf) — so a dialog never offers a value the server no longer has. On an update the wiki network is not joined by default."""
    lines = ["#!/bin/sh", "# generated from vi_mcp/configure.py (QUESTIONS) — do not edit", "set -e", ". /usr/share/debconf/confmodule",
             'if [ -x /usr/bin/vi-mcp ] && [ -e /etc/vi-mcp/config.json ]; then',
             # not through a pipe: debconf reads its answers from stdin, a piped loop would feed it our lines (found by the container test,
             # 11.11.2026: "return: Illegal number: bind" on dpkg-reconfigure) — the values come on fd 4 from a file
             '    _cur=$(mktemp); /usr/bin/vi-mcp configure --debconf-current 2>/dev/null >"$_cur" || true',
             '    while read -r key value <&4; do db_set "vi-mcp/$key" "$value" || true; done 4<"$_cur"; rm -f "$_cur"',
             "fi",
             '# an update from before 0.48.0: the server is configured already — ask only questions later versions add',
             'if [ -n "$2" ] && [ ! -e /etc/vi-mcp/configure.json ] && [ -e /etc/vi-mcp/config.json ]; then',
             "    for k in " + " ".join(q.key for q in QUESTIONS) + "; do db_fset \"vi-mcp/$k\" seen true || true; done",
             "fi",
             "# unattended (like WAZUH_MANAGER=…): a VI_MCP_<KEY> in the environment is the answer and is not asked",
             "norm() { case \"$1\" in 1|[Tt]rue|[Yy]es|[Oo]n|[Jj]a|[Yy]) echo true ;; 0|[Ff]alse|[Nn]o|[Oo]ff|[Nn]ein|[Nn]) echo false ;; *) echo \"$1\" ;; esac; }"]
    for q in QUESTIONS:
        val = f'"$(norm "${q.env}")"' if q.kind == "boolean" else f'"${q.env}"'
        lines.append(f'if [ -n "${{{q.env}+x}}" ]; then db_set vi-mcp/{q.key} {val}; db_fset vi-mcp/{q.key} seen true; fi')
    lines.append('if [ -n "${VI_MCP_KEIN_WIKI:-}" ]; then db_set vi-mcp/wiki false; db_fset vi-mcp/wiki seen true; fi')
    lines += [
             'if [ -n "$2" ] && [ ! -e /etc/vi-p2p/wiki.json ] && [ -z "${VI_MCP_WIKI+x}" ]; then',
             '    # an update: never join the wiki network by default (decided by the user); a dialog may still say yes',
             '    db_fget vi-mcp/wiki seen || true',
             '    if [ "$RET" = "false" ]; then db_set vi-mcp/wiki false; fi',
             "fi"]
    for sec in SECTIONS:
        for q in QUESTIONS:
            if q.section == sec:
                lines.append(f"db_input {q.priority} vi-mcp/{q.key} || true")
        lines.append("db_go || true")
    return "\n".join(lines) + "\nexit 0\n"


def debconf_answers(pairs: dict[str, str]) -> dict[str, str]:
    """What postinst read with db_get → answers; a further network/instance only when named."""
    a = {k: v for k, v in pairs.items() if k in BY_KEY}
    if not a.get("net_name"):
        for k in ("net_name", "net_kind", "net_mode", "net_public", "net_start"):
            a.pop(k, None)
    if not a.get("instance"):
        a.pop("instance", None)
        a.pop("instance_family", None)
    return a


# ---- ANSI menu (RPM, and `vi-mcp configure` everywhere) ----

def render(values: dict[str, str], cursor: int, items: list, width: int = 80, msg: str = "") -> str:
    out = ["\x1b[1mvi-mcp — configure\x1b[0m   ↑/↓ choose · Enter change · a apply · Esc leave without changes", ""]
    sec = None
    for i, q in enumerate(items):
        if q is None:
            out.append("")
            out.append(("\x1b[7m" if i == cursor else "") + "  [ Apply ]" + ("\x1b[0m" if i == cursor else ""))
            continue
        if q.section != sec:
            sec = q.section
            out.append(f"\x1b[1m{sec}\x1b[0m")
        v = values.get(q.key, "")
        shown = ("yes" if v == "true" else "no") if q.kind == "boolean" else (v or "—")
        line = f"  {q.title[:max(20, width - 30)]:<{max(20, width - 30)}} {shown}"[:width - 1]
        out.append(("\x1b[7m" + line + "\x1b[0m") if i == cursor else line)
    cur = items[cursor]
    out += ["", (cur.text[:width * 3] if cur else "Apply the settings above (changes only)."), "", msg]
    return "\n".join(out)


def step(values: dict[str, str], items: list, cursor: int, key: str, read_line=None) -> tuple[int, str | None]:
    """Pure apart from read_line. Returns (cursor, action) — action None, 'apply' or 'quit'."""
    if key == "up":
        return max(0, cursor - 1), None
    if key == "down":
        return min(len(items) - 1, cursor + 1), None
    if key in ("esc", "q"):
        return cursor, "quit"
    if key == "a":
        return cursor, "apply"
    if key == "enter":
        q = items[cursor]
        if q is None:
            return cursor, "apply"
        if q.kind == "boolean":
            values[q.key] = "false" if values.get(q.key) == "true" else "true"
        elif q.kind == "select":
            i = q.choices.index(values.get(q.key, q.default)) if values.get(q.key, q.default) in q.choices else -1
            values[q.key] = q.choices[(i + 1) % len(q.choices)]
        elif read_line:
            v = read_line(f"{q.title} [{values.get(q.key, '')}]: ")
            if v is not None:
                values[q.key] = v.strip()
    return cursor, None


def menu(only_new: bool = False) -> int:
    import shutil
    import termios
    import tty as _tty
    items = [q for q in (unanswered() if only_new else QUESTIONS)]
    if not items:
        return 0
    if not sys.stdin.isatty():
        print("vi-mcp configure: no terminal — the defaults stay; later: sudo vi-mcp configure")
        return 0
    values = current()
    items = items + [None]
    cursor, msg = 0, ""
    fd, out = sys.stdin.fileno(), sys.stdout
    old = termios.tcgetattr(fd)
    keys = {b"\x1b[A": "up", b"\x1bOA": "up", b"\x1b[B": "down", b"\x1bOB": "down", b"\r": "enter", b"\n": "enter", b"\x1b": "esc", b"a": "a", b"q": "q"}

    def read_line(prompt):
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.write("\x1b[?25h\r\n" + prompt)
        out.flush()
        try:
            return sys.stdin.readline().rstrip("\n")
        finally:
            _tty.setraw(fd)
            out.write("\x1b[?25l")
    out.write("\x1b[?1049h\x1b[?25l")
    try:
        _tty.setraw(fd)
        while True:
            out.write("\x1b[H\x1b[2J" + render(values, cursor, items, shutil.get_terminal_size((80, 24)).columns, msg).replace("\n", "\r\n"))
            out.flush()
            k = keys.get(os.read(fd, 8))
            if not k:
                continue
            cursor, action = step(values, items, cursor, k, read_line)
            if action == "quit":
                return 1
            if action == "apply":
                ask = {q.key: values.get(q.key, q.default) for q in items if q is not None}
                bad = validate({k2: v for k2, v in ask.items()})
                if bad:
                    msg = "Not applied: " + "; ".join(f"{BY_KEY[k2].title}: {r}" for k2, r in bad.items())
                    continue
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                out.write("\x1b[?25h\x1b[?1049l")
                for line in apply(ask):
                    print(f"vi-mcp configure: {line}")
                return 0
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.write("\x1b[?25h\x1b[?1049l")


def main(argv: list[str]) -> int:
    """vi-mcp configure [--new] | --set KEY=VALUE … | --apply-json FILE | --defaults | --debconf-templates | --debconf-config | --debconf-current"""
    if argv[:1] == ["--debconf-templates"]:
        print(debconf_templates(), end="")
        return 0
    if argv[:1] == ["--debconf-config"]:
        print(debconf_config(), end="")
        return 0
    if argv[:1] == ["--debconf-current"]:
        for k, v in current().items():
            if not BY_KEY[k].once:
                print(f"{k} {v}")
        return 0
    if argv[:1] in (["--apply-pairs"], ["--package"]):  # 0.51.0: package install/update — older German config files → English first
        for line in migrate_configs():
            print(f"vi-mcp configure: {line}")
    if argv[:1] == ["--apply-pairs"] and len(argv) == 2:  # postinst: "key value" per line from db_get (no JSON quoting in shell)
        pairs = {}
        for line in Path(argv[1]).read_text().splitlines():
            k, _, v = line.partition(" ")
            if k:
                pairs[k] = v
        argv = ["--apply-json", "-"]
        pairs_given = pairs
    else:
        pairs_given = None
    if argv[:1] == ["--apply-json"] and len(argv) == 2:
        pairs = pairs_given if pairs_given is not None else json.loads(Path(argv[1]).read_text())
        try:
            for line in apply(debconf_answers(pairs)):
                print(f"vi-mcp configure: {line}")
        except ValueError as e:
            print(f"vi-mcp configure: not applied — {e}", file=sys.stderr)
            return 2
        return 0
    if argv[:1] == ["--set"]:
        pairs = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
        try:
            for line in apply(pairs):
                print(line)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        return 0
    if argv[:1] == ["--env"]:  # RPM (and anyone): take VI_MCP_<KEY> from the environment
        given = env_answers()
        if given:
            try:
                for line in apply(given):
                    print(f"vi-mcp configure: {line}")
            except ValueError as e:
                print(f"vi-mcp configure: not applied — {e}", file=sys.stderr)
                return 2
        return 0
    if argv[:1] == ["--package"]:  # RPM %posttrans: --package first|upgrade
        first = argv[1:2] == ["first"]
        if not first and not STATE.exists() and config.fpath().exists():
            mark_answered(q.key for q in QUESTIONS)  # configured before 0.48.0: only later questions are new
        main(["--env"])
        if sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get("VI_MCP_KEIN_MENUE"):
            return menu(only_new=True)
        rest = {q.key: q.default for q in unanswered() if not q.once}
        if not first:
            rest.pop("wiki", None)  # an update never joins the wiki network by default
        if rest:
            for line in apply(rest):
                print(f"vi-mcp configure: {line}")
        return 0
    if argv[:1] == ["--defaults"]:  # unattended first installation without a terminal: the defaults of what was never answered
        new = {q.key: q.default for q in unanswered() if not q.once}
        for line in apply(new):
            print(f"vi-mcp configure: {line}")
        return 0
    return menu(only_new="--new" in argv)
