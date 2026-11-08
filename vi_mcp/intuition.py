"""Intuition — der automatische Gedächtniszugriff vor und das Lernen nach jeder Handlung.

Die VI handelt nie selbst. Ein Client (Agent, Skill-Server, Hook) meldet eine Handlung zweimal:
  vorher(tool, args)   → gemerkte Antwort (wenn lesend und frisch), Hinweise (Erkenntnisse, Regeln, gelernte
                         Suchen, Vorher-Reflexe), evtl. von einem aktiven Reflex geänderte Argumente.
                         Der Zugriff selbst wird gespeichert (Erfahrung.daten.vorher: Reize, Gefundenes).
  nachher(...)         → Erfahrung (ok/Fehler, Dauer), gemerkte Antwort (wenn lesend), Nachher-Reflexe.
Bewusstsein = Erkenntnisse/Regeln (Hinweise), Unterbewusstsein = gemerkte Antworten/Reflexe.
Grenze: schreibende Werkzeuge werden nie aus dem Gedächtnis beantwortet.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone

from . import gedaechtnis as g
from . import reflexe

#: Werkzeuge, die etwas verändern (Wortteile im Namen) — nie aus dem Gedächtnis beantwortet. Ein Client kann
#: `lesend` ausdrücklich angeben; dann gilt seine Angabe, nicht das Namensmuster.
SCHREIBEND = re.compile(r"(create|add|update|launch|acknowledge|push|transition|assign|send|click|run_|type_text|"
                        r"schedule|delete|link|comment|modify|set_|_auth_|login|logout|focus|foreground|move_|write|edit|"
                        r"activate|bake|discovery|downtime|reschedule|refresh|vergiss|lerne|markiere|bestaetige|widerlege)", re.I)
TTL_STANDARD = 120
TTL_MAX = 3600
HOSTKEYS = ("host", "hostname", "host_name", "node", "device")
OFFEN_MAX_S = 3600

ttl_je_werkzeug: dict[str, int] = {}
#: vorher-Zugriffe, die auf ihr nachher warten: {vorher_id: (zeitpunkt, tool, args, zugriff, instanz, lesend, gespraech)}.
#: Kommt kein nachher, wird der Zugriff nicht still verworfen, sondern als Erfahrung mit `ok:unbekannt` gespeichert
#: (beim Ende des Gesprächs oder nach OFFEN_MAX_S) — siehe offene_abschliessen().
_offen: dict[str, tuple] = {}
_offen_sperre = threading.Lock()


def lesend(tool: str, angabe: bool | None = None) -> bool:
    return angabe if isinstance(angabe, bool) else not SCHREIBEND.search(tool)


def reize(tool: str, args: dict, kontext: list[str] | None = None) -> list[str]:
    """Hinweisreize einer Handlung: Werkzeug, Skill (Präfix bis zum ersten _), Host aus den Argumenten, dazu die
    Kontext-Hashtags des Clients (woran er gerade arbeitet, z. B. thema:oom). Ungültige Hashtags fallen weg."""
    r = [f"tool:{tool}", f"skill:{tool.split('_')[0]}"]
    for k, v in (args or {}).items():
        if k in HOSTKEYS and isinstance(v, str) and v.strip():
            r.append(f"host:{v.strip().lower()}")
    r += [t.strip() for t in (kontext or []) if isinstance(t, str) and not t.startswith(g.VERWALTUNG)]
    return list(dict.fromkeys(t for t in r if g.TAG.match(t)))


def fehler_signatur(text: str) -> str:
    return re.sub(r"[0-9a-f]{8,}|\d+", "#", (text or "")[:160])


def _frage(tool: str, args: dict) -> str:
    return g.hashwert(tool, json.dumps(args, sort_keys=True, ensure_ascii=False))


def vorher(tool: str, args: dict, instanz: str | None = None, ist_lesend: bool | None = None,
           kontext: list[str] | None = None) -> dict:
    args, hinweise = reflexe.vorher(tool, dict(args or {}))
    from . import fragen  # spät: fragen nutzt gedaechtnis wie wir
    hinweise += fragen.zustellen(instanz)
    rz = reize(tool, args, kontext)
    such_reize = rz
    gefunden, suchen = [], []
    for _, o, _g in g.erinnere("(" + " OR ".join(such_reize) + ")", limit=4, arten=("erkenntnis", "regel")):
        o.zugriff()
        gefunden.append(o.id)
        herkunft = f"von {o.instanz}" + (f", bestätigt von {o.fremde_bestaetigungen()} weiteren Instanz(en)" if o.fremde_bestaetigungen() else "")
        hinweise.append(f"{'Gelernt' if o.art == 'erkenntnis' else 'Regel'} [{o.id[:28]}] ({herkunft}"
                        + (", STRITTIG — von einer anderen Instanz widersprochen" if o.modus == "strittig" else "")
                        + f"; {', '.join(t for t in o.hashtags if t.startswith(('modus:', 'skill:', 'kollektiv:')))[:60]}): "
                        f"{o.text[:300]} [Quelle: {str(o.daten.get('quelle', '—'))[:120]}]")
    # 1. Zugriff auf Gelerntes: Suchen, deren Hinweisreize zur Handlung passen, laufen automatisch
    for _, su, _g in g.erinnere("(" + " OR ".join(such_reize) + ")", limit=3, arten=("suche",)):
        su.zugriff()
        treffer = [o for _, o, _g2 in g.erinnere(su.daten.get("filter", ""), limit=3) if o.id != su.id]
        for o in treffer:
            o.zugriff()
        gefunden += [su.id] + [o.id for o in treffer]
        suchen.append({"suche": su.id, "name": su.daten.get("name"), "treffer": [o.id for o in treffer]})
        hinweise.append(f"Gelernte Suche „{su.daten.get('name')}“ [{su.daten.get('filter')}] — {su.text[:120]}: "
                        + ("; ".join(f"[{o.id[:24]}] {o.text[:90]}" for o in treffer) if treffer else "keine Treffer"))
    antwort, alter_s, ttl = None, None, None
    if lesend(tool, ist_lesend):
        ttl = min(ttl_je_werkzeug.get(tool, TTL_STANDARD), TTL_MAX)
        for _, o, _g in g.erinnere(f"art:antwort cache:{_frage(tool, args)}", limit=1, betrachter=instanz):
            alter = (datetime.now(timezone.utc) - datetime.fromisoformat(o.zeit)).total_seconds()
            if alter <= ttl:
                o.zugriff()
                gefunden.append(o.id)
                antwort, alter_s = o.daten.get("ergebnis", ""), int(alter)
    zugriff = {"reize": rz, "gefunden": gefunden, "suchen": suchen, "aus_gedaechtnis": antwort is not None}
    vorher_id = secrets.token_hex(8)
    if antwort is not None:
        erfahrung(tool, args, True, 0, None, antwort, zugriff, instanz, ist_lesend)
    else:
        offene_abschliessen(nur_aelter_als_s=OFFEN_MAX_S)
        with _offen_sperre:
            _offen[vorher_id] = (time.monotonic(), tool, args, zugriff, instanz, ist_lesend, g.aktuelles_gespraech.get())
    return {"vorher_id": vorher_id, "antwort": antwort, "antwort_alter_s": alter_s, "antwort_ttl_s": ttl,
            "args": args, "hinweise": hinweise, "zugriff": zugriff}


def nachher(tool: str, args: dict, ok: bool, dauer_ms: int, fehler: str | None, ergebnis: str | None,
            vorher_id: str | None = None, instanz: str | None = None, ist_lesend: bool | None = None) -> dict:
    with _offen_sperre:
        offen = _offen.pop(vorher_id, None) if vorher_id else None
    zugriff = offen[3] if offen else {"reize": reize(tool, args or {}), "gefunden": [], "suchen": [],
                                      "aus_gedaechtnis": False, "ohne_vorher": True}
    o = erfahrung(tool, args or {}, ok, dauer_ms, fehler, ergebnis, zugriff, instanz, ist_lesend)
    hinweise = reflexe.nachher(tool, dict(args or {}), ergebnis or "") if ok else []
    return {"erfahrung": o.id, "hinweise": hinweise, "vorher_gefunden": bool(offen)}


def offene_abschliessen(gespraech: str | None = None, nur_aelter_als_s: float | None = None) -> int:
    """vorher ohne nachher → Erfahrung mit ok:unbekannt (benannter Zustand statt stillem Verschwinden).
    Wahl: alle eines Gesprächs (beim Sitzungsende) oder alle älter als nur_aelter_als_s."""
    with _offen_sperre:
        if gespraech is not None:
            ids = [k for k, v in _offen.items() if v[6] == gespraech]
        else:
            grenze = time.monotonic() - (nur_aelter_als_s or 0)
            ids = [k for k, v in _offen.items() if v[0] < grenze]
        faelle = [_offen.pop(k) for k in ids]
    for _t0, tool, args, zugriff, instanz, ist_lesend, serial in faelle:
        tok = g.aktuelles_gespraech.set(serial)
        try:
            erfahrung(tool, args, None, 0, None, None, {**zugriff, "ohne_nachher": True}, instanz, ist_lesend)
        finally:
            g.aktuelles_gespraech.reset(tok)
    return len(faelle)


def erfahrung(tool: str, args: dict, ok: bool | None, dauer_ms: int, fehler: str | None, ergebnis: str | None,
              zugriff: dict, instanz: str | None = None, ist_lesend: bool | None = None) -> g.Objekt:
    tags = [f"tool:{tool}", f"skill:{tool.split('_')[0]}", f"ok:{'unbekannt' if ok is None else 'ja' if ok else 'nein'}"]
    tags += [t for t in zugriff.get("reize", []) if t.startswith("host:")]
    if fehler:
        sig = fehler_signatur(fehler)[:60].replace(" ", "_").replace("(", "_").replace(")", "_")
        if g.TAG.match(f"fehler:{sig}"):
            tags.append(f"fehler:{sig}")
    tags = [t for t in tags if g.TAG.match(t)]
    text = f"{tool}({json.dumps(args, ensure_ascii=False)[:300]}) → " + (f"Fehler: {fehler[:300]}" if fehler else "kein Ergebnis gemeldet (vi_nachher fehlt)" if ok is None
                                                                       else f"ok, {len(ergebnis or '')} Zeichen, {dauer_ms} ms")
    o = g.neues_objekt("erfahrung", text, tags, {"args": args, "dauer_ms": dauer_ms, "fehler": fehler, "vorher": zugriff},
                       wichtigkeit=2 if fehler else 0, grund="Werkzeugaufruf", instanz=instanz)
    for oid in zugriff.get("gefunden", []):
        o.verknuepfe(oid, "vor der Handlung erinnert")
    if ok and ergebnis is not None and lesend(tool, ist_lesend) and not zugriff.get("aus_gedaechtnis") and len(ergebnis) <= 200_000:
        fh = _frage(tool, args)
        with g.sperre:
            # nur die eigene gemerkte Antwort ersetzen — der Cache ist privat je Instanz
            alt = [r[0] for r in g.db().execute("SELECT t.objekt_id FROM tag t JOIN objekt o ON o.id = t.objekt_id "
                                                "WHERE t.tag = ? AND o.instanz = ?", (f"cache:{fh}", o.instanz))]
        g.loesche(alt)
        g.neues_objekt("antwort", text, [f"tool:{tool}", f"cache:{fh}"], {"ergebnis": ergebnis, "args": args},
                       wichtigkeit=0, grund="Antwort gemerkt", instanz=instanz)
    from . import sitzung  # spät: sitzung kennt intuition nicht
    s = sitzung.aktuelle()
    if s:
        s.zug({"zeit": g.jetzt(), "tool": tool, "args": args, "ok": ok, "dauer_ms": dauer_ms, "fehler": fehler,
               "vorher": zugriff, "erfahrung": o.id})
    return o
