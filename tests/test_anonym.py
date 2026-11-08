"""0.13.0: Das Netz bekommt keine IPs, internen Namen, Zugangsdaten, Nutzernamen oder Proxy-Angaben; Recht auf Vergessen mit Token."""
import hashlib
import json

import pytest

pytest.importorskip("cryptography")

from vi_mcp import anonym, p2p, pruefung, werkzeuge, vektor  # noqa: E402
from vi_mcp import gedaechtnis as g  # noqa: E402

from test_p2p import _bundle, _modell, GUT, netz  # noqa: E402,F401


@pytest.mark.parametrize("text,klasse", [
    ("Der Server hat 10.1.2.3 als Adresse", "ip"), ("Netz 172.16.0.0/16 ist intern", "ip"), ("Adresse fe80::1 am Link", "ip"), ("2001:db8::8a2e:370:7334 antwortet", "ip"),
    ("Karte 00:1a:2b:3c:4d:5e fällt aus", "mac"), ("Dienst auf db1.firma.intern läuft", "domain"), ("Siehe mail.acme.de für Details", "domain"), ("https://wiki/seite ist die Quelle", "domain"),
    ("http://gitlab.firma.media:8080/x/y", "domain"), ("Host app0815 hängt", "host"), ("cache0218 startet neu", "host"),
    ("password=geheim123", "geheimnis"), ('"api_key": "abc"', "geheimnis"), ("Authorization: Bearer abcdefghijkl", "geheimnis"), ("https://max:geheim@example.com/", "geheimnis"),
    ("-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----", "geheimnis"), ("Token ghp_abcdefghijklmnopqrstuvwx1234", "geheimnis"), ("sshpass -p hallo ssh x", "geheimnis"),
    ("Das Kennwort lautet 4PxLh7j0 seit gestern", "geheimnis"), ("Altes Passwort war dvxhMSsqSC][ hier", "geheimnis"), ("Schlüssel 7f3a9c1e8b2d4f6a7f3a9c1e8b2d4f6a", "geheimnis"),
    ("https_proxy=http://p.firma.de:80 setzen", "proxy"), ("curl --proxy p:3128 url", "proxy"), ("Proxy: squid:3128 nutzen", "proxy"), ("über proxy.firma.media erreichbar", "proxy"), ("no_proxy=localhost,.firma.de", "proxy"),
    ("Mail an max.muster@firma.de schicken", "email"), ("ssh deploy@web1 ausführen", "nutzer"), ("Datei /home/maxm/x.txt prüfen", "nutzer"), (r"C:\Users\maxm\a.txt liegt dort", "nutzer"), ("user=maxm und weiter", "nutzer"),
])
def test_erkennt_jede_klasse(text, klasse):
    assert klasse in anonym.klassen(text)
    aus = anonym.ersetze(text)
    assert anonym.klassen(aus) == [] or klasse not in anonym.klassen(aus)


@pytest.mark.parametrize("text", [
    "Der Dienst braucht nach dem Neustart 30 Sekunden", "os.path.join und urllib.request.urlopen werden genutzt", "Datei start.sh und config.yaml prüfen", "Version 1.2 und Python 3.11 funktionieren",
    "um 14:04:58 begann der Lauf", "Das geht nur über den Proxy", "SHA256 und RFC9110 sind gemeint", "Siehe https://docs.python.org/3/library/re.html", "numpy.ndarray wird zurückgegeben", "Host web1 und db2 sind Beispiele",
])
def test_harmloses_bleibt(text):
    assert anonym.klassen(text) == [], anonym.befunde(text)


def test_bekannte_namen_und_mcp_server():
    assert anonym.ersetze("web1 und Mustermann-AG sind betroffen", frozenset({"web1", "Mustermann-AG"})) == "<host> und <host> sind betroffen"
    assert anonym.ersetze("mcp__firma-skills__netbox_get_vms lief") == "netbox_get_vms lief"


def test_oeffentliche_domain_aus_konfiguration():
    assert anonym.klassen("siehe docs.partner.de") == ["domain"]
    anonym.setze({"oeffentliche_domains": ["partner.de"]})
    try:
        assert anonym.klassen("siehe docs.partner.de") == []
    finally:
        anonym.setze(None)


