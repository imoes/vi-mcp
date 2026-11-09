"""Vektoren — Bedeutung statt Wortgleichheit (Stufe 3, docs/TRAINING.md 4c; Park et al. 2023, Abschnitt 4.1: Relevanz
= Kosinus-Ähnlichkeit der Embeddings).

Heute findet `erinnere` nur, was dieselben Hashtags oder Wörter trägt. Ein Embedding-Dienst (OpenAI-kompatibel,
`/v1/embeddings`) macht aus dem Text jedes geteilten Wissensobjekts einen Vektor; gespeichert als float32-BLOB in der
Tabelle `vektor` (4 Byte je Dimension, ohne Erweiterung — TRAINING.md 4c, Weg 1). Weil der Dienst auf dem Host
mehrere Sekunden je Anfrage braucht (gemessen 08.11.2026), passiert das **im Schlaf**, im Batch, nie in `vi_vorher`:
  Schritt 7_vektoren  fehlende Vektoren für erkenntnis/regel/suche/skill nachziehen (höchstens NACHZIEH_MAX_S Sekunden je Schlaf)
  Schritt 7b_naehe    Paare mit Kosinus ≥ NAEHE_KANTE bekommen eine Kante „semantisch ähnlich (cos 0,91)“;
                      Paare ≥ NAEHE_DUBLETTE ohne gemeinsame Instanz werden als `dublette:moeglich` markiert (nicht
                      zusammengelegt — das entscheidet ein Mensch oder eine zweite Instanz)
Dazu `vi_erinnere(filter, semantisch=true)`: bettet den Freitext **jetzt** ein (dauert, wird im Ergebnis genannt) und
ordnet die Kandidaten nach Kosinus, zusammengeführt mit dem Volltext (Rangfusion, werkzeuge.RRF_K) — ausdrücklich, nie automatisch.
Ohne Konfiguration `embed` passiert nichts; der Schlaf meldet den Schritt als übersprungen (benannt).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import numpy as np

from . import gedaechtnis as g
from .protokoll import log

BATCH = 16
#: Zeitgrenze statt Stückzahl: Ein Schlaf soll nicht stundenlang einbetten, der Rest kommt im nächsten (gemessen rund 1,5 s je Text)
NACHZIEH_MAX_S = 300
#: 0.20.5: Pause nach jedem Batch, als Anteil seiner Dauer (1.0 = höchstens halbe Auslastung). Der Embedding-Dienst ist geteilt
#: (AIKB, CentralStation): am 09.11. 07:00 UTC brauchte eine einzelne kurze Frage dort 23–27 s statt sonst 1,9–6,5 s.
#: Einstellbar über konfig embed.pause_anteil; 0 schaltet die Pause ab.
PAUSE_ANTEIL = 1.0
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
        # 0.20.0: verglichen = 1, sobald die Nähe-Kanten des Vektors berechnet sind (ein neu eingebetteter Vektor fängt bei 0 an)
        if "verglichen" not in {r[1] for r in g.db().execute("PRAGMA table_info(vektor)")}:
            g.db().execute("ALTER TABLE vektor ADD COLUMN verglichen INTEGER NOT NULL DEFAULT 0")
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


def _pack(v) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def _unpack(roh: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(roh, dtype=np.float32, count=dim)


def kosinus(a, b) -> float:
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    n = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / n) if n else 0.0


def _matrix(vs: dict[str, np.ndarray]) -> tuple[list[str], np.ndarray]:
    """Normierte Vektoren der häufigsten Dimension (ein Modellwechsel hinterlässt andere Längen)."""
    if not vs:
        return [], np.zeros((0, 0), dtype=np.float32)
    dims = [len(v) for v in vs.values()]
    dim = max(set(dims), key=dims.count)
    ids = [i for i, v in vs.items() if len(v) == dim]
    m = np.stack([vs[i] for i in ids])
    normen = np.linalg.norm(m, axis=1, keepdims=True)
    normen[normen == 0] = 1.0
    return ids, m / normen


def speichere(oid: str, v, modell: str) -> None:
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


def lade(oid: str) -> np.ndarray | None:
    _tabelle()
    with g.sperre:
        row = g.db().execute("SELECT dim, roh FROM vektor WHERE id = ?", (oid,)).fetchone()
    return _unpack(row[1], row[0]) if row else None


def alle() -> dict[str, np.ndarray]:
    _tabelle()
    with g.sperre:
        rows = g.db().execute("SELECT v.id, v.dim, v.roh FROM vektor v JOIN objekt o ON o.id = v.id WHERE o.modus NOT IN ('widerlegt', 'archiviert', 'quarantaene')").fetchall()
    return {oid: _unpack(roh, dim) for oid, dim, roh in rows}


def vorhanden(ids: list[str]) -> int:
    """Wie viele der IDs einen Vektor haben (ohne die Vektoren zu laden)."""
    _tabelle()
    with g.sperre:
        alle_ids = {r[0] for r in g.db().execute("SELECT id FROM vektor")}
    return len(alle_ids & set(ids))


def nachziehen(max_s: float | None = None) -> dict:
    """Schlaf-Schritt 7: fehlende Vektoren geteilter Wissensobjekte berechnen, Neueste zuerst, höchstens NACHZIEH_MAX_S Sekunden je Schlaf."""
    if not verfuegbar():
        return {"zustand": "uebersprungen", "grund": "kein Embedding-Dienst konfiguriert (konfig.embed)"}
    _tabelle()
    with g.sperre:
        fehlend = g.db().execute(
            f"SELECT o.id, o.text FROM objekt o LEFT JOIN vektor v ON v.id = o.id WHERE v.id IS NULL AND o.art IN ({','.join('?' * len(VEKTOR_ARTEN))}) "
            "AND o.modus NOT IN ('widerlegt', 'archiviert', 'quarantaene') AND length(o.text) > 0 ORDER BY o.zeit DESC", VEKTOR_ARTEN).fetchall()
    n, fehler, ende, pausiert = 0, None, time.monotonic() + (NACHZIEH_MAX_S if max_s is None else max_s), 0.0
    modell = (konfig or {}).get("modell") or "embed"
    for i in range(0, len(fehlend), BATCH):
        if time.monotonic() > ende:
            break  # der Rest folgt im nächsten Schlaf; „offen“ nennt ihn
        teil = fehlend[i:i + BATCH]
        t_batch = time.monotonic()
        try:
            vs = einbetten([t for _, t in teil])
        except (urllib.error.URLError, OSError, KeyError, ValueError, RuntimeError) as e:
            fehler = f"{type(e).__name__}: {e}"
            log(f"Vektoren: Batch scheiterte — {fehler}")
            break
        for (oid, _), v in zip(teil, vs):
            speichere(oid, v, modell)
            n += 1
        pause = (time.monotonic() - t_batch) * float((konfig or {}).get("pause_anteil", PAUSE_ANTEIL))
        if pause > 0 and i + BATCH < len(fehlend):
            pausiert += pause
            time.sleep(min(pause, max(0.0, ende - time.monotonic())))
    return {"zustand": "fertig" if fehler is None else "fehler", "neu": n, "offen": len(fehlend) - n, "pause_s": round(pausiert, 1),
            **({"fehler": fehler} if fehler else {})}


def naehe_kanten() -> dict:
    """Schritt 7b: Kanten zwischen semantisch nahen Wissensobjekten; sehr nahe fremde Paare → dublette:moeglich.
    Seit 0.20.0 inkrementell: nur noch nicht verglichene Vektoren gegen alle (O(neu × alle) statt O(alle²); gemessen 9,6 s für 3.312 Vektoren
    beim vollen Vergleich, das wüchse mit dem Confluence-Import quadratisch)."""
    _tabelle()
    ids, m = _matrix(alle())
    with g.sperre:
        neu_ids = {r[0] for r in g.db().execute("SELECT id FROM vektor WHERE verglichen = 0")}
    pos = {oid: i for i, oid in enumerate(ids)}
    neu = sorted(pos[o] for o in neu_ids if o in pos)
    ist_neu = np.zeros(len(ids), dtype=bool)
    ist_neu[neu] = True
    kanten = dubletten = 0
    for i in neu:  # zeilenweise: der Speicher wächst nicht mit dem Quadrat der Objektzahl
        naehe = m @ m[i]
        naehe[i] = -1.0
        naehe[ist_neu & (np.arange(len(ids)) < i)] = -1.0  # Paare zweier neuer Vektoren nur einmal
        for k in np.nonzero(naehe >= NAEHE_KANTE)[0]:
            j, c = int(k), float(naehe[k])
            a, b = g.lade(ids[min(i, j)]), g.lade(ids[max(i, j)])
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
    with g.sperre:
        g.db().executemany("UPDATE vektor SET verglichen = 1 WHERE id = ?", [(ids[i],) for i in neu])
        g.db().commit()
    return {"kanten_neu": kanten, "dubletten_moeglich": dubletten, "vektoren": len(ids), "neu_verglichen": len(neu)}


def aehnlich(text: str, kandidaten: list[str], limit: int = 10) -> list[tuple[str, float]]:
    """Freitext jetzt einbetten und Kandidaten nach Kosinus ordnen (dauert — nur auf ausdrücklichen Wunsch)."""
    q = np.asarray(einbetten([text])[0], dtype=np.float32)
    n = float(np.linalg.norm(q)) or 1.0
    vs = alle()
    ids, m = _matrix({k: vs[k] for k in kandidaten if k in vs and len(vs[k]) == len(q)})
    if not ids:
        return []
    naehe = m @ (q / n)
    return sorted(((ids[i], float(naehe[i])) for i in range(len(ids))), key=lambda x: -x[1])[:limit]
