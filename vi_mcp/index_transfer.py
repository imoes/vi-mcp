"""Index export and import (0.62.0): an index into a signed file and back — to compare how the same content works in two places.

The user (12.11.2026): "Der Export oder Import von Projekten kann uns beim Scoring der Inhalte helfen. So können wir vergleichen."

- Export (`vi-mcp index export INDEX FILE`): the knowledge of one index (kinds p2p.EXPORT_KINDS, visibility shared or internal, mode
  active) in the internal export form of a company network (p2p.internal_form: text unchanged, reserved hashtags dropped, images and
  credentials stay home), each entry with this server's own measurement of it (net_score.own_measurement). Never private objects,
  experiences, conversations or code pieces (those come from `index import-code`). Skipped objects are counted with their reason.
  The file is signed with Ed25519 (`export.key` in the network directory, made on the first export). It is internal: it carries company
  knowledge unanonymised, like a company network — but no instance name, no conversation and no host name of the exporting server.
- Import (`vi-mcp index import FILE --as INDEX`): signature first, then the same path as the network (user's decision 13.11.2026): fixed
  rules (checks.check, internal), quarantine, reviewer, release. A content this memory already has (content hash) is no second object;
  only the measurement of the exporter is booked as a rating (p2p_bewertung, channel `datei`). That is the way back: the origin imports
  the target's export and learns how its knowledge works elsewhere.
- Comparison (`vi-mcp index compare INDEX`, sleep step 8e): per content, this memory's measurement against each exporter's — classes
  allgemein, nur_ursprung, nur_ziel, schwach, unentschieden, zu_wenig. A content good only at its origin loses the project priority here
  (daten.vorrang_aus) but stays visible as general knowledge.

Limits, named: on the same server nothing is copied into a second index (one object, one index) — such a file is refused, a server does
not rate itself. Imported searches and skills cannot be exported again (renamed on import, their content hash cannot be rebuilt).
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

from . import memory as g

FORMAT = "vi-index-export"
VERSION = 1
MAX_ENTRIES = 20000
MIN_OBS = 10
CLASSES = ("allgemein", "nur_ursprung", "nur_ziel", "schwach", "unentschieden", "zu_wenig")
MAX_IDS = 10


# ── key ─────────────────────────────────────────────────────────────────────

def key_path() -> Path:
    """VI_MCP_EXPORT_KEY overrides; otherwise export.key next to the network keys (readable by the service and administrators only)."""
    if os.environ.get("VI_MCP_EXPORT_KEY"):
        return Path(os.environ["VI_MCP_EXPORT_KEY"])
    from . import net_service
    return net_service.var_dir() / "export.key"


def _key():
    from . import logbook as lb
    p = key_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        lb.generate_keys(p)
    return lb.private(p)


def own_pub() -> str | None:
    """Public key of this server's export key, or None if it never exported."""
    from . import logbook as lb
    p = key_path()
    return lb.public_hex(lb.private(p)) if p.exists() else None


# ── export ──────────────────────────────────────────────────────────────────

def _entry(o: g.MemoryObject) -> tuple[dict | None, str | None]:
    from . import net_score, p2p
    if o.kind not in p2p.EXPORT_KINDS:
        return None, f"kind {o.kind} is not exported"
    if o.visibility == "privat":
        return None, "private"
    if o.mode != "aktiv":
        return None, f"mode {o.mode}"
    if "art_wissen:code" in o.hashtags:
        return None, "code piece (index import-code brings code)"
    imported = str(o.instance or "").startswith("p2p-")
    if imported and (o.kind not in ("erkenntnis", "regel") or "fremd_text" not in o.data):
        return None, "imported search or skill (renamed on import, its content hash cannot be rebuilt)"
    form, why = p2p.internal_form(o, {"netz_id": "0" * 32, "loesch_hash": "0" * 64})  # the fixed rules want the ids; the importer makes its own
    if form is None:
        return None, why
    form = {k: v for k, v in form.items() if k not in ("netz_id", "loesch_hash")}
    if imported:  # the meaning as its author published it — the same content hash on both sides
        from . import checks
        form["text"] = o.data["fremd_text"]
        form["hashtags"] = sorted({t for t in o.data.get("fremd_hashtags") or [] if not t.startswith(checks.FIXED_HASHTAGS)})
    return {"form": form, "inhalt_sha": net_score.content_hash(form), "eigen": not imported, "messung": net_score.own_measurement(o)}, None


