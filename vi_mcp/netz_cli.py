"""vi-mcp netz … — Modus wählen, Einladungen, Stand. Zustand liegt im Logbuch; der Dienst läuft als eigener Nutzer."""
from __future__ import annotations

import argparse
import datetime
import ipaddress
import json
import os
import pwd
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from . import konfig, logbuch as lb, netzdienst as nd

DIENST_NUTZER = "vi-p2p"


def _als_dienstnutzer() -> None:
    """Datenbank und Begleitdateien müssen dem Dienst gehören."""
    if os.geteuid() != 0:
        return
    try:
        p = pwd.getpwnam(DIENST_NUTZER)
    except KeyError:
        return
    os.setgroups([])
    os.setgid(p.pw_gid)
    os.setuid(p.pw_uid)


def _logbuch(k: nd.NetzKonfig) -> lb.Logbuch:
    return lb.Logbuch(Path(k.db), Path(k.seed), k.gruender)


def _als_dienst(fn) -> int:
    """fn mit den Rechten des Dienstnutzers ausführen. Als root in einem Kindprozess, sonst direkt."""
    if os.geteuid() != 0:
        return fn()
    sys.stdout.flush()  # sonst erscheint gepufferter Text des Elternprozesses erst nach dem des Kindes
    sys.stderr.flush()
    kind = os.fork()
    if kind == 0:
        code = 1
        try:
            _als_dienstnutzer()
            code = fn()
        except Exception as e:  # noqa: BLE001 — der Kindprozess meldet jeden Fehler und endet
            print(f"Fehler: {type(e).__name__}: {e}", file=sys.stderr)
        finally:
            sys.stdout.flush()
            os._exit(code)
    return os.waitstatus_to_exitcode(os.waitpid(kind, 0)[1])


