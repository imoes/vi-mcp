"""0.70.4: vectors of a large external index are computed on another host and imported — the shared embedding service stays free.

`vi-mcp vectors export --index X --out DIR [--reference N]` writes the texts the VI itself would embed (`object.text`, the same objects
sleep step 7 would choose if the index were normal) as `texts.jsonl` ({"id", "text"}), and N reference vectors computed by THIS
server's embedding service (`reference.npy` + `reference_ids.txt`), so the other host can compare before it sends anything back.

`vi-mcp vectors import --index X --ids FILE --vectors FILE.npy [--check N] [--dry-run]` stores them. Fixed rules decide, nothing is
written when one fails:
- the index has a search scope (`named` or `external`) — a normal index is embedded by sleep itself, two sources for one vector of
  the same object would be two definitions of it;
- one vector per id, all of the stored dimension, finite and not zero;
- every id is an object of that index (other ids are counted with their class, not stored);
- the check: N seeded ids are embedded again by this server's service and must agree with the imported vector to a cosine of at least
  CHECK_MIN_COS (another model, quantization or pooling shows up here, not later as a silently worse search).
Imported vectors are stored with compared = 1: an index with a search scope gets no proximity edges (vector.proximity_edges)."""
from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np

from . import memory as g
from . import vector

CHECK_MIN_COS = 0.999
CHECK_DEFAULT = 50
BATCH = 2000


def _scope(index: str) -> int:
    with g.lock:
        r = g.db().execute("SELECT explicit FROM vi_index WHERE name = ?", (index,)).fetchone()
    return int(r[0]) if r else g.SCOPE_ALL


def _texts(index: str) -> list[tuple[str, str]]:
    with g.lock:
        return [tuple(r) for r in g.db().execute(
            f"SELECT id, text FROM object WHERE idx = ? AND kind IN ({','.join('?' * len(vector.VECTOR_KINDS))}) "
            "AND mode NOT IN ('refuted', 'withdrawn', 'archived', 'quarantine') AND length(text) > 0 ORDER BY id",
            (index, *vector.VECTOR_KINDS)).fetchall()]


def export(index: str, out: Path, reference: int = 0, seed: int = 7) -> dict:
    """texts.jsonl of the index (and N reference vectors of this server's service)."""
    if _scope(index) == g.SCOPE_ALL:
        raise ValueError(f"index {index} has no search scope — sleep embeds it itself (vi_indexes scope=external first)")
    rows = _texts(index)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "texts.jsonl", "w", encoding="utf-8") as f:
        for oid, text in rows:
            f.write(json.dumps({"id": oid, "text": text}, ensure_ascii=False) + "\n")
    res = {"index": index, "texts": len(rows), "out": str(out)}
    if reference:
        pick = random.Random(seed).sample(rows, min(reference, len(rows)))
        vs = vector.embed_texts([t for _, t in pick], timeout=300)
        np.save(out / "reference.npy", np.asarray(vs, dtype=np.float32))
        (out / "reference_ids.txt").write_text("\n".join(oid for oid, _ in pick) + "\n", encoding="utf-8")
        res["reference"] = len(pick)
    return res


