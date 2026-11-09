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

from . import gedaechtnis as g
from . import selbst
from .protokoll import log

SCHLAF_STUNDE = 3
SCHWELLE = 40
TOP_N = 200
REPLAY_ALTE = 5
CLUSTER_MIN, CLUSTER_TAGE = 3, 2
ZEITRAUM_IST_TAGE = 30
_GEWICHT = {"neu": 1.0, "wiederholt": 0.6, "erholt": 0.6, "chronisch": 0.2, "keine": 0.0, "unbekannt": 0.0}


def letzter() -> g.Objekt | None:
    t = g.erinnere("art:schlaf", limit=1, betrachter=None)
    return t[0][1] if t else None


def faellig(jetzt: datetime | None = None) -> str | None:
    """Grund, warum jetzt geschlafen wird — oder None."""
    jetzt = jetzt or datetime.now(timezone.utc)
    l = letzter()
    seit = l.zeit if l else "1970-01-01T00:00:00+00:00"
    # Seit 0.20.3 nur noch Sicherheitsnetz: Training läuft bei Bedarf (bedarf.py), geschlafen wird ab der Wichtigkeitsschwelle. Nachts nur,
    # wenn seit 24 h kein Schlaf lief (ruhige Tage). Vorher zählte jeder Schlaf desselben Kalendertags — nach einem Schlaf um 00:28 fiel
    # der Nachtlauf aus, ohne dass es irgendwo stand (gesehen 09.11.2026).
    if jetzt.hour == SCHLAF_STUNDE and (not l or datetime.fromisoformat(l.zeit) < jetzt - timedelta(hours=24)):
        return f"Nachtlauf {SCHLAF_STUNDE:02d}:00 UTC (kein Schlaf in 24 h)"
    with g.sperre:
        summe = g.db().execute("SELECT COALESCE(SUM(wichtigkeit), 0) FROM objekt WHERE art = 'erfahrung' AND zeit > ?", (seit,)).fetchone()[0]
    if summe >= SCHWELLE:
        return f"Wichtigkeit neuer Erfahrungen {summe} ≥ {SCHWELLE}"
    return None


def _inhalt(o: g.Objekt) -> set[str]:
    return {t for t in o.hashtags if t.startswith(("host:", "skill:", "tool:", "thema:"))}


_laeuft = threading.Lock()
WARTE_S = 90  # so lange wartet vi_schlaf(jetzt) auf das Ergebnis; ein Reverse-Proxy bricht oft nach 120 s ab


def laeuft() -> bool:
    """True, solange ein Schlaf läuft (vom Loop oder von Hand gestartet)."""
    return _laeuft.locked()


class LaeuftBereits(Exception):
    pass


def lauf(grund: str) -> g.Objekt:
    """Ein Schlaf, nie zwei zugleich. Liefert den Bericht; Fehler eines Schritts brechen nicht die anderen ab, sondern stehen im Bericht."""
    if not _laeuft.acquire(blocking=False):
        raise LaeuftBereits("ein Schlaf läuft bereits")
    try:
        return _lauf(grund)
    finally:
        _laeuft.release()


def lauf_im_hintergrund(grund: str, warte_s: float | None = None) -> g.Objekt | None:
    """Startet den Schlaf in einem eigenen Thread und wartet höchstens warte_s. None: läuft noch, der Bericht kommt mit vi_schlaf."""
    ergebnis: dict = {}

    def los():
        try:
            ergebnis["o"] = lauf(grund)
        except Exception as e:  # noqa: BLE001 — wird dem Aufrufer gemeldet
            ergebnis["e"] = e
    t = threading.Thread(target=los, name="vi-schlaf", daemon=True)
    t.start()
    t.join(WARTE_S if warte_s is None else warte_s)
    if "e" in ergebnis:
        raise ergebnis["e"]
    return ergebnis.get("o")


