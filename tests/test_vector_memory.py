"""24.11.2026: production 0.71.1 grew to 11–15 GB. The vector matrix was built from one bytes object per BLOB plus two full copies,
each hybrid search copied every candidate row, and the content groups and proximity edges kept or rebuilt a second full matrix of
every vector (external index included). Same results, a fraction of the memory — measured here with tracemalloc."""
import threading
import tracemalloc

import numpy as np

from vi_mcp import content
from vi_mcp import memory as g
from vi_mcp import vector


def _put(rows):
    """Write (id, vector) rows straight into the vector table (no objects needed for the matrix itself)."""
    vector._table()
    with g.lock:
        g.db().executemany("INSERT OR REPLACE INTO vector (id, dim, model, ts, raw) VALUES (?,?,?,?,?)",
                           [(oid, len(v), "t", g.now(), np.asarray(v, dtype=np.float32).tobytes()) for oid, v in rows])
        g.db().commit()
    vector._invalidate()


def _old(rows):
    """The construction before 24.11.2026: every vector unpacked, then _matrix (stack, normalized copy)."""
    return vector._matrix({oid: vector._unpack(np.asarray(v, dtype=np.float32).tobytes(), len(v)) for oid, v in rows})


def test_the_matrix_is_the_same_as_before_bit_for_bit(gd):
    rng = np.random.default_rng(1)
    rows = [(f"insight:{i:04d}", rng.standard_normal(64)) for i in range(300)]
    rows += [(f"insight:x{i}", rng.standard_normal(32)) for i in range(20)]  # a minority dimension is left out, as before
    rows.append(("insight:zero", np.zeros(64)))  # a zero vector stays zero (norm 1 used), as before
    _put(rows)
    ids, pos, m = vector.matrix()
    old_ids, old_m = _old(rows)
    assert ids == old_ids and m.dtype == np.float32 and np.array_equal(m, old_m)
    assert pos == {oid: i for i, oid in enumerate(ids)} and not any(i.startswith("insight:x") for i in ids)


def test_building_the_matrix_needs_about_one_matrix_not_three(gd):
    rng = np.random.default_rng(2)
    rows = [(f"insight:{i:05d}", rng.standard_normal(256)) for i in range(20000)]  # 20 MiB of float32
    _put(rows)
    tracemalloc.start()
    try:
        with g.lock:  # the construction before 24.11.2026, measured the same way
            raw = g.db().execute("SELECT id, dim, raw FROM vector").fetchall()
        vector._matrix({oid: vector._unpack(r, d) for oid, d, r in raw})
        del raw
        _cur, old_peak = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        _ids, _pos, m = vector.matrix()
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert m.nbytes == 20000 * 256 * 4
    # the matrix plus a fixed overhead (one chunk of rows, its norms, ids and positions) — not a multiple of the matrix
    assert peak < m.nbytes + 12 * 2**20, f"peak {peak / 2**20:.1f} MiB for a {m.nbytes / 2**20:.1f} MiB matrix"
    assert peak < old_peak / 2, f"new {peak / 2**20:.1f} MiB, before {old_peak / 2**20:.1f} MiB"


def test_similar_gives_the_same_answer_without_copying_the_candidates(gd, monkeypatch):
    rng = np.random.default_rng(3)
    rows = [(f"insight:{i:05d}", rng.standard_normal(256)) for i in range(20000)]
    _put(rows)
    q = rng.standard_normal(256).astype(np.float32)
    monkeypatch.setattr(vector, "embed_fn", lambda texts: [q.tolist()])
    ids, pos, m = vector.matrix()
    cand = [oid for oid, _ in rows[::2]] + ["insight:unknown"]  # half the rows, and one id without a vector
    got = vector.similar("free text", cand, limit=25)
    qn = q / float(np.linalg.norm(q))
    r = [pos[k] for k in cand if k in pos]
    before = m[r] @ qn  # the computation before 24.11.2026
    want = [(ids[r[i]], float(before[i])) for i in np.argsort(-before)[:25]]
    assert got == want  # same ids, same order, same cosines to the last bit
    tracemalloc.start()
    try:
        vector.similar("free text", cand, limit=25)
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    copy = len(r) * 256 * 4  # what m[rows] allocated: 10 MiB here, 445 MiB on the production copy
    assert peak < copy / 4, f"peak {peak / 2**20:.1f} MiB, the candidate copy would be {copy / 2**20:.1f} MiB"


