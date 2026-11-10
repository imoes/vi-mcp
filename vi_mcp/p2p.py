"""The memory on the network: anonymous outbox, checked inbox, quarantine, right to be forgotten, value per publisher.

Transport and logbooks belong to the network service (net_service.py, own process). Only what it delivers via `vi_net_inbox` arrives here, and the
signature is checked again anyway: the network service reads foreign data and could be compromised.
Anonymous: the network knows the publisher only by pseudonym; objects carry no instance, no host names, only the date (anonymize.py).
Only proven knowledge goes out: shared, active and confirmed by another instance or with measured benefit.
Forgetting: every instance has a network token. Per object it yields a `netz_id` and a `loesch_hash` (SHA-256 of the object token HMAC(token, oid)).
Whoever presents the object token proves authorship without the network knowing the instance; one object token opens no other object.
Inbox flow: signature → fixed rules (checks.py) → quarantine → reviewer (reviewer.py) → release.
Only source text is distributed, as a JSON field. Imported content is a text hint and triggers nothing; code runs only in the sandbox.
Release: unremarkable objects by an instance with reflex permission or, if `p2p.auto_freigabe` is set, automatically during sleep. Reflexes, write access,
detected instructions and everything without a positive review verdict only by an instance with release permission, whose token stays on the server (vi-mcp release).
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

from . import memory as g
from . import anonymize, bandit, reviewer, checks, reflexes, sandbox, vector
from . import logbook as lb
from .logbook import canonical, pseudonym, generate_keys, sha256  # noqa: F401

MAX_OBJECTS = 2000
VALUE_MIN_VERDICTS = 20
VALUE_BLOCK = 0.3
PROVEN_YES = 3
EXPORT_KINDS = ("erkenntnis", "regel", "suche", "skill")
RELEASE_STATUS_OK = "zulassen"

#: {"reflexe_von": [pubkey], "auto_freigabe": bool, "oeffentliche_domains": [...], "interne_namen": [...]}
config: dict = {}


def _proven(o: g.MemoryObject) -> bool:
    yes, no = bandit.counter(o)
    return o.foreign_confirmations() >= 1 or (yes >= PROVEN_YES and yes >= 3 * no)


def _tables() -> None:
    with g.lock:
        g.db().executescript("""
            CREATE TABLE IF NOT EXISTS p2p_gesehen (sha TEXT PRIMARY KEY, oid TEXT NOT NULL, herausgeber TEXT NOT NULL, anzahl INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS netz_token (instanz TEXT PRIMARY KEY, token TEXT NOT NULL, zeit TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS netz_widerruf (oid TEXT PRIMARY KEY, instanz TEXT NOT NULL, netz_id TEXT NOT NULL, token TEXT NOT NULL, zeit TEXT NOT NULL, grund TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS p2p_netz (netz_id TEXT PRIMARY KEY, oid TEXT NOT NULL, loesch_hash TEXT NOT NULL, sha TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS p2p_grab (netz_id TEXT PRIMARY KEY, token_sha TEXT NOT NULL, zeit TEXT NOT NULL);
        """)
        g.db().commit()


def _object_token(token: str, oid: str) -> tuple[str, str]:
    """(netz_id, object_token). Neither can be derived from the other, nor the instance token from either."""
    return hmac.new(token.encode(), b"id|" + oid.encode(), hashlib.sha256).hexdigest()[:32], hmac.new(token.encode(), b"vergessen|" + oid.encode(), hashlib.sha256).hexdigest()


def generate_token(instance: str) -> str:
    """Once only: a new token could never revoke entries already distributed."""
    _tables()
    t = secrets.token_urlsafe(32)
    with g.lock:
        if g.db().execute("SELECT 1 FROM netz_token WHERE instanz = ?", (instance,)).fetchone():
            raise ValueError(f"instance {instance} already has a network token; it is not renewed, otherwise distributed entries could no longer be deleted (show it on the server: vi-mcp net-token {instance})")
        g.db().execute("INSERT INTO netz_token (instanz, token, zeit) VALUES (?,?,?)", (instance, t, g.now()))
        g.db().commit()
    return t


def _token(instance: str) -> str | None:
    _tables()
    with g.lock:
        z = g.db().execute("SELECT token FROM netz_token WHERE instanz = ?", (instance,)).fetchone()
    return z[0] if z else None


def show_token(instance: str) -> str | None:
    return _token(instance)


def _known() -> frozenset[str]:
    """Everything this memory knows as an internal name: hosts from hashtags and instances, plus the system."""
    with g.lock:
        hosts = [r[0][5:] for r in g.db().execute("SELECT DISTINCT tag FROM tag WHERE tag LIKE 'host:%'")]
        instances = [r[0] for r in g.db().execute("SELECT DISTINCT instanz FROM objekt WHERE instanz IS NOT NULL")]
    names = set(hosts) | {h.split(".")[0] for h in hosts} | set(instances) | anonymize.system_names()
    return frozenset(n for n in names if n and len(n) >= 3 and n.lower() not in anonymize.GENERIC and not n.startswith("p2p-"))


def _export_form(o: g.MemoryObject, token: str, known_set: frozenset[str]) -> tuple[dict | None, str | None]:
    """The object as the network would see it, or (None, reason). The reason names only the class, never the value."""
    raw_content = str(o.data.get("inhalt") or "")
    if o.data.get("bild"):  # 0.35.0: the network carries text; an image (and what it shows) stays on this server
        return None, "has an image (images stay on this server)"
    if anonymize.CREDENTIAL_WORDS.search(o.text) or anonymize.CREDENTIAL_WORDS.search(raw_content):
        return None, "mentions credentials"
    if len(raw_content) > checks.CONTENT_MAX:
        return None, "content too large for the network"
    ts = o.ts[:10]
    raw_tags = [t for t in o.hashtags if not t.startswith(checks.FIXED_HASHTAGS + anonymize.LOCATION_REF)]
    is_clean = lambda t: anonymize.tool_parts(t)
    tags = sorted({t2 for t in raw_tags if not anonymize.categories(((t2 := is_clean(t)).split(":", 1)[-1]), known_set)})
    net_id, object_token = _object_token(token, o.id)
    outputs = {"art": o.kind, "text": anonymize.replace(o.text, known_set), "hashtags": tags, "quelle": anonymize.replace(str(o.data.get("quelle") or f"geteilte Erfahrung vom {ts}"), known_set)[:500],
           "wichtigkeit": o.importance, "zeit": ts, "netz_id": net_id, "loesch_hash": hashlib.sha256(object_token.encode()).hexdigest()}
    if raw_content:
        outputs["inhalt"] = anonymize.replace(raw_content, known_set)
    if len(re.sub(r"<\w+>|[\W\d]", "", outputs["text"])) < 10:
        return None, "no content left after anonymising"
    if o.kind == "erkenntnis" and o.data.get("ausgang"):
        outputs["ausgang"] = o.data["ausgang"]
    if o.kind == "suche":
        outputs.update(name=anonymize.replace(o.data["name"], known_set), filter=o.data["filter"], reize=[t for t in tags if not t.startswith("suche:")])
        if anonymize.categories(o.data["filter"], known_set) or "host:" in o.data["filter"]:
            return None, "filter contains internals"
    if o.kind == "skill":
        triggers = sorted({r2 for r in o.data["problem"]["reize"] if not r.startswith(anonymize.LOCATION_REF + ("instanz:",)) and not anonymize.categories((r2 := anonymize.tool_parts(r)).split(":", 1)[-1], known_set)})
        outputs.update(name=anonymize.replace(o.data["name"], known_set), reize=triggers, schritte=[anonymize.tool_parts(s["tool"]) for s in o.data["loesung"]["schritte"]])
        if any(anonymize.categories(s, known_set) for s in outputs["schritte"]):
            return None, "steps contain internals"
    for field_name in ("text", "inhalt", "quelle", "name"):
        if isinstance(outputs.get(field_name), str) and anonymize.categories(outputs[field_name], known_set):
            return None, f"{field_name}: still suspicious after replacement"
    probe = checks.check(outputs)
    if probe.verdict == "ablehnen":
        return None, "own import rules: " + ", ".join(g_.split(":")[0] for g_ in probe.reasons)[:120]
    return outputs, None


def _collect(instance: str | None = None) -> tuple[list[tuple[g.MemoryObject, dict]], dict[str, int]]:
    _tables()
    with g.lock:
        withdrawn = {r[0] for r in g.db().execute("SELECT oid FROM netz_widerruf")}
        tokens = dict(g.db().execute("SELECT instanz, token FROM netz_token").fetchall())
    known_set = _known()
    outputs, reason = [], Counter()
    for kind in EXPORT_KINDS:
        for _, o, _g in g.recall(f"art:{kind} !herkunft:p2p", limit=MAX_OBJECTS, viewer=None):
            if o.visibility != "geteilt" or o.mode != "aktiv" or o.id in withdrawn or (instance and o.instance != instance):
                continue
            if not _proven(o):
                reason["not yet proven"] += 1
                continue
            if o.instance not in tokens:
                reason["instance has no network token"] += 1
                continue
            raw, g_ = _export_form(o, tokens[o.instance], known_set)
            if raw is None:
                reason[g_] += 1
            else:
                outputs.append((o, raw))
    return outputs[:MAX_OBJECTS], dict(reason)


def preview(instance: str, limit: int = 10) -> dict:
    """What would go out from this instance — exactly the form the network would see."""
    mem_objects, withheld = _collect(instance)
    return {"anzahl": len(mem_objects), "zurueckgehalten": withheld, "beispiele": [r for _o, r in mem_objects[:limit]]}


def net_forget(instance: str, token: str, ids: list[str] | None, reason: str) -> dict:
    """Revoke own entries from the network. ids=None means all. The local object stays but is no longer distributed."""
    if not (reason or "").strip():
        raise ValueError("reason is required")
    real = _token(instance)
    if not real or not hmac.compare_digest(real.encode(), (token or "").encode()):
        raise ValueError("network token does not match this instance")
    if ids is None:
        with g.lock:
            ids = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE instanz = ? AND art IN (%s)" % ",".join("?" * len(EXPORT_KINDS)), (instance, *EXPORT_KINDS))]
    mem_objects = g.load_many(ids)
    foreign = [i for i in ids if i in mem_objects and mem_objects[i].instance != instance]
    if foreign:
        raise ValueError(f"{len(foreign)} entries belong to another instance; only the author may revoke")
    unknown, n = [i for i in ids if i not in mem_objects], 0
    with g.lock:
        for i in ids:
            if i in mem_objects:
                net_id, t = _object_token(real, i)
                n += g.db().execute("INSERT OR IGNORE INTO netz_widerruf (oid, instanz, netz_id, token, zeit, grund) VALUES (?,?,?,?,?,?)", (i, instance, net_id, t, g.now(), reason[:300])).rowcount
        g.db().commit()
    return {"zurueckgerufen": n, "unbekannt": unknown}


def _revocations() -> list[dict]:
    _tables()
    with g.lock:
        return [{"netz_id": a, "token": b} for a, b in g.db().execute("SELECT netz_id, token FROM netz_widerruf ORDER BY zeit")]


def outbox() -> dict:
    """What may go to the network, unsigned: signing is the network service's job, which keeps its key to itself."""
    mem_objects, withdrawn = _collect()
    return {"objekte": [r for _o, r in mem_objects], "widerrufe": _revocations(), "zurueckgehalten": withdrawn}


def _apply_forget(revocations) -> int:
    """Only whoever knows the object token deletes. A tombstone prevents the object from arriving later after all."""
    n = 0
    for w in revocations if isinstance(revocations, list) else []:
        net_id, token = (w.get("netz_id"), w.get("token")) if isinstance(w, dict) else (None, None)
        if not isinstance(net_id, str) or not isinstance(token, str) or len(token) > 128:
            continue
        evidence = hashlib.sha256(token.encode()).hexdigest()
        with g.lock:
            z = g.db().execute("SELECT oid, loesch_hash, sha FROM p2p_netz WHERE netz_id = ?", (net_id,)).fetchone()
            known = g.db().execute("SELECT 1 FROM p2p_grab WHERE netz_id = ?", (net_id,)).fetchone()
        if z and hmac.compare_digest(z[1], evidence):
            g.delete([z[0]])
            vector.remove_entry(z[0])
            with g.lock:
                g.db().execute("DELETE FROM p2p_netz WHERE netz_id = ?", (net_id,))
                g.db().execute("DELETE FROM p2p_gesehen WHERE sha = ?", (z[2],))
                g.db().commit()
            n += 1
        elif z:
            continue  # wrong token: nothing happens
        if not known:
            with g.lock:
                g.db().execute("INSERT OR IGNORE INTO p2p_grab (netz_id, token_sha, zeit) VALUES (?,?,?)", (net_id, evidence, g.now()[:10]))
                g.db().commit()
    return n


def _create(b: checks.Finding, header: dict, sha: str) -> g.MemoryObject:
    name = pseudonym(header["pub"])
    o, short = b.mem_object, sha[:16]
    instance = f"p2p-{name}"
    data = {"quelle": o["quelle"], "herkunft": {"herausgeber": name, "pubkey": header["pub"], "seq": header["seq"], "sha256": sha, "netz_id": o["netz_id"]},
             "pruefung": {"regeln": b.reasons, "pruefer": None}, "fremd_text": o["text"], "fremd_hashtags": o["hashtags"]}
    tags = o["hashtags"] + ["herkunft:p2p", f"herausgeber:{name}", "pruefer:ausstehend", "modus:quarantaene"]
    if o["art"] == "erkenntnis" and o.get("ausgang"):
        data["ausgang"] = o["ausgang"]
    if o.get("inhalt"):
        data["inhalt"] = o["inhalt"]
    if o["art"] == "suche":
        slug = checks.re.sub(r"[^a-z0-9_-]", "-", o["name"].lower())
        data.update(name=f"p2p-{name}-{slug}"[:60], filter=o["filter"])
        tags += o["reize"]
    if o["art"] == "skill":
        slug = checks.re.sub(r"[^a-z0-9_-]", "-", o["name"].lower())
        n = f"p2p-{name}-{slug}"[:60]
        data.update(name=n, schritte=o["schritte"], problem={"reize": o["reize"]}, loesung={"schritte": [{"tool": s} for s in o["schritte"]], "text": o["text"]},
                     version=1, versionen=[{"version": 1, "zeit": g.now(), "wer": f"import@{name}", "grund": "Import", "belege": []}], belege=[])
        tags += o["reize"]
    if o["art"] == "reflex":
        data.update(name=f"p2p_{name.replace('-', '_')}_{o['name']}"[:40], art="vorher", code=o["code"], laeufe=0, fehler=0)
    oid = f"{o['art']}:p2p-{name}-{short}"
    return g.new_object(o["art"], o["text"], sorted(set(tags)), data, importance=o["wichtigkeit"], who=f"import@{name}", reason=f"import from {name}",
                          oid=oid, mode="quarantaene", instance=instance)


def inbox(entries, in_background: bool = True) -> dict:
    """Check entries from the network and put them into quarantine."""
    _tables()
    report = {"quarantaene": 0, "abgelehnt": 0, "bekannt": 0, "gruende": [], "vergessen": 0}

    def from_seq(reason):
        report["abgelehnt"] += 1
        report["gruende"].append(reason[:200])
    for e in entries if isinstance(entries, list) else []:
        header, raw = e.get("kopf") if isinstance(e, dict) else None, e.get("inhalt") if isinstance(e, dict) else None
        if lb.header_form(header) or not lb.signature_valid(header) or sha256(raw) != header["sha"]:
            from_seq("signature or checksum invalid")
            continue
        if header["typ"] == "widerruf":
            if lb.valid_control_form("widerruf", raw):
                report["vergessen"] += _apply_forget([{"netz_id": raw["ziel"], "token": raw["token"]}])
            continue
        if header["typ"] != "objekt":
            continue
        b = checks.check(raw, header["pub"] in (config.get("reflexe_von") or []))
        if b.verdict != "ablehnen" and (b.mem_object["netz_id"] != header.get("netz_id") or b.mem_object["loesch_hash"] != header.get("loesch_hash")):
            b.reject("header and content name different objects")
        if b.verdict != "ablehnen" and b.mem_object["art"] == "reflex":
            compiled = sandbox.run(b.mem_object["code"], [], check_only=True)  # parse in the sandbox first: foreign code can crash the parser
            reason = compiled.get("fehler") or reflexes.check(b.mem_object["code"], "vorher")
            if reason:
                b.reject(f"code: {reason}"[:300])
        if b.verdict == "ablehnen":
            from_seq("; ".join(b.reasons))
            continue
        with g.lock:
            tombstone = g.db().execute("SELECT token_sha FROM p2p_grab WHERE netz_id = ?", (b.mem_object["netz_id"],)).fetchone()
        if tombstone and hmac.compare_digest(tombstone[0], b.mem_object["loesch_hash"]):
            report["bekannt"] += 1  # revoked: stays away
            continue
        sha = sha256(b.mem_object)
        with g.lock:
            n = g.db().execute("UPDATE p2p_gesehen SET anzahl = anzahl + 1 WHERE sha = ?", (sha,)).rowcount
            g.db().commit()
            old = g.db().execute("SELECT oid, sha FROM p2p_netz WHERE netz_id = ?", (b.mem_object["netz_id"],)).fetchone()
        if n:
            report["bekannt"] += 1
            continue
        if old:  # a new version of the same object replaces the old one
            g.delete([old[0]])
            vector.remove_entry(old[0])
            with g.lock:
                g.db().execute("DELETE FROM p2p_gesehen WHERE sha = ?", (old[1],))
                g.db().commit()
        o = _create(b, header, sha)
        with g.lock:
            g.db().execute("INSERT INTO p2p_gesehen (sha, oid, herausgeber) VALUES (?,?,?)", (sha, o.id, pseudonym(header["pub"])))
            g.db().execute("INSERT OR REPLACE INTO p2p_netz (netz_id, oid, loesch_hash, sha) VALUES (?,?,?,?)", (b.mem_object["netz_id"], o.id, b.mem_object["loesch_hash"], sha))
            g.db().commit()
        report["quarantaene"] += 1
    report["gruende"] = report["gruende"][:20]
    if in_background and report["quarantaene"] and reviewer.available():
        threading.Thread(target=reviewer.work_off, args=(MAX_OBJECTS,), name="vi-pruefer", daemon=True).start()
    return report


_value_cache: tuple[float, dict] = (0.0, {})


def publisher_value(fresh: bool = False) -> dict[str, dict]:
    """Benefit per publisher from the hint counters (beta mean). A publisher that proves harmful is no longer shown."""
    global _value_cache
    if not fresh and time.time() - _value_cache[0] < 300:
        return _value_cache[1]
    with g.lock:
        lines = g.db().execute("SELECT t.tag, COUNT(*), SUM(COALESCE(json_extract(o.daten, '$.nuetzlich.ja'), 0)), SUM(COALESCE(json_extract(o.daten, '$.nuetzlich.nein'), 0)), SUM(COALESCE(json_extract(o.daten, '$.nuetzlich.n'), 0)) "
                                "FROM tag t JOIN objekt o ON o.id = t.objekt_id WHERE t.tag LIKE 'herausgeber:%' GROUP BY t.tag").fetchall()
    outputs = {}
    for tag, n, yes, no, shown_flag in lines:
        mean = (1 + yes) / (2 + yes + no)
        outputs[tag[12:]] = {"objekte": n, "ja": round(yes, 2), "nein": round(no, 2), "gezeigt": shown_flag, "mittel": round(mean, 3), "gesperrt": shown_flag >= VALUE_MIN_VERDICTS and mean < VALUE_BLOCK}
    _value_cache = (time.time(), outputs)
    return outputs


def without_blocked(mem_objects: list[g.MemoryObject]) -> list[g.MemoryObject]:
    if not any("herkunft:p2p" in o.hashtags for o in mem_objects):
        return mem_objects
    value = publisher_value()
    return [o for o in mem_objects if not any(t.startswith("herausgeber:") and value.get(t[12:], {}).get("gesperrt") for t in o.hashtags)]


def auto_approve() -> int:
    """Only with `p2p.auto_freigabe`: what rules and reviewer find unremarkable becomes provisional (mode test). Sensitive items stay with a human."""
    if not config.get("auto_freigabe"):
        return 0
    n = 0
    value = publisher_value(fresh=True)
    for _, o, _g in g.recall("modus:quarantaene", limit=MAX_OBJECTS, viewer=None):
        if "pruefer:ausstehend" in o.hashtags or sensitive(o) or value.get(o.data["herkunft"]["herausgeber"], {}).get("gesperrt"):
            continue
        approve(o, "vi", True, False, "automatic: no rule findings, reviewer admits")
        n += 1
    return n


def status() -> dict:
    _tables()
    with g.lock:
        q = g.db().execute("SELECT COUNT(*) FROM objekt WHERE modus = 'quarantaene'").fetchone()[0]
        gr = g.db().execute("SELECT COUNT(*) FROM p2p_grab").fetchone()[0]
    return {"quarantaene": q, "grabsteine": gr, "herausgeber": publisher_value(fresh=True)}


def sensitive(o: g.MemoryObject) -> list[str]:
    """Reasons why only an instance with release permission may release this object. Empty = unremarkable."""
    p = o.data["pruefung"]
    e = p.get("pruefer") or {}
    outputs = []
    if o.kind == "reflex":
        outputs.append("reflex (source code)")
    if len(str(o.data.get("inhalt") or "")) > reviewer.CONTENT_READ:
        outputs.append("content longer than the reviewer reads")
    if p["regeln"]:
        outputs.append("rule finding: " + "; ".join(p["regeln"])[:160])
    if e.get("status") != RELEASE_STATUS_OK:
        outputs.append(f"reviewer: {e.get('status', 'ausstehend')}")
    if e.get("enthaelt_anweisung"):
        outputs.append("reviewer: contains an instruction")
    if e.get("verlangt_schreibzugriff"):
        outputs.append("reviewer: requires write access")
    if e.get("widerspruch_zu"):
        outputs.append("reviewer: contradicts local knowledge")
    return outputs


def approve(o: g.MemoryObject, instance: str, reflex_permission: bool, release_permission: bool, reason: str) -> g.MemoryObject:
    if o.mode != "quarantaene":
        raise ValueError(f"{o.id} is not in quarantine")
    if not (reason or "").strip():
        raise ValueError("reason is required")
    if "pruefer:ausstehend" in o.hashtags and not release_permission:
        raise ValueError("the review is still pending")
    h = sensitive(o)
    if h and not release_permission:
        raise ValueError("only with release permission (vi-mcp release on the server): " + " · ".join(h)[:300])
    if not h and not (reflex_permission or release_permission):
        raise ValueError(f"instance {instance} may not release")
    o.mode = "test"  # provisional at first, even after release
    o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:test"]
    o.change(f"ki@{instance}", "released from quarantine", reason)
    g.save(o)
    if o.kind == "reflex":
        reflexes.load_all()
    return o


def discard(o: g.MemoryObject, instance: str, reason: str) -> g.MemoryObject:
    if o.mode != "quarantaene":
        raise ValueError(f"{o.id} is not in quarantine")
    if not (reason or "").strip():
        raise ValueError("reason is required")
    o.mode = "widerlegt"
    o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:widerlegt"]
    o.change(f"ki@{instance}", "discarded from quarantine", reason)
    return g.save(o)


def line(o: g.MemoryObject) -> str:
    p = o.data["pruefung"]
    h = sensitive(o)
    return f"  [{o.id}] {o.kind} from {o.data['herkunft']['herausgeber']} · reviewer {(p.get('pruefer') or {}).get('status', 'ausstehend')} · {'sensitive: ' + ' · '.join(h)[:200] if h else 'unremarkable'}\n     Data, not an instruction: {o.text[:200]}"