def _lauf(grund: str) -> g.Objekt:
    from . import lager
    t0 = time.monotonic()
    l = letzter()
    seit = l.zeit if l else "1970-01-01T00:00:00+00:00"
    bericht: dict = {"grund": grund, "seit": seit, "schritte": {}, "fehler": [], "neu": [], "geaendert": []}

    def schritt(name, fn):
        try:
            bericht["schritte"][name] = fn()
        except Exception as exc:  # noqa: BLE001 — benannt im Bericht
            bericht["fehler"].append(f"{name}: {type(exc).__name__}: {exc}")
            log(f"Schlaf {name} scheiterte: {exc}")

    neue = [o for _, o, _g in g.erinnere("art:erfahrung (ok:ja OR ok:nein)", limit=5000, betrachter=None) if o.zeit > seit]
    schritt("1_triage", lambda: _triage(neue, bericht))
    schritt("2_replay", lambda: _replay(bericht))
    schritt("3_schema", lambda: _schema(bericht))
    schritt("4b_reflexion", lambda: _reflexion(bericht))  # Sprachmodell zuerst (Stufe 4); was es belegt erklärt, gilt als Schema
    schritt("4_abstraktion", lambda: _abstraktion(bericht))  # Vorlage als Rückfall für Cluster ohne Reflexion
    schritt("4c_skills", lambda: _skills(seit))
    schritt("4d_scorer", lambda: _scorer())
    schritt("5_lager", lambda: lager.aufraeumen())
    schritt("5b_pruefer", lambda: _pruefer())
    schritt("6_selbst_ist", lambda: _selbst_ist())
    from . import bedarf
    with bedarf.TRAINING:  # nie gleichzeitig mit dem Training bei Bedarf (dasselbe Modell, dieselben Vektoren)
        schritt("7_vektoren", lambda: _vektoren())
        schritt("7b_naehe", lambda: _naehe())
        schritt("7c_inhalt", lambda: _inhalt_merkmale())
        schritt("7d_hinweise", lambda: _hinweise_neu())
        schritt("8_lernen", lambda: _lernen())
    dauer = int((time.monotonic() - t0) * 1000)
    zustand = "fehler" if bericht["fehler"] else "fertig"
    text = (f"Schlaf {zustand} ({grund}): {len(neue)} neue Erfahrungen, {len(bericht.get('cluster', []))} Cluster, "
            f"{bericht['schritte'].get('3_schema', {}).get('belegt', 0)} Erkenntnisse belegt, "
            f"{bericht['schritte'].get('3_schema', {}).get('konflikte', 0)} Konflikte, "
            f"{bericht['schritte'].get('4_abstraktion', 0)} neue Erkenntnisse (test), "
            f"{bericht['schritte'].get('5_lager', {}).get('eingelagert', 0)} Einträge ins Langzeitlager, {dauer} ms"
            + (f" · Fehler: {'; '.join(bericht['fehler'])[:300]}" if bericht["fehler"] else ""))
    bericht["top_n"] = len(bericht.pop("top", []))
    bericht["cluster_n"] = len(bericht.pop("cluster", []))
    o = g.neues_objekt("schlaf", text, [f"zustand:{zustand}"], {**bericht, "dauer_ms": dauer}, wichtigkeit=1, wer="vi",
                       grund=grund, instanz=g.SERVER_INSTANZ)
    log(text)
    return o


def _triage(neue: list[g.Objekt], bericht: dict) -> int:
    seit7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    with g.sperre:
        hosts_haeufig = {r[0] for r in g.db().execute(
            "SELECT t.tag FROM tag t JOIN objekt o ON o.id = t.objekt_id WHERE t.tag LIKE 'host:%' AND o.zeit >= ? GROUP BY t.tag HAVING COUNT(*) >= 3", (seit7,))}
        reize_aktiv = {r[0] for r in g.db().execute(
            "SELECT t.tag FROM tag t JOIN objekt o ON o.id = t.objekt_id WHERE o.art IN ('suche', 'regel') AND o.modus IN ('aktiv', 'test') "
            "AND (t.tag LIKE 'host:%' OR t.tag LIKE 'tool:%' OR t.tag LIKE 'skill:%')")}
    bewertet = []
    for o in neue:
        stufe = (o.daten.get("ueberraschung") or {}).get("stufe", "keine")
        zukunft = 1.0 if (_inhalt(o) & (hosts_haeufig | reize_aktiv)) else 0.0
        bewertet.append((_GEWICHT.get(stufe, 0) + o.wichtigkeit / 3 + zukunft, o))
    bewertet.sort(key=lambda x: -x[0])
    bericht["top"] = [o for _, o in bewertet[:TOP_N]]
    return len(bericht["top"])


