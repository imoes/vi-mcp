"""0.43.0: AIs talk in the network — questions and answers between servers, what vi_ask/vi_answer already do between the instances of
one server (questions.py), carried by the logbooks.

A post is a logbook entry of type `beitrag` {faden, eltern, art (frage|antwort), text, inhalt, hashtags, reize, autor, netz_id,
loesch_hash, zeit}; its id is the SHA-256 of its content. A thread (faden) is the id of its question.
  ask      vi_ask(to="netz" or "netz:<name>") — the local question as before, plus a post for the network
  ingest   a foreign post: fixed rules, then quarantine like every import (the user's decision: only after review)
             question → a question object to "alle", delivered at the next vi_before after release
             answer   → only to an own question; an object of kind erkenntnis (it is knowledge, with evidence) — after release it is
                        appended to the question and reaches the asker like a local answer; vi_confirm/vi_refute on it are ratings
                        and feed the network score (net_score)
  reply    vi_answer on a question from the network → a post of kind antwort
Authors: in an open network a stable pseudonym per instance and network (ki-<HMAC>), which recognises a partner without naming the
instance; in a company network the instance name.
States of an incoming post (exhaustive): ausstehend · frei · verworfen · vergessen · fremd (an answer to a question not asked here: not kept).
"""
from __future__ import annotations

import hashlib
import hmac
import json

from . import memory as g
from .logbook import pseudonym, sha256

MAX_OPEN_PER_INSTANCE = 20
STATES = ("ausstehend", "frei", "verworfen", "vergessen")


def _tables() -> None:
    with g.lock:
        g.db().executescript("""
            CREATE TABLE IF NOT EXISTS beitrag_aus (netz TEXT NOT NULL, id TEXT NOT NULL, art TEXT NOT NULL, faden TEXT, eltern TEXT, instanz TEXT NOT NULL,
                                                   daten TEXT NOT NULL, zeit TEXT NOT NULL, oid TEXT, PRIMARY KEY (netz, id));
            CREATE TABLE IF NOT EXISTS beitrag_ein (netz TEXT NOT NULL, id TEXT NOT NULL, art TEXT NOT NULL, faden TEXT, eltern TEXT, pub TEXT NOT NULL,
                                                   autor TEXT NOT NULL, status TEXT NOT NULL, oid TEXT, netz_id TEXT NOT NULL, loesch_hash TEXT NOT NULL,
                                                   empfangen TEXT NOT NULL, entschieden TEXT, PRIMARY KEY (netz, id));
            CREATE INDEX IF NOT EXISTS beitrag_ein_netz_id ON beitrag_ein (netz_id);
        """)
        g.db().commit()


def author(instance: str, net: str) -> str:
    from . import p2p
    if p2p.is_company(net):
        return instance
    return "ki-" + hmac.new(p2p._token(instance).encode(), b"autor|" + net.encode(), hashlib.sha256).hexdigest()[:10]


def _check_outgoing(content: dict, net: str) -> None:
    from . import anonymize, checks, p2p
    company = p2p.is_company(net)
    b = checks.check_post(content, internal_ok=company)
    if b.verdict == "ablehnen":
        where = " for the open network" if not company and any("internals" in r for r in b.reasons) else ""
        raise ValueError(f"post refused{where}: " + "; ".join(b.reasons)[:300])
    if not company:
        known = p2p._known()
        for name in ("text", "inhalt"):
            if hits := anonymize.categories(content[name], known):
                raise ValueError(f"post refused for the open network: {name} contains {', '.join(hits)} — write it without, or use a company network")


