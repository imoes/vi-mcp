"""Das Gedächtnis am Netz: anonymer Ausgang, geprüfter Eingang, Quarantäne, Recht auf Vergessen, Wert je Herausgeber.

Transport und Logbücher gehören dem Netzdienst (netzdienst.py, eigener Prozess). Hier kommt nur an, was er über `vi_netz_eingang` liefert, und die Signatur
wird trotzdem erneut geprüft: Der Netzdienst liest fremde Daten und könnte übernommen sein.
Anonym: Das Netz kennt den Herausgeber nur als Pseudonym; Objekte tragen keine Instanz, keine Hostnamen, nur das Datum (anonym.py).
Hinaus geht nur Bewährtes: geteilt, aktiv und von einer fremden Instanz bestätigt oder mit gemessenem Nutzen.
Vergessen: Jede Instanz hat ein Netz-Token. Pro Objekt entsteht daraus eine `netz_id` und ein `loesch_hash` (SHA-256 des Objekt-Tokens HMAC(Token, oid)).
Wer das Objekt-Token vorlegt, beweist die Urheberschaft, ohne dass das Netz die Instanz kennt; ein Objekt-Token öffnet kein anderes Objekt.
Ablauf beim Eingang: Signatur → feste Regeln (pruefung.py) → Quarantäne → Prüfer (pruefer.py) → Freigabe.
Es wird nur Quelltext als JSON-Feld verteilt. Importiertes ist Text-Hinweis und löst nichts aus; Code läuft nur in der Sandbox.
Freigabe: Unauffälliges durch eine Instanz mit Reflex-Recht oder, wenn `p2p.auto_freigabe` gesetzt ist, automatisch im Schlaf. Reflexe, Schreibzugriffe, erkannte Anweisungen
und alles ohne positives Prüfurteil nur durch eine Instanz mit Freigabe-Recht, deren Token auf dem Server bleibt (vi-mcp freigeben).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections import Counter
from pathlib import Path

from . import gedaechtnis as g
from . import anonym, bandit, pruefer, pruefung, reflexe, sandbox, vektor
from . import logbuch as lb
from .logbuch import kanonisch, pseudonym, schluessel_erzeugen, sha256  # noqa: F401

MAX_OBJEKTE = 2000
WERT_MIN_URTEILE = 20
WERT_SPERRE = 0.3
BEWAEHRT_JA = 3
EXPORT_ARTEN = ("erkenntnis", "regel", "suche", "skill")
FREIGABE_STATUS_OK = "zulassen"

#: {"reflexe_von": [pubkey], "auto_freigabe": bool, "oeffentliche_domains": [...], "interne_namen": [...]}
konfig: dict = {}


def _bewaehrt(o: g.Objekt) -> bool:
    ja, nein = bandit.zaehler(o)
    return o.fremde_bestaetigungen() >= 1 or (ja >= BEWAEHRT_JA and ja >= 3 * nein)


def _tabellen() -> None:
    with g.sperre:
        g.db().executescript("""
            CREATE TABLE IF NOT EXISTS p2p_gesehen (sha TEXT PRIMARY KEY, oid TEXT NOT NULL, herausgeber TEXT NOT NULL, anzahl INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS netz_token (instanz TEXT PRIMARY KEY, token TEXT NOT NULL, zeit TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS netz_widerruf (oid TEXT PRIMARY KEY, instanz TEXT NOT NULL, netz_id TEXT NOT NULL, token TEXT NOT NULL, zeit TEXT NOT NULL, grund TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS p2p_netz (netz_id TEXT PRIMARY KEY, oid TEXT NOT NULL, loesch_hash TEXT NOT NULL, sha TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS p2p_grab (netz_id TEXT PRIMARY KEY, token_sha TEXT NOT NULL, zeit TEXT NOT NULL);
        """)
        g.db().commit()


def _objekt_token(token: str, oid: str) -> tuple[str, str]:
    """(netz_id, objekt_token). Aus dem einen lässt sich weder das andere noch das Instanz-Token herleiten."""
    return hmac.new(token.encode(), b"id|" + oid.encode(), hashlib.sha256).hexdigest()[:32], hmac.new(token.encode(), b"vergessen|" + oid.encode(), hashlib.sha256).hexdigest()


def token_erzeugen(instanz: str) -> str:
    """Einmalig: Ein neues Token könnte bereits verteilte Einträge nie mehr zurückrufen."""
    _tabellen()
    t = secrets.token_urlsafe(32)
    with g.sperre:
        if g.db().execute("SELECT 1 FROM netz_token WHERE instanz = ?", (instanz,)).fetchone():
            raise ValueError(f"Instanz {instanz} hat bereits ein Netz-Token; es wird nicht erneuert, sonst wären verteilte Einträge nicht mehr löschbar (Anzeige auf dem Server: vi-mcp netz-token {instanz})")
        g.db().execute("INSERT INTO netz_token (instanz, token, zeit) VALUES (?,?,?)", (instanz, t, g.jetzt()))
        g.db().commit()
    return t


def _token(instanz: str) -> str | None:
    _tabellen()
    with g.sperre:
        z = g.db().execute("SELECT token FROM netz_token WHERE instanz = ?", (instanz,)).fetchone()
    return z[0] if z else None


def token_anzeigen(instanz: str) -> str | None:
    return _token(instanz)


def _bekannte() -> frozenset[str]:
    """Alles, was dieses Gedächtnis als internen Namen kennt: Hosts aus Hashtags und Instanzen, dazu das System."""
    with g.sperre:
        hosts = [r[0][5:] for r in g.db().execute("SELECT DISTINCT tag FROM tag WHERE tag LIKE 'host:%'")]
        instanzen = [r[0] for r in g.db().execute("SELECT DISTINCT instanz FROM objekt WHERE instanz IS NOT NULL")]
    namen = set(hosts) | {h.split(".")[0] for h in hosts} | set(instanzen) | anonym.system_namen()
    return frozenset(n for n in namen if n and len(n) >= 3 and n.lower() not in anonym.GENERISCH and not n.startswith("p2p-"))


def _export_form(o: g.Objekt, token: str, bek: frozenset[str]) -> tuple[dict | None, str | None]:
    """Das Objekt, wie es das Netz sähe, oder (None, Grund). Der Grund nennt nur die Klasse, nie den Wert."""
    roh_inhalt = str(o.daten.get("inhalt") or "")
    if anonym.ZUGANG.search(o.text) or anonym.ZUGANG.search(roh_inhalt):
        return None, "spricht von Zugangsdaten"
    if len(roh_inhalt) > pruefung.INHALT_MAX:
        return None, "Inhalt ist zu groß fürs Netz"
    zeit = o.zeit[:10]
    roh_tags = [t for t in o.hashtags if not t.startswith(pruefung.FESTE_HASHTAGS + anonym.ORTSBEZUG)]
    sauber = lambda t: anonym.werkzeug(t)
    tags = sorted({t2 for t in roh_tags if not anonym.klassen(((t2 := sauber(t)).split(":", 1)[-1]), bek)})
    netz_id, objekt_token = _objekt_token(token, o.id)
    aus = {"art": o.art, "text": anonym.ersetze(o.text, bek), "hashtags": tags, "quelle": anonym.ersetze(str(o.daten.get("quelle") or f"geteilte Erfahrung vom {zeit}"), bek)[:500],
           "wichtigkeit": o.wichtigkeit, "zeit": zeit, "netz_id": netz_id, "loesch_hash": hashlib.sha256(objekt_token.encode()).hexdigest()}
    if roh_inhalt:
        aus["inhalt"] = anonym.ersetze(roh_inhalt, bek)
    if len(re.sub(r"<\w+>|[\W\d]", "", aus["text"])) < 10:
        return None, "nach dem Anonymisieren bleibt kein Inhalt"
    if o.art == "erkenntnis" and o.daten.get("ausgang"):
        aus["ausgang"] = o.daten["ausgang"]
    if o.art == "suche":
        aus.update(name=anonym.ersetze(o.daten["name"], bek), filter=o.daten["filter"], reize=[t for t in tags if not t.startswith("suche:")])
        if anonym.klassen(o.daten["filter"], bek) or "host:" in o.daten["filter"]:
            return None, "Filter enthält Interna"
    if o.art == "skill":
        reize = sorted({r2 for r in o.daten["problem"]["reize"] if not r.startswith(anonym.ORTSBEZUG + ("instanz:",)) and not anonym.klassen((r2 := anonym.werkzeug(r)).split(":", 1)[-1], bek)})
        aus.update(name=anonym.ersetze(o.daten["name"], bek), reize=reize, schritte=[anonym.werkzeug(s["tool"]) for s in o.daten["loesung"]["schritte"]])
        if any(anonym.klassen(s, bek) for s in aus["schritte"]):
            return None, "Schritte enthalten Interna"
    for feld in ("text", "inhalt", "quelle", "name"):
        if isinstance(aus.get(feld), str) and anonym.klassen(aus[feld], bek):
            return None, f"{feld}: nach dem Ersetzen auffällig"
    probe = pruefung.pruefe(aus)
    if probe.urteil == "ablehnen":
        return None, "eigene Importregeln: " + ", ".join(g_.split(":")[0] for g_ in probe.gruende)[:120]
    return aus, None


def _sammle(instanz: str | None = None) -> tuple[list[tuple[g.Objekt, dict]], dict[str, int]]:
    _tabellen()
    with g.sperre:
        zurueck = {r[0] for r in g.db().execute("SELECT oid FROM netz_widerruf")}
        tokens = dict(g.db().execute("SELECT instanz, token FROM netz_token").fetchall())
    bek = _bekannte()
    aus, grund = [], Counter()
    for art in EXPORT_ARTEN:
        for _, o, _g in g.erinnere(f"art:{art} !herkunft:p2p", limit=MAX_OBJEKTE, betrachter=None):
            if o.sicht != "geteilt" or o.modus != "aktiv" or o.id in zurueck or (instanz and o.instanz != instanz):
                continue
            if not _bewaehrt(o):
                grund["noch nicht bewährt"] += 1
                continue
            if o.instanz not in tokens:
                grund["Instanz hat kein Netz-Token"] += 1
                continue
            roh, g_ = _export_form(o, tokens[o.instanz], bek)
            if roh is None:
                grund[g_] += 1
            else:
                aus.append((o, roh))
    return aus[:MAX_OBJEKTE], dict(grund)


def vorschau(instanz: str, limit: int = 10) -> dict:
    """Was von dieser Instanz hinausgehen würde — genau die Form, die das Netz sähe."""
    objekte, zurueckgehalten = _sammle(instanz)
    return {"anzahl": len(objekte), "zurueckgehalten": zurueckgehalten, "beispiele": [r for _o, r in objekte[:limit]]}


def netz_vergessen(instanz: str, token: str, ids: list[str] | None, grund: str) -> dict:
    """Eigene Einträge aus dem Netz zurückrufen. ids=None heißt alle. Das lokale Objekt bleibt, wird aber nicht mehr verteilt."""
    if not (grund or "").strip():
        raise ValueError("Grund ist Pflicht")
    echt = _token(instanz)
    if not echt or not hmac.compare_digest(echt.encode(), (token or "").encode()):
        raise ValueError("Netz-Token passt nicht zu dieser Instanz")
    if ids is None:
        with g.sperre:
            ids = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE instanz = ? AND art IN (%s)" % ",".join("?" * len(EXPORT_ARTEN)), (instanz, *EXPORT_ARTEN))]
    objekte = g.lade_viele(ids)
    fremd = [i for i in ids if i in objekte and objekte[i].instanz != instanz]
    if fremd:
        raise ValueError(f"{len(fremd)} Einträge gehören einer anderen Instanz; zurückrufen darf nur der Urheber")
    unbekannt, n = [i for i in ids if i not in objekte], 0
    with g.sperre:
        for i in ids:
            if i in objekte:
                netz_id, t = _objekt_token(echt, i)
                n += g.db().execute("INSERT OR IGNORE INTO netz_widerruf (oid, instanz, netz_id, token, zeit, grund) VALUES (?,?,?,?,?,?)", (i, instanz, netz_id, t, g.jetzt(), grund[:300])).rowcount
        g.db().commit()
    return {"zurueckgerufen": n, "unbekannt": unbekannt}


def _widerrufe() -> list[dict]:
    _tabellen()
    with g.sperre:
        return [{"netz_id": a, "token": b} for a, b in g.db().execute("SELECT netz_id, token FROM netz_widerruf ORDER BY zeit")]


def ausgang() -> dict:
    """Was ins Netz darf, unsigniert: Signieren ist Sache des Netzdienstes, der seinen Schlüssel für sich behält."""
    objekte, zurueck = _sammle()
    return {"objekte": [r for _o, r in objekte], "widerrufe": _widerrufe(), "zurueckgehalten": zurueck}


def _vergessen_anwenden(widerrufe) -> int:
    """Nur wer das Objekt-Token kennt, löscht. Ein Grabstein verhindert, dass das Objekt später doch noch ankommt."""
    n = 0
    for w in widerrufe if isinstance(widerrufe, list) else []:
        netz_id, token = (w.get("netz_id"), w.get("token")) if isinstance(w, dict) else (None, None)
        if not isinstance(netz_id, str) or not isinstance(token, str) or len(token) > 128:
            continue
        beleg = hashlib.sha256(token.encode()).hexdigest()
        with g.sperre:
            z = g.db().execute("SELECT oid, loesch_hash, sha FROM p2p_netz WHERE netz_id = ?", (netz_id,)).fetchone()
            bekannt = g.db().execute("SELECT 1 FROM p2p_grab WHERE netz_id = ?", (netz_id,)).fetchone()
        if z and hmac.compare_digest(z[1], beleg):
            g.loesche([z[0]])
            vektor.entferne(z[0])
            with g.sperre:
                g.db().execute("DELETE FROM p2p_netz WHERE netz_id = ?", (netz_id,))
                g.db().execute("DELETE FROM p2p_gesehen WHERE sha = ?", (z[2],))
                g.db().commit()
            n += 1
        elif z:
            continue  # falsches Token: nichts geschieht
        if not bekannt:
            with g.sperre:
                g.db().execute("INSERT OR IGNORE INTO p2p_grab (netz_id, token_sha, zeit) VALUES (?,?,?)", (netz_id, beleg, g.jetzt()[:10]))
                g.db().commit()
    return n


def _anlegen(b: pruefung.Befund, kopf: dict, sha: str) -> g.Objekt:
    name = pseudonym(kopf["pub"])
    o, kurz = b.objekt, sha[:16]
    instanz = f"p2p-{name}"
    daten = {"quelle": o["quelle"], "herkunft": {"herausgeber": name, "pubkey": kopf["pub"], "seq": kopf["seq"], "sha256": sha, "netz_id": o["netz_id"]},
             "pruefung": {"regeln": b.gruende, "pruefer": None}, "fremd_text": o["text"], "fremd_hashtags": o["hashtags"]}
    tags = o["hashtags"] + ["herkunft:p2p", f"herausgeber:{name}", "pruefer:ausstehend", "modus:quarantaene"]
    if o["art"] == "erkenntnis" and o.get("ausgang"):
        daten["ausgang"] = o["ausgang"]
    if o.get("inhalt"):
        daten["inhalt"] = o["inhalt"]
    if o["art"] == "suche":
        slug = pruefung.re.sub(r"[^a-z0-9_-]", "-", o["name"].lower())
        daten.update(name=f"p2p-{name}-{slug}"[:60], filter=o["filter"])
        tags += o["reize"]
    if o["art"] == "skill":
        slug = pruefung.re.sub(r"[^a-z0-9_-]", "-", o["name"].lower())
        n = f"p2p-{name}-{slug}"[:60]
        daten.update(name=n, schritte=o["schritte"], problem={"reize": o["reize"]}, loesung={"schritte": [{"tool": s} for s in o["schritte"]], "text": o["text"]},
                     version=1, versionen=[{"version": 1, "zeit": g.jetzt(), "wer": f"import@{name}", "grund": "Import", "belege": []}], belege=[])
        tags += o["reize"]
    if o["art"] == "reflex":
        daten.update(name=f"p2p_{name.replace('-', '_')}_{o['name']}"[:40], art="vorher", code=o["code"], laeufe=0, fehler=0)
    oid = f"{o['art']}:p2p-{name}-{kurz}"
    return g.neues_objekt(o["art"], o["text"], sorted(set(tags)), daten, wichtigkeit=o["wichtigkeit"], wer=f"import@{name}", grund=f"Import von {name}",
                          oid=oid, modus="quarantaene", instanz=instanz)


def eingang(eintraege, im_hintergrund: bool = True) -> dict:
    """Einträge aus dem Netz prüfen und in die Quarantäne legen."""
    _tabellen()
    bericht = {"quarantaene": 0, "abgelehnt": 0, "bekannt": 0, "gruende": [], "vergessen": 0}

    def ab(grund):
        bericht["abgelehnt"] += 1
        bericht["gruende"].append(grund[:200])
    for e in eintraege if isinstance(eintraege, list) else []:
        kopf, roh = e.get("kopf") if isinstance(e, dict) else None, e.get("inhalt") if isinstance(e, dict) else None
        if lb.kopf_form(kopf) or not lb.signatur_stimmt(kopf) or sha256(roh) != kopf["sha"]:
            ab("Signatur oder Prüfsumme ungültig")
            continue
        if kopf["typ"] == "widerruf":
            if lb.steuer_form("widerruf", roh):
                bericht["vergessen"] += _vergessen_anwenden([{"netz_id": roh["ziel"], "token": roh["token"]}])
            continue
        if kopf["typ"] != "objekt":
            continue
        b = pruefung.pruefe(roh, kopf["pub"] in (konfig.get("reflexe_von") or []))
        if b.urteil != "ablehnen" and (b.objekt["netz_id"] != kopf.get("netz_id") or b.objekt["loesch_hash"] != kopf.get("loesch_hash")):
            b.ablehnen("Kopf und Inhalt nennen verschiedene Objekte")
        if b.urteil != "ablehnen" and b.objekt["art"] == "reflex":
            kompiliert = sandbox.lauf(b.objekt["code"], [], nur_pruefen=True)  # erst in der Sandbox parsen: fremder Code kann den Parser zum Absturz bringen
            grund = kompiliert.get("fehler") or reflexe.pruefe(b.objekt["code"], "vorher")
            if grund:
                b.ablehnen(f"code: {grund}"[:300])
        if b.urteil == "ablehnen":
            ab("; ".join(b.gruende))
            continue
        with g.sperre:
            grab = g.db().execute("SELECT token_sha FROM p2p_grab WHERE netz_id = ?", (b.objekt["netz_id"],)).fetchone()
        if grab and hmac.compare_digest(grab[0], b.objekt["loesch_hash"]):
            bericht["bekannt"] += 1  # zurückgerufen: bleibt weg
            continue
        sha = sha256(b.objekt)
        with g.sperre:
            n = g.db().execute("UPDATE p2p_gesehen SET anzahl = anzahl + 1 WHERE sha = ?", (sha,)).rowcount
            g.db().commit()
            alt = g.db().execute("SELECT oid, sha FROM p2p_netz WHERE netz_id = ?", (b.objekt["netz_id"],)).fetchone()
        if n:
            bericht["bekannt"] += 1
            continue
        if alt:  # neue Fassung desselben Objekts ersetzt die alte
            g.loesche([alt[0]])
            vektor.entferne(alt[0])
            with g.sperre:
                g.db().execute("DELETE FROM p2p_gesehen WHERE sha = ?", (alt[1],))
                g.db().commit()
        o = _anlegen(b, kopf, sha)
        with g.sperre:
            g.db().execute("INSERT INTO p2p_gesehen (sha, oid, herausgeber) VALUES (?,?,?)", (sha, o.id, pseudonym(kopf["pub"])))
            g.db().execute("INSERT OR REPLACE INTO p2p_netz (netz_id, oid, loesch_hash, sha) VALUES (?,?,?,?)", (b.objekt["netz_id"], o.id, b.objekt["loesch_hash"], sha))
            g.db().commit()
        bericht["quarantaene"] += 1
    bericht["gruende"] = bericht["gruende"][:20]
    if im_hintergrund and bericht["quarantaene"] and pruefer.verfuegbar():
        threading.Thread(target=pruefer.abarbeiten, args=(MAX_OBJEKTE,), name="vi-pruefer", daemon=True).start()
    return bericht


_wert_cache: tuple[float, dict] = (0.0, {})


def herausgeber_wert(frisch: bool = False) -> dict[str, dict]:
    """Nutzen je Herausgeber aus den Hinweis-Zählern (Beta-Mittel). Wer sich als schädlich erweist, wird nicht mehr gezeigt."""
    global _wert_cache
    if not frisch and time.time() - _wert_cache[0] < 300:
        return _wert_cache[1]
    with g.sperre:
        zeilen = g.db().execute("SELECT t.tag, COUNT(*), SUM(COALESCE(json_extract(o.daten, '$.nuetzlich.ja'), 0)), SUM(COALESCE(json_extract(o.daten, '$.nuetzlich.nein'), 0)), SUM(COALESCE(json_extract(o.daten, '$.nuetzlich.n'), 0)) "
                                "FROM tag t JOIN objekt o ON o.id = t.objekt_id WHERE t.tag LIKE 'herausgeber:%' GROUP BY t.tag").fetchall()
    aus = {}
    for tag, n, ja, nein, gez in zeilen:
        mittel = (1 + ja) / (2 + ja + nein)
        aus[tag[12:]] = {"objekte": n, "ja": round(ja, 2), "nein": round(nein, 2), "gezeigt": gez, "mittel": round(mittel, 3), "gesperrt": gez >= WERT_MIN_URTEILE and mittel < WERT_SPERRE}
    _wert_cache = (time.time(), aus)
    return aus


def ohne_gesperrte(objekte: list[g.Objekt]) -> list[g.Objekt]:
    if not any("herkunft:p2p" in o.hashtags for o in objekte):
        return objekte
    wert = herausgeber_wert()
    return [o for o in objekte if not any(t.startswith("herausgeber:") and wert.get(t[12:], {}).get("gesperrt") for t in o.hashtags)]


def auto_freigeben() -> int:
    """Nur mit `p2p.auto_freigabe`: Was Regeln und Prüfer unauffällig finden, wird vorläufig (Modus test). Heikles bleibt beim Menschen."""
    if not konfig.get("auto_freigabe"):
        return 0
    n = 0
    wert = herausgeber_wert(frisch=True)
    for _, o, _g in g.erinnere("modus:quarantaene", limit=MAX_OBJEKTE, betrachter=None):
        if "pruefer:ausstehend" in o.hashtags or heikel(o) or wert.get(o.daten["herkunft"]["herausgeber"], {}).get("gesperrt"):
            continue
        freigeben(o, "vi", True, False, "automatisch: Regeln ohne Befund, Prüfer lässt zu")
        n += 1
    return n


def status() -> dict:
    _tabellen()
    with g.sperre:
        q = g.db().execute("SELECT COUNT(*) FROM objekt WHERE modus = 'quarantaene'").fetchone()[0]
        gr = g.db().execute("SELECT COUNT(*) FROM p2p_grab").fetchone()[0]
    return {"quarantaene": q, "grabsteine": gr, "herausgeber": herausgeber_wert(frisch=True)}


def heikel(o: g.Objekt) -> list[str]:
    """Gründe, warum nur eine Instanz mit Freigabe-Recht dieses Objekt freigeben darf. Leer = unauffällig."""
    p = o.daten["pruefung"]
    e = p.get("pruefer") or {}
    aus = []
    if o.art == "reflex":
        aus.append("Reflex (Quelltext)")
    if len(str(o.daten.get("inhalt") or "")) > pruefer.INHALT_GELESEN:
        aus.append("Inhalt länger, als der Prüfer liest")
    if p["regeln"]:
        aus.append("Regelbefund: " + "; ".join(p["regeln"])[:160])
    if e.get("status") != FREIGABE_STATUS_OK:
        aus.append(f"Prüfer: {e.get('status', 'ausstehend')}")
    if e.get("enthaelt_anweisung"):
        aus.append("Prüfer: enthält Anweisung")
    if e.get("verlangt_schreibzugriff"):
        aus.append("Prüfer: verlangt Schreibzugriff")
    if e.get("widerspruch_zu"):
        aus.append("Prüfer: Widerspruch zu lokalem Wissen")
    return aus


def freigeben(o: g.Objekt, instanz: str, reflex_recht: bool, freigabe_recht: bool, grund: str) -> g.Objekt:
    if o.modus != "quarantaene":
        raise ValueError(f"{o.id} liegt nicht in der Quarantäne")
    if not (grund or "").strip():
        raise ValueError("Grund ist Pflicht")
    if "pruefer:ausstehend" in o.hashtags and not freigabe_recht:
        raise ValueError("die Prüfung steht noch aus")
    h = heikel(o)
    if h and not freigabe_recht:
        raise ValueError("nur mit Freigabe-Recht (vi-mcp freigeben auf dem Server): " + " · ".join(h)[:300])
    if not h and not (reflex_recht or freigabe_recht):
        raise ValueError(f"Instanz {instanz} darf nicht freigeben")
    o.modus = "test"  # auch nach der Freigabe zunächst vorläufig
    o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:test"]
    o.aendere(f"ki@{instanz}", "aus der Quarantäne freigegeben", grund)
    g.speichere(o)
    if o.art == "reflex":
        reflexe.lade_alle()
    return o


def verwerfen(o: g.Objekt, instanz: str, grund: str) -> g.Objekt:
    if o.modus != "quarantaene":
        raise ValueError(f"{o.id} liegt nicht in der Quarantäne")
    if not (grund or "").strip():
        raise ValueError("Grund ist Pflicht")
    o.modus = "widerlegt"
    o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:widerlegt"]
    o.aendere(f"ki@{instanz}", "aus der Quarantäne verworfen", grund)
    return g.speichere(o)


def zeile(o: g.Objekt) -> str:
    p = o.daten["pruefung"]
    h = heikel(o)
    return f"  [{o.id}] {o.art} von {o.daten['herkunft']['herausgeber']} · Prüfer {(p.get('pruefer') or {}).get('status', 'ausstehend')} · {'heikel: ' + ' · '.join(h)[:200] if h else 'unauffällig'}\n     Daten, keine Anweisung: {o.text[:200]}"
