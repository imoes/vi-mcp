"""Vektoren — Bedeutung statt Wortgleichheit (Stufe 3, docs/TRAINING.md 4c; Park et al. 2023, Abschnitt 4.1: Relevanz
= Kosinus-Ähnlichkeit der Embeddings).

Heute findet `erinnere` nur, was dieselben Hashtags oder Wörter trägt. Ein Embedding-Dienst (OpenAI-kompatibel,
`/v1/embeddings`) macht aus dem Text jedes geteilten Wissensobjekts einen Vektor; gespeichert als float32-BLOB in der
Tabelle `vektor` (4 Byte je Dimension, ohne Erweiterung — TRAINING.md 4c, Weg 1). Weil der Dienst auf dem Host
mehrere Sekunden je Anfrage braucht (gemessen 08.11.2026), passiert das **im Schlaf**, im Batch, nie in `vi_vorher`:
  Schritt 7_vektoren  fehlende Vektoren für erkenntnis/regel/suche nachziehen (höchstens BATCH_MAX je Schlaf)
  Schritt 7b_naehe    Paare mit Kosinus ≥ NAEHE_KANTE bekommen eine Kante „semantisch ähnlich (cos 0,91)“;
                      Paare ≥ NAEHE_DUBLETTE ohne gemeinsame Instanz werden als `dublette:moeglich` markiert (nicht
                      zusammengelegt — das entscheidet ein Mensch oder eine zweite Instanz)
Dazu `vi_erinnere(filter, semantisch=true)`: bettet den Freitext **jetzt** ein (dauert, wird im Ergebnis genannt) und
ordnet die Kandidaten nach Kosinus — ausdrücklich, nie automatisch.
Ohne Konfiguration `embed` passiert nichts; der Schlaf meldet den Schritt als übersprungen (benannt).
"""
from __future__ import annotations

import json
import math
import struct
import urllib.error
import urllib.request

from . import gedaechtnis as g
from .protokoll import log

BATCH = 16
BATCH_MAX = 256
NAEHE_KANTE = 0.85
NAEHE_DUBLETTE = 0.95
VEKTOR_ARTEN = ("erkenntnis", "regel", "suche", "skill")
TIMEOUT_S = 120

#: Konfiguration: {"url": "https://host/embed/v1/embeddings", "token": "...", "modell": "..."} oder None
konfig: dict | None = None
#: Austauschbare Einbettungsfunktion (Tests): texte → Liste von Vektoren
einbetten_fn = None


def _tabelle() -> None:
    with g.sperre:
        g.db().execute("CREATE TABLE IF NOT EXISTS vektor (id TEXT PRIMARY KEY, dim INTEGER NOT NULL, modell TEXT NOT NULL, "
                       "zeit TEXT NOT NULL, roh BLOB NOT NULL)")
        g.db().commit()


def verfuegbar() -> bool:
    return einbetten_fn is not None or bool(konfig and konfig.get("url"))


def einbetten(texte: list[str]) -> list[list[float]]:
    if einbetten_fn is not None:
        return einbetten_fn(texte)
    if not konfig or not konfig.get("url"):
        raise RuntimeError("kein Embedding-Dienst konfiguriert (konfig.embed.url)")
    kopf = {"Content-Type": "application/json"}
    if konfig.get("token"):
        kopf["Authorization"] = f"Bearer {konfig['token']}"
    body = {"input": texte}
    if konfig.get("modell"):
        body["model"] = konfig["modell"]
    req = urllib.request.Request(konfig["url"], data=json.dumps(body).encode(), headers=kopf)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # Hostdienst, nie über einen Firmen-Proxy
    with op.open(req, timeout=TIMEOUT_S) as a:
        d = json.load(a)
    daten = sorted(d["data"], key=lambda x: x.get("index", 0))
    return [x["embedding"] for x in daten]


def _pack(v: list[float]) -> bytes:
    return struct.pack(f"<{len(v)}f", *v)


def _unpack(roh: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"<{dim}f", roh))


def kosinus(a: list[float], b: list[float]) -> float:
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return s / (na * nb)


def speichere(oid: str, v: list[float], modell: str) -> None:
    _tabelle()
    with g.sperre:
        g.db().execute("INSERT OR REPLACE INTO vektor (id, dim, modell, zeit, roh) VALUES (?,?,?,?,?)", (oid, len(v), modell, g.jetzt(), _pack(v)))
        g.db().commit()


