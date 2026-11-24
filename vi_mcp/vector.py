"""Vectors — meaning instead of identical words (stage 3, docs/TRAINING.md 4c; Park et al. 2023, section 4.1: relevance
= cosine similarity of the embeddings).

Otherwise `vi_recall` only finds what carries the same hashtags or words. An embedding service (OpenAI-compatible,
`/v1/embeddings`) turns the text of every shared knowledge object into a vector; stored as a float32 BLOB in the
table `vektor` (4 bytes per dimension, no extension — TRAINING.md 4c, way 1). Because the service on the host
needs several seconds per request (measured 08.11.2026), this happens **during sleep**, in batches, never in `vi_before`:
  step 7_vektoren  add missing vectors for erkenntnis/regel/suche/skill (at most CATCHUP_MAX_S seconds per sleep)
  step 7b_naehe    pairs with cosine ≥ PROXIMITY_EDGE get an edge "semantisch ähnlich (cos 0.91)";
                   pairs ≥ PROXIMITY_DUPLICATE without a common instance are marked `duplicate:possible` (not
                   merged — a human or a second instance decides that)
Plus `vi_recall(filter, semantisch=true)`: embeds the free text **now** (takes time, stated in the result) and
orders the candidates by cosine, fused with the full-text search (rank fusion, tools.RRF_K) — explicitly, never automatically.
Without the `embed` configuration nothing happens; sleep reports the step as skipped (named).
"""
from __future__ import annotations

import json
import threading
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
VECTOR_KINDS = ("insight", "rule", "search", "skill", "image", "page")  # bild: its key statement
TIMEOUT_S = 120

#: Configuration: {"url": "https://host/embed/v1/embeddings", "token": "...", "model": "..."} or None
config: dict | None = None
#: Replaceable embedding function (tests): texts → list of vectors
embed_fn = None


def _table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS vector (id TEXT PRIMARY KEY, dim INTEGER NOT NULL, model TEXT NOT NULL, "
                       "ts TEXT NOT NULL, raw BLOB NOT NULL)")
        # 0.20.0: compared = 1 once the vector's proximity edges are computed (a newly embedded vector starts at 0)
        if "compared" not in {r[1] for r in g.db().execute("PRAGMA table_info(vector)")}:
            g.db().execute("ALTER TABLE vector ADD COLUMN compared INTEGER NOT NULL DEFAULT 0")
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
        g.db().execute("INSERT OR REPLACE INTO vector (id, dim, model, ts, raw) VALUES (?,?,?,?,?)", (oid, len(v), model, g.now(), _pack(v)))
        g.db().commit()
    _invalidate()


def remove_entry(oid: str) -> None:
    """Archived objects need no vector; after restoring, sleep adds it again."""
    _table()
    with g.lock:
        g.db().execute("DELETE FROM vector WHERE id = ?", (oid,))
        g.db().commit()
    _invalidate()


def load(oid: str) -> np.ndarray | None:
    _table()
    with g.lock:
        row = g.db().execute("SELECT dim, raw FROM vector WHERE id = ?", (oid,)).fetchone()
    return _unpack(row[1], row[0]) if row else None


def all_() -> dict[str, np.ndarray]:
    _table()
    with g.lock:
        rows = g.db().execute("SELECT v.id, v.dim, v.raw FROM vector v JOIN object o ON o.id = v.id WHERE o.mode NOT IN ('refuted', 'withdrawn', 'archived', 'quarantine')").fetchall()
    return {oid: _unpack(raw, dim) for oid, dim, raw in rows}


def present(ids: list[str]) -> int:
    """How many of the IDs have a vector — from the cached matrix (search-top4: reading every vector id from SQLite per query cost
    hundreds of milliseconds at 500,000 objects)."""
    _ids, pos, _m = matrix()
    return sum(1 for i in set(ids) if i in pos)


#: vi_mcp.code_facts.FACT_TAGS (not imported: vector is loaded early and code_facts is not needed for anything else here)
FACT_TAGS = ("code:funktion", "code:modul", "code:konstante")


