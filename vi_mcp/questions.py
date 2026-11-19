"""Questions between instances — instances learn from each other by asking each other.

A question is an object `kind:question` (geteilt) with `daten`:
  von, an (instance name or "all"), text, reize, zustand, zugestellt_an [instances], antworten [{instanz, text,
  belege, zeit}], gemeldet (answers the asker has already seen).
States (exhaustive): `offen` (not yet shown to any target instance) · `zugestellt` (shown to at least one) ·
`beantwortet` (at least one answer) · `abgelaufen` (after EXPIRY_DAYS without an answer; set by the loop).
Delivery: at the target instance's next `vi_before` as a hint (once per instance). Answers reach the
asker likewise at its next `vi_before` — or via `vi_questions`.

Between conversations of ONE instance (0.66.0): all Claude Code sessions of a machine share the instance `claude-code`, so a
question to the own instance goes to its other conversations. The question records its origin `von_gespraech` (the asker's
conversation; a hook's conversation counts as its agent's, session.canonical) and optionally a target `an_gespraech`
(`to="claude-code#<conversation>"`). Such a question is delivered once per other conversation (`zugestellt_gespraeche`), never to the
asking one; its answers go back to the asking conversation — to any conversation of the instance only once the asking one has ended
(said in the hint). Questions between different instances keep their behaviour: delivered once per instance.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from . import memory as g, names

STATES = ("open", "delivered", "answered", "expired")
EXPIRY_DAYS = 7


def _set_state(o: g.MemoryObject, state: str) -> None:
    state = names.english(names.STATES, state)  # 0.67.0
    o.data["state"] = state
    o.hashtags = [t for t in o.hashtags if not t.startswith("state:")] + [f"state:{state}"]


ANSWER_MAX = 20000
EVIDENCE_MAX = 2000


CONVERSATION = re.compile(r"\d{11,14}")


def split_target(to: str) -> tuple[str, str | None]:
    """'claude-code#20261115004' → ('claude-code', '20261115004'); without '#' the conversation is None. Pure."""
    inst, _, conv = (to or "").partition("#")
    return inst, (conv or None)


def own_conversation() -> str | None:
    """The asking conversation as other conversations know it: a hook's conversation stands for its agent's."""
    from . import session
    return session.canonical(g.current_conversation.get())


def ask(from_: str, to: str, text: str, triggers: list[str], source: str, conversation: str | None = None) -> g.MemoryObject:
    if len((text or "").strip()) < 10:
        raise ValueError("text (the question, one sentence) is required")
    to, target = split_target(to)
    to = names.canonical_target(to)  # 0.67.0: alle/netz/netz:<n> of older clients
    if not to or not (all(c.isalnum() or c in "-_." for c in to) or re.fullmatch(r"net:[a-z][a-z0-9-]{1,30}", to)):
        raise ValueError("to: name of an instance, 'all', or net:<network> (0.43.0: a question to the network); "
                         "<instance>#<conversation> asks one conversation")
    if target is not None and (not CONVERSATION.fullmatch(target) or to in ("all",) or to.startswith("net:")):
        raise ValueError(f"#{target}: a conversation is its serial number (e.g. claude-code#20261115004), and only after an instance name")
    if to == from_ and not conversation:
        raise ValueError("a question to your own instance needs a conversation to come from (an MCP session) — otherwise use vi_recall")
    if to == from_ and target is not None and target == conversation:
        raise ValueError("a question to your own conversation is no question — use vi_recall")
    tags = [t.strip() for t in triggers or [] if isinstance(t, str) and g.TAG.match(t.strip()) and not t.startswith(g.ADMIN_PREFIXES)]
    text = text.strip()
    if len(text) > ANSWER_MAX:
        raise ValueError(f"a question has at most {ANSWER_MAX} characters — put longer material into an object (vi_learn) and name its id")
    # 14.11.2026: the question used to be cut to 1000 characters without notice; the whole text is now kept in inhalt
    o = g.new_object("question", text[:1000], tags + [f"to:{to}", f"from:{from_}", "state:open"],
                       {"from": from_, "to": to, "state": "open", "source": (source or "").strip()[:500],
                        "delivered_to": [], "answers": [], "reported": 0, **({"inhalt": text} if len(text) > 1000 else {}),
                        **({"from_conversation": conversation} if conversation else {}), **({"to_conversation": target} if target else {}),
                        **({"zugestellt_gespraeche": []} if to == from_ or target else {})},
                       importance=2, who=f"ki@{from_}", reason="vi_ask", instance=from_)
    return o


def _per_conversation(d: dict) -> bool:
    """Delivered per conversation (a question within one instance, or one aimed at a conversation) — else once per instance."""
    return d["from"] == d["to"] or bool(d.get("to_conversation"))


def _who(d: dict, a: dict | None = None) -> str:
    if a is not None:
        return a["instance"] + (f"#{a['conversation']}" if a.get("conversation") else "")
    return d["from"] + (f"#{d['from_conversation']}" if d.get("from_conversation") else "")


def _due_here(d: dict, instance: str, conv: str | None) -> bool:
    """Is this question to be shown in this conversation now? Exhaustive over the two delivery kinds."""
    if d["state"] == "expired" or d["to"] not in (instance, "all"):
        return False
    if _per_conversation(d):
        if not conv or (d["from"] == instance and d.get("from_conversation") == conv):
            return False  # no conversation to deliver to, or the asker's own
        if d.get("to_conversation") and d["to_conversation"] != conv:
            return False
        from . import session
        done = set(d.get("zugestellt_gespraeche", []))
        return conv not in done and session._hook_of.get(conv) not in done  # shown to its hook before the pairing: shown
    return d["from"] != instance and instance not in d["delivered_to"]


def _answers_due_here(d: dict, instance: str, conv: str | None) -> bool:
    """New answers go to the asking conversation; to any of the instance's conversations only once it has ended (or never had one)."""
    from . import session
    if d["from"] != instance or len(d["answers"]) <= d.get("reported", 0):
        return False
    asker = d.get("from_conversation")
    return not asker or asker == conv or not session.is_open(asker)


