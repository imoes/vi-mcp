"""VIL — the language in which an AI asks the memory and the memory answers (0.62.0, first executable part).

The user (13.11.2026): "Im Prinzip bräuchten wir eine KI-Sprache, die wie Programmcode funktioniert, mit Suchtermen und Anweisungen …
damit sich KIs einfach und effizient miteinander verständigen können, über Grenzen hinweg", in English, and its meaning trained in
weights. Design (README, CHANGELOG 0.62.0): a readable symbol layer — speech act plus words — over a weight layer — vectors and measured
weights per word. This module is the symbol layer for `ask`; the answer comes back as `tell` lines.

An utterance:  ACT[.TYPE] WORD…  — tolerant: anything that does not start with a known act is an ordinary vi_recall filter.

  act    ask (question), tell, do, promise, def, rate — only ask is executed here; the others are named, never run (a foreign `do` is data).
         The body of a `def rule` is the logic notation of logic.py (facts, head <= body, never(…), soft(…)), checked by vi_logic.
  type   for ask: how · why · what · who · where · rule — which question it is
  words  kind:value as in vi_recall, plus short forms:  @web1 → host:web1* (a name without a dot: every host starting with it),
         @web1.example → host:web1.example   #x → thema:x   since:30d / since:2026-10-01 (recency)
         !word negates, (a OR b), "phrase", free text — unchanged

The question type does not reorder the hits (ORDER "off"): every reordering measured on a production copy — the fixed prior, a lift
for labelled objects, the word weights — lowered MRR (see ORDER). The type is kept in the search log, so a relevance weight can be
learned for it; the modes of `order` stay to measure against. The raw utterance stays
in the search log, so the type of every question is there to learn from.

The answer (format "vil"): one line per hit
  tell.<memory> <id> "<text>" ev:<evidence> w:<weight>/<n> src:"<source>"
memory: fact · procedure · rule · episode (from the object's kind until labels exist); evidence: how the memory knows it — measured
(it was shown and rated), documented (a source URL), hearsay (imported from another server), inferred (derived by a language model),
unknown (named, never silently "observed"); weight: success after showing (beta mean of helped/not helped) with the number of ratings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

ACTS = ("ask", "tell", "do", "promise", "def", "rate")
QTYPES = ("how", "why", "what", "who", "where", "rule")
_HEAD = re.compile(r"^\s*(" + "|".join(ACTS) + r")(?:\.([a-z]+))?(?=\s|$)", re.I)
_SINCE = re.compile(r"(?<!\S)since:(\d+)([dhw])(?!\S)|(?<!\S)since:(\d{4}-\d{2}-\d{2})(?!\S)")
_SHORT = re.compile(r"(?<![\w:])([!(]*)([@#])([A-Za-z0-9][\w.\-:/]*)")

#: which kinds of knowledge usually answer which question — the fixed prior (hashtag or kind prefixes, in order of preference)
PRIOR = {
    "how": ("art:skill", "art_wissen:loesung", "art_wissen:runbook", "art_wissen:handbuch", "art_wissen:doku-extern"),
    "why": ("fehler:", "ausgang:schlecht", "art_wissen:loesung"),
    "rule": ("art:regel", "thema:vorgabe"),
    "who": ("person:", "team:", "zustaendig:"),
    "where": ("host:", "pfad:", "port:", "url:"),
    "what": (),
}


@dataclass
class Utterance:
    act: str | None            # None: no VIL — an ordinary filter
    qtype: str | None
    filter: str                # the vi_recall filter the words translate to
    since: str | None = None   # ISO time: only objects learned or used since then
    notes: list[str] = field(default_factory=list)


def parse(text: str, now: datetime | None = None) -> Utterance:
    """Pure. A VIL utterance → act, question type and the vi_recall filter. Never raises: what it cannot read it names in notes."""
    raw = text or ""
    m = _HEAD.match(raw)
    if not m:
        return Utterance(None, None, raw)
    act, sub = m.group(1).lower(), (m.group(2) or "").lower() or None
    rest = raw[m.end():]
    notes = []
    qtype = None
    if act == "ask":
        if sub in QTYPES:
            qtype = sub
        elif sub:
            notes.append(f"unknown question type .{sub} (known: {', '.join(QTYPES)}) — searched without one")
    since = None
    s = _SINCE.search(rest)
    if s:
        now = now or datetime.now(timezone.utc)
        if s.group(1):
            n, unit = int(s.group(1)), s.group(2)
            since = (now - timedelta(days=n) if unit == "d" else now - timedelta(hours=n) if unit == "h" else now - timedelta(weeks=n)).isoformat(timespec="seconds")
        else:
            since = s.group(3)
        rest = rest[:s.start()] + rest[s.end():]
    def short(x):
        neg, sign, word = x.group(1), x.group(2), x.group(3)
        if sign == "#":
            return f"{neg}thema:{word.lower()}"
        # host hashtags are fully qualified: @web1 (no dot) means every host whose name starts with it, @web1.example exactly that one
        return f"{neg}host:{word}" + ("" if "." in word or word.endswith("*") else "*")
    rest = _SHORT.sub(short, rest)
    return Utterance(act, qtype, " ".join(rest.split()), since, notes)


#: How the question type orders hits. Measured 13.11.2026 on a production copy (fixed question set, 140 typed questions × 2 styles =
#: 280 queries, paired against the plain hybrid order, MRR 0.737):
#:   "prior"          the fixed prior as a priority rank (first design)       −0.059 ± 0.012 without word weights, −0.289 ± 0.021 with them
#:   "labels"         a hit labelled answers:<type> lifted ≤ LIFT places        −0.006 ± 0.003 (4 worse, 0 better; 257 labelled objects)
#:   "labels+weights" plus ±1 place by the measured word weight for the type   −0.056 ± 0.010 (47 worse, 4 better)
#: Nothing reordered for the better, so the default is "off": the search's relevance order stays. Hypothesis for the word weights: they
#: measure whether a hint helped an action, not whether a hit answers a question — another label; a relevance weight has to be learned
#: from what is used after a search (suche_log). The modes stay to measure against.
ORDER = "off"
ORDERS = ("off", "labels", "labels+weights", "prior")
LIFT = 2


def order(hits: list, qtype: str | None, mode: str | None = None) -> list:
    """The hits of a VIL question in their new order: relevance first, bounded lifts (see ORDER). hits = [(score, object, …)]."""
    mode = mode or ORDER
    if not qtype or mode == "off" or not hits:
        return list(hits)
    if mode == "prior":
        from . import word_weights
        return sorted(hits, key=lambda h: (prior_rank(h[1], qtype), -round(word_weights.hit_weight(h[1], qtype), 2)))
    keyed = []
    for i, h in enumerate(hits):
        lift = LIFT if f"answers:{qtype}" in h[1].hashtags else 0
        if mode == "labels+weights":
            from . import word_weights
            w = word_weights.hit_weight(h[1], qtype)
            lift += 1 if w >= 0.6 else -1 if w <= 0.4 else 0
        keyed.append((i - lift - 0.5 * (lift > 0) + 0.5 * (lift < 0), i, h))  # ±0.5: ahead of (behind) the hit it moves past
    return [h for _k, _i, h in sorted(keyed, key=lambda x: (x[0], x[1]))]


def prior_rank(o, qtype: str | None) -> int:
    """0 = labelled as answering this type (classify.py, answers:<type>), 1 = unlabelled but of the kind that usually answers it (the
    fixed PRIOR), 2 = anything else. Stable order inside each rank: priority, not exclusion."""
    if not qtype:
        return 2
    tags = set(o.hashtags) | {f"art:{o.kind}"}
    if f"answers:{qtype}" in tags:
        return 0
    if any(t.startswith("answers:") and t != "answers:unsure" for t in tags):
        return 2  # labelled as answering something else: the label wins over the fixed prior
    prefixes = PRIOR.get(qtype, ())
    return 1 if any(t == p or (p.endswith(":") and t.startswith(p)) for t in tags for p in prefixes) else 2


MEMORY = {"skill": "procedure", "regel": "rule", "erfahrung": "episode", "gespraech": "episode"}


def memory_of(o) -> str:
    lab = next((t[7:] for t in o.hashtags if t.startswith("memory:") and t != "memory:unsure"), None)
    if lab:  # labelled by classify.py
        return lab
    if o.kind in MEMORY:
        return MEMORY[o.kind]
    if any(t.startswith("art_wissen:loesung") for t in o.hashtags):
        return "procedure"
    return "fact"


def evidence_of(o) -> str:
    from . import bandit
    if str(o.instance or "").startswith("p2p-") or "herkunft:p2p" in o.hashtags:
        return "hearsay"
    yes, no = bandit.counter(o)
    if yes + no > 0:
        return "measured"
    if "herkunft:schlaf-llm" in o.hashtags:  # derived by a language model in sleep — not every object of instance vi is
        return "inferred"
    if re.search(r"https?://", str(o.data.get("quelle") or "")):
        return "documented"
    return "unknown"


def weight_of(o) -> tuple[float, int]:
    from . import bandit
    yes, no = bandit.counter(o)
    return round((1 + yes) / (2 + yes + no), 2), int(round(yes + no))


def tell_line(o) -> str:
    w, n = weight_of(o)
    text = o.text[:200].replace("\n", " ").replace('"', "'")
    src = str(o.data.get("quelle") or "")[:120].replace('"', "'")
    return f'tell.{memory_of(o)} {o.id} "{text}" ev:{evidence_of(o)} w:{w}/{n}' + (f' src:"{src}"' if src else "")