@pytest.mark.parametrize("feld,wert", [("text", "Der Host 10.1.2.3 fällt regelmäßig aus"), ("quelle", "Logzeile von db1.firma.intern"), ("hashtags", ["thema:a", "host:web1"]), ("hashtags", ["thema:10.1.2.3"])])
def test_import_lehnt_interna_ab_und_nennt_nur_die_klasse(feld, wert):
    b = pruefung.pruefe({**GUT, feld: wert})
    assert b.urteil == "ablehnen" and "interna" in " ".join(b.gruende) and "10.1.2.3" not in " ".join(b.gruende) and "firma" not in " ".join(b.gruende)


def test_import_ohne_loeschbarkeit_wird_abgelehnt():
    assert "löschbar" in pruefung.pruefe({k: v for k, v in GUT.items() if k != "netz_id"}).gruende[0]


@pytest.fixture()
def herausgeber(netz, monkeypatch, tmp_path):  # noqa: F811
    seed = tmp_path / "seed"
    pk = p2p.schluessel_erzeugen(seed)
    monkeypatch.setattr(p2p, "konfig", {"seed_datei": str(seed), "vertraut": {**p2p.konfig["vertraut"], "eigen": {"pubkey": pk, "darf": []}}})
    return netz


def _ko(text, tags=("thema:a",), instanz="a", **d):
    return g.neues_objekt("erkenntnis", text, list(tags), {"quelle": "Messung vom 2.11.", **d}, grund="T", instanz=instanz)


def test_export_verraet_nichts(herausgeber):
    p2p.token_erzeugen("alice-laptop")
    _ko("Auf srv-alpha ist 10.9.1.5 der Gateway, gemeldet von alice-laptop", tags=("thema:netz", "host:srv-alpha"), instanz="alice-laptop", quelle="Ticket von max@firma.de")
    b = p2p.exportieren()
    roh = json.dumps(b, ensure_ascii=False)
    for verboten in ("srv-alpha", "10.9.1.5", "alice-laptop", "max@", "firma.de", "host:"):
        assert verboten not in roh, verboten
    o = b["objekte"][0]["objekt"]
    assert o["text"] == "Auf <host> ist <ip> der Gateway, gemeldet von <host>" and len(o["zeit"]) == 10 and b["manifest"]["herausgeber"].startswith("vi-") and "T" not in b["manifest"]["zeit"]
    assert p2p.importieren(b, im_hintergrund=False)["quarantaene"] == 1  # das Exportierte besteht die eigenen Importregeln


def test_zurueckgehalten_wird_benannt(herausgeber):
    p2p.token_erzeugen("a")
    _ko("Das Passwort des Routers steht im Tresor")
    _ko("<host> <ip>   12")
    _ko("Wissen einer Instanz ohne Token bleibt hier", instanz="b")
    v = p2p.vorschau("a")
    assert v["anzahl"] == 0 and v["zurueckgehalten"] == {"spricht von Zugangsdaten": 1, "nach dem Anonymisieren bleibt kein Inhalt": 1}
    assert p2p.exportieren()["objekte"] == []


def test_recht_auf_vergessen_von_ende_zu_ende(herausgeber):
    tok = p2p.token_erzeugen("a")
    eins = _ko("Erstes Wissen zum Eingang des Dienstes")
    _ko("Zweites Wissen zum Ausgang des Dienstes", tags=("thema:b",))
    b = p2p.exportieren()
    assert p2p.importieren(b, im_hintergrund=False)["quarantaene"] == 2
    nid, _ = p2p._objekt_token(tok, eins.id)
    with g.sperre:
        oid = g.db().execute("SELECT oid FROM p2p_netz WHERE netz_id = ?", (nid,)).fetchone()[0]
    assert g.lade(oid)
    r = p2p.netz_vergessen("a", tok, [eins.id], "Daten waren falsch")
    assert r == {"zurueckgerufen": 1, "unbekannt": []}
    n = p2p.exportieren()
    assert len(n["objekte"]) == 1 and len(n["widerrufe"]) == 1 and tok not in json.dumps(n)
    assert p2p.importieren(n, im_hintergrund=False)["vergessen"] == 1
    assert g.lade(oid) is None and g.lade(eins.id)  # beim Empfänger weg, beim Urheber bleibt es
    with g.sperre:
        assert g.db().execute("SELECT 1 FROM p2p_grab WHERE netz_id = ?", (nid,)).fetchone()
        assert not g.db().execute("SELECT 1 FROM objekt_fts WHERE id = ?", (oid,)).fetchone()
    p2p_b = {**b}
    g.db().execute("DELETE FROM p2p_stand")
    r = p2p.importieren(p2p_b, im_hintergrund=False)
    assert r["quarantaene"] == 0 and r["bekannt"] == 2  # die alte Fassung bringt nichts zurück