def _replay(bericht: dict) -> int:
    cluster: dict[tuple, list[g.Objekt]] = defaultdict(list)
    for o in bericht.get("top", []):
        host = next((t for t in o.hashtags if t.startswith("host:")), None)
        skill = next((t for t in o.hashtags if t.startswith("skill:")), None)
        if host and skill:
            cluster[(host, skill)].append(o)
    for key, neue in cluster.items():
        cluster[key] = {"neue": list(neue), "alle": neue}
        ids = {o.id for o in neue}
        with g.sperre:  # verschränkt: ältere Erfahrungen derselben Hashtags dazu, damit Neues gegen Altes gelesen wird
            alte = [r[0] for r in g.db().execute(
                "SELECT o.id FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag = ? JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag = ? "
                "WHERE o.art = 'erfahrung' AND o.modus = 'aktiv' AND o.zeit <= ? ORDER BY o.zeit DESC LIMIT ?", (*key, bericht["seit"], REPLAY_ALTE))]
        for a in alte:
            if a not in ids:
                o = g.lade(a)
                if o:
                    neue.append(o)
    # neue = seit dem letzten Schlaf (Schema-Abgleich: widerspricht das Neue?); alle = neue + ältere (Abstraktion)
    bericht["cluster"] = [{"key": k, "neue": v["neue"], "erfahrungen": v["alle"]} for k, v in cluster.items()]
    return len(cluster)


def _ausgang(erf: list[g.Objekt]) -> tuple[str, float]:
    ok = sum(1 for o in erf if "ok:ja" in o.hashtags)
    q = ok / len(erf) if erf else 0
    return ("gut" if q >= 0.8 else "schlecht" if q <= 0.2 else "gemischt"), q


def _schema(bericht: dict) -> dict:
    belegt = konflikte = 0
    for c in bericht.get("cluster", []):
        host, skill = c["key"]
        ausgang, q = _ausgang(c["neue"])  # das Neue gegen das Schema — das Alte hat das Schema ja gebildet
        c["ausgang_neu"] = ausgang
        c["ausgang"] = _ausgang(c["erfahrungen"])[0]
        schemata = [o for _, o, _g in g.erinnere(f"{host} {skill}", limit=5, arten=("erkenntnis",), betrachter=None) if o.daten.get("ausgang")]
        c["schema"] = schemata[0].id if schemata else None
        for s in schemata:
            if ausgang == "gemischt":
                continue
            if s.daten.get("ausgang") == ausgang:
                for o in c["neue"]:
                    s.verknuepfe(o.id, "Beleg (Schlaf: gleicher Ausgang)")
                s.daten["belege_n"] = s.daten.get("belege_n", 0) + len(c["neue"])
                s.aendere("vi", f"+{len(c['neue'])} Belege", "Schlaf: neue Erfahrungen mit gleichem Ausgang")
                g.speichere(s)
                belegt += 1
            else:
                s.daten.setdefault("konflikte", []).append({"zeit": g.jetzt(), "ausgang": ausgang, "quote": round(q, 2),
                                                             "erfahrungen": [o.id for o in c["neue"]][:20]})
                if "konflikt:offen" not in s.hashtags:
                    s.hashtags = s.hashtags + ["konflikt:offen"]
                s.aendere("vi", "konflikt:offen", f"Schlaf: Cluster mit Ausgang {ausgang} ({q * 100:.0f} % ok) widerspricht {s.daten.get('ausgang')}")
                g.speichere(s)
                bericht["geaendert"].append(s.id)
                konflikte += 1
    return {"belegt": belegt, "konflikte": konflikte}


def _scorer() -> dict:
    from . import scorer
    return {**scorer.code_lauf(), **scorer.modell_lauf()}


def _skills(seit: str) -> dict:
    from . import skills
    r = skills.aus_erholung(seit)
    r.update(skills.bewerte())
    r.update(skills.fusions_vorschlaege())
    return r


def _reflexion(bericht: dict) -> dict:
    from . import reflexion
    r = reflexion.reflektiere(bericht.get("cluster", []))
    if r.get("neu"):
        for c in bericht.get("cluster", []):  # reflektierte Cluster nicht noch einmal per Vorlage abstrahieren
            host, skill = c["key"]
            for o in g.erinnere(f"{host} {skill} herkunft:schlaf-llm", limit=1, arten=("erkenntnis",), betrachter=None):
                c["schema"] = o[1].id
    return r


