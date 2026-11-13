"""Weights per word — the meaning layer of the AI language, and how memories talk to each other with weights (0.62.0).

The user (13.11.2026): "Im Endeffekt muss die Sprache aus Gewichten bestehen, weil das die Art und Weise ist, wie KIs ihre Informationen
ablegen" and "die Kommunikation der Systeme geschieht mit Gewichten". Research the same day: raw model weights, adapters or vectors work
only between identical models and leak content (vec2text recovers 92 % of short texts) — so between organisations the symbol stays
readable and the meaning travels as measured weights.

- A word is a hashtag `kind:value`. Its weight for a question type (answers:<type>, or `any`) is the beta mean of helped / not helped over
  the knowledge that carries it — the hint bandit's counters, summed (sleep step 8g, table vil_gewicht).
- Memories exchange these weights as ordinary signed ratings: target = sha256("vil-word-v1|<word>|<type>"). No new logbook type (older
  peers would reject it and stop the publisher's chain), and the word itself never travels — a receiver can attribute a weight only to a
  word it knows. Into an open network go no host names and no word the anonymisation flags as internal (a hash of a host name could be
  guessed); a company network gets all.
- A receiver keeps the weights in vil_gewicht_netz and combines them with its own, each foreign rater weighted by its measured benefit as
  a publisher (as net_score does), at most CAP observations per rater. A weight from another server is a measurement, never a command.
- Use: in a VIL question (`ask.<type>`), hits of the same priority are ordered by the combined weight of their words for that type.
"""
from __future__ import annotations

import hashlib

from . import memory as g

KINDS = ("host:", "tool:", "thema:", "fehler:", "skill:", "art_wissen:", "answers:", "memory:")
OPEN_KINDS = ("tool:", "thema:", "fehler:", "skill:", "art_wissen:", "answers:", "memory:")
MIN_N = 5
CAP = 20
VERSION = "vil-word-v1"


def word_hash(word: str, qtype: str) -> str:
    return hashlib.sha256(f"{VERSION}|{word}|{qtype}".encode()).hexdigest()


def _tables() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS vil_gewicht (wort TEXT NOT NULL, frageart TEXT NOT NULL, ja REAL NOT NULL, nein REAL NOT NULL, "
                       "n REAL NOT NULL, hash TEXT NOT NULL, zeit TEXT NOT NULL, PRIMARY KEY (wort, frageart))")
        g.db().execute("CREATE INDEX IF NOT EXISTS vil_gewicht_hash ON vil_gewicht (hash)")
        g.db().execute("CREATE TABLE IF NOT EXISTS vil_gewicht_netz (hash TEXT NOT NULL, pub TEXT NOT NULL, netz TEXT NOT NULL, seq INTEGER NOT NULL, "
                       "ja REAL NOT NULL, nein REAL NOT NULL, zeit TEXT NOT NULL, PRIMARY KEY (hash, pub))")
        g.db().commit()


def compute() -> dict:
    """Sleep step 8g: every word's own weight, overall (`any`) and per question type, from the hint counters of the knowledge carrying it."""
    _tables()
    cond = " OR ".join(f"t.tag LIKE '{k}%'" for k in KINDS)
    base = ("FROM tag t JOIN objekt o ON o.id = t.objekt_id {join} WHERE o.art IN ('erkenntnis', 'regel', 'skill') AND o.modus IN ('aktiv', 'test') "
            f"AND o.sicht <> 'privat' AND ({cond}) GROUP BY t.tag{{group}}")
    sums = ("SUM(COALESCE(CAST(json_extract(o.daten, '$.nuetzlich.ja') AS REAL), 0)), SUM(COALESCE(CAST(json_extract(o.daten, '$.nuetzlich.nein') AS REAL), 0)), "
            "SUM(COALESCE(CAST(json_extract(o.daten, '$.nuetzlich.n') AS REAL), 0))")
    with g.lock:
        rows = [(w, "any", y, n_, c) for w, y, n_, c in g.db().execute(f"SELECT t.tag, {sums} " + base.format(join="", group=""))]
        rows += list(g.db().execute(f"SELECT t.tag, substr(a.tag, 9), {sums} "
                                    + base.format(join="JOIN tag a ON a.objekt_id = o.id AND a.tag LIKE 'answers:%' AND a.tag <> 'answers:unsure'",
                                                  group=", substr(a.tag, 9)")))
        now = g.now()
        g.db().execute("DELETE FROM vil_gewicht")
        for w, q, y, n_, c in rows:
            g.db().execute("INSERT INTO vil_gewicht (wort, frageart, ja, nein, n, hash, zeit) VALUES (?,?,?,?,?,?,?)",
                           (w, q, float(y or 0), float(n_ or 0), float(c or 0), word_hash(w, q), now))
        g.db().commit()
    return {"woerter": len({r[0] for r in rows}), "zeilen": len(rows), "gemessen": sum(1 for r in rows if (r[2] or 0) + (r[3] or 0) >= MIN_N)}


