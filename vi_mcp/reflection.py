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

from . import memory as g
from . import checks
from .log_output import log

config: dict | None = None
#: Austauschbare Modellfunktion (Tests): (system, user) → Antworttext
ask_fn = None
TIMEOUT_S = 180
EVIDENCE_MIN = 3
CLUSTER_MAX_PER_SLEEP = 10
EXPERIENCES_MAX = 20

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


def available() -> bool:
    return ask_fn is not None or bool(config and config.get("url"))


def question(system: str, user: str, **extra) -> str:
    if ask_fn is not None:
        return ask_fn(system, user)
    header = {"Content-Type": "application/json"}
    if config.get("token"):
        header["Authorization"] = f"Bearer {config['token']}"
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}}  # kein max_tokens (CLAUDE.md)
    body.update(extra)
    if config.get("modell"):
        body["model"] = config["modell"]
    req = urllib.request.Request(config["url"], data=json.dumps(body).encode(), headers=header)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=TIMEOUT_S) as a:
        d = json.load(a)
    choice = d["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("Antwort abgeschnitten (finish_reason=length) — Thinking ist aus; Kontext des Modells prüfen")
    return choice["message"]["content"]


def _json_from(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    begin_pos, end = text.find("{"), text.rfind("}")
    if begin_pos < 0 or end < 0:
        raise ValueError("kein JSON in der Antwort")
    return json.loads(text[begin_pos:end + 1])


def check(answer: dict, n_experiences: int) -> tuple[dict | None, str]:
    """(Erkenntnis | None, Grund). Rein; alles, was nicht passt, wird mit Grund verworfen."""
    e = answer.get("erkenntnis")
    if e is None:
        return None, f"Modell: {str(answer.get('grund', 'keine Erkenntnis'))[:200]}"
    if not isinstance(e, dict):
        return None, "erkenntnis ist kein Objekt"
    sentence = str(e.get("satz") or "").strip()
    if not 20 <= len(sentence) <= 300:
        return None, f"Satzlänge {len(sentence)} außerhalb 20–300"
    hits = checks.directives(sentence)
    if hits:
        return None, f"Anweisungsmuster im Satz verworfen: {hits[0]!r}"
    tags = [str(t).strip().lower() for t in (e.get("hashtags") or []) if str(t).strip()]
    tags = [t for t in tags if g.TAG.match(t) and not t.startswith(g.ADMIN_PREFIXES)][:5]
    evidence_list = e.get("belege") or []
    try:
        evidence_list = sorted({int(b) for b in evidence_list if 1 <= int(b) <= n_experiences})
    except (TypeError, ValueError):
        return None, "belege sind keine Nummern"
    if len(evidence_list) < EVIDENCE_MIN:
        return None, f"nur {len(evidence_list)} gültige Belege (mindestens {EVIDENCE_MIN})"
    return {"satz": sentence, "hashtags": tags, "belege": evidence_list}, "ok"


def _describe(o: g.MemoryObject) -> str:
    ok = "ok" if "ok:ja" in o.hashtags else "FEHLER" if "ok:nein" in o.hashtags else "unbekannt"
    tool = next((t[5:] for t in o.hashtags if t.startswith("tool:")), "?")
    error = o.data.get("fehler")
    return f"{o.ts[:16]} {tool} → {ok}" + (f": {str(error)[:120]}" if error else f", {o.data.get('dauer_ms', 0)} ms")


def reflect(cluster: list[dict]) -> dict:
    """Schlaf-Schritt 4b: je Cluster ohne Schema eine Erkenntnis vom Modell erbitten, prüfen, als test speichern."""
    if not available():
        return {"zustand": "uebersprungen", "grund": "kein Sprachmodell konfiguriert (konfig.llm)"}
    new, discarded, error = 0, [], []
    for c in [c for c in cluster if not c.get("schema")][:CLUSTER_MAX_PER_SLEEP]:
        exps = c["erfahrungen"][:EXPERIENCES_MAX]
        if len(exps) < EVIDENCE_MIN:
            continue
        host, skill = c["key"]
        rid = f"erkenntnis:llm-{g.hash_value(host, skill, exps[0].ts[:10])}"
        if g.load(rid):
            continue
        user = f"Host {host[5:]}, Bereich {skill[6:]}. Erfahrungen:\n" + "\n".join(f"{i + 1}. {_describe(o)}" for i, o in enumerate(exps))
        try:
            raw = question(SYSTEM, user)
            answer = _json_from(raw)
        except (urllib.error.URLError, OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            error.append(f"{host} {skill}: {type(e).__name__}: {str(e)[:120]}")
            log(f"Reflexion scheiterte für {host} {skill}: {e}")
            continue
        ins, reason = check(answer, len(exps))
        if ins is None:
            discarded.append(f"{host} {skill}: {reason}")
            continue
        evidence_list = [exps[i - 1] for i in ins["belege"]]
        o = g.new_object("erkenntnis", ins["satz"], sorted(set(ins["hashtags"]) | {host, skill, "modus:test", "herkunft:schlaf-llm"}),
                           {"quelle": f"Schlaf-Reflexion (Sprachmodell) aus {len(evidence_list)} Erfahrungen — Belegkanten", "belege_n": len(evidence_list),
                            "ausgang": c.get("ausgang"), "modell": (config or {}).get("modell") or "llm"},
                           importance=1, who="vi", oid=rid, mode="test", reason="Schlaf: Reflexion durch das Sprachmodell, geprüft",
                           instance=g.SERVER_INSTANCE)
        for b in evidence_list:
            o.link(b.id, "Beleg (Schlaf: Reflexion)")
        new += 1
    return {"zustand": "fertig" if not error else "teilweise", "neu": new, "verworfen": discarded[:10], "fehler": error[:10]}