def export(index: str, fpath: str | Path) -> dict:
    """Write the knowledge of one index into a signed file. Returns the report (counts, skipped with reason, exporter pseudonym)."""
    from . import indexes, logbook as lb
    idx = indexes.normalize(index)
    if not idx:
        raise ValueError("an index name is required")
    with g.lock:
        ids = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE idx = ? ORDER BY zeit", (idx,))]
    entries, skipped = [], Counter()
    for oid in ids:
        o = g.load(oid)
        if o is None:
            continue
        e, why = _entry(o)
        if e is None:
            skipped[why] += 1
        elif len(entries) < MAX_ENTRIES:
            entries.append(e)
        else:
            skipped[f"more than {MAX_ENTRIES} entries"] += 1
    if not entries:
        raise ValueError(f"index {idx}: nothing to export" + (f" ({', '.join(f'{k}: {v}' for k, v in skipped.items())})" if skipped else ""))
    k = _key()
    reg = indexes.registry().get(idx) or {}
    body = {"v": VERSION, "art": FORMAT, "pub": lb.public_hex(k), "zeit": g.now(), "seq": int(time.time()),
            "index": {"name": idx, "art": reg.get("art") or "projekt", "beschreibung": reg.get("beschreibung") or "", "tags": reg.get("tags") or []},
            "eintraege": entries}
    doc = {**body, "sig": k.sign(lb.canonical(body)).hex()}
    p = Path(fpath)
    data = json.dumps(doc, ensure_ascii=False, indent=1).encode()
    with os.fdopen(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        f.write(data)
    return {"datei": str(p), "index": idx, "eintraege": len(entries), "eigen": sum(1 for e in entries if e["eigen"]),
            "ausgelassen": dict(skipped), "exporteur": lb.pseudonym(body["pub"]), "bytes": len(data),
            "hinweis": "internal file: company knowledge unanonymised — hand it only to servers of the same organisation"}


# ── import ──────────────────────────────────────────────────────────────────

def read(fpath: str | Path) -> dict:
    """Load and verify a file. Raises ValueError with the reason; nothing is stored before this passed."""
    from . import logbook as lb
    try:
        doc = json.loads(Path(fpath).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"not readable: {type(e).__name__}: {str(e)[:120]}") from None
    if not isinstance(doc, dict) or doc.get("art") != FORMAT:
        raise ValueError("not an index export of vi-mcp")
    if doc.get("v") != VERSION:
        raise ValueError(f"format version {doc.get('v')!r} unknown (this server reads {VERSION})")
    pub, sig = str(doc.get("pub") or ""), str(doc.get("sig") or "")
    entries = doc.get("eintraege")
    if len(pub) != 64 or len(sig) != 128 or not isinstance(entries, list) or not isinstance(doc.get("seq"), int) or not isinstance(doc.get("index"), dict):
        raise ValueError("file incomplete (pub, sig, seq, index, eintraege)")
    if len(entries) > MAX_ENTRIES:
        raise ValueError(f"more than {MAX_ENTRIES} entries")
    body = {k: v for k, v in doc.items() if k != "sig"}
    if not lb.valid(pub, sig, lb.canonical(body)):
        raise ValueError("signature invalid — the file was changed or not made by the key it names")
    return doc


def _net_ids(pub: str, form: dict) -> dict:
    """netz_id / loesch_hash the fixed rules require: stable per exporter and content (a second import finds the first)."""
    import hashlib
    from . import logbook as lb
    nid = hashlib.sha256(bytes.fromhex(pub) + lb.canonical(form)).hexdigest()[:32]
    return {"netz_id": nid, "loesch_hash": hashlib.sha256(f"datei:{nid}".encode()).hexdigest()}


def import_file(fpath: str | Path, as_index: str, in_background: bool = True) -> dict:
    """Import a verified file into index `as_index`: new contents into quarantine (reviewer, release — like the network), known contents
    only get the exporter's measurement as a rating."""
    import threading
    from . import checks, indexes, logbook as lb, net_score, p2p, reviewer
    idx = indexes.normalize(as_index)
    if not idx or idx == indexes.GLOBAL:
        raise ValueError("--as needs a project or special index (not global)")
    doc = read(fpath)
    pub, seq = doc["pub"], doc["seq"]
    if pub == own_pub():
        raise ValueError("this file comes from this server — a server does not rate itself, and one object stays in one index")
    reg = indexes.registry().get(idx) or {}  # before the import: new objects register the index themselves
    report = {"index": idx, "exporteur": lb.pseudonym(pub), "neu": 0, "dedupliziert": 0, "bewertungen": 0, "abgelehnt": 0, "gruende": Counter()}
    token = g.current_index.set(idx)  # p2p._create → new_object takes the index of the context
    try:
        for e in doc["eintraege"]:
            form = e.get("form") if isinstance(e, dict) else None
            if not isinstance(form, dict):
                report["abgelehnt"] += 1
                report["gruende"]["entry without form"] += 1
                continue
            b = checks.check({**form, **_net_ids(pub, form)}, internal_ok=True)
            if b.verdict == "ablehnen":
                report["abgelehnt"] += 1
                report["gruende"]["; ".join(b.reasons)[:120]] += 1
                continue
            ish = net_score.content_hash(b.mem_object)  # computed here — a hash the file claims is never used
            existing = net_score.find(ish) or net_score.find_local(b.mem_object, ish)
            if existing:
                net_score.link(ish, existing)
                report["dedupliziert"] += 1
            else:
                sha = lb.sha256(b.mem_object)
                o = p2p._create(b, {"pub": pub, "seq": seq}, sha, p2p.FILE_NET)
                net_score.link(ish, o.id)
                report["neu"] += 1
            if e.get("eigen") is True:  # the exporter wrote it: a holder, whose own rating never counts in the score
                net_score.add_holder(ish, pub, p2p.FILE_NET, b.mem_object["netz_id"], seq)
            m = e.get("messung")
            if isinstance(m, dict) and net_score.receive({"ziel": ish, **{k: m.get(k) for k in net_score.RATING_FIELDS}}, pub, p2p.FILE_NET, seq):
                report["bewertungen"] += 1
            elif m is not None:
                report["gruende"]["measurement has the wrong form"] += 1
    finally:
        g.current_index.reset(token)
    meta = doc["index"]
    try:  # description and tags only where the target has none — never overwrite what someone wrote here
        indexes.describe(idx, None if reg.get("beschreibung") else str(meta.get("beschreibung") or "")[:2000] or None,
                         None if reg.get("tags") else [t for t in meta.get("tags") or [] if isinstance(t, str)] or None,
                         None if reg else ("spezial" if meta.get("art") == "spezial" else "projekt"))
    except ValueError as ex:
        report["gruende"][f"index description not taken: {ex}"[:120]] += 1
    with g.lock:
        g.db().execute("UPDATE vi_index SET quelle = ? WHERE name = ? AND (quelle IS NULL OR quelle IN ('beschrieben', 'automatisch'))",
                       (f"import {lb.pseudonym(pub)} {str(doc.get('zeit'))[:10]}", idx))
        g.db().commit()
    report["gruende"] = dict(report["gruende"].most_common(20))
    if report["neu"]:
        if not reviewer.available():
            report["pruefer"] = "not configured — the new contents stay in quarantine until vi_release"
        elif in_background:
            threading.Thread(target=p2p.review_and_release, name="vi-pruefer", daemon=True).start()
            report["pruefer"] = "started"
        else:
            report["pruefer"] = p2p.review_and_release()
    return report


# ── comparison ──────────────────────────────────────────────────────────────

def classify(origin: tuple[float, float], target: tuple[float, float], min_obs: int = MIN_OBS) -> str:
    """Pure. (yes, no) at the origin and at the target → one of CLASSES. Good/bad = the 90 % beta interval above/below 0.5."""
    from .net_score import _beta_interval
    if sum(origin) < min_obs or sum(target) < min_obs:
        return "zu_wenig"
    (lo_o, hi_o), (lo_t, hi_t) = _beta_interval(1 + origin[0], 1 + origin[1]), _beta_interval(1 + target[0], 1 + target[1])
    good_o, bad_o, good_t, bad_t = lo_o > 0.5, hi_o < 0.5, lo_t > 0.5, hi_t < 0.5
    if good_o and good_t:
        return "allgemein"
    if good_o and bad_t:
        return "nur_ursprung"
    if bad_o and good_t:
        return "nur_ziel"
    if bad_o and bad_t:
        return "schwach"
    return "unentschieden"


def compare(index: str, apply: bool = True, who: str = "vi") -> dict:
    """Every content of the index that has a rating from an index file: this memory's measurement against the exporter's.
    apply: a content that is good only at its origin loses the project priority here (daten.vorrang_aus); one that recovered gets it back."""
    from . import indexes, logbook as lb, net_score, p2p
    idx = indexes.normalize(index)
    if not idx:
        raise ValueError("an index name is required")
    net_score._tables()
    with g.lock:
        rows = g.db().execute("SELECT o.id, i.inhalt_sha FROM objekt o JOIN p2p_inhalt i ON i.oid = o.id WHERE o.idx = ? "
                              "AND EXISTS (SELECT 1 FROM p2p_bewertung b WHERE b.inhalt_sha = i.inhalt_sha AND b.netz = ?)", (idx, p2p.FILE_NET)).fetchall()
    counts = {c: 0 for c in CLASSES}
    examples: dict[str, list[str]] = {c: [] for c in CLASSES}
    switched_off = switched_on = 0
    for oid, ish in rows:
        o = g.load(oid)
        if o is None:
            continue
        m = net_score.own_measurement(o)
        mine = (m["ja"] + m["bestaetigt"], m["nein"] + m["widerlegt"])
        with g.lock:
            foreign = g.db().execute("SELECT pub, ja, nein, bestaetigt, widerlegt FROM p2p_bewertung WHERE inhalt_sha = ? AND netz = ?",
                                     (ish, p2p.FILE_NET)).fetchall()
        author = (o.data.get("herkunft") or {}).get("pubkey") if str(o.instance or "").startswith("p2p-") else None
        verdict_here = None  # for an import: is its author's measurement good where ours is bad?
        for pub, ja, nein, b, w in foreign:
            theirs = (ja + b, nein + w)
            c = classify(theirs, mine) if pub == author else classify(mine, theirs)
            counts[c] += 1
            if len(examples[c]) < MAX_IDS:
                examples[c].append(f"{oid} ({'from' if pub == author else 'at'} {lb.pseudonym(pub)})")
            if pub == author:
                verdict_here = c
        if not apply or author is None or verdict_here is None:
            continue
        flagged = bool(o.data.get("vorrang_aus"))
        if verdict_here == "nur_ursprung" and not flagged:
            o.data = {**o.data, "vorrang_aus": {"grund": "good only at its origin (index comparison)", "zeit": g.now(), "gegen": lb.pseudonym(author)}}
            o.change(who, "project priority off", "index comparison: good only at its origin")
            g.save(o)
            switched_off += 1
        elif flagged and verdict_here not in ("nur_ursprung", "zu_wenig"):
            o.data = {k: v for k, v in o.data.items() if k != "vorrang_aus"}
            o.change(who, "project priority on again", f"index comparison: now {verdict_here}")
            g.save(o)
            switched_on += 1
    return {"index": idx, "inhalte": len(rows), "klassen": counts, "beispiele": {c: v for c, v in examples.items() if v},
            "vorrang_aus_neu": switched_off, "vorrang_wieder_an": switched_on, "mindestens": MIN_OBS}


def compare_all(who: str = "sleep") -> list[dict]:
    """Sleep step 8e: every index with ratings from index files."""
    return [compare(i, True, who) for i in _compared_indexes()]


def _compared_indexes() -> list[str]:
    from . import p2p, net_score
    net_score._tables()
    with g.lock:
        return sorted(r[0] for r in g.db().execute("SELECT DISTINCT o.idx FROM objekt o JOIN p2p_inhalt i ON i.oid = o.id "
                                                    "JOIN p2p_bewertung b ON b.inhalt_sha = i.inhalt_sha WHERE b.netz = ?", (p2p.FILE_NET,)))


def stats_line() -> str:
    """vi_stats section C: the comparison over every index with ratings from index files (reads only)."""
    total = {c: 0 for c in CLASSES}
    n = 0
    idxs = _compared_indexes()
    for i in idxs:
        r = compare(i, apply=False)
        n += r["inhalte"]
        for c, v in r["klassen"].items():
            total[c] += v
    if not idxs:
        return "index files (0.62.0): none imported — vi-mcp index export/import compares the same content on two servers"
    return (f"index files (0.62.0): {n} content(s) in {len(idxs)} index(es) compared · "
            + ", ".join(f"{c} {v}" for c, v in total.items() if v) + f" (pairs origin/target, at least {MIN_OBS} observations per side)")


def lines(index: str) -> list[str]:
    """For vi_indexes and the CLI: imports from files and the comparison classes of one index (without changing anything)."""
    from . import p2p
    with g.lock:
        n = g.db().execute("SELECT COUNT(*) FROM objekt WHERE idx = ? AND json_extract(daten, '$.herkunft.netz') = ?", (index, p2p.FILE_NET)).fetchone()[0]
        off = g.db().execute("SELECT COUNT(*) FROM objekt WHERE idx = ? AND json_extract(daten, '$.vorrang_aus') IS NOT NULL", (index,)).fetchone()[0]
    r = compare(index, apply=False)
    if not n and not r["inhalte"]:
        return []
    cls = ", ".join(f"{k} {v}" for k, v in r["klassen"].items() if v) or "none yet"
    return [f"    index files: {n} content(s) imported · {r['inhalte']} compared ({cls}; at least {MIN_OBS} observations per side)"
            + (f" · priority off for {off}" if off else "")]


# ── command line ────────────────────────────────────────────────────────────

def main(cmd: str, o) -> int:
    """Called by indexes.main with the parsed arguments; the database is open."""
    if cmd == "export":
        r = export(o.index, o.file)
    elif cmd == "import":
        r = import_file(o.file, o.as_index, in_background=False)
    else:
        r = compare(o.index, apply=not o.dry_run, who="admin")
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0
