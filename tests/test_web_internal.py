"""0.62.0: the internal knowledge search in the browser — sign-in with a VI token, shared and internal knowledge, never private."""
import hashlib
import re

import pytest

from vi_mcp import config, web, web_internal as wi
from vi_mcp import memory as g

TOKEN = "s3cret-token-for-alice"


class Headers(dict):
    def get(self, k, default=None):
        return super().get(k, default)


@pytest.fixture()
def k(gd):
    c = config.Config()
    c.instances = {"alice": config.Instance("alice", hashlib.sha256(TOKEN.encode()).hexdigest())}
    c.web_internal, c.web_internal_base = True, "/vi-mcp/intern"
    wi._sessions.clear()
    web._counter.clear()
    return c


def req(k, path, method="GET", body=b"", cookie=None, origin=None, host="vi.example"):
    h = Headers(Host=host)
    if cookie:
        h["Cookie"] = cookie
    if origin:
        h["Origin"] = origin
    return wi.handle(method, path, h, body, "10.0.0.9", k)


def login(k):
    code, _t, _b, hd = req(k, "/intern/login", "POST", f"token={TOKEN}".encode(), origin="https://vi.example")
    assert code == 303
    return hd["Set-Cookie"].split(";")[0]


def test_without_a_session_only_the_sign_in_form(k):
    g.new_object("erkenntnis", "deploy vi-mcp: back up the database first", ["thema:deploy"], {"quelle": "t"}, visibility="intern")
    code, _t, body, hd = req(k, "/intern/suche?q=deploy")
    assert code == 200 and b'name="token"' in body and b"back up the database" not in body and hd["Cache-Control"] == "no-store"


def test_sign_in_wrong_token_cross_site_and_cookie_attributes(k):
    code, _t, body, _h = req(k, "/intern/login", "POST", b"token=wrong", origin="https://vi.example")
    assert code == 401 and b"belongs to no instance" in body
    code, _t, _b, _h = req(k, "/intern/login", "POST", f"token={TOKEN}".encode(), origin="https://evil.example")
    assert code == 403
    assert req(k, "/intern/login", "POST", f"token={TOKEN}".encode(), origin="null")[0] == 403  # sandboxed or opaque origins never sign in
    # the pages must let the browser send its real origin: with no-referrer Chrome sends "null" and nobody could sign in
    assert req(k, "/intern/")[3]["Referrer-Policy"] == "same-origin"
    code, _t, _b, hd = req(k, "/intern/login", "POST", f"token={TOKEN}".encode(), origin="https://vi.example")
    c = hd["Set-Cookie"]
    assert code == 303 and hd["Location"] == "/vi-mcp/intern/"
    for attr in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/vi-mcp/intern", "Max-Age=28800"):
        assert attr in c
    assert TOKEN not in c
    cookie = c.split(";")[0]
    code, _t, _b, hd = req(k, "/intern/logout", "POST", cookie=cookie, origin="https://vi.example")
    assert code == 303 and "Max-Age=0" in hd["Set-Cookie"]
    assert b'name="token"' in req(k, "/intern/", cookie=cookie)[2]  # the session is gone


def test_search_shows_shared_and_internal_never_private_or_quarantine_and_counts_them(k):
    cookie = login(k)
    a = g.new_object("erkenntnis", "deploy vi-mcp: back up the database first", ["thema:deploy"], {"quelle": "t", "inhalt": "cp vi.db vi.db.bak"},
                     visibility="intern", instance="bob")
    b = g.new_object("erkenntnis", "deploy vi-mcp: check health afterwards", ["thema:deploy"], {"quelle": "t"}, visibility="geteilt", instance="bob")
    g.new_object("erkenntnis", "deploy vi-mcp: my private note", ["thema:deploy"], {"quelle": "t"}, visibility="privat", instance="alice")
    g.new_object("erkenntnis", "deploy vi-mcp: imported, not reviewed", ["thema:deploy"], {"quelle": "t"}, mode="quarantaene", visibility="intern")
    with g.lock:
        before = g.db().execute("SELECT zugriffe FROM objekt WHERE id = ?", (a.id,)).fetchone()[0]
    code, _t, body, _h = req(k, "/intern/suche?q=deploy+vi-mcp", cookie=cookie)
    html = body.decode()
    assert code == 200 and a.text in html and b.text in html and html.count('class="hit"') == 2
    assert "my private note" not in html and "not reviewed" not in html
    assert "1 not shown (private)" in html  # alice's own private note is found by the search, not shown, and counted
    with g.lock:
        assert g.db().execute("SELECT zugriffe FROM objekt WHERE id = ?", (a.id,)).fetchone()[0] == before  # reading reinforces nothing
        row = g.db().execute("SELECT instanz, treffer FROM nutzung WHERE werkzeug = 'web_search'").fetchone()
    assert row == ("alice", 2)


