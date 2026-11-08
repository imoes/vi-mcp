"""0.15.0: Beitritt mit Code, selbstsigniertes TLS mit Pin, HTTPS-Proxy, Befehle für weitere Peers."""
import json
import select
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from vi_mcp import logbuch as lb  # noqa: E402
from vi_mcp import netz_cli  # noqa: E402
from vi_mcp import netzdienst as nd  # noqa: E402

from test_netz import Gedaechtnis, objekt, netz  # noqa: E402,F401


def test_code_hin_und_zurueck():
    g = ["a" * 64]
    c = nd.code_bauen(g, "https://wissen.example/vi-p2p", "b" * 64, "geheim", time.time() + 60)
    d = nd.code_lesen(c)
    assert d["g"] == g and d["s"] == "https://wissen.example/vi-p2p" and d["p"] == "b" * 64 and d["n"] == "geheim"
    for kaputt, grund in ((c[:-6], "beschädigt|Gründer|Adresse"), ("xyz", "kein Beitrittscode"), (nd.code_bauen(g, "https://w.example", None, "n", time.time() - 1), "abgelaufen"),
                          (nd.code_bauen(["x"], "https://w.example", None, "n", time.time() + 9), "Gründer"), (nd.code_bauen(g, "https://w.example/", None, "n", time.time() + 9), "Adresse")):
        with pytest.raises(ValueError, match=grund):
            nd.code_lesen(kaputt)


def _zert(tmp_path, host="127.0.0.1"):
    c, k = tmp_path / "c.pem", tmp_path / "k.pem"
    netz_cli._zertifikat_erzeugen(f"https://{host}:1", c, k)
    return str(c), str(k)


def test_beitritt_ueber_tls_mit_pin(netz, tmp_path):
    cert, key = _zert(tmp_path)
    (sa, a_pub), (sb, b_pub) = netz.schluessel(), netz.schluessel()
    a = netz.baue(sa, [a_pub], tls_cert=cert, tls_key=key)
    a.mcp.objekte.append(objekt(1))
    a.runde()
    assert a.log.letzte_eigene_adresse()["pin"] == nd.zertifikat_pin(Path(cert))
    nonce = "einmal-und-nie-wieder"
    a.log.beitritt_anlegen(nonce, 60)
    b = netz.baue(sb, [a_pub], modus="peer")
    with pytest.raises(ValueError, match="CERTIFICATE_VERIFY_FAILED|certificate verify failed"):
        b._anfrage(a.k.adresse, "POST", "/netz/beitritt", {"code": nonce})  # ohne Pin und ohne CA kein Vertrauen
    b.log.peer_merken(a.k.adresse, "beitritt", "f" * 64)
    with pytest.raises(ValueError, match="Pin"):
        b._anfrage(a.k.adresse, "POST", "/netz/beitritt", {"code": nonce})
    b.log.peer_merken(a.k.adresse, "beitritt", nd.zertifikat_pin(Path(cert)))
    assert b._anfrage(a.k.adresse, "POST", "/netz/beitritt", {"code": nonce}) == {"eingeladen": lb.pseudonym(b_pub)}
    with pytest.raises(ValueError, match="403.*schon benutzt"):
        b._anfrage(a.k.adresse, "POST", "/netz/beitritt", {"code": nonce})
    assert a.log.ist_mitglied(b_pub)
    b.mcp.objekte.append(objekt(2))
    b.runde()
    a.runde()
    assert b.mcp.texte() == [objekt(1)["text"]] and a.mcp.texte() == [objekt(2)["text"]]


def test_abgelaufener_code_und_ohne_signatur(netz):
    (sa, a_pub), (sb, _b) = netz.schluessel(), netz.schluessel()
    a = netz.baue(sa, [a_pub])
    a.log.beitritt_anlegen("alt", -1)
    b = netz.baue(sb, [a_pub], modus="peer")
    with pytest.raises(ValueError, match="403.*abgelaufen"):
        b._anfrage(a.k.adresse, "POST", "/netz/beitritt", {"code": "alt"})
    with pytest.raises(ValueError, match="403"):
        b._anfrage(a.k.adresse, "POST", "/netz/beitritt", {"code": "gibtsnicht"})
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", a.port(), timeout=5)
    c.request("POST", "/netz/beitritt", body=b'{"code":"alt"}')
    assert c.getresponse().status == 401


def test_pin_wandert_mit_der_adresse(netz, tmp_path):
    cert, key = _zert(tmp_path)
    (sa, a_pub), (sb, b_pub), (sc, c_pub) = netz.schluessel(), netz.schluessel(), netz.schluessel()
    b = netz.baue(sb, [a_pub])  # b ist peerhost ohne eigenes TLS (lokal), a mit selbstsigniertem
    a = netz.baue(sa, [a_pub], tls_cert=cert, tls_key=key, start=[b.k.adresse])
    a.log.anhaengen("einladung", {"pub": b_pub})
    a.log.anhaengen("einladung", {"pub": c_pub})
    a.runde()  # a schiebt sein Logbuch samt Adresse und Pin zu b
    c = netz.baue(sc, [a_pub], modus="peer", start=[b.k.adresse])
    c.runde()
    assert c.log.pin(a.k.adresse) == nd.zertifikat_pin(Path(cert))
    a.mcp.objekte.append(objekt(3))
    a.runde()
    assert c.abgleich(a.k.adresse) >= 1 and objekt(3)["text"] in c.mcp.texte() + [x["inhalt"]["text"] for x in c.log.lies(a_pub, 0) if x["kopf"]["typ"] == "objekt"]


