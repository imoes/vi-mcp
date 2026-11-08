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

from . import gedaechtnis as g

LEERLAUF_S = 4 * 3600


@dataclass
class Sitzung:
    id: str
    serial: str
    instanz: str
    client: str
    begonnen: float = field(default_factory=time.monotonic)
    zuletzt: float = field(default_factory=time.monotonic)
    zuege: list = field(default_factory=list)
    sperre: threading.Lock = field(default_factory=threading.Lock)
    gesichert_bis: int = 0
    handlungen: int = 0

    def zug(self, z: dict) -> None:
        with self.sperre:
            self.zuege.append(z)


_sitzungen: dict[str, Sitzung] = {}
_reg_sperre = threading.Lock()
_aktuell: contextvars.ContextVar[Sitzung | None] = contextvars.ContextVar("aktuelle_sitzung", default=None)


def aktuelle() -> Sitzung | None:
    return _aktuell.get()


@contextlib.contextmanager
def im_auftrag(s: Sitzung | None):
    """Für die Dauer einer Anfrage: Objekte gehören zu diesem Gespräch, Züge landen in seinem Verlauf."""
    t1 = _aktuell.set(s)
    t2 = g.aktuelles_gespraech.set(s.serial if s else None)
    t3 = g.aktuelle_instanz.set(s.instanz if s else None)
    try:
        yield s
    finally:
        g.aktuelle_instanz.reset(t3)
        g.aktuelles_gespraech.reset(t2)
        _aktuell.reset(t1)


def neue_seriennummer() -> str:
    """Höchste Nummer des Tages + 1, numerisch verglichen (auch über 999 hinaus), mit INSERT als Sperre."""
    tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    praefix = f"gespraech:{tag}"
    for _ in range(50):
        with g.sperre:
            n = g.db().execute("SELECT max(CAST(substr(id, ?) AS INTEGER)) FROM objekt WHERE art = 'gespraech' AND id LIKE ?",
                               (len(praefix) + 1, f"{praefix}%")).fetchone()[0] or 0
            serial = f"{tag}{n + 1:03d}"
            try:
                g.db().execute("INSERT INTO objekt (id, art, zeit, zuletzt) VALUES (?, 'gespraech', ?, ?)",
                               (f"gespraech:{serial}", g.jetzt(), g.jetzt()))
                g.db().commit()
                return serial
            except sqlite3.IntegrityError:
                g.db().rollback()
                continue
    raise RuntimeError("keine freie Gesprächs-Seriennummer nach 50 Versuchen")


def beginne(instanz: str, client: str) -> Sitzung:
    serial = neue_seriennummer()
    tag = serial[:8]
    g.neues_objekt("gespraech", f"Gespräch {serial} begonnen ({client}, Instanz {instanz})",
                   [f"serial:{serial}", f"tag:{tag}"],
                   {"serial": serial, "aufrufe": 0, "client": client},
                   oid=f"gespraech:{serial}", grund="Sitzung gestartet", gespraech=serial, instanz=instanz)
    s = Sitzung(id=secrets.token_urlsafe(24), serial=serial, instanz=instanz, client=client)
    with _reg_sperre:
        _sitzungen[s.id] = s
    return s


def finde(sitzungs_id: str | None) -> Sitzung | None:
    if not sitzungs_id:
        return None
    with _reg_sperre:
        s = _sitzungen.get(sitzungs_id)
    if s:
        s.zuletzt = time.monotonic()
    return s


def offene() -> list[Sitzung]:
    with _reg_sperre:
        return list(_sitzungen.values())


def sichere(s: Sitzung, zustand: str = "offen") -> None:
    """Zusammenfassung + Hashtags ans Gesprächsobjekt, Rohverlauf komprimiert daneben. Idempotent."""
    with s.sperre:
        zuege = list(s.zuege)
    o = g.lade(f"gespraech:{s.serial}")
    if not o or (not zuege and zustand == "offen"):
        return
    werkzeuge: dict[str, int] = {}
    hosts: set[str] = set()
    fehler = ohne_ergebnis = 0
    for z in zuege:
        werkzeuge[z["tool"]] = werkzeuge.get(z["tool"], 0) + 1
        hosts |= {t[5:] for t in z.get("vorher", {}).get("reize", []) if t.startswith("host:")}
        fehler += 1 if z["ok"] is False else 0
        ohne_ergebnis += 1 if z["ok"] is None else 0
    o.text = (f"Gespräch {s.serial} ({s.client}, Instanz {s.instanz}, {zustand}): {len(zuege)} Aufrufe, {fehler} Fehler"
              + (f", {ohne_ergebnis} ohne gemeldetes Ergebnis" if ohne_ergebnis else "")
              + (" · Werkzeuge: " + ", ".join(f"{k} ({v})" for k, v in sorted(werkzeuge.items(), key=lambda kv: -kv[1])[:12]) if werkzeuge else "")
              + (f" · Hosts: {', '.join(sorted(hosts)[:12])}" if hosts else ""))
    o.daten = {**o.daten, "aufrufe": len(zuege), "fehler": fehler, "ohne_ergebnis": ohne_ergebnis, "werkzeuge": werkzeuge, "zustand": zustand,
               "gesichert": g.jetzt()}
    o.hashtags = sorted({t for t in o.hashtags if not t.startswith("zustand:")} | {f"zustand:{zustand}"}
                        | {f"tool:{k}" for k in werkzeuge} | {f"skill:{k.split('_')[0]}" for k in werkzeuge}
                        | {f"host:{h}" for h in hosts} | ({"ok:nein"} if fehler else {"ok:ja"} if zuege else set()))
    o.zuletzt = g.jetzt()
    g.speichere(o)
    roh = zlib.compress(json.dumps(zuege, ensure_ascii=False).encode())
    with g.sperre:
        g.db().execute("INSERT OR REPLACE INTO gespraech_roh (serial, roh, laenge) VALUES (?,?,?)", (s.serial, roh, len(roh)))
        g.db().commit()
    s.gesichert_bis = len(zuege)