def _post(instance: str, net: str, art: str, text: str, inhalt: str, hashtags: list, reize: list, faden, eltern, key: str) -> dict:
    from . import checks, p2p
    token = p2p._token(instance)
    if not token:
        raise ValueError(f"instance {instance} has no network token (vi_net_token): without it a post could never be revoked")
    net_id, obj_token = p2p._object_token(token, key, net)
    clean = lambda ts: sorted({t.strip() for t in ts or [] if isinstance(t, str) and g.TAG.match(t.strip()) and not t.strip().startswith(checks.FIXED_HASHTAGS)})[:20]  # noqa: E731
    content = {"faden": faden, "eltern": eltern, "art": art, "text": (text or "").strip()[:2000], "inhalt": (inhalt or "").strip()[:20000],
               "hashtags": clean(hashtags), "reize": clean(reize), "autor": author(instance, net), "netz_id": net_id,
               "loesch_hash": hashlib.sha256(obj_token.encode()).hexdigest(), "zeit": g.now()[:10]}
    _check_outgoing(content, net)
    return content


def ask(instance: str, net: str, text: str, triggers: list, source: str) -> g.MemoryObject:
    """A question to the network: local question object (as vi_ask) + post."""
    from . import p2p, questions
    if net not in p2p.networks():
        raise ValueError(f"unknown network {net!r} — known: {', '.join(p2p.networks())}")
    _tables()
    with g.lock:
        n = g.db().execute("SELECT COUNT(*) FROM objekt WHERE art = 'frage' AND json_extract(daten, '$.von') = ? AND json_extract(daten, '$.an') LIKE 'netz:%' "
                           "AND json_extract(daten, '$.zustand') IN ('offen', 'zugestellt')", (instance,)).fetchone()[0]
    if n >= MAX_OPEN_PER_INSTANCE:
        raise ValueError(f"{n} questions of {instance} to the network are still open (at most {MAX_OPEN_PER_INSTANCE}); they expire after {questions.EXPIRY_DAYS} days")
    content = _post(instance, net, "frage", text, source, [], triggers, None, None, f"beitrag|frage|{instance}|{g.now()}|{text[:40]}")
    o = questions.ask(instance, f"netz:{net}", text, triggers, source)
    pid = sha256(content)
    o.data["beitrag"] = {"netz": net, "id": pid, "richtung": "aus"}
    g.save(o)
    with g.lock:
        g.db().execute("INSERT INTO beitrag_aus (netz, id, art, faden, eltern, instanz, daten, zeit, oid) VALUES (?,?,?,?,?,?,?,?,?)",
                       (net, pid, "frage", None, None, instance, json.dumps(content, ensure_ascii=False), g.now(), o.id))
        g.db().commit()
    return o


def reply(instance: str, question: g.MemoryObject, text: str, evidence: str) -> str | None:
    """An answer of a local instance to a question that came from the network → a post. None if the question is not from the network."""
    b = question.data.get("beitrag") or {}
    if b.get("richtung") != "ein":
        return None
    content = _post(instance, b["netz"], "antwort", text, evidence, [], [], b.get("faden") or b["id"], b["id"], f"beitrag|antwort|{instance}|{g.now()}|{b['id']}")
    pid = sha256(content)
    _tables()
    with g.lock:
        g.db().execute("INSERT INTO beitrag_aus (netz, id, art, faden, eltern, instanz, daten, zeit, oid) VALUES (?,?,?,?,?,?,?,?,?)",
                       (b["netz"], pid, "antwort", content["faden"], b["id"], instance, json.dumps(content, ensure_ascii=False), g.now(), question.id))
        g.db().commit()
    return pid


def outgoing(net: str, limit: int = 500) -> list[dict]:
    _tables()
    with g.lock:
        return [json.loads(d) for (d,) in g.db().execute("SELECT daten FROM beitrag_aus WHERE netz = ? ORDER BY zeit DESC LIMIT ?", (net, limit))]