def catch_up(max_s: float | None = None) -> dict:
    """Sleep step 7: compute missing vectors of shared knowledge objects, newest first, at most CATCHUP_MAX_S seconds per sleep."""
    if not available():
        return {"zustand": "uebersprungen", "grund": "no embedding service configured (config embed)"}
    _table()
    with g.lock:
        missing = g.db().execute(
            f"SELECT o.id, o.text FROM object o LEFT JOIN vector v ON v.id = o.id WHERE v.id IS NULL AND o.kind IN ({','.join('?' * len(VECTOR_KINDS))}) "
            "AND o.mode NOT IN ('refuted', 'withdrawn', 'archived', 'quarantine') AND length(o.text) > 0 "
            # code structure facts: generated one-line summaries, found by hashtag and clingo — embedding them would only add near
            # duplicates (and proximity edges between them)
            f"AND o.id NOT IN (SELECT object_id FROM tag WHERE tag IN ({','.join('?' * len(FACT_TAGS))})) "
            # 0.70.3: an index searched only when named (a large external corpus) is not embedded in sleep — it would keep the shared
            # embedding service busy for weeks; it is found by full text when named
            "AND o.idx NOT IN (SELECT name FROM vi_index WHERE explicit <> 0) ORDER BY o.ts DESC",
            (*VECTOR_KINDS, *FACT_TAGS)).fetchall()
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
    """Step 7b: edges between semantically close knowledge objects; very close pairs of different instances → duplicate:possible.
    Incremental since 0.20.0: only not yet compared vectors against all (O(new × all) instead of O(all²); measured 9.6 s for 3,312 vectors
    with the full comparison, which would grow quadratically with the Confluence import)."""
    _table()
    with g.lock:
        # 0.70.4: objects of an index with a search scope (named only, external) get no proximity edges, neither as new vectors nor as
        # partners — a large external corpus would add O(new × all) comparisons and an edge flood; they are marked compared, counted
        skipped = g.db().execute("UPDATE vector SET compared = 1 WHERE compared = 0 AND id IN "
                                 "(SELECT o.id FROM object o WHERE o.idx IN (SELECT name FROM vi_index WHERE explicit <> 0))").rowcount
        g.db().commit()
    # 24.11.2026: the rows of the cached search matrix (active objects, scoped indexes left out), not a second full load of every
    # vector — all_() read each BLOB as its own object on every on-demand run, about a minute apart under load
    ids, m = active_matrix()
    with g.lock:
        new_ids = {r[0] for r in g.db().execute("SELECT id FROM vector WHERE compared = 0")}
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
                already = g.db().execute("SELECT 1 FROM edge WHERE a = ? AND b = ?", (a.id, b.id)).fetchone()
            if not already:
                a.link(b.id, f"semantisch ähnlich (cos {c:.2f})")  # label parsed: LIKE 'semantisch%', ORDER BY grund
                edges += 1
            if c >= PROXIMITY_DUPLICATE and a.instance != b.instance:
                for o in (a, b):
                    if "duplicate:possible" not in o.hashtags:
                        o.hashtags = o.hashtags + ["duplicate:possible"]
                        o.change("vi", "duplicate:possible", f"cos {c:.2f} to {(b if o is a else a).id} (other instance) — an instance decides whether to merge")
                        g.save(o)
                duplicates += 1
    with g.lock:
        g.db().executemany("UPDATE vector SET compared = 1 WHERE id = ?", [(ids[i],) for i in new])
        g.db().commit()
    return {"kanten_neu": edges, "dubletten_moeglich": duplicates, "vektoren": len(ids), "neu_verglichen": len(new), "gekappt": cap(),
            "scoped_skipped": skipped}


