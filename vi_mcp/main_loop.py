"""The loop — exactly one, because there is exactly one server process.

Every LOOP_S seconds: delete expired answers, condense repeated errors into rules (mode test) —
across all instances; if the error occurred at ≥ 2 instances, the rule carries `kollektiv:ja` —, unanswered
questions become `abgelaufen` after 7 days,
save open conversations, close idle conversations as `abgelaufen`, checkpoint the WAL.
Errors of a run are counted and named in the status — nothing vanishes silently.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from . import memory as g
from .log_output import log

LOOP_S = 60
ERROR_RULE_MIN = 3
progress = {"laeufe": 0, "zuletzt": None, "regeln_neu": 0, "fehler": 0, "letzter_fehler": None, "schlaf_zuletzt": None}
_halt = threading.Event()


def step() -> int:
    from . import questions, intuition, session
    new = 0
    bound = (datetime.now(timezone.utc) - timedelta(seconds=intuition.TTL_MAX)).isoformat(timespec="seconds")
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    with g.lock:
        old = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE art = 'antwort' AND zeit < ?", (bound,))]
        g.delete(old)
        rows = g.db().execute(
            "SELECT t1.tag, t2.tag, COUNT(*), COUNT(DISTINCT o.instanz), group_concat(DISTINCT o.instanz) "
            "FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag LIKE 'tool:%' "
            "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag LIKE 'fehler:%' WHERE o.art = 'erfahrung' AND o.zeit >= ? "
            "GROUP BY t1.tag, t2.tag HAVING COUNT(*) >= ?", (since, ERROR_RULE_MIN)).fetchall()
        for tool_tag, error_tag, n, n_inst, instances in rows:
            rid = f"regel:{g.hash_value(tool_tag, error_tag, 'wiederholter-fehler')}"
            collective = n_inst >= 2
            o = g.load(rid)
            data = {"treffer": n, "instanzen": sorted((instances or "").split(",")),
                     "quelle": "loop: experiences of the last 24 h" + (f" at {n_inst} instances" if collective else "")}
            if o is None:
                g.new_object("regel", f"{tool_tag[5:]} failed {n}× in 24 h the same way ({error_tag[7:]})"
                                        + (f", at {n_inst} instances" if collective else "")
                                        + " — check arguments or reachability before the next call",
                               [tool_tag, f"skill:{tool_tag[5:].split('_')[0]}", error_tag, "regelart:wiederholter-fehler", "modus:test",
                                f"kollektiv:{'ja' if collective else 'nein'}"],
                               data, importance=2, oid=rid, mode="test",
                               reason=f"{n} identical errors in 24 h")  # author: the server (instance vi), no conversation
                new += 1
            elif o.data.get("treffer") != n or o.data.get("instanzen") != data["instanzen"]:
                o.data.update(data)
                o.hashtags = [t for t in o.hashtags if not t.startswith("kollektiv:")] + [f"kollektiv:{'ja' if collective else 'nein'}"]
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
                progress["letzter_fehler"] = f"{g.now()} sleep: {type(exc).__name__}: {exc}"[:300]
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
        except Exception as exc:  # noqa: BLE001 — counted and named in the status
            progress["fehler"] += 1
            progress["letzter_fehler"] = f"{g.now()} {type(exc).__name__}: {exc}"[:300]
            log(f"Loop error: {exc}")


def launch() -> threading.Thread:
    _halt.clear()
    th = threading.Thread(target=_run, name="vi-loop", daemon=True)
    th.start()
    return th


def stop_background() -> None:
    _halt.set()
