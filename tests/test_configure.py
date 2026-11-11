"""0.48.0: configuring after installation — one catalogue for debconf (Debian) and the ANSI menu (RPM), unattended via VI_MCP_<KEY>."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vi_mcp import config, configure, net_cli, setup

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"bind": "127.0.0.1", "port": 8765, "db": str(tmp_path / "vi.db"), "instanzen": {}}))
    monkeypatch.setenv("VI_MCP_CONFIG", str(p))
    monkeypatch.setenv("VI_P2P_DIR", str(tmp_path / "p2p"))
    monkeypatch.setattr(configure, "STATE", tmp_path / "configure.json")
    monkeypatch.setattr(configure, "TOKEN_DIR", tmp_path)
    calls = {"net": [], "restart": 0}
    monkeypatch.setattr(net_cli, "main", lambda argv: calls["net"].append(argv) or 0)

    def restart():
        calls["restart"] += 1
    monkeypatch.setattr(setup, "_restart", restart)
    for k in list(os.environ):
        if k.startswith("VI_MCP_") and k not in ("VI_MCP_CONFIG",):
            monkeypatch.delenv(k)
    return p, calls


def test_catalogue_is_complete_and_named():
    keys = [q.key for q in configure.QUESTIONS]
    assert len(keys) == len(set(keys))
    assert {"port", "bind", "open", "wiki", "net_name", "web", "web_base", "instance", "llm_url", "reviewer_prompt", "embed_url"} <= set(keys)
    assert configure.BY_KEY["port"].env == "VI_MCP_PORT" and configure.BY_KEY["net_start"].env == "VI_MCP_NET_START"


def test_env_answers_like_an_unattended_agent_install():
    env = {"VI_MCP_PORT": "9000", "VI_MCP_WIKI": "no", "VI_MCP_WEB": "1", "VI_MCP_INSTANCE": "max", "VI_MCP_OPEN": "ja", "OTHER": "x"}
    assert configure.env_answers(env) == {"port": "9000", "wiki": "false", "web": "true", "instance": "max", "open": "true"}
    assert configure.env_answers({"VI_MCP_KEIN_WIKI": "1"}) == {"wiki": "false"}


def test_validate_names_the_reason():
    bad = configure.validate({"port": "80", "bind": "localhost", "wiki": "vielleicht", "net_kind": "geheim", "web_base": "web", "llm_url": "ftp://x"})
    assert set(bad) == {"port", "bind", "wiki", "net_kind", "web_base", "llm_url"}
    assert configure.validate({"port": "9000", "bind": "127.0.0.1,172.19.0.1", "net_start": "vinetz1.abc"}) == {}


def test_apply_changes_only_what_differs_and_restarts_once(cfg):
    p, calls = cfg
    assert configure.apply({"port": "8765", "bind": "127.0.0.1"}) == ["nothing changed"] and calls["restart"] == 0
    done = configure.apply({"port": "9000", "bind": "127.0.0.1,172.19.0.1", "open": "true", "web": "true", "web_base": "/vi-mcp/web",
                            "llm_url": "http://127.0.0.1:8080/v1/chat/completions", "llm_model": "qwen", "embed_url": "http://127.0.0.1:8081/v1/embeddings",
                            "reviewer_prompt": "/etc/vi-mcp/pruefer.txt"})
    raw = json.loads(p.read_text())
    assert raw["port"] == 9000 and raw["bind"] == ["127.0.0.1", "172.19.0.1"] and raw["offen"] is True and raw["web"] is True
    assert raw["web_basis"] == "/vi-mcp/web" and raw["llm"] == {"url": "http://127.0.0.1:8080/v1/chat/completions", "modell": "qwen"}
    assert raw["embed"]["url"].endswith("/embeddings") and raw["pruefer_prompt"] == "/etc/vi-mcp/pruefer.txt"
    assert calls["restart"] == 1 and "service restarted" in done and "port 8765 → 9000" in done
    with pytest.raises(ValueError, match="port"):
        configure.apply({"port": "80"})


def test_new_instance_token_goes_to_a_root_file_never_to_the_screen(cfg, capsys):
    p, _ = cfg
    done = configure.apply({"instance": "max", "instance_family": "claude"})
    tf = configure.TOKEN_DIR / "vi-mcp-token-max"
    token = tf.read_text().strip()
    assert oct(tf.stat().st_mode)[-3:] == "600" and token not in " ".join(done) and token not in capsys.readouterr().out
    raw = json.loads(p.read_text())
    assert raw["instanzen"]["max"]["familie"] == "claude" and config.load().instance_for(token).name == "max"
    assert "not renewed" in " ".join(configure.apply({"instance": "max"}))  # a second run never locks max out
    assert tf.read_text().strip() == token


def test_wiki_and_networks_through_net_cli(cfg):
    _, calls = cfg
    configure.apply({"wiki": "true"})
    configure.apply({"net_name": "firma", "net_kind": "firma", "net_mode": "peerhost", "net_public": "https://h.example", "net_start": ""})
    configure.apply({"net_name": "welt", "net_kind": "frei", "net_mode": "peer", "net_start": "https://vi-wiki.org/vi-p2p/welt"})
    configure.apply({"net_name": "zu", "net_kind": "offen", "net_mode": "peer", "net_start": "vinetz1.CODE"})
    assert calls["net"] == [["wiki", "on"],
                            ["--network", "firma", "setup", "--kind", "firma", "--mode", "peerhost", "--public", "https://h.example", "--found"],
                            ["--network", "welt", "setup", "--kind", "frei", "--mode", "peer", "--start", "https://vi-wiki.org/vi-p2p/welt"],
                            ["--network", "zu", "join", "vinetz1.CODE", "--mode", "peer", "--kind", "offen"]]


def test_package_first_install_without_terminal_takes_env_then_defaults(cfg, monkeypatch):
    p, calls = cfg
    monkeypatch.setenv("VI_MCP_PORT", "9100")
    monkeypatch.setenv("VI_MCP_WEB", "yes")
    assert configure.main(["--package", "first"]) == 0
    raw = json.loads(p.read_text())
    assert raw["port"] == 9100 and raw["web"] is True
    assert ["wiki", "on"] in calls["net"]  # the default of a new installation
    assert configure.unanswered() == [q for q in configure.QUESTIONS if q.once]


def test_package_upgrade_of_a_server_configured_before_048_asks_nothing_and_never_joins(cfg):
    _, calls = cfg
    assert configure.main(["--package", "upgrade"]) == 0
    assert calls["net"] == [] and configure.unanswered() == []


def test_menu_logic():
    items = [configure.BY_KEY["wiki"], configure.BY_KEY["net_kind"], configure.BY_KEY["port"], None]
    v = {"wiki": "true", "net_kind": "firma", "port": "8765"}
    assert configure.step(v, items, 0, "enter")[1] is None and v["wiki"] == "false"
    configure.step(v, items, 1, "enter")
    assert v["net_kind"] == "frei"
    configure.step(v, items, 2, "enter", read_line=lambda prompt: "9000")
    assert v["port"] == "9000"
    assert configure.step(v, items, 3, "enter")[1] == "apply" and configure.step(v, items, 0, "esc")[1] == "quit"
    assert configure.step(v, items, 0, "down")[0] == 1 and configure.step(v, items, 0, "up")[0] == 0
    screen = configure.render(v, 2, items)
    assert "Join the public wiki network vi-wiki.org" in screen and "Port of the VI server" in screen and "[ Apply ]" in screen


def test_debconf_files_are_generated_and_valid(tmp_path):
    t = configure.debconf_templates()
    for q in configure.QUESTIONS:
        assert f"Template: vi-mcp/{q.key}\n" in t
    assert "Choices: frei, offen, firma" in t
    c = configure.debconf_config()
    for q in configure.QUESTIONS:
        assert f"db_input {q.priority} vi-mcp/{q.key}" in c and f'if [ -n "${{{q.env}+x}}" ]' in c
    f = tmp_path / "config"
    f.write_text(c)
    assert subprocess.run(["sh", "-n", str(f)]).returncode == 0
    assert configure.debconf_answers({"port": "9000", "net_name": "", "net_kind": "firma", "instance": "", "instance_family": "claude"}) == {"port": "9000"}


def test_apply_pairs_from_postinst(cfg, tmp_path):
    p, _ = cfg
    f = tmp_path / "answers"
    f.write_text("port 9200\nwiki false\nnet_name \nnet_kind firma\ninstance \nweb_base /web\n")
    assert configure.main(["--apply-pairs", str(f)]) == 0
    assert json.loads(p.read_text())["port"] == 9200


def test_cli_entry_and_package_files():
    r = subprocess.run([sys.executable, "-m", "vi_mcp", "configure", "--debconf-templates"], capture_output=True, text=True, cwd=ROOT,
                       env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0 and "Template: vi-mcp/wiki" in r.stdout
    build = (ROOT / "deploy/debian/build.sh").read_text()
    assert "--debconf-templates" in build and "--debconf-config" in build and "debconf" in build
    post = (ROOT / "deploy/debian/postinst").read_text()
    assert ". /usr/share/debconf/confmodule" in post and "db_stop" in post and post.index("db_stop") < post.index("configure --apply-pairs")
    assert "db_purge" in (ROOT / "deploy/debian/postrm").read_text()
