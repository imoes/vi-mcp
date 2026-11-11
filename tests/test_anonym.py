"""0.13.0: The network gets no IPs, internal names, credentials, user names or proxy details; right to be forgotten with a token."""
import hashlib
import json

import pytest

pytest.importorskip("cryptography")

from vi_mcp import anonymize, p2p, reviewer, checks, reflection, tools  # noqa: E402
from vi_mcp import memory as g  # noqa: E402

from test_p2p import _bundle, _model, GOOD, net  # noqa: E402,F401


@pytest.mark.parametrize("text,category", [
    ("Der Server hat 10.1.2.3 als Adresse", "ip"), ("Netz 172.16.0.0/16 ist intern", "ip"), ("Adresse fe80::1 am Link", "ip"), ("2001:db8::8a2e:370:7334 antwortet", "ip"),
    ("Karte 00:1a:2b:3c:4d:5e fällt aus", "mac"), ("Dienst auf db1.firma.intern läuft", "domain"), ("Siehe mail.acme.de für Details", "domain"), ("https://wiki/seite ist die Quelle", "domain"),
    ("http://gitlab.firma.media:8080/x/y", "domain"), ("Host app0815 hängt", "host"), ("cache0218 startet neu", "host"),
    ("Auf dbtest01 hilft ein Neustart", "host"), ("web-01 und db-test-02 antworten nicht", "host"), ("srv12 ist voll", "host"),
    ("password=geheim123", "geheimnis"), ('"api_key": "abc"', "geheimnis"), ("Authorization: Bearer abcdefghijkl", "geheimnis"), ("https://max:geheim@example.com/", "geheimnis"),
    ("-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----", "geheimnis"), ("Token ghp_abcdefghijklmnopqrstuvwx1234", "geheimnis"), ("sshpass -p hallo ssh x", "geheimnis"),
    ("Das Kennwort lautet 4PxLh7j0 seit gestern", "geheimnis"), ("Altes Passwort war dvxhMSsqSC][ hier", "geheimnis"), ("Schlüssel 7f3a9c1e8b2d4f6a7f3a9c1e8b2d4f6a", "geheimnis"),
    ("https_proxy=http://p.firma.de:80 setzen", "proxy"), ("curl --proxy p:3128 url", "proxy"), ("Proxy: squid:3128 nutzen", "proxy"), ("über proxy.firma.media erreichbar", "proxy"), ("no_proxy=localhost,.firma.de", "proxy"),
    ("Mail an max.muster@firma.de schicken", "email"), ("ssh deploy@web1 ausführen", "nutzer"), ("Datei /home/maxm/x.txt prüfen", "nutzer"), (r"C:\Users\maxm\a.txt liegt dort", "nutzer"), ("user=maxm und weiter", "nutzer"),
])
def test_detects_every_category(text, category):
    assert category in anonymize.categories(text)
    outputs = anonymize.replace(text)
    assert anonymize.categories(outputs) == [] or category not in anonymize.categories(outputs)


@pytest.mark.parametrize("text", [
    "Der Dienst braucht nach dem Neustart 30 Sekunden", "os.path.join und urllib.request.urlopen werden genutzt", "Datei start.sh und config.yaml prüfen", "Version 1.2 und Python 3.11 funktionieren",
    "um 14:04:58 begann der Lauf", "Windows Server 2019 und Debian 12 sowie python3.11", "UTF-16 und SHA-256 und TLS13 und HTTP2", "Port 8080 und RFC 9110", "Ubuntu 2404 und ubuntu24", "ES2015 und win2019",
    "Das geht nur über den Proxy", "SHA256 und RFC9110 sind gemeint", "Siehe https://docs.python.org/3/library/re.html", "numpy.ndarray wird zurückgegeben", "Host web1 und db2 sind Beispiele",
])
def test_harmless_stays(text):
    assert anonymize.categories(text) == [], anonymize.findings(text)


def test_known_names_and_mcp_servers():
    assert anonymize.replace("web1 und Mustermann-AG sind betroffen", frozenset({"web1", "Mustermann-AG"})) == "<host> und <host> sind betroffen"
    assert anonymize.replace("mcp__firma-skills__netbox_get_vms lief") == "netbox_get_vms lief"