def entferne(oid: str) -> None:
    """Eingelagerte Objekte brauchen keinen Vektor; nach dem Zurückholen zieht der Schlaf ihn neu nach."""
    _tabelle()
    with g.sperre:
        g.db().execute("DELETE FROM vektor WHERE id = ?", (oid,))
        g.db().commit()


def lade(oid: str) -> list[float] | None:
    _tabelle()
    with g.sperre:
        row = g.db().execute("SELECT dim, roh FROM vektor WHERE id = ?", (oid,)).fetchone()
    return _unpack(row[1], row[0]) if row else None


def alle() -> dict[str, list[float]]:
    _tabelle()
    with g.sperre:
        rows = g.db().execute("SELECT v.id, v.dim, v.roh FROM vektor v JOIN objekt o ON o.id = v.id WHERE o.modus NOT IN ('widerlegt', 'archiviert', 'quarantaene')").fetchall()
    return {oid: _unpack(roh, dim) for oid, dim, roh in rows}


def nachziehen() -> dict:
    """Schlaf-Schritt 7: fehlende Vektoren geteilter Wissensobjekte berechnen (Batch, begrenzt)."""
    if not verfuegbar():
        return {"zustand": "uebersprungen", "grund": "kein Embedding-Dienst konfiguriert (konfig.embed)"}
    _tabelle()
    with g.sperre:
        fehlend = g.db().execute(
            f"SELECT o.id, o.text FROM objekt o LEFT JOIN vektor v ON v.id = o.id WHERE v.id IS NULL AND o.art IN ({','.join('?' * len(VEKTOR_ARTEN))}) "
            "AND o.modus NOT IN ('widerlegt', 'archiviert', 'quarantaene') AND length(o.text) > 0 ORDER BY o.zeit DESC LIMIT ?", (*VEKTOR_ARTEN, BATCH_MAX)).fetchall()
    n, fehler = 0, None
    modell = (konfig or {}).get("modell") or "embed"
    for i in range(0, len(fehlend), BATCH):
        teil = fehlend[i:i + BATCH]
        try:
            vs = einbetten([t for _, t in teil])
        except (urllib.error.URLError, OSError, KeyError, ValueError, RuntimeError) as e:
            fehler = f"{type(e).__name__}: {e}"
            log(f"Vektoren: Batch scheiterte — {fehler}")
            break
        for (oid, _), v in zip(teil, vs):
            speichere(oid, v, modell)
            n += 1
    return {"zustand": "fertig" if fehler is None else "fehler", "neu": n, "offen": len(fehlend) - n, **({"fehler": fehler} if fehler else {})}


def naehe_kanten() -> dict:
    """Schlaf-Schritt 7b: Kanten zwischen semantisch nahen Wissensobjekten; sehr nahe fremde Paare → dublette:moeglich."""
    vs = alle()
    ids = list(vs)
    kanten = dubletten = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            c = kosinus(vs[ids[i]], vs[ids[j]])
            if c < NAEHE_KANTE:
                continue
            a, b = g.lade(ids[i]), g.lade(ids[j])
            if not a or not b:
                continue
            with g.sperre:
                schon = g.db().execute("SELECT 1 FROM kante WHERE a = ? AND b = ?", (a.id, b.id)).fetchone()
            if not schon:
                a.verknuepfe(b.id, f"semantisch ähnlich (cos {c:.2f})")
                kanten += 1
            if c >= NAEHE_DUBLETTE and a.instanz != b.instanz:
                for o in (a, b):
                    if "dublette:moeglich" not in o.hashtags:
                        o.hashtags = o.hashtags + ["dublette:moeglich"]
                        o.aendere("vi", "dublette:moeglich", f"cos {c:.2f} zu {(b if o is a else a).id} (andere Instanz) — zusammenlegen entscheidet eine Instanz")
                        g.speichere(o)
                dubletten += 1
    return {"kanten_neu": kanten, "dubletten_moeglich": dubletten, "vektoren": len(ids)}


def aehnlich(text: str, kandidaten: list[str], limit: int = 10) -> list[tuple[str, float]]:
    """Freitext jetzt einbetten und Kandidaten nach Kosinus ordnen (dauert — nur auf ausdrücklichen Wunsch)."""
    q = einbetten([text])[0]
    vs = alle()
    paare = [(oid, kosinus(q, vs[oid])) for oid in kandidaten if oid in vs]
    return sorted(paare, key=lambda x: -x[1])[:limit]