def test_content_and_proximity_work_on_active_unscoped_rows_of_the_one_matrix(gd):
    keep = g.new_object("insight", "an active object", ["topic:a"], {}, instance="a")
    gone = g.new_object("insight", "an archived object", ["topic:a"], {}, instance="a")
    ext = g.new_object("insight", "an object of an external corpus", ["topic:a"], {}, instance="a")
    ext.idx = "corpus"
    g.save(ext)
    with g.lock:
        g.db().execute("UPDATE object SET mode = 'archived' WHERE id = ?", (gone.id,))
        g.db().execute("UPDATE vi_index SET explicit = 2 WHERE name = 'corpus'")  # scope external (0.70.4)
        g.db().commit()
    rng = np.random.default_rng(4)
    _put([(o.id, rng.standard_normal(16)) for o in (keep, gone, ext)])
    ids, pos, m = vector.matrix()
    a_ids, a_m = vector.active_matrix()
    assert a_ids == [keep.id] and np.array_equal(a_m[0], m[pos[keep.id]])
    assert content._normalized()[0] == [keep.id]  # the router feature matrix leaves the external corpus out
    with g.lock:
        g.db().execute("UPDATE vi_index SET explicit = 0 WHERE name = 'corpus'")
        g.db().execute("UPDATE object SET mode = 'active' WHERE id = ?", (gone.id,))
        g.db().commit()
    a_ids, a_m = vector.active_matrix()
    assert sorted(a_ids) == sorted(ids) and a_m is m  # nothing left out: the cached matrix itself, no copy


def test_concurrent_readers_wait_for_one_build(gd, monkeypatch):
    rng = np.random.default_rng(5)
    _put([(f"insight:{i}", rng.standard_normal(16)) for i in range(50)])
    builds = []
    real = vector._load_matrix
    gate = threading.Event()

    def slow():
        builds.append(1)
        gate.wait(2)
        return real()
    monkeypatch.setattr(vector, "_load_matrix", slow)
    out = []
    threads = [threading.Thread(target=lambda: out.append(vector.matrix()[0])) for _ in range(4)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join(10)
    assert len(builds) == 1 and len(out) == 4 and all(o == out[0] for o in out)


def test_nearest_first_gives_the_hits_of_listing_every_admitted_id_first(gd, monkeypatch):
    """24.11.2026: vector.nearest + memory.admitted replace ids_for_filter + similar in the hybrid vi_recall — the same hits."""
    rng = np.random.default_rng(6)
    objs = []
    for i in range(1200):  # more than one block (VISIBLE_CHUNK 900); private objects of another instance are not admitted
        vis, inst = ("private", "other") if i % 3 == 0 else ("shared", "a")
        kind = "rule" if i % 7 == 0 else "insight"
        objs.append(g.new_object(kind, f"object {i}", [f"topic:t{i % 4}"], {}, instance=inst, visibility=vis))
    _put([(o.id, rng.standard_normal(32)) for o in objs])
    q = rng.standard_normal(32)
    monkeypatch.setattr(vector, "embed_fn", lambda texts: [q.tolist()])
    token = g.current_instance.set("a")  # reset below: a context variable left set leaks into the next test of this thread
    try:
        for filter_text, kinds in (("", ("insight", "rule")), ("topic:t1", ()), ("(topic:t2 OR topic:t3) !topic:t3", ()), ("", ("rule",))):
            for limit in (5, 90, 2000):
                old = vector.similar("q", g.ids_for_filter(filter_text, kinds=kinds), limit=limit)
                new, checked = vector.nearest("q", lambda ids: g.admitted(ids, filter_text, kinds=kinds), limit=limit)
                assert new == old, (filter_text, kinds, limit)
                assert checked <= len(objs)
        near, checked = vector.nearest("q", lambda ids: g.admitted(ids, "", kinds=("insight", "rule")), limit=5)
        assert checked == 900  # the first block was enough: 5 admitted among the 900 nearest
    finally:
        g.current_instance.reset(token)


def test_the_per_object_filter_selects_the_same_rows_as_the_list_form(gd):
    """24.11.2026: memory._filter_sql(per_id=True) — EXISTS per object instead of IN (list) — for the queries that check a few
    hundred ids (admitted, recall's full-text pool and final query). The same rows for every kind of condition."""
    for i in range(60):
        g.new_object("rule" if i % 5 == 0 else "insight", f"backup note {i}", [f"topic:t{i % 3}", f"host:h{i % 4}"], {},
                     instance="a" if i % 2 else "b", visibility="private" if i % 7 == 0 else "shared")
    cases = [([["kind:insight", "kind:rule"]], []), ([["topic:t1"]], []), ([["topic:t1", "topic:t2"], ["host:h3"]], ["topic:t2"]),
             ([], ["host:h0"]), ([["host:h*"]], []), ([], [])]
    with g.lock:
        every = [r[0] for r in g.db().execute("SELECT id FROM object")]
        for groups, remove in cases:
            for viewer in ("a", None):
                a_sql, a_par = g._filter_sql(groups, remove, viewer)
                b_sql, b_par = g._filter_sql(groups, remove, viewer, per_id=True)
                ids = every[:40]
                q = f" AND id IN ({','.join('?' * len(ids))})"
                a = {r[0] for r in g.db().execute(a_sql + q, [*a_par, *ids])}
                b = {r[0] for r in g.db().execute(b_sql + q, [*b_par, *ids])}
                assert a == b, (groups, remove, viewer)
                assert {r[0] for r in g.db().execute(a_sql, a_par)} == {r[0] for r in g.db().execute(b_sql, b_par)}