class ConnectProxy:
    """Ein winziger HTTPS-Proxy: merkt sich jedes CONNECT-Ziel und leitet an 127.0.0.1 weiter."""

    def __init__(self):
        self.ziele = []
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(8)
        self.port = self.s.getsockname()[1]
        threading.Thread(target=self._lauf, daemon=True).start()

    def _lauf(self):
        while True:
            try:
                k, _ = self.s.accept()
            except OSError:
                return
            threading.Thread(target=self._eins, args=(k,), daemon=True).start()

    def _eins(self, k):
        kopf = b""
        while b"\r\n\r\n" not in kopf:
            kopf += k.recv(4096)
        ziel = kopf.split(b" ")[1].decode()
        self.ziele.append(ziel)
        z = socket.create_connection(("127.0.0.1", int(ziel.rsplit(":", 1)[1])))
        k.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        try:
            while True:
                r, _, _ = select.select([k, z], [], [], 10)
                if not r:
                    break
                for q in r:
                    d = q.recv(65536)
                    if not d:
                        return
                    (z if q is k else k).sendall(d)
        finally:
            k.close()
            z.close()


def test_https_ueber_proxy(netz, tmp_path):
    cert, key = _zert(tmp_path, "peer.wissen.test")
    (sa, a_pub), (sb, b_pub) = netz.schluessel(), netz.schluessel()
    a = netz.baue(sa, [a_pub], tls_cert=cert, tls_key=key)
    a.log.anhaengen("einladung", {"pub": b_pub})
    a.mcp.objekte.append(objekt(4))
    a.runde()
    p = ConnectProxy()
    fern = f"https://peer.wissen.test:{a.port()}"  # nur über den Proxy erreichbar: der Name existiert nicht
    b = netz.baue(sb, [a_pub], modus="peer", proxy=f"http://127.0.0.1:{p.port}")
    b.log.peer_merken(fern, "beitritt", nd.zertifikat_pin(Path(cert)))
    b.runde()
    assert b.mcp.texte() == [objekt(4)["text"]] and f"peer.wissen.test:{a.port()}" in p.ziele
    b.k.kein_proxy = ["wissen.test"]
    with pytest.raises(OSError):  # ohne Proxy ist der Name nicht auflösbar
        b._anfrage(fern, "POST", "/netz/koepfe", {"koepfe": {}})
    p.s.close()


def test_befehle_von_ende_zu_ende(tmp_path, monkeypatch, capsys):
    """einrichten --tls-selbst → einladung → beitreten → peers, wie auf echten Servern, nur ohne systemd."""
    monkeypatch.setenv("VI_MCP_KEIN_DIENST", "1")
    token = tmp_path / "mcp-token"
    token.write_text("t\n")
    frei = socket.socket()
    frei.bind(("127.0.0.1", 0))
    port = frei.getsockname()[1]
    frei.close()

    def konf(name, **kw):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps({"db": str(tmp_path / name / "netz.db"), "seed": str(tmp_path / name / "schluessel"), "mcp_token_datei": str(token), **kw}))
        (tmp_path / name).mkdir()
        monkeypatch.setenv("VI_P2P_CONFIG", str(p))
        return p
    konf("a", bind="127.0.0.1", port=port)
    assert netz_cli.main(["einrichten", "--modus", "peerhost", "--gruenden", "--adresse", f"https://127.0.0.1:{port}", "--tls-selbst"]) == 0
    ka = nd.lade()
    assert ka.tls_cert and Path(ka.tls_cert).exists()
    a = nd.Netzdienst(ka, Gedaechtnis())
    a.starte_server()
    try:
        a.runde()
        capsys.readouterr()
        assert netz_cli.main(["einladung", "--stunden", "1"]) == 0
        code = capsys.readouterr().out.strip()
        assert code.startswith("vinetz1.") and nd.code_lesen(code)["p"] == nd.zertifikat_pin(Path(ka.tls_cert))
        konf("b")
        assert netz_cli.main(["beitreten", code]) == 0
        assert "Aufgenommen als vi-" in capsys.readouterr().out
        kb = nd.lade()
        assert kb.modus == "peer" and kb.gruender == ka.gruender and kb.startpeers == [f"https://127.0.0.1:{port}"]
        assert netz_cli.main(["beitreten", code]) == 1  # zweimal geht nicht
        b = nd.Netzdienst(kb, Gedaechtnis())
        a.mcp.objekte.append(objekt(5))
        a.runde()
        b.runde()
        assert b.mcp.texte() == [objekt(5)["text"]]
        b.stoppe()
        capsys.readouterr()
        assert netz_cli.main(["peers"]) == 0
        assert "Pin " in capsys.readouterr().out
        monkeypatch.setenv("VI_P2P_CONFIG", str(tmp_path / "a.json"))
        assert netz_cli.main(["einrichten", "--modus", "peer", "--gruender", "a" * 64, "--tls-selbst"]) == 2
    finally:
        a.stoppe()