def own(word: str, qtype: str = "any") -> tuple[float, float]:
    """(yes, no) of this memory for a word and question type."""
    _tables()
    with g.lock:
        r = g.db().execute("SELECT ja, nein FROM vil_gewicht WHERE wort = ? AND frageart = ?", (word, qtype)).fetchone()
    return (float(r[0]), float(r[1])) if r else (0.0, 0.0)


def outgoing(net: str, limit: int = 2000) -> list[dict]:
    """Ratings this memory publishes for its words — measured ones only; an open network gets no host names and nothing internal."""
    from . import anonymize, p2p
    _tables()
    company = p2p.is_company(net)
    with g.lock:
        rows = g.db().execute("SELECT wort, hash, ja, nein, n FROM vil_gewicht WHERE ja + nein >= ? ORDER BY ja + nein DESC", (MIN_N,)).fetchall()
    out = []
    for w, h, y, n_, c in rows:
        if not company and (not w.startswith(OPEN_KINDS) or anonymize.categories(w)):
            continue
        out.append({"ziel": h, "gezeigt": round(c, 2), "ja": round(y, 2), "nein": round(n_, 2), "bestaetigt": 0, "widerlegt": 0})
        if len(out) >= limit:
            break
    return out


def known_hash(h: str) -> bool:
    _tables()
    with g.lock:
        if g.db().execute("SELECT 1 FROM vil_gewicht WHERE hash = ? LIMIT 1", (h,)).fetchone():
            return True
    from . import logic  # 0.62.0: rule weights travel on the same channel
    return logic.known_hash(h)


def receive(c: dict, pub: str, net: str, seq: int) -> bool:
    """A word weight from another server (a rating whose target is one of our word hashes); the latest per rater counts."""
    _tables()
    with g.lock:
        old = g.db().execute("SELECT seq FROM vil_gewicht_netz WHERE hash = ? AND pub = ?", (c["ziel"], pub)).fetchone()
        if old and old[0] >= seq:
            return True
        g.db().execute("INSERT OR REPLACE INTO vil_gewicht_netz (hash, pub, netz, seq, ja, nein, zeit) VALUES (?,?,?,?,?,?,?)",
                       (c["ziel"], pub, net, seq, float(c["ja"]) + float(c["bestaetigt"]), float(c["nein"]) + float(c["widerlegt"]), g.now()))
        g.db().commit()
    return True


def combined(word: str, qtype: str = "any") -> dict:
    """Own weight plus the network's: beta mean over this memory (weight 1) and every foreign rater (weight = its benefit as a publisher,
    0.5 while unknown), each capped at CAP observations."""
    y, n_ = own(word, qtype)
    c = combine(y, n_, word_hash(word, qtype))
    return {"gewicht": round((1 + c["ja"]) / (2 + c["ja"] + c["nein"]), 3), "eigen": [y, n_], "netz": c["netz"]}


def combine(y: float, n_: float, h: str) -> dict:
    """Own counters (weight 1) plus every foreign rater's for the target hash h (weight = its benefit as a publisher, 0.5 while unknown),
    each capped at CAP observations — shared by word weights and rule weights (logic.py)."""
    from . import p2p
    from .logbook import pseudonym
    _tables()
    with g.lock:
        foreign = g.db().execute("SELECT pub, ja, nein FROM vil_gewicht_netz WHERE hash = ?", (h,)).fetchall()
    value = p2p.publisher_value() if foreign else {}
    yes = no = 0.0
    for wgt, a, b in [(1.0, y, n_)] + [(value.get(pseudonym(p), {}).get("mittel", 0.5), a, b) for p, a, b in foreign]:
        if a + b <= 0:
            continue
        f = min(1.0, CAP / (a + b))
        yes, no = yes + wgt * a * f, no + wgt * b * f
    return {"ja": yes, "nein": no, "netz": len(foreign)}


def weight_for(word: str, qtype: str | None) -> float:
    """The word's weight for this question type where measured (own or from the network), else its overall weight (`any`) — a word
    without a measurement for one type still says what it is worth in general (found on 13.11.2026: without the fallback every hit of
    an unmeasured type weighed 0.5 and the order was chance)."""
    if qtype and qtype != "any":
        c = combined(word, qtype)
        if sum(c["eigen"]) > 0 or c["netz"]:
            return c["gewicht"]
    return combined(word, "any")["gewicht"]


def hit_weight(o, qtype: str | None) -> float:
    """Mean weight of an object's words for a question type — the order within one priority rank of a VIL question."""
    words = [t for t in o.hashtags if t.startswith(KINDS) and not t.startswith(("answers:", "memory:"))]
    if not words:
        return 0.5
    ws = [weight_for(w, qtype) for w in words[:8]]
    return sum(ws) / len(ws)
