"""0.41.0: the network wiki — pages every member of a network may edit, without a master.

Every revision is a logbook entry of type `seite` (see wiki_merge for the view). Here the memory side:
  write       an own revision (instance with a network token): checked like an import, then into the table and the outbox — own
              revisions count at once on this server
  ingest      a foreign revision from vi_net_inbox: fixed rules (checks.check_page), then a quarantine object of kind seite with the
              diff to its parent as content — the same reviewer, release and auto-release as every import ("everything only after review")
  on_release  release → the revision counts (status frei), the quarantine object is merged into the page (mode aufgegangen);
              discard → status verworfen
  materialize the page as one object `seite:<netz>:<slug>` (kind seite): title, the view with named conflict blocks, heads, authors —
              found by vi_recall, offered as a hint like every reviewed import
States of a revision (exhaustive): ausstehend (waiting for review) · frei (counts) · verworfen (discarded at release) · vergessen (revoked
by its author; stays in the graph for ancestry).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import secrets
import time

from . import memory as g
from . import wiki_merge as wm
from .logbook import pseudonym, sha256

STATES = ("ausstehend", "frei", "verworfen", "vergessen")
MAX_OWN_IN_OUTBOX = 500


def _tables() -> None:
    with g.lock:
        g.db().executescript("""
            CREATE TABLE IF NOT EXISTS seite_rev (netz TEXT NOT NULL, rev TEXT NOT NULL, seite TEXT NOT NULL, eltern TEXT NOT NULL, pub TEXT, instanz TEXT,
                                                 seq INTEGER, status TEXT NOT NULL, daten TEXT, netz_id TEXT NOT NULL, loesch_hash TEXT NOT NULL,
                                                 empfangen TEXT NOT NULL, geprueft TEXT, entschieden TEXT, eigen INTEGER NOT NULL DEFAULT 0, oid TEXT,
                                                 PRIMARY KEY (netz, rev));
            CREATE INDEX IF NOT EXISTS seite_rev_seite ON seite_rev (netz, seite);
            CREATE INDEX IF NOT EXISTS seite_rev_netz_id ON seite_rev (netz_id);
            CREATE TABLE IF NOT EXISTS seite_eigen (rev TEXT PRIMARY KEY, netz TEXT NOT NULL, instanz TEXT NOT NULL, schluessel TEXT NOT NULL);
        """)
        g.db().commit()


def page_id(net: str, slug: str) -> str:
    return f"seite:{net}:{slug}"


def _revs(net: str, slug: str) -> tuple[dict[str, wm.Rev], set[str], list[dict]]:
    _tables()
    with g.lock:
        lines = g.db().execute("SELECT rev, eltern, pub, instanz, status, daten, empfangen, entschieden, eigen FROM seite_rev WHERE netz = ? AND seite = ? ORDER BY empfangen",
                               (net, slug)).fetchall()
    revs, accepted, meta = {}, set(), []
    for rev, parents, pub, inst, status, data, recv, decided, own in lines:
        d = json.loads(data) if data else None
        author = (inst if own else pseudonym(pub)) if (own or pub) else "?"
        revs[rev] = wm.Rev(rev, json.loads(parents), None if (d is None or status == "vergessen") else d["text"], title=(d or {}).get("titel", ""),
                           deleted=bool((d or {}).get("geloescht")), author=author, hashtags=list((d or {}).get("hashtags") or []))
        if status == "frei":
            accepted.add(rev)
        meta.append({"rev": rev, "eltern": json.loads(parents), "autor": author, "status": status, "empfangen": recv, "entschieden": decided,
                     "eigen": bool(own), "notiz": (d or {}).get("notiz", ""), "zeit": (d or {}).get("zeit", "")})
    return revs, accepted, meta


def view(net: str, slug: str) -> tuple[wm.View, list[dict]]:
    revs, accepted, meta = _revs(net, slug)
    return wm.view(revs, accepted), meta


def _known_names() -> frozenset:
    from . import p2p
    return p2p._known()


def write(instance: str, net: str, slug: str, text: str, base_rev: str | None, title: str | None = None, note: str = "",
          hashtags: list[str] | None = None, source: str = "", also_parents: list[str] | None = None, delete: bool = False) -> dict:
    """An own revision. Returns {rev, eltern, zweig: bool, view state}. ValueError with the reason otherwise."""
    from . import anonymize, checks, p2p
    if net not in p2p.networks():
        raise ValueError(f"unknown network {net!r} — known: {', '.join(p2p.networks())}")
    token = p2p._token(instance)
    if not token:
        raise ValueError(f"instance {instance} has no network token (vi_net_token): without it a revision could never be revoked")
    _tables()
    revs, accepted, meta = _revs(net, slug)
    v = wm.view(revs, accepted)
    parents = [p.strip() for p in [base_rev, *(also_parents or [])] if p and p.strip()]
    if revs and not parents:
        raise ValueError(f"page {slug} exists: give base_rev (the revision you edited) — heads now: {', '.join(h[:16] for h in v.heads) or '—'}")
    full = []
    for p in parents:
        hits = [r for r in revs if r.startswith(p)] if len(p) < 64 else ([p] if p in revs else [])
        if len(hits) != 1:
            raise ValueError(f"revision {p} is not a revision of page {slug}" if not hits else f"revision prefix {p} is ambiguous")
        full.append(hits[0])
    title = (title or (v.title if v.heads else "") or slug.rsplit("/", 1)[-1].replace("-", " ")).strip()
    if len(title) < 3:
        title = f"Page {slug}"
    tags = sorted({t.strip() for t in hashtags or [] if isinstance(t, str) and g.TAG.match(t.strip()) and not t.strip().startswith(checks.FIXED_HASHTAGS)})[:20]
    key = f"seite|{net}|{slug}|{time.time_ns()}|{secrets.token_hex(4)}"
    net_id, obj_token = p2p._object_token(token, key, net)
    content = {"seite": slug, "titel": title[:200], "text": "" if delete else (text or ""), "eltern": sorted(set(full)), "hashtags": tags,
               "quelle": (source or "").strip()[:500], "notiz": (note or "").strip()[:300], "geloescht": bool(delete), "netz_id": net_id,
               "loesch_hash": hashlib.sha256(obj_token.encode()).hexdigest(), "zeit": g.now()[:10]}
    company = p2p.is_company(net)
    b = checks.check_page(content, internal_ok=company)
    if b.verdict == "ablehnen":
        where = " for the open network" if not company and any("internals" in r for r in b.reasons) else ""
        raise ValueError(f"page revision refused{where}: " + "; ".join(b.reasons)[:300] + (" — write it without, or use a company network" if where else ""))
    if not company:  # the open network: refuse instead of rewriting the author's words; name the class, not the value
        known = _known_names()
        for name in ("titel", "text", "notiz", "quelle"):
            if hits := anonymize.categories(content[name], known):
                raise ValueError(f"page revision refused for the open network: {name} contains {', '.join(hits)} — write it without, or use a company network")
    rev = sha256(content)
    with g.lock:
        g.db().execute("INSERT OR IGNORE INTO seite_rev (netz, rev, seite, eltern, pub, instanz, seq, status, daten, netz_id, loesch_hash, empfangen, entschieden, eigen) "
                       "VALUES (?,?,?,?,NULL,?,NULL,'frei',?,?,?,?,?,1)",
                       (net, rev, slug, json.dumps(content["eltern"]), instance, json.dumps(content, ensure_ascii=False), net_id, content["loesch_hash"], g.now(), g.now()))
        g.db().execute("INSERT OR IGNORE INTO seite_eigen (rev, netz, instanz, schluessel) VALUES (?,?,?,?)", (rev, net, instance, key))
        g.db().commit()
    new_view = materialize(net, slug)
    branch = bool(v.heads) and set(full) != set(v.heads)
    return {"rev": rev, "eltern": content["eltern"], "zweig": branch, "zustand": new_view.state, "koepfe": new_view.heads,
            "befunde": b.reasons}


def outgoing(net: str) -> list[dict]:
    """Own revisions for the network service; it writes only those it has not written yet (by checksum)."""
    _tables()
    with g.lock:
        lines = g.db().execute("SELECT daten FROM seite_rev WHERE netz = ? AND eigen = 1 AND status = 'frei' AND daten IS NOT NULL ORDER BY empfangen DESC LIMIT ?",
                               (net, MAX_OWN_IN_OUTBOX)).fetchall()
    return [json.loads(d) for (d,) in lines]


def _diff(revs: dict[str, wm.Rev], parents: list[str], text: str) -> str:
    base = next((revs[p].text for p in parents if p in revs and revs[p].text is not None), None)
    if base is None:
        return text
    return "\n".join(difflib.unified_diff(base.splitlines(), text.splitlines(), "parent", "this revision", lineterm="", n=2))[:40_000]


def ingest(raw: dict, header: dict, net: str) -> str:
    """A foreign revision. Returns 'neu', 'bekannt' or the reason of the rejection."""
    from . import checks, p2p
    b = checks.check_page(raw, internal_ok=p2p.is_company(net))
    if b.verdict == "ablehnen":
        return "; ".join(b.reasons)[:200]
    if raw["netz_id"] != header.get("netz_id") or raw["loesch_hash"] != header.get("loesch_hash"):
        return "header and content name different revisions"
    rev = sha256(raw)
    if rev != header["sha"]:
        return "checksum does not match"
    _tables()
    with g.lock:
        if g.db().execute("SELECT 1 FROM seite_rev WHERE netz = ? AND rev = ?", (net, rev)).fetchone():
            return "bekannt"
        tomb = g.db().execute("SELECT token_sha FROM p2p_grab WHERE netz_id = ?", (raw["netz_id"],)).fetchone()
    if tomb and tomb[0] == raw["loesch_hash"]:
        return "bekannt"  # revoked before it arrived: stays away
    slug, name = raw["seite"], pseudonym(header["pub"])
    revs, _acc, _meta = _revs(net, slug)
    oid = f"seite:rev-{rev[:32]}"
    data = {"quelle": raw["quelle"] or f"wiki page {slug} in network {net}", "inhalt": _diff(revs, raw["eltern"], raw["text"]),
            "herkunft": {"herausgeber": name, "pubkey": header["pub"], "seq": header["seq"], "sha256": rev, "netz_id": raw["netz_id"], "netz": net},
            "pruefung": {"regeln": b.reasons, "pruefer": None}, "fremd_text": f"{raw['titel']} — {raw['notiz'] or 'edit of the page'}"[:1000],
            "fremd_hashtags": raw["hashtags"], "wiki": {"netz": net, "seite": slug, "rev": rev, "geloescht": raw["geloescht"]}}
    tags = sorted(set(raw["hashtags"] + ["herkunft:p2p", f"herausgeber:{name}", "pruefer:ausstehend", "modus:quarantaene", f"netz:{net}", "herkunft:wiki"]))
    g.new_object("seite", data["fremd_text"], tags, data, who=f"import@{name}", reason=f"wiki revision from {name}", oid=oid, mode="quarantaene",
                 instance=f"p2p-{name}", visibility="intern" if p2p.is_company(net) else None)
    with g.lock:
        g.db().execute("INSERT INTO seite_rev (netz, rev, seite, eltern, pub, instanz, seq, status, daten, netz_id, loesch_hash, empfangen, eigen, oid) "
                       "VALUES (?,?,?,?,?,NULL,?,'ausstehend',?,?,?,?,0,?)",
                       (net, rev, slug, json.dumps(raw["eltern"]), header["pub"], header["seq"], json.dumps(raw, ensure_ascii=False), raw["netz_id"], raw["loesch_hash"], g.now(), oid))
        g.db().commit()
    materialize(net, slug)  # the page names pending revisions
    return "neu"


def on_release(o: g.MemoryObject, accepted: bool) -> None:
    """Called by p2p.approve / p2p.discard for a revision object."""
    w = o.data.get("wiki") or {}
    if not w:
        return
    _tables()
    with g.lock:
        g.db().execute("UPDATE seite_rev SET status = ?, entschieden = ?, geprueft = COALESCE(geprueft, ?) WHERE netz = ? AND rev = ?",
                       ("frei" if accepted else "verworfen", g.now(), g.now(), w["netz"], w["rev"]))
        g.db().commit()
    if accepted:  # the revision lives on in the page; the quarantine object is merged into it
        o.mode = "aufgegangen"
        o.hashtags = [t for t in o.hashtags if not t.startswith("modus:")] + ["modus:aufgegangen"]
        o.data["merged_into"] = page_id(w["netz"], w["seite"])
        g.save(o)
    materialize(w["netz"], w["seite"])


def reviewed(o: g.MemoryObject) -> None:
    """The reviewer has judged a revision object (for the time from arrival to review)."""
    w = o.data.get("wiki") or {}
    if w:
        with g.lock:
            g.db().execute("UPDATE seite_rev SET geprueft = COALESCE(geprueft, ?) WHERE netz = ? AND rev = ?", (g.now(), w["netz"], w["rev"]))
            g.db().commit()


def forget(net_id: str, evidence: str) -> bool:
    """A revocation of a revision: its text goes, its place in the graph stays (status vergessen)."""
    import hmac
    _tables()
    with g.lock:
        z = g.db().execute("SELECT netz, rev, seite, loesch_hash, oid FROM seite_rev WHERE netz_id = ?", (net_id,)).fetchone()
    if not z or not hmac.compare_digest(z[3], evidence):
        return False
    net, rev, slug, _lh, oid = z
    with g.lock:
        g.db().execute("UPDATE seite_rev SET status = 'vergessen', daten = NULL, entschieden = ? WHERE netz = ? AND rev = ?", (g.now(), net, rev))
        g.db().commit()
    if oid and g.load(oid):
        g.delete([oid])
    materialize(net, slug)
    return True


def render(v: wm.View, meta: list[dict]) -> str:
    pending = [m for m in meta if m["status"] == "ausstehend"]
    head = [f"state {v.state} · heads {', '.join(h[:16] for h in v.heads) or '—'}"
            + (f" · {len(v.conflicts)} conflict(s) between " + "; ".join(f"{c.a_rev[:12]} ({c.a_author}) and {c.b_rev[:12]} ({c.b_author})" for c in v.conflicts)
               + ": resolve with vi_page_write base_rev=<one head> also_parents=<the others>" if v.conflicts else "")
            + (f" · deleted by {', '.join(h[:16] for h in v.deleted_by)}" if v.deleted_by else "")
            + (f" · {len(pending)} change(s) waiting for review" if pending else "")]
    return "\n".join(head) + "\n\n" + v.text


def materialize(net: str, slug: str) -> wm.View:
    """Keep the page object current: one object per page, the view as its content."""
    from . import p2p
    revs, accepted, meta = _revs(net, slug)
    v = wm.view(revs, accepted)
    oid = page_id(net, slug)
    o = g.load(oid)
    if not v.heads or v.deleted:
        if o:
            g.delete([oid])
        return v
    first = wm.paragraphs(v.text)[:1]
    text = (v.title + (" — " + first[0][:300].replace("\n", " ") if first else ""))[:1000]
    authors = sorted({m["autor"] for m in meta if m["status"] == "frei"})
    foreign = any(not m["eigen"] for m in meta if m["rev"] in v.heads)
    tags = sorted({t for h in v.heads for t in revs[h].hashtags} | {"herkunft:wiki", f"netz:{net}"} | ({"herkunft:p2p"} if foreign else set()))
    data = {"quelle": f"network wiki {net}, page {slug}", "inhalt": render(v, meta),
            "wiki": {"netz": net, "seite": slug, "koepfe": v.heads, "zustand": v.state, "konflikte": len(v.conflicts), "autoren": authors,
                     "ausstehend": sum(1 for m in meta if m["status"] == "ausstehend"), "revisionen": len(meta)}}
    mode = "test" if foreign else "aktiv"
    if o:
        o.text, o.hashtags, o.mode = text, tags, mode
        o.data.update(data)
        g.save(o)
    else:
        g.new_object("seite", text, tags, data, who="vi", reason=f"wiki page {slug}", oid=oid, mode=mode,
                     instance=None, visibility="intern" if p2p.is_company(net) else None)
    return v


def revoke(instance: str, net: str, rev: str, reason: str) -> dict:
    """Right to be forgotten for an own revision: the network deletes its text; the graph keeps its place."""
    from . import p2p
    if not (reason or "").strip():
        raise ValueError("reason is required")
    _tables()
    with g.lock:
        z = g.db().execute("SELECT e.rev, e.instanz, e.schluessel, r.seite FROM seite_eigen e JOIN seite_rev r ON r.rev = e.rev AND r.netz = e.netz "
                           "WHERE e.netz = ? AND e.rev LIKE ?", (net, rev + "%")).fetchall()
    if len(z) != 1:
        raise ValueError(f"no own revision {rev} in network {net}" if not z else f"revision prefix {rev} is ambiguous")
    full, inst, key, slug = z[0]
    if inst != instance:
        raise ValueError(f"revision {full[:16]} was written by instance {inst}; only the author revokes")
    net_id, token = p2p._object_token(p2p._token(instance), key, net)
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS seite_widerruf (rev TEXT PRIMARY KEY, netz TEXT NOT NULL, netz_id TEXT NOT NULL, token TEXT NOT NULL, zeit TEXT NOT NULL, grund TEXT NOT NULL)")
        g.db().execute("INSERT OR IGNORE INTO seite_widerruf (rev, netz, netz_id, token, zeit, grund) VALUES (?,?,?,?,?,?)", (full, net, net_id, token, g.now(), reason[:300]))
        g.db().execute("UPDATE seite_rev SET status = 'vergessen', daten = NULL, entschieden = ? WHERE netz = ? AND rev = ?", (g.now(), net, full))
        g.db().commit()
    materialize(net, slug)
    return {"rev": full, "seite": slug}


def revocations(net: str) -> list[dict]:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS seite_widerruf (rev TEXT PRIMARY KEY, netz TEXT NOT NULL, netz_id TEXT NOT NULL, token TEXT NOT NULL, zeit TEXT NOT NULL, grund TEXT NOT NULL)")
        return [{"netz_id": a, "token": b} for a, b in g.db().execute("SELECT netz_id, token FROM seite_widerruf WHERE netz = ? ORDER BY zeit", (net,))]


def history(net: str, slug: str) -> list[dict]:
    return view(net, slug)[1]


def pages(net: str | None = None) -> list[tuple[str, str]]:
    _tables()
    with g.lock:
        if net:
            return g.db().execute("SELECT DISTINCT netz, seite FROM seite_rev WHERE netz = ? ORDER BY seite", (net,)).fetchall()
        return g.db().execute("SELECT DISTINCT netz, seite FROM seite_rev ORDER BY netz, seite").fetchall()


def stats(days: float = 7) -> dict:
    """For vi_stats section W: stock, review, merging."""
    from datetime import datetime, timedelta, timezone
    _tables()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    with g.lock:
        by_state = dict(g.db().execute("SELECT status, COUNT(*) FROM seite_rev GROUP BY status").fetchall())
        own = g.db().execute("SELECT COUNT(*) FROM seite_rev WHERE eigen = 1").fetchone()[0]
        foreign_released = g.db().execute("SELECT COUNT(*) FROM seite_rev WHERE eigen = 0 AND status = 'frei'").fetchone()[0]
        total = g.db().execute("SELECT COUNT(*) FROM seite_rev").fetchone()[0]
        publishers = g.db().execute("SELECT COUNT(DISTINCT COALESCE(pub, instanz)) FROM seite_rev").fetchone()[0]
        new_pages = g.db().execute("SELECT COUNT(*) FROM (SELECT netz, seite, MIN(empfangen) m FROM seite_rev GROUP BY netz, seite) WHERE m >= ?", (since,)).fetchone()[0]
        changed = g.db().execute("SELECT COUNT(DISTINCT netz || '|' || seite) FROM seite_rev WHERE empfangen >= ?", (since,)).fetchone()[0]
        waits = g.db().execute("SELECT empfangen, entschieden FROM seite_rev WHERE eigen = 0 AND status = 'frei' AND entschieden >= ?", (since,)).fetchall()
        auto = g.db().execute("SELECT COUNT(*) FROM objekt WHERE art = 'seite' AND id LIKE 'seite:rev-%' AND aenderungen LIKE '%automatic%'").fetchone()[0]
    hours = sorted((datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() / 3600 for a, b in waits)

    def q(p):
        return round(hours[min(len(hours) - 1, int(p * len(hours)))], 1) if hours else None
    active = deleted = multi = conflict = 0
    oldest = []
    for net, slug in pages():
        v, meta = view(net, slug)
        if v.deleted:
            deleted += 1
            continue
        if v.heads:
            active += 1
        if len(v.heads) > 1:
            multi += 1
        if v.conflicts:
            conflict += 1
            since_c = max((m["entschieden"] or m["empfangen"]) for m in meta if m["rev"] in v.heads)
            oldest.append((since_c, f"{net}/{slug}"))
    return {"seiten": active, "geloescht": deleted, "revisionen": total, "eigene": own, "fremde": total - own, "herausgeber": publishers,
            "neue_seiten": new_pages, "geaenderte_seiten": changed, "je_status": {s: by_state.get(s, 0) for s in STATES},
            "automatisch_freigegeben": auto, "fremd_freigegeben": foreign_released, "freigabe_h_median": q(0.5), "freigabe_h_p90": q(0.9), "mehrere_koepfe": multi,
            "still_zusammengefuehrt": multi - conflict, "offene_konflikte": conflict, "aelteste_konflikte": sorted(oldest)[:3]}