def test_public_domain_from_config():
    assert anonymize.categories("siehe docs.partner.de") == ["domain"]
    anonymize.configure({"oeffentliche_domains": ["partner.de"]})
    try:
        assert anonymize.categories("siehe docs.partner.de") == []
    finally:
        anonymize.configure(None)


@pytest.mark.parametrize("field_name,value", [("text", "Der Host 10.1.2.3 fällt regelmäßig aus"), ("quelle", "Logzeile von db1.firma.intern"), ("hashtags", ["thema:a", "host:web1"]), ("hashtags", ["thema:10.1.2.3"])])
def test_import_rejects_internals_and_names_only_the_category(field_name, value):
    b = checks.check({**GOOD, field_name: value})
    assert b.verdict == "ablehnen" and "interna" in " ".join(b.reasons) and "10.1.2.3" not in " ".join(b.reasons) and "firma" not in " ".join(b.reasons)


def test_import_without_deletability_is_rejected():
    assert "could never be deleted again" in checks.check({k: v for k, v in GOOD.items() if k != "netz_id"}).reasons[0]


@pytest.fixture()
def publisher(net):  # noqa: F811
    return net


def _mk_obj(text, tags=("thema:a",), instance="a", proven=True, **d):
    o = g.new_object("erkenntnis", text, list(tags), {"quelle": "Messung vom 2.11.", **d}, reason="T", instance=instance)
    if proven:
        o.confirm("ki@andere", "stimmt", "andere")
        g.save(o)
    return o


def _import_bundle(k, start=1):
    a = p2p.outbox()
    return a, p2p.inbox(_bundle(k, a["objekte"], start=start), in_background=False)


def _revocations(k):
    return p2p.inbox(_bundle(k, [{"ziel": w["netz_id"], "token": w["token"]} for w in p2p.outbox()["widerrufe"]], type_="widerruf"), in_background=False)


def test_export_reveals_nothing(publisher):
    p2p.generate_token("alice-laptop")
    _mk_obj("Auf srv-alpha ist 10.9.1.5 der Gateway, gemeldet von alice-laptop", tags=("thema:netz", "host:srv-alpha"), instance="alice-laptop", quelle="Ticket von max@firma.de")
    a, r = _import_bundle(publisher)
    raw = json.dumps(a, ensure_ascii=False)
    for forbidden in ("srv-alpha", "10.9.1.5", "alice-laptop", "max@", "firma.de", "host:"):
        assert forbidden not in raw, forbidden
    o = a["objekte"][0]
    assert o["text"] == "Auf <host> ist <ip> der Gateway, gemeldet von <host>" and len(o["zeit"]) == 10
    assert r["quarantaene"] == 1  # the export passes our own import rules


def test_withheld_is_named(publisher):
    p2p.generate_token("a")
    _mk_obj("Das Passwort des Routers steht im Tresor")
    _mk_obj("<host> <ip>   12")
    _mk_obj("Nur einmal gesehen und von niemandem bestätigt", proven=False)
    _mk_obj("Wissen einer Instanz ohne Token bleibt hier", instance="b")
    v = p2p.preview("a")
    assert v["anzahl"] == 0 and v["zurueckgehalten"] == {"mentions credentials": 1, "no content left after anonymising": 1, "not yet proven": 1}
    assert p2p.outbox()["objekte"] == []


def test_proven_by_measured_benefit(publisher):
    p2p.generate_token("a")
    o = _mk_obj("Dieser Hinweis hat sich in der Praxis bewährt", proven=False)
    o.data["nuetzlich"] = {"ja": 3, "nein": 0}
    g.save(o)
    assert p2p.preview("a")["anzahl"] == 1


def test_right_to_be_forgotten_end_to_end(publisher):
    tok = p2p.generate_token("a")
    one = _mk_obj("Erstes Wissen zum Eingang des Dienstes")
    _mk_obj("Zweites Wissen zum Ausgang des Dienstes", tags=("thema:b",))
    a, r = _import_bundle(publisher)
    assert r["quarantaene"] == 2
    nid, _ = p2p._object_token(tok, one.id)
    with g.lock:
        oid = g.db().execute("SELECT oid FROM p2p_netz WHERE netz_id = ?", (nid,)).fetchone()[0]
    assert g.load(oid)
    assert p2p.net_forget("a", tok, [one.id], "Daten waren falsch") == {"zurueckgerufen": 1, "unbekannt": []}
    n = p2p.outbox()
    assert len(n["objekte"]) == 1 and len(n["widerrufe"]) == 1 and tok not in json.dumps(n)
    assert _revocations(publisher)["vergessen"] == 1
    assert g.load(oid) is None and g.load(one.id)  # gone at the receiver, stays with the author
    with g.lock:
        assert g.db().execute("SELECT 1 FROM p2p_grab WHERE netz_id = ?", (nid,)).fetchone()
        assert not g.db().execute("SELECT 1 FROM objekt_fts WHERE id = ?", (oid,)).fetchone()
    r = p2p.inbox(_bundle(publisher, a["objekte"]), in_background=False)
    assert r["quarantaene"] == 0 and r["bekannt"] == 2  # the old version brings nothing back


