"""Z6 method M1 (development): entity-anchored retrieval with one mention hop — the sym-rag idea (title lookup + one mention hop,
RAG-0: all-gold@4 90.5 % vs bge-m3 43.8 %) applied to the VI. Rules only, no model, nothing specific to the question templates:
  1. host vocabulary = every value of the VI's host:<fqdn> hashtags; a question names a host when its short name (first label) or
     its fqdn occurs as a word;
  2. anchor = the page whose TITLE names that host (imported documentation pages, text "LABEL: title — …"; the shortest such title
     wins) — v2, 22.11.2026 on development data: v1 anchored by host:<fqdn> hashtags, but a page about a VM carries its NODE's host
     tag, and the hashtag search for a hop host returned the VM page itself (dev smoke: node page @4 1/20);
     A short name (first label) counts only when it contains a digit (the hosts here are named like vmhost0002, vmhost0001); otherwise only
     the full name — found on development data: page titles with names like "system.…" and "that.…" made the words "system" and
     "that" of the English OS question into anchors (os/en both@4 0 % vs 89.6 % for the other forms).
  3. hop = every OTHER host whose name occurs as a word in the anchor's text + content and that has its own titled page; its page;
  4. ranking = anchor, hop objects (in order of first mention), then the hybrid list without duplicates.
usage: z6_hop.py DB QUESTIONS.jsonl OUT.jsonl [--limit N]   (DB = a private working copy; PYTHONPATH = vi-mcp rel-0.70.12)"""
import json
import os
import re
import sqlite3
import sys

from vi_mcp import evaluation, memory as g, vector


def vocab(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    hosts = sorted({t[5:] for (t,) in con.execute("SELECT DISTINCT tag FROM tag WHERE tag LIKE 'host:%'") if "." in t[5:]})
    by_name = {}
    for h in hosts:
        by_name.setdefault(h.lower(), set()).add(h)
        by_name.setdefault(h.split(".")[0].lower(), set()).add(h)
    return by_name


def named_hosts(text, by_name, exclude=()):
    found = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]", text):
        for h in sorted(by_name.get(w.lower(), ())):
            if h not in found and h not in exclude:
                found.append(h)
    return found


def title_index(db):
    """host name (fqdn and short) → page id of the shortest documentation title naming it."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    best = {}
    for oid, text in con.execute("SELECT id, text FROM object WHERE id LIKE 'insight:doc-%' AND mode = 'active'"):
        head = (text or "").split(" — ", 1)[0]
        title = head.split(": ", 1)[1] if ": " in head else head
        for h in re.findall(r"[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+){2,}", title.lower()):
            short = h.split(".")[0]
            for key in ((h, short) if any(ch.isdigit() for ch in short) else (h,)):
                if key not in best or len(title) < best[key][1]:
                    best[key] = (oid, len(title))
    return {k: v[0] for k, v in best.items()}


def tags_of(ids):
    objs = g.load_many(ids)
    return {i: set(objs[i].hashtags) if i in objs else set() for i in ids}, objs


def best_with_tag(ids, tag):
    tg, _ = tags_of(ids)
    return next((i for i in ids if tag in tg[i]), None)


def main():
    db, qf, out = sys.argv[1:4]
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    vector.config = {"url": os.environ["VI_EMBED_URL"]}   # the embedding service of the VI (internal URL, never in the repo)
    g.open_db(db)
    titles = title_index(db)
    rows = [json.loads(l) for l in open(qf)][:limit]
    with open(out, "w") as f:
        for q in rows:
            base = evaluation.hybrid(q["question"], 30)
            ranked, trace = [], {}
            words = [w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]", q["question"])]
            for w in dict.fromkeys(words):
                a = titles.get(w)
                if not a or a in ranked:
                    continue
                ranked.append(a)
                o = g.load_many([a]).get(a)
                body = (o.text + "\n" + str(o.data.get("content") or o.data.get("inhalt") or "")) if o else ""
                hops = []
                for h in re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]", body):
                    b = titles.get(h.lower())
                    if b and b != a and b not in hops:
                        hops.append(b)
                trace[a] = {"anchor_word": w, "hop_pages": hops[:5]}
                for b in hops[:5]:
                    if b not in ranked:
                        ranked.append(b)
            ranked += [i for i in base if i not in ranked]
            vm, node = q["gold"]
            f.write(json.dumps({"id": q["id"], "ids": ranked[:10], "vm4": vm in ranked[:4], "node4": node in ranked[:4],
                                "both4": vm in ranked[:4] and node in ranked[:4], "both10": vm in ranked[:10] and node in ranked[:10],
                                "trace": trace}) + "\n")


if __name__ == "__main__":
    main()
