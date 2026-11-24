"""24.11.2026: reads of committed state run on their own SQLite connections (memory.reading), beside the one writing connection and
outside the global lock — under session churn every read had waited for that lock (production 0.71.1: 180 threads)."""
import threading

from vi_mcp import memory as g


def test_a_read_does_not_wait_for_the_global_lock(gd):
    o = g.new_object("insight", "Backups run at 02:00", ["topic:backup"], {}, instance="a")
    held, release = threading.Event(), threading.Event()

    def writer():  # a long write holds the lock
        with g.lock:
            held.set()
            release.wait(5)
    t = threading.Thread(target=writer)
    t.start()
    held.wait(2)
    try:
        got = []
        r = threading.Thread(target=lambda: got.append(g.load_many([o.id])))
        r.start()
        r.join(2)
        assert not r.is_alive() and o.id in got[0]  # finished while the lock was held
    finally:
        release.set()
        t.join(5)


def test_no_read_keeps_an_old_snapshot(gd):
    """A result read only partly and still referenced keeps SQLite's read snapshot open, and later reads on that pooled connection
    would miss newer commits — every pooled result is read whole and its statement closed (memory._Rows)."""
    for i in range(3):
        g.new_object("insight", f"first {i}", ["topic:x"], {}, instance="a")
    kept = []
    for _ in range(g.READERS):  # on every pooled connection: a result read only to its first row, kept alive
        with g.reading() as con:
            rows = con.execute("SELECT id FROM object")
            next(iter(rows))
            kept.append(rows)
    b = g.new_object("insight", "second", ["topic:x"], {}, instance="a")  # committed afterwards
    for _ in range(g.READERS + 1):
        with g.reading() as con:
            assert con.execute("SELECT id FROM object WHERE id = ?", (b.id,)).fetchone() == (b.id,)


def test_an_uncommitted_change_is_read_through_the_writing_connection(gd):
    o = g.new_object("insight", "draft", ["topic:x"], {}, instance="a")
    with g.lock:
        g.db().execute("UPDATE object SET text = 'changed, not committed' WHERE id = ?", (o.id,))
        assert g.db().in_transaction
        with g.reading() as con:  # falls back to the writing connection (an RLock: same thread)
            assert con.execute("SELECT text FROM object WHERE id = ?", (o.id,)).fetchone() == ("changed, not committed",)
        g.db().commit()
    with g.reading() as con:
        assert con.execute("SELECT text FROM object WHERE id = ?", (o.id,)).fetchone() == ("changed, not committed",)


def test_the_pool_is_closed_with_the_database(gd, tmp_path):
    assert g._readers is not None and g._readers.qsize() == g.READERS
    g.close_db()
    assert g._readers is None
    g.open_db(tmp_path / "other.db")  # gd's teardown closes this one
    assert g._readers is not None