def beende(sitzungs_id: str, zustand: str = "beendet") -> bool:
    from . import intuition  # spät: intuition importiert sitzung
    with _reg_sperre:
        s = _sitzungen.pop(sitzungs_id, None)
    if not s:
        return False
    with im_auftrag(s):
        intuition.offene_abschliessen(gespraech=s.serial)
    sichere(s, zustand)
    return True


def raeume_auf(leerlauf_s: float = LEERLAUF_S) -> list[str]:
    """Sitzungen ohne Anfrage seit `leerlauf_s` → `abgelaufen` (gesichert, aus dem Speicher). Liefert ihre Serials."""
    grenze = time.monotonic() - leerlauf_s
    with _reg_sperre:
        alt = [s.id for s in _sitzungen.values() if s.zuletzt < grenze]
    serials = []
    for sid in alt:
        s = finde_ohne_beruehren(sid)
        if s and beende(sid, "abgelaufen"):
            serials.append(s.serial)
    return serials


def finde_ohne_beruehren(sitzungs_id: str) -> Sitzung | None:
    with _reg_sperre:
        return _sitzungen.get(sitzungs_id)


def loesche_gespraech(serial: str, instanz: str, grund: str) -> dict:
    """Privaten Inhalt eines Gesprächs löschen: Erfahrungen, gemerkte Antworten, Rohverlauf, deren Kanten.
    Das Gesprächsobjekt bleibt als **Grabstein** (Zustand `geloescht`, mit Zeit, Urheber, Grund, Anzahl) — nichts
    verschwindet still. Geteiltes Wissen aus dem Gespräch (Erkenntnisse, Suchen, Regeln) bleibt: es ist Wissen, kein
    Verlauf. Nur die Urheber-Instanz darf löschen; offene Gespräche nicht (erst beenden)."""
    if not (grund or "").strip():
        raise ValueError("Grund ist Pflicht")
    o = g.lade(f"gespraech:{serial}")
    if not o:
        raise ValueError(f"Gespräch {serial} unbekannt")
    if o.instanz != instanz:
        raise ValueError(f"Gespräch {serial} gehört Instanz {o.instanz}, nicht {instanz}")
    if any(s.serial == serial for s in offene()):
        raise ValueError(f"Gespräch {serial} ist noch offen — erst beenden (DELETE)")
    if o.daten.get("zustand") == "geloescht":
        raise ValueError(f"Gespräch {serial} ist bereits gelöscht ({o.daten['geloescht']['zeit']})")
    with g.sperre:
        ids = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE gespraech = ? AND sicht = 'privat'", (serial,))]
        g.db().execute("DELETE FROM gespraech_roh WHERE serial = ?", (serial,))
        g.db().commit()
    from . import lager
    lager.loesche_roh(serial)
    g.loesche(ids)
    o.text = f"Gespräch {serial} ({o.daten.get('client', '?')}, Instanz {o.instanz}): Inhalt gelöscht am {g.jetzt()[:16]} — {grund.strip()[:200]}"
    o.daten = {"serial": serial, "client": o.daten.get("client"), "zustand": "geloescht",
               "geloescht": {"zeit": g.jetzt(), "wer": f"ki@{instanz}", "grund": grund.strip()[:300], "objekte": len(ids)}}
    o.hashtags = [t for t in o.hashtags if t.startswith(("serial:", "tag:"))] + ["zustand:geloescht"]
    o.aendere(f"ki@{instanz}", "gelöscht", grund)
    g.speichere(o)
    return {"serial": serial, "objekte": len(ids)}


def loesche_instanz_daten(instanz: str, grund: str) -> dict:
    """Admin (CLI, nicht per MCP): alle privaten Daten einer Instanz — jedes ihrer Gespräche bekommt einen Grabstein."""
    with g.sperre:
        serials = [r[0][len("gespraech:"):] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art = 'gespraech' AND instanz = ? AND json_extract(daten, '$.zustand') <> 'geloescht'", (instanz,))]
    n = 0
    for s in serials:
        n += loesche_gespraech(s, instanz, grund)["objekte"]
    with g.sperre:  # private Objekte ohne Gespräch (z. B. aus Tests ohne Sitzung)
        rest = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE instanz = ? AND sicht = 'privat'", (instanz,))]
    n += g.loesche(rest)
    return {"gespraeche": len(serials), "objekte": n}


def alle_beenden(zustand: str = "beendet") -> int:
    with _reg_sperre:
        ids = list(_sitzungen)
    return sum(1 for sid in ids if beende(sid, zustand))