def test_revocation_arrives_before_the_object(publisher):
    tok = p2p.generate_token("a")
    o = _mk_obj("Dieses Wissen wird zurückgerufen, bevor es ankommt")
    a = p2p.outbox()
    p2p.net_forget("a", tok, [o.id], "x")
    _revocations(publisher)
    assert p2p.inbox(_bundle(publisher, a["objekte"]), in_background=False)["quarantaene"] == 0


def test_foreign_token_deletes_nothing(publisher):
    tok = p2p.generate_token("a")
    o = _mk_obj("Dieses Wissen soll niemand anderes löschen können")
    _import_bundle(publisher)
    nid, _ = p2p._object_token(tok, o.id)
    r = p2p.inbox(_bundle(publisher, [{"ziel": nid, "token": "geraten"}], type_="widerruf"), in_background=False)
    with g.lock:
        assert r["vergessen"] == 0 and g.db().execute("SELECT COUNT(*) FROM p2p_netz WHERE netz_id = ?", (nid,)).fetchone()[0] == 1


def test_new_version_replaces_the_old(publisher):
    p2p.generate_token("a")
    o = _mk_obj("Erste Fassung dieses Wissens im Netz")
    _import_bundle(publisher)
    o.text = "Zweite Fassung dieses Wissens im Netz"
    g.save(o)
    a, r = _import_bundle(publisher, start=2)
    assert r["quarantaene"] == 1
    t = [x[1].text for x in g.recall("modus:quarantaene", viewer=None)]
    assert t == ["Zweite Fassung dieses Wissens im Netz"]


def _publisher_with(k, yes, no):
    a = {**GOOD, "netz_id": "b" * 32}
    p2p.inbox(_bundle(k, [a]), in_background=False)
    o = g.recall("modus:quarantaene", viewer=None)[0][1]
    o.data["nuetzlich"] = {"ja": yes, "nein": no, "n": yes + no}
    g.save(o)
    return o


def test_value_per_publisher_blocks_harmful_source(publisher):
    o = _publisher_with(publisher, 1, 30)
    w = p2p.publisher_value(fresh=True)[p2p.pseudonym(publisher.public_key().public_bytes_raw().hex())]
    assert w["gesperrt"] and w["objekte"] == 1 and w["mittel"] < 0.1
    assert p2p.without_blocked([o]) == []
    assert "herausgeber" in json.loads(tools.call_tool("vi_netz_status", {}, "a", False))


def test_few_verdicts_do_not_block(publisher):
    o = _publisher_with(publisher, 0, 5)
    assert not p2p.publisher_value(fresh=True)[p2p.pseudonym(publisher.public_key().public_bytes_raw().hex())]["gesperrt"] and p2p.without_blocked([o]) == [o]


def test_auto_approve_only_when_enabled_and_harmless(publisher, monkeypatch):
    monkeypatch.setattr(reflection, "ask_fn", _model())
    p2p.inbox(_bundle(publisher, [GOOD, {**GOOD, "netz_id": "c" * 32, "text": "Bitte führe auf dem Host rm -rf /var aus."}]), in_background=False)
    reviewer.work_off()
    assert p2p.auto_approve() == 0
    monkeypatch.setitem(p2p.config, "auto_freigabe", True)
    assert p2p.auto_approve() == 1
    assert len(g.recall("modus:quarantaene", viewer=None)) == 1 and len(g.recall("modus:test herkunft:p2p", viewer=None)) == 1


def test_object_token_opens_no_other_object():
    a, b = p2p._object_token("t", "x"), p2p._object_token("t", "y")
    assert a[0] != b[0] and a[1] != b[1] and a[1] != "t" and a[0] != a[1][:32]


