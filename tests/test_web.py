"""0.46.0: the read-only web page — only free and open networks, nothing internal, no local instance names, everything escaped."""
import hashlib
import http.client
import json
import threading

import pytest

pytest.importorskip("cryptography")

from vi_mcp import config, forum, logbook as lb, p2p, server, web, wiki  # noqa: E402
from vi_mcp import memory as g  # noqa: E402

from test_p2p import _key  # noqa: E402

LOCAL = "secret-laptop-7"  # a local instance name: must never appear on a page


@pytest.fixture()
def site(gd, monkeypatch):
    monkeypatch.setattr(p2p, "config", {"netze": {"welt": {"art": "frei", "instanz": "netz-welt"}, "firma": {"art": "firma", "instanz": "netz-firma"}}})
    monkeypatch.setattr(web, "_counter", {})
    monkeypatch.setattr(web, "_own_cache", {})
    p2p.generate_token(LOCAL)
    wiki.write(LOCAL, "welt", "backup/borg", "Restore a borg archive.\n\n```\nborg extract repo::archive path\n```\n\n<script>alert(1)</script>", None, title="Borg restore")
    wiki.write(LOCAL, "firma", "intern/db", "db01 backups run at 02:00 via borg to the NAS.", None, title="Company backup page")
    forum.ask(LOCAL, "welt", "How do you restore a single file from a borg archive?", ["tool:borg"], "user question 11.11.2026")
    k, _ = _key()
    pk = k.public_key().public_bytes_raw().hex()
    for net, vis, mode, text in (("welt", None, "test", "Borg compact frees space only after prune"), ("firma", "intern", "test", "Firma borg import internal"),
                                 ("welt", None, "quarantaene", "Borg quarantined claim not yet reviewed")):
        name = lb.pseudonym(pk)
        g.new_object("erkenntnis", text, ["tool:borg", "herkunft:p2p", f"herausgeber:{name}", f"netz:{net}"],
                     {"quelle": "other server", "herkunft": {"herausgeber": name, "pubkey": pk, "netz": net, "netz_id": hashlib.md5(text.encode()).hexdigest()},
                      "pruefung": {"regeln": [], "pruefer": None}}, instance=f"p2p-{name}", mode=mode, visibility=vis,
                     oid=f"erkenntnis:p2p-{name}-{hashlib.md5(text.encode()).hexdigest()[:16]}")
    own = g.new_object("erkenntnis", f"Borg needs BORG_PASSCOMMAND for unattended runs, noted by {LOCAL}", ["tool:borg"], {"quelle": "own test"}, instance=LOCAL)
    own.confirm("ki@other", "worked", "other", family="gpt")
    internal = g.new_object("erkenntnis", "Borg internal runbook for the NAS cluster", ["tool:borg"], {"quelle": "own"}, instance=LOCAL, visibility="intern")
    internal.confirm("ki@other", "worked", "other", family="gpt")


def get(path):
    code, ctype, body, headers = web.handle(path, "203.0.113.5")
    return code, body.decode(), headers


def test_home_and_networks(site):
    code, body, h = get("/web/")
    assert code == 200 and "welt" in body and "firma" not in body and "Content-Security-Policy" in h and "script-src" not in h["Content-Security-Policy"]
    assert "Borg restore" in body  # recently
    assert get("/web/netze")[0] == 200
    code, css, h = get("/web/stil.css")
    assert code == 200 and "--accent" in css


def test_wiki_pages_escaped_and_only_public(site):
    code, body, _ = get("/web/wiki/welt/backup/borg")
    assert code == 200 and "borg extract repo::archive path" in body and "<pre><code>" in body
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body
    assert LOCAL not in body and "this server" in body
    assert get("/web/wiki/firma/intern/db")[0] == 404 and get("/web/wiki/firma")[0] == 404
    code, hist, _ = get("/web/wiki/welt/backup/borg?verlauf=1")
    assert code == 200 and "History" in hist and LOCAL not in hist


def test_forum_shows_pseudonyms_not_instances(site):
    code, body, _ = get("/web/forum/welt")
    assert code == 200 and "How do you restore a single file" in body and LOCAL not in body and "ki-" in body
    tid = body.split("/web/forum/welt/")[1].split('"')[0]
    code, thread, _ = get(f"/web/forum/welt/{tid}")
    assert code == 200 and "0 answer(s)" in thread and LOCAL not in thread


def test_knowledge_only_released_public_and_anonymised(site):
    code, body, _ = get("/web/wissen/welt")
    assert code == 200 and "Borg compact frees space only after prune" in body
    assert "quarantined claim" not in body and "Firma borg import" not in body and "internal runbook" not in body
    assert "BORG_PASSCOMMAND" in body and LOCAL not in body  # own knowledge only in its anonymised network form
    oid = [o.id for _s, o, _g in g.recall("compact prune", viewer=None)][0]
    assert get(f"/web/eintrag/{oid}")[0] == 200
    internal_import = [o.id for _s, o, _g in g.recall("Firma borg import", viewer=None)][0]
    assert get(f"/web/eintrag/{internal_import}")[0] == 404


def test_search(site):
    code, body, _ = get("/web/suche?q=borg")
    assert code == 200 and "Borg restore" in body and "How do you restore" in body and "compact frees space" in body and "BORG_PASSCOMMAND" in body
    for hidden in ("Company backup page", "Firma borg import", "quarantined claim", "internal runbook", LOCAL):
        assert hidden not in body
    assert "needs words" in get("/web/suche?q=a")[1]
    code, only_wiki, _ = get("/web/suche?q=borg&art=wiki")
    assert "Borg restore" in only_wiki and "compact frees" not in only_wiki


def test_rate_limit_and_unknown(site, monkeypatch):
    monkeypatch.setattr(web, "REQUESTS_PER_MIN", 3)
    assert [web.handle("/web/", "198.51.100.9")[0] for _ in range(4)] == [200, 200, 200, 429]
    assert get("/web/nichts/da")[0] == 404


def test_render_text_links_and_conflicts():
    out = web.render_text("See https://example.org/doc and javascript:alert(1)\n\n<<<<<<< aaa\nA\n=======\nB\n>>>>>>> bbb")
    assert 'href="https://example.org/doc" rel="nofollow noopener noreferrer"' in out and "javascript:alert" in out and 'href="javascript' not in out
    assert 'class="conflict"' in out and "revision aaa" in out


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    def start(on):
        cfg = tmp_path / f"c{on}.json"
        monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
        config.create_instance("anna")
        raw = json.loads(cfg.read_text())
        raw.update({"port": 0, "db": str(tmp_path / "vi.db"), "web": on, "web_basis": "/vi-mcp/web"})
        cfg.write_text(json.dumps(raw))
        (s,) = server.build(config.load())
        threading.Thread(target=s.serve_forever, daemon=True).start()
        started.append(s)
        return s.server_address[1]
    started = []
    yield start
    for s in started:
        s.shutdown()
        s.server_close()
        server.finish([s])


def test_server_serves_it_only_when_switched_on(srv):
    port = srv(True)
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/web/")
    r = c.getresponse()
    body = r.read().decode()
    assert r.status == 200 and 'href="/vi-mcp/web/stil.css"' in body and r.getheader("Content-Security-Policy")
    c.close()


def test_server_without_web_says_404(srv):
    port = srv(False)
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/web/")
    assert c.getresponse().status == 404
    c.close()
