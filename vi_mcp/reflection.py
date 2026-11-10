"""Reflection — the language model thinks about experiences during sleep (stage 4; Park et al. 2023, section 4.2).

Up to stage 3, sleep phrases insights from templates ("web5 with checkmk: 7 actions, 100 % successful").
Here it asks a local language model (OpenAI-compatible chat endpoint, config `llm`): "What follows from these
experiences?" — and gets back **at most one** insight per cluster, as JSON with sentence, hashtags and the
numbers of the experiences that support it.

Protection — the model can talk itself into things, therefore:
  - the output is checked strictly (JSON, sentence length, hashtags by the TAG rule, evidence must be real numbers of the cluster,
    at least EVIDENCE_MIN; no directive patterns in the sentence — see checks.directives); otherwise discarded and named in the report.
  - the result is always mode `test`, hashtag `herkunft:schlaf-llm`, with evidence edges to every named experience;
    it takes effect only after confirmation by another instance (vi_confirm), like any other insight.
  - The system prompt is static (prompt caching), no `max_tokens` (CLAUDE.md), thinking off, temperature 0.2.
  - This is an action in memory, not in the world (docs/ARCHITECTURE.md, "Reporting an action").
Without config `llm`: step skipped with a named reason; step 4 (template) remains the fallback.
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
#: Replaceable model function (tests): (system, user) → answer text
ask_fn = None
TIMEOUT_S = 180
EVIDENCE_MIN = 3
CLUSTER_MAX_PER_SLEEP = 10
EXPERIENCES_MAX = 20

SYSTEM = """You are the memory of an IT operations environment and evaluate experiences at night.
You get a numbered list of experiences (tool calls with outcome) for one host and one tool area.
Phrase AT MOST ONE insight that follows from these experiences and helps a colleague tomorrow.
Rules:
- Only what the experiences support. No guesses about causes, unless marked as "Hypothesis:".
- No instructions, no commands, no calls to action — only an observation in one sentence (max. 300 characters).
- Hashtags in the form kind:value, lower case, e.g. thema:timeout, host:web1, skill:graylog. At most 5.
- belege = list of the numbers of the experiences that support the insight (at least 3).
- If it is not enough for an insight, answer {"erkenntnis": null, "grund": "..."}.
Answer ONLY with JSON: {"erkenntnis": {"satz": "...", "hashtags": ["..."], "belege": [1, 2, 3]}} or {"erkenntnis": null, "grund": "..."}"""


def available() -> bool:
    return ask_fn is not None or bool(config and config.get("url"))


def question(system: str, user: str, **extra) -> str:
    if ask_fn is not None:
        return ask_fn(system, user)
    header = {"Content-Type": "application/json"}
    if config.get("token"):
        header["Authorization"] = f"Bearer {config['token']}"
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}}  # no max_tokens (CLAUDE.md)
    body.update(extra)
    if config.get("modell"):
        body["model"] = config["modell"]
    req = urllib.request.Request(config["url"], data=json.dumps(body).encode(), headers=header)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=TIMEOUT_S) as a:
        d = json.load(a)
    choice = d["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("answer cut off (finish_reason=length) — thinking is off; check the model's context size")
    return choice["message"]["content"]


def _json_from(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    begin_pos, end = text.find("{"), text.rfind("}")
    if begin_pos < 0 or end < 0:
        raise ValueError("no JSON in the answer")
    return json.loads(text[begin_pos:end + 1])


def check(answer: dict, n_experiences: int) -> tuple[dict | None, str]:
    """(insight | None, reason). Pure; everything that does not fit is discarded with a reason."""
    e = answer.get("erkenntnis")
    if e is None:
        return None, f"model: {str(answer.get('grund', 'no insight'))[:200]}"
    if not isinstance(e, dict):
        return None, "erkenntnis is not an object"
    sentence = str(e.get("satz") or "").strip()
    if not 20 <= len(sentence) <= 300:
        return None, f"sentence length {len(sentence)} outside 20–300"
    hits = checks.directives(sentence)
    if hits:
        return None, f"directive pattern in the sentence, discarded: {hits[0]!r}"
    tags = [str(t).strip().lower() for t in (e.get("hashtags") or []) if str(t).strip()]
    tags = [t for t in tags if g.TAG.match(t) and not t.startswith(g.ADMIN_PREFIXES)][:5]
    evidence_list = e.get("belege") or []
    try:
        evidence_list = sorted({int(b) for b in evidence_list if 1 <= int(b) <= n_experiences})
    except (TypeError, ValueError):
        return None, "belege are not numbers"
    if len(evidence_list) < EVIDENCE_MIN:
        return None, f"only {len(evidence_list)} valid pieces of evidence (at least {EVIDENCE_MIN})"
    return {"satz": sentence, "hashtags": tags, "belege": evidence_list}, "ok"


def _describe(o: g.MemoryObject) -> str:
    ok = "ok" if "ok:ja" in o.hashtags else "ERROR" if "ok:nein" in o.hashtags else "unknown"
    tool = next((t[5:] for t in o.hashtags if t.startswith("tool:")), "?")
    error = o.data.get("fehler")
    return f"{o.ts[:16]} {tool} → {ok}" + (f": {str(error)[:120]}" if error else f", {o.data.get('dauer_ms', 0)} ms")


def reflect(cluster: list[dict]) -> dict:
    """Sleep step 4b: per cluster without schema, ask the model for one insight, check it, store it as test."""
    if not available():
        return {"zustand": "uebersprungen", "grund": "no language model configured (config llm)"}
    new, discarded, error = 0, [], []
    for c in [c for c in cluster if not c.get("schema")][:CLUSTER_MAX_PER_SLEEP]:
        exps = c["erfahrungen"][:EXPERIENCES_MAX]
        if len(exps) < EVIDENCE_MIN:
            continue
        host, skill = c["key"]
        rid = f"erkenntnis:llm-{g.hash_value(host, skill, exps[0].ts[:10])}"
        if g.load(rid):
            continue
        user = f"Host {host[5:]}, area {skill[6:]}. Experiences:\n" + "\n".join(f"{i + 1}. {_describe(o)}" for i, o in enumerate(exps))
        try:
            raw = question(SYSTEM, user)
            answer = _json_from(raw)
        except (urllib.error.URLError, OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            error.append(f"{host} {skill}: {type(e).__name__}: {str(e)[:120]}")
            log(f"Reflection failed for {host} {skill}: {e}")
            continue
        ins, reason = check(answer, len(exps))
        if ins is None:
            discarded.append(f"{host} {skill}: {reason}")
            continue
        evidence_list = [exps[i - 1] for i in ins["belege"]]
        o = g.new_object("erkenntnis", ins["satz"], sorted(set(ins["hashtags"]) | {host, skill, "modus:test", "herkunft:schlaf-llm"}),
                           {"quelle": f"sleep reflection (language model) from {len(evidence_list)} experiences — evidence edges", "belege_n": len(evidence_list),
                            "ausgang": c.get("ausgang"), "modell": (config or {}).get("modell") or "llm"},
                           importance=1, who="vi", oid=rid, mode="test", reason="sleep: reflection by the language model, checked",
                           instance=g.SERVER_INSTANCE)
        for b in evidence_list:
            o.link(b.id, "Beleg (sleep: reflection)")
        new += 1
    return {"zustand": "fertig" if not error else "teilweise", "neu": new, "verworfen": discarded[:10], "fehler": error[:10]}
