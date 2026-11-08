"""0.14.0: Logbuch, Mitgliedschaft, Netzdienst über echtes HTTP, TLS, Vergessen über mehrere Stationen, Torrent."""
import datetime
import hashlib
import http.client
import ipaddress
import json
import time

import pytest

pytest.importorskip("cryptography")

from vi_mcp import logbuch as lb  # noqa: E402
from vi_mcp import netzdienst as nd  # noqa: E402


def objekt(i, token=None):
    return {"art": "erkenntnis", "text": f"Wissen Nummer {'abcdefghijklmnop'[i % 16]}{i} über den Eingang des Dienstes", "hashtags": ["thema:eingang"], "quelle": "Messung vom 2.11.",
            "wichtigkeit": 1, "zeit": "2026-11-08", "netz_id": hashlib.md5(str(i).encode()).hexdigest(), "loesch_hash": hashlib.sha256((token or f"t{i}").encode()).hexdigest()}


class Gedaechtnis:
    def __init__(self):
        self.objekte, self.widerrufe, self.empfangen, self.ausfall = [], [], [], False

    def ausgang(self):
        if self.ausfall:
            raise OSError("weg")
        return {"objekte": list(self.objekte), "widerrufe": list(self.widerrufe)}

    def eingang(self, e):
        if self.ausfall:
            raise OSError("weg")
        self.empfangen += e
        return {}

    def texte(self):
        return sorted(x["inhalt"]["text"] for x in self.empfangen if x["kopf"]["typ"] == "objekt")

    def ziele(self):
        return [x["inhalt"]["ziel"] for x in self.empfangen if x["kopf"]["typ"] == "widerruf"]


@pytest.fixture()
def netz(tmp_path):
    knoten = []

    class N:
        def __init__(self):
            self.n = 0

        def schluessel(self):
            self.n += 1
            seed = tmp_path / f"seed{self.n}"
            return seed, lb.schluessel_erzeugen(seed)

        def baue(self, seed, gruender, modus="peerhost", start=(), **kw):
            db = tmp_path / f"{seed.name}.db"
            k = nd.NetzKonfig(modus=modus, db=str(db), seed=str(seed), bind="127.0.0.1", port=0, gruender=gruender, startpeers=list(start), min_runde_s=0, **kw)
            d = nd.Netzdienst(k, Gedaechtnis())
            if modus == "peerhost":
                d.starte_server()
                k.adresse = f"{'https' if k.tls_cert else 'http'}://127.0.0.1:{d.port()}"
            knoten.append(d)
            return d
    yield N()
    for d in knoten:
        d.stoppe()


def _log(tmp_path, name="a", gruender=None):
    seed = tmp_path / f"s{name}"
    pub = lb.schluessel_erzeugen(seed)
    return lb.Logbuch(tmp_path / f"{name}.db", seed, gruender if gruender is not None else [pub])


