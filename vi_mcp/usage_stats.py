"""Usage statistics — is the VI used, and does it work as intended? (0.21.0)

Every call of a VI tool in the server is counted (`record`), independently of the hook — the hook deliberately does not report vi_*.
Only time, instance, client, tool, outcome, duration and, for searches, hit count and search kind are stored — no arguments,
no text. Retention RETENTION_DAYS, after that the loop deletes (`cleanup`).

`report(days)` answers six questions, each with number, period and origin:
  A Usage         Who calls which VI tools how often, with which outcome and which duration?
  B Rules         Is there a search before changing actions (rules 1–2)? Is there learning (5–8)? Is there feedback on hints?
  C Hints         How many hints and warnings were shown, and do actions succeed more often afterwards?
  D Knowledge     How much knowledge was added (kind, visibility, origin) — and how much of it is ever recalled?
  E Search        How often does a search find nothing, which search kind ran, how long did it take?
  F Cleanup       Sleep, training, edges, long-term archive.
  P Measurement   0.55.0: does the search find the known target (fixed question set, daily), and how does the router do on its holdout?
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timedelta, timezone

from . import api_en
from . import memory as g

RETENTION_DAYS = 90
#: A changing action counts as "prepared with a search" if the same instance consulted the VI this many minutes before
LEAD_MIN = 30
#: Public (English) tool names, as the server counts them since 0.22.0
SEARCH_TOOLS = ("vi_recall", "vi_drilldown", "vi_object", "vi_conversation", "vi_skills")


#: Shell commands that change something. intuition.read_only treats Bash as reading across the board; for the rule statistics the command itself counts.
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
    # Parses the vi_recall / vi_drilldown output of this version (English since 0.23.0); the German forms of older versions
    # stay recognised. The kinds "oder"/"volltext" are stored values.
    text = text or ""
    m = re.search(r"(\d+) (?:objects? for|Objekte? zu)", text)
    n = int(m.group(1)) if m else (0 if re.search(r"\b(?:no|0) (?:objects|hits)\b|\bnothing in memory\b|\b(?:keine|0) (?:Objekte|Treffer)", text, re.I) else None)
    # 0.57.1: the default hybrid of 0.57.0 says "default hybrid" — it was counted as full text
    if re.search(r"(?:semantic|default|semantisch) hybrid \(embedding", text):
        kind = "hybrid"
    elif "OR search" in text or "ODER-Suche" in text:
        kind = "oder"
    else:
        q = re.search(r"(?:objects? for|Objekte? zu|nothing in memory for) “([^”·]*)", text)
        kind = "tags" if q and not g.parse_filter(q.group(1).strip(), g.known_kinds())[2] else "volltext"  # hashtags only: no full text ran
    return n, kind


def record(instance: str, client: str | None, tool_parts: str, outbox: str, ms: int, text: str = "") -> None:
    """One call of a VI tool; outcome ∈ ok | abgelehnt | fehler. Never fails loudly — statistics must not disturb the answer."""
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
    """All metrics as data (for tests and further processing). Read-only."""
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
                                "FROM objekt o WHERE art IN ('erkenntnis', 'regel', 'skill', 'suche', 'bild') AND zeit >= ?", (since,)).fetchall()
        knowledge_total = db.execute("SELECT COUNT(*), SUM(zugriffe > 0) FROM objekt WHERE art IN ('erkenntnis', 'regel', 'skill', 'suche', 'bild') "
                                "AND modus NOT IN ('widerlegt', 'archiviert')").fetchone()
        top = db.execute("SELECT id, zugriffe, substr(text, 1, 80) FROM objekt WHERE art IN ('erkenntnis', 'regel', 'skill', 'suche', 'bild') "
                         "ORDER BY zugriffe DESC LIMIT 5").fetchall()
        conversations = db.execute("SELECT instanz, COUNT(*) FROM objekt WHERE art = 'gespraech' AND zeit >= ? GROUP BY instanz", (since,)).fetchall()
        sleeps = db.execute("SELECT daten FROM objekt WHERE art = 'schlaf' AND zeit >= ?", (since,)).fetchall()
        sem_edges = db.execute("SELECT COUNT(*) FROM kante WHERE grund LIKE 'semantisch%'").fetchone()[0]
        first_call = db.execute("SELECT MIN(zeit) FROM nutzung").fetchone()[0]
        projects_of = dict(db.execute("SELECT json_extract(daten, '$.serial'), json_extract(daten, '$.project') FROM objekt "
                                      "WHERE art = 'gespraech' AND json_extract(daten, '$.project') IS NOT NULL").fetchall())
    # 0.35.1: calls recorded before 0.22.0 (f344419) carry the German tool name (vi_erinnere, vi_lerne …). One tool, one name: count
    # them under the English one — otherwise A listed vi_recall and vi_erinnere as two tools and B/E missed the older searches.
    calls = [(z, i, c, api_en.canonical_name(w), *rest) for z, i, c, w, *rest in calls]
    # 0.24.0: tool calls are only recorded since the table nutzung exists (0.21.0); before, the report mixed 24 h of actions with
    # a few hours of searches. Everything that compares calls with actions counts only from calls_since on.
    calls_since = max(since, first_call) if first_call else None
    # A Usage
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
    # B Rules: changing actions with a VI query by the same instance in the LEAD_MIN minutes before
    search_times = {}
    for z, i, _c, w, outputs, *_r in calls:
        if w in SEARCH_TOOLS and outputs == "ok":
            search_times.setdefault(i, []).append(datetime.fromisoformat(z))
    n_mutating = prepared = 0
    shown = feedbacks = opened = 0
    warn = {"n": 0, "ok": 0}
    without_warn = {"n": 0, "ok": 0}
    conv_with_action: set[str] = set()
    per_project: dict[str, dict] = {}
    for z, i, tot, d_json, tooltag, oktag in exps:
        d = json.loads(d_json)
        v = d.get("vorher") or {}
        shown += len([h for h in v.get("gezeigt") or [] if not h.startswith("antwort:")])
        feedbacks += len(d.get("rueckmeldung") or {})
        opened += len(d.get("geoeffnet") or {})
        if tot:
            conv_with_action.add(tot)
        pr = per_project.setdefault(projects_of.get(tot) or "—", {"n": 0, "ok": 0, "ok_known": 0})
        pr["n"] += 1
        pr["ok"] += oktag == "ok:ja"
        pr["ok_known"] += bool(oktag)
        if oktag:
            target = warn if v.get("warnung") else without_warn
            target["n"] += 1
            target["ok"] += oktag == "ok:ja"
        tool = (tooltag or "tool:?")[5:]
        if not mutating(tool, d.get("args")) or calls_since is None or z < calls_since:
            continue
        n_mutating += 1
        t = datetime.fromisoformat(z)
        if any(timedelta(0) <= t - s <= timedelta(minutes=LEAD_MIN) for s in search_times.get(i, [])):
            prepared += 1
    learned = sum(1 for _z, _i, _c, w, outputs, *_r in calls if w in ("vi_learn", "vi_solved", "vi_learn_search") and outputs == "ok")
    confirmed = sum(1 for _z, _i, _c, w, outputs, *_r in calls if w in ("vi_confirm", "vi_refute") and outputs == "ok")
    # E Search
    search = [(t, a, ms) for _z, _i, _c, w, outputs, ms, t, a in calls if w in ("vi_recall", "vi_drilldown") and outputs == "ok"]
    # F Cleanup
    sl = [json.loads(x[0]) for x in sleeps]
    return {
        "tage": days, "seit": since,
        "nutzung": {"aufrufe": len(calls), "je_werkzeug": {w: {**{k: v for k, v in e.items() if k != "ms"},
                                                                  "ms_median": int(statistics.median(e["ms"])) if e["ms"] else 0}
                                                              for w, e in sorted(by_tool.items(), key=lambda kv: -kv[1]["n"])},
                    "je_instanz": dict(sorted(per_instance.items(), key=lambda kv: -kv[1])), "clients": clients,
                    "gespraeche": dict(conversations), "handlungen": len(exps), "aufrufe_seit": calls_since,
                    "je_projekt": dict(sorted(per_project.items(), key=lambda kv: -kv[1]["n"]))},
        "regeln": {"aendernd": n_mutating, "vorbereitet": prepared, "gelernt": learned, "gespraeche_mit_handlung": len(conv_with_action),
                   "bestaetigt_widerlegt": confirmed, "hinweise_gezeigt": shown, "rueckmeldungen": feedbacks,
                   "geoeffnet": opened},
        "hinweise": {"gezeigt": shown, "warnung": warn, "ohne_warnung": without_warn},
        "wissen": {"neu": len(knowledge_new), "neu_je_art": _count(r[0] for r in knowledge_new), "neu_je_sicht": _count(r[1] for r in knowledge_new),
                   "neu_je_quelle": _count((r[3] or "quelle_art:—")[11:] for r in knowledge_new),
                   "neu_abgerufen": sum(1 for r in knowledge_new if r[2] > 0), "gesamt": knowledge_total[0] or 0, "je_abgerufen": knowledge_total[1] or 0,
                   "top": [(oid, n, t) for oid, n, t in top]},
        "suche": {"n": len(search), "ohne_treffer": sum(1 for t, _a, _m in search if t == 0),
                  "treffer_unbekannt": sum(1 for t, _a, _m in search if t is None),  # 0.35.1: recorded before hit counts existed, named
                  "je_art": _count(a or "?" for _t, a, _m in search),
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


def _age(ts: str) -> str:
    try:
        s = (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()
    except (ValueError, AttributeError):
        return "?"
    return f"{s / 60:.0f} min" if s < 5400 else f"{s / 3600:.1f} h" if s < 172800 else f"{s / 86400:.0f} d"


def network_lines(days: float = 7) -> list[str]:
    """0.39.0: section W — the networks this memory takes part in, as their services reported them (snapshot with every outbox call).
    Nothing is invented: without a snapshot a network shows 'not recorded'."""
    from . import p2p
    from . import net_score
    nets, st = p2p.networks(), p2p.states()
    out = [f"W Network: {len(nets)} network(s) (source: snapshot of each network service, sent with its outbox call; config p2p.networks)"]
    sc = net_score.stats()  # 0.40.0
    out.append(f"    contents by hash: {sc['inhalte']} known on the network, {sc['halterzeilen']} holder lines, {sc['dedupliziert']} arrivals deduplicated "
               f"(same meaning from a further server) · holders per content " + ", ".join(f"{k}: {v}" for k, v in sc["halter_verteilung"].items())
               + f" · rated {sc['bewertet']} (score " + ", ".join(f"{k} {v}" for k, v in sc["score_verteilung"].items())
               + f"), hidden as a hint {sc['ausgeblendet']} · ratings received {sc['bewertungen_empfangen']} (latest per rater and content; source: tables p2p_halter, p2p_bewertung)")
    from . import wiki  # 0.41.0
    ws = wiki.stats(days)
    _table()
    with g.lock:
        reads = g.db().execute("SELECT COUNT(*) FROM nutzung WHERE werkzeug IN ('vi_page_read', 'vi_page_history') AND zeit >= ?", (_since(days),)).fetchone()[0]
        writes = g.db().execute("SELECT COUNT(*) FROM nutzung WHERE werkzeug = 'vi_page_write' AND zeit >= ?", (_since(days),)).fetchone()[0]
    wst = ws["je_status"]
    out.append(f"    wiki: {ws['seiten']} page(s) ({ws['geloescht']} deleted), {ws['revisionen']} revisions (own {ws['eigene']}, foreign {ws['fremde']}) from "
               f"{ws['herausgeber']} author(s) · in {days:g} d: {ws['neue_seiten']} new, {ws['geaenderte_seiten']} changed page(s), {reads} reads, {writes} writes · "
               f"revisions waiting for review {wst['ausstehend']}, counting {wst['frei']} (foreign ones released {ws['fremd_freigegeben']}, of them automatically "
               f"{ws['automatisch_freigegeben']}), discarded {wst['verworfen']}, "
               f"forgotten {wst['vergessen']} · arrival → release median {ws['freigabe_h_median'] if ws['freigabe_h_median'] is not None else 'not recorded'} h, "
               f"90th percentile {ws['freigabe_h_p90'] if ws['freigabe_h_p90'] is not None else 'not recorded'} h · several heads {ws['mehrere_koepfe']} "
               f"(merged silently {ws['still_zusammengefuehrt']}, open conflicts {ws['offene_konflikte']}"
               + (": oldest " + ", ".join(f"{pg} since {ts[:16]}" for ts, pg in ws["aelteste_konflikte"]) if ws["aelteste_konflikte"] else "")
               + ") (source: table seite_rev, usage log)")
    from . import forum  # 0.43.0
    fs = forum.stats(days)
    nz0 = lambda v: "not recorded" if v is None else v  # noqa: E731
    out.append(f"    conversations: in {days:g} d sent " + (", ".join(f"{k} {v}" for k, v in fs["gesendet"].items()) or "nothing") + ", received "
               + (", ".join(f"{k} {v}" for k, v in fs["empfangen"].items()) or "nothing") + f" from {fs['partner']} partner(s), {fs['in_pruefung']} waiting for review · "
               f"questions to the network {fs['fragen']}, answered {fs['beantwortet']} ({_pct(fs['beantwortet'], fs['fragen'])}), answers per question median "
               f"{nz0(fs['antworten_median'])}, first answer after median {nz0(fs['erste_antwort_h_median'])} h (90th percentile {nz0(fs['erste_antwort_h_p90'])} h), "
               f"accepted (confirmed) {fs['angenommen']}, expired {fs['abgelaufen']} (source: tables beitrag_aus, beitrag_ein)")
    ls = p2p.search_stats(days)  # 0.42.0
    tr = [(st.get(n) or {}).get("daten", {}).get("transport") or {} for n in nets]
    nz = lambda v: "not recorded" if v is None else v  # noqa: E731
    out.append(f"    live search: {ls['suchen']} search(es) in {days:g} d, with at least one hit {ls['mit_treffer']} ({_pct(ls['mit_treffer'], ls['suchen'])}), "
               f"members answering per search median {nz(ls['antworten_median'])}, not reachable {ls['nicht_erreichbar']} in all, time median "
               f"{nz(ls['ms_median'])} ms, 90th percentile {nz(ls['ms_p90'])} ms, taken into review {ls['uebernommen']} · answered for other members "
               f"{sum(t.get('suchen_beantwortet', 0) for t in tr)}, refused (rate limit) {sum(t.get('suchen_abgewiesen', 0) for t in tr)} "
               "(since the services started; source: table netz_suche, service snapshots)")
    for name, d in nets.items():
        s = st.get(name)
        if not s:
            out.append(f"    {name} ({d['kind']}, instance {d['instance']}): not recorded — its network service has not reported (not running, or older than 0.39.0)")
            continue
        x = s["daten"]
        peers = x.get("peers") or []
        reach = sum(1 for p in peers if p.get("erreichbar"))
        versions = _count(p.get("version") or "unknown" for p in peers)
        here = sum(p.get("fehlt_hier") or 0 for p in peers)
        there = sum(p.get("fehlt_dort") or 0 for p in peers)
        tr = x.get("transport") or {}
        out.append(f"    {name} ({d['kind']}): snapshot {_age(s['zeit'])} old · {x.get('pseudonym', '?')} {x.get('modus', '?')} {x.get('version', '?')} · "
                   f"{x.get('mitglieder', '?')} members · peers {reach} of {len(peers)} reachable · versions "
                   + (", ".join(f"{v} {n}" for v, n in versions.items()) or "—")
                   + f" · backlog: missing here {here}, missing there {there} entries (after the last exchange) · since service start {tr.get('runden', 0)} rounds, "
                   f"{tr.get('per_https', 0)} entries via HTTPS, {tr.get('per_torrent', 0)} via torrent · entries of unknown types {x.get('unbekannte_typen', 0)} "
                   f"· forks {x.get('gabelungen', 0)} · violations {x.get('verstoesse', 0)} · own entries "
                   + (", ".join(f"{k} {v}" for k, v in (x.get("eigene") or {}).items()) or "not recorded")
                   + (f" · ratings waiting for peers older than 0.39.0: {', '.join(tr['bewertung_sperre'])}" if tr.get("bewertung_sperre") else ""))
    return out


def report(days: float = 7) -> str:
    d = data(days)
    from . import on_demand, learning, metrics
    n, r, h, w, s, a = d["nutzung"], d["regeln"], d["hinweise"], d["wissen"], d["suche"], d["aufraeumen"]
    z = [f"Usage statistics of the last {days:g} days (since {d['seit'][:16]} UTC; source: table nutzung, experiences, objects)"]
    z.append(f"A Usage: {n['aufrufe']} calls of VI tools (recorded since {(n['aufrufe_seit'] or '—')[:16]}), {n['handlungen']} reported actions, conversations per instance "
             + (", ".join(f"{i} {k}" for i, k in n["gespraeche"].items()) or "—"))
    z += [f"    {wz:22} {e['n']:5}×  rejected {e['abgelehnt']}, errors {e['fehler']}, median {e['ms_median']} ms" for wz, e in list(n["je_werkzeug"].items())[:12]]
    z.append("    per instance: " + (", ".join(f"{i} {k}" for i, k in n["je_instanz"].items()) or "—") + " · clients: " + (", ".join(n["clients"]) or "—"))
    z.append("    actions per project (working directory sent by the hook; — = unknown): "
             + (", ".join(f"{p} {e['n']} ({_pct(e['ok'], e['ok_known'])} ok)" for p, e in list(n["je_projekt"].items())[:8]) or "—"))
    z.append(f"B Rules: before {_pct(r['vorbereitet'], r['aendernd'])} of the changing actions ({r['vorbereitet']} of {r['aendernd']}) the same "
             f"instance consulted the VI in the {LEAD_MIN} min before (counted since {(n['aufrufe_seit'] or '—')[:16]}, when calls are recorded; "
             f"the automatic vi_before of the hook does not count as consulting) · learned {r['gelernt']}× in {r['gespraeche_mit_handlung']} conversations with actions · "
             f"feedback on hints {r['rueckmeldungen']} for {r['hinweise_gezeigt']} shown ({_pct(r['rueckmeldungen'], r['hinweise_gezeigt'])}; "
             f"vi_feedback, vi_confirm, vi_refute) · opened with vi_object after being shown {r['geoeffnet']} ({_pct(r['geoeffnet'], r['hinweise_gezeigt'])})")
    lift = metrics.hint_lift(24 * days, viewer=None)
    z.append(f"C Hints: {h['gezeigt']} shown · {metrics.line(lift)} · warnings {h['warnung']['n']} (succeeded afterwards "
             f"{_pct(h['warnung']['ok'], h['warnung']['n'])}; without warning {_pct(h['ohne_warnung']['ok'], h['ohne_warnung']['n'])})")
    z.append("    " + metrics.matched_line(metrics.hint_lift_matched(24 * days, viewer=None)))  # 0.49.0: the raw lift mixes instances
    ex = metrics.exploration_effect(24 * days)  # 0.57.0: the randomized comparison — causal, unlike the two lines above
    z.append(f"    randomized (ε-exploration, last slot random vs ranked): {ex['urteil']}")
    from . import learning, weight_writer
    m_ = learning.model()
    if m_ is not None and weight_writer.layer(m_):  # 0.58.0
        z.append(f"    {weight_writer.line(m_)} · online: {metrics.arm_effect(since=weight_writer.layer(m_).get('ab_seit'))['urteil']}")
    z.append("    " + metrics.age_line(metrics.lift_by_age(24 * days, viewer=None)))  # 0.29.0: cold-start observation point
    z.append(f"D Knowledge: {w['neu']} new (" + ", ".join(f"{k} {v}" for k, v in w["neu_je_art"].items()) + "; visibility "
             + ", ".join(f"{k} {v}" for k, v in w["neu_je_sicht"].items()) + "; origin " + ", ".join(f"{k} {v}" for k, v in list(w["neu_je_quelle"].items())[:5])
             + f") · of these ever recalled {_pct(w['neu_abgerufen'], w['neu'])} · total {w['gesamt']}, ever recalled {w['je_abgerufen']} ({_pct(w['je_abgerufen'], w['gesamt'])})")
    z += [f"    most recalled: [{oid}] {k}× {t}" for oid, k, t in w["top"][:3]]
    known = s["n"] - s["treffer_unbekannt"]
    z.append(f"E Search: {s['n']} searches, without hits {s['ohne_treffer']} ({_pct(s['ohne_treffer'], known)} of {known} with a recorded hit count"
             + (f"; {s['treffer_unbekannt']} older ones without a hit count" if s["treffer_unbekannt"] else "") + ") · search kind "
             + (", ".join(f"{k} {v}" for k, v in s["je_art"].items()) or "—") + " · median "
             + (", ".join(f"{k} {v} ms" for k, v in s["ms_median"].items()) or "—"))
    from . import evaluation
    ck = evaluation.click_stats(days)  # 0.57.0
    z.append(f"    opened afterwards (suche_log since 0.57.0): {ck['mit_klick']} of {ck['suchen']} searches · opened hits by rank "
             + (", ".join(f"#{r} {n}" for r, n in ck["je_rang"].items()) or "—"))
    m = learning.model()
    z.append(f"F Cleanup: {a['schlaefe']} sleeps (median {a['schlaf_ms_median'] // 1000} s, {a['neue_erkenntnisse']} new insights, {a['fehler']} step errors) · "
             f"{on_demand.line()} · router AUC {m.data.get('auc_holdout') if m else '—'} · semantic edges {a['semantische_kanten']}")
    z += measurement_lines()
    z += network_lines(days)
    return "\n".join(z)


def measurement_lines(limit: int = 7) -> list[str]:
    """0.55.0: section P — the daily measurements of sleep step 9_pruefung (eval/verlauf.jsonl next to the database)."""
    from . import evaluation
    h = evaluation.history(limit)
    if not h:
        return ["P Measurement: not recorded yet — sleep step 9_pruefung writes the question set first (eval/recall.json, "
                f"at least {evaluation.EVAL_MIN} targets) and measures once a day"]
    out = [f"P Measurement: {len(h)} day(s), question set {h[-1].get('fragen')} targets × 2 queries, page level (source: eval/verlauf.jsonl)"]
    for e in h:
        parts = []
        for name, r in (e.get("suche") or {}).items():
            gs = r.get("gesamt") if isinstance(r, dict) else None
            parts.append(f"{name} MRR {gs['mrr']} Hit@5 {gs['hit5']} ({gs['ms_median']} ms)" if gs else f"{name} {r.get('zustand', '—')}")
        rt = e.get("router") or {}
        lift = (e.get("hinweis_lift") or {}).get("differenz_punkte", (e.get("hinweis_lift") or {}).get("lift"))
        out.append(f"    {e['zeit'][:10]}: " + " · ".join(parts) + f" · router AUC {rt.get('auc', '—')} log loss {rt.get('log_loss', '—')} "
                   f"champion {rt.get('champion', '—')}" + (f" · hint lift matched {lift}" if lift is not None else "")
                   + (f" · exploration − ranked {e['exploration']['differenz'] * 100:+.1f} ± {e['exploration']['standardfehler'] * 100:.1f} points"
                      if (e.get("exploration") or {}).get("differenz") is not None else ""))
    return out
