"""Sessions and conversations — the time slice.

One server process, many clients. Every MCP session (header `Mcp-Session-Id`, assigned at `initialize`) is a
conversation with serial number YYYYMMDDNNN: its own context (history of turns), tagged, stored compressed
(zlib in `conversation_raw`), full-text searchable via the conversation object.

States of a session (exhaustive): `offen` (requests arrive), `beendet` (client sent DELETE),
`abgelaufen` (longer than `IDLE_S` without a request), `unterbrochen` (server was stopped while it was
open). Everything except `offen` is saved and removed from memory; a request with its id gets 404
(client must re-initialize, MCP spec).
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import secrets
import sqlite3
import threading
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import memory as g, names

IDLE_S = 4 * 3600


@dataclass
class Session:
    id: str
    serial: str
    instance: str
    client: str
    started_at: float = field(default_factory=time.monotonic)
    last_at: float = field(default_factory=time.monotonic)
    turns: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    secured_until: int = 0
    actions: int = 0
    signals: list = field(default_factory=list)  # the user's corrections and grades, without their text
    project: str | None = None  # 0.24.0: name of the client's working directory (hook: clientInfo.cwd), for statistics per project
    shown: dict = field(default_factory=dict)  # 0.24.0: hint id → monotonic time last shown in this conversation (no repetition)
    family: str | None = None  # 0.34.0: model family announced by the client (header X-VI-Family) or recognised from its name

    def turn(self, z: dict) -> None:
        with self.lock:
            self.turns.append(z)


_sessions: dict[str, Session] = {}
_reg_lock = threading.Lock()
_current: contextvars.ContextVar[Session | None] = contextvars.ContextVar("aktuelle_sitzung", default=None)


def current() -> Session | None:
    return _current.get()


@contextlib.contextmanager
def on_behalf(s: Session | None):
    """For the duration of a request: objects belong to this conversation, turns go into its history."""
    t1 = _current.set(s)
    t2 = g.current_conversation.set(s.serial if s else None)
    t3 = g.current_instance.set(s.instance if s else None)
    from . import indexes  # 0.61.0: what this session creates lands in its project's index
    t4 = g.current_index.set(indexes.from_project(s.project) if s is not None and s.project else None)
    try:
        yield s
    finally:
        g.current_index.reset(t4)
        g.current_instance.reset(t3)
        g.current_conversation.reset(t2)
        _current.reset(t1)


#: 0.61.0: instance → (time, project) of the last vi_context call of a hook session. The agent's own MCP session does not know its working
#: directory; the hook calls vi_context right before vi_learn/vi_recall, so the call that follows within seconds is from that project.
#: Limit, named: two sessions of the same instance in different projects learning within RECENT_S could be swapped.
_recent: dict[str, tuple[float, str]] = {}
RECENT_S = 15.0


def note_project(instance: str, project: str) -> None:
    import time
    _recent[instance] = (time.monotonic(), project)


def recent_project(instance: str, within_s: float = RECENT_S) -> str | None:
    import time
    t, p = _recent.get(instance, (0.0, None))
    return p if p and time.monotonic() - t <= within_s else None


# ── Pairing: the agent's own MCP conversation and its hook's conversation (0.66.0) ───────────────────────────────────────────
#: A Claude Code session talks to vi-mcp twice: the agent's MCP client (the conversation named in the instructions) and the hook
#: (vi_before/vi_after/vi_prompt_context, its own conversation). Questions between conversations of one instance need to know that both
#: are the same asker — otherwise a question would be delivered to its own author through the author's hook. The hook announces every
#: tool call of the agent in vi_before, with the same arguments, a moment before the agent's MCP client sends it; the first call of the
#: agent conversation whose fingerprint matches exactly one recent announcement pairs the two. Evidence, not timing alone: the
#: fingerprint covers tool and arguments. Two hooks announcing the same fingerprint inside the window: not paired, counted.
ANNOUNCE_S = 60.0
_announced: dict[str, list[tuple[float, str, str]]] = {}  # instance → [(monotonic time, fingerprint, hook serial)]
_agent_of: dict[str, str] = {}  # hook serial → agent serial
_hook_of: dict[str, str] = {}  # agent serial → hook serial
pairing_counts = {"gekoppelt": 0, "mehrdeutig": 0}
_announcers: set[str] = set()


def fingerprint(tool: str, args: dict) -> str:
    """Tool and arguments as the hook passes them on (it masks and cuts strings at 2000 characters): strings by their first 80
    characters, whitespace normalised. Pure."""
    import hashlib

    def norm(v):
        if isinstance(v, str):
            return " ".join(v.split())[:80]
        if isinstance(v, dict):
            return {str(k): norm(x) for k, x in sorted(v.items())}
        if isinstance(v, list):
            return [norm(x) for x in v[:50]]
        return v
    return hashlib.sha256(json.dumps([tool, norm(args or {})], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:24]


def announce(instance: str, hook_serial: str, tool: str, args: dict) -> None:
    now = time.monotonic()
    with _reg_lock:
        items = [x for x in _announced.get(instance, []) if now - x[0] <= ANNOUNCE_S]
        items.append((now, fingerprint(tool, args), hook_serial))
        _announced[instance] = items[-200:]
        _announcers.add(hook_serial)


def pair_on_call(instance: str, agent_serial: str, tool: str, args: dict) -> str | None:
    """Called for every tool call of a conversation that is not a hook's: pair it with the hook that announced exactly this call."""
    if agent_serial in _hook_of or agent_serial in _agent_of or agent_serial in _announcers:
        return _hook_of.get(agent_serial)  # a conversation that announces calls is a hook, never an agent
    fp, now = fingerprint(tool, args), time.monotonic()
    with _reg_lock:
        hooks = {h for t, f, h in _announced.get(instance, []) if f == fp and now - t <= ANNOUNCE_S and h != agent_serial
                 and h not in _agent_of}
        if len(hooks) != 1:
            if len(hooks) > 1:
                pairing_counts["mehrdeutig"] += 1
            return None
        hook = hooks.pop()
        _agent_of[hook], _hook_of[agent_serial] = agent_serial, hook
        pairing_counts["gekoppelt"] += 1
    for mine, other, role in ((agent_serial, hook, "hook"), (hook, agent_serial, "agent")):
        try:
            note = {"partner": other, "partner_rolle": role,
                    "partner_grund": f"the hook announced {tool} with the same arguments before the agent sent it"}
            g.update_data(g.keyed_id("conversation", mine), lambda d, note=note: d.update(note))
            with g.lock:
                g.db().commit()
        except Exception:  # noqa: BLE001 — the pairing holds in memory; the note on the conversation object is only its explanation
            pass
    return hook