def test_kette_wird_geprueft(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    for i in range(3):
        a.anhaengen("objekt", objekt(i), objekt(i)["netz_id"], objekt(i)["loesch_hash"])
    assert b.aufnehmen(a.lies(a.pub, 0))["neu"] == 3
    assert b.aufnehmen(a.lies(a.pub, 0))["bekannt"] == 3
    assert b.koepfe() == {a.pub: 3}
    c = _log(tmp_path, "c", [a.pub])
    r = c.aufnehmen(a.lies(a.pub, 1))
    assert r["neu"] == 0 and "Kette unterbrochen" in r["gruende"][0]  # Lücke am Anfang
    d = _log(tmp_path, "d", [a.pub])
    gefaelscht = a.lies(a.pub, 0)
    gefaelscht[1]["kopf"]["zeit"] = "2020-01-01"
    r = d.aufnehmen(gefaelscht)
    assert r["neu"] == 1 and "Signatur" in r["gruende"][0]


def test_gabelung_sperrt_den_herausgeber(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    a.anhaengen("adresse", {"adresse": "https://eins.example"})
    eins = a.lies(a.pub, 0)
    b.aufnehmen(eins)
    kopf = {**eins[0]["kopf"], "sha": lb.sha256({"adresse": "https://zwei.example"})}
    kopf.pop("sig")
    kopf["sig"] = a.k.sign(lb.kanonisch(kopf)).hex()
    r = b.aufnehmen([{"kopf": kopf, "inhalt": {"adresse": "https://zwei.example"}}])
    assert "Gabelung bei Nummer 1" in r["gruende"][0]
    a.anhaengen("adresse", {"adresse": "https://drei.example"})
    assert "Gabelung bekannt" in b.aufnehmen(a.lies(a.pub, 1))["gruende"][0] and b.status()["gabelungen"] == 1


def test_mitgliedschaft_folgt_den_einladungen(tmp_path):
    a = _log(tmp_path, "a")
    b, c = _log(tmp_path, "b", [a.pub]), _log(tmp_path, "c", [a.pub])
    b.anhaengen("adresse", {"adresse": "https://b.example"})
    z = _log(tmp_path, "z", [a.pub])
    assert "kein Mitglied" in z.aufnehmen(b.lies(b.pub, 0))["gruende"][0]
    a.anhaengen("einladung", {"pub": b.pub})
    z.aufnehmen(a.lies(a.pub, 0))
    assert z.aufnehmen(b.lies(b.pub, 0))["neu"] == 1
    b.anhaengen("einladung", {"pub": c.pub})
    z.aufnehmen(b.lies(b.pub, 1))
    assert z.mitglieder() == {a.pub, b.pub, c.pub}
    a.anhaengen("ausschluss", {"pub": b.pub})
    z.aufnehmen(a.lies(a.pub, 1))
    assert z.mitglieder() == {a.pub}  # wer nur über b kam, fällt mit heraus


def test_ausschliessen_duerfen_nur_einladende_und_gruender(tmp_path):
    a = _log(tmp_path, "a")
    b, c = _log(tmp_path, "b", [a.pub]), _log(tmp_path, "c", [a.pub])
    a.anhaengen("einladung", {"pub": b.pub})
    a.anhaengen("einladung", {"pub": c.pub})
    b.anhaengen("ausschluss", {"pub": c.pub})
    b.anhaengen("ausschluss", {"pub": a.pub})
    z = _log(tmp_path, "z", [a.pub])
    z.aufnehmen(a.lies(a.pub, 0))
    z.aufnehmen(b.lies(b.pub, 0))
    assert z.mitglieder() == {a.pub, b.pub, c.pub}


def test_interna_werden_nicht_weitergetragen(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    o = {**objekt(1), "text": "Der Rechner 10.1.2.3 fällt immer wieder aus"}
    a.anhaengen("objekt", o, o["netz_id"], o["loesch_hash"])
    a.anhaengen("objekt", objekt(2), objekt(2)["netz_id"], objekt(2)["loesch_hash"])
    assert b.aufnehmen(a.lies(a.pub, 0))["neu"] == 2  # die Kette bleibt ganz
    e = b.lies(a.pub, 0)
    assert e[0]["inhalt"] is None and e[1]["inhalt"] and b.status()["verstoesse"] == 1


def test_vergessen_im_logbuch(tmp_path):
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    o = objekt(1, "geheim")
    a.anhaengen("objekt", o, o["netz_id"], o["loesch_hash"])
    b.aufnehmen(a.lies(a.pub, 0))
    x = _log(tmp_path, "x", [a.pub])
    a.anhaengen("widerruf", {"ziel": o["netz_id"], "token": "falsch"}, o["netz_id"])
    b.aufnehmen(a.lies(a.pub, 1))
    assert b.lies(a.pub, 0)[0]["inhalt"]  # falscher Nachweis ändert nichts
    a2 = len(a.lies(a.pub, 0))
    a.anhaengen("widerruf", {"ziel": o["netz_id"], "token": "geheim"}, o["netz_id"])
    b.aufnehmen(a.lies(a.pub, a2))
    assert b.lies(a.pub, 0)[0]["inhalt"] is None and b.status()["grabsteine"] == 1
    # die Kette bleibt prüfbar, auch für jemanden, der erst danach dazukommt
    assert x.aufnehmen(b.lies(a.pub, 0))["neu"] == 3
    assert x.lies(a.pub, 0)[0]["inhalt"] is None
    # kommt der Inhalt von einem Peer mit altem Stand, bleibt er weg
    x.aufnehmen([{"kopf": a.lies(a.pub, 0)[0]["kopf"], "inhalt": o}])
    assert x.lies(a.pub, 0)[0]["inhalt"] is None


def test_kontingent(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "MAX_JE_TAG", 2)
    a = _log(tmp_path, "a")
    b = _log(tmp_path, "b", [a.pub])
    for i in range(3):
        a.anhaengen("adresse", {"adresse": f"https://x{i}.example"})
    r = b.aufnehmen(a.lies(a.pub, 0))
    assert r["neu"] == 2 and "Tageskontingent" in r["gruende"][0]


def _drei(netz):
    (sa, a_pub), (sb, b_pub), (sc, c_pub) = netz.schluessel(), netz.schluessel(), netz.schluessel()
    g = [a_pub]
    a = netz.baue(sa, g)
    a.log.anhaengen("einladung", {"pub": b_pub})
    a.log.anhaengen("einladung", {"pub": c_pub})
    b = netz.baue(sb, g, start=[a.k.adresse])
    c = netz.baue(sc, g, modus="peer", start=[b.k.adresse])
    return a, b, c


def test_wissen_wandert_ueber_mehrere_stationen(netz):
    a, b, c = _drei(netz)
    a.mcp.objekte.append(objekt(1))
    c.mcp.objekte.append(objekt(2))
    for _ in range(3):
        a.runde(), b.runde(), c.runde()
    assert c.mcp.texte() == [objekt(1)["text"]]
    assert a.mcp.texte() == [objekt(2)["text"]]  # vom Peer hinter der Firewall, über b geschoben
    assert sorted(b.mcp.texte()) == sorted([objekt(1)["text"], objekt(2)["text"]])


def test_vergessen_erreicht_alle_stationen(netz):
    a, b, c = _drei(netz)
    a.mcp.objekte.append(objekt(1, "geheim"))
    for _ in range(3):
        a.runde(), b.runde(), c.runde()
    nid = objekt(1)["netz_id"]
    a.mcp.objekte.clear()
    a.mcp.widerrufe.append({"netz_id": nid, "token": "geheim"})
    for _ in range(3):
        a.runde(), b.runde(), c.runde()
    for d in (a, b, c):
        assert d.log.lies(a.log.pub, 0)[2]["inhalt"] is None, d.k.modus
        assert d.log.status()["grabsteine"] == 1
    assert c.mcp.ziele() == [nid] and b.mcp.ziele() == [nid]


def test_peers_finden_sich_ueber_das_logbuch(netz):
    a, b, c = _drei(netz)
    for _ in range(3):
        b.runde(), a.runde(), c.runde()
    (sd, d_pub) = netz.schluessel()
    a.log.anhaengen("einladung", {"pub": d_pub})
    d = netz.baue(sd, a.k.gruender, modus="peer", start=[a.k.adresse])
    d.runde()
    assert b.k.adresse in [r[0] for r in d.log.db.execute("SELECT adresse FROM peer WHERE quelle = 'logbuch'")]


def test_anstoss_weckt_die_nachbarn(netz):
    a, b, c = _drei(netz)
    b.runde()
    a.wach.clear()
    b.mcp.objekte.append(objekt(5))
    b.runde()
    assert a.wach.is_set()


def _roh(d, methode, pfad, kopf=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", d.port(), timeout=5)
    c.request(methode, pfad, body=body, headers=kopf or {})
    r = c.getresponse()
    r.read()
    return r.status


def test_nur_mitglieder_bekommen_antwort(netz):
    (sa, a_pub), (_sz, _z) = netz.schluessel(), netz.schluessel()
    a = netz.baue(sa, [a_pub])
    assert _roh(a, "GET", "/netz/gesund") == 200
    assert _roh(a, "GET", f"/netz/log/{a_pub}?ab=0") == 401
    fremd = lb.privat(_sz)
    assert _roh(a, "GET", f"/netz/log/{a_pub}?ab=0", {"Authorization": nd._signiere(fremd, "GET", f"/netz/log/{a_pub}?ab=0", b"")}) == 403
    eigen = a.log.k
    assert _roh(a, "GET", f"/netz/log/{a_pub}?ab=0", {"Authorization": nd._signiere(eigen, "GET", f"/netz/log/{a_pub}?ab=0", b"")}) == 200
    assert _roh(a, "GET", f"/netz/log/{a_pub}?ab=5", {"Authorization": nd._signiere(eigen, "GET", f"/netz/log/{a_pub}?ab=0", b"")}) == 401  # Signatur gilt nur für diesen Pfad
    wert = nd._signiere(eigen, "GET", "/netz/segmente/x", b"").split()
    wert[2] = str(int(time.time()) - 900)
    wert[3] = eigen.sign("\n".join(("GET", "/netz/segmente/x", wert[2], hashlib.sha256(b"").hexdigest())).encode()).hex()
    assert _roh(a, "GET", "/netz/segmente/x", {"Authorization": " ".join(wert)}) == 401  # veraltet


def test_ausfall_des_peers_und_rueckfall(netz):
    a, b, c = _drei(netz)
    b.log.peer_merken("http://127.0.0.1:1", "start")
    b.abgleich("http://127.0.0.1:1")
    z = b.log.db.execute("SELECT fehler, naechster FROM peer WHERE adresse = 'http://127.0.0.1:1'").fetchone()
    assert z[0] == 1 and z[1] > time.time()
    assert "http://127.0.0.1:1" not in b.log.peers_waehlen(10)


def test_gedaechtnis_weg_haelt_das_netz_nicht_an(netz):
    a, b, c = _drei(netz)
    a.mcp.objekte.append(objekt(1))
    a.runde()
    b.mcp.ausfall = True
    b.runde()
    assert b.log.koepfe()[a.log.pub] >= 3 and not b.mcp.empfangen  # getragen, noch nicht übergeben
    b.mcp.ausfall = False
    b.runde()
    assert b.mcp.texte() == [objekt(1)["text"]]


def test_nur_geglaubte_herausgeber_erreichen_das_gedaechtnis(netz):
    (sa, a_pub), (sb, _b) = netz.schluessel(), netz.schluessel()
    a = netz.baue(sa, [a_pub])
    a.log.anhaengen("einladung", {"pub": _b})
    b = netz.baue(sb, [a_pub], start=[a.k.adresse], glauben=[])
    a.mcp.objekte.append(objekt(1))
    a.mcp.widerrufe.append({"netz_id": "e" * 32, "token": "x"})
    a.runde()
    b.runde()
    assert b.mcp.texte() == [] and b.mcp.ziele() == ["e" * 32]  # getragen, nicht geglaubt; das Vergessen gilt trotzdem


def test_http_zu_fremdem_rechner_ist_verboten(netz):
    (sa, a_pub) = netz.schluessel()
    a = netz.baue(sa, [a_pub], modus="peer")
    with pytest.raises(ValueError, match="unverschlüsselt"):
        a._anfrage("http://peer.example", "GET", "/netz/gesund")


def _zertifikat(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "test")])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(jetzt).not_valid_after(jetzt + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False).add_extension(x509.BasicConstraints(ca=True, path_length=None), True).sign(key, hashes.SHA256()))
    c, k = tmp_path / "c.pem", tmp_path / "k.pem"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return str(c), str(k)


def test_abgleich_ueber_tls(netz, tmp_path):
    cert, key = _zertifikat(tmp_path)
    (sa, a_pub), (sb, b_pub), (sc, c_pub) = netz.schluessel(), netz.schluessel(), netz.schluessel()
    a = netz.baue(sa, [a_pub], tls_cert=cert, tls_key=key)
    a.log.anhaengen("einladung", {"pub": b_pub})
    a.log.anhaengen("einladung", {"pub": c_pub})
    a.mcp.objekte.append(objekt(1))
    a.runde()
    assert a.k.adresse.startswith("https://")
    b = netz.baue(sb, [a_pub], modus="peer", start=[a.k.adresse], ca_datei=cert)
    b.runde()
    assert b.mcp.texte() == [objekt(1)["text"]]
    c = netz.baue(sc, [a_pub], modus="peer", start=[a.k.adresse])  # ohne vertrauenswürdiges Zertifikat
    c.runde()
    assert c.log.koepfe() == {}


def test_torrent_holt_grosse_rueckstaende(netz, tmp_path):
    pytest.importorskip("libtorrent")
    (sa, a_pub), (sb, b_pub) = netz.schluessel(), netz.schluessel()
    t = {"aktiv": True, "port": 0, "segment": 10, "ab": 5, "warte_s": 30}
    a = netz.baue(sa, [a_pub], torrent={**t, "verzeichnis": str(tmp_path / "ta")})
    a.log.anhaengen("einladung", {"pub": b_pub})
    a.mcp.objekte.extend(objekt(i) for i in range(25))
    a.runde()
    assert a.log.status()["segmente"] >= 1 and a.log.segmente(a.log.pub)[0]["von"] == 1
    b = netz.baue(sb, [a_pub], modus="peer", start=[a.k.adresse], torrent={**t, "verzeichnis": str(tmp_path / "tb")})
    b.runde()
    assert b.statistik["per_torrent"] >= 10 and b.log.koepfe()[a.log.pub] == a.log.koepfe()[a.log.pub]
    assert len(b.mcp.texte()) == 25
    # ein vergessenes Objekt lässt das Segment verschwinden
    nid = objekt(3)["netz_id"]
    a.mcp.objekte = [o for o in a.mcp.objekte if o["netz_id"] != nid]
    a.mcp.widerrufe.append({"netz_id": nid, "token": "t3"})
    assert a.ausgang() == 1
    assert all(not (s["von"] <= 5 <= s["bis"]) for s in a.log.segmente(a.log.pub))


def test_ohne_libtorrent_bleibt_https(netz, tmp_path, monkeypatch):
    from vi_mcp import netz_torrent
    monkeypatch.setattr(netz_torrent, "verfuegbar", lambda: False)
    (sa, a_pub) = netz.schluessel()
    a = netz.baue(sa, [a_pub], torrent={"aktiv": True})
    assert a.schwarm is None


def test_adresse_hinter_reverse_proxy():
    assert lb.steuer_form("adresse", {"adresse": "https://wissen.example/vi-p2p"})
    assert lb.steuer_form("adresse", {"adresse": "https://wissen.example:8443/a/b"})
    for falsch in ("https://wissen.example/", "https://wissen.example/x?y=1", "ftp://wissen.example", "https://wissen.example/../x y"):
        assert not lb.steuer_form("adresse", {"adresse": falsch}), falsch


def test_abgleich_ueber_pfad_praefix(netz):
    """Wie hinter nginx: der Peer erreicht den Dienst unter /vi-p2p, der Dienst sieht /netz/…"""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    (sa, a_pub), (sb, b_pub) = netz.schluessel(), netz.schluessel()
    a = netz.baue(sa, [a_pub])
    a.log.anhaengen("einladung", {"pub": b_pub})
    a.mcp.objekte.append(objekt(1))
    a.runde()
    ziel = a.port()

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _weiter(self):
            assert self.path.startswith("/vi-p2p/")
            c = http.client.HTTPConnection("127.0.0.1", ziel, timeout=10)
            koerper = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            c.request(self.command, self.path[len("/vi-p2p"):], body=koerper or None, headers={k: v for k, v in self.headers.items() if k.lower() in ("authorization", "content-type")})
            r = c.getresponse()
            d = r.read()
            self.send_response(r.status)
            self.send_header("Content-Length", str(len(d)))
            self.end_headers()
            self.wfile.write(d)
        do_GET = do_POST = _weiter
    p = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=p.serve_forever, daemon=True).start()
    try:
        b = netz.baue(sb, [a_pub], modus="peer", start=[f"http://127.0.0.1:{p.server_address[1]}/vi-p2p"])
        b.runde()
        assert b.mcp.texte() == [objekt(1)["text"]]
    finally:
        p.shutdown()
        p.server_close()
