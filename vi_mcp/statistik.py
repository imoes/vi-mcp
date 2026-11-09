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

from . import gedaechtnis as g

AUFBEWAHRUNG_TAGE = 90
#: Eine ändernde Handlung gilt als „mit Suche vorbereitet“, wenn dieselbe Instanz so viele Minuten davor die VI befragt hat
VORLAUF_MIN = 30
SUCH_WERKZEUGE = ("vi_erinnere", "vi_vertiefe", "vi_objekt", "vi_gespraech", "vi_skills")


#: Shell-Befehle, die etwas ändern. Bash gilt in intuition.lesend pauschal als lesend; für die Regel-Statistik zählt der Befehl selbst.
_SHELL_AENDERND = re.compile(r"\b(apt(-get)?\s+(install|remove|purge|upgrade|dist-upgrade)|dpkg\s+-i|systemctl\s+(restart|stop|start|enable|disable|reload)|"
                             r"service\s+\S+\s+(restart|stop|start)|docker\s+(restart|stop|rm|run|compose\s+(up|down|restart))|rm\s+-|sed\s+-i|"
                             r"chmod|chown|git\s+(push|commit|reset|checkout|merge|rebase)|p?kill\b|reboot|shutdown|nginx\s+-s|"
                             r"ansible-playbook(?!.*--check)|curl\s.*-X\s*(POST|PUT|DELETE|PATCH)|tee\s+/|>\s*/(etc|var|opt|srv))", re.I)


def aendernd(tool: str, args: dict | None) -> bool:
    from . import intuition
    if tool in intuition.SHELL_WERKZEUGE:
        return bool(_SHELL_AENDERND.search(str((args or {}).get("command") or (args or {}).get("cmd") or "")))
    return not intuition.lesend(tool)


def _tabelle() -> None:
    with g.sperre:
        g.db().execute("CREATE TABLE IF NOT EXISTS nutzung (zeit TEXT NOT NULL, instanz TEXT NOT NULL, client TEXT, werkzeug TEXT NOT NULL, "
                       "ausgang TEXT NOT NULL, ms INTEGER NOT NULL, treffer INTEGER, suchart TEXT)")
        g.db().execute("CREATE INDEX IF NOT EXISTS nutzung_zeit ON nutzung (zeit)")
        g.db().commit()


def _treffer(werkzeug: str, text: str) -> tuple[int | None, str | None]:
    if werkzeug not in ("vi_erinnere", "vi_vertiefe"):
        return None, None
    m = re.search(r"(\d+) Objekte? zu", text or "")
    n = int(m.group(1)) if m else (0 if re.search(r"\b(keine|0) (Objekte|Treffer)", text or "", re.I) else None)
    art = "hybrid" if "semantisch hybrid" in (text or "") else ("oder" if "ODER-Suche" in (text or "") else "volltext")
    return n, art


def zeichne(instanz: str, client: str | None, werkzeug: str, ausgang: str, ms: int, text: str = "") -> None:
    """Ein Aufruf eines VI-Werkzeugs; ausgang ∈ ok | abgelehnt | fehler. Scheitert nie laut — Statistik darf die Antwort nicht stören."""
    try:
        _tabelle()
        n, art = _treffer(werkzeug, text) if ausgang == "ok" else (None, None)
        with g.sperre:
            g.db().execute("INSERT INTO nutzung VALUES (?,?,?,?,?,?,?,?)", (g.jetzt(), instanz, client, werkzeug, ausgang, int(ms), n, art))
            g.db().commit()
    except Exception:  # noqa: BLE001
        pass


def aufraeumen() -> int:
    _tabelle()
    grenze = (datetime.now(timezone.utc) - timedelta(days=AUFBEWAHRUNG_TAGE)).isoformat(timespec="seconds")
    with g.sperre:
        n = g.db().execute("DELETE FROM nutzung WHERE zeit < ?", (grenze,)).rowcount
        g.db().commit()
    return n


