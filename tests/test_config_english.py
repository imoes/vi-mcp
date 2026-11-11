"""0.51.0: the configuration files speak English (decided by the user, 11.11.2026): keys and network kinds. Older German files keep
working and are rewritten in English at the next package install, with a copy of the old file next to them."""
import json
import os

from vi_mcp import config, configure, net_service as nd

GERMAN = {"port": 8765, "offen": True, "web_basis": "/vi-mcp/web", "pruefer_prompt": "/etc/vi-mcp/p.txt", "lager_tage": {"erfahrung": 30},
          "lokal": {"alice": "anna"},
          "instanzen": {"anna": {"token_sha256": "a" * 64, "reflexe": True, "freigabe": False, "mensch": True, "familie": "claude"}},
          "llm": {"url": "http://127.0.0.1:8080/v1/chat/completions", "modell": "qwen"}, "embed": {"url": "http://127.0.0.1:8081/v1/embeddings", "modell": "bge"},
          "p2p": {"reflexe_von": ["b" * 64], "auto_freigabe": True, "oeffentliche_domains": ["example.org"], "interne_namen": ["acme"],
                  "lokal": {"url": "http://127.0.0.1:9765", "token": "t"},
                  "netze": {"firma": {"art": "firma", "instanz": "netz-firma", "auto_freigabe": True}, "welt": {"art": "frei", "instanz": "netz-welt"}}}}


def test_normalize_translates_every_level_but_never_names():
    new, notes = config.normalize(GERMAN)
    assert new["open"] is True and new["web_base"] == "/vi-mcp/web" and new["reviewer_prompt"] == "/etc/vi-mcp/p.txt" and new["archive_days"] == {"erfahrung": 30}
    assert new["local"] == {"alice": "anna"}  # a user name is a name, not a key
    assert new["instances"]["anna"] == {"token_sha256": "a" * 64, "reflexes": True, "release": False, "human": True, "family": "claude"}
    assert new["llm"]["model"] == "qwen" and new["embed"]["model"] == "bge"
    p = new["p2p"]
    assert p["reflexes_from"] == ["b" * 64] and p["auto_release"] is True and p["public_domains"] == ["example.org"] and p["internal_names"] == ["acme"]
    assert p["networks"] == {"firma": {"kind": "company", "instance": "netz-firma", "auto_release": True}, "welt": {"kind": "free", "instance": "netz-welt"}}
    assert "offen → open" in notes and "p2p.networks.welt.kind frei → free" in notes
    assert config.normalize(new) == (new, [])  # English stays as it is
    both, notes = config.normalize({"offen": False, "open": True})
    assert both == {"open": True} and notes == ["offen dropped (open is set)"]  # named, not silent


def test_a_german_file_still_works_and_migrates_with_a_backup(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(GERMAN))
    os.chmod(p, 0o640)
    monkeypatch.setenv("VI_MCP_CONFIG", str(p))
    k = config.load()
    assert k.open_ and k.web_base == "/vi-mcp/web" and k.instances["anna"].family == "claude" and k.instances["anna"].human
    notes = config.migrate_file(p)
    raw = json.loads(p.read_text())
    assert notes and "instances" in raw and "instanzen" not in raw and raw["p2p"]["networks"]["firma"]["kind"] == "company"
    backups = list(tmp_path.glob("config.json.bak-*-german-keys"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == GERMAN and (os.stat(p).st_mode & 0o777) == 0o640
    assert config.migrate_file(p) == [] and len(list(tmp_path.glob("config.json.bak-*"))) == 1  # nothing left to do


def test_network_service_files_and_kinds(tmp_path, monkeypatch):
    old = {"netz": "welt", "art": "frei", "modus": "peer", "gruender": [], "arbeit_bits": 26, "sperren": ["c" * 64], "lokal_port": 9766,
           "mcp_token_datei": "/etc/vi-p2p/welt-mcp-token", "torrent": {"aktiv": True, "verzeichnis": "/srv/seg"}}
    new = nd.english_file(old)
    assert new == {"net": "welt", "kind": "free", "mode": "peer", "founders": [], "pow_bits": 26, "blocked": ["c" * 64], "local_port": 9766,
                   "mcp_token_file": "/etc/vi-p2p/welt-mcp-token", "torrent": {"active": True, "directory": "/srv/seg"}}
    k = nd.from_file(old)
    assert k.kind == "free" and k.torrent == {"active": True, "directory": "/srv/seg"} and k.blocked == ["c" * 64]
    assert nd.NetConfig(kind="firma").kind == "company" and config.net_kind("offen") == "open"
    d = tmp_path / "p2p"
    d.mkdir()
    (d / "welt.json").write_text(json.dumps(old))
    monkeypatch.setenv("VI_P2P_DIR", str(d))
    monkeypatch.setenv("VI_MCP_CONFIG", str(tmp_path / "c.json"))
    (tmp_path / "c.json").write_text(json.dumps({"offen": True}))
    lines = configure.migrate_configs()
    assert len(lines) == 2 and json.loads((d / "welt.json").read_text()) == new and json.loads((tmp_path / "c.json").read_text()) == {"open": True}
    assert configure.migrate_configs() == []


def test_unattended_and_cli_accept_the_german_kinds():
    assert configure.env_answers({"VI_MCP_NET_KIND": "Firma"}) == {"net_kind": "company"}
    assert configure.validate({"net_kind": "company"}) == {} and configure.validate({"net_kind": "firma"})  # validate sees English only
    from vi_mcp import net_cli  # noqa: F401 — the --kind option translates through config.net_kind
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", type=config.net_kind, choices=("company", "open", "free"))
    assert ap.parse_args(["--kind", "frei"]).kind == "free"