def test_widerruf_kommt_vor_dem_objekt_an(herausgeber):
    tok = p2p.token_erzeugen("a")
    o = _ko("Dieses Wissen wird zurückgerufen, bevor es ankommt")
    b = p2p.exportieren()
    p2p.netz_vergessen("a", tok, [o.id], "x")
    p2p.importieren(_bundle(herausgeber, [], widerrufe=p2p._widerrufe()), im_hintergrund=False)
    assert p2p.importieren(b, im_hintergrund=False)["quarantaene"] == 0


def test_fremdes_token_loescht_nichts(herausgeber):
    tok = p2p.token_erzeugen("a")
    o = _ko("Dieses Wissen soll niemand anderes löschen können")
    b = p2p.exportieren()
    p2p.importieren(b, im_hintergrund=False)
    nid, _ = p2p._objekt_token(tok, o.id)
    r = p2p.importieren(_bundle(herausgeber, [], widerrufe=[{"netz_id": nid, "token": "geraten"}]), im_hintergrund=False)
    with g.sperre:
        assert r["vergessen"] == 0 and g.db().execute("SELECT COUNT(*) FROM p2p_netz WHERE netz_id = ?", (nid,)).fetchone()[0] == 1


def test_objekt_token_oeffnet_kein_anderes_objekt():
    a, b = p2p._objekt_token("t", "x"), p2p._objekt_token("t", "y")
    assert a[0] != b[0] and a[1] != b[1] and a[1] != "t" and a[0] != a[1][:32]


def test_rechte_und_einmaligkeit(herausgeber):
    tok = p2p.token_erzeugen("a")
    with pytest.raises(ValueError, match="nicht erneuert"):
        p2p.token_erzeugen("a")
    fremd = _ko("Wissen der anderen Instanz bleibt ihres", instanz="b")
    with pytest.raises(ValueError, match="anderen Instanz"):
        p2p.netz_vergessen("a", tok, [fremd.id], "x")
    with pytest.raises(ValueError, match="passt nicht"):
        p2p.netz_vergessen("a", "falsch", [fremd.id], "x")
    with pytest.raises(ValueError, match="Grund"):
        p2p.netz_vergessen("a", tok, [fremd.id], " ")
    assert p2p.netz_vergessen("a", tok, None, "alles") == {"zurueckgerufen": 0, "unbekannt": []}


def test_werkzeuge(herausgeber):
    t = werkzeuge.rufe("vi_netz_token", {}, "a", False).split("\n")[-1]
    with pytest.raises(werkzeuge.Abgelehnt):
        werkzeuge.rufe("vi_netz_token", {}, "a", False)
    o = _ko("Das hier wird über das Werkzeug zurückgerufen")
    assert json.loads(werkzeuge.rufe("vi_netz_vorschau", {}, "a", False))["anzahl"] == 1
    with pytest.raises(werkzeuge.Abgelehnt):
        werkzeuge.rufe("vi_netz_vergiss", {"token": t, "grund": "x"}, "a", False)
    assert "1 Einträge" in werkzeuge.rufe("vi_netz_vergiss", {"token": t, "ids": [o.id], "grund": "x"}, "a", False)
    assert json.loads(werkzeuge.rufe("vi_netz_vorschau", {}, "a", False))["anzahl"] == 0


def test_zugangsdaten_werden_nie_gespeichert(gd):
    o = g.neues_objekt("erkenntnis", "Login mit password=abc123 und Bearer abcdefghijkl", ["thema:a"], {"quelle": "x", "args": {"cmd": "curl https://u:p4ss@h/x", "liste": ["api_key: 77"]}}, grund="T", instanz="a")
    roh = json.dumps([o.text, o.daten])
    for v in ("abc123", "abcdefghijkl", "p4ss", "77"):
        assert v not in roh, v
    r = g.neues_objekt("reflex", "Reflex mit Code", ["thema:a"], {"code": "token = lese()  # password=ok"}, grund="T", instanz="a")
    assert r.daten["code"] == "token = lese()  # password=ok"  # Quelltext wird nicht verstümmelt


def test_standort_tags_gehen_nicht_hinaus(herausgeber):
    p2p.token_erzeugen("a")
    _ko("Wissen mit Standort im Hashtag bleibt ohne ihn", tags=("thema:a", "ort:MUC-1", "kunde:acme", "host:x"))
    assert p2p.vorschau("a")["beispiele"][0]["hashtags"] == ["thema:a"]
    assert pruefung.pruefe({**GUT, "hashtags": ["thema:a", "ort:MUC-1"]}).urteil == "ablehnen"