def pairing_of(serial: str | None) -> str | None:
    """The paired conversation (the agent's hook, or the hook's agent), or None."""
    return (_hook_of.get(serial) or _agent_of.get(serial)) if serial else None


def canonical(serial: str | None) -> str | None:
    """The conversation that speaks for an asker: a hook's conversation stands for its agent's, once paired."""
    return _agent_of.get(serial, serial) if serial else None


def is_open(serial: str | None) -> bool:
    """Is this (canonical) conversation still reachable — its own session or its paired hook's session open?"""
    if not serial:
        return False
    alive = {s.serial for s in open_items()}
    return serial in alive or _hook_of.get(serial) in alive


def new_serial() -> str:
    """Highest number of the day + 1, compared numerically (also beyond 999), with INSERT as the lock."""
    tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefixes = names.ids("conversation", tag)  # 0.67.0: today's serials may already exist under the German prefix of 0.66
    for _ in range(50):
        with g.lock:
            n = max(g.db().execute("SELECT max(CAST(substr(id, ?) AS INTEGER)) FROM object WHERE kind = 'conversation' AND id LIKE ?",
                                   (len(p) + 1, f"{p}%")).fetchone()[0] or 0 for p in prefixes)
            serial = f"{tag}{n + 1:03d}"
            try:
                # every value named: a database migrated from 0.66 keeps its German column defaults (mode 'aktiv', visibility
                # 'geteilt' — SQLite's RENAME COLUMN does not change them), and a stub left by a process that died before begin()
                # saved the object stayed German until the next start renamed it (24.11.2026, 22 + 22 values after a hang)
                g.db().execute("INSERT INTO object (id, kind, ts, last_at, mode, visibility) VALUES (?, 'conversation', ?, ?, 'active', ?)",
                               (names.new_id("conversation", serial), g.now(), g.now(), g.VISIBILITY_PER_KIND["conversation"]))
                g.db().commit()
                return serial
            except sqlite3.IntegrityError:
                g.db().rollback()
                continue
    raise RuntimeError("no free conversation serial number after 50 attempts")


