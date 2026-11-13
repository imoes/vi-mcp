"""0.62.0: the internal knowledge search in the browser — "wie bei Wikipedia darin suchen" (the user, 13.11.2026).

Decided by the user: internal, with sign-in. Config `web_internal` (off by default), path `web_internal_base` (e.g. /vi-mcp/intern behind
the reverse proxy). The public page /web (web.py) is unchanged and still never shows internal knowledge.

- Sign-in with a VI token (the same check as /mcp: config.instance_for); a session lives in this process for SESSION_S, the browser
  holds only a random id in a cookie (HttpOnly, Secure, SameSite=Strict, Path = base). The token never appears in a URL, a log or a page.
  The login POST must come from this site (Origin = Host, or an origin of the config) — SameSite and the check against cross-site forms.
- Shown: shared and internal knowledge (KINDS) the signed-in instance may see — never private objects (not even its own), never
  quarantine, never experiences or conversations. What a search finds but this page does not show is counted under the hits.
- Search: the same path as vi_recall (tools.search: full text, meaning, rank fusion, reranker), read only — a page view reinforces
  nothing and writes no search log entry with the query; it is counted as a call `web_search` in the usage statistics.
- Server-side HTML, standard library only, no JavaScript, strict CSP; text rendering and style of web.py.
"""
from __future__ import annotations

import secrets
import threading
import time
import urllib.parse

from . import __version__
from . import memory as g
from .web import CSS, SECURITY_HEADERS, _inline, _limited, e, render_text, when

BASE = "/intern"
SESSION_S = 8 * 3600
COOKIE = "vi_intern"
KINDS = ("erkenntnis", "regel", "skill", "suche", "bild", "seite")
HIDDEN_MODES = ("quarantaene",)
PAGE_HITS = 30
#: signed-in pages are never cached. Referrer-Policy same-origin, not the no-referrer of /web: with no-referrer Chrome sends the sign-in
#: POST with "Origin: null" (found in the browser test, 13.11.2026), and the cross-site check must reject null.
HEADERS = {**SECURITY_HEADERS, "Cache-Control": "no-store", "Referrer-Policy": "same-origin"}
_sessions: dict[str, tuple[str, float]] = {}  # session id → (instance, expiry)
_lock = threading.Lock()


# ── sessions ────────────────────────────────────────────────────────────────

def _new_session(instance: str) -> str:
    sid = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        for k in [k for k, (_i, t) in _sessions.items() if t < now]:
            del _sessions[k]
        _sessions[sid] = (instance, now + SESSION_S)
    return sid


def _instance(cookie_header: str | None) -> str | None:
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE and v:
            with _lock:
                inst, t = _sessions.get(v, (None, 0.0))
            return inst if inst and t > time.time() else None
    return None


def _cookie(base: str, sid: str, max_age: int) -> str:
    return f"{COOKIE}={sid}; Path={base}; Max-Age={max_age}; HttpOnly; Secure; SameSite=Strict"


def _same_site(headers, origins: list[str]) -> bool:
    origin = headers.get("Origin")
    if not origin:  # browsers send Origin with every POST form; without one it is no browser form from elsewhere either
        return True
    host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").split(",")[0].strip()
    o = urllib.parse.urlsplit(origin)
    return bool(host) and o.netloc == host or any(origin == x or origin.startswith(x + ":") for x in origins)


# ── page frame ──────────────────────────────────────────────────────────────

EXTRA_CSS = """
.hero{display:flex;flex-direction:column;gap:1rem;padding-block:2.5rem 1rem}
.hero h1{font-size:2.3rem;margin:0}
.hero form.search{max-width:40rem}
.hit h3 a{text-decoration:none}
.excerpt{margin:.25rem 0;overflow-wrap:anywhere}
.tags a{display:inline-block;font-size:.8rem;margin:.15rem .35rem 0 0;color:var(--muted);text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:0 .5rem}
.tags a:hover{color:var(--accent);border-color:var(--accent)}
dl.facts{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem;margin:0}
dl.facts dt{color:var(--muted)}
dl.facts dd{margin:0;min-width:0;overflow-wrap:anywhere}
.refuted{color:var(--warn);font-weight:600}
form.login{display:flex;flex-direction:column;gap:.75rem;max-width:26rem}
form.login input{padding:.55rem .75rem;border:1px solid var(--line);border-radius:.5rem;background:var(--paper);color:var(--ink);font:inherit}
.error{color:var(--warn);background:var(--warn-bg);border:1px solid var(--warn);border-radius:.5rem;padding:.5rem .8rem}
form.inline{display:inline}
form.inline button{background:none;border:0;color:var(--muted);font:inherit;cursor:pointer;padding:0}
"""