def ingest(raw: dict, header: dict, net: str) -> str:
    """'neu', 'bekannt', 'fremd' or the reason of a rejection."""
    from . import checks, net_score, p2p
    b = checks.check_post(raw, internal_ok=p2p.is_company(net))
    if b.verdict == "ablehnen":
        return "; ".join(b.reasons)[:200]
    if raw["netz_id"] != header.get("netz_id") or raw["loesch_hash"] != header.get("loesch_hash") or sha256(raw) != header["sha"]:
        return "header and content name different posts"
    pid = header["sha"]
    _tables()
    with g.lock:
        if g.db().execute("SELECT 1 FROM beitrag_ein WHERE netz = ? AND id = ?", (net, pid)).fetchone():
            return "bekannt"
        tomb = g.db().execute("SELECT token_sha FROM p2p_grab WHERE netz_id = ?", (raw["netz_id"],)).fetchone()
        mine = g.db().execute("SELECT oid FROM beitrag_aus WHERE netz = ? AND id = ? AND art = 'frage'", (net, raw["eltern"])).fetchone() if raw["art"] == "antwort" else None
    if tomb and tomb[0] == raw["loesch_hash"]:
        return "bekannt"
    if raw["art"] == "antwort" and not mine:
        return "fremd"  # an answer to someone else's question: not ours to keep
    name = pseudonym(header["pub"])
    company = p2p.is_company(net)
    herkunft = {"herausgeber": name, "pubkey": header["pub"], "seq": header["seq"], "sha256": pid, "netz_id": raw["netz_id"], "netz": net}
    common = {"herkunft": herkunft, "pruefung": {"regeln": b.reasons, "pruefer": None}, "fremd_text": raw["text"], "fremd_hashtags": raw["hashtags"] + raw["reize"],
              "beitrag": {"netz": net, "id": pid, "faden": raw["faden"] or pid, "art": raw["art"], "autor": raw["autor"], "richtung": "ein"}}
    tags = ["herkunft:p2p", "herkunft:gespraech", f"herausgeber:{name}", "pruefer:ausstehend", "modus:quarantaene", f"netz:{net}"]
    if raw["art"] == "frage":
        data = {**common, "von": f"{raw['autor']}@{net}", "an": "alle", "zustand": "offen", "quelle": raw["inhalt"] or f"question in network {net}",
                "zugestellt_an": [], "antworten": [], "gemeldet": 0}
        o = g.new_object("frage", raw["text"], sorted(set(raw["reize"] + raw["hashtags"] + tags + ["an:alle", "zustand:offen"])), data, importance=2,
                         who=f"import@{name}", reason=f"question from {raw['autor']} in {net}", oid=f"frage:post-{pid[:32]}", mode="quarantaene",
                         instance=f"p2p-{name}", visibility="intern" if company else None)
    else:
        data = {**common, "quelle": (raw["inhalt"] or f"answer in network {net}")[:500], "inhalt": raw["inhalt"], "frage": mine[0]}
        o = g.new_object("erkenntnis", raw["text"], sorted(set(raw["hashtags"] + tags)), data, who=f"import@{name}", reason=f"answer from {raw['autor']} in {net}",
                         oid=f"erkenntnis:post-{pid[:32]}", mode="quarantaene", instance=f"p2p-{name}", visibility="intern" if company else None)
        form = {"art": "erkenntnis", "text": raw["text"], "inhalt": raw["inhalt"], "hashtags": raw["hashtags"]}
        ish = net_score.content_hash(form)  # an answer is content like any other: holders and network score
        net_score.link(ish, o.id)
        net_score.add_holder(ish, header["pub"], net, raw["netz_id"], header["seq"])
    with g.lock:
        g.db().execute("INSERT INTO beitrag_ein (netz, id, art, faden, eltern, pub, autor, status, oid, netz_id, loesch_hash, empfangen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (net, pid, raw["art"], raw["faden"], raw["eltern"], header["pub"], raw["autor"], "ausstehend", o.id, raw["netz_id"], raw["loesch_hash"], g.now()))
        g.db().commit()
    return "neu"


def on_release(o: g.MemoryObject, accepted: bool) -> None:
    from . import questions
    b = o.data.get("beitrag") or {}
    if b.get("richtung") != "ein":
        return
    _tables()
    with g.lock:
        g.db().execute("UPDATE beitrag_ein SET status = ?, entschieden = ? WHERE netz = ? AND id = ?", ("frei" if accepted else "verworfen", g.now(), b["netz"], b["id"]))
        g.db().commit()
    if not accepted:
        return
    if b["art"] == "frage":  # a question carries no claim: once reviewed it is delivered like a local one
        o.mode = "aktiv"
        o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:aktiv"]
        g.save(o)
        return
    q = g.load(o.data.get("frage") or "")
    if q and q.kind == "frage":
        q.data["antworten"] = q.data["antworten"] + [{"instanz": f"{b['autor']}@{b['netz']}", "text": o.text[:2000], "belege": str(o.data.get("inhalt") or "")[:500],
                                                        "zeit": g.now(), "objekt": o.id}]
        questions._set_state(q, "beantwortet")
        q.change("vi", f"answer from the network ({b['autor']})", "released after review")
        g.save(q)


def forget(net_id: str, evidence: str) -> bool:
    _tables()
    with g.lock:
        z = g.db().execute("SELECT netz, id, loesch_hash, oid FROM beitrag_ein WHERE netz_id = ?", (net_id,)).fetchone()
    if not z or not hmac.compare_digest(z[2], evidence):
        return False
    with g.lock:
        g.db().execute("UPDATE beitrag_ein SET status = 'vergessen', entschieden = ? WHERE netz = ? AND id = ?", (g.now(), z[0], z[1]))
        g.db().commit()
    if z[3] and g.load(z[3]):
        g.delete([z[3]])
    return True


def stats(days: float = 7) -> dict:
    from datetime import datetime, timedelta, timezone
    _tables()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    with g.lock:
        sent = dict(g.db().execute("SELECT art, COUNT(*) FROM beitrag_aus WHERE zeit >= ? GROUP BY art", (since,)).fetchall())
        recv = dict(g.db().execute("SELECT art, COUNT(*) FROM beitrag_ein WHERE empfangen >= ? GROUP BY art", (since,)).fetchall())
        waiting = g.db().execute("SELECT COUNT(*) FROM beitrag_ein WHERE status = 'ausstehend'").fetchone()[0]
        partners = g.db().execute("SELECT COUNT(DISTINCT autor) FROM beitrag_ein WHERE empfangen >= ?", (since,)).fetchone()[0]
        qs = g.db().execute("SELECT oid, zeit FROM beitrag_aus WHERE art = 'frage' AND zeit >= ?", (since,)).fetchall()
    answered, firsts, per_q, accepted, expired = 0, [], [], 0, 0
    for oid, t0 in qs:
        q = g.load(oid)
        if not q:
            continue
        net_answers = [a for a in q.data.get("antworten") or [] if a.get("objekt")]
        expired += q.data.get("zustand") == "abgelaufen"
        per_q.append(len(net_answers))
        if net_answers:
            answered += 1
            first = min(a["zeit"] for a in net_answers)
            firsts.append((datetime.fromisoformat(first.replace("Z", "+00:00")) - datetime.fromisoformat(t0.replace("Z", "+00:00"))).total_seconds() / 3600)
            accepted += any((o := g.load(a["objekt"])) and o.confirmed > 0 for a in net_answers)
    firsts.sort()
    per_q.sort()
    q = lambda xs, p: round(xs[min(len(xs) - 1, int(p * len(xs)))], 1) if xs else None  # noqa: E731
    return {"gesendet": sent, "empfangen": recv, "in_pruefung": waiting, "partner": partners, "fragen": len(qs), "beantwortet": answered,
            "antworten_median": q(per_q, 0.5), "erste_antwort_h_median": q(firsts, 0.5), "erste_antwort_h_p90": q(firsts, 0.9),
            "angenommen": accepted, "abgelaufen": expired}