def _pct(a: float, b: float) -> str:
    return f"{round(100 * a / b)} %" if b else "—"


def _seit(tage: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=tage)).isoformat(timespec="seconds")


def daten(tage: float = 7) -> dict:
    """Alle Kennzahlen als Daten (für Tests und Weiterverarbeitung). Rein lesend."""
    _tabelle()
    seit = _seit(tage)
    db = g.db()
    with g.sperre:
        aufrufe = db.execute("SELECT zeit, instanz, client, werkzeug, ausgang, ms, treffer, suchart FROM nutzung WHERE zeit >= ? ORDER BY zeit",
                             (seit,)).fetchall()
        erf = db.execute("SELECT o.zeit, o.instanz, o.gespraech, o.daten, (SELECT tag FROM tag t WHERE t.objekt_id = o.id AND t.tag LIKE 'tool:%'), "
                         "(SELECT tag FROM tag t WHERE t.objekt_id = o.id AND t.tag IN ('ok:ja', 'ok:nein')) FROM objekt o "
                         "WHERE o.art = 'erfahrung' AND o.zeit >= ? ORDER BY o.zeit", (seit,)).fetchall()
        wissen_neu = db.execute("SELECT art, sicht, zugriffe, (SELECT tag FROM tag t WHERE t.objekt_id = o.id AND t.tag LIKE 'quelle_art:%') "
                                "FROM objekt o WHERE art IN ('erkenntnis', 'regel', 'skill', 'suche') AND zeit >= ?", (seit,)).fetchall()
        wissen_ges = db.execute("SELECT COUNT(*), SUM(zugriffe > 0) FROM objekt WHERE art IN ('erkenntnis', 'regel', 'skill', 'suche') "
                                "AND modus NOT IN ('widerlegt', 'archiviert')").fetchone()
        top = db.execute("SELECT id, zugriffe, substr(text, 1, 80) FROM objekt WHERE art IN ('erkenntnis', 'regel', 'skill', 'suche') "
                         "ORDER BY zugriffe DESC LIMIT 5").fetchall()
        gespraeche = db.execute("SELECT instanz, COUNT(*) FROM objekt WHERE art = 'gespraech' AND zeit >= ? GROUP BY instanz", (seit,)).fetchall()
        schlaefe = db.execute("SELECT daten FROM objekt WHERE art = 'schlaf' AND zeit >= ?", (seit,)).fetchall()
        sem_kanten = db.execute("SELECT COUNT(*) FROM kante WHERE grund LIKE 'semantisch%'").fetchone()[0]
    # A Nutzung
    je_werkzeug: dict[str, dict] = {}
    for _z, _i, _c, w, aus, ms, _t, _a in aufrufe:
        e = je_werkzeug.setdefault(w, {"n": 0, "abgelehnt": 0, "fehler": 0, "ms": []})
        e["n"] += 1
        e["abgelehnt"] += aus == "abgelehnt"
        e["fehler"] += aus == "fehler"
        e["ms"].append(ms)
    je_instanz: dict[str, int] = {}
    for _z, i, *_r in aufrufe:
        je_instanz[i] = je_instanz.get(i, 0) + 1
    clients = sorted({c for _z, _i, c, *_r in aufrufe if c})
    # B Regeln: ändernde Handlungen mit VI-Befragung derselben Instanz in den VORLAUF_MIN Minuten davor
    such = {}
    for z, i, _c, w, aus, *_r in aufrufe:
        if w in SUCH_WERKZEUGE and aus == "ok":
            such.setdefault(i, []).append(datetime.fromisoformat(z))
    n_aendernd = vorbereitet = 0
    gezeigt = rueckmeldungen = 0
    warn = {"n": 0, "ok": 0}
    ohne_warn = {"n": 0, "ok": 0}
    gespr_mit_handlung: set[str] = set()
    for z, i, ges, d_json, tooltag, oktag in erf:
        d = json.loads(d_json)
        v = d.get("vorher") or {}
        gezeigt += len([h for h in v.get("gezeigt") or [] if not h.startswith("antwort:")])
        rueckmeldungen += len(d.get("rueckmeldung") or {})
        if ges:
            gespr_mit_handlung.add(ges)
        if oktag:
            ziel = warn if v.get("warnung") else ohne_warn
            ziel["n"] += 1
            ziel["ok"] += oktag == "ok:ja"
        tool = (tooltag or "tool:?")[5:]
        if not aendernd(tool, d.get("args")):
            continue
        n_aendernd += 1
        t = datetime.fromisoformat(z)
        if any(timedelta(0) <= t - s <= timedelta(minutes=VORLAUF_MIN) for s in such.get(i, [])):
            vorbereitet += 1
    gelernt = sum(1 for _z, _i, _c, w, aus, *_r in aufrufe if w in ("vi_lerne", "vi_geloest", "vi_suche_lerne") and aus == "ok")
    bestaetigt = sum(1 for _z, _i, _c, w, aus, *_r in aufrufe if w in ("vi_bestaetige", "vi_widerlege") and aus == "ok")
    # E Suche
    suchen = [(t, a, ms) for _z, _i, _c, w, aus, ms, t, a in aufrufe if w in ("vi_erinnere", "vi_vertiefe") and aus == "ok"]
    # F Aufräumen
    sl = [json.loads(x[0]) for x in schlaefe]
    return {
        "tage": tage, "seit": seit,
        "nutzung": {"aufrufe": len(aufrufe), "je_werkzeug": {w: {**{k: v for k, v in e.items() if k != "ms"},
                                                                  "ms_median": int(statistics.median(e["ms"])) if e["ms"] else 0}
                                                              for w, e in sorted(je_werkzeug.items(), key=lambda kv: -kv[1]["n"])},
                    "je_instanz": dict(sorted(je_instanz.items(), key=lambda kv: -kv[1])), "clients": clients,
                    "gespraeche": dict(gespraeche), "handlungen": len(erf)},
        "regeln": {"aendernd": n_aendernd, "vorbereitet": vorbereitet, "gelernt": gelernt, "gespraeche_mit_handlung": len(gespr_mit_handlung),
                   "bestaetigt_widerlegt": bestaetigt, "hinweise_gezeigt": gezeigt, "rueckmeldungen": rueckmeldungen},
        "hinweise": {"gezeigt": gezeigt, "warnung": warn, "ohne_warnung": ohne_warn},
        "wissen": {"neu": len(wissen_neu), "neu_je_art": _zaehle(r[0] for r in wissen_neu), "neu_je_sicht": _zaehle(r[1] for r in wissen_neu),
                   "neu_je_quelle": _zaehle((r[3] or "quelle_art:—")[11:] for r in wissen_neu),
                   "neu_abgerufen": sum(1 for r in wissen_neu if r[2] > 0), "gesamt": wissen_ges[0] or 0, "je_abgerufen": wissen_ges[1] or 0,
                   "top": [(oid, n, t) for oid, n, t in top]},
        "suche": {"n": len(suchen), "ohne_treffer": sum(1 for t, _a, _m in suchen if t == 0), "je_art": _zaehle(a or "?" for _t, a, _m in suchen),
                  "ms_median": {a: int(statistics.median([m for _t, a2, m in suchen if a2 == a])) for a in {a for _t, a, _m in suchen}}},
        "aufraeumen": {"schlaefe": len(sl), "schlaf_ms_median": int(statistics.median([s.get("dauer_ms", 0) for s in sl])) if sl else 0,
                       "neue_erkenntnisse": sum(len(s.get("neu") or []) for s in sl),
                       "fehler": sum(len(s.get("fehler") or []) for s in sl), "semantische_kanten": sem_kanten},
    }