def _page(base: str, title: str, body: str, instance: str | None, q: str = "") -> str:
    nav = (f'<form class="search" action="{e(base)}/suche" method="get" role="search"><input name="q" value="{e(q)}" list="vocab" '
           f'placeholder="Search the knowledge" aria-label="Search"><button type="submit">Search</button></form>'
           f'<nav><a href="{e(base)}/">Overview</a><a href="{e(base)}/w">Words</a><form class="inline" action="{e(base)}/logout" method="post">'
           f'<button type="submit">Sign out ({e(instance)})</button></form></nav>') if instance else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)} · VI knowledge</title><link rel="stylesheet" href="{e(base)}/stil.css"></head><body>'
            f'<header class="top"><div class="wrap"><a class="brand" href="{e(base)}/">VI <span>knowledge</span></a>{nav}</div></header>'
            f'<main class="wrap">{body}</main>{_datalist(instance) if instance else ""}<footer><div class="wrap">Internal knowledge of this vi-mcp server — shared and internal, never '
            f'private · read only · vi-mcp {e(__version__)}</div></footer></body></html>')


VOCAB_OPTIONS = 400


def _datalist(instance: str) -> str:
    """0.62.0: autocomplete without script — the most used words this instance may see, as a <datalist> of the search field."""
    from . import vocabulary
    opts = []
    for k, _nv, _no in vocabulary.kinds(instance, 40):
        opts += [t for t, _n in vocabulary.values(k, "", instance, max(5, VOCAB_OPTIONS // 40))]
    return '<datalist id="vocab">' + "".join(f'<option value="{e(t)}">' for t in opts[:VOCAB_OPTIONS]) + "</datalist>"


def words_page(base: str, instance: str, kind: str = "") -> str:
    """0.62.0: "what is there, what can I search?" — the kinds of words, or the values of one kind, each a link to its search."""
    from . import vocabulary
    if kind:
        rows = vocabulary.values(kind, "", instance, 500)
        body = (f'<p class="meta"><a href="{e(base)}/w">Words</a> › {e(kind)}</p><h1>{e(kind)}: — {len(rows)} value{"" if len(rows) == 1 else "s"}</h1>'
                + '<div class="tags">' + "".join(f'<a href="{e(base)}/suche?q={urllib.parse.quote(t)}">{e(t)} ({n})</a>' for t, n in rows) + "</div>")
        return _page(base, f"Words: {kind}", body, instance)
    rows = vocabulary.kinds(instance, 200)
    body = ('<h1>Words you can search with</h1><p class="muted">Every word is a hashtag <code>kind:value</code>. Counted over what you may see.</p>'
            '<div class="table-wrap"><table><tr><th>kind</th><th>values</th><th>objects</th></tr>'
            + "".join(f'<tr><td><a href="{e(base)}/w/{e(k)}">{e(k)}:</a></td><td>{nv}</td><td>{no}</td></tr>' for k, nv, no in rows) + "</table></div>")
    return _page(base, "Words", body, instance)


def _login_page(base: str, error: str = "") -> str:
    body = ('<div class="hero"><h1>Sign in</h1><p class="muted">The knowledge of this memory is internal. Sign in with the token of your '
            'VI instance (the file the setup wrote, e.g. <code>~/.config/vi-mcp/token-…</code>).</p>'
            + (f'<p class="error">{e(error)}</p>' if error else "")
            + f'<form class="login" action="{e(base)}/login" method="post"><label for="t">Token</label>'
            f'<input id="t" name="token" type="password" autocomplete="current-password" required>'
            f'<button class="btn" type="submit">Sign in</button></form></div>')
    return _page(base, "Sign in", body, None)


# ── content ─────────────────────────────────────────────────────────────────

def _visible(o: g.MemoryObject | None) -> str | None:
    """None if this page may show the object, else the reason it does not."""
    if o is None:
        return "unknown"
    if o.visibility == "privat":
        return "private"
    if o.mode in HIDDEN_MODES:
        return "in quarantine"
    if o.kind not in KINDS:
        return f"kind {o.kind} is not shown here"
    return None


def _excerpt(o: g.MemoryObject, n: int = 260) -> str:
    import re
    t = re.sub(r"(?m)^\s*(#{1,6}|[-*]|```\w*)\s*", "", str(o.data.get("inhalt") or ""))  # plain text: no Markdown marks
    t = re.sub(r"\s+", " ", t.replace("**", "").replace("`", "")).strip()
    return (t[:n] + " …") if len(t) > n else t


def _tag_links(base: str, tags: list[str]) -> str:
    from . import checks
    shown = [t for t in tags if not t.startswith(checks.FIXED_HASHTAGS)][:14]
    return '<div class="tags">' + "".join(f'<a href="{e(base)}/suche?q={urllib.parse.quote(t)}">{e(t)}</a>' for t in shown) + "</div>"


def _hit(base: str, o: g.MemoryObject) -> str:
    refuted = ' <span class="refuted">refuted</span>' if o.mode == "widerlegt" else ""
    return (f'<li class="hit"><span class="kind">{e(o.kind)}</span><span class="kind">{e(o.idx)}</span>'
            f'<h3><a href="{e(base)}/o/{urllib.parse.quote(o.id, safe=":")}">{e(o.text[:220])}</a>{refuted}</h3>'
            f'<p class="excerpt muted">{e(_excerpt(o))}</p><p class="meta">{when(o.last_at or o.ts)}'
            + (f" · confirmed {e(o.confirmed)}" if o.confirmed else "") + "</p>"
            f'{_tag_links(base, o.hashtags)}</li>')


def home(base: str, instance: str) -> str:
    from . import indexes
    rows = [x for x in indexes.summary() if x["wissen"]][:24]
    cards = "".join(f'<div class="card"><h3><a href="{e(base)}/i/{e(x["index"])}">{e(x["index"])}</a></h3>'
                    f'<p class="meta">{e(x["art"])} · {x["wissen"]} knowledge'
                    + (f' · {x["code"]} code pieces' if x["code"] else "") + "</p>"
                    + (f'<p>{e(x["beschreibung"])}</p>' if x.get("beschreibung") else "") + "</div>" for x in rows)
    with g.lock:
        ids = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE art IN ('erkenntnis', 'regel', 'skill') AND sicht <> 'privat' AND modus NOT IN ('quarantaene', 'widerlegt') "
            "ORDER BY zeit DESC LIMIT 12")]
    recent = "".join(_hit(base, o) for o in g.load_many(ids).values() if _visible(o) is None)
    body = (f'<div class="hero"><h1>What does the memory know?</h1><form class="search" action="{e(base)}/suche" method="get" role="search">'
            f'<input name="q" placeholder="e.g. deploy vi-mcp, backup database, host:… thema:…" aria-label="Search" autofocus>'
            f'<button type="submit">Search</button></form><p class="muted">Full text and meaning, like vi_recall: words, '
            f'<code>kind:value</code>, <code>!kind:value</code>, <code>(a OR b)</code>.</p></div>'
            f'<h2>Indexes</h2><div class="cards">{cards or "<p class=muted>no indexes with knowledge</p>"}</div>'
            f'<h2>Recently learned</h2><ul class="list">{recent or "<li class=muted>nothing yet</li>"}</ul>')
    return _page(base, "Overview", body, instance)


def search_page(base: str, instance: str, q: str, index: str = "") -> tuple[str, int]:
    """The search page and the number of hits shown."""
    from . import indexes, tools
    q = q.strip()
    try:
        only = indexes.normalize(index) if index else None
    except ValueError:
        only = None
    t0 = time.monotonic()
    t_inst, t_idx = g.current_instance.set(instance), g.search_index.set(only)
    try:
        hits, notes, _kind = tools.search({"filter": q, "limit": PAGE_HITS}, only, None)
    except tools.Rejected as ex:
        hits, notes = [], f"{q} · {ex}"
    finally:
        g.search_index.reset(t_idx)
        g.current_instance.reset(t_inst)
    shown, held = [], {}
    for _s, o, _w in hits:
        why = _visible(o)
        if why is None:
            shown.append(o)
        else:
            held[why] = held.get(why, 0) + 1
    ms = int((time.monotonic() - t0) * 1000)
    how = notes[len(q):].strip(" ·") if notes.startswith(q) else notes
    body = (f'<h1>{len(shown)} result{"" if len(shown) == 1 else "s"} for “{e(q)}”</h1>'
            f'<p class="meta">{e(how) or "full text"} · {ms} ms' + (f' · only index {e(only)}' if only else "")
            + ("".join(f" · {n} not shown ({e(k)})" for k, n in held.items())) + "</p>"
            f'<ul class="list">{"".join(_hit(base, o) for o in shown) or _empty(base, instance, q)}</ul>')
    from . import usage_stats  # counted like a tool call: instance, duration, number and kind of hits; the query is parsed, never stored
    usage_stats.record(instance, "web-intern", "web_search", "ok", ms, f"{len(shown)} objects for “{notes}”")
    return _page(base, f"Search: {q}", body, instance, q), len(shown)


def _empty(base: str, instance: str, q: str) -> str:
    """Why nothing was found — the same answer as vi_recall gives (vocabulary.empty_reason)."""
    from . import vocabulary
    reason, unknown = vocabulary.empty_reason(q, instance)
    if reason == "unbekannt" and unknown:
        items = "".join(f"<li>{e(t)} is not in memory" + (" — did you mean " + ", ".join(f'<a href="{e(base)}/suche?q={urllib.parse.quote(x)}">{e(x)}</a>' for x in sug) + "?" if sug else "")
                        + "</li>" for t, sug in unknown[:5])
        return f'<li class="muted">Nothing is known about this. <ul>{items}</ul> <a href="{e(base)}/w">Words</a> lists what exists.</li>'
    if reason == "unbekannt":
        return f'<li class="muted">None of these words occurs in memory. <a href="{e(base)}/w">Words</a> lists what exists.</li>'
    return '<li class="muted">The words are known, but no entry carries them together — fewer words, or OR, find more.</li>'


def _gold_form(base: str, o: g.MemoryObject) -> str:
    """0.62.0: for people (instances with human: true) — the gold label of this object (classify.set_gold)."""
    from . import classify
    cur = o.data.get("gold") or {}
    lab = o.data.get("klasse") or {}
    opt = lambda vals, sel: "".join(f'<option value="{v}"{" selected" if v == sel else ""}>{v}</option>' for v in vals)  # noqa: E731
    return (f'<h2>Gold label</h2><p class="muted">Which question does this answer, what kind of memory is it? Your label is the gold '
            f'the language model is measured against' + (f' (model said {e(lab.get("answers"))}/{e(lab.get("memory"))})' if lab else "") + ".</p>"
            f'<form class="inline-form" action="{e(base)}/o/{urllib.parse.quote(o.id, safe=":")}/gold" method="post">'
            f'<select name="answers" aria-label="answers">{opt(classify.ANSWERS + ("none",), cur.get("answers"))}</select> '
            f'<select name="memory" aria-label="memory">{opt(classify.MEMORY, cur.get("memory"))}</select> '
            f'<button class="btn" type="submit">Save gold label</button></form>'
            + (f'<p class="meta">gold set by {e(cur["wer"])} on {when(cur["zeit"])}</p>' if cur else ""))


def object_page(base: str, instance: str, oid: str, human: bool = False) -> str | None:
    from . import bandit, net_score
    o = g.load(oid)
    if _visible(o) is not None or (o.visibility == "intern" and instance == "offen"):
        return None
    yes, no = bandit.counter(o)
    facts = [("kind", e(o.kind)), ("index", f'<a href="{e(base)}/i/{e(o.idx)}">{e(o.idx)}</a>'), ("author", e(o.instance or "—")),
             ("visibility", e(o.visibility)), ("state", e(o.mode) + (' <span class="refuted">refuted — do not rely on it</span>' if o.mode == "widerlegt" else "")),
             ("learned", when(o.ts)), ("last used", when(o.last_at)), ("importance", e(o.importance)),
             ("source", _inline(str(o.data.get("quelle") or "—"))),
             ("measured", f"shown {bandit.shown(o)}× · helped {yes:g} · did not help {no:g} · confirmed by "
                          f"{len(o.data.get('bestaetigt_von') or {})} · refuted by {len(o.data.get('widerlegt_von') or {})}")]
    line = net_score.line(o)
    if line:
        facts.append(("network", e(line)))
    hist = "".join(f"<tr><td>{when(c.get('zeit'))}</td><td>{e(c.get('wer'))}</td><td>{e(c.get('was'))}</td><td>{e(c.get('grund'))}</td></tr>"
                   for c in reversed(o.changes[-15:]))
    rel_ids = [b for b, _r in o.edges()][:40]
    rel = [x for x in g.load_many(rel_ids).values() if _visible(x) is None][:10]
    body = (f'<p class="meta"><span class="kind">{e(o.kind)}</span>{e(o.id)}</p><h1>{e(o.text)}</h1>'
            f'<div class="prose">{render_text(str(o.data.get("inhalt") or "")) or "<p class=muted>no further content</p>"}</div>'
            f'{_tag_links(base, o.hashtags)}<h2>Facts</h2><dl class="facts">'
            + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts) + "</dl>"
            + (f'<h2>Related</h2><ul class="list">{"".join(_hit(base, x) for x in rel)}</ul>' if rel else "")
            + (f'<h2>History</h2><div class="table-wrap"><table><tr><th>when</th><th>who</th><th>what</th><th>reason</th></tr>{hist}</table></div>' if hist else "")
            + (_gold_form(base, o) if human and o.kind in ("erkenntnis", "regel", "skill") else ""))
    return _page(base, o.text[:80], body, instance)


