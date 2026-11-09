"""Vektoren — Bedeutung statt Wortgleichheit (Stufe 3, docs/TRAINING.md 4c; Park et al. 2023, Abschnitt 4.1: Relevanz
= Kosinus-Ähnlichkeit der Embeddings).

Heute findet `erinnere` nur, was dieselben Hashtags oder Wörter trägt. Ein Embedding-Dienst (OpenAI-kompatibel,
`/v1/embeddings`) macht aus dem Text jedes geteilten Wissensobjekts einen Vektor; gespeichert als float32-BLOB in der
Tabelle `vektor` (4 Byte je Dimension, ohne Erweiterung — TRAINING.md 4c, Weg 1). Weil der Dienst auf dem Host
mehrere Sekunden je Anfrage braucht (gemessen 08.11.2026), passiert das **im Schlaf**, im Batch, nie in `vi_before`:
  Schritt 7_vektoren  fehlende Vektoren für erkenntnis/regel/suche/skill nachziehen (höchstens NACHZIEH_MAX_S Sekunden je Schlaf)
  Schritt 7b_naehe    Paare mit Kosinus ≥ NAEHE_KANTE bekommen eine Kante „semantisch ähnlich (cos 0,91)“;
                      Paare ≥ NAEHE_DUBLETTE ohne gemeinsame Instanz werden als `dublette:moeglich` markiert (nicht
                      zusammengelegt — das entscheidet ein Mensch oder eine zweite Instanz)
Dazu `vi_recall(filter, semantisch=true)`: bettet den Freitext **jetzt** ein (dauert, wird im Ergebnis genannt) und
ordnet die Kandidaten nach Kosinus, zusammengeführt mit dem Volltext (Rangfusion, werkzeuge.RRF_K) — ausdrücklich, nie automatisch.
Ohne Konfiguration `embed` passiert nichts; der Schlaf meldet den Schritt als übersprungen (benannt).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import numpy as np

from . import memory as g
from .log_output import log

BATCH = 16
#: Zeitgrenze statt Stückzahl: Ein Schlaf soll nicht stundenlang einbetten, der Rest kommt im nächsten (gemessen rund 1,5 s je Text)
CATCHUP_MAX_S = 300
#: 0.20.5: Pause nach jedem Batch, als Anteil seiner Dauer (1.0 = höchstens halbe Auslastung), für geteilte Embedding-Dienste.
#: Standard 0 = ungedrosselt (Entscheidung des Nutzers, 09.11.); einschalten über konfig embed.pause_anteil.
PAUSE_SHARE = 0.0
PROXIMITY_EDGE = 0.85
PROXIMITY_DUPLICATE = 0.95
#: 0.20.6: höchstens so viele semantische Nachbarn je neuem Vektor. Ohne Grenze verband der Confluence-Import fast gleiche Vorlagenseiten
#: alle miteinander: 2,24 Mio. Kanten, bis 1.316 je Objekt, 96 s je Nähe-Schritt (gemessen 09.11. 07:41 UTC).
PROXIMITY_MAX = 10
VECTOR_KINDS = ("erkenntnis", "regel", "suche", "skill")
TIMEOUT_S = 120

#: Konfiguration: {"url": "https://host/embed/v1/embeddings", "token": "...", "modell": "..."} oder None
config: dict | None = None
#: Austauschbare Einbettungsfunktion (Tests): texte → Liste von Vektoren
embed_fn = None


def _table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS vektor (id TEXT PRIMARY KEY, dim INTEGER NOT NULL, modell TEXT NOT NULL, "
                       "zeit TEXT NOT NULL, roh BLOB NOT NULL)")
        # 0.20.0: verglichen = 1, sobald die Nähe-Kanten des Vektors berechnet sind (ein neu eingebetteter Vektor fängt bei 0 an)
        if "verglichen" not in {r[1] for r in g.db().execute("PRAGMA table_info(vektor)")}:
            g.db().execute("ALTER TABLE vektor ADD COLUMN verglichen INTEGER NOT NULL DEFAULT 0")
        g.db().commit()


def available() -> bool:
    return embed_fn is not None or bool(config and config.get("url"))


def embed_texts(texts: list[str]) -> list[list[float]]:
    if embed_fn is not None:
        return embed_fn(texts)
    if not config or not config.get("url"):
        raise RuntimeError("kein Embedding-Dienst konfiguriert (konfig.embed.url)")
    header = {"Content-Type": "application/json"}
    if config.get("token"):
        header["Authorization"] = f"Bearer {config['token']}"
    body = {"input": texts}
    if config.get("modell"):
        body["model"] = config["modell"]
    req = urllib.request.Request(config["url"], data=json.dumps(body).encode(), headers=header)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # Hostdienst, nie über einen Firmen-Proxy
    with op.open(req, timeout=TIMEOUT_S) as a:
        d = json.load(a)
    data = sorted(d["data"], key=lambda x: x.get("index", 0))
    return [x["embedding"] for x in data]


def _pack(v) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def _unpack(raw: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.float32, count=dim)


def cosine(a, b) -> float:
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
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return ids, m / norms


def save(oid: str, v, model: str) -> None:
    _table()
    with g.lock:
        g.db().execute("INSERT OR REPLACE INTO vektor (id, dim, modell, zeit, roh) VALUES (?,?,?,?,?)", (oid, len(v), model, g.now(), _pack(v)))
        g.db().commit()


def remove_entry(oid: str) -> None:
    """Eingelagerte Objekte brauchen keinen Vektor; nach dem Zurückholen zieht der Schlaf ihn neu nach."""
    _table()
    with g.lock:
        g.db().execute("DELETE FROM vektor WHERE id = ?", (oid,))
        g.db().commit()


def load(oid: str) -> np.ndarray | None:
    _table()
    with g.lock:
        row = g.db().execute("SELECT dim, roh FROM vektor WHERE id = ?", (oid,)).fetchone()
    return _unpack(row[1], row[0]) if row else None


def all_() -> dict[str, np.ndarray]:
    _table()
    with g.lock:
        rows = g.db().execute("SELECT v.id, v.dim, v.roh FROM vektor v JOIN objekt o ON o.id = v.id WHERE o.modus NOT IN ('widerlegt', 'archiviert', 'quarantaene')").fetchall()
    return {oid: _unpack(raw, dim) for oid, dim, raw in rows}


def present(ids: list[str]) -> int:
    """Wie viele der IDs einen Vektor haben (ohne die Vektoren zu laden)."""
    _table()
    with g.lock:
        all_ids = {r[0] for r in g.db().execute("SELECT id FROM vektor")}
    return len(all_ids & set(ids))


def catch_up(max_s: float | None = None) -> dict:
    """Schlaf-Schritt 7: fehlende Vektoren geteilter Wissensobjekte berechnen, Neueste zuerst, höchstens NACHZIEH_MAX_S Sekunden je Schlaf."""
    if not available():
        return {"zustand": "uebersprungen", "grund": "kein Embedding-Dienst konfiguriert (konfig.embed)"}
    _table()
    with g.lock:
        missing = g.db().execute(
            f"SELECT o.id, o.text FROM objekt o LEFT JOIN vektor v ON v.id = o.id WHERE v.id IS NULL AND o.art IN ({','.join('?' * len(VECTOR_KINDS))}) "
            "AND o.modus NOT IN ('widerlegt', 'archiviert', 'quarantaene') AND length(o.text) > 0 ORDER BY o.zeit DESC", VECTOR_KINDS).fetchall()
    n, error, end, paused = 0, None, time.monotonic() + (CATCHUP_MAX_S if max_s is None else max_s), 0.0
    model = (config or {}).get("modell") or "embed"
    for i in range(0, len(missing), BATCH):
        if time.monotonic() > end:
            break  # der Rest folgt im nächsten Schlaf; „offen“ nennt ihn
        part = missing[i:i + BATCH]
        t_batch = time.monotonic()
        try:
            vs = embed_texts([t for _, t in part])
        except (urllib.error.URLError, OSError, KeyError, ValueError, RuntimeError) as e:
            error = f"{type(e).__name__}: {e}"
            log(f"Vektoren: Batch scheiterte — {error}")
            break
        for (oid, _), v in zip(part, vs):
            save(oid, v, model)
            n += 1
        pause = (time.monotonic() - t_batch) * float((config or {}).get("pause_anteil", PAUSE_SHARE))
        if pause > 0 and i + BATCH < len(missing):
            paused += pause
            time.sleep(min(pause, max(0.0, end - time.monotonic())))
    return {"zustand": "fertig" if error is None else "fehler", "neu": n, "offen": len(missing) - n, "pause_s": round(paused, 1),
            **({"fehler": error} if error else {})}


def proximity_edges() -> dict:
    """Schritt 7b: Kanten zwischen semantisch nahen Wissensobjekten; sehr nahe fremde Paare → dublette:moeglich.
    Seit 0.20.0 inkrementell: nur noch nicht verglichene Vektoren gegen alle (O(neu × alle) statt O(alle²); gemessen 9,6 s für 3.312 Vektoren
    beim vollen Vergleich, das wüchse mit dem Confluence-Import quadratisch)."""
    _table()
    ids, m = _matrix(all_())
    with g.lock:
        new_ids = {r[0] for r in g.db().execute("SELECT id FROM vektor WHERE verglichen = 0")}
    pos = {oid: i for i, oid in enumerate(ids)}
    new = sorted(pos[o] for o in new_ids if o in pos)
    is_new = np.zeros(len(ids), dtype=bool)
    is_new[new] = True
    edges = duplicates = 0
    for i in new:  # zeilenweise: der Speicher wächst nicht mit dem Quadrat der Objektzahl
        proximity = m @ m[i]
        proximity[i] = -1.0
        proximity[is_new & (np.arange(len(ids)) < i)] = -1.0  # Paare zweier neuer Vektoren nur einmal
        nearby = np.nonzero(proximity >= PROXIMITY_EDGE)[0]
        if len(nearby) > PROXIMITY_MAX:
            nearby = nearby[np.argsort(-proximity[nearby])[:PROXIMITY_MAX]]
        for k in nearby:
            j, c = int(k), float(proximity[k])
            a, b = g.load(ids[min(i, j)]), g.load(ids[max(i, j)])
            if not a or not b:
                continue
            with g.lock:
                already = g.db().execute("SELECT 1 FROM kante WHERE a = ? AND b = ?", (a.id, b.id)).fetchone()
            if not already:
                a.link(b.id, f"semantisch ähnlich (cos {c:.2f})")
                edges += 1
            if c >= PROXIMITY_DUPLICATE and a.instance != b.instance:
                for o in (a, b):
                    if "dublette:moeglich" not in o.hashtags:
                        o.hashtags = o.hashtags + ["dublette:moeglich"]
                        o.change("vi", "dublette:moeglich", f"cos {c:.2f} zu {(b if o is a else a).id} (andere Instanz) — zusammenlegen entscheidet eine Instanz")
                        g.save(o)
                duplicates += 1
    with g.lock:
        g.db().executemany("UPDATE vektor SET verglichen = 1 WHERE id = ?", [(ids[i],) for i in new])
        g.db().commit()
    return {"kanten_neu": edges, "dubletten_moeglich": duplicates, "vektoren": len(ids), "neu_verglichen": len(new), "gekappt": cap()}


def cap(per_object: int | None = None) -> int:
    """Semantische Kanten auf gegenseitige nächste Nachbarn begrenzen (mutual kNN): Ein Paar bleibt nur, wenn jede Seite die andere unter
    ihren `je_objekt` ähnlichsten hat — so hat kein Objekt mehr als `je_objekt` semantische Kanten (bei Gleichstand entscheidet die Id).
    Belege und Hashtag-Kanten bleiben unberührt; semantische Kanten sind abgeleitet und jederzeit neu berechenbar.
    Liefert die Zahl gelöschter Zeilen (beide Richtungen gezählt) — nichts verschwindet still."""
    n = per_object or PROXIMITY_MAX
    with g.lock:
        db = g.db()
        if not db.execute("SELECT 1 FROM kante WHERE grund LIKE 'semantisch%' GROUP BY a HAVING COUNT(*) > ? LIMIT 1", (n,)).fetchone():
            return 0  # schon begrenzt
        db.execute("DROP TABLE IF EXISTS temp.behalte")
        db.execute("CREATE TEMP TABLE behalte AS SELECT a, b FROM (SELECT a, b, ROW_NUMBER() OVER (PARTITION BY a ORDER BY grund DESC, b) r "
                   "FROM kante WHERE grund LIKE 'semantisch%') WHERE r <= ?", (n,))
        db.execute("CREATE INDEX temp.behalte_ab ON behalte (a, b)")
        deleted = db.execute("DELETE FROM kante WHERE grund LIKE 'semantisch%' AND NOT ("
                               "EXISTS (SELECT 1 FROM behalte k WHERE k.a = kante.a AND k.b = kante.b) AND "
                               "EXISTS (SELECT 1 FROM behalte k WHERE k.a = kante.b AND k.b = kante.a))").rowcount
        db.execute("DROP TABLE temp.behalte")
        db.commit()
    if deleted:
        log(f"Vektoren: {deleted} semantische Kanten gekappt (höchstens {n} nächste Nachbarn je Objekt)")
    return deleted


def similar(text: str, candidates: list[str], limit: int = 10) -> list[tuple[str, float]]:
    """Freitext jetzt einbetten und Kandidaten nach Kosinus ordnen (dauert — nur auf ausdrücklichen Wunsch)."""
    q = np.asarray(embed_texts([text])[0], dtype=np.float32)
    n = float(np.linalg.norm(q)) or 1.0
    vs = all_()
    ids, m = _matrix({k: vs[k] for k in candidates if k in vs and len(vs[k]) == len(q)})
    if not ids:
        return []
    proximity = m @ (q / n)
    return sorted(((ids[i], float(proximity[i])) for i in range(len(ids))), key=lambda x: -x[1])[:limit]