def cap(per_object: int | None = None) -> int:
    """Limit semantic edges to mutual nearest neighbours (mutual kNN): a pair stays only if each side has the other among
    its `per_object` most similar — so no object has more than `per_object` semantic edges (on a tie the id decides).
    Evidence and hashtag edges stay untouched; semantic edges are derived and can be recomputed at any time.
    Returns the number of deleted rows (both directions counted) — nothing vanishes silently."""
    n = per_object or PROXIMITY_MAX
    with g.lock:
        db = g.db()
        if not db.execute("SELECT 1 FROM edge WHERE reason LIKE 'semantisch%' GROUP BY a HAVING COUNT(*) > ? LIMIT 1", (n,)).fetchone():
            return 0  # already limited
        db.execute("DROP TABLE IF EXISTS temp.behalte")
        db.execute("CREATE TEMP TABLE behalte AS SELECT a, b FROM (SELECT a, b, ROW_NUMBER() OVER (PARTITION BY a ORDER BY reason DESC, b) r "
                   "FROM edge WHERE reason LIKE 'semantisch%') WHERE r <= ?", (n,))
        db.execute("CREATE INDEX temp.behalte_ab ON behalte (a, b)")
        deleted = db.execute("DELETE FROM edge WHERE reason LIKE 'semantisch%' AND NOT ("
                               "EXISTS (SELECT 1 FROM behalte k WHERE k.a = edge.a AND k.b = edge.b) AND "
                               "EXISTS (SELECT 1 FROM behalte k WHERE k.a = edge.b AND k.b = edge.a))").rowcount
        db.execute("DROP TABLE temp.behalte")
        db.commit()
    if deleted:
        log(f"Vectors: {deleted} semantic edges capped (at most {n} nearest neighbours per object)")
    return deleted


#: The normalized vector matrix, kept between queries (search-top4 branch, 15.11.2026). Before, every query loaded and unpacked every
#: vector from SQLite (all_()): 2.5 s median per hybrid query on a production copy with 24,811 vectors. The ranking is unchanged —
#: only where the vectors come from. Invalidated by save/remove in this process and by the table's (count, newest time) signature,
#: which another process (sleep, CLI) changes when it writes vectors. 24.11.2026: one state tuple (sig, ids, pos, m), replaced at once,
#: so a reader never mixes the ids of one build with the matrix of another; one build at a time (_build).
_cache: dict = {"state": (None, [], {}, np.zeros((0, 0), dtype=np.float32))}
_build = threading.Lock()
#: rows read per step while building the matrix
BUILD_CHUNK = 4096


def _signature() -> tuple:
    _table()
    with g.lock:
        return tuple(g.db().execute("SELECT COUNT(*), MAX(ts) FROM vector").fetchone())


