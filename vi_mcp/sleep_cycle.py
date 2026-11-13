"""Sleep — the consolidation run (docs/FORSCHUNG.md A4, A5, C2).

Runs in its own thread started by the loop (since 0.20.5; writes are guarded by g.lock, model and vectors by on_demand.TRAINING), once per night (SLEEP_HOUR UTC) or as soon as the sum
of the importance of new experiences since the last run exceeds THRESHOLD (Park's reflection trigger, scaled to 0–3). 0.62.0: a sleep
older than CATCHUP_H is caught up in the next quiet moment (a workstation that is off at night), and config sleep.workstation lets the
importance trigger wait for quiet too.
Steps — each one counts, each one is in the report (object `schlaf:<zeit>`, state `fertig` or `fehler`):
  1 Triage      experiences since the last run, priority = surprise + importance/3 + future relevance
  2 Replay      clusters by (host, skill) over the top experiences, plus k older ones with the same hashtags per cluster
  3 Schema      does an insight fit the cluster? same outcome → evidence edge; different → `konflikt:offen`
  4b Reflection the language model phrases at most one insight per cluster without schema (test, reviewed, evidence edges) — reflection.py
  4 Abstraction template fallback for clusters without reflection: ≥ 3 experiences on ≥ 2 days → insight (test)
  4c Skills     success after errors in the same conversation → skill (solution path); failing skills → disputed; same problems → fusion:vorschlag
  4d Scorer     rate actions by fixed features, finished conversations by the language model (scorer.py)
  5 Housekeeping unused entries and old raw transcripts go to the long-term archive (archive.py; a stub stays)
  6 Self actual recompute competence per skill, weaknesses, relations
  7 Vectors     add missing embeddings of shared knowledge objects (batch), semantic proximity → edges / dublette:moeglich
  7c Content    centroids per trigger and meaning groups for the router (content.py)
  7d Hints      recompute hint counters from the experiences, measured by the advantage over the tool without a hint (bandit.py)
  8 Learning    train the router model (learning.py)
  9 Report
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import memory as g
from . import self_model
from .log_output import log

SLEEP_HOUR = 3
#: 0.21.1: 40 → 80 and at most every MIN_GAP_MIN minutes. Measured 08./09.11.: 45 sleeps in 24 h (median 83 s), only 3 new insights
#: in total — sleep ran almost every half hour and loaded the language model without delivering much (vi_stats, F).
THRESHOLD = 80
MIN_GAP_MIN = 120
TOP_N = 200
REPLAY_OLD = 5
CLUSTER_MIN, CLUSTER_DAYS = 3, 2
PERIOD_IN_DAYS = 30
_WEIGHT = {"neu": 1.0, "wiederholt": 0.6, "erholt": 0.6, "chronisch": 0.2, "keine": 0.0, "unbekannt": 0.0}


#: 0.62.0 — the user: "Wir müssen auch bedenken, dass dieser Server auf einer Workstation laufen kann und nicht 24 h durchläuft. Beim
#: Schlafen muss das berücksichtigt werden." A machine that is off at SLEEP_HOUR never had its nightly run, and quiet days never reached
#: the threshold: such a VI slept rarely and its daily measurement fell out with it. Now a sleep older than CATCHUP_H is caught up as soon
#: as the server has run GRACE_S and no MCP request came for idle_min minutes; with config sleep.workstation the importance trigger waits
#: for such a quiet moment too, so sleep (language model, training) does not run while someone works.
import time as _time

CATCHUP_H = 24
GRACE_S = 300
IDLE_MIN = 10
_STARTED = _time.monotonic()
_last_activity = [_time.monotonic()]


def touch() -> None:
    """An MCP request arrived (server.do_POST)."""
    _last_activity[0] = _time.monotonic()


def idle_s() -> float:
    return _time.monotonic() - _last_activity[0]


def uptime_s() -> float:
    return _time.monotonic() - _STARTED


def _cfg() -> dict:
    from . import config
    try:
        c = config.read_raw(config.fpath()).get("sleep") or {}
    except Exception:  # noqa: BLE001
        c = {}
    return {"workstation": bool(c.get("workstation", False)), "idle_min": float(c.get("idle_min", IDLE_MIN))}


def _new_since(since: str) -> bool:
    """Is there anything new to consolidate? A catch-up without new experiences would only load the language model (and an empty
    memory, e.g. a fresh installation, has nothing to sleep over)."""
    with g.lock:
        return bool(g.db().execute("SELECT 1 FROM objekt WHERE art = 'erfahrung' AND zeit > ? LIMIT 1", (since,)).fetchone())


def last() -> g.MemoryObject | None:
    t = g.recall("art:schlaf", limit=1, viewer=None)
    return t[0][1] if t else None


def due(now: datetime | None = None) -> str | None:
    """Reason why sleep runs now — or None."""
    now = now or datetime.now(timezone.utc)
    l = last()
    since = l.ts if l else "1970-01-01T00:00:00+00:00"
    # Since 0.20.3 only a safety net: training runs on demand (on_demand.py), sleep starts at the importance threshold. At night only
    # if no sleep ran for 24 h (quiet days). Before, any sleep on the same calendar day counted — after a sleep at 00:28 the
    # nightly run was skipped without this being recorded anywhere (seen 09.11.2026).
    if now.hour == SLEEP_HOUR and (not l or datetime.fromisoformat(l.ts) < now - timedelta(hours=24)):
        return f"nightly run {SLEEP_HOUR:02d}:00 UTC (no sleep in 24 h)"
    cfg = _cfg()
    quiet = idle_s() >= cfg["idle_min"] * 60
    if (not l or datetime.fromisoformat(l.ts) < now - timedelta(hours=CATCHUP_H)) and uptime_s() >= GRACE_S and quiet and _new_since(since):
        ago = "never slept" if not l else f"last sleep {int((now - datetime.fromisoformat(l.ts)).total_seconds() // 3600)} h ago"
        return f"catch-up: {ago} (machine off or busy at {SLEEP_HOUR:02d}:00 UTC), quiet for {int(idle_s() // 60)} min"
    if l and datetime.fromisoformat(l.ts) > now - timedelta(minutes=MIN_GAP_MIN):
        return None  # too soon after the last sleep; importance keeps accumulating
    with g.lock:
        sum_total = g.db().execute("SELECT COALESCE(SUM(wichtigkeit), 0) FROM objekt WHERE art = 'erfahrung' AND zeit > ?", (since,)).fetchone()[0]
    if sum_total >= THRESHOLD:
        if cfg["workstation"] and not quiet:
            return None  # a workstation: wait for a quiet moment instead of sleeping while someone works
        return f"importance of new experiences {sum_total} ≥ {THRESHOLD}" + (", workstation quiet" if cfg["workstation"] else "")
    return None


def _content(o: g.MemoryObject) -> set[str]:
    return {t for t in o.hashtags if t.startswith(("host:", "skill:", "tool:", "thema:"))}


_running = threading.Lock()
WAIT_S = 90  # how long vi_sleep(now) waits for the result; a reverse proxy often aborts after 120 s


def running() -> bool:
    """True while a sleep is running (started by the loop or by hand)."""
    return _running.locked()


class AlreadyRunning(Exception):
    pass


def run(reason: str) -> g.MemoryObject:
    """One sleep, never two at once. Returns the report; an error in one step does not abort the others but is recorded in the report."""
    if not _running.acquire(blocking=False):
        raise AlreadyRunning("a sleep is already running")
    try:
        return _run(reason)
    finally:
        _running.release()


def run_in_background(reason: str, wait_s: float | None = None) -> g.MemoryObject | None:
    """Starts sleep in its own thread and waits at most wait_s. None: still running, the report comes with vi_sleep."""
    result: dict = {}

    def go():
        try:
            result["o"] = run(reason)
        except Exception as e:  # noqa: BLE001 — reported to the caller
            result["e"] = e
    t = threading.Thread(target=go, name="vi-schlaf", daemon=True)
    t.start()
    t.join(WAIT_S if wait_s is None else wait_s)
    if "e" in result:
        raise result["e"]
    return result.get("o")


def _run(reason: str) -> g.MemoryObject:
    from . import archive
    t0 = time.monotonic()
    l = last()
    since = l.ts if l else "1970-01-01T00:00:00+00:00"
    report: dict = {"grund": reason, "seit": since, "schritte": {}, "fehler": [], "neu": [], "geaendert": []}

    def step(name, fn):
        try:
            report["schritte"][name] = fn()
        except Exception as exc:  # noqa: BLE001 — named in the report
            report["fehler"].append(f"{name}: {type(exc).__name__}: {exc}")
            log(f"Sleep {name} failed: {exc}")

    new_items = [o for _, o, _g in g.recall("art:erfahrung (ok:ja OR ok:nein)", limit=5000, viewer=None) if o.ts > since]
    step("1_triage", lambda: _triage(new_items, report))
    step("2_replay", lambda: _replay(report))
    step("3_schema", lambda: _schema(report))
    step("4b_reflexion", lambda: _reflection(report))  # language model first (stage 4); what it explains with evidence counts as schema
    step("4_abstraktion", lambda: _abstraction(report))  # template as fallback for clusters without reflection
    step("4c_skills", lambda: _skills(since))
    step("4d_scorer", lambda: _scorer())
    step("5_lager", lambda: archive.cleanup())
    step("5b_pruefer", lambda: _reviewer())
    step("6_selbst_ist", lambda: _self_actual())
    step("6b_doc_triggers", lambda: _doc_triggers())  # 0.26.0
    from . import on_demand
    with on_demand.TRAINING:  # never at the same time as on-demand training (same model, same vectors)
        step("7_vektoren", lambda: _vectors())
        step("7b_naehe", lambda: _proximity())
        step("7c_inhalt", lambda: _content_features())
        step("7d_hinweise", lambda: _hints_new())
        step("8_lernen", lambda: _learning())
        step("8b_gewichte_pruefen", lambda: _weight_audit())  # 0.29.0: read the new weights, never write them
        from . import learning, weight_writer
        step("8c_llm_gewichte", lambda: weight_writer.run())  # 0.58.0: the language model may propose a weight layer — measured before it acts
        step("8d_index_modelle", lambda: [{k: r.get(k) for k in ("index", "zustand", "n", "auc_holdout")} for r in learning.train_indexes("sleep")])  # 0.61.0
        from . import index_transfer
        step("8e_index_vergleich", lambda: [{k: r[k] for k in ("index", "inhalte", "klassen", "vorrang_aus_neu", "vorrang_wieder_an")}
                                             for r in index_transfer.compare_all("sleep")])  # 0.62.0: origin against target per content
        from . import word_weights
        step("8g_wortgewichte", lambda: word_weights.compute())  # 0.62.0: the measured weight of every word — the meaning layer of VIL
        from . import classify
        if classify.configured():  # 0.62.0: labels for the AI language — only with an explicit classify model (the shared LLM is not loaded unasked)
            step("8f_klassifizieren", lambda: {"schueler_training": {k: v for k, v in classify.train_student("sleep").items() if k in ("zustand", "n", "grund")},
                                               **classify.run_with_student(classify.per_sleep(), "sleep")})
    from . import evaluation
    step("9_pruefung", lambda: evaluation.nightly())  # 0.55.0: once a day the fixed question set and the router numbers
    duration = int((time.monotonic() - t0) * 1000)
    state = "fehler" if report["fehler"] else "fertig"
    text = (f"Sleep {'finished' if state == 'fertig' else 'finished with errors'} ({reason}): {len(new_items)} new experiences, {len(report.get('cluster', []))} clusters, "
            f"{report['schritte'].get('3_schema', {}).get('belegt', 0)} insights with evidence, "
            f"{report['schritte'].get('3_schema', {}).get('konflikte', 0)} conflicts, "
            f"{report['schritte'].get('4_abstraktion', 0)} new insights (test), "
            f"{report['schritte'].get('5_lager', {}).get('eingelagert', 0)} entries moved to the long-term archive, {duration} ms"
            + (f" · errors: {'; '.join(report['fehler'])[:300]}" if report["fehler"] else ""))
    report["top_n"] = len(report.pop("top", []))
    report["cluster_n"] = len(report.pop("cluster", []))
    o = g.new_object("schlaf", text, [f"zustand:{state}"], {**report, "dauer_ms": duration}, importance=1, who="vi",
                       reason=reason, instance=g.SERVER_INSTANCE)
    log(text)
    return o


def _triage(new_items: list[g.MemoryObject], report: dict) -> int:
    since7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    with g.lock:
        frequent_hosts = {r[0] for r in g.db().execute(
            "SELECT t.tag FROM tag t JOIN objekt o ON o.id = t.objekt_id WHERE t.tag LIKE 'host:%' AND o.zeit >= ? GROUP BY t.tag HAVING COUNT(*) >= 3", (since7,))}
        triggers_active = {r[0] for r in g.db().execute(
            "SELECT t.tag FROM tag t JOIN objekt o ON o.id = t.objekt_id WHERE o.art IN ('suche', 'regel') AND o.modus IN ('aktiv', 'test') "
            "AND (t.tag LIKE 'host:%' OR t.tag LIKE 'tool:%' OR t.tag LIKE 'skill:%')")}
    rated = []
    for o in new_items:
        level = (o.data.get("ueberraschung") or {}).get("stufe", "keine")
        future = 1.0 if (_content(o) & (frequent_hosts | triggers_active)) else 0.0
        rated.append((_WEIGHT.get(level, 0) + o.importance / 3 + future, o))
    rated.sort(key=lambda x: -x[0])
    report["top"] = [o for _, o in rated[:TOP_N]]
    return len(report["top"])


def _replay(report: dict) -> int:
    cluster: dict[tuple, list[g.MemoryObject]] = defaultdict(list)
    for o in report.get("top", []):
        host = next((t for t in o.hashtags if t.startswith("host:")), None)
        skill = next((t for t in o.hashtags if t.startswith("skill:")), None)
        if host and skill:
            cluster[(host, skill)].append(o)
    for key, new_items in cluster.items():
        cluster[key] = {"neue": list(new_items), "alle": new_items}
        ids = {o.id for o in new_items}
        with g.lock:  # interleaved: add older experiences with the same hashtags so the new is read against the old
            old_umask_value = [r[0] for r in g.db().execute(
                "SELECT o.id FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag = ? JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag = ? "
                "WHERE o.art = 'erfahrung' AND o.modus = 'aktiv' AND o.zeit <= ? ORDER BY o.zeit DESC LIMIT ?", (*key, report["seit"], REPLAY_OLD))]
        for a in old_umask_value:
            if a not in ids:
                o = g.load(a)
                if o:
                    new_items.append(o)
    # neue = since the last sleep (schema check: does the new contradict?); alle = new + older (abstraction)
    report["cluster"] = [{"key": k, "neue": v["neue"], "erfahrungen": v["alle"]} for k, v in cluster.items()]
    return len(cluster)


def _outcome(exps: list[g.MemoryObject]) -> tuple[str, float]:
    ok = sum(1 for o in exps if "ok:ja" in o.hashtags)
    q = ok / len(exps) if exps else 0
    return ("gut" if q >= 0.8 else "schlecht" if q <= 0.2 else "gemischt"), q


def _schema(report: dict) -> dict:
    evidenced = conflicts = 0
    for c in report.get("cluster", []):
        host, skill = c["key"]
        outbox, q = _outcome(c["neue"])  # the new against the schema — the old formed the schema in the first place
        c["ausgang_neu"] = outbox
        c["ausgang"] = _outcome(c["erfahrungen"])[0]
        schemata = [o for _, o, _g in g.recall(f"{host} {skill}", limit=5, kinds=("erkenntnis",), viewer=None) if o.data.get("ausgang")]
        c["schema"] = schemata[0].id if schemata else None
        for s in schemata:
            if outbox == "gemischt":
                continue
            if s.data.get("ausgang") == outbox:
                for o in c["neue"]:
                    s.link(o.id, "Beleg (sleep: same outcome)")
                s.data["belege_n"] = s.data.get("belege_n", 0) + len(c["neue"])
                s.change("vi", f"+{len(c['neue'])} evidence", "sleep: new experiences with the same outcome")
                g.save(s)
                evidenced += 1
            else:
                s.data.setdefault("konflikte", []).append({"zeit": g.now(), "ausgang": outbox, "quote": round(q, 2),
                                                             "erfahrungen": [o.id for o in c["neue"]][:20]})
                if "konflikt:offen" not in s.hashtags:
                    s.hashtags = s.hashtags + ["konflikt:offen"]
                s.change("vi", "konflikt:offen", f"sleep: cluster with outcome {outbox} ({q * 100:.0f} % ok) contradicts {s.data.get('ausgang')}")
                g.save(s)
                report["geaendert"].append(s.id)
                conflicts += 1
    return {"belegt": evidenced, "konflikte": conflicts}


def _scorer() -> dict:
    from . import scorer
    return {**scorer.code_run(), **scorer.model_run()}


def _skills(since: str) -> dict:
    from . import skills, solutions
    r = solutions.from_episodes(since)  # 0.56.0: solutions with content instead of bare tool sequences (skills.from_recovery)
    r.update(skills.rate())
    r.update(skills.fusion_proposals())
    return r


def _reflection(report: dict) -> dict:
    from . import reflection
    r = reflection.reflect(report.get("cluster", []))
    if r.get("neu"):
        for c in report.get("cluster", []):  # do not abstract reflected clusters again via template
            host, skill = c["key"]
            for o in g.recall(f"{host} {skill} herkunft:schlaf-llm", limit=1, kinds=("erkenntnis",), viewer=None):
                c["schema"] = o[1].id
    return r


def _abstraction(report: dict) -> int:
    new = 0
    for c in report.get("cluster", []):
        if c.get("schema") or len(c["erfahrungen"]) < CLUSTER_MIN or c.get("ausgang") == "gemischt":
            continue
        days = {o.ts[:10] for o in c["erfahrungen"]}
        if len(days) < CLUSTER_DAYS:
            continue
        host, skill = c["key"]
        tools = sorted({t[5:] for o in c["erfahrungen"] for t in o.hashtags if t.startswith("tool:")})
        error = sorted({t[7:] for o in c["erfahrungen"] for t in o.hashtags if t.startswith("fehler:")})
        q = _outcome(c["erfahrungen"])[1]
        text = (f"{host[5:]} with {skill[6:]}: {len(c['erfahrungen'])} actions on {len(days)} days, {q * 100:.0f} % successful"
                + (f" — tools {', '.join(tools[:4])}" if tools else "")
                + (f"; typical errors: {', '.join(error[:3])}" if error else ""))
        rid = f"erkenntnis:schlaf-{g.hash_value(host, skill)}"
        if g.load(rid):
            continue
        e = g.new_object("erkenntnis", text, [host, skill, "modus:test", "herkunft:schlaf"],
                           {"quelle": f"sleep: {len(c['erfahrungen'])} experiences, evidence edges", "ausgang": c["ausgang"],
                            "quote": round(q, 2), "belege_n": len(c["erfahrungen"])},
                           importance=1, who="vi", oid=rid, mode="test", reason="sleep: abstraction from a cluster without schema",
                           instance=g.SERVER_INSTANCE)
        for o in c["erfahrungen"]:
            e.link(o.id, "Beleg (sleep: abstraction)")
        report["neu"].append(e.id)
        new += 1
    return new


def _vectors() -> dict:
    from . import vector
    return vector.catch_up()


def _proximity() -> dict:
    from . import vector
    if not vector.available():
        return {"zustand": "uebersprungen", "grund": "no embedding service configured"}
    return vector.proximity_edges()


def _reviewer() -> dict:
    from . import reviewer
    from . import p2p
    from . import forum
    return {**reviewer.work_off(100), "fragen_freigegeben": forum.release_questions(), "auto_freigegeben": p2p.auto_approve()}


def _doc_triggers() -> dict:
    from . import doc_triggers
    return doc_triggers.run()


def _hints_new() -> dict:
    from . import bandit
    return bandit.recompute()


def _content_features() -> dict:
    from . import content
    return content.compute()


def _learning() -> dict:
    from . import learning
    b = learning.train("sleep")
    return {k: b.get(k) for k in ("zustand", "n", "merkmale", "auc_holdout", "nutzen_holdout", "untrennbar", "grund", "urteil") if k in b}


def _weight_audit() -> dict:
    from . import weight_audit
    r = weight_audit.audit()
    return {"zustand": r["zustand"], "je_klasse": r["je_klasse"], "befunde": r["befunde"][:10], **({"grund": r["grund"]} if "grund" in r else {})}


def _self_actual() -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=PERIOD_IN_DAYS)).isoformat(timespec="seconds")
    with g.lock:
        comp = g.db().execute(
            "SELECT t.tag, COUNT(*), SUM(CASE WHEN EXISTS (SELECT 1 FROM tag x WHERE x.objekt_id = o.id AND x.tag = 'ok:ja') THEN 1 ELSE 0 END) "
            "FROM objekt o JOIN tag t ON t.objekt_id = o.id AND t.tag LIKE 'skill:%' WHERE o.art = 'erfahrung' AND o.zeit >= ? "
            "GROUP BY t.tag ORDER BY 2 DESC LIMIT 12", (since,)).fetchall()
        weak = g.db().execute(
            "SELECT t1.tag, t2.tag, COUNT(*) FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag LIKE 'tool:%' "
            "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag LIKE 'fehler:%' WHERE o.art = 'erfahrung' AND o.zeit >= ? "
            "GROUP BY t1.tag, t2.tag HAVING COUNT(*) >= 3 ORDER BY 3 DESC LIMIT 8", (since,)).fetchall()
        relations = g.db().execute(
            "SELECT instanz, COUNT(*), MAX(zeit) FROM objekt WHERE art = 'gespraech' AND instanz <> 'vi' GROUP BY instanz ORDER BY 2 DESC").fetchall()
    actual = {"zeitraum": f"{PERIOD_IN_DAYS} d", "berechnet": g.now(),
           "kompetenz": [{"bereich": b, "erfahrungen": n, "erfolgsquote": round(ok / n, 2), "zeitraum": f"{PERIOD_IN_DAYS} d"} for b, n, ok in comp],
           "schwaechen": [{"bereich": t, "fehler": f, "n": n} for t, f, n in weak],
           "beziehungen": [{"instanz": i, "gespraeche": n, "zuletzt": z} for i, n, z in relations]}
    self_model.set_actual(actual, "sleep: extension from the experiences of the last 30 days")
    return {"kompetenz": len(comp), "schwaechen": len(weak), "beziehungen": len(relations)}
