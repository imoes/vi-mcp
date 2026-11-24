"""The loop — exactly one, because there is exactly one server process.

Every LOOP_S seconds: delete expired answers, condense repeated errors into rules (mode test) —
across all instances; if the error occurred at ≥ 2 instances, the rule carries `collective:yes` —, unanswered
questions become `abgelaufen` after 7 days,
save open conversations, close idle conversations as `abgelaufen`, checkpoint the WAL.
Every TRIM_S seconds (0.71.3): give the memory glibc keeps back to the system (`trim_memory`).
Errors of a run are counted and named in the status — nothing vanishes silently.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone

from . import memory as g
from .log_output import log

LOOP_S = 60
ERROR_RULE_MIN = 3
progress = {"laeufe": 0, "zuletzt": None, "regeln_neu": 0, "fehler": 0, "last_error": None, "schlaf_zuletzt": None,
            "trim_laeufe": 0, "trim_mb": 0, "trim_zuletzt_mb": None, "trim_verfuegbar": None}
_halt = threading.Event()

#: 0.71.3: glibc keeps freed memory in its arenas (one per thread, up to 8 per core; every request has its own thread) and gives
#: little of it back. Measured 24.11.2026 on a production copy under session churn (20 a minute, 46 min): Python's own memory
#: stayed flat at ~645 MB (tracemalloc) while RSS grew ~0.23 GB/h; malloc_trim(0) every 300 s gave back 924 MB the first time and
#: 120–270 MB each time after, in 28–83 ms, and kept RSS at 1.0–1.3 GB (MALLOC_ARENA_MAX=2 instead: flat at 1.8 GB).
TRIM_S = 300
_last_trim = [0.0]


def _rss_mb() -> int | None:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") // 2**20
    except (OSError, ValueError, IndexError):
        return None


def trim_memory() -> int | None:
    """malloc_trim(0): the memory glibc keeps back goes back to the system. Returns the MB freed (RSS before minus after), or None
    where there is no glibc (named in progress["trim_verfuegbar"], never an error)."""
    if progress["trim_verfuegbar"] is False:
        return None
    try:
        import ctypes
        fn = ctypes.CDLL("libc.so.6").malloc_trim
    except (OSError, AttributeError):
        progress["trim_verfuegbar"] = False
        return None
    progress["trim_verfuegbar"] = True
    before = _rss_mb()
    fn(0)
    after = _rss_mb()
    freed = before - after if before is not None and after is not None else 0
    progress.update(trim_laeufe=progress["trim_laeufe"] + 1, trim_mb=progress["trim_mb"] + max(0, freed), trim_zuletzt_mb=freed)
    return freed


def maybe_trim(now: float | None = None) -> int | None:
    """trim_memory() when TRIM_S have passed since the last one; else nothing (None)."""
    now = time.monotonic() if now is None else now
    if now - _last_trim[0] < TRIM_S:
        return None
    _last_trim[0] = now
    return trim_memory()


def step() -> int:
    from . import questions, intuition, session
    new = 0
    bound = (datetime.now(timezone.utc) - timedelta(seconds=intuition.TTL_MAX)).isoformat(timespec="seconds")
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    with g.lock:
        old = [r[0] for r in g.db().execute("SELECT id FROM object WHERE kind = 'answer' AND ts < ?", (bound,))]
        g.delete(old)
        rows = g.db().execute(
            "SELECT t1.tag, t2.tag, COUNT(*), COUNT(DISTINCT o.instance), group_concat(DISTINCT o.instance) "
            "FROM object o JOIN tag t1 ON t1.object_id = o.id AND t1.tag LIKE 'tool:%' "
            "JOIN tag t2 ON t2.object_id = o.id AND t2.tag LIKE 'error:%' WHERE o.kind = 'experience' AND o.ts >= ? "
            "GROUP BY t1.tag, t2.tag HAVING COUNT(*) >= ?", (since, ERROR_RULE_MIN)).fetchall()
        for tool_tag, error_tag, n, n_inst, instances in rows:
            rid = g.keyed_id("rule", g.hash_value(tool_tag, error_tag, "wiederholter-fehler"))
            collective = n_inst >= 2
            o = g.load(rid)
            data = {"hits": n, "instances": sorted((instances or "").split(",")),
                     "source": "loop: experiences of the last 24 h" + (f" at {n_inst} instances" if collective else "")}
            if o is None:
                g.new_object("rule", f"{tool_tag[5:]} failed {n}× in 24 h the same way ({error_tag.split(':', 1)[-1]})"
                                        + (f", at {n_inst} instances" if collective else "")
                                        + " — check arguments or reachability before the next call",
                               [tool_tag, f"skill:{tool_tag[5:].split('_')[0]}", error_tag, "rule_kind:repeated-error", "mode:test",
                                f"collective:{'yes' if collective else 'no'}"],  # 24.11.2026: was ja/nein, renamed at every start
                               data, importance=2, oid=rid, mode="test",
                               reason=f"{n} identical errors in 24 h")  # author: the server (instance vi), no conversation
                new += 1
            elif o.data.get("hits") != n or o.data.get("instances") != data["instances"]:
                o.data.update(data)
                o.hashtags = [t for t in o.hashtags if not t.startswith("collective:")] + [f"collective:{'yes' if collective else 'no'}"]
                g.save(o)
    expired_questions = questions.let_expire()
    from . import usage_stats
    usage_stats.cleanup()  # usage entries older than RETENTION_DAYS
    from . import evaluation
    evaluation.cleanup_log()  # 0.57.0: the search log, same retention
    from . import sleep_cycle
    sleep_reason = None if sleep_cycle.running() else sleep_cycle.due()
    if sleep_reason:
        # 0.20.5: own thread. Run synchronously, a sleep (measured 429–530 s, step 7 up to 1,200 s of embedding) stalled the loop and, via
        # the training lock, also training on demand: after the restart on 09.11. 06:43 the loop stood at 1 run in 20 min.
        def _sleep_bg(reason=sleep_reason):
            try:
                progress["schlaf_zuletzt"] = sleep_cycle.run(reason).text
            except sleep_cycle.AlreadyRunning:
                pass  # a sleep started by hand is still running; the next round checks again
            except Exception as exc:  # noqa: BLE001 — named in the progress state
                progress["last_error"] = f"{g.now()} sleep: {type(exc).__name__}: {exc}"[:300]
                log(f"Sleep failed: {exc}")
        threading.Thread(target=_sleep_bg, name="vi-schlaf", daemon=True).start()
    if expired_questions:
        log(f"Questions expired (no answer): {expired_questions}")
    for s in session.open_items():
        if len(s.turns) != s.secured_until:
            session.persist(s)
    expired = session.tidy_up()
    if expired:
        log(f"Conversations expired (idle): {', '.join(expired)}")
    with g.lock:
        g.db().execute("PRAGMA wal_checkpoint(PASSIVE)")
    return new


def _run() -> None:
    while not _halt.wait(LOOP_S):
        try:
            n = step()
            progress["laeufe"] += 1
            progress["zuletzt"] = g.now()
            progress["regeln_neu"] += n
            if n:
                log(f"Loop: {n} new rule(s) from experience")
            freed = maybe_trim()
            if freed is not None and freed >= 256:
                log(f"Loop: {freed} MB of memory glibc kept back returned to the system (malloc_trim)")
        except Exception as exc:  # noqa: BLE001 — counted and named in the status
            progress["fehler"] += 1
            progress["last_error"] = f"{g.now()} {type(exc).__name__}: {exc}"[:300]
            log(f"Loop error: {exc}")


def launch() -> threading.Thread:
    _halt.clear()
    th = threading.Thread(target=_run, name="vi-loop", daemon=True)
    th.start()
    return th


def stop_background() -> None:
    _halt.set()
