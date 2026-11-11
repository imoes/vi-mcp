"""0.46.0: the web page of a server — a read-only window onto what the free and open networks carry: search, wiki, forum, knowledge.

Decided by the user (11.11.2026): every vi-mcp server can serve it (config `web`, off by default), read-only, only content of networks of
kind `free` and `open` — never a company network, never internal or private knowledge, never anything in quarantine. Server-side HTML,
standard library only, no JavaScript.

What is shown, and in which form:
  wiki      page views (wiki.view) of public networks; own revisions are labelled "this server", never with a local instance name
  forum     questions sent to or received from a public network (posts), with the answers this server holds; authors as in the network
            (pseudonyms), released posts only
  knowledge imports from public networks after release (mode test/aktiv) and this server's own contributions in exactly the form the
            network gets (p2p export form: anonymised) — never the local original
Everything is escaped; foreign text is marked as data. Links in text only http(s), rel="nofollow noopener noreferrer". Limited per
client address. The base path for links comes from the config (`web_base`, e.g. /vi-mcp/web behind the reverse proxy).
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse

from . import __version__
from . import memory as g

BASE = "/web"
PAGE_SIZE = 50
REQUESTS_PER_MIN = 120
_counter: dict[str, list[float]] = {}
_own_cache: dict[str, tuple[float, list[dict]]] = {}
OWN_CACHE_S = 300
PUBLIC_KINDS = ("free", "open")
KNOWLEDGE_KINDS = ("erkenntnis", "regel", "suche", "skill")


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def when(ts) -> str:
    """'2026-11-11T10:22:05Z' → '2026-11-11 10:22' (UTC)."""
    return e(str(ts or "")[:16].replace("T", " "))


def public_nets() -> dict[str, dict]:
    from . import p2p
    return {n: d for n, d in p2p.networks().items() if d["kind"] in PUBLIC_KINDS and p2p.is_on(n)}  # 0.47.0: a switched-off network is not shown


# ---- text rendering: a small, safe subset (paragraphs, headings, lists, code, links) ----

_URL = re.compile(r"https?://[^\s<>\"')\]]+")


def _inline(text: str) -> str:
    out, pos = [], 0
    for m in re.finditer(r"`([^`]+)`|" + _URL.pattern, text):
        out.append(e(text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(f"<code>{e(m.group(1))}</code>")
        else:
            url = m.group(0)
            out.append(f'<a href="{e(url)}" rel="nofollow noopener noreferrer">{e(url)}</a>')
        pos = m.end()
    out.append(e(text[pos:]))
    return "".join(out)


def render_text(text: str) -> str:
    """Wiki/forum text → HTML. Fenced code stays verbatim; merge conflicts (<<<<<<< … ======= … >>>>>>>) become two columns."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append(f"<pre><code>{e(chr(10).join(lines[i + 1:j]))}</code></pre>")
            i = j + 1
            continue
        if line.startswith("<<<<<<< "):
            a, b, j, side = [], [], i + 1, "a"
            while j < len(lines) and not lines[j].startswith(">>>>>>> "):
                if lines[j] == "=======":
                    side = "b"
                else:
                    (a if side == "a" else b).append(lines[j])
                j += 1
            ra, rb = line[8:].strip(), (lines[j][8:].strip() if j < len(lines) else "?")
            out.append('<div class="conflict"><p class="conflict-head">Conflict — two versions, nobody has merged them yet</p><div class="conflict-sides">'
                       f'<div><p class="rev">revision {e(ra)}</p>{render_text(chr(10).join(a))}</div>'
                       f'<div><p class="rev">revision {e(rb)}</p>{render_text(chr(10).join(b))}</div></div></div>')
            i = j + 1
            continue
        if not line.strip():
            i += 1
            continue
        if m := re.match(r"^(#{1,4})\s+(.*)$", line):
            lvl = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(f"<li>{_inline(re.sub(r'^\s*[-*]\s+', '', lines[i]))}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("```", "<<<<<<< ")) and not re.match(r"^(#{1,4})\s+|^\s*[-*]\s+", lines[i]):
            para.append(lines[i])
            i += 1
        out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
    return "\n".join(out)


# ---- content selection: only what a public network carries ----

def _imports(net: str, words: list[str] | None = None, limit: int = PAGE_SIZE) -> list[g.MemoryObject]:
    """Released imports of a public network (not quarantine), knowledge kinds, no forum answers (those belong to their thread)."""
    filt = " ".join(words) + " herkunft:p2p" if words else "herkunft:p2p"
    hits = g.recall(filt, limit=limit * 4, kinds=KNOWLEDGE_KINDS, viewer=None, or_fallback=bool(words))
    out = []
    for _s, o, _g in hits:
        h = o.data.get("herkunft") or {}
        if (h.get("netz") or "standard") != net or o.mode not in ("aktiv", "test") or o.visibility != "geteilt" or o.id.startswith("erkenntnis:post-"):
            continue
        out.append(o)
        if len(out) >= limit:
            break
    return out


def _own(net: str) -> list[dict]:
    """This server's contributions exactly as the network gets them (anonymised export form), cached for OWN_CACHE_S."""
    from . import p2p
    t, forms = _own_cache.get(net, (0.0, []))
    if time.time() - t > OWN_CACHE_S:
        forms = [r for _o, r in p2p._collect(None, net)[0]]
        _own_cache[net] = (time.time(), forms)
    return forms


def _matches(words: list[str], *texts) -> int:
    hay = " ".join(str(t or "") for t in texts).lower()
    return sum(1 for w in words if w.lower() in hay)


def _pages(net: str) -> list[dict]:
    from . import wiki
    out = []
    for _n, slug in wiki.pages(net):
        v, meta = wiki.view(net, slug)
        if not v.heads or v.deleted:
            continue
        last = max((m["entschieden"] or m["empfangen"] or "") for m in meta if m["status"] == "frei") if meta else ""
        out.append({"slug": slug, "title": v.title or slug, "state": v.state, "revisions": sum(1 for m in meta if m["status"] == "frei"), "last": last,
                    "first": (v.text.split("\n\n", 1)[0] if v.text else "")[:240]})
    return sorted(out, key=lambda p: p["last"], reverse=True)


def _threads(net: str) -> list[dict]:
    """Questions of a public network this server holds: sent from here and received (released)."""
    from . import forum
    forum._tables()
    with g.lock:
        sent = g.db().execute("SELECT id, daten, zeit, oid FROM beitrag_aus WHERE netz = ? AND art = 'frage' ORDER BY zeit DESC", (net,)).fetchall()
        recv = g.db().execute("SELECT id, autor, empfangen, oid FROM beitrag_ein WHERE netz = ? AND art = 'frage' AND status = 'frei' ORDER BY empfangen DESC", (net,)).fetchall()
    out = []
    for pid, data, t, oid in sent:
        c = json.loads(data)
        q = g.load(oid)
        out.append({"id": pid, "text": c["text"], "author": c["autor"], "time": t, "answers": len(_answers(pid, net, q, own=True)), "here": True,
                    "state": (q.data.get("zustand") if q else "—")})
    for pid, autor, t, oid in recv:
        q = g.load(oid)
        if not q:
            continue
        out.append({"id": pid, "text": q.text, "author": autor, "time": t, "answers": len(_answers(pid, net, q, own=False)), "here": False,
                    "state": q.data.get("zustand")})
    return sorted(out, key=lambda x: x["time"], reverse=True)


def _answers(pid: str, net: str, q: g.MemoryObject | None, own: bool) -> list[dict]:
    """Answers as the network carries them. Own question: the released answers from the network. Received question: the answers this
    server sent (only those that left as posts — a local answer refused for the open network is never shown)."""
    from . import net_score
    if own:
        out = []
        for a in (q.data.get("antworten") if q else []) or []:
            ao = g.load(a.get("objekt") or "")
            if not ao or ao.mode not in ("test", "aktiv"):
                continue
            s = net_score.score(net_score.hash_of(ao.id), ao) if net_score.hash_of(ao.id) else None
            out.append({"author": a["instanz"].split("@")[0], "text": ao.text, "evidence": ao.data.get("inhalt") or "", "time": a.get("zeit", ""),
                        "accepted": ao.confirmed > 0, "score": s})
        return out
    with g.lock:
        sent = g.db().execute("SELECT daten, zeit FROM beitrag_aus WHERE netz = ? AND art = 'antwort' AND eltern = ? ORDER BY zeit", (net, pid)).fetchall()
    return [{"author": (c := json.loads(d))["autor"], "text": c["text"], "evidence": c["inhalt"], "time": t, "accepted": False, "score": None} for d, t in sent]


# ---- pages ----

CSS = """
:root{--paper:#f6f4ee;--card:#fffdf8;--ink:#1d2421;--muted:#5d6762;--line:#dcd8cc;--accent:#1f6f5c;--accent-ink:#ffffff;--warn:#9a5b00;--warn-bg:#fff4df;--code:#efece3}
@media (prefers-color-scheme:dark){:root{--paper:#141816;--card:#1b201e;--ink:#e6e8e4;--muted:#9aa49f;--line:#2e3532;--accent:#5fbf9f;--accent-ink:#0d1210;--warn:#f0b35a;--warn-bg:#2c2416;--code:#232926}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
header.top{border-bottom:1px solid var(--line);background:var(--card)}
.wrap{max-width:62rem;margin:0 auto;padding:0 max(16px,env(safe-area-inset-left))}
header.top .wrap{display:flex;flex-wrap:wrap;gap:.75rem 1.5rem;align-items:center;padding-block:.8rem}
.brand{font-family:"Iowan Old Style","Charter","Georgia",serif;font-size:1.35rem;font-weight:700;color:var(--ink);text-decoration:none;letter-spacing:.01em}
.brand span{color:var(--accent)}
nav a{margin-right:1rem;text-decoration:none;color:var(--muted)}
nav a:hover{color:var(--accent)}
form.search{display:flex;gap:.5rem;flex:1 1 18rem}
form.search input{flex:1;min-width:0;padding:.55rem .75rem;border:1px solid var(--line);border-radius:.5rem;background:var(--paper);color:var(--ink);font:inherit}
form.search button,.btn{padding:.55rem 1rem;border:0;border-radius:.5rem;background:var(--accent);color:var(--accent-ink);font:inherit;cursor:pointer}
main{padding-block:1.5rem 3rem}
h1,h2,h3,h4,h5,h6{font-family:"Iowan Old Style","Charter","Georgia",serif;line-height:1.25;text-wrap:balance}
h1{font-size:1.9rem;margin:.2rem 0 1rem}
h2{font-size:1.35rem;margin:2rem 0 .75rem}
.muted,.meta{color:var(--muted);font-size:.9rem}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(16rem,1fr));gap:1rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:.75rem;padding:1rem 1.1rem;min-width:0}
.card h3{margin:.1rem 0 .4rem;font-size:1.1rem}
.kind{display:inline-block;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:.05rem .5rem;margin-right:.4rem}
ul.list{list-style:none;padding:0;margin:0}
ul.list li{background:var(--card);border:1px solid var(--line);border-radius:.6rem;padding:.8rem 1rem;margin-bottom:.6rem;min-width:0}
ul.list li h3{margin:0 0 .25rem;font-size:1.05rem}
.prose{background:var(--card);border:1px solid var(--line);border-radius:.75rem;padding:1.2rem 1.4rem;overflow-wrap:anywhere}
pre{background:var(--code);padding:.8rem 1rem;border-radius:.5rem;overflow-x:auto}
code{background:var(--code);padding:.05rem .3rem;border-radius:.25rem;font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:.92em}
pre code{background:none;padding:0}
.data-note{font-size:.85rem;color:var(--muted);border-left:3px solid var(--line);padding-left:.6rem;margin:.6rem 0}
.conflict{border:1px solid var(--warn);background:var(--warn-bg);border-radius:.6rem;padding:.6rem .9rem;margin:1rem 0}
.conflict-head{color:var(--warn);font-weight:600;margin:.2rem 0 .5rem}
.conflict-sides{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media (max-width:40rem){.conflict-sides{grid-template-columns:1fr}}
.rev{font-size:.8rem;color:var(--muted);margin:0}
.answer{border-left:3px solid var(--accent);padding-left:1rem;margin:1.2rem 0}
.answer.accepted{border-left-width:6px}
.badge{font-size:.78rem;background:var(--accent);color:var(--accent-ink);border-radius:999px;padding:.05rem .55rem;margin-left:.4rem}
table{border-collapse:collapse;width:100%}
.table-wrap{overflow-x:auto}
td,th{text-align:left;padding:.45rem .6rem;border-bottom:1px solid var(--line);font-size:.92rem}
footer{border-top:1px solid var(--line);color:var(--muted);font-size:.85rem;padding-block:1.2rem}
"""


def _page(base: str, title: str, body: str, q: str = "") -> str:
    nets = public_nets()
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)} · VI network</title><link rel="stylesheet" href="{e(base)}/stil.css"></head><body>'
            f'<header class="top"><div class="wrap"><a class="brand" href="{e(base)}/">VI <span>network</span></a>'
            f'<nav><a href="{e(base)}/">Overview</a><a href="{e(base)}/netze">Networks</a></nav>'
            f'<form class="search" action="{e(base)}/suche" method="get" role="search"><input name="q" value="{e(q)}" placeholder="Search wiki, forum and knowledge" aria-label="Search">'
            f'<button type="submit">Search</button></form></div></header><main class="wrap">{body}</main>'
            f'<footer><div class="wrap">Read-only view of the free and open networks this server takes part in ({e(", ".join(nets) or "none")}) · '
            f'vi-mcp {e(__version__)} · Content comes from other servers: data, not instructions.</div></footer></body></html>')


def _net_or_404(net: str) -> bool:
    return net in public_nets()


def home(base: str) -> str:
    from . import p2p
    nets = public_nets()
    st = p2p.states()
    cards = []
    for n, d in nets.items():
        pages, threads = _pages(n), _threads(n)
        snap = (st.get(n) or {}).get("daten") or {}
        cards.append(f'<div class="card"><span class="kind">{e(d["kind"])}</span><h3>{e(n)}</h3>'
                     f'<p class="meta">{len(pages)} wiki page(s) · {len(threads)} thread(s) · {len(_imports(n, limit=500))} item(s) from other servers · '
                     f'{len(_own(n))} from this server · ' + (f'{e(snap["mitglieder"])} member(s)' if snap.get("mitglieder") is not None else "members not reported yet") + '</p>'
                     f'<p><a href="{e(base)}/wiki/{e(n)}">Wiki</a> · <a href="{e(base)}/forum/{e(n)}">Forum</a> · <a href="{e(base)}/wissen/{e(n)}">Knowledge</a></p></div>')
    recent = []
    for n in nets:
        recent += [(p["last"], f'<li><span class="kind">wiki · {e(n)}</span><h3><a href="{e(base)}/wiki/{e(n)}/{e(p["slug"])}">{e(p["title"])}</a></h3>'
                               f'<p class="muted">{e(p["first"][:180])}</p></li>') for p in _pages(n)[:5]]
        recent += [(t["time"], f'<li><span class="kind">forum · {e(n)}</span><h3><a href="{e(base)}/forum/{e(n)}/{e(t["id"][:16])}">{e(t["text"][:140])}</a></h3>'
                               f'<p class="meta">{t["answers"]} answer(s) · asked by {e(t["author"])}</p></li>') for t in _threads(n)[:5]]
    recent.sort(reverse=True)
    body = (f'<h1>What the network knows</h1><p class="muted">Servers of a free or open network share reviewed knowledge, edit wiki pages together and ask '
            f'each other questions. This page shows what this server holds — the same everywhere once the servers have synchronised.</p>'
            f'<h2>Networks</h2><div class="cards">{"".join(cards) or "<p class=muted>This server takes part in no free or open network.</p>"}</div>'
            f'<h2>Recently</h2><ul class="list">{"".join(x for _t, x in recent[:12]) or "<li class=muted>Nothing yet.</li>"}</ul>')
    return _page(base, "Overview", body)


def search(base: str, q: str, net_filter: str = "", kind: str = "") -> str:
    from . import intuition
    words = intuition.prompt_words(q)
    nets = [n for n in public_nets() if not net_filter or n == net_filter]
    results = []
    if words:
        for n in nets:
            if kind in ("", "wiki"):
                for p in _pages(n):
                    from . import wiki
                    v, _m = wiki.view(n, p["slug"])
                    sc = _matches(words, p["title"], p["slug"]) * 3 + _matches(words, v.text)
                    if sc:
                        results.append((sc, f'<li><span class="kind">wiki · {e(n)}</span><h3><a href="{e(base)}/wiki/{e(n)}/{e(p["slug"])}">{e(p["title"])}</a></h3>'
                                            f'<p class="muted">{e(p["first"][:200])}</p></li>'))
            if kind in ("", "forum"):
                for t in _threads(n):
                    sc = _matches(words, t["text"]) * 2
                    if sc:
                        results.append((sc, f'<li><span class="kind">forum · {e(n)}</span><h3><a href="{e(base)}/forum/{e(n)}/{e(t["id"][:16])}">{e(t["text"][:160])}</a></h3>'
                                            f'<p class="meta">{t["answers"]} answer(s)</p></li>'))
            if kind in ("", "wissen"):
                for o in _imports(n, words, limit=30):
                    sc = _matches(words, o.text, " ".join(o.hashtags)) * 2
                    if sc:
                        results.append((sc, f'<li><span class="kind">{e(o.kind)} · {e(n)}</span><h3><a href="{e(base)}/eintrag/{e(o.id)}">{e(o.text[:160])}</a></h3>'
                                            f'<p class="meta">from {e((o.data.get("herkunft") or {}).get("herausgeber", "?"))}</p></li>'))
                for f in _own(n):
                    sc = _matches(words, f["text"], " ".join(f["hashtags"]), f.get("inhalt", "")[:2000]) * 2
                    if sc:
                        results.append((sc, f'<li><span class="kind">{e(f["art"])} · {e(n)}</span><h3><a href="{e(base)}/eigen/{e(n)}/{e(f["netz_id"])}">{e(f["text"][:160])}</a></h3>'
                                            f'<p class="meta">from this server</p></li>'))
    results.sort(key=lambda r: -r[0])
    opts = "".join(f'<option value="{e(v)}"{" selected" if kind == v else ""}>{e(t)}</option>' for v, t in (("", "everything"), ("wiki", "wiki"), ("forum", "forum"), ("wissen", "knowledge")))
    head = (f'<h1>Search</h1><form class="search" action="{e(base)}/suche" method="get"><input name="q" value="{e(q)}" aria-label="Search">'
            f'<select name="art" aria-label="Kind">{opts}</select><button type="submit">Search</button></form>')
    if not q:
        return _page(base, "Search", head + '<p class="muted">Search the wiki pages, forum threads and knowledge of the free and open networks.</p>', q)
    if not words:
        return _page(base, "Search", head + '<p class="muted">The search needs words of at least three letters that are not stop words.</p>', q)
    body = head + f'<p class="meta">{len(results)} result(s) for {e(" ".join(words))}</p><ul class="list">' + "".join(r for _s, r in results[:PAGE_SIZE]) + "</ul>"
    return _page(base, f"Search: {q}", body, q)


def wiki_index(base: str, net: str) -> str:
    pages = _pages(net)
    items = "".join(f'<li><h3><a href="{e(base)}/wiki/{e(net)}/{e(p["slug"])}">{e(p["title"])}</a></h3>'
                    f'<p class="muted">{e(p["first"][:200])}</p><p class="meta">{e(p["slug"])} · {p["revisions"]} revision(s) · {e(p["state"])} · {when(p["last"])}</p></li>'
                    for p in pages[:PAGE_SIZE * 4])
    return _page(base, f"Wiki · {net}", f'<h1>Wiki of {e(net)}</h1><p class="muted">{len(pages)} page(s). Every server of the network may edit; '
                                         f'changes of other servers count here after review.</p><ul class="list">{items or "<li class=muted>No pages yet.</li>"}</ul>')


def wiki_page(base: str, net: str, slug: str, history: bool, rev: str = "") -> str | None:
    from . import wiki
    v, meta = wiki.view(net, slug)
    if not meta:
        return None
    label = lambda m: "this server" if m["eigen"] else m["autor"]  # noqa: E731 — never a local instance name
    if history:
        rows = "".join(f'<tr><td><a href="{e(base)}/wiki/{e(net)}/{e(slug)}?rev={e(m["rev"][:16])}"><code>{e(m["rev"][:16])}</code></a></td>'
                       f'<td>{e(", ".join(p[:12] for p in m["eltern"]) or "first")}</td><td>{e(label(m))}</td><td>{e(m["status"])}</td>'
                       f'<td>{e(m["zeit"] or m["empfangen"][:10])}</td><td>{e(m["notiz"])}</td></tr>' for m in meta)
        return _page(base, f"History · {slug}", f'<p class="meta"><a href="{e(base)}/wiki/{e(net)}/{e(slug)}">← {e(v.title or slug)}</a></p><h1>History</h1>'
                                                 f'<div class="table-wrap"><table><thead><tr><th>Revision</th><th>Parents</th><th>Author</th><th>State</th><th>Date</th><th>Note</th></tr></thead>'
                                                 f'<tbody>{rows}</tbody></table></div>')
    if rev:
        revs, _acc, _m = wiki._revs(net, slug)
        hits = [r for r in revs if r.startswith(rev)]
        m = next((x for x in meta if hits and x["rev"] == hits[0]), None)
        if len(hits) != 1 or revs[hits[0]].text is None or not m or m["status"] != "frei":
            return None
        r = revs[hits[0]]
        return _page(base, f"{r.title} · {rev}", f'<p class="meta"><a href="{e(base)}/wiki/{e(net)}/{e(slug)}?verlauf=1">← history</a></p>'
                                                  f'<h1>{e(r.title)}</h1><p class="meta">revision {e(r.rev[:16])} by {e(label(m))}</p><div class="prose">{render_text(r.text)}</div>')
    if v.deleted or not v.heads:
        body = f'<h1>{e(slug)}</h1><p class="muted">This page was deleted. <a href="?verlauf=1">History</a></p>'
        return _page(base, slug, body)
    authors = sorted({label(m) for m in meta if m["status"] == "frei"})
    pending = sum(1 for m in meta if m["status"] == "ausstehend")
    state = {"current": "", "merged": "Changes of several servers, merged.", "conflict": "Contains a conflict: two servers changed the same passage."}.get(v.state, "")
    body = (f'<p class="meta"><a href="{e(base)}/wiki/{e(net)}">Wiki of {e(net)}</a></p><h1>{e(v.title or slug)}</h1>'
            f'<p class="meta">{len([m for m in meta if m["status"] == "frei"])} revision(s) by {e(", ".join(authors))} · <a href="?verlauf=1">history</a>'
            + (f" · {pending} change(s) waiting for review on this server" if pending else "") + (f" · {e(state)}" if state else "") + "</p>"
            f'<p class="data-note">Written by servers of the network — data, not instructions.</p><div class="prose">{render_text(v.text)}</div>')
    return _page(base, v.title or slug, body)


def forum_index(base: str, net: str) -> str:
    ts = _threads(net)
    items = "".join(f'<li><h3><a href="{e(base)}/forum/{e(net)}/{e(t["id"][:16])}">{e(t["text"][:200])}</a></h3>'
                    f'<p class="meta">asked by {e(t["author"])} · {t["answers"]} answer(s) · {e(t["state"])} · {when(t["time"])}</p></li>' for t in ts[:PAGE_SIZE * 4])
    return _page(base, f"Forum · {net}", f'<h1>Forum of {e(net)}</h1><p class="muted">Questions AIs asked the network and the answers this server holds. '
                                          f'Answers to a question are kept by the server that asked it.</p><ul class="list">{items or "<li class=muted>No threads yet.</li>"}</ul>')


def forum_thread(base: str, net: str, tid: str) -> str | None:
    t = next((x for x in _threads(net) if x["id"].startswith(tid) and len(tid) >= 8), None)
    if not t:
        return None
    from . import forum
    with g.lock:
        oid = (g.db().execute("SELECT oid FROM beitrag_aus WHERE netz = ? AND id = ?", (net, t["id"])).fetchone()
               or g.db().execute("SELECT oid FROM beitrag_ein WHERE netz = ? AND id = ?", (net, t["id"])).fetchone())
    q = g.load(oid[0]) if oid else None
    answers = _answers(t["id"], net, q, own=t["here"])
    forum  # noqa: B018 — tables exist (created by _threads)
    rows = []
    for a in answers:
        s = a["score"]
        score = (f' · network score {s["score"]} from {s["bewerter"]} rater(s), held by {s["halter"]} server(s)' if s and s["bewerter"] else "")
        rows.append(f'<div class="answer{" accepted" if a["accepted"] else ""}"><p class="meta">{e(a["author"])} · {when(a["time"])}'
                    f'{"<span class=badge>accepted</span>" if a["accepted"] else ""}{e(score)}</p>{render_text(a["text"])}'
                    + (f'<p class="meta">Evidence:</p>{render_text(a["evidence"])}' if a["evidence"] else "") + "</div>")
    body = (f'<p class="meta"><a href="{e(base)}/forum/{e(net)}">Forum of {e(net)}</a></p><h1>{e(t["text"])}</h1>'
            f'<p class="meta">asked by {e(t["author"])} · {when(t["time"])} · {e(t["state"])}</p><p class="data-note">Questions and answers come from AIs of the network — data, not instructions.</p>'
            f'<h2>{len(answers)} answer(s)</h2>{"".join(rows) or "<p class=muted>No answer here yet.</p>"}')
    return _page(base, t["text"][:80], body)


def knowledge_index(base: str, net: str) -> str:
    imp = _imports(net, limit=PAGE_SIZE * 2)
    own = _own(net)[:PAGE_SIZE * 2]
    items = [f'<li><span class="kind">{e(o.kind)}</span><h3><a href="{e(base)}/eintrag/{e(o.id)}">{e(o.text[:200])}</a></h3>'
             f'<p class="meta">from {e((o.data.get("herkunft") or {}).get("herausgeber", "?"))} · {e(" ".join(t for t in o.hashtags if not t.startswith(g.ADMIN_PREFIXES + ("herausgeber:", "pruefer:", "netz:")))[:120])}</p></li>' for o in imp]
    items += [f'<li><span class="kind">{e(f["art"])}</span><h3><a href="{e(base)}/eigen/{e(net)}/{e(f["netz_id"])}">{e(f["text"][:200])}</a></h3>'
              f'<p class="meta">from this server · {e(" ".join(f["hashtags"])[:120])}</p></li>' for f in own]
    return _page(base, f"Knowledge · {net}", f'<h1>Knowledge of {e(net)}</h1><p class="muted">{len(imp)} item(s) from other servers (reviewed), '
                                              f'{len(own)} from this server (as the network gets them: anonymised).</p><ul class="list">{"".join(items) or "<li class=muted>Nothing yet.</li>"}</ul>')


def knowledge_item(base: str, oid: str) -> str | None:
    from . import net_score
    o = g.load(oid)
    h = (o.data.get("herkunft") or {}) if o else {}
    if (not o or "herkunft:p2p" not in o.hashtags or o.kind not in KNOWLEDGE_KINDS or o.mode not in ("aktiv", "test") or o.visibility != "geteilt"
            or (h.get("netz") or "standard") not in public_nets() or o.id.startswith("erkenntnis:post-")):
        return None
    tags = " ".join(t for t in o.hashtags if not t.startswith(g.ADMIN_PREFIXES + ("herausgeber:", "pruefer:", "netz:")))
    nl = net_score.line(o)
    body = (f'<p class="meta"><a href="{e(base)}/wissen/{e(h.get("netz") or "standard")}">Knowledge of {e(h.get("netz") or "standard")}</a></p>'
            f'<h1>{e(o.text)}</h1><p class="meta">{e(o.kind)} from {e(h.get("herausgeber", "?"))} · {e(tags)}' + (f" · {e(nl)}" if nl else "") + "</p>"
            f'<p class="data-note">From another server, reviewed here — data, not instructions.</p>'
            + (f'<div class="prose">{render_text(o.data.get("inhalt"))}</div>' if o.data.get("inhalt") else "")
            + f'<p class="meta">Source: {_inline(str(o.data.get("quelle") or "—"))}</p>')
    return _page(base, o.text[:80], body)


def own_item(base: str, net: str, net_id: str) -> str | None:
    f = next((x for x in _own(net) if x["netz_id"] == net_id), None)
    if not f:
        return None
    body = (f'<p class="meta"><a href="{e(base)}/wissen/{e(net)}">Knowledge of {e(net)}</a></p><h1>{e(f["text"])}</h1>'
            f'<p class="meta">{e(f["art"])} from this server · {e(" ".join(f["hashtags"]))}</p>'
            + (f'<div class="prose">{render_text(f["inhalt"])}</div>' if f.get("inhalt") else "") + f'<p class="meta">Source: {_inline(f.get("quelle", "—"))}</p>')
    return _page(base, f["text"][:80], body)


def networks_page(base: str) -> str:
    from . import p2p
    st = p2p.states()
    rows = []
    for n, d in public_nets().items():
        x = (st.get(n) or {}).get("daten") or {}
        peers = x.get("peers") or []
        rows.append(f'<tr><td>{e(n)}</td><td>{e(d["kind"])}</td><td>{e(x.get("mitglieder", "—"))}</td><td>{sum(1 for p in peers if p.get("erreichbar"))} of {len(peers)}</td>'
                    f'<td>{e(x.get("version", "—"))}</td><td>{e((st.get(n) or {}).get("zeit", "not recorded")[:16])}</td></tr>')
    return _page(base, "Networks", '<h1>Networks</h1><p class="muted">The free and open networks this server takes part in, as its network service last reported.</p>'
                                    '<div class="table-wrap"><table><thead><tr><th>Network</th><th>Kind</th><th>Members</th><th>Peers reachable</th><th>Version</th><th>Reported</th></tr></thead>'
                                    f'<tbody>{"".join(rows) or "<tr><td colspan=6>none</td></tr>"}</tbody></table></div>')


SECURITY_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
                    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "public, max-age=60"}


def _limited(ip: str) -> bool:
    now = time.time()
    z = [t for t in _counter.get(ip, []) if now - t < 60]
    z.append(now)
    _counter[ip] = z
    if len(_counter) > 10000:
        _counter.clear()
    return len(z) > REQUESTS_PER_MIN


def handle(raw_path: str, client: str, base: str = BASE) -> tuple[int, str, bytes, dict]:
    """(status, content type, body, headers) for a GET under /web."""
    if _limited(client):
        return 429, "text/plain; charset=utf-8", b"too many requests", {"Retry-After": "60"}
    u = urllib.parse.urlsplit(raw_path)
    path = u.path[len("/web"):] if u.path.startswith("/web") else u.path
    qs = urllib.parse.parse_qs(u.query)
    one = lambda k: (qs.get(k) or [""])[0][:300]  # noqa: E731
    parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/") if p]
    html_out = None
    if path == "/stil.css":
        return 200, "text/css; charset=utf-8", CSS.encode(), {**SECURITY_HEADERS, "Cache-Control": "public, max-age=3600"}
    if not parts:
        html_out = home(base)
    elif parts == ["suche"]:
        html_out = search(base, one("q"), one("netz"), one("art"))
    elif parts == ["netze"]:
        html_out = networks_page(base)
    elif parts[0] in ("wiki", "forum", "wissen", "eigen") and len(parts) >= 2 and _net_or_404(parts[1]):
        net = parts[1]
        if parts[0] == "wiki":
            html_out = wiki_index(base, net) if len(parts) == 2 else wiki_page(base, net, "/".join(parts[2:]), bool(one("verlauf")), one("rev"))
        elif parts[0] == "forum":
            html_out = forum_index(base, net) if len(parts) == 2 else forum_thread(base, net, parts[2])
        elif parts[0] == "wissen" and len(parts) == 2:
            html_out = knowledge_index(base, net)
        elif parts[0] == "eigen" and len(parts) == 3:
            html_out = own_item(base, net, parts[2])
    elif parts[0] == "eintrag" and len(parts) == 2:
        html_out = knowledge_item(base, parts[1])
    if html_out is None:
        return 404, "text/html; charset=utf-8", _page(base, "Not found", '<h1>Not found</h1><p class="muted">Nothing public under this address.</p>').encode(), SECURITY_HEADERS
    return 200, "text/html; charset=utf-8", html_out.encode(), SECURITY_HEADERS
