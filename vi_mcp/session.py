"""Sessions and conversations — the time slice.

One server process, many clients. Every MCP session (header `Mcp-Session-Id`, assigned at `initialize`) is a
conversation with serial number YYYYMMDDNNN: its own context (history of turns), tagged, stored compressed
(zlib in `gespraech_roh`), full-text searchable via the conversation object.

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

from . import memory as g

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
    try:
        yield s
    finally:
        g.current_instance.reset(t3)
        g.current_conversation.reset(t2)
        _current.reset(t1)


def new_serial() -> str:
    """Highest number of the day + 1, compared numerically (also beyond 999), with INSERT as the lock."""
    tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"gespraech:{tag}"
    for _ in range(50):
        with g.lock:
            n = g.db().execute("SELECT max(CAST(substr(id, ?) AS INTEGER)) FROM objekt WHERE art = 'gespraech' AND id LIKE ?",
                               (len(prefix) + 1, f"{prefix}%")).fetchone()[0] or 0
            serial = f"{tag}{n + 1:03d}"
            try:
                g.db().execute("INSERT INTO objekt (id, art, zeit, zuletzt) VALUES (?, 'gespraech', ?, ?)",
                               (f"gespraech:{serial}", g.now(), g.now()))
                g.db().commit()
                return serial
            except sqlite3.IntegrityError:
                g.db().rollback()
                continue
    raise RuntimeError("no free conversation serial number after 50 attempts")


def begin(instance: str, client: str, project: str | None = None, family: str | None = None, family_source: str | None = None) -> Session:
    serial = new_serial()
    tag = serial[:8]
    g.new_object("gespraech", f"Conversation {serial} started ({client}, instance {instance})",
                   [f"serial:{serial}", f"tag:{tag}"],
                   {"serial": serial, "aufrufe": 0, "client": client, **({"project": project} if project else {}),
                    **({"familie": family, "familie_quelle": family_source} if family else {})},
                   oid=f"gespraech:{serial}", reason="session started", conversation=serial, instance=instance)
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


def persist(s: Session, state: str = "offen") -> None:
    """Summary + hashtags on the conversation object, raw history compressed next to it. Idempotent."""
    with s.lock:
        turns = list(s.turns)
    o = g.load(f"gespraech:{s.serial}")
    if not o or (not turns and state == "offen"):
        return
    tools: dict[str, int] = {}
    hosts: set[str] = set()
    error = without_result = 0
    for z in turns:
        tools[z["tool"]] = tools.get(z["tool"], 0) + 1
        hosts |= {t[5:] for t in z.get("vorher", {}).get("reize", []) if t.startswith("host:")}
        error += 1 if z["ok"] is False else 0
        without_result += 1 if z["ok"] is None else 0
    o.text = (f"Conversation {s.serial} ({s.client}, instance {s.instance}, {state}): {len(turns)} calls, {error} errors"
              + (f", {without_result} without reported result" if without_result else "")
              + (" · Tools: " + ", ".join(f"{k} ({v})" for k, v in sorted(tools.items(), key=lambda kv: -kv[1])[:12]) if tools else "")
              + (f" · Hosts: {', '.join(sorted(hosts)[:12])}" if hosts else ""))
    o.data = {**o.data, "aufrufe": len(turns), "fehler": error, "ohne_ergebnis": without_result, "signale": list(s.signals), "werkzeuge": tools, "zustand": state,
               "gesichert": g.now()}
    o.hashtags = sorted({t for t in o.hashtags if not t.startswith("zustand:")} | {f"zustand:{state}"}
                        | {f"tool:{k}" for k in tools} | {f"skill:{k.split('_')[0]}" for k in tools}
                        | {f"host:{h}" for h in hosts} | ({"ok:nein"} if error else {"ok:ja"} if turns else set()))
    o.last_at = g.now()
    g.save(o)
    raw = zlib.compress(json.dumps(turns, ensure_ascii=False).encode())
    with g.lock:
        g.db().execute("INSERT OR REPLACE INTO gespraech_roh (serial, roh, laenge) VALUES (?,?,?)", (s.serial, raw, len(raw)))
        g.db().commit()
    s.secured_until = len(turns)


def finish(session_id: str, state: str = "beendet") -> bool:
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
        if s and finish(sid, "abgelaufen"):
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
    o = g.load(f"gespraech:{serial}")
    if not o:
        raise ValueError(f"conversation {serial} unknown")
    if o.instance != instance:
        raise ValueError(f"conversation {serial} belongs to instance {o.instance}, not {instance}")
    if any(s.serial == serial for s in open_items()):
        raise ValueError(f"conversation {serial} is still open — end it first (DELETE)")
    if o.data.get("zustand") == "geloescht":
        raise ValueError(f"conversation {serial} is already deleted ({o.data['geloescht']['zeit']})")
    with g.lock:
        ids = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE gespraech = ? AND sicht = 'privat'", (serial,))]
        g.db().execute("DELETE FROM gespraech_roh WHERE serial = ?", (serial,))
        g.db().commit()
    from . import archive
    archive.delete_raw(serial)
    g.delete(ids)
    o.text = f"Conversation {serial} ({o.data.get('client', '?')}, instance {o.instance}): content deleted on {g.now()[:16]} — {reason.strip()[:200]}"
    o.data = {"serial": serial, "client": o.data.get("client"), "zustand": "geloescht",
               "geloescht": {"zeit": g.now(), "wer": f"ki@{instance}", "grund": reason.strip()[:300], "objekte": len(ids)}}
    o.hashtags = [t for t in o.hashtags if t.startswith(("serial:", "tag:"))] + ["zustand:geloescht"]
    o.change(f"ki@{instance}", "deleted", reason)
    g.save(o)
    return {"serial": serial, "objekte": len(ids)}


def delete_instance_data(instance: str, reason: str) -> dict:
    """Admin (CLI, not via MCP): all private data of an instance — each of its conversations gets a tombstone."""
    with g.lock:
        serials = [r[0][len("gespraech:"):] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'gespraech' AND instanz = ? AND json_extract(daten, '$.zustand') <> 'geloescht'", (instance,))]
    n = 0
    for s in serials:
        n += delete_conversation(s, instance, reason)["objekte"]
    with g.lock:  # private objects without a conversation (e.g. from tests without a session)
        rest = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE instanz = ? AND sicht = 'privat'", (instance,))]
    n += g.delete(rest)
    return {"gespraeche": len(serials), "objekte": n}


def end_all(state: str = "beendet") -> int:
    with _reg_lock:
        ids = list(_sessions)
    return sum(1 for sid in ids if finish(sid, state))