def begin(instance: str, client: str, project: str | None = None, family: str | None = None, family_source: str | None = None) -> Session:
    serial = new_serial()
    tag = serial[:8]
    g.new_object("conversation", f"Conversation {serial} started ({client}, instance {instance})",
                   [f"serial:{serial}", f"tag:{tag}"],
                   {"serial": serial, "calls": 0, "client": client, **({"project": project} if project else {}),
                    **({"family": family, "family_source": family_source} if family else {})},
                   oid=names.new_id("conversation", serial), reason="session started", conversation=serial, instance=instance)
    s = Session(id=secrets.token_urlsafe(24), serial=serial, instance=instance, client=client, project=project, family=family)
    with _reg_lock:
        _sessions[s.id] = s
    return s


def find(session_id: str | None) -> Session | None:
    if not session_id:
        return None
    with _reg_lock:
        s = _sessions.get(session_id)
    if s:
        s.last_at = time.monotonic()
    return s


def open_items() -> list[Session]:
    with _reg_lock:
        return list(_sessions.values())


def persist(s: Session, state: str = "open") -> None:
    """Summary + hashtags on the conversation object, raw history compressed next to it. Idempotent."""
    with s.lock:
        turns = list(s.turns)
    o = g.load_keyed("conversation", s.serial)
    if not o or (not turns and state == "open"):
        return
    tools: dict[str, int] = {}
    hosts: set[str] = set()
    error = without_result = 0
    for z in turns:
        tools[z["tool"]] = tools.get(z["tool"], 0) + 1
        hosts |= {t[5:] for t in (z.get("vorher") or {}).get("triggers", (z.get("vorher") or {}).get("reize", [])) if t.startswith("host:")}  # the turn keeps its German keys (conversation_raw); its access dict is English (0.67.0)
        error += 1 if z["ok"] is False else 0
        without_result += 1 if z["ok"] is None else 0
    o.text = (f"Conversation {s.serial} ({s.client}, instance {s.instance}, {state}): {len(turns)} calls, {error} errors"
              + (f", {without_result} without reported result" if without_result else "")
              + (" · Tools: " + ", ".join(f"{k} ({v})" for k, v in sorted(tools.items(), key=lambda kv: -kv[1])[:12]) if tools else "")
              + (f" · Hosts: {', '.join(sorted(hosts)[:12])}" if hosts else ""))
    o.data = {**o.data, "calls": len(turns), "error": error, "without_result": without_result, "signals": list(s.signals), "tools": tools, "state": state,
               "saved": g.now()}
    o.hashtags = sorted({t for t in o.hashtags if not t.startswith("state:")} | {f"state:{state}"}
                        | {f"tool:{k}" for k in tools} | {f"skill:{k.split('_')[0]}" for k in tools}
                        | {f"host:{h}" for h in hosts} | ({"ok:no"} if error else {"ok:yes"} if turns else set()))
    o.last_at = g.now()
    g.save(o)
    raw = zlib.compress(json.dumps(turns, ensure_ascii=False).encode())
    with g.lock:
        g.db().execute("INSERT OR REPLACE INTO conversation_raw (serial, raw, length) VALUES (?,?,?)", (s.serial, raw, len(raw)))
        g.db().commit()
    s.secured_until = len(turns)


