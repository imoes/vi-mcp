"""0.47.0: the public wiki network vi-wiki.org — joined on a new installation, switchable by the AI on the user's request, named in the
instructions."""
import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from vi_mcp import config, net_cli, net_service as nd, p2p, server, tools, web  # noqa: E402
from vi_mcp import memory as g  # noqa: E402

from test_netz import mem_object, net  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def wnet(gd, monkeypatch):
    monkeypatch.setattr(p2p, "config", {"netze": {"wiki": {"art": "frei", "instanz": "netz-wiki"}}})
    p2p.generate_token("a")
    o = g.new_object("erkenntnis", "Borg needs BORG_PASSCOMMAND for unattended runs", ["tool:borg"], {"quelle": "test 11.11.2026"}, instance="a")
    o.confirm("ki@b", "worked", "b", family="gpt")


def test_defaults():
    assert p2p.WIKI_START == "https://vi-wiki.org/vi-p2p/wiki" and p2p.WIKI_NET == "wiki"


def test_switch_off_stops_out_and_in_and_on_again(wnet):
    assert p2p.is_on("wiki") and p2p.outbox("wiki")["objekte"]
    out = tools.call_tool("vi_net_switch", {"network": "wiki", "on": False, "reason": "the user does not want to share"}, "a", False)
    assert "is off" in out and not p2p.is_on("wiki")
    ob = p2p.outbox("wiki")
    assert ob["aus"] and ob["objekte"] == [] and ob["seiten"] == [] and ob["beitraege"] == []
    assert p2p.inbox([{"kopf": {}, "inhalt": {}}], in_background=False, net="wiki")["aus"]
    assert p2p.answer_search("wiki", "borg") == []
    with pytest.raises(tools.Rejected, match="switched off"):
        tools.call_tool("vi_net_search", {"query": "borg", "network": "wiki"}, "a", False)
    st = p2p.status()["netze"]["wiki"]
    assert st["an"] is False and st["schalter"]["wer"] == "ki@a" and "does not want" in st["schalter"]["grund"]
    assert "is on" in tools.call_tool("vi_net_switch", {"network": "wiki", "on": True, "reason": "the user wants it back"}, "a", False)
    assert p2p.outbox("wiki")["objekte"]


def test_switch_rules(wnet):
    with pytest.raises(tools.Rejected, match="token"):
        tools.call_tool("vi_net_switch", {"network": "wiki", "on": False, "reason": "x"}, "offen", False)
    with pytest.raises(tools.Rejected, match="reason"):
        tools.call_tool("vi_net_switch", {"network": "wiki", "on": False, "reason": " "}, "a", False)
    with pytest.raises(tools.Rejected, match="unknown network"):
        tools.call_tool("vi_net_switch", {"network": "nix", "on": False, "reason": "x"}, "a", False)


def test_notice_names_the_wiki_network_and_disappears_when_off(wnet):
    n = p2p.notice()
    assert "wiki (frei, vi-wiki.org)" in n and "vi_net_switch" in n
    p2p.switch("wiki", False, "ki@a", "test")
    assert p2p.notice() == ""


def test_web_hides_a_switched_off_network(wnet):
    assert "wiki" in web.public_nets()
    p2p.switch("wiki", False, "ki@a", "test")
    assert "wiki" not in web.public_nets()


def test_service_pauses_when_switched_off(net):
    seed, _ = net.key_()
    a = net.build(seed, [], kind="frei", net="wiki", pow_bits=8, private_ok=True)

    class Off:
        def outbox(self, state=None):
            return {"aus": True, "objekte": [], "widerrufe": []}

        def inbox(self, e):
            raise AssertionError("no inbox while switched off")
    a.mcp = Off()
    assert a.run_round() == 0 and a.paused and a.usage_stats["pausiert"] == 1 and a.snapshot()["pausiert"]


def test_instructions_carry_the_notice(tmp_path, monkeypatch):
    import threading
    from test_http import request
    cfg = tmp_path / "c.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    tok = config.create_instance("anna")
    raw = json.loads(cfg.read_text())
    raw.update({"port": 0, "db": str(tmp_path / "vi.db"), "p2p": {"netze": {"wiki": {"art": "frei", "instanz": "netz-wiki"}}}})
    cfg.write_text(json.dumps(raw))
    (s,) = server.build(config.load())
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        _, _, a = request(s.server_address[1], "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "t"}}}, tok)
        assert "[Network] This server takes part in the public network(s) wiki (frei, vi-wiki.org)" in a["result"]["instructions"]
    finally:
        s.shutdown()
        s.server_close()
        server.finish([s])


def test_cli_wiki_on_sets_up_the_free_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VI_MCP_KEIN_DIENST", "1")
    token = tmp_path / "tok"
    token.write_text("t\n")
    monkeypatch.setenv("VI_P2P_CONFIG", str(tmp_path / "wiki.json"))
    (tmp_path / "wiki.json").write_text(json.dumps({"db": str(tmp_path / "w" / "netz.db"), "seed": str(tmp_path / "w" / "schluessel"), "mcp_token_datei": str(token)}))
    assert net_cli.main(["wiki", "on"]) == 0
    raw = json.loads((tmp_path / "wiki.json").read_text())
    assert raw["art"] == "frei" and raw["netz"] == "wiki" and raw["modus"] == "peer" and raw["startpeers"] == ["https://vi-wiki.org/vi-p2p/wiki"]
    assert nd.load(tmp_path / "wiki.json").kind == "frei"
    assert net_cli.main(["wiki", "status"]) == 0 and "configured" in capsys.readouterr().out


def test_install_scripts_join_on_new_installations_only():
    # 0.48.0: Debian asks through debconf (question vi-mcp/wiki, default true, false on an update); RPM through vi-mcp configure --package
    post = (ROOT / "deploy/debian/postinst").read_text()
    assert "configure --apply-pairs" in post and "db_get" in post
    spec = (ROOT / "deploy/rpm/vi-mcp.spec").read_text()
    assert ".erstinstallation" in spec and "configure --package first" in spec and "configure --package upgrade" in spec
    sh = (ROOT / "deploy/nach-installation.sh").read_text()
    assert "VI_MCP_KEIN_WIKI" in sh and "vi-mcp net wiki on" in sh and "[ ! -e /etc/vi-p2p/wiki.json ]" in sh
    r = subprocess.run(["sh", "-n", str(ROOT / "deploy/nach-installation.sh")], capture_output=True)
    assert r.returncode == 0, r.stderr
