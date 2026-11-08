"""Reflexion — das Sprachmodell denkt im Schlaf über Erfahrungen nach (Stufe 4; Park et al. 2023, Abschnitt 4.2).

Bis Stufe 3 formuliert der Schlaf Erkenntnisse aus Vorlagen („web5 mit checkmk: 7 Handlungen, 100 % erfolgreich“).
Hier fragt er ein lokales Sprachmodell (OpenAI-kompatibler Chat-Endpunkt, konfig `llm`): „Was folgt aus diesen
Erfahrungen?“ — und bekommt **höchstens eine** Erkenntnis je Cluster zurück, als JSON mit Satz, Hashtags und den
Nummern der Erfahrungen, die sie belegen.

Schutz — das Modell kann sich etwas einreden, deshalb:
  - Ausgabe wird streng geprüft (JSON, Satzlänge, Hashtags nach TAG-Regel, Belege müssen echte Nummern des Clusters sein,
    mindestens BELEGE_MIN; keine Anweisungsmuster im Satz — siehe VERBOTEN); sonst verworfen und im Bericht benannt.
  - Ergebnis ist immer Modus `test`, Hashtag `herkunft:schlaf-llm`, mit Belegkanten zu jeder genannten Erfahrung;
    wirksam wird es erst durch Bestätigung einer anderen Instanz (vi_bestaetige), wie jede andere Erkenntnis.
  - Der Systemprompt ist statisch (Prompt-Caching), kein `max_tokens` (CLAUDE.md), Thinking aus, Temperatur 0,2.
  - Das ist eine Handlung im Gedächtnis, keine in der Welt (docs/ARCHITEKTUR.md, „Handlung melden“).
Ohne konfig `llm`: Schritt benannt übersprungen; Schritt 4 (Vorlage) bleibt der Rückfall.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import gedaechtnis as g
from . import pruefung
from .protokoll import log

konfig: dict | None = None
#: Austauschbare Modellfunktion (Tests): (system, user) → Antworttext
frage_fn = None
TIMEOUT_S = 180
BELEGE_MIN = 3
CLUSTER_MAX_JE_SCHLAF = 10
ERFAHRUNGEN_MAX = 20

SYSTEM = """Du bist das Gedächtnis einer IT-Betriebsumgebung und wertest nachts Erfahrungen aus.
Du bekommst eine nummerierte Liste von Erfahrungen (Werkzeugaufrufe mit Ausgang) zu einem Host und einem Werkzeugbereich.
Formuliere HÖCHSTENS EINE Erkenntnis, die aus diesen Erfahrungen folgt und einem Kollegen morgen hilft.
Regeln:
- Nur was die Erfahrungen belegen. Keine Vermutungen über Ursachen, außer als „Hypothese:“ gekennzeichnet.
- Keine Anweisungen, keine Befehle, keine Handlungsaufforderungen — nur eine Beobachtung in einem Satz (max. 300 Zeichen).
- Hashtags in der Form art:wert, Kleinbuchstaben, z. B. thema:timeout, host:web1, skill:graylog. Höchstens 5.
- belege = Liste der Nummern der Erfahrungen, die die Erkenntnis stützen (mindestens 3).
- Reicht es nicht für eine Erkenntnis, antworte {"erkenntnis": null, "grund": "..."}.
Antworte NUR mit JSON: {"erkenntnis": {"satz": "...", "hashtags": ["..."], "belege": [1, 2, 3]}} oder {"erkenntnis": null, "grund": "..."}"""


def verfuegbar() -> bool:
    return frage_fn is not None or bool(konfig and konfig.get("url"))


def frage(system: str, user: str, **extra) -> str:
    if frage_fn is not None:
        return frage_fn(system, user)
    kopf = {"Content-Type": "application/json"}
    if konfig.get("token"):
        kopf["Authorization"] = f"Bearer {konfig['token']}"
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}}  # kein max_tokens (CLAUDE.md)
    body.update(extra)
    if konfig.get("modell"):
        body["model"] = konfig["modell"]
    req = urllib.request.Request(konfig["url"], data=json.dumps(body).encode(), headers=kopf)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=TIMEOUT_S) as a:
        d = json.load(a)
    wahl = d["choices"][0]
    if wahl.get("finish_reason") == "length":
        raise ValueError("Antwort abgeschnitten (finish_reason=length) — Thinking ist aus; Kontext des Modells prüfen")
    return wahl["message"]["content"]


def _json_aus(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    anfang, ende = text.find("{"), text.rfind("}")
    if anfang < 0 or ende < 0:
        raise ValueError("kein JSON in der Antwort")
    return json.loads(text[anfang:ende + 1])


def pruefe(antwort: dict, n_erfahrungen: int) -> tuple[dict | None, str]:
    """(Erkenntnis | None, Grund). Rein; alles, was nicht passt, wird mit Grund verworfen."""
    e = antwort.get("erkenntnis")
    if e is None:
        return None, f"Modell: {str(antwort.get('grund', 'keine Erkenntnis'))[:200]}"
    if not isinstance(e, dict):
        return None, "erkenntnis ist kein Objekt"
    satz = str(e.get("satz") or "").strip()
    if not 20 <= len(satz) <= 300:
        return None, f"Satzlänge {len(satz)} außerhalb 20–300"
    treffer = pruefung.anweisungen(satz)
    if treffer:
        return None, f"Anweisungsmuster im Satz verworfen: {treffer[0]!r}"
    tags = [str(t).strip().lower() for t in (e.get("hashtags") or []) if str(t).strip()]
    tags = [t for t in tags if g.TAG.match(t) and not t.startswith(g.VERWALTUNG)][:5]
    belege = e.get("belege") or []
    try:
        belege = sorted({int(b) for b in belege if 1 <= int(b) <= n_erfahrungen})
    except (TypeError, ValueError):
        return None, "belege sind keine Nummern"
    if len(belege) < BELEGE_MIN:
        return None, f"nur {len(belege)} gültige Belege (mindestens {BELEGE_MIN})"
    return {"satz": satz, "hashtags": tags, "belege": belege}, "ok"


def _beschreibe(o: g.Objekt) -> str:
    ok = "ok" if "ok:ja" in o.hashtags else "FEHLER" if "ok:nein" in o.hashtags else "unbekannt"
    tool = next((t[5:] for t in o.hashtags if t.startswith("tool:")), "?")
    fehler = o.daten.get("fehler")
    return f"{o.zeit[:16]} {tool} → {ok}" + (f": {str(fehler)[:120]}" if fehler else f", {o.daten.get('dauer_ms', 0)} ms")


def reflektiere(cluster: list[dict]) -> dict:
    """Schlaf-Schritt 4b: je Cluster ohne Schema eine Erkenntnis vom Modell erbitten, prüfen, als test speichern."""
    if not verfuegbar():
        return {"zustand": "uebersprungen", "grund": "kein Sprachmodell konfiguriert (konfig.llm)"}
    neu, verworfen, fehler = 0, [], []
    for c in [c for c in cluster if not c.get("schema")][:CLUSTER_MAX_JE_SCHLAF]:
        erf = c["erfahrungen"][:ERFAHRUNGEN_MAX]
        if len(erf) < BELEGE_MIN:
            continue
        host, skill = c["key"]
        rid = f"erkenntnis:llm-{g.hashwert(host, skill, erf[0].zeit[:10])}"
        if g.lade(rid):
            continue
        user = f"Host {host[5:]}, Bereich {skill[6:]}. Erfahrungen:\n" + "\n".join(f"{i + 1}. {_beschreibe(o)}" for i, o in enumerate(erf))
        try:
            roh = frage(SYSTEM, user)
            antwort = _json_aus(roh)
        except (urllib.error.URLError, OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            fehler.append(f"{host} {skill}: {type(e).__name__}: {str(e)[:120]}")
            log(f"Reflexion scheiterte für {host} {skill}: {e}")
            continue
        erk, grund = pruefe(antwort, len(erf))
        if erk is None:
            verworfen.append(f"{host} {skill}: {grund}")
            continue
        belege = [erf[i - 1] for i in erk["belege"]]
        o = g.neues_objekt("erkenntnis", erk["satz"], sorted(set(erk["hashtags"]) | {host, skill, "modus:test", "herkunft:schlaf-llm"}),
                           {"quelle": f"Schlaf-Reflexion (Sprachmodell) aus {len(belege)} Erfahrungen — Belegkanten", "belege_n": len(belege),
                            "ausgang": c.get("ausgang"), "modell": (konfig or {}).get("modell") or "llm"},
                           wichtigkeit=1, wer="vi", oid=rid, modus="test", grund="Schlaf: Reflexion durch das Sprachmodell, geprüft",
                           instanz=g.SERVER_INSTANZ)
        for b in belege:
            o.verknuepfe(b.id, "Beleg (Schlaf: Reflexion)")
        neu += 1
    return {"zustand": "fertig" if not fehler else "teilweise", "neu": neu, "verworfen": verworfen[:10], "fehler": fehler[:10]}