def deliver(instance: str | None, conversation: str | None = None) -> list[str]:
    """Hints for `vi_before`: new questions to this instance (or this conversation) and new answers to its questions. Marks them.
    conversation: the calling conversation, canonical (a hook's stands for its agent's); default: the current one."""
    return [i["text"] for i in _collect(instance, conversation, mark=True)]


def pending(instance: str | None, conversation: str | None = None) -> list[dict]:
    """0.70.4: what `deliver` would show now, WITHOUT marking it — for the push channel (stdio_bridge --channel). The client may drop a
    pushed message silently (Claude Code does when its channel gate is closed), so only the next `vi_before` marks it delivered and
    nothing is lost; the pushed item can therefore appear a second time there. Items: {kind: question|answer, id, text}."""
    return _collect(instance, conversation, mark=False)


def _collect(instance: str | None, conversation: str | None, mark: bool) -> list[dict]:
    if not instance:
        return []
    conv = conversation if conversation is not None else own_conversation()
    items = []
    with g.lock:
        ids = [r[0] for r in g.db().execute(
            "SELECT id FROM object WHERE kind = 'question' AND json_extract(data, '$.state') IN ('open', 'delivered', 'answered') "
            "AND mode NOT IN ('quarantine', 'refuted', 'withdrawn') "  # 0.43.0: a question from the network only after review
            "AND (json_extract(data, '$.to') IN (?, 'all') OR json_extract(data, '$.from') = ?) ORDER BY ts", (instance, instance))]
        for oid in ids:
            o = g.load(oid)
            d = o.data
            if _due_here(d, instance, conv):
                full = str(d.get("content") or o.text)
                more = f" … (complete: vi_questions(id={o.id}))" if len(full) > 400 else ""
                items.append({"kind": "question", "id": o.id,
                              "text": f"Question from {_who(d)} [{o.id}]: {full[:400]}{more} — answer with vi_answer(id, text, belege)"})
                if mark:
                    if _per_conversation(d):
                        d["zugestellt_gespraeche"] = d.get("zugestellt_gespraeche", []) + [conv]
                        where = f"{instance}#{conv}"
                    else:
                        d["delivered_to"] = d["delivered_to"] + [instance]
                        where = instance
                    if d["state"] == "open":
                        _set_state(o, "delivered")
                    o.change("vi", f"delivered to {where}", "next vi_before of the target")
                    g.save(o)
            if _answers_due_here(d, instance, conv):  # not elif: another conversation of the asker may get the question and its answers
                new = d["answers"][d.get("reported", 0):]
                ended = (f" (the asking conversation {d['from_conversation']} has ended — shown here so it is not lost)"
                         if d.get("from_conversation") and d["from_conversation"] != conv else "")
                items += [{"kind": "answer", "id": o.id,
                           "text": f"Answer from {_who(d, a)} to your question [{o.id}] \"{o.text[:80]}\"{ended}: {a['text'][:400]}"
                           + (f" … (complete: vi_questions(id={o.id}))" if len(a["text"]) > 400 or len(a.get("evidence") or "") > 160 else "")
                           + (f" [Evidence: {a['evidence'][:160]}]" if a.get("evidence") else "")} for a in new]
                if mark:
                    d["reported"] = len(d["answers"])
                    g.save(o)
    return items


