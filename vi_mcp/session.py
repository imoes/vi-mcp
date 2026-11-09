"""Sitzungen und Gespräche — die Zeitscheibe.

Ein Serverprozess, viele Clients. Jede MCP-Sitzung (Header `Mcp-Session-Id`, vergeben bei `initialize`) ist ein
Gespräch mit Seriennummer YYYYMMDDNNN: eigener Kontext (Verlauf der Züge), getaggt, komprimiert gespeichert
(zlib in `gespraech_roh`), volltextdurchsuchbar über das Gesprächsobjekt.

Zustände einer Sitzung (erschöpfend): `offen` (Anfragen kommen), `beendet` (Client hat DELETE gesendet),
`abgelaufen` (länger als `LEERLAUF_S` ohne Anfrage), `unterbrochen` (Server wurde beendet, während sie offen
war). Alles außer `offen` wird gesichert und aus dem Speicher genommen; eine Anfrage mit ihrer Id bekommt 404
(Client muss neu initialisieren, MCP-Spec).
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
    signals: list = field(default_factory=list)  # Korrekturen und Noten des Nutzers, ohne seinen Text

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
    """Für die Dauer einer Anfrage: Objekte gehören zu diesem Gespräch, Züge landen in seinem Verlauf."""
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
    """Höchste Nummer des Tages + 1, numerisch verglichen (auch über 999 hinaus), mit INSERT als Sperre."""
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
    raise RuntimeError("keine freie Gesprächs-Seriennummer nach 50 Versuchen")


def begin(instance: str, client: str) -> Session:
    serial = new_serial()
    tag = serial[:8]
    g.new_object("gespraech", f"Gespräch {serial} begonnen ({client}, Instanz {instance})",
                   [f"serial:{serial}", f"tag:{tag}"],
                   {"serial": serial, "aufrufe": 0, "client": client},
                   oid=f"gespraech:{serial}", reason="Sitzung gestartet", conversation=serial, instance=instance)
    s = Session(id=secrets.token_urlsafe(24), serial=serial, instance=instance, client=client)
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
    """Zusammenfassung + Hashtags ans Gesprächsobjekt, Rohverlauf komprimiert daneben. Idempotent."""
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
    o.text = (f"Gespräch {s.serial} ({s.client}, Instanz {s.instance}, {state}): {len(turns)} Aufrufe, {error} Fehler"
              + (f", {without_result} ohne gemeldetes Ergebnis" if without_result else "")
              + (" · Werkzeuge: " + ", ".join(f"{k} ({v})" for k, v in sorted(tools.items(), key=lambda kv: -kv[1])[:12]) if tools else "")
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
    from . import intuition  # spät: intuition importiert sitzung
    with _reg_lock:
        s = _sessions.pop(session_id, None)
    if not s:
        return False
    with on_behalf(s):
        intuition.close_open(conversation=s.serial)
    persist(s, state)
    return True


def tidy_up(idle_s: float = IDLE_S) -> list[str]:
    """Sitzungen ohne Anfrage seit `leerlauf_s` → `abgelaufen` (gesichert, aus dem Speicher). Liefert ihre Serials."""
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
    """Privaten Inhalt eines Gesprächs löschen: Erfahrungen, gemerkte Antworten, Rohverlauf, deren Kanten.
    Das Gesprächsobjekt bleibt als **Grabstein** (Zustand `geloescht`, mit Zeit, Urheber, Grund, Anzahl) — nichts
    verschwindet still. Geteiltes Wissen aus dem Gespräch (Erkenntnisse, Suchen, Regeln) bleibt: es ist Wissen, kein
    Verlauf. Nur die Urheber-Instanz darf löschen; offene Gespräche nicht (erst beenden)."""
    if not (reason or "").strip():
        raise ValueError("Grund ist Pflicht")
    o = g.load(f"gespraech:{serial}")
    if not o:
        raise ValueError(f"Gespräch {serial} unbekannt")
    if o.instance != instance:
        raise ValueError(f"Gespräch {serial} gehört Instanz {o.instance}, nicht {instance}")
    if any(s.serial == serial for s in open_items()):
        raise ValueError(f"Gespräch {serial} ist noch offen — erst beenden (DELETE)")
    if o.data.get("zustand") == "geloescht":
        raise ValueError(f"Gespräch {serial} ist bereits gelöscht ({o.data['geloescht']['zeit']})")
    with g.lock:
        ids = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE gespraech = ? AND sicht = 'privat'", (serial,))]
        g.db().execute("DELETE FROM gespraech_roh WHERE serial = ?", (serial,))
        g.db().commit()
    from . import archive
    archive.delete_raw(serial)
    g.delete(ids)
    o.text = f"Gespräch {serial} ({o.data.get('client', '?')}, Instanz {o.instance}): Inhalt gelöscht am {g.now()[:16]} — {reason.strip()[:200]}"
    o.data = {"serial": serial, "client": o.data.get("client"), "zustand": "geloescht",
               "geloescht": {"zeit": g.now(), "wer": f"ki@{instance}", "grund": reason.strip()[:300], "objekte": len(ids)}}
    o.hashtags = [t for t in o.hashtags if t.startswith(("serial:", "tag:"))] + ["zustand:geloescht"]
    o.change(f"ki@{instance}", "gelöscht", reason)
    g.save(o)
    return {"serial": serial, "objekte": len(ids)}


def delete_instance_data(instance: str, reason: str) -> dict:
    """Admin (CLI, nicht per MCP): alle privaten Daten einer Instanz — jedes ihrer Gespräche bekommt einen Grabstein."""
    with g.lock:
        serials = [r[0][len("gespraech:"):] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'gespraech' AND instanz = ? AND json_extract(daten, '$.zustand') <> 'geloescht'", (instance,))]
    n = 0
    for s in serials:
        n += delete_conversation(s, instance, reason)["objekte"]
    with g.lock:  # private Objekte ohne Gespräch (z. B. aus Tests ohne Sitzung)
        rest = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE instanz = ? AND sicht = 'privat'", (instance,))]
    n += g.delete(rest)
    return {"gespraeche": len(serials), "objekte": n}


def end_all(state: str = "beendet") -> int:
    with _reg_lock:
        ids = list(_sessions)
    return sum(1 for sid in ids if finish(sid, state))
