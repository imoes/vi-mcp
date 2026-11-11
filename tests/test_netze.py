"""0.39.0: several networks (company and open), a logbook that relays entry types of newer versions, versions and backlog per peer."""
import json
import time

import pytest

pytest.importorskip("cryptography")

from vi_mcp import checks, config, logbook as lb, net_service as nd, p2p, tools, usage_stats  # noqa: E402
from vi_mcp import memory as g  # noqa: E402

from test_netz import FakeMemory, mem_object, net, _log  # noqa: E402,F401
from test_p2p import GOOD, _bundle, _key  # noqa: E402


def _foreign_entry(log: lb.Logbook, type_: str, content, **extra_header):
    """An entry of a type this version does not know, signed as a newer version would write it."""
    seq, prev = log._header_of(log.pub)
    header = {"v": lb.VERSION, "pub": log.pub, "seq": seq + 1, "vor": prev, "typ": type_, "sha": lb.sha256(content), "zeit": time.strftime("%Y-%m-%d", time.gmtime()), **extra_header}
    header["sig"] = log.k.sign(lb.canonical(header)).hex()
    with log.lock:
        log._insert(header, content)
    return header


# ---- logbook: forward compatibility ----

def test_unknown_type_is_accepted_relayed_and_keeps_the_chain(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    c = _log(tmp_path, "c", [a.pub])
    _foreign_entry(a, "seite", {"seite": "backup", "text": "Restore with proxmox-backup-client"})
    a.attach("adresse", {"adresse": "https://a.example:8766"})
    r = b.ingest(a.read(a.pub, 0))
    assert r["neu"] == 2 and r["unbekannt"] == 1 and r["abgelehnt"] == 0  # the entry after it still arrives: chain intact
    r = c.ingest(b.read(a.pub, 0))  # relayed by b, verifiable at c
    assert r["neu"] == 2 and r["unbekannt"] == 1
    assert b.status()["unbekannte_typen"] == 1


def test_unknown_type_with_wrong_content_is_a_violation(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    _foreign_entry(a, "seite", {"seite": "x", "text": "y"})
    entries = a.read(a.pub, 0)
    entries[0]["inhalt"] = {"seite": "x", "text": "changed on the way"}
    r = b.ingest(entries)
    assert r["neu"] == 0 and "unusable" in r["gruende"][0]


def test_header_extra_fields_tolerated_within_limits():
    base = {"v": 1, "pub": "a" * 64, "seq": 1, "vor": None, "typ": "adresse", "sha": "b" * 64, "zeit": "2026-11-11", "sig": "c"}
    assert lb.header_form({**base, "faehig": "seite"}) is None
    assert lb.header_form({**base, "Bad-Key": "x"}) == "header has wrong fields"
    assert lb.header_form({**base, **{f"feld_{c}": 1 for c in "abcde"}}) == "header has wrong fields"
    assert lb.header_form({**base, "typ": "Seite!"}) == "header: version, type or key unusable"


def test_address_with_fields_of_a_newer_version():
    assert lb.valid_control_form("adresse", {"adresse": "https://a.example:8766", "faehig": ["seite"]})
    assert not lb.valid_control_form("adresse", {"adresse": "nicht-url"})
    assert not lb.valid_control_form("einladung", {"pub": "a" * 64, "extra": 1})  # membership stays strict


def test_version_tuple_and_peers_below(tmp_path):
    assert lb.version_tuple("0.39.0") > lb.version_tuple("0.38.12") and lb.version_tuple("?") == (0, 0, 0)
    a = _log(tmp_path, "a")
    for addr, v in (("http://p1", "0.41.0"), ("http://p2", "0.38.2"), ("http://p3", None)):
        a.peer_remember(addr, "start")
        a.peer_result(addr, True)
        if v:
            a.peer_state(addr, version=v)
    assert a.peers_below("0.41.0") == ["http://p2", "http://p3"]


# ---- network service: version, backlog, snapshot ----

def test_service_reports_version_backlog_and_snapshot(net):
    (sa, a_pub), (sb, b_pub) = net.key_(), net.key_()
    a = net.build(sa, [a_pub])
    a.log.attach("einladung", {"pub": b_pub})
    b = net.build(sb, [a_pub], start=[a.k.address])
    a.mcp.mem_objects.append(mem_object(1))
    a.run_round()
    b.run_round()
    p = {x["adresse"]: x for x in b.log.peers()}[a.k.address]
    from vi_mcp import __version__
    assert p["version"] == __version__ and p["fehlt_hier"] == 0 and p["fehlt_dort"] == 0
    b.run_round()  # the snapshot goes with the outbox call at the start of a round: it shows the previous round
    s = b.mcp.state
    assert s["netz"] == "standard" and s["art"] == "offen" and s["version"] == __version__ and s["mitglieder"] == 2
    assert s["peers"][0]["erreichbar"] and s["peers"][0]["version"] == __version__


def test_company_service_relays_internal_names(net):
    (sa, a_pub), (sb, b_pub) = net.key_(), net.key_()
    a = net.build(sa, [a_pub], kind="firma", net="firma")
    a.log.attach("einladung", {"pub": b_pub})
    b = net.build(sb, [a_pub], start=[a.k.address], kind="firma", net="firma")
    o = {**mem_object(1), "text": "Backup of db01.corp.internal runs at 02:00 via borg", "hashtags": ["host:db01", "thema:backup"]}
    a.mcp.mem_objects.append(o)
    a.run_round()
    b.run_round()
    assert b.mcp.texts() == [o["text"]]
    (sc, c_pub), (sd, d_pub) = net.key_(), net.key_()  # the same in an open network: kept out
    c = net.build(sc, [c_pub])
    c.log.attach("einladung", {"pub": d_pub})
    d = net.build(sd, [c_pub], start=[c.k.address])
    c.mcp.mem_objects.append(o)
    c.run_round()
    d.run_round()
    assert d.mcp.texts() == []


# ---- memory: networks and their kind ----

@pytest.fixture()
def nets(gd, monkeypatch):
    monkeypatch.setattr(p2p, "config", {"netze": {"firma": {"art": "firma", "instanz": "netz-firma"}, "kaputt": {"art": "geheim", "instanz": "x"}}})
    p2p.generate_token("a")


def _proven(text, tags, visibility):
    o = g.new_object("erkenntnis", text, tags, {"quelle": "Messung 11.11.2026 auf dem Host"}, instance="a", visibility=visibility)
    o.confirm("ki@b", "checked", "b", family="gpt")
    return g.load(o.id)


def test_networks_and_their_kind(nets):
    assert set(p2p.networks()) == {"standard", "firma"}  # the unusable one is ignored (and logged)
    assert p2p.network_of("p2p") == "standard" and p2p.network_of("netz-firma") == "firma" and p2p.network_of("a") is None
    assert p2p.is_company("firma") and not p2p.is_company("standard")


def test_company_network_carries_internal_knowledge_unanonymised(nets):
    internal = _proven("Backup of db01.corp.internal runs nightly via borg to the NAS", ["thema:backup", "host:db01"], "intern")
    shared = _proven("Borg needs the passphrase in BORG_PASSCOMMAND for unattended runs", ["thema:backup"], "geteilt")
    private = _proven("My own private notes on the backup schedule here", ["thema:backup"], "privat")
    company = {o["text"]: o for o in p2p.outbox("firma")["objekte"]}
    open_ = {o["text"]: o for o in p2p.outbox("standard")["objekte"]}
    assert internal.text in company and "host:db01" in company[internal.text]["hashtags"]  # unchanged, host tag kept
    assert shared.text in company and private.text not in company
    assert internal.text not in open_ and all("db01" not in t for t in open_)  # internal never into the open network
    shared_open = next(o for o in open_.values() if "BORG_PASSCOMMAND" in o["text"])
    assert shared_open["netz_id"] != company[shared.text]["netz_id"]  # not linkable across networks


def test_company_import_becomes_internal_and_never_reexported(nets, monkeypatch):
    k, _pk = _key()
    o = {**GOOD, "text": "db01.corp.internal loses the NFS mount after kernel updates", "hashtags": ["host:db01", "thema:nfs"]}
    assert p2p.inbox(_bundle(k, [o]), in_background=False)["abgelehnt"] == 1  # standard network: internals rejected
    r = p2p.inbox(_bundle(k, [o]), in_background=False, net="firma")
    assert r["quarantaene"] == 1
    imp = g.recall("modus:quarantaene", viewer=None)[0][1]
    assert imp.visibility == "intern" and "netz:firma" in imp.hashtags and imp.data["herkunft"]["netz"] == "firma"
    assert all(x["text"] != o["text"] for x in p2p.outbox("standard")["objekte"] + p2p.outbox("firma")["objekte"])


def test_publisher_cannot_claim_a_network():
    b = checks.check({**GOOD, "hashtags": GOOD["hashtags"] + ["netz:firma"]})
    assert "netz:firma" not in b.mem_object["hashtags"]


def test_tools_take_the_network_from_the_instance(nets):
    state = {"netz": "firma", "pseudonym": "vi-abc", "version": "0.39.0", "mitglieder": 3, "peers": [{"adresse": "https://x", "version": "0.39.0", "erreichbar": True, "fehlt_hier": 0, "fehlt_dort": 2}],
             "transport": {"runden": 4, "per_https": 10, "per_torrent": 0}}
    out = json.loads(tools.call_tool("vi_net_outbox", {"state": state}, "netz-firma", False))
    assert "objekte" in out and p2p.states()["firma"]["daten"]["mitglieder"] == 3
    with pytest.raises(tools.Rejected, match="network service"):
        tools.call_tool("vi_net_outbox", {}, "a", False)
    st = p2p.status()["netze"]
    assert st["firma"]["art"] == "firma" and st["firma"]["stand"]["mitglieder"] == 3
    assert st["standard"]["stand"].startswith("not recorded")
    w = "\n".join(usage_stats.network_lines())
    assert "standard (offen" in w and "not recorded" in w
    assert "firma (firma): snapshot" in w and "peers 1 of 1 reachable" in w and "missing there 2" in w
    with pytest.raises(tools.Rejected, match="unknown network"):
        tools.call_tool("vi_net_preview", {"network": "gibtsnicht"}, "a", False)


def test_set_network_registers_kind_and_instance(tmp_path, monkeypatch):
    cfg = tmp_path / "c.json"
    monkeypatch.setenv("VI_MCP_CONFIG", str(cfg))
    inst, token = config.set_network("firma", "firma")
    assert inst == "netz-firma" and token and config.load().p2p["netze"]["firma"] == {"art": "firma", "instanz": "netz-firma"}
    assert config.set_network("firma", "firma") == ("netz-firma", None)
    with pytest.raises(ValueError, match="not changed afterwards"):
        config.set_network("firma", "offen")
    for bad in ("standard", "config", "Firma", "x"):
        with pytest.raises(ValueError):
            config.set_network(bad, "firma")


def test_template_unit_and_packaging():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    unit = (root / "deploy/vi-p2p@.service").read_text()
    assert "VI_P2P_CONFIG=/etc/vi-p2p/%i.json" in unit and "InaccessiblePaths=-/var/lib/vi-mcp" in unit and "StateDirectory=vi-p2p vi-p2p/%i" in unit
    for f in ("deploy/debian/build.sh", "deploy/rpm/build.sh", "deploy/rpm/vi-mcp.spec"):
        assert "vi-p2p@.service" in (root / f).read_text(), f


def test_net_config_kind_is_checked(tmp_path):
    p = tmp_path / "n.json"
    p.write_text(json.dumps({"netz": "firma", "art": "firma"}))
    k = nd.load(p)
    assert k.net == "firma" and k.kind == "firma"
    p.write_text(json.dumps({"art": "geheim"}))
    with pytest.raises(ValueError, match="offen or firma"):
        nd.load(p)