def finish(session_id: str, state: str = "ended") -> bool:
    state = names.english(names.STATES, state)  # 0.67.0: beendet/unterbrochen of older callers
    from . import intuition  # late: intuition imports session
    with _reg_lock:
        s = _sessions.pop(session_id, None)
    if not s:
        return False
    with on_behalf(s):
        intuition.close_open(conversation=s.serial)
    persist(s, state)
    return True


def tidy_up(idle_s: float = IDLE_S) -> list[str]:
    """Sessions without a request since `idle_s` → `abgelaufen` (saved, removed from memory). Returns their serials."""
    bound = time.monotonic() - idle_s
    with _reg_lock:
        old = [s.id for s in _sessions.values() if s.last_at < bound]
    serials = []
    for sid in old:
        s = find_without_touching(sid)
        if s and finish(sid, "expired"):
            serials.append(s.serial)
    return serials


def find_without_touching(session_id: str) -> Session | None:
    with _reg_lock:
        return _sessions.get(session_id)


def delete_conversation(serial: str, instance: str, reason: str) -> dict:
    """Delete the private content of a conversation: experiences, remembered answers, raw history, their edges.
    The conversation object stays as a **tombstone** (state `geloescht`, with time, author, reason, count) — nothing
    vanishes silently. Shared knowledge from the conversation (insights, searches, rules) stays: it is knowledge, not
    history. Only the author instance may delete; open conversations cannot be deleted (end them first)."""
    if not (reason or "").strip():
        raise ValueError("reason is required")
    o = g.load_keyed("conversation", serial)
    if not o:
        raise ValueError(f"conversation {serial} unknown")
    if o.instance != instance:
        raise ValueError(f"conversation {serial} belongs to instance {o.instance}, not {instance}")
    if any(s.serial == serial for s in open_items()):
        raise ValueError(f"conversation {serial} is still open — end it first (DELETE)")
    if o.data.get("state") == "deleted":
        raise ValueError(f"conversation {serial} is already deleted ({o.data['deleted']['ts']})")
    with g.lock:
        ids = [r[0] for r in g.db().execute("SELECT id FROM object WHERE conversation = ? AND visibility = 'private'", (serial,))]
        g.db().execute("DELETE FROM conversation_raw WHERE serial = ?", (serial,))
        g.db().commit()
    from . import archive
    archive.delete_raw(serial)
    g.delete(ids)
    o.text = f"Conversation {serial} ({o.data.get('client', '?')}, instance {o.instance}): content deleted on {g.now()[:16]} — {reason.strip()[:200]}"
    o.data = {"serial": serial, "client": o.data.get("client"), "state": "deleted",
               "deleted": {"ts": g.now(), "who": f"ki@{instance}", "reason": reason.strip()[:300], "objekte": len(ids)}}
    o.hashtags = [t for t in o.hashtags if t.startswith(("serial:", "tag:"))] + ["state:deleted"]
    o.change(f"ki@{instance}", "deleted", reason)
    g.save(o)
    return {"serial": serial, "objekte": len(ids)}


def delete_instance_data(instance: str, reason: str) -> dict:
    """Admin (CLI, not via MCP): all private data of an instance — each of its conversations gets a tombstone."""
    with g.lock:
        serials = [names.id_key(r[0]) for r in g.db().execute(
            "SELECT id FROM object WHERE kind = 'conversation' AND instance = ? AND json_extract(data, '$.state') <> 'deleted'", (instance,))]
    n = 0
    for s in serials:
        n += delete_conversation(s, instance, reason)["objekte"]
    with g.lock:  # private objects without a conversation (e.g. from tests without a session)
        rest = [r[0] for r in g.db().execute("SELECT id FROM object WHERE instance = ? AND visibility = 'private'", (instance,))]
    n += g.delete(rest)
    return {"gespraeche": len(serials), "objekte": n}


def end_all(state: str = "ended") -> int:
    with _reg_lock:
        ids = list(_sessions)
    return sum(1 for sid in ids if finish(sid, state))