def answer_question(oid: str, instance: str, text: str, evidence_list: str, conversation: str | None = None) -> g.MemoryObject:
    o = g.load(oid)
    if not o or o.kind != "question":
        raise ValueError(f"question {oid} unknown")
    d = o.data
    if d["state"] == "expired":
        raise ValueError(f"question {oid} has expired ({EXPIRY_DAYS} days without an answer)")
    if d["from"] == instance and (not d.get("from_conversation") or d["from_conversation"] == conversation):
        raise ValueError("you do not answer your own question — use vi_learn if you found it out yourself")
    if d["to"] not in (instance, "all"):
        raise ValueError(f"the question went to {d['to']}, not to {instance}")
    if d.get("to_conversation") and d["to_conversation"] != conversation:
        raise ValueError(f"the question went to conversation {d['to']}#{d['to_conversation']}, not to this one ({conversation or 'none'})")
    if len((text or "").strip()) < 10 or len((evidence_list or "").strip()) < 8:
        raise ValueError("text (the answer) and belege (command/URL/measurement) are required")
    # 14.11.2026: answers were cut to 2000 and evidence to 500 characters without notice (a review ended mid-sentence). Stored whole
    # now; longer is refused with the reason — nothing disappears silently.
    if len(text.strip()) > ANSWER_MAX or len(evidence_list.strip()) > EVIDENCE_MAX:
        raise ValueError(f"an answer has at most {ANSWER_MAX} characters and its evidence at most {EVIDENCE_MAX} — put longer material "
                         "into an object (vi_learn) and name its id in the answer")
    entry = {"instance": instance, "text": text.strip(), "evidence": evidence_list.strip(), "ts": g.now(),
             **({"conversation": conversation} if conversation else {})}
    # The object's data has a size limit, past which the generic shortening drops the oldest half of the longest list — here the
    # answers (Codex's review, 14.11.2026). Refuse before that happens; nothing already answered may vanish.
    if len(json.dumps({**d, "antworten": d["answers"] + [entry]}, ensure_ascii=False)) > g.DATA_MAX - 2000:
        raise ValueError(f"this answer does not fit: the question already holds {len(d['answers'])} answers near the size limit "
                         f"({g.DATA_MAX} characters) — ask a new question or put the material into an object (vi_learn) and name its id")
    d["answers"] = d["answers"] + [entry]
    _set_state(o, "answered")
    o.change(f"ki@{instance}", "answered", "vi_answer")
    return g.save(o)


def listing(instance: str, conversation: str | None = None) -> tuple[list[g.MemoryObject], list[g.MemoryObject]]:
    """(questions to me, offen/zugestellt), (my questions, all states). Within one instance, "me" is this conversation: questions of
    the instance's other conversations are to me, and my own are those this conversation asked (and questions asked without one)."""
    with g.lock:
        to_me = [r[0] for r in g.db().execute(
            "SELECT id FROM object WHERE kind = 'question' AND json_extract(data, '$.state') IN ('open', 'delivered') AND mode NOT IN ('quarantine', 'refuted', 'withdrawn') "
            "AND json_extract(data, '$.to') IN (?, 'all') ORDER BY ts DESC LIMIT 200", (instance,))]
        mine = [r[0] for r in g.db().execute(
            "SELECT id FROM object WHERE kind = 'question' AND json_extract(data, '$.from') = ? ORDER BY ts DESC LIMIT 200", (instance,))]

    def to_this(d: dict) -> bool:
        if d.get("to_conversation") and d["to_conversation"] != conversation:
            return False
        if d["from"] != instance:
            return True
        return bool(d.get("from_conversation")) and d["from_conversation"] != conversation and bool(conversation)

    def from_this(d: dict) -> bool:
        return not d.get("from_conversation") or not conversation or d["from_conversation"] == conversation

    return ([o for o in (g.load(i) for i in to_me) if o and to_this(o.data)][:50],
            [o for o in (g.load(i) for i in mine) if o and from_this(o.data)][:50])


def let_expire() -> int:
    bound = (datetime.now(timezone.utc) - timedelta(days=EXPIRY_DAYS)).isoformat(timespec="seconds")
    with g.lock:
        ids = [r[0] for r in g.db().execute(
            "SELECT id FROM object WHERE kind = 'question' AND ts < ? AND json_extract(data, '$.state') IN ('open', 'delivered')", (bound,))]
        for oid in ids:
            o = g.load(oid)
            _set_state(o, "expired")
            o.change("vi", "expired", f"{EXPIRY_DAYS} days without an answer")
            g.save(o)
    return len(ids)
