"""Content as a feature — the router weights hints not only by situation but also by meaning.

Nothing is embedded live (that costs about 1 s per text). Instead, sleep precomputes two things:
  Centroids     per trigger hashtag (tool:, skill:, host:, thema:) the mean of the vectors of all knowledge objects with this hashtag.
                Feature `naehe` = cosine between the hint and the mean of the centroids of the current triggers.
                The hint itself is subtracted so that it does not confirm itself.
  Groups        K-means over the vectors of the knowledge objects. Feature `inhalt:<n>`: the model learns weights per meaning group,
                a new hint inherits them before it has experience of its own. Each group is named after its most frequent hashtags.
Both are recomputed at night; the model is trained afterwards in the same night, so the group numbers match the weights.
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter

import numpy as np

from . import memory as g
from . import vector

TRIGGER_KINDS = ("tool:", "skill:", "host:", "thema:")
MIN_CENTROID = 3
MIN_GROUP_OBJECTS = 20
GROUPS_MAX = 40
CACHE_S = 300

_lock = threading.Lock()
_cache: dict = {"zeit": 0.0}


def _tables() -> None:
    with g.lock:
        g.db().executescript("""
            CREATE TABLE IF NOT EXISTS zentrum (tag TEXT PRIMARY KEY, n INTEGER NOT NULL, summe BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS inhalt_gruppe (id TEXT PRIMARY KEY, gruppe INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS inhalt_gruppe_name (gruppe INTEGER PRIMARY KEY, name TEXT NOT NULL, n INTEGER NOT NULL);
        """)
        g.db().commit()


def _normalized() -> tuple[list[str], np.ndarray]:
    return vector._matrix(vector.all_())


def _tags(ids: list[str]) -> dict[str, list[str]]:
    outputs: dict[str, list[str]] = {}
    with g.lock:
        for i in range(0, len(ids), 900):
            part = ids[i:i + 900]
            for oid, tag in g.db().execute(f"SELECT objekt_id, tag FROM tag WHERE objekt_id IN ({','.join('?' * len(part))})", part):
                outputs.setdefault(oid, []).append(tag)
    return outputs


def compute() -> dict:
    """Sleep: recompute centroids and groups. Without vectors skipped with a named reason."""
    _tables()
    ids, m = _normalized()
    if not ids:
        return {"zustand": "uebersprungen", "grund": "no vectors"}
    tags = _tags(ids)
    sums: dict[str, np.ndarray] = {}
    count: Counter = Counter()
    for i, oid in enumerate(ids):
        for t in tags.get(oid, []):
            if t.startswith(TRIGGER_KINDS):
                sums[t] = sums.get(t, 0) + m[i]
                count[t] += 1
    centroids = [(t, count[t], vector._pack(s)) for t, s in sums.items() if count[t] >= MIN_CENTROID]
    report = {"zentren": len(centroids), "objekte": len(ids)}
    groups: list[tuple[str, int]] = []
    names: list[tuple[int, str, int]] = []
    if len(ids) >= MIN_GROUP_OBJECTS:
        try:
            from sklearn.cluster import MiniBatchKMeans
        except ImportError as e:
            report["gruppen"] = f"uebersprungen: scikit-learn missing ({e.name})"
        else:
            k = int(min(GROUPS_MAX, max(2, round((len(ids) / 2) ** 0.5))))
            km = MiniBatchKMeans(n_clusters=k, random_state=7, n_init=3, batch_size=1024).fit(m)
            groups = [(oid, int(c)) for oid, c in zip(ids, km.labels_)]
            per_tool_rate: dict[int, Counter] = {}
            for oid, c in groups:
                per_tool_rate.setdefault(c, Counter()).update(t for t in tags.get(oid, []) if t.startswith(TRIGGER_KINDS + ("skill:",)) and not t.startswith("host:"))
            size = Counter(c for _, c in groups)
            names = [(c, ", ".join(t for t, _ in per_tool_rate.get(c, Counter()).most_common(3)) or "no hashtags", size[c]) for c in sorted(size)]
            report["gruppen"] = k
    with g.lock:
        g.db().execute("DELETE FROM zentrum")
        g.db().executemany("INSERT INTO zentrum (tag, n, summe) VALUES (?,?,?)", centroids)
        if groups:
            g.db().execute("DELETE FROM inhalt_gruppe")
            g.db().execute("DELETE FROM inhalt_gruppe_name")
            g.db().executemany("INSERT INTO inhalt_gruppe (id, gruppe) VALUES (?,?)", groups)
            g.db().executemany("INSERT INTO inhalt_gruppe_name (gruppe, name, n) VALUES (?,?,?)", names)
        g.db().commit()
    forget_cache()
    return {"zustand": "fertig", **report}


def forget_cache() -> None:
    with _lock:
        _cache.clear()
        _cache["zeit"] = 0.0


def _progress() -> dict:
    """Vectors, centroids and groups in RAM (about 4 MB per 1,000 objects), at most CACHE_S old."""
    with _lock:
        if time.time() - _cache.get("zeit", 0) < CACHE_S:
            return _cache
        _tables()
        ids, m = _normalized()
        with g.lock:
            centroids = {t: (n, vector._unpack(s, len(s) // 4)) for t, n, s in g.db().execute("SELECT tag, n, summe FROM zentrum")}
            group = dict(g.db().execute("SELECT id, gruppe FROM inhalt_gruppe").fetchall())
            names = {c: n for c, n in g.db().execute("SELECT gruppe, name FROM inhalt_gruppe_name")}
        _cache.update(zeit=time.time(), index={oid: i for i, oid in enumerate(ids)}, m=m, zentren=centroids, gruppe=group, namen=names,
                      tags=_tags(ids) if centroids else {})
        return _cache


def proximity(hid: str, triggers: list[str]) -> float | None:
    """Cosine between hint and situation. None if the hint has no vector or no trigger has a centroid."""
    s = _progress()
    i = s.get("index", {}).get(hid)
    if i is None:
        return None
    v = s["m"][i]
    own_items = set(s["tags"].get(hid, []))
    sum_total, n = None, 0
    for r in triggers:
        z = s["zentren"].get(r)
        if not z or len(z[1]) != len(v):
            continue
        cnt, vec = z
        if r in own_items:  # subtract the hint itself
            if cnt <= 1:
                continue
            vec, cnt = vec - v, cnt - 1
        sum_total = vec if sum_total is None else sum_total + vec
        n += cnt
    if sum_total is None or n == 0:
        return None
    norm = float(np.linalg.norm(sum_total))
    return round(float(np.dot(v, sum_total) / norm), 3) if norm else None


def group(hid: str) -> int | None:
    return _progress().get("gruppe", {}).get(hid)


def group_name(c: int) -> str:
    return _progress().get("namen", {}).get(c, "?")


def line() -> str:
    s = _progress()
    if not s.get("zentren") and not s.get("gruppe"):
        return "not computed yet (sleep)"
    return f"{len(s['zentren'])} centroids, {len(set(s['gruppe'].values()))} meaning groups over {len(s['gruppe'])} objects"


def groups_json() -> str:
    s = _progress()
    return json.dumps({str(c): n for c, n in sorted(s.get("namen", {}).items())}, ensure_ascii=False)