def _zertifikat_erzeugen(adresse: str, cert: Path, key: Path) -> None:
    """Selbstsigniert, zehn Jahre: Gültigkeit beweist hier nichts, das tut der Pin im Logbuch."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    host = urllib.parse.urlsplit(adresse).hostname or ""
    try:
        san = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        san = x509.DNSName(host)
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "vi-p2p")])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(jetzt - datetime.timedelta(minutes=5)).not_valid_after(jetzt + datetime.timedelta(days=3650))
         .add_extension(x509.SubjectAlternativeName([san]), False).sign(k, hashes.SHA256()))
    with os.fdopen(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))


def _dienst(*befehl: str) -> str | None:
    if os.environ.get("VI_MCP_KEIN_DIENST"):
        return "Dienststeuerung abgeschaltet (VI_MCP_KEIN_DIENST)"
    if not shutil.which("systemctl"):
        return "systemctl fehlt"
    r = subprocess.run(["systemctl", *befehl], capture_output=True, text=True)
    return None if r.returncode == 0 else r.stderr.strip()[:200]


def _schreibe(p: Path, roh: dict) -> None:
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(roh, indent=2, ensure_ascii=False) + "\n")
    if os.geteuid() == 0:
        try:
            shutil.chown(tmp, "root", DIENST_NUTZER)
        except (LookupError, PermissionError):
            pass
    os.replace(tmp, p)


def einrichten(o) -> int:
    p = nd.pfad()
    roh = json.loads(p.read_text()) if p.exists() else {}
    k_alt = nd.NetzKonfig(**{a: b for a, b in roh.items() if a in nd.NetzKonfig.__dataclass_fields__})
    roh["modus"] = o.modus
    for feld in ("adresse", "bind", "port", "tls_cert", "tls_key", "ca_datei"):
        if getattr(o, feld) is not None:
            roh[feld] = getattr(o, feld)
    if o.start:
        roh["startpeers"] = sorted(set(roh.get("startpeers", [])) | set(o.start))
    if o.http_erlaubt:
        roh["http_erlaubt"] = True
    if o.proxy is not None:
        roh["proxy"] = o.proxy or None
    if o.kein_proxy:
        roh["kein_proxy"] = sorted(set(roh.get("kein_proxy", [])) | set(o.kein_proxy))
    if o.torrent:
        roh["torrent"] = {**roh.get("torrent", {}), "aktiv": True}
    if o.modus == "standalone":
        _schreibe(p, roh)
        if grund := _dienst("disable", "--now", "vi-p2p"):
            print(f"Hinweis: {grund}")
        print("Modus standalone: Der Netzdienst läuft nicht. Das Logbuch bleibt erhalten.")
        return 0
    seed = Path(roh.get("seed") or k_alt.seed)
    if not seed.exists():
        kind = os.fork()
        if kind == 0:
            _als_dienstnutzer()
            lb.schluessel_erzeugen(seed)
            os._exit(0)
        os.waitpid(kind, 0)
    # der Seed gehört dem Dienstnutzer und root liest ihn nur, um das Pseudonym zu nennen
    pub = lb.oeffentlich_hex(lb.privat(seed))
    if o.gruenden:
        roh["gruender"] = sorted(set(roh.get("gruender", [])) | {pub})
    if o.gruender:
        roh["gruender"] = sorted(set(roh.get("gruender", [])) | set(o.gruender))
    if not roh.get("gruender"):
        print("Gründer fehlt: --gruenden für ein neues Netz oder --gruender SCHLUESSEL zum Beitreten", file=sys.stderr)
        return 2
    if o.modus == "peerhost" and not roh.get("adresse"):
        print("peerhost braucht --adresse https://name:port, sonst findet ihn niemand", file=sys.stderr)
        return 2
    if o.tls_selbst:
        if o.modus != "peerhost":
            print("--tls-selbst gilt nur für peerhost", file=sys.stderr)
            return 2
        verz = Path(roh.get("db") or k_alt.db).parent
        cert, key = verz / "tls-cert.pem", verz / "tls-key.pem"
        if not cert.exists():
            _als_dienst(lambda: _zertifikat_erzeugen(roh["adresse"], cert, key) or 0)
        roh["tls_cert"], roh["tls_key"] = str(cert), str(key)
    token_datei = Path(roh.get("mcp_token_datei") or k_alt.mcp_token_datei)
    if not token_datei.exists():
        token = konfig.instanz_anlegen("p2p")
        fd = os.open(token_datei, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
        if os.geteuid() == 0:
            shutil.chown(token_datei, "root", DIENST_NUTZER)
        if grund := _dienst("restart", "vi-mcp"):
            print(f"Hinweis: vi-mcp nicht neu gestartet: {grund}")
    _schreibe(p, roh)
    if grund := _dienst("enable", "vi-p2p"):
        print(f"Hinweis: {grund}")
    if grund := _dienst("restart", "vi-p2p"):
        print(f"Hinweis: {grund}")
    print(f"Modus {o.modus}. Schlüssel dieses Servers: {pub}\nPseudonym: {lb.pseudonym(pub)}")
    if not o.gruenden and pub not in roh["gruender"] and not getattr(o, "still", False):
        print("Beitreten: Ein Mitglied führt aus:  vi-mcp netz einladen " + pub)
    return 0


def beitreten(o) -> int:
    try:
        d = nd.code_lesen(o.code)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    e = argparse.Namespace(modus=o.modus, adresse=o.adresse, bind=None, port=None, tls_cert=None, tls_key=None, ca_datei=None, gruenden=False, gruender=d["g"], start=[d["s"]],
                           http_erlaubt=o.http_erlaubt, torrent=False, tls_selbst=o.tls_selbst, proxy=o.proxy, kein_proxy=o.kein_proxy, still=True)
    if (code := einrichten(e)) != 0:
        return code

    def einloesen() -> int:
        dienst = nd.Netzdienst(nd.lade(), None)
        try:
            dienst.log.peer_merken(d["s"], "beitritt", d["p"])
            r = dienst._anfrage(d["s"], "POST", "/netz/beitritt", {"code": d["n"]})
        except (ValueError, OSError) as ex:
            print(f"Beitritt abgelehnt: {ex}", file=sys.stderr)
            return 1
        finally:
            dienst.stoppe()
        print(f"Aufgenommen als {r['eingeladen']}. Der Abgleich beginnt mit der nächsten Runde.")
        return 0
    code = _als_dienst(einloesen)
    if code == 0:
        _dienst("restart", "vi-p2p")
    return code


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser(prog="vi-mcp netz")
    u = a.add_subparsers(dest="befehl", required=True)
    e = u.add_parser("einrichten")
    e.add_argument("--modus", choices=nd.MODI, required=True)
    e.add_argument("--adresse")
    e.add_argument("--bind")
    e.add_argument("--port", type=int)
    e.add_argument("--tls-cert", dest="tls_cert")
    e.add_argument("--tls-key", dest="tls_key")
    e.add_argument("--ca-datei", dest="ca_datei")
    e.add_argument("--gruenden", action="store_true", help="dieser Server gründet ein neues Netz")
    e.add_argument("--gruender", action="append", default=[], help="öffentlicher Schlüssel eines Gründers")
    e.add_argument("--start", action="append", default=[], help="Adresse eines bekannten Peers")
    e.add_argument("--http-erlaubt", dest="http_erlaubt", action="store_true")
    e.add_argument("--torrent", action="store_true")
    e.add_argument("--tls-selbst", dest="tls_selbst", action="store_true", help="selbstsigniertes Zertifikat erzeugen; Peers prüfen es über den Pin im Logbuch")
    e.add_argument("--proxy", help="HTTPS-Proxy für fremde Peers, z. B. http://proxy:3128 (leer = keiner)")
    e.add_argument("--kein-proxy", dest="kein_proxy", action="append", default=[], help="Domain, für die kein Proxy gilt")
    for name in ("einladen", "ausschliessen"):
        x = u.add_parser(name)
        x.add_argument("schluessel")
    ei = u.add_parser("einladung", help="einmaligen Beitrittscode erzeugen (nur auf einem peerhost)")
    ei.add_argument("--stunden", type=float, default=24)
    bt = u.add_parser("beitreten", help="mit einem Beitrittscode einem Netz beitreten")
    bt.add_argument("code")
    bt.add_argument("--modus", choices=("peer", "peerhost"), default="peer")
    bt.add_argument("--adresse")
    bt.add_argument("--tls-selbst", dest="tls_selbst", action="store_true")
    bt.add_argument("--proxy")
    bt.add_argument("--kein-proxy", dest="kein_proxy", action="append", default=[])
    bt.add_argument("--http-erlaubt", dest="http_erlaubt", action="store_true")
    u.add_parser("peers")
    u.add_parser("id")
    u.add_parser("status")
    u.add_parser("lauf")
    o = a.parse_args(argv)
    if o.befehl == "einrichten":
        return einrichten(o)
    if o.befehl == "lauf":
        return nd.main()
    if o.befehl == "beitreten":
        return beitreten(o)
    _als_dienstnutzer()
    k = nd.lade()
    if not Path(k.seed).exists():
        print("Noch nicht eingerichtet: vi-mcp netz einrichten --modus …", file=sys.stderr)
        return 2
    log = _logbuch(k)
    if o.befehl == "id":
        print(f"{log.pub}\n{lb.pseudonym(log.pub)}")
        return 0
    if o.befehl == "einladung":
        if k.modus != "peerhost" or not k.adresse:
            print("Beitrittscodes gibt nur ein peerhost mit Adresse aus: Der neue Server löst den Code dort ein.", file=sys.stderr)
            return 2
        if not log.ist_mitglied(log.pub):
            print("Dieser Server ist selbst noch kein Mitglied.", file=sys.stderr)
            return 2
        nonce = secrets.token_urlsafe(24)
        log.beitritt_anlegen(nonce, o.stunden * 3600)
        pin = nd.zertifikat_pin(Path(k.tls_cert)) if k.tls_cert else None
        print(nd.code_bauen(sorted(k.gruender), k.adresse.rstrip("/"), pin, nonce, time.time() + o.stunden * 3600))
        print(f"Einmalig, gültig {o.stunden:g} h. Wie ein Passwort behandeln: Wer ihn hat, wird Mitglied. Auf dem neuen Server:  sudo vi-mcp netz beitreten <code>", file=sys.stderr)
        return 0
    if o.befehl == "peers":
        for p in log.peers():
            stand = "erreichbar" if p["fehler"] == 0 and p["zuletzt"] else "noch nie erreicht" if not p["zuletzt"] else f"{p['fehler']} Fehler in Folge"
            print(f"{p['adresse']:45} {p['quelle']:9} {'Pin ' + p['pin'][:12] if p['pin'] else 'CA':16} {stand}")
        return 0
    if o.befehl in ("einladen", "ausschliessen"):
        try:
            log.anhaengen("einladung" if o.befehl == "einladen" else "ausschluss", {"pub": o.schluessel})
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 2
        print(f"{'Eingeladen' if o.befehl == 'einladen' else 'Ausgeschlossen'}: {lb.pseudonym(o.schluessel)}. Das Netz erfährt es beim nächsten Abgleich.")
        return 0
    st = log.status()
    print(f"Modus {k.modus} · Pseudonym {lb.pseudonym(log.pub)} · {'Mitglied' if log.ist_mitglied(log.pub) else 'noch nicht Mitglied'}")
    print(" · ".join(f"{a_} {b}" for a_, b in st.items()))
    return 0
