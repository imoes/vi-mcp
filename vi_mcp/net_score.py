"""0.40.0: the same information on several servers, verifiable by hash — deduplicated, and a network score per content.

Content hash: SHA-256 over the meaning of an object — kind, text, content, hashtags (and for searches and skills their filter, steps) — with
whitespace normalised; without netz_id, loesch_hash, date and source, which differ per publisher. The receiver computes it itself; a hash a
sender claims is never used. Before 0.40.0 the network deduplicated only identical entries, i.e. never across publishers.

Holders: every publisher whose objekt entry carries a content is a holder of it. A second holder adds no second object, only a line in
`p2p_halter`; if the content equals a local object of this memory, the foreign server is a holder of that one. A revocation removes only its
holder line; an imported object goes when its last holder revoked. Local objects always stay.

Ratings: every server publishes, per content it holds as an import, its own measurements — hints shown, helpful, not helpful (bandit),
confirmations and refutations by its own instances. Never counters it received: an import starts at zero. Logbook type `bewertung`
{ziel, gezeigt, ja, nein, bestaetigt, widerlegt}; the network service writes at most one per content and day and only changed values.

Network score per content: beta mean (1 + Σ w·yes) / (2 + Σ w·(yes + no)) over distinct raters, with yes = ja + bestaetigt, no = nein +
widerlegt; the latest rating of each rater counts, at most CAP observations per rater (so no server dominates), weight w = measured
benefit of that rater as a publisher (0.5 while unknown). A holder's rating of its own content does not count (no instance rates itself).
This memory's own measurement counts as one more rater. 90 % interval from the beta distribution.
Effect: shown with imported objects (vi_object, vi_recall); with ≥ HIDE_MIN_OBS observations and a score below HIDE_BELOW a content is no
longer offered as a hint before actions. 0.62.0: ratings from index files (channel `datei`, index_transfer) count in the score, but never
hide this memory's own object — they compare two places, and knowledge that fits only here must not vanish here. The router keeps learning from this server's own experiences only.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import memory as g

CAP = 20
HIDE_MIN_OBS = 20
HIDE_BELOW = 0.3
UNKNOWN_WEIGHT = 0.5
from .logbook import RATING_FIELDS, valid_rating  # noqa: E402,F401 — one definition, used by the network service as well
_WS = re.compile(r"\s+")


def _tables() -> None:
    with g.lock:
        new = not g.db().execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'p2p_inhalt'").fetchone()
        g.db().executescript("""
            CREATE TABLE IF NOT EXISTS p2p_inhalt (inhalt_sha TEXT PRIMARY KEY, oid TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS p2p_inhalt_oid ON p2p_inhalt (oid);
            CREATE TABLE IF NOT EXISTS p2p_halter (inhalt_sha TEXT NOT NULL, pub TEXT NOT NULL, netz TEXT NOT NULL, netz_id TEXT NOT NULL, seq INTEGER NOT NULL,
                                                  zeit TEXT NOT NULL, PRIMARY KEY (inhalt_sha, pub));
            CREATE INDEX IF NOT EXISTS p2p_halter_netz_id ON p2p_halter (netz_id);
            CREATE TABLE IF NOT EXISTS p2p_bewertung (inhalt_sha TEXT NOT NULL, pub TEXT NOT NULL, netz TEXT NOT NULL, seq INTEGER NOT NULL, gezeigt REAL NOT NULL,
                                                     ja REAL NOT NULL, nein REAL NOT NULL, bestaetigt REAL NOT NULL, widerlegt REAL NOT NULL, zeit TEXT NOT NULL,
                                                     PRIMARY KEY (inhalt_sha, pub));
        """)
        g.db().commit()
    if new:
        _backfill()


def _backfill() -> None:
    """Imports from before 0.40.0: content hash and holder from what the import kept (foreign text, hashtags, content, origin).
    Searches and skills were renamed on import, their hash cannot be rebuilt — they are counted, not guessed."""
    from .log_output import log
    with g.lock:
        ids = [r[0] for r in g.db().execute("SELECT id FROM objekt WHERE json_extract(daten, '$.herkunft.pubkey') IS NOT NULL")]
    done = skipped = 0
    for oid in ids:
        o = g.load(oid)
        h = (o.data.get("herkunft") or {}) if o else {}
        if not o or o.kind not in ("erkenntnis", "regel") or "fremd_text" not in o.data:
            skipped += 1
            continue
        ish = content_hash({"art": o.kind, "text": o.data["fremd_text"], "inhalt": o.data.get("inhalt"), "hashtags": o.data.get("fremd_hashtags") or []})
        with g.lock:
            g.db().execute("INSERT OR IGNORE INTO p2p_inhalt (inhalt_sha, oid) VALUES (?,?)", (ish, oid))
            g.db().execute("INSERT OR IGNORE INTO p2p_halter (inhalt_sha, pub, netz, netz_id, seq, zeit) VALUES (?,?,?,?,?,?)",
                           (ish, h["pubkey"], h.get("netz") or "standard", h.get("netz_id") or "", int(h.get("seq") or 0), g.now()))
        done += 1
    with g.lock:
        g.db().commit()
    if ids:
        log(f"migration: content hash for {done} import(s) from before 0.40.0; {skipped} search/skill import(s) without (renamed on import)")


def _norm_text(s) -> str:
    return _WS.sub(" ", str(s or "")).strip()


def _norm_block(s) -> str:
    """Content keeps its lines (code); only line ends and trailing blanks are normalised."""
    return "\n".join(line.rstrip() for line in str(s or "").replace("\r\n", "\n").replace("\r", "\n").strip().split("\n"))


def content_hash(o: dict) -> str:
    """Pure. o in the wire form (art, text, inhalt, hashtags, …). Same meaning → same hash, whoever published it."""
    core = {"art": o.get("art"), "text": _norm_text(o.get("text")), "inhalt": _norm_block(o.get("inhalt")),
            "hashtags": sorted({str(t).strip() for t in o.get("hashtags") or []})}
    for k in ("filter", "name"):
        if o.get(k):
            core[k] = _norm_text(o[k])
    if o.get("schritte"):
        core["schritte"] = list(o["schritte"])
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def local_form(o: g.MemoryObject) -> dict:
    """A local object in the fields the content hash uses (hashtags without the reserved ones)."""
    from . import checks
    d = {"art": o.kind, "text": o.text, "inhalt": o.data.get("inhalt"), "hashtags": [t for t in o.hashtags if not t.startswith(checks.FIXED_HASHTAGS)]}
    if o.kind == "suche":
        d.update(filter=o.data.get("filter"), name=o.data.get("name"))
    return d


def find(ish: str) -> str | None:
    """Object id this memory holds for a content hash, or None."""
    _tables()
    with g.lock:
        z = g.db().execute("SELECT oid FROM p2p_inhalt WHERE inhalt_sha = ?", (ish,)).fetchone()
    if z and g.load(z[0]):
        return z[0]
    return None


def find_local(raw: dict, ish: str) -> str | None:
    """An own (not imported) object with the same meaning — by exact text (0.62.0: and exact content first), then the hash decides.
    0.62.0: the content narrows the candidates, and up to 500 with the same text are checked (was 20 by text alone: a generic heading such
    as "What is missing" shared by many objects hid the matching one — found on the way back of an index file, 40 of 180 contents were
    stored a second time)."""
    where = ("FROM objekt WHERE art = ? AND text = ? AND (instanz IS NULL OR instanz NOT LIKE 'p2p-%') "
             "AND modus NOT IN ('widerlegt', 'quarantaene')")
    par = (raw.get("art"), str(raw.get("text") or "").strip())
    with g.lock:
        ids = [r[0] for r in g.db().execute(f"SELECT id {where} AND json_extract(daten, '$.inhalt') IS ? LIMIT 20", (*par, raw.get("inhalt")))]
        ids += [r[0] for r in g.db().execute(f"SELECT id {where} LIMIT 500", par) if r[0] not in ids]
    for oid in ids:
        o = g.load(oid)
        if o and content_hash(local_form(o)) == ish:
            return oid
    return None


def link(ish: str, oid: str) -> None:
    _tables()
    with g.lock:
        g.db().execute("INSERT OR REPLACE INTO p2p_inhalt (inhalt_sha, oid) VALUES (?,?)", (ish, oid))
        g.db().commit()


def add_holder(ish: str, pub: str, net: str, net_id: str, seq: int) -> bool:
    """True if this publisher was not yet a holder of this content."""
    _tables()
    with g.lock:
        n = g.db().execute("INSERT OR IGNORE INTO p2p_halter (inhalt_sha, pub, netz, netz_id, seq, zeit) VALUES (?,?,?,?,?,?)",
                           (ish, pub, net, net_id, seq, g.now())).rowcount
        g.db().commit()
    return bool(n)


def is_holder(ish: str, pub: str) -> bool:
    _tables()
    with g.lock:
        return bool(g.db().execute("SELECT 1 FROM p2p_halter WHERE inhalt_sha = ? AND pub = ?", (ish, pub)).fetchone())


def drop_holder(net_id: str) -> tuple[str | None, int]:
    """Remove the holder line of this netz_id. Returns (content hash, holders left)."""
    _tables()
    with g.lock:
        z = g.db().execute("SELECT inhalt_sha FROM p2p_halter WHERE netz_id = ?", (net_id,)).fetchone()
        if not z:
            return None, 0
        g.db().execute("DELETE FROM p2p_halter WHERE netz_id = ?", (net_id,))
        left = g.db().execute("SELECT COUNT(*) FROM p2p_halter WHERE inhalt_sha = ?", (z[0],)).fetchone()[0]
        if not left:
            g.db().execute("DELETE FROM p2p_inhalt WHERE inhalt_sha = ?", (z[0],))
        g.db().commit()
    return z[0], left


def holders(ish: str) -> list[str]:
    _tables()
    with g.lock:
        return [r[0] for r in g.db().execute("SELECT pub FROM p2p_halter WHERE inhalt_sha = ? ORDER BY zeit", (ish,))]


def hash_of(oid: str) -> str | None:
    _tables()
    with g.lock:
        z = g.db().execute("SELECT inhalt_sha FROM p2p_inhalt WHERE oid = ?", (oid,)).fetchone()
    return z[0] if z else None


# ---- ratings ----

def own_measurement(o: g.MemoryObject) -> dict:
    """This server's own measurements of an object: the hint bandit (only fed by this server) and its own instances' verdicts."""
    from . import bandit
    yes, no = bandit.counter(o)
    return {"gezeigt": bandit.shown(o), "ja": yes, "nein": no, "bestaetigt": sum((o.data.get("bestaetigt_von") or {}).values()),
            "widerlegt": sum((o.data.get("widerlegt_von") or {}).values())}


def outgoing(net: str, limit: int = 2000) -> list[dict]:
    """Ratings this memory publishes in a network: imports from that network with any own measurement. The service writes only changes."""
    _tables()
    out = []
    with g.lock:
        lines = g.db().execute("SELECT i.inhalt_sha, i.oid FROM p2p_inhalt i JOIN objekt o ON o.id = i.oid "
                               "WHERE json_extract(o.daten, '$.herkunft.netz') IS ? OR (? = 'standard' AND json_extract(o.daten, '$.herkunft') IS NOT NULL "
                               "AND json_extract(o.daten, '$.herkunft.netz') IS NULL)", (net, net)).fetchall()
    for ish, oid in lines:
        o = g.load(oid)
        if not o or o.mode == "quarantaene":
            continue
        m = own_measurement(o)
        if any(m.values()):
            out.append({"ziel": ish, **m})
        if len(out) >= limit:
            break
    return out


def receive(c: dict, pub: str, net: str, seq: int) -> bool:
    """Store a rating; the latest per rater and content counts. False if the form is wrong."""
    if not valid_rating(c):
        return False
    _tables()
    with g.lock:
        old = g.db().execute("SELECT seq FROM p2p_bewertung WHERE inhalt_sha = ? AND pub = ?", (c["ziel"], pub)).fetchone()
        if old and old[0] >= seq:
            return True
        g.db().execute("INSERT OR REPLACE INTO p2p_bewertung (inhalt_sha, pub, netz, seq, gezeigt, ja, nein, bestaetigt, widerlegt, zeit) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (c["ziel"], pub, net, seq, *(float(c[k]) for k in RATING_FIELDS), g.now()))
        g.db().commit()
    return True


def _beta_interval(a: float, b: float) -> tuple[float, float]:
    try:
        from scipy.stats import beta
        return float(beta.ppf(0.05, a, b)), float(beta.ppf(0.95, a, b))
    except Exception:  # noqa: BLE001 — without scipy: normal approximation
        m, v = a / (a + b), a * b / ((a + b) ** 2 * (a + b + 1))
        return max(0.0, m - 1.645 * v ** 0.5), min(1.0, m + 1.645 * v ** 0.5)


def score(ish: str, local: g.MemoryObject | None = None) -> dict:
    """Network score of one content (see module doc). `local`: this memory's object, whose own measurement counts as one rater."""
    from . import p2p
    from .logbook import pseudonym
    _tables()
    with g.lock:
        ratings = g.db().execute("SELECT pub, ja, nein, bestaetigt, widerlegt, netz FROM p2p_bewertung WHERE inhalt_sha = ?", (ish,)).fetchall()
    held_by = set(holders(ish))
    value = p2p.publisher_value()
    rows, self_rated = [], 0
    for pub, ja, nein, b, w, net in ratings:
        if pub in held_by:
            self_rated += 1
            continue
        weight = value.get(pseudonym(pub), {}).get("mittel", UNKNOWN_WEIGHT)
        rows.append((weight, ja + b, nein + w, net == p2p.FILE_NET))
    imported = local is not None and str(local.instance or "").startswith("p2p-")
    if imported:  # an import: our measurement is foreign to its holders
        m = own_measurement(local)
        rows.append((1.0, m["ja"] + m["bestaetigt"], m["nein"] + m["widerlegt"], False))

    def total(rs):
        yes = no = obs = 0.0
        raters = 0
        for weight, y, n, _f in rs:
            if y + n <= 0:
                continue
            raters += 1
            f = min(1.0, CAP / (y + n))
            yes, no, obs = yes + weight * y * f, no + weight * n * f, obs + (y + n) * f
        return yes, no, obs, raters
    yes, no, obs, raters = total(rows)
    a, b = 1 + yes, 1 + no
    lo, hi = _beta_interval(a, b)
    s = a / (a + b)
    hide_obs, hide_s = obs, s
    if local is not None and not imported:  # 0.62.0: index files compare places — knowledge that fits only here must not vanish here
        hy, hn, hide_obs, _r = total([r for r in rows if not r[3]])
        hide_s = (1 + hy) / (2 + hy + hn)
    return {"score": round(s, 3), "von": round(lo, 3), "bis": round(hi, 3), "bewerter": raters, "beobachtungen": round(obs, 1), "halter": len(held_by),
            "selbstbewertungen_ignoriert": self_rated, "ausgeblendet": hide_obs >= HIDE_MIN_OBS and hide_s < HIDE_BELOW}


def line(o: g.MemoryObject) -> str | None:
    """One line for vi_object / vi_recall, or None if the object is not known on the network."""
    ish = hash_of(o.id)
    if not ish:
        return None
    s = score(ish, o)
    if not s["bewerter"]:
        return f"network: held by {s['halter']} server(s) · no ratings yet · content hash {ish[:16]}"
    return (f"network score {s['score']} (90 % {s['von']}–{s['bis']}, beta mean) from {s['bewerter']} rater(s), {s['beobachtungen']} observations "
            f"(at most {CAP} per rater) · held by {s['halter']} server(s)" + (" · hidden as a hint (below 0.3)" if s["ausgeblendet"] else "")
            + f" · content hash {ish[:16]}")


def hidden(o: g.MemoryObject) -> bool:
    ish = hash_of(o.id)
    return bool(ish) and score(ish, o)["ausgeblendet"]


def stats() -> dict:
    """For vi_stats section W."""
    _tables()
    with g.lock:
        contents = g.db().execute("SELECT COUNT(*) FROM p2p_inhalt").fetchone()[0]
        per = [r[0] for r in g.db().execute("SELECT COUNT(*) FROM p2p_halter GROUP BY inhalt_sha")]
        rated = [r[0] for r in g.db().execute("SELECT DISTINCT inhalt_sha FROM p2p_bewertung")]
        received = g.db().execute("SELECT COUNT(*) FROM p2p_bewertung").fetchone()[0]
    dist = {"1": 0, "2": 0, "3+": 0}
    for n in per:
        dist["1" if n == 1 else "2" if n == 2 else "3+"] += 1
    buckets = {"<0.3": 0, "0.3–0.7": 0, ">0.7": 0}
    hidden_n = 0
    for ish in rated[:5000]:
        oid = find(ish)
        s = score(ish, g.load(oid) if oid else None)
        if not s["bewerter"]:
            continue
        buckets["<0.3" if s["score"] < 0.3 else ">0.7" if s["score"] > 0.7 else "0.3–0.7"] += 1
        hidden_n += s["ausgeblendet"]
    return {"inhalte": contents, "halterzeilen": sum(per), "dedupliziert": sum(per) - len(per), "halter_verteilung": dist,
            "bewertet": sum(buckets.values()), "score_verteilung": buckets, "ausgeblendet": hidden_n, "bewertungen_empfangen": received}