def _load_matrix() -> tuple[list[str], np.ndarray]:
    """Every stored vector of the most common dimension, normalized — the same rows and values as _matrix over all vectors, built in
    one preallocated float32 array. 24.11.2026 (production 0.71.1 grew to 11–15 GB): fetchall() held every BLOB as its own 4-KiB
    bytes object, then np.stack copied them and the normalisation copied again — about three matrices at once, most of it kept by
    the allocator afterwards. Now the matrix and one chunk of rows."""
    with g.lock:
        top = g.db().execute("SELECT dim, COUNT(*) FROM vector GROUP BY dim ORDER BY COUNT(*) DESC, dim LIMIT 1").fetchone()
        if not top:
            return [], np.zeros((0, 0), dtype=np.float32)
        dim, n = int(top[0]), int(top[1])
        m = np.empty((n, dim), dtype=np.float32)
        ids: list[str] = []
        cur = g.db().execute("SELECT id, raw FROM vector WHERE dim = ?", (dim,))
        while rows := cur.fetchmany(BUILD_CHUNK):
            for oid, raw in rows:
                m[len(ids)] = np.frombuffer(raw, dtype=np.float32, count=dim)
                ids.append(oid)
    m = m[:len(ids)]
    for i in range(0, len(ids), BUILD_CHUNK):  # the norms exactly as _matrix computes them, row block by row block, divided in place
        part = m[i:i + BUILD_CHUNK]
        norms = np.linalg.norm(part, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        part /= norms
    return ids, m


def matrix() -> tuple[list[str], dict[str, int], np.ndarray]:
    """(ids, id -> row, normalized matrix) of every stored vector of the most common dimension — cached (see _cache)."""
    sig = _signature()
    state = _cache["state"]
    if state[0] != sig:
        with _build:  # a second thread waits for this build instead of building its own copy beside it
            state = _cache["state"]
            sig = _signature()
            if state[0] != sig:
                ids, m = _load_matrix()
                state = (sig, ids, {oid: i for i, oid in enumerate(ids)}, m)
                _cache["state"] = state
    return state[1], state[2], state[3]


def active_matrix() -> tuple[list[str], np.ndarray]:
    """The rows of the cached matrix for vectors of active objects outside indexes with a search scope (named only, external): what
    the proximity edges and the content groups (router features, content.py) work on. 24.11.2026: both loaded every vector themselves
    (all_(), a second full matrix), the external index included although its objects are never a hint. A copy of only these rows; the
    cached matrix itself when nothing is left out."""
    ids, pos, m = matrix()
    with g.lock:
        inside = [r[0] for r in g.db().execute(
            "SELECT v.id FROM vector v JOIN object o ON o.id = v.id WHERE o.mode NOT IN ('refuted', 'withdrawn', 'archived', 'quarantine') "
            "AND o.idx NOT IN (SELECT name FROM vi_index WHERE explicit <> 0)")]
    keep = sorted(pos[i] for i in inside if i in pos)
    if len(keep) == len(ids):
        return ids, m
    return [ids[k] for k in keep], m[keep]


def _invalidate() -> None:
    sig, ids, pos, m = _cache["state"]
    _cache["state"] = (None, ids, pos, m)


def similar(text: str, candidates: list[str], limit: int = 10, timeout: float | None = None) -> list[tuple[str, float]]:
    """Embed free text now and order candidates by cosine (vi_recall: by default since 0.57.0, with QUERY_TIMEOUT_S). Only the
    candidates count (the caller's visibility filter), so refuted or archived objects never come back through a cached vector."""
    q = np.asarray(embed_texts([text], timeout=timeout)[0], dtype=np.float32)
    n = float(np.linalg.norm(q)) or 1.0
    ids, pos, m = matrix()
    rows = np.fromiter((pos[k] for k in dict.fromkeys(candidates) if k in pos), dtype=np.int64)
    if not len(rows) or m.shape[1] != len(q):
        return []
    qn = q / n
    # 24.11.2026: (m @ q)[rows], not m[rows] @ q — the same cosines, without copying every candidate row first (445 MiB per hybrid
    # vi_recall on a production copy with 108,809 candidate vectors; concurrent searches added up). Costs one float per stored vector.
    proximity = (m @ qn)[rows]
    from . import query_adapter  # 0.68.0: learned weights on the query vector (scikit-learn), only while its offline gate says on
    qa = query_adapter.transform(qn)  # the same object while off
    order = np.argsort(-(proximity if qa is qn else (m @ qa)[rows]), kind="stable")[:limit]
    return [(ids[rows[i]], float(proximity[i])) for i in order]  # the cosine is reported, the order may come from the adapter


def nearest(text: str, admit, limit: int = 10, timeout: float | None = None) -> tuple[list[tuple[str, float]], int]:
    """The `limit` nearest vectors that `admit` lets through — the answer of similar(text, <every admitted id>, limit) without listing
    the admitted ids first. All stored vectors are ordered by closeness (one product with the cached matrix, no row copy), then
    admitted in blocks of memory.VISIBLE_CHUNK in that order until `limit` are found. admit(ids) -> the admitted subset (memory.admitted
    with the search's filter and viewer). Returns (hits as (id, cosine), how many vectors were checked).
    24.11.2026: the hybrid vi_recall listed 197,036 visible ids for every query (1.46 s of 3.05 s on a production copy, under the
    database lock); usually the first block of nearest vectors holds enough admitted ones."""
    q = np.asarray(embed_texts([text], timeout=timeout)[0], dtype=np.float32)
    n = float(np.linalg.norm(q)) or 1.0
    ids, _pos, m = matrix()
    if not ids or m.shape[1] != len(q):
        return [], 0
    qn = q / n
    proximity = m @ qn
    from . import query_adapter  # the order may come from the learned query adapter, as in similar(); the cosine is reported
    qa = query_adapter.transform(qn)
    order = np.argsort(-(proximity if qa is qn else m @ qa), kind="stable")
    out: list[tuple[str, float]] = []
    checked = 0
    for start in range(0, len(order), g.VISIBLE_CHUNK):
        block = order[start:start + g.VISIBLE_CHUNK]
        ok = admit([ids[i] for i in block])
        checked += len(block)
        for i in block:
            if ids[i] in ok:
                out.append((ids[i], float(proximity[i])))
                if len(out) >= limit:
                    return out, checked
    return out, checked


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
