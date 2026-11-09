"""Schlaf — der Konsolidierungslauf (docs/FORSCHUNG.md A4, A5, C2).

Läuft in einem eigenen Thread, den der Loop startet (seit 0.20.5; Schreiben schützt g.sperre, Modell und Vektoren bedarf.TRAINING), einmal pro Nacht (SCHLAF_STUNDE UTC) oder sobald die Summe
der Wichtigkeit neuer Erfahrungen seit dem letzten Lauf SCHWELLE übersteigt (Parks Reflexions-Trigger, auf 0–3 skaliert).
Schritte — jeder zählt, jeder steht im Bericht (Objekt `schlaf:<zeit>`, Zustand `fertig` oder `fehler`):
  1 Triage      Erfahrungen seit dem letzten Lauf, Priorität = Überraschung + Wichtigkeit/3 + Zukunftsrelevanz
  2 Replay      Cluster nach (host, skill) über die Top-Erfahrungen, je Cluster k ältere derselben Hashtags dazu
  3 Schema      passt eine Erkenntnis zum Cluster? gleicher Ausgang → Beleg-Kante; anderer → `konflikt:offen`
  4b Reflexion  Sprachmodell formuliert je Cluster ohne Schema höchstens eine Erkenntnis (test, geprüft, Belegkanten) — reflexion.py
  4 Abstraktion Rückfall aus Vorlage für Cluster ohne Reflexion: ≥ 3 Erfahrungen an ≥ 2 Tagen → Erkenntnis (test)
  4c Skills     Erfolg nach Fehlern im selben Gespräch → Skill (Lösungsweg); scheiternde Skills → strittig; gleiche Probleme → fusion:vorschlag
  4d Scorer     Handlungen nach festen Merkmalen bewerten, beendete Gespräche durch das Sprachmodell (scorer.py)
  5 Housekeeping nicht mehr verwendete Einträge und alte Rohverläufe ins Langzeitlager (lager.py; Stummel bleibt)
  6 Selbst-Ist  Kompetenz je Skill, Schwächen, Beziehungen neu berechnen
  7 Vektoren    fehlende Embeddings geteilter Wissensobjekte nachziehen (Batch), semantische Nähe → Kanten / dublette:moeglich
  7c Inhalt     Mittelpunkte je Reiz und Bedeutungsgruppen für den Router (inhalt.py)
  7d Hinweise   Hinweis-Zähler aus den Erfahrungen neu, gemessen am Vorteil gegenüber dem Werkzeug ohne Hinweis (bandit.py)
  8 Lernen      Router-Modell trainieren (lernen.py)
  9 Bericht
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
#: 0.21.1: 40 → 80 und höchstens alle MIN_ABSTAND_MIN Minuten. Gemessen 08./09.11.: 45 Schläfe in 24 h (Median 83 s), zusammen nur
#: 3 neue Erkenntnisse — der Schlaf lief fast im Halbstundentakt und belastete das Sprachmodell, ohne viel zu liefern (vi_stats, F).
THRESHOLD = 80
MIN_GAP_MIN = 120
TOP_N = 200
REPLAY_OLD = 5
CLUSTER_MIN, CLUSTER_DAYS = 3, 2
PERIOD_IN_DAYS = 30
_WEIGHT = {"neu": 1.0, "wiederholt": 0.6, "erholt": 0.6, "chronisch": 0.2, "keine": 0.0, "unbekannt": 0.0}


def last() -> g.MemoryObject | None:
    t = g.recall("art:schlaf", limit=1, viewer=None)
    return t[0][1] if t else None


def due(now: datetime | None = None) -> str | None:
    """Grund, warum jetzt geschlafen wird — oder None."""
    now = now or datetime.now(timezone.utc)
    l = last()
    since = l.ts if l else "1970-01-01T00:00:00+00:00"
    # Seit 0.20.3 nur noch Sicherheitsnetz: Training läuft bei Bedarf (bedarf.py), geschlafen wird ab der Wichtigkeitsschwelle. Nachts nur,
    # wenn seit 24 h kein Schlaf lief (ruhige Tage). Vorher zählte jeder Schlaf desselben Kalendertags — nach einem Schlaf um 00:28 fiel
    # der Nachtlauf aus, ohne dass es irgendwo stand (gesehen 09.11.2026).
    if now.hour == SLEEP_HOUR and (not l or datetime.fromisoformat(l.ts) < now - timedelta(hours=24)):
        return f"Nachtlauf {SLEEP_HOUR:02d}:00 UTC (kein Schlaf in 24 h)"
    if l and datetime.fromisoformat(l.ts) > now - timedelta(minutes=MIN_GAP_MIN):
        return None  # zu kurz nach dem letzten Schlaf; die Wichtigkeit sammelt sich weiter
    with g.lock:
        sum_total = g.db().execute("SELECT COALESCE(SUM(wichtigkeit), 0) FROM objekt WHERE art = 'erfahrung' AND zeit > ?", (since,)).fetchone()[0]
    if sum_total >= THRESHOLD:
        return f"Wichtigkeit neuer Erfahrungen {sum_total} ≥ {THRESHOLD}"
    return None


def _content(o: g.MemoryObject) -> set[str]:
    return {t for t in o.hashtags if t.startswith(("host:", "skill:", "tool:", "thema:"))}


_running = threading.Lock()
WAIT_S = 90  # so lange wartet vi_sleep(jetzt) auf das Ergebnis; ein Reverse-Proxy bricht oft nach 120 s ab


def running() -> bool:
    """True, solange ein Schlaf läuft (vom Loop oder von Hand gestartet)."""
    return _running.locked()


class AlreadyRunning(Exception):
    pass


def run(reason: str) -> g.MemoryObject:
    """Ein Schlaf, nie zwei zugleich. Liefert den Bericht; Fehler eines Schritts brechen nicht die anderen ab, sondern stehen im Bericht."""
    if not _running.acquire(blocking=False):
        raise AlreadyRunning("ein Schlaf läuft bereits")
    try:
        return _run(reason)
    finally:
        _running.release()


def run_in_background(reason: str, wait_s: float | None = None) -> g.MemoryObject | None:
    """Startet den Schlaf in einem eigenen Thread und wartet höchstens warte_s. None: läuft noch, der Bericht kommt mit vi_sleep."""
    result: dict = {}

    def go():
        try:
            result["o"] = run(reason)
        except Exception as e:  # noqa: BLE001 — wird dem Aufrufer gemeldet
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
        except Exception as exc:  # noqa: BLE001 — benannt im Bericht
            report["fehler"].append(f"{name}: {type(exc).__name__}: {exc}")
            log(f"Schlaf {name} scheiterte: {exc}")

    new_items = [o for _, o, _g in g.recall("art:erfahrung (ok:ja OR ok:nein)", limit=5000, viewer=None) if o.ts > since]
    step("1_triage", lambda: _triage(new_items, report))
    step("2_replay", lambda: _replay(report))
    step("3_schema", lambda: _schema(report))
    step("4b_reflexion", lambda: _reflection(report))  # Sprachmodell zuerst (Stufe 4); was es belegt erklärt, gilt als Schema
    step("4_abstraktion", lambda: _abstraction(report))  # Vorlage als Rückfall für Cluster ohne Reflexion
    step("4c_skills", lambda: _skills(since))
    step("4d_scorer", lambda: _scorer())
    step("5_lager", lambda: archive.cleanup())
    step("5b_pruefer", lambda: _reviewer())
    step("6_selbst_ist", lambda: _self_actual())
    from . import on_demand
    with on_demand.TRAINING:  # nie gleichzeitig mit dem Training bei Bedarf (dasselbe Modell, dieselben Vektoren)
        step("7_vektoren", lambda: _vectors())
        step("7b_naehe", lambda: _proximity())
        step("7c_inhalt", lambda: _content_features())
        step("7d_hinweise", lambda: _hints_new())
        step("8_lernen", lambda: _learning())
    duration = int((time.monotonic() - t0) * 1000)
    state = "fehler" if report["fehler"] else "fertig"
    text = (f"Schlaf {state} ({reason}): {len(new_items)} neue Erfahrungen, {len(report.get('cluster', []))} Cluster, "
            f"{report['schritte'].get('3_schema', {}).get('belegt', 0)} Erkenntnisse belegt, "
            f"{report['schritte'].get('3_schema', {}).get('konflikte', 0)} Konflikte, "
            f"{report['schritte'].get('4_abstraktion', 0)} neue Erkenntnisse (test), "
            f"{report['schritte'].get('5_lager', {}).get('eingelagert', 0)} Einträge ins Langzeitlager, {duration} ms"
            + (f" · Fehler: {'; '.join(report['fehler'])[:300]}" if report["fehler"] else ""))
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
        with g.lock:  # verschränkt: ältere Erfahrungen derselben Hashtags dazu, damit Neues gegen Altes gelesen wird
            old_umask_value = [r[0] for r in g.db().execute(
                "SELECT o.id FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag = ? JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag = ? "
                "WHERE o.art = 'erfahrung' AND o.modus = 'aktiv' AND o.zeit <= ? ORDER BY o.zeit DESC LIMIT ?", (*key, report["seit"], REPLAY_OLD))]
        for a in old_umask_value:
            if a not in ids:
                o = g.load(a)
                if o:
                    new_items.append(o)
    # neue = seit dem letzten Schlaf (Schema-Abgleich: widerspricht das Neue?); alle = neue + ältere (Abstraktion)
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
        outbox, q = _outcome(c["neue"])  # das Neue gegen das Schema — das Alte hat das Schema ja gebildet
        c["ausgang_neu"] = outbox
        c["ausgang"] = _outcome(c["erfahrungen"])[0]
        schemata = [o for _, o, _g in g.recall(f"{host} {skill}", limit=5, kinds=("erkenntnis",), viewer=None) if o.data.get("ausgang")]
        c["schema"] = schemata[0].id if schemata else None
        for s in schemata:
            if outbox == "gemischt":
                continue
            if s.data.get("ausgang") == outbox:
                for o in c["neue"]:
                    s.link(o.id, "Beleg (Schlaf: gleicher Ausgang)")
                s.data["belege_n"] = s.data.get("belege_n", 0) + len(c["neue"])
                s.change("vi", f"+{len(c['neue'])} Belege", "Schlaf: neue Erfahrungen mit gleichem Ausgang")
                g.save(s)
                evidenced += 1
            else:
                s.data.setdefault("konflikte", []).append({"zeit": g.now(), "ausgang": outbox, "quote": round(q, 2),
                                                             "erfahrungen": [o.id for o in c["neue"]][:20]})
                if "konflikt:offen" not in s.hashtags:
                    s.hashtags = s.hashtags + ["konflikt:offen"]
                s.change("vi", "konflikt:offen", f"Schlaf: Cluster mit Ausgang {outbox} ({q * 100:.0f} % ok) widerspricht {s.data.get('ausgang')}")
                g.save(s)
                report["geaendert"].append(s.id)
                conflicts += 1
    return {"belegt": evidenced, "konflikte": conflicts}


def _scorer() -> dict:
    from . import scorer
    return {**scorer.code_run(), **scorer.model_run()}


def _skills(since: str) -> dict:
    from . import skills
    r = skills.from_recovery(since)
    r.update(skills.rate())
    r.update(skills.fusion_proposals())
    return r


def _reflection(report: dict) -> dict:
    from . import reflection
    r = reflection.reflect(report.get("cluster", []))
    if r.get("neu"):
        for c in report.get("cluster", []):  # reflektierte Cluster nicht noch einmal per Vorlage abstrahieren
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
        text = (f"{host[5:]} mit {skill[6:]}: {len(c['erfahrungen'])} Handlungen an {len(days)} Tagen, {q * 100:.0f} % erfolgreich"
                + (f" — Werkzeuge {', '.join(tools[:4])}" if tools else "")
                + (f"; typische Fehler: {', '.join(error[:3])}" if error else ""))
        rid = f"erkenntnis:schlaf-{g.hash_value(host, skill)}"
        if g.load(rid):
            continue
        e = g.new_object("erkenntnis", text, [host, skill, "modus:test", "herkunft:schlaf"],
                           {"quelle": f"Schlaf: {len(c['erfahrungen'])} Erfahrungen, Belegkanten", "ausgang": c["ausgang"],
                            "quote": round(q, 2), "belege_n": len(c["erfahrungen"])},
                           importance=1, who="vi", oid=rid, mode="test", reason="Schlaf: Abstraktion aus Cluster ohne Schema",
                           instance=g.SERVER_INSTANCE)
        for o in c["erfahrungen"]:
            e.link(o.id, "Beleg (Schlaf: Abstraktion)")
        report["neu"].append(e.id)
        new += 1
    return new


def _vectors() -> dict:
    from . import vector
    return vector.catch_up()


def _proximity() -> dict:
    from . import vector
    if not vector.available():
        return {"zustand": "uebersprungen", "grund": "kein Embedding-Dienst konfiguriert"}
    return vector.proximity_edges()


def _reviewer() -> dict:
    from . import reviewer
    from . import p2p
    return {**reviewer.work_off(100), "auto_freigegeben": p2p.auto_approve()}


def _hints_new() -> dict:
    from . import bandit
    return bandit.recompute()


def _content_features() -> dict:
    from . import content
    return content.compute()


def _learning() -> dict:
    from . import learning
    b = learning.train("Schlaf")
    return {k: b.get(k) for k in ("zustand", "n", "merkmale", "auc_holdout", "grund", "urteil") if k in b}


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
    self_model.set_actual(actual, "Schlaf: Extension aus den Erfahrungen der letzten 30 Tage")
    return {"kompetenz": len(comp), "schwaechen": len(weak), "beziehungen": len(relations)}