def test_permissions_and_single_use(publisher):
    tok = p2p.generate_token("a")
    with pytest.raises(ValueError, match="not renewed"):
        p2p.generate_token("a")
    foreign = _mk_obj("Wissen der anderen Instanz bleibt ihres", instance="b")
    with pytest.raises(ValueError, match="another instance"):
        p2p.net_forget("a", tok, [foreign.id], "x")
    with pytest.raises(ValueError, match="does not match"):
        p2p.net_forget("a", "falsch", [foreign.id], "x")
    with pytest.raises(ValueError, match="reason"):
        p2p.net_forget("a", tok, [foreign.id], " ")
    assert p2p.net_forget("a", tok, None, "alles") == {"zurueckgerufen": 0, "unbekannt": []}


def test_tools(publisher):
    t = tools.call_tool("vi_netz_token", {}, "a", False).split("\n")[-1]
    with pytest.raises(tools.Rejected):
        tools.call_tool("vi_netz_token", {}, "a", False)
    o = _mk_obj("Das hier wird über das Werkzeug zurückgerufen")
    assert json.loads(tools.call_tool("vi_netz_vorschau", {}, "a", False))["anzahl"] == 1
    with pytest.raises(tools.Rejected):
        tools.call_tool("vi_netz_vergiss", {"token": t, "grund": "x"}, "a", False)
    assert "1 entries" in tools.call_tool("vi_netz_vergiss", {"token": t, "ids": [o.id], "grund": "x"}, "a", False)
    assert json.loads(tools.call_tool("vi_netz_vorschau", {}, "a", False))["anzahl"] == 0


def test_credentials_are_never_stored(gd):
    o = g.new_object("erkenntnis", "Login mit password=abc123 und Bearer abcdefghijkl", ["thema:a"], {"quelle": "x", "args": {"cmd": "curl https://u:p4ss@h/x", "liste": ["api_key: 77"]}}, reason="T", instance="a")
    raw = json.dumps([o.text, o.data])
    for v in ("abc123", "abcdefghijkl", "p4ss", "77"):
        assert v not in raw, v
    r = g.new_object("reflex", "Reflex mit Code", ["thema:a"], {"code": "token = lese()  # password=ok"}, reason="T", instance="a")
    assert r.data["code"] == "token = lese()  # password=ok"  # source code is not mangled


def test_location_tags_do_not_leave(publisher):
    p2p.generate_token("a")
    _mk_obj("Wissen mit Standort im Hashtag bleibt ohne ihn", tags=("thema:a", "ort:MUC-1", "kunde:acme", "host:x"))
    assert p2p.preview("a")["beispiele"][0]["hashtags"] == ["thema:a"]
    assert checks.check({**GOOD, "hashtags": ["thema:a", "ort:MUC-1"]}).verdict == "ablehnen"


def test_content_goes_to_net_anonymized(publisher):
    p2p.generate_token("a")
    _mk_obj("Die Hosts-API des Inventars liefert Listen", inhalt="| GET | https://inventar.firma.de/api | Liste |\nimport requests\nr = requests.get(ziel)\n")
    a = p2p.outbox()["objekte"][0]
    assert a["inhalt"].startswith("| GET | https://<host>/api | Liste |") and "requests.get(ziel)" in a["inhalt"]
    r = p2p.inbox(_bundle(publisher, [a]), in_background=False)
    assert r["quarantaene"] == 1 and g.recall("modus:quarantaene", viewer=None)[0][1].data["inhalt"] == a["inhalt"]


def test_import_rejects_internals_in_content():
    b = checks.check({**GOOD, "inhalt": "Der Dienst läuft auf 10.1.2.3 mit Port 80"})
    assert b.verdict == "ablehnen" and "internals in inhalt" in b.reasons[-1]


def test_long_content_is_sensitive(publisher):
    o = _publisher_with(publisher, 0, 0)
    o.data["inhalt"] = "Wissen " * 3000
    assert any("longer" in h for h in p2p.sensitive(o))


def test_code_examples_stay_locally_readable(gd):
    o = g.new_object("erkenntnis", "Beispiel für den Aufruf", ["thema:a"], {"quelle": "x", "inhalt": 'token = lese_token()\npassword: ${PW}\nheaders = {"Authorization": f"Bearer {token}"}\npassword=abc123\n'}, reason="T", instance="a")
    i = o.data["inhalt"]
    assert "token = lese_token()" in i and "${PW}" in i and "Bearer {token}" in i and "abc123" not in i