def _zaehle(werte) -> dict:
    aus: dict = {}
    for w in werte:
        aus[w] = aus.get(w, 0) + 1
    return dict(sorted(aus.items(), key=lambda kv: -kv[1]))


def bericht(tage: float = 7) -> str:
    d = daten(tage)
    from . import bedarf, lernen, messung
    n, r, h, w, s, a = d["nutzung"], d["regeln"], d["hinweise"], d["wissen"], d["suche"], d["aufraeumen"]
    z = [f"Nutzungsstatistik der letzten {tage:g} Tage (seit {d['seit'][:16]} UTC; Quelle: Tabelle nutzung, Erfahrungen, Objekte)"]
    z.append(f"A Nutzung: {n['aufrufe']} Aufrufe von VI-Werkzeugen, {n['handlungen']} gemeldete Handlungen, Gespräche je Instanz "
             + (", ".join(f"{i} {k}" for i, k in n["gespraeche"].items()) or "—"))
    z += [f"    {wz:22} {e['n']:5}×  abgelehnt {e['abgelehnt']}, Fehler {e['fehler']}, Median {e['ms_median']} ms" for wz, e in list(n["je_werkzeug"].items())[:12]]
    z.append("    je Instanz: " + (", ".join(f"{i} {k}" for i, k in n["je_instanz"].items()) or "—") + " · Clients: " + (", ".join(n["clients"]) or "—"))
    z.append(f"B Regeln: vor {_pct(r['vorbereitet'], r['aendernd'])} der ändernden Handlungen ({r['vorbereitet']} von {r['aendernd']}) hat dieselbe "
             f"Instanz in den {VORLAUF_MIN} min davor die VI befragt · gelernt {r['gelernt']}× in {r['gespraeche_mit_handlung']} Gesprächen mit Handlungen · "
             f"Rückmeldungen zu Hinweisen {r['rueckmeldungen']} auf {r['hinweise_gezeigt']} gezeigte ({_pct(r['rueckmeldungen'], r['hinweise_gezeigt'])})")
    lift = messung.hinweis_lift(24 * tage, betrachter=None)
    z.append(f"C Hinweise: {h['gezeigt']} gezeigt · {messung.zeile(lift)} · Warnungen {h['warnung']['n']} (danach gelungen "
             f"{_pct(h['warnung']['ok'], h['warnung']['n'])}; ohne Warnung {_pct(h['ohne_warnung']['ok'], h['ohne_warnung']['n'])})")
    z.append(f"D Wissen: {w['neu']} neu (" + ", ".join(f"{k} {v}" for k, v in w["neu_je_art"].items()) + "; Sicht "
             + ", ".join(f"{k} {v}" for k, v in w["neu_je_sicht"].items()) + "; Herkunft " + ", ".join(f"{k} {v}" for k, v in list(w["neu_je_quelle"].items())[:5])
             + f") · davon je abgerufen {_pct(w['neu_abgerufen'], w['neu'])} · Bestand {w['gesamt']}, je abgerufen {w['je_abgerufen']} ({_pct(w['je_abgerufen'], w['gesamt'])})")
    z += [f"    meist abgerufen: [{oid}] {k}× {t}" for oid, k, t in w["top"][:3]]
    z.append(f"E Suche: {s['n']} Suchen, ohne Treffer {s['ohne_treffer']} ({_pct(s['ohne_treffer'], s['n'])}) · Suchart "
             + (", ".join(f"{k} {v}" for k, v in s["je_art"].items()) or "—") + " · Median "
             + (", ".join(f"{k} {v} ms" for k, v in s["ms_median"].items()) or "—"))
    m = lernen.modell()
    z.append(f"F Aufräumen: {a['schlaefe']} Schläfe (Median {a['schlaf_ms_median'] // 1000} s, {a['neue_erkenntnisse']} neue Erkenntnisse, {a['fehler']} Schrittfehler) · "
             f"{bedarf.zeile()} · Router AUC {m.daten.get('auc_holdout') if m else '—'} · semantische Kanten {a['semantische_kanten']}")
    return "\n".join(z)
