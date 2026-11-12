"""Vectors — meaning instead of identical words (stage 3, docs/TRAINING.md 4c; Park et al. 2023, section 4.1: relevance
= cosine similarity of the embeddings).

Otherwise `vi_recall` only finds what carries the same hashtags or words. An embedding service (OpenAI-compatible,
`/v1/embeddings`) turns the text of every shared knowledge object into a vector; stored as a float32 BLOB in the
table `vektor` (4 bytes per dimension, no extension — TRAINING.md 4c, way 1). Because the service on the host
needs several seconds per request (measured 08.11.2026), this happens **during sleep**, in batches, never in `vi_before`:
  step 7_vektoren  add missing vectors for erkenntnis/regel/suche/skill (at most CATCHUP_MAX_S seconds per sleep)
  step 7b_naehe    pairs with cosine ≥ PROXIMITY_EDGE get an edge "semantisch ähnlich (cos 0.91)";
                   pairs ≥ PROXIMITY_DUPLICATE without a common instance are marked `dublette:moeglich` (not
                   merged — a human or a second instance decides that)
Plus `vi_recall(filter, semantisch=true)`: embeds the free text **now** (takes time, stated in the result) and
orders the candidates by cosine, fused with the full-text search (rank fusion, tools.RRF_K) — explicitly, never automatically.
Without the `embed` configuration nothing happens; sleep reports the step as skipped (named).
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
#: Time limit instead of count: a sleep should not embed for hours, the rest follows in the next one (measured about 1.5 s per text)
CATCHUP_MAX_S = 300
#: 0.20.5: Pause after each batch, as a share of its duration (1.0 = at most half load), for shared embedding services.
#: Default 0 = unthrottled (user's decision, 09.11.); switch on via config embed.pause_anteil.
PAUSE_SHARE = 0.0
PROXIMITY_EDGE = 0.85
PROXIMITY_DUPLICATE = 0.95
#: 0.20.6: at most this many semantic neighbours per new vector. Without a limit the Confluence import linked nearly identical template pages
#: all with each other: 2.24 million edges, up to 1,316 per object, 96 s per proximity step (measured 09.11. 07:41 UTC).
PROXIMITY_MAX = 10
VECTOR_KINDS = ("erkenntnis", "regel", "suche", "skill", "bild", "seite")  # bild: its key statement
TIMEOUT_S = 120

#: Configuration: {"url": "https://host/embed/v1/embeddings", "token": "...", "model": "..."} or None
config: dict | None = None
#: Replaceable embedding function (tests): texts → list of vectors
embed_fn = None


def _table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS vektor (id TEXT PRIMARY KEY, dim INTEGER NOT NULL, modell TEXT NOT NULL, "
                       "zeit TEXT NOT NULL, roh BLOB NOT NULL)")
        # 0.20.0: verglichen = 1 once the vector's proximity edges are computed (a newly embedded vector starts at 0)
        if "verglichen" not in {r[1] for r in g.db().execute("PRAGMA table_info(vektor)")}:
            g.db().execute("ALTER TABLE vektor ADD COLUMN verglichen INTEGER NOT NULL DEFAULT 0")
        g.db().commit()


def available() -> bool:
    return embed_fn is not None or bool(config and config.get("url"))


def embed_texts(texts: list[str], timeout: float | None = None) -> list[list[float]]:
    if embed_fn is not None:
        return embed_fn(texts)
    if not config or not config.get("url"):
        raise RuntimeError("no embedding service configured (config embed.url)")
    header = {"Content-Type": "application/json"}
    if config.get("token"):
        header["Authorization"] = f"Bearer {config['token']}"
    body = {"input": texts}
    if config.get("model"):  # 0.51.0: config key model (modell in older files, translated by config.normalize)
        body["model"] = config["model"]
    req = urllib.request.Request(config["url"], data=json.dumps(body).encode(), headers=header)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # host service, never via a corporate proxy
    with op.open(req, timeout=timeout or TIMEOUT_S) as a:
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
    """Normalized vectors of the most common dimension (a model change leaves other lengths behind)."""
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
    """Archived objects need no vector; after restoring, sleep adds it again."""
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
    """How many of the IDs have a vector (without loading the vectors)."""
    _table()
    with g.lock:
        all_ids = {r[0] for r in g.db().execute("SELECT id FROM vektor")}
    return len(all_ids & set(ids))


def catch_up(max_s: float | None = None) -> dict:
    """Sleep step 7: compute missing vectors of shared knowledge objects, newest first, at most CATCHUP_MAX_S seconds per sleep."""
    if not available():
        return {"zustand": "uebersprungen", "grund": "no embedding service configured (config embed)"}
    _table()
    with g.lock:
        missing = g.db().execute(
            f"SELECT o.id, o.text FROM objekt o LEFT JOIN vektor v ON v.id = o.id WHERE v.id IS NULL AND o.art IN ({','.join('?' * len(VECTOR_KINDS))}) "
            "AND o.modus NOT IN ('widerlegt', 'archiviert', 'quarantaene') AND length(o.text) > 0 ORDER BY o.zeit DESC", VECTOR_KINDS).fetchall()
    n, error, end, paused = 0, None, time.monotonic() + (CATCHUP_MAX_S if max_s is None else max_s), 0.0
    model = (config or {}).get("model") or "embed"
    for i in range(0, len(missing), BATCH):
        if time.monotonic() > end:
            break  # the rest follows in the next sleep; "offen" names it
        part = missing[i:i + BATCH]
        t_batch = time.monotonic()
        try:
            vs = embed_texts([t for _, t in part])
        except (urllib.error.URLError, OSError, KeyError, ValueError, RuntimeError) as e:
            error = f"{type(e).__name__}: {e}"
            log(f"Vectors: batch failed — {error}")
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
    """Step 7b: edges between semantically close knowledge objects; very close pairs of different instances → dublette:moeglich.
    Incremental since 0.20.0: only not yet compared vectors against all (O(new × all) instead of O(all²); measured 9.6 s for 3,312 vectors
    with the full comparison, which would grow quadratically with the Confluence import)."""
    _table()
    ids, m = _matrix(all_())
    with g.lock:
        new_ids = {r[0] for r in g.db().execute("SELECT id FROM vektor WHERE verglichen = 0")}
    pos = {oid: i for i, oid in enumerate(ids)}
    new = sorted(pos[o] for o in new_ids if o in pos)
    is_new = np.zeros(len(ids), dtype=bool)
    is_new[new] = True
    edges = duplicates = 0
    for i in new:  # row by row: memory does not grow with the square of the object count
        proximity = m @ m[i]
        proximity[i] = -1.0
        proximity[is_new & (np.arange(len(ids)) < i)] = -1.0  # pairs of two new vectors only once
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
                a.link(b.id, f"semantisch ähnlich (cos {c:.2f})")  # label parsed: LIKE 'semantisch%', ORDER BY grund
                edges += 1
            if c >= PROXIMITY_DUPLICATE and a.instance != b.instance:
                for o in (a, b):
                    if "dublette:moeglich" not in o.hashtags:
                        o.hashtags = o.hashtags + ["dublette:moeglich"]
                        o.change("vi", "dublette:moeglich", f"cos {c:.2f} to {(b if o is a else a).id} (other instance) — an instance decides whether to merge")
                        g.save(o)
                duplicates += 1
    with g.lock:
        g.db().executemany("UPDATE vektor SET verglichen = 1 WHERE id = ?", [(ids[i],) for i in new])
        g.db().commit()
    return {"kanten_neu": edges, "dubletten_moeglich": duplicates, "vektoren": len(ids), "neu_verglichen": len(new), "gekappt": cap()}


def cap(per_object: int | None = None) -> int:
    """Limit semantic edges to mutual nearest neighbours (mutual kNN): a pair stays only if each side has the other among
    its `per_object` most similar — so no object has more than `per_object` semantic edges (on a tie the id decides).
    Evidence and hashtag edges stay untouched; semantic edges are derived and can be recomputed at any time.
    Returns the number of deleted rows (both directions counted) — nothing vanishes silently."""
    n = per_object or PROXIMITY_MAX
    with g.lock:
        db = g.db()
        if not db.execute("SELECT 1 FROM kante WHERE grund LIKE 'semantisch%' GROUP BY a HAVING COUNT(*) > ? LIMIT 1", (n,)).fetchone():
            return 0  # already limited
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
        log(f"Vectors: {deleted} semantic edges capped (at most {n} nearest neighbours per object)")
    return deleted


def similar(text: str, candidates: list[str], limit: int = 10, timeout: float | None = None) -> list[tuple[str, float]]:
    """Embed free text now and order candidates by cosine (vi_recall: by default since 0.57.0, with QUERY_TIMEOUT_S)."""
    q = np.asarray(embed_texts([text], timeout=timeout)[0], dtype=np.float32)
    n = float(np.linalg.norm(q)) or 1.0
    vs = all_()
    ids, m = _matrix({k: vs[k] for k in candidates if k in vs and len(vs[k]) == len(q)})
    if not ids:
        return []
    proximity = m @ (q / n)
    return sorted(((ids[i], float(proximity[i])) for i in range(len(ids))), key=lambda x: -x[1])[:limit]


# ── 0.57.0: cross-encoder reranker (optional) ──────────────────────────────────────────────────────────────────────────────────────
#: the query's vector within this time, else vi_recall falls back to full text (named): the embedding service is shared — measured
#: 09.11.2026, a live request waited ~20 s while a batch was embedded
QUERY_TIMEOUT_S = 8.0
#: Configuration: {"url": "https://host/rerank/v1/rerank", "token": "...", "model": "..."} or None (config key rerank)
rerank_config: dict | None = None
#: how many of the best hybrid hits the reranker orders (it-aikb: the reranker judges against the question alone)
RERANK_TOP = 30
RERANK_TIMEOUT_S = 15.0
RERANK_CHARS = 2000
#: Replaceable rerank function (tests): (query, documents) -> scores
rerank_fn = None


def rerank_available() -> bool:
    return rerank_fn is not None or bool(rerank_config and rerank_config.get("url"))


def rerank_scores(query: str, documents: list[str]) -> list[float]:
    """Relevance of each document for the query from a cross-encoder (llama.cpp /v1/rerank, Jina/Cohere form). Raises on failure."""
    if rerank_fn is not None:
        return rerank_fn(query, documents)
    header = {"Content-Type": "application/json"}
    if rerank_config.get("token"):
        header["Authorization"] = f"Bearer {rerank_config['token']}"
    body = {"query": query, "documents": [d[:RERANK_CHARS] for d in documents], "top_n": len(documents)}
    if rerank_config.get("model"):
        body["model"] = rerank_config["model"]
    req = urllib.request.Request(rerank_config["url"], data=json.dumps(body).encode(), headers=header)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=RERANK_TIMEOUT_S) as a:
        d = json.load(a)
    scores = [float("-inf")] * len(documents)
    for item in d.get("results", []):
        scores[int(item["index"])] = float(item["relevance_score"])
    return scores