def index_page(base: str, instance: str, name: str) -> str | None:
    from . import index_transfer, indexes
    try:
        n = indexes.normalize(name)
    except ValueError:
        return None
    x = next((r for r in indexes.summary() if r["index"] == n), None)
    if x is None:
        return None
    with g.lock:
        ids = [r[0] for r in g.db().execute(
            "SELECT id FROM objekt WHERE idx = ? AND art IN ('erkenntnis', 'regel', 'skill', 'suche') AND sicht <> 'privat' "
            "AND modus <> 'quarantaene' ORDER BY zuletzt DESC LIMIT 50", (n,))]
    items = [o for o in g.load_many(ids).values() if _visible(o) is None]
    extra = " ".join(z.strip() for z in index_transfer.lines(n))
    body = (f'<p class="meta"><span class="kind">{e(x["art"])}</span>index</p><h1>{e(n)}</h1>'
            + (f'<p>{e(x["beschreibung"])}</p>' if x.get("beschreibung") else "")
            + f'<p class="meta">{x["wissen"]} knowledge · {x["erfahrungen"]} experiences · {x["code"]} code pieces · own model {e(x["modell"])}'
            + (f' · tags {e(", ".join(x["tags"]))}' if x.get("tags") else "") + "</p>"
            + (f'<p class="meta">{e(extra)}</p>' if extra else "")
            + f'<form class="search" action="{e(base)}/suche" method="get"><input type="hidden" name="index" value="{e(n)}">'
            f'<input name="q" placeholder="Search in {e(n)}" aria-label="Search in this index"><button type="submit">Search</button></form>'
            f'<h2>Recently used</h2><ul class="list">{"".join(_hit(base, o) for o in items) or "<li class=muted>nothing</li>"}</ul>')
    return _page(base, f"Index {n}", body, instance)