@pytest.mark.parametrize("text,remains", [
    ("Das Passwort lautet Sommer2026!", "Sommer2026!"), ("Kennwort: hallo123", "hallo123"), ("PW = Geheim#1", "Geheim#1"), ("root-Passwort ist Xy7kLm9q", "Xy7kLm9q"),
    ("Login: admin / Passwort: Start123", "Start123"), ("| Host | User | Passwort |\n|---|---|---|\n| web1 | admin | Ab12cd34 |\n| web2 | root | Zz99yy88 |", "Ab12cd34"),
    ("Passwort:\n   9fK2mPq7", "9fK2mPq7"), ("SNMP community string: publicXYZ", "publicXYZ"), ("Der PSK = WlanKey2026", "WlanKey2026"),
])
def test_strip_credentials_finds(text, remains):
    outputs, n = anonymize.strip_credentials(text)
    assert remains not in outputs and n >= 1 and "<geheimnis>" in outputs


@pytest.mark.parametrize("text", [
    "Das Passwort steht im Password Depot unter IT/Server.", "Passwort: siehe Tresor", "Das Passwort muss alle 90 Tage geändert werden.", "token = lese_token()",
    "password: ${DB_PASSWORD}", "Kennwort zurücksetzen über das Portal", "Passwort: ***", "Die Spalte Passwort bleibt leer", "Bei Login-Fehlern das Passwort prüfen",
])
def test_strip_credentials_leaves_alone(text):
    outputs, n = anonymize.strip_credentials(text)
    assert n == 0 and outputs == text, outputs


def test_company_names_and_internal_paths_are_replaced():
    """0.20.10: after anonymising, skills still contained an internal path and a company name in a compound (<firma>-skills)."""
    from vi_mcp import anonymize
    known_set = frozenset({"build07.beispiel-firma.media", "build07", "hna09.anderefirma.de"})
    a = anonymize.replace("ssh build07 'cd /intern/ansible/prod' (beispiel-firma-skills, anderefirma_backup)", known_set)
    assert "intern/" not in a and "beispiel-firma" not in a and "anderefirma" not in a and "build07" not in a
    assert "<pfad>" in a and "<firma>" in a
    # standard paths, URL paths and slashes in text stay knowledge
    for t in ("Konfig in /etc/nginx/nginx.conf und /var/log/syslog", "https://github.com/imoes/vi-mcp/releases", "und/oder TCP/UDP 1/2"):
        assert anonymize.replace(t, known_set) == t
    assert anonymize.companies({"x.github.com", "a.b"}) == set()  # public domains and too-short names are not companies
    # non-hosts from host: hashtags (file names, paths) yield no company names (seen in production: changelog, felder)
    assert anonymize.companies({"CHANGELOG.md", "felder.py", "app/services/stibodx", "docs/*", "web1.beispiel-firma.media"}) == {"beispiel-firma"}


def test_company_network_export_keeps_the_open_network_clean(publisher, monkeypatch):
    """0.39.0: the company export (no anonymising) is a new kind of export — it must never leak into the open network, and even there
    images and credentials stay home."""
    monkeypatch.setattr(p2p, "config", {**p2p.config, "netze": {"firma": {"art": "firma", "instanz": "netz-firma"}}})
    p2p.generate_token("alice-laptop")
    _mk_obj("Auf srv-alpha ist 10.9.1.5 der Gateway, gemeldet von alice-laptop", tags=("thema:netz", "host:srv-alpha"), instance="alice-laptop")
    internal = _mk_obj("srv-beta hängt am Switch sw-07 im Keller, Port 12", tags=("thema:netz", "host:srv-beta"), instance="alice-laptop")
    internal.visibility = "intern"
    g.save(internal)
    _mk_obj("Das Passwort für srv-gamma steht im Tresor unter Netz", tags=("thema:netz",), instance="alice-laptop")
    company = json.dumps(p2p.outbox("firma"), ensure_ascii=False)
    assert "srv-alpha" in company and "srv-beta" in company and "Passwort" not in company
    open_ = json.dumps(p2p.outbox("standard"), ensure_ascii=False)
    for forbidden in ("srv-alpha", "srv-beta", "10.9.1.5", "alice-laptop", "sw-07", "host:", "Passwort"):
        assert forbidden not in open_, forbidden