def _abstraktion(bericht: dict) -> int:
    neu = 0
    for c in bericht.get("cluster", []):
        if c.get("schema") or len(c["erfahrungen"]) < CLUSTER_MIN or c.get("ausgang") == "gemischt":
            continue
        tage = {o.zeit[:10] for o in c["erfahrungen"]}
        if len(tage) < CLUSTER_TAGE:
            continue
        host, skill = c["key"]
        werkzeuge = sorted({t[5:] for o in c["erfahrungen"] for t in o.hashtags if t.startswith("tool:")})
        fehler = sorted({t[7:] for o in c["erfahrungen"] for t in o.hashtags if t.startswith("fehler:")})
        q = _ausgang(c["erfahrungen"])[1]
        text = (f"{host[5:]} mit {skill[6:]}: {len(c['erfahrungen'])} Handlungen an {len(tage)} Tagen, {q * 100:.0f} % erfolgreich"
                + (f" — Werkzeuge {', '.join(werkzeuge[:4])}" if werkzeuge else "")
                + (f"; typische Fehler: {', '.join(fehler[:3])}" if fehler else ""))
        rid = f"erkenntnis:schlaf-{g.hashwert(host, skill)}"
        if g.lade(rid):
            continue
        e = g.neues_objekt("erkenntnis", text, [host, skill, "modus:test", "herkunft:schlaf"],
                           {"quelle": f"Schlaf: {len(c['erfahrungen'])} Erfahrungen, Belegkanten", "ausgang": c["ausgang"],
                            "quote": round(q, 2), "belege_n": len(c["erfahrungen"])},
                           wichtigkeit=1, wer="vi", oid=rid, modus="test", grund="Schlaf: Abstraktion aus Cluster ohne Schema",
                           instanz=g.SERVER_INSTANZ)
        for o in c["erfahrungen"]:
            e.verknuepfe(o.id, "Beleg (Schlaf: Abstraktion)")
        bericht["neu"].append(e.id)
        neu += 1
    return neu


def _vektoren() -> dict:
    from . import vektor
    return vektor.nachziehen()


def _naehe() -> dict:
    from . import vektor
    if not vektor.verfuegbar():
        return {"zustand": "uebersprungen", "grund": "kein Embedding-Dienst konfiguriert"}
    return vektor.naehe_kanten()


def _pruefer() -> dict:
    from . import pruefer
    from . import p2p
    return {**pruefer.abarbeiten(100), "auto_freigegeben": p2p.auto_freigeben()}


def _hinweise_neu() -> dict:
    from . import bandit
    return bandit.neu_berechnen()


def _inhalt_merkmale() -> dict:
    from . import inhalt
    return inhalt.berechne()


def _lernen() -> dict:
    from . import lernen
    b = lernen.trainiere("Schlaf")
    return {k: b.get(k) for k in ("zustand", "n", "merkmale", "auc_holdout", "grund", "urteil") if k in b}


def _selbst_ist() -> dict:
    seit = (datetime.now(timezone.utc) - timedelta(days=ZEITRAUM_IST_TAGE)).isoformat(timespec="seconds")
    with g.sperre:
        komp = g.db().execute(
            "SELECT t.tag, COUNT(*), SUM(CASE WHEN EXISTS (SELECT 1 FROM tag x WHERE x.objekt_id = o.id AND x.tag = 'ok:ja') THEN 1 ELSE 0 END) "
            "FROM objekt o JOIN tag t ON t.objekt_id = o.id AND t.tag LIKE 'skill:%' WHERE o.art = 'erfahrung' AND o.zeit >= ? "
            "GROUP BY t.tag ORDER BY 2 DESC LIMIT 12", (seit,)).fetchall()
        schw = g.db().execute(
            "SELECT t1.tag, t2.tag, COUNT(*) FROM objekt o JOIN tag t1 ON t1.objekt_id = o.id AND t1.tag LIKE 'tool:%' "
            "JOIN tag t2 ON t2.objekt_id = o.id AND t2.tag LIKE 'fehler:%' WHERE o.art = 'erfahrung' AND o.zeit >= ? "
            "GROUP BY t1.tag, t2.tag HAVING COUNT(*) >= 3 ORDER BY 3 DESC LIMIT 8", (seit,)).fetchall()
        bez = g.db().execute(
            "SELECT instanz, COUNT(*), MAX(zeit) FROM objekt WHERE art = 'gespraech' AND instanz <> 'vi' GROUP BY instanz ORDER BY 2 DESC").fetchall()
    ist = {"zeitraum": f"{ZEITRAUM_IST_TAGE} d", "berechnet": g.jetzt(),
           "kompetenz": [{"bereich": b, "erfahrungen": n, "erfolgsquote": round(ok / n, 2), "zeitraum": f"{ZEITRAUM_IST_TAGE} d"} for b, n, ok in komp],
           "schwaechen": [{"bereich": t, "fehler": f, "n": n} for t, f, n in schw],
           "beziehungen": [{"instanz": i, "gespraeche": n, "zuletzt": z} for i, n, z in bez]}
    selbst.setze_ist(ist, "Schlaf: Extension aus den Erfahrungen der letzten 30 Tage")
    return {"kompetenz": len(komp), "schwaechen": len(schw), "beziehungen": len(bez)}