# ── routing ─────────────────────────────────────────────────────────────────

def handle(method: str, raw_path: str, headers, body: bytes, client: str, k) -> tuple[int, str, bytes, dict]:
    """(status, content type, body, headers) for a request under /intern. `k`: the server configuration (instances, origins, base)."""
    base = k.web_internal_base
    html_type = "text/html; charset=utf-8"
    if _limited(client):
        return 429, "text/plain; charset=utf-8", b"too many requests", {"Retry-After": "60"}
    u = urllib.parse.urlsplit(raw_path)
    path = u.path[len(BASE):] if u.path.startswith(BASE) else u.path
    if path == "/stil.css":
        return 200, "text/css; charset=utf-8", (CSS + EXTRA_CSS).encode(), {**SECURITY_HEADERS, "Cache-Control": "public, max-age=3600"}
    if method == "POST" and path == "/login":
        if not _same_site(headers, k.origins):
            return 403, html_type, _login_page(base, "This sign-in form was sent from another site.").encode(), HEADERS
        token = (urllib.parse.parse_qs(body.decode("utf-8", "replace")).get("token") or [""])[0].strip()
        from . import config
        inst = k.instance_for(token) if token else None
        if inst is None or inst.name == config.OPEN:
            return 401, html_type, _login_page(base, "This token belongs to no instance of this server.").encode(), HEADERS
        sid = _new_session(inst.name)
        return 303, html_type, b"", {**HEADERS, "Location": f"{base}/", "Set-Cookie": _cookie(base, sid, SESSION_S)}
    if method == "POST" and path.startswith("/o/") and path.endswith("/gold"):  # 0.62.0: a person's gold label
        inst = _instance(headers.get("Cookie"))
        if inst is None:
            return 401, html_type, _login_page(base, "Sign in first.").encode(), HEADERS
        if not _same_site(headers, k.origins):
            return 403, "text/plain; charset=utf-8", b"cross-site request", HEADERS
        from . import classify
        form = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        oid = urllib.parse.unquote(path[3:-5])
        i = k.instances.get(inst)
        try:
            classify.set_gold(oid, (form.get("answers") or [""])[0], (form.get("memory") or [""])[0], inst, bool(i and i.human))
        except ValueError as ex:
            return 403, html_type, _page(base, "Not saved", f'<h1>Not saved</h1><p class="error">{e(ex)}</p>', inst).encode(), HEADERS
        return 303, html_type, b"", {**HEADERS, "Location": f"{base}/o/{urllib.parse.quote(oid, safe=':')}"}
    if method == "POST" and path == "/logout":
        if not _same_site(headers, k.origins):
            return 403, "text/plain; charset=utf-8", b"cross-site request", HEADERS
        for part in (headers.get("Cookie") or "").split(";"):
            key, _, v = part.strip().partition("=")
            if key == COOKIE:
                with _lock:
                    _sessions.pop(v, None)
        return 303, html_type, b"", {**HEADERS, "Location": f"{base}/", "Set-Cookie": _cookie(base, "", 0)}
    if method != "GET":
        return 405, "text/plain; charset=utf-8", b"read only", {"Allow": "GET"}
    instance = _instance(headers.get("Cookie"))
    if instance is None:
        return 200, html_type, _login_page(base).encode(), HEADERS
    qs = urllib.parse.parse_qs(u.query)
    one = lambda key: (qs.get(key) or [""])[0][:300]  # noqa: E731
    parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/") if p]
    out = None
    if not parts:
        out = home(base, instance)
    elif parts == ["suche"]:
        out = search_page(base, instance, one("q"), one("index"))[0] if one("q").strip() else home(base, instance)
    elif parts[0] == "o" and len(parts) == 2:
        i = k.instances.get(instance)
        out = object_page(base, instance, parts[1], bool(i and i.human))
    elif parts[0] == "i" and len(parts) == 2:
        out = index_page(base, instance, parts[1])
    elif parts == ["w"] or (parts[0] == "w" and len(parts) == 2):
        out = words_page(base, instance, parts[1] if len(parts) == 2 else "")
    if out is None:
        return 404, html_type, _page(base, "Not found", '<h1>Not found</h1><p class="muted">Not here, or not shown on this page '
                                                         '(private, in quarantine, or not knowledge).</p>', instance).encode(), HEADERS
    return 200, html_type, out.encode(), HEADERS
