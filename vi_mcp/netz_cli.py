"""vi-mcp netz … — Modus wählen, Einladungen, Stand. Zustand liegt im Logbuch; der Dienst läuft als eigener Nutzer."""
from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import subprocess
import sys
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


def _dienst(*befehl: str) -> str | None:
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
    if not o.gruenden and pub not in roh["gruender"]:
        print("Beitreten: Ein Mitglied führt aus:  vi-mcp netz einladen " + pub)
    return 0


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
    for name in ("einladen", "ausschliessen"):
        x = u.add_parser(name)
        x.add_argument("schluessel")
    u.add_parser("id")
    u.add_parser("status")
    u.add_parser("lauf")
    o = a.parse_args(argv)
    if o.befehl == "einrichten":
        return einrichten(o)
    if o.befehl == "lauf":
        return nd.main()
    _als_dienstnutzer()
    k = nd.lade()
    if not Path(k.seed).exists():
        print("Noch nicht eingerichtet: vi-mcp netz einrichten --modus …", file=sys.stderr)
        return 2
    log = _logbuch(k)
    if o.befehl == "id":
        print(f"{log.pub}\n{lb.pseudonym(log.pub)}")
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