def test_article_is_escaped_and_private_is_not_found(k):
    cookie = login(k)
    a = g.new_object("erkenntnis", "XSS probe <script>alert(1)</script>", ["thema:web"], {"quelle": "https://example.org/x", "inhalt": "<img src=x onerror=alert(1)>"},
                     visibility="intern", instance="bob", index="vi-mcp")
    p = g.new_object("erkenntnis", "private thing", ["thema:web"], {"quelle": "t"}, visibility="privat", instance="alice")
    code, _t, body, _h = req(k, f"/intern/o/{a.id}", cookie=cookie)
    html = body.decode()
    assert code == 200 and "<script>alert" not in html and "&lt;script&gt;" in html and "<img src=x" not in html
    assert 'href="/vi-mcp/intern/i/vi-mcp"' in html and 'rel="nofollow noopener noreferrer"' in html
    assert req(k, f"/intern/o/{p.id}", cookie=cookie)[0] == 404
    assert req(k, "/intern/i/vi-mcp", cookie=cookie)[0] == 200
    assert req(k, "/intern/i/nope", cookie=cookie)[0] == 404


def test_public_web_page_still_never_shows_internal_knowledge(k):
    g.new_object("erkenntnis", "internal: the backup path of the database", ["thema:deploy"], {"quelle": "t"}, visibility="intern")
    code, _t, body, _h = web.handle("/web/suche?q=backup", "10.0.0.9")
    assert b"backup path of the database" not in body


def test_home_lists_indexes_and_recent_knowledge(k):
    cookie = login(k)
    g.new_object("erkenntnis", "cue print: restart the render queue", ["thema:cue"], {"quelle": "t"}, visibility="intern", index="cue-print")
    code, _t, body, _h = req(k, "/intern/", cookie=cookie)
    html = body.decode()
    assert code == 200 and "cue-print" in html and "restart the render queue" in html and re.search(r"Sign out \(alice\)", html)


def test_markdown_bold_and_wrapped_list_items_render_and_excerpts_are_plain(k):
    from vi_mcp.web import render_text
    assert render_text("- **Bold start,** text\n  wrapped line\n- next") == \
        "<ul><li><strong>Bold start,</strong> text wrapped line</li><li>next</li></ul>"
    assert render_text("**stays `global`:** text") == "<p><strong>stays <code>global</code>:</strong> text</p>"
    o = g.new_object("erkenntnis", "excerpt probe", ["thema:web"], {"quelle": "t", "inhalt": "### Head\n- **bold** and `code`"}, visibility="intern")
    assert wi._excerpt(o) == "Head bold and code"


def test_words_page_datalist_and_empty_search_reason(k):
    cookie = login(k)
    g.new_object("erkenntnis", "nginx on web1", ["host:web1.example", "tool:nginx"], {"quelle": "t"}, visibility="intern", instance="bob")
    g.new_object("erkenntnis", "secret", ["host:hidden.example"], {"quelle": "t"}, visibility="privat", instance="bob")
    html = req(k, "/intern/w", cookie=cookie)[2].decode()
    assert 'href="/vi-mcp/intern/w/host"' in html and '<datalist id="vocab">' in html and '<option value="host:web1.example">' in html
    assert "hidden.example" not in html  # someone else's private word is no vocabulary
    html = req(k, "/intern/w/host", cookie=cookie)[2].decode()
    assert "host:web1.example (1)" in html and "hidden" not in html
    html = req(k, "/intern/suche?q=host:web2.example", cookie=cookie)[2].decode()
    assert "host:web2.example is not in memory" in html and "did you mean" in html and "host:web1.example" in html