def _stored_dim() -> int | None:
    vector._table()  # a fresh memory has no vector table yet
    with g.lock:
        r = g.db().execute("SELECT dim, COUNT(*) FROM vector GROUP BY dim ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    return int(r[0]) if r else None


def import_(index: str, ids_file: Path, vectors_file: Path, check: int = CHECK_DEFAULT, dry_run: bool = False, seed: int = 7) -> dict:
    """Store externally computed vectors of an index with a search scope — all or nothing (see the module docstring)."""
    scope = _scope(index)
    if scope == g.SCOPE_ALL:
        raise ValueError(f"index {index} has no search scope — sleep embeds it itself; set vi_indexes scope=external first")
    ids = [x.strip() for x in Path(ids_file).read_text(encoding="utf-8").splitlines() if x.strip()]
    m = np.load(vectors_file, mmap_mode="r")
    if m.ndim != 2 or m.shape[0] != len(ids):
        raise ValueError(f"shape {m.shape} does not match {len(ids)} ids")
    if len(set(ids)) != len(ids):
        raise ValueError("an id occurs twice")
    dim = _stored_dim()
    if dim is not None and m.shape[1] != dim:
        raise ValueError(f"dimension {m.shape[1]}, the stored vectors have {dim}")
    norms = np.linalg.norm(np.asarray(m, dtype=np.float32), axis=1)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0):
        raise ValueError(f"{int(np.sum(~np.isfinite(norms) | (norms == 0)))} vectors are not finite or zero")
    known = dict(_texts(index))
    rows = [(i, k) for k, i in enumerate(ids) if i in known]
    unknown = [i for i in ids if i not in known]  # counted and named, never stored: an id of another index or a gone object
    res = {"index": index, "scope": {v: k for k, v in g.SCOPES.items()}[scope], "ids": len(ids), "dim": int(m.shape[1]),
           "matching": len(rows), "not_in_index": len(unknown), "not_in_index_examples": unknown[:5]}
    if check:
        pick = random.Random(seed).sample(rows, min(check, len(rows)))
        if pick:
            ref = np.asarray(vector.embed_texts([known[i] for i, _ in pick], timeout=300), dtype=np.float32)
            got = np.asarray(m[[k for _, k in pick]], dtype=np.float32)
            cos = np.sum(ref * got, axis=1) / (np.linalg.norm(ref, axis=1) * np.linalg.norm(got, axis=1))
            res["check"] = {"n": len(pick), "min_cos": round(float(cos.min()), 5), "median_cos": round(float(np.median(cos)), 5),
                            "required": CHECK_MIN_COS}
            if float(cos.min()) < CHECK_MIN_COS:
                res["refused"] = (f"check failed: min cosine {cos.min():.5f} < {CHECK_MIN_COS} against this server's embedding service "
                                  "(another model, quantization or pooling?) — nothing stored")
                return res
    else:
        res["check"] = "skipped (--check 0)"
    if dry_run:
        res["stored"] = 0
        res["dry_run"] = True
        return res
    model = (vector.config or {}).get("model") or "embed"
    vector._table()
    stored = 0
    for s in range(0, len(rows), BATCH):
        part = rows[s:s + BATCH]
        data = [(i, int(m.shape[1]), model, g.now(), vector._pack(np.asarray(m[k], dtype=np.float32)), 1) for i, k in part]
        with g.lock:
            g.db().executemany("INSERT OR REPLACE INTO vector (id, dim, model, ts, raw, compared) VALUES (?,?,?,?,?,?)", data)
            g.db().commit()
        stored += len(part)
    vector._invalidate()
    res["stored"] = stored
    return res


def main(argv: list[str]) -> int:
    """vi-mcp vectors export|import — see the module docstring."""
    import argparse
    from . import config
    a = argparse.ArgumentParser(prog="vi-mcp vectors", description="vectors of an external index: export texts, import vectors")
    sub = a.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="the texts the VI would embed, and reference vectors of this server")
    e.add_argument("--index", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--reference", type=int, default=200, help="reference vectors computed here (0 = none)")
    i = sub.add_parser("import", help="store vectors computed elsewhere — checked, all or nothing")
    i.add_argument("--index", required=True)
    i.add_argument("--ids", required=True, help="one object id per line, in the order of the rows")
    i.add_argument("--vectors", required=True, help="a float32 .npy matrix, one row per id")
    i.add_argument("--check", type=int, default=CHECK_DEFAULT, help="ids embedded again here and compared (0 = skip)")
    i.add_argument("--dry-run", action="store_true")
    o = a.parse_args(argv)
    k = config.load()
    vector.config = k.embed
    g.open_db(k.db)
    try:
        if o.cmd == "export":
            r = export(o.index, Path(o.out), o.reference)
        else:
            r = import_(o.index, Path(o.ids), Path(o.vectors), o.check, o.dry_run)
    except ValueError as ex:
        print(json.dumps({"refused": str(ex)}, ensure_ascii=False))
        return 2
    finally:
        g.close_db()
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 1 if r.get("refused") else 0
