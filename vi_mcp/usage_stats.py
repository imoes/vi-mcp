"""Nutzungsstatistik — wird die VI genutzt, und funktioniert sie so, wie gedacht? (0.21.0)

Gezählt wird jeder Aufruf eines VI-Werkzeugs im Server (`zeichne`), unabhängig vom Hook — der Hook meldet vi_* absichtlich nicht.
Gespeichert werden nur Zeit, Instanz, Client, Werkzeug, Ausgang, Dauer und bei Suchen Trefferzahl und Suchart — keine Argumente,
kein Text. Aufbewahrung AUFBEWAHRUNG_TAGE, danach löscht der Loop (`aufraeumen`).

`bericht(tage)` beantwortet sechs Fragen, jede mit Zahl, Zeitraum und Herkunft:
  A Nutzung       Wer ruft welche VI-Werkzeuge wie oft, mit welchem Ausgang und welcher Dauer?
  B Regeln        Wird vor ändernden Handlungen gesucht (Regel 1–2)? Wird gelernt (5–8)? Kommen Rückmeldungen zu Hinweisen?
  C Hinweise      Wie viele Hinweise und Warnungen wurden gezeigt, und gelingen Handlungen danach häufiger?
  D Wissen        Wie viel Wissen kam dazu (Art, Sicht, Herkunft) — und wie viel davon wird je abgerufen?
  E Suche         Wie oft findet eine Suche nichts, welche Suchart lief, wie lange dauerte sie?
  F Aufräumen     Schlaf, Training, Kanten, Langzeitlager.
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timedelta, timezone

from . import memory as g

RETENTION_DAYS = 90
#: Eine ändernde Handlung gilt als „mit Suche vorbereitet“, wenn dieselbe Instanz so viele Minuten davor die VI befragt hat
LEAD_MIN = 30
#: Öffentliche (englische) Werkzeugnamen, wie der Server sie seit 0.22.0 zählt
SEARCH_TOOLS = ("vi_recall", "vi_drilldown", "vi_object", "vi_conversation", "vi_skills")


#: Shell-Befehle, die etwas ändern. Bash gilt in intuition.lesend pauschal als lesend; für die Regel-Statistik zählt der Befehl selbst.
_SHELL_MUTATING = re.compile(r"\b(apt(-get)?\s+(install|remove|purge|upgrade|dist-upgrade)|dpkg\s+-i|systemctl\s+(restart|stop|start|enable|disable|reload)|"
                             r"service\s+\S+\s+(restart|stop|start)|docker\s+(restart|stop|rm|run|compose\s+(up|down|restart))|rm\s+-|sed\s+-i|"
                             r"chmod|chown|git\s+(push|commit|reset|checkout|merge|rebase)|p?kill\b|reboot|shutdown|nginx\s+-s|"
                             r"ansible-playbook(?!.*--check)|curl\s.*-X\s*(POST|PUT|DELETE|PATCH)|tee\s+/|>\s*/(etc|var|opt|srv))", re.I)


def mutating(tool: str, args: dict | None) -> bool:
    from . import intuition
    if tool in intuition.SHELL_TOOLS:
        return bool(_SHELL_MUTATING.search(str((args or {}).get("command") or (args or {}).get("cmd") or "")))
    return not intuition.read_only(tool)


def _table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS nutzung (zeit TEXT NOT NULL, instanz TEXT NOT NULL, client TEXT, werkzeug TEXT NOT NULL, "
                       "ausgang TEXT NOT NULL, ms INTEGER NOT NULL, treffer INTEGER, suchart TEXT)")
        g.db().execute("CREATE INDEX IF NOT EXISTS nutzung_zeit ON nutzung (zeit)")
        g.db().commit()


def _hits(tool_parts: str, text: str) -> tuple[int | None, str | None]:
    if tool_parts not in ("vi_recall", "vi_drilldown"):
        return None, None
    m = re.search(r"(\d+) Objekte? zu", text or "")
    n = int(m.group(1)) if m else (0 if re.search(r"\b(keine|0) (Objekte|Treffer)", text or "", re.I) else None)
    kind = "hybrid" if "semantisch hybrid" in (text or "") else ("oder" if "ODER-Suche" in (text or "") else "volltext")
    return n, kind


def record(instance: str, client: str | None, tool_parts: str, outbox: str, ms: int, text: str = "") -> None:
    """Ein Aufruf eines VI-Werkzeugs; ausgang ∈ ok | abgelehnt | fehler. Scheitert nie laut — Statistik darf die Antwort nicht stören."""
    try:
        _table()
        n, kind = _hits(tool_parts, text) if outbox == "ok" else (None, None)
        with g.lock:
            g.db().execute("INSERT INTO nutzung VALUES (?,?,?,?,?,?,?,?)", (g.now(), instance, client, tool_parts, outbox, int(ms), n, kind))
            g.db().commit()
    except Exception:  # noqa: BLE001
        pass


def cleanup() -> int:
    _table()
    bound = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    with g.lock:
        n = g.db().execute("DELETE FROM nutzung WHERE zeit < ?", (bound,)).rowcount
        g.db().commit()
    return n


def _pct(a: float, b: float) -> str:
    return f"{round(100 * a / b)} %" if b else "—"


def _since(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def data(days: float = 7) -> dict:
    """Alle Kennzahlen als Daten (für Tests und Weiterverarbeitung). Rein lesend."""
    _table()
    since = _since(days)
    db = g.db()
    with g.lock:
        calls = db.execute("SELECT zeit, instanz, client, werkzeug, ausgang, ms, treffer, suchart FROM nutzung WHERE zeit >= ? ORDER BY zeit",
                             (since,)).fetchall()
        exps = db.execute("SELECT o.zeit, o.instanz, o.gespraech, o.daten, (SELECT tag FROM tag t WHERE t.objekt_id = o.id AND t.tag LIKE 'tool:%'), "
                         "(SELECT tag FROM tag t WHERE t.objekt_id = o.id AND t.tag IN ('ok:ja', 'ok:nein')) FROM objekt o "
                         "WHERE o.art = 'erfahrung' AND o.zeit >= ? ORDER BY o.zeit", (since,)).fetchall()
        knowledge_new = db.execute("SELECT art, sicht, zugriffe, (SELECT tag FROM tag t WHERE t.objekt_id = o.id AND t.tag LIKE 'quelle_art:%') "
                                "FROM objekt o WHERE art IN ('erkenntnis', 'regel', 'skill', 'suche') AND zeit >= ?", (since,)).fetchall()
        knowledge_total = db.execute("SELECT COUNT(*), SUM(zugriffe > 0) FROM objekt WHERE art IN ('erkenntnis', 'regel', 'skill', 'suche') "
                                "AND modus NOT IN ('widerlegt', 'archiviert')").fetchone()
        top = db.execute("SELECT id, zugriffe, substr(text, 1, 80) FROM objekt WHERE art IN ('erkenntnis', 'regel', 'skill', 'suche') "
                         "ORDER BY zugriffe DESC LIMIT 5").fetchall()
        conversations = db.execute("SELECT instanz, COUNT(*) FROM objekt WHERE art = 'gespraech' AND zeit >= ? GROUP BY instanz", (since,)).fetchall()
        sleeps = db.execute("SELECT daten FROM objekt WHERE art = 'schlaf' AND zeit >= ?", (since,)).fetchall()
        sem_edges = db.execute("SELECT COUNT(*) FROM kante WHERE grund LIKE 'semantisch%'").fetchone()[0]
    # A Nutzung
    by_tool: dict[str, dict] = {}
    for _z, _i, _c, w, outputs, ms, _t, _a in calls:
        e = by_tool.setdefault(w, {"n": 0, "abgelehnt": 0, "fehler": 0, "ms": []})
        e["n"] += 1
        e["abgelehnt"] += outputs == "abgelehnt"
        e["fehler"] += outputs == "fehler"
        e["ms"].append(ms)
    per_instance: dict[str, int] = {}
    for _z, i, *_r in calls:
        per_instance[i] = per_instance.get(i, 0) + 1
    clients = sorted({c for _z, _i, c, *_r in calls if c})
    # B Regeln: ändernde Handlungen mit VI-Befragung derselben Instanz in den VORLAUF_MIN Minuten davor
    search_times = {}
    for z, i, _c, w, outputs, *_r in calls:
        if w in SEARCH_TOOLS and outputs == "ok":
            search_times.setdefault(i, []).append(datetime.fromisoformat(z))
    n_mutating = prepared = 0
    shown = feedbacks = 0
    warn = {"n": 0, "ok": 0}
    without_warn = {"n": 0, "ok": 0}
    conv_with_action: set[str] = set()
    for z, i, tot, d_json, tooltag, oktag in exps:
        d = json.loads(d_json)
        v = d.get("vorher") or {}
        shown += len([h for h in v.get("gezeigt") or [] if not h.startswith("antwort:")])
        feedbacks += len(d.get("rueckmeldung") or {})
        if tot:
            conv_with_action.add(tot)
        if oktag:
            target = warn if v.get("warnung") else without_warn
            target["n"] += 1
            target["ok"] += oktag == "ok:ja"
        tool = (tooltag or "tool:?")[5:]
        if not mutating(tool, d.get("args")):
            continue
        n_mutating += 1
        t = datetime.fromisoformat(z)
        if any(timedelta(0) <= t - s <= timedelta(minutes=LEAD_MIN) for s in search_times.get(i, [])):
            prepared += 1
    learned = sum(1 for _z, _i, _c, w, outputs, *_r in calls if w in ("vi_learn", "vi_solved", "vi_learn_search") and outputs == "ok")
    confirmed = sum(1 for _z, _i, _c, w, outputs, *_r in calls if w in ("vi_confirm", "vi_refute") and outputs == "ok")
    # E Suche
    search = [(t, a, ms) for _z, _i, _c, w, outputs, ms, t, a in calls if w in ("vi_recall", "vi_drilldown") and outputs == "ok"]
    # F Aufräumen
    sl = [json.loads(x[0]) for x in sleeps]
    return {
        "tage": days, "seit": since,
        "nutzung": {"aufrufe": len(calls), "je_werkzeug": {w: {**{k: v for k, v in e.items() if k != "ms"},
                                                                  "ms_median": int(statistics.median(e["ms"])) if e["ms"] else 0}
                                                              for w, e in sorted(by_tool.items(), key=lambda kv: -kv[1]["n"])},
                    "je_instanz": dict(sorted(per_instance.items(), key=lambda kv: -kv[1])), "clients": clients,
                    "gespraeche": dict(conversations), "handlungen": len(exps)},
        "regeln": {"aendernd": n_mutating, "vorbereitet": prepared, "gelernt": learned, "gespraeche_mit_handlung": len(conv_with_action),
                   "bestaetigt_widerlegt": confirmed, "hinweise_gezeigt": shown, "rueckmeldungen": feedbacks},
        "hinweise": {"gezeigt": shown, "warnung": warn, "ohne_warnung": without_warn},
        "wissen": {"neu": len(knowledge_new), "neu_je_art": _count(r[0] for r in knowledge_new), "neu_je_sicht": _count(r[1] for r in knowledge_new),
                   "neu_je_quelle": _count((r[3] or "quelle_art:—")[11:] for r in knowledge_new),
                   "neu_abgerufen": sum(1 for r in knowledge_new if r[2] > 0), "gesamt": knowledge_total[0] or 0, "je_abgerufen": knowledge_total[1] or 0,
                   "top": [(oid, n, t) for oid, n, t in top]},
        "suche": {"n": len(search), "ohne_treffer": sum(1 for t, _a, _m in search if t == 0), "je_art": _count(a or "?" for _t, a, _m in search),
                  "ms_median": {a: int(statistics.median([m for _t, a2, m in search if a2 == a])) for a in {a for _t, a, _m in search}}},
        "aufraeumen": {"schlaefe": len(sl), "schlaf_ms_median": int(statistics.median([s.get("dauer_ms", 0) for s in sl])) if sl else 0,
                       "neue_erkenntnisse": sum(len(s.get("neu") or []) for s in sl),
                       "fehler": sum(len(s.get("fehler") or []) for s in sl), "semantische_kanten": sem_edges},
    }


def _count(values) -> dict:
    outputs: dict = {}
    for w in values:
        outputs[w] = outputs.get(w, 0) + 1
    return dict(sorted(outputs.items(), key=lambda kv: -kv[1]))


def report(days: float = 7) -> str:
    d = data(days)
    from . import on_demand, learning, metrics
    n, r, h, w, s, a = d["nutzung"], d["regeln"], d["hinweise"], d["wissen"], d["suche"], d["aufraeumen"]
    z = [f"Nutzungsstatistik der letzten {days:g} Tage (seit {d['seit'][:16]} UTC; Quelle: Tabelle nutzung, Erfahrungen, Objekte)"]
    z.append(f"A Nutzung: {n['aufrufe']} Aufrufe von VI-Werkzeugen, {n['handlungen']} gemeldete Handlungen, Gespräche je Instanz "
             + (", ".join(f"{i} {k}" for i, k in n["gespraeche"].items()) or "—"))
    z += [f"    {wz:22} {e['n']:5}×  abgelehnt {e['abgelehnt']}, Fehler {e['fehler']}, Median {e['ms_median']} ms" for wz, e in list(n["je_werkzeug"].items())[:12]]
    z.append("    je Instanz: " + (", ".join(f"{i} {k}" for i, k in n["je_instanz"].items()) or "—") + " · Clients: " + (", ".join(n["clients"]) or "—"))
    z.append(f"B Regeln: vor {_pct(r['vorbereitet'], r['aendernd'])} der ändernden Handlungen ({r['vorbereitet']} von {r['aendernd']}) hat dieselbe "
             f"Instanz in den {LEAD_MIN} min davor die VI befragt · gelernt {r['gelernt']}× in {r['gespraeche_mit_handlung']} Gesprächen mit Handlungen · "
             f"Rückmeldungen zu Hinweisen {r['rueckmeldungen']} auf {r['hinweise_gezeigt']} gezeigte ({_pct(r['rueckmeldungen'], r['hinweise_gezeigt'])})")
    lift = metrics.hint_lift(24 * days, viewer=None)
    z.append(f"C Hinweise: {h['gezeigt']} gezeigt · {metrics.line(lift)} · Warnungen {h['warnung']['n']} (danach gelungen "
             f"{_pct(h['warnung']['ok'], h['warnung']['n'])}; ohne Warnung {_pct(h['ohne_warnung']['ok'], h['ohne_warnung']['n'])})")
    z.append(f"D Wissen: {w['neu']} neu (" + ", ".join(f"{k} {v}" for k, v in w["neu_je_art"].items()) + "; Sicht "
             + ", ".join(f"{k} {v}" for k, v in w["neu_je_sicht"].items()) + "; Herkunft " + ", ".join(f"{k} {v}" for k, v in list(w["neu_je_quelle"].items())[:5])
             + f") · davon je abgerufen {_pct(w['neu_abgerufen'], w['neu'])} · Bestand {w['gesamt']}, je abgerufen {w['je_abgerufen']} ({_pct(w['je_abgerufen'], w['gesamt'])})")
    z += [f"    meist abgerufen: [{oid}] {k}× {t}" for oid, k, t in w["top"][:3]]
    z.append(f"E Suche: {s['n']} Suchen, ohne Treffer {s['ohne_treffer']} ({_pct(s['ohne_treffer'], s['n'])}) · Suchart "
             + (", ".join(f"{k} {v}" for k, v in s["je_art"].items()) or "—") + " · Median "
             + (", ".join(f"{k} {v} ms" for k, v in s["ms_median"].items()) or "—"))
    m = learning.model()
    z.append(f"F Aufräumen: {a['schlaefe']} Schläfe (Median {a['schlaf_ms_median'] // 1000} s, {a['neue_erkenntnisse']} neue Erkenntnisse, {a['fehler']} Schrittfehler) · "
             f"{on_demand.line()} · Router AUC {m.data.get('auc_holdout') if m else '—'} · semantische Kanten {a['semantische_kanten']}")
    return "\n".join(z)
