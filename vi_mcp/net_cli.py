"""vi-mcp net … — choose a mode, invitations, status. State lives in the logbook; the service runs as its own user."""
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

from . import config, logbook as lb, net_service as nd

SERVICE_USER = "vi-p2p"


def _as_service_user() -> None:
    """Database and companion files must belong to the service."""
    if os.geteuid() != 0:
        return
    try:
        p = pwd.getpwnam(SERVICE_USER)
    except KeyError:
        return
    os.setgroups([])
    os.setgid(p.pw_gid)
    os.setuid(p.pw_uid)


def _logbook(k: nd.NetConfig) -> lb.Logbook:
    return lb.Logbook(Path(k.db), Path(k.seed), k.founders)


def _as_service(fn) -> int:
    """Run fn with the rights of the service user. As root in a child process, otherwise directly."""
    if os.geteuid() != 0:
        return fn()
    sys.stdout.flush()  # otherwise buffered text of the parent appears only after the child's
    sys.stderr.flush()
    child_pid = os.fork()
    if child_pid == 0:
        code = 1
        try:
            _as_service_user()
            code = fn()
        except Exception as e:  # noqa: BLE001 — the child process reports every error and exits
            print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        finally:
            sys.stdout.flush()
            os._exit(code)
    return os.waitstatus_to_exitcode(os.waitpid(child_pid, 0)[1])


def _create_certificate(address: str, cert: Path, key: Path) -> None:
    """Self-signed, ten years: validity proves nothing here, the pin in the logbook does."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    host = urllib.parse.urlsplit(address).hostname or ""
    try:
        san = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        san = x509.DNSName(host)
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "vi-p2p")])
    now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=3650))
         .add_extension(x509.SubjectAlternativeName([san]), False).sign(k, hashes.SHA256()))
    with os.fdopen(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))


def _service(*command: str) -> str | None:
    if os.environ.get("VI_MCP_KEIN_DIENST"):
        return "service control switched off (VI_MCP_KEIN_DIENST)"
    if not shutil.which("systemctl"):
        return "systemctl missing"
    r = subprocess.run(["systemctl", *command], capture_output=True, text=True)
    return None if r.returncode == 0 else r.stderr.strip()[:200]


def _write(p: Path, raw: dict) -> None:
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    if os.geteuid() == 0:
        try:
            shutil.chown(tmp, "root", SERVICE_USER)
        except (LookupError, PermissionError):
            pass
    os.replace(tmp, p)


def setup(o) -> int:
    p = nd.fpath()
    raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    k_old = nd.from_file(raw)
    raw["modus"] = o.mode
    for attr, key in (("address", "adresse"), ("bind", "bind"), ("port", "port"), ("tls_cert", "tls_cert"), ("tls_key", "tls_key"), ("ca_file", "ca_datei")):
        if getattr(o, attr) is not None:
            raw[key] = getattr(o, attr)
    if o.start:
        raw["startpeers"] = sorted(set(raw.get("startpeers", [])) | set(o.start))
    if o.http_allowed:
        raw["http_erlaubt"] = True
    if o.proxy is not None:
        raw["proxy"] = o.proxy or None
    if o.no_proxy:
        raw["kein_proxy"] = sorted(set(raw.get("kein_proxy", [])) | set(o.no_proxy))
    if o.torrent:
        raw["torrent"] = {**raw.get("torrent", {}), "aktiv": True}
    if o.mode == "standalone":
        _write(p, raw)
        if reason := _service("disable", "--now", "vi-p2p"):
            print(f"Hint: {reason}")
        print("Mode standalone: the network service does not run. The logbook is kept.")
        return 0
    seed = Path(raw.get("seed") or k_old.seed)
    if not seed.exists():
        child_pid = os.fork()
        if child_pid == 0:
            _as_service_user()
            lb.generate_keys(seed)
            os._exit(0)
        os.waitpid(child_pid, 0)
    # the seed belongs to the service user; root reads it only to name the pseudonym
    pub = lb.public_hex(lb.private(seed))
    if o.found:
        raw["gruender"] = sorted(set(raw.get("gruender", [])) | {pub})
    if o.founders:
        raw["gruender"] = sorted(set(raw.get("gruender", [])) | set(o.founders))
    if not raw.get("gruender"):
        print("Founder missing: --found for a new network or --founder KEY to join", file=sys.stderr)
        return 2
    if o.mode == "peerhost" and not raw.get("adresse"):
        print("peerhost needs --address https://name:port, otherwise nobody finds it", file=sys.stderr)
        return 2
    if o.tls_self:
        if o.mode != "peerhost":
            print("--tls-self applies to peerhost only", file=sys.stderr)
            return 2
        dir_path = Path(raw.get("db") or k_old.db).parent
        cert, key = dir_path / "tls-cert.pem", dir_path / "tls-key.pem"
        if not cert.exists():
            _as_service(lambda: _create_certificate(raw["adresse"], cert, key) or 0)
        raw["tls_cert"], raw["tls_key"] = str(cert), str(key)
    token_file = Path(raw.get("mcp_token_datei") or k_old.mcp_token_file)
    if not token_file.exists():
        token = config.create_instance("p2p")
        fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
        if os.geteuid() == 0:
            shutil.chown(token_file, "root", SERVICE_USER)
        if reason := _service("restart", "vi-mcp"):
            print(f"Hint: vi-mcp not restarted: {reason}")
    _write(p, raw)
    if reason := _service("enable", "vi-p2p"):
        print(f"Hint: {reason}")
    if reason := _service("restart", "vi-p2p"):
        print(f"Hint: {reason}")
    print(f"Mode {o.mode}. Key of this server: {pub}\nPseudonym: {lb.pseudonym(pub)}")
    if not o.found and pub not in raw["gruender"] and not getattr(o, "quiet", False):
        print("To join: a member runs:  vi-mcp net invite " + pub)
    return 0


def join(o) -> int:
    try:
        d = nd.read_code(o.code)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    e = argparse.Namespace(mode=o.mode, address=o.address, bind=None, port=None, tls_cert=None, tls_key=None, ca_file=None, found=False, founders=d["g"], start=[d["s"]],
                           http_allowed=o.http_allowed, torrent=False, tls_self=o.tls_self, proxy=o.proxy, no_proxy=o.no_proxy, quiet=True)
    if (code := setup(e)) != 0:
        return code

    def redeem() -> int:
        service = nd.NetService(nd.load(), None)
        try:
            service.log.peer_remember(d["s"], "beitritt", d["p"])
            r = service._request(d["s"], "POST", "/netz/beitritt", {"code": d["n"]})
        except (ValueError, OSError) as ex:
            print(f"Join refused: {ex}", file=sys.stderr)
            return 1
        finally:
            service.stop_service()
        print(f"Joined as {r['eingeladen']}. Sync starts with the next round.")
        return 0
    code = _as_service(redeem)
    if code == 0:
        _service("restart", "vi-p2p")
    return code


def main(argv: list[str]) -> int:
    a = argparse.ArgumentParser(prog="vi-mcp net")
    u = a.add_subparsers(dest="subcommand", required=True)

    def cmd(name: str, alias: str | None = None, **kw):
        sp = u.add_parser(name, aliases=[alias] if alias else [], **kw)
        sp.set_defaults(command=name)
        return sp

    e = cmd("setup", "einrichten")
    e.add_argument("--mode", "--modus", dest="mode", choices=nd.MODES, required=True)
    e.add_argument("--address", "--adresse", dest="address")
    e.add_argument("--bind")
    e.add_argument("--port", type=int)
    e.add_argument("--tls-cert", dest="tls_cert")
    e.add_argument("--tls-key", dest="tls_key")
    e.add_argument("--ca-file", "--ca-datei", dest="ca_file")
    e.add_argument("--found", "--gruenden", dest="found", action="store_true", help="this server founds a new network")
    e.add_argument("--founder", "--gruender", dest="founders", action="append", default=[], help="public key of a founder")
    e.add_argument("--start", action="append", default=[], help="address of a known peer")
    e.add_argument("--http-allowed", "--http-erlaubt", dest="http_allowed", action="store_true")
    e.add_argument("--torrent", action="store_true")
    e.add_argument("--tls-self", "--tls-selbst", dest="tls_self", action="store_true", help="create a self-signed certificate; peers check it via the pin in the logbook")
    e.add_argument("--proxy", help="HTTPS proxy for foreign peers, e.g. http://proxy:3128 (empty = none)")
    e.add_argument("--no-proxy", "--kein-proxy", dest="no_proxy", action="append", default=[], help="domain for which no proxy applies")
    for name, alias in (("invite", "einladen"), ("exclude", "ausschliessen")):
        x = cmd(name, alias)
        x.add_argument("key_", metavar="key")
    ei = cmd("invitation", "einladung", help="create a one-time join code (peerhost only)")
    ei.add_argument("--hours", "--stunden", dest="hours", type=float, default=24)
    bt = cmd("join", "beitreten", help="join a network with a join code")
    bt.add_argument("code")
    bt.add_argument("--mode", "--modus", dest="mode", choices=("peer", "peerhost"), default="peer")
    bt.add_argument("--address", "--adresse", dest="address")
    bt.add_argument("--tls-self", "--tls-selbst", dest="tls_self", action="store_true")
    bt.add_argument("--proxy")
    bt.add_argument("--no-proxy", "--kein-proxy", dest="no_proxy", action="append", default=[])
    bt.add_argument("--http-allowed", "--http-erlaubt", dest="http_allowed", action="store_true")
    cmd("peers")
    cmd("id")
    cmd("status")
    cmd("run", "lauf")
    o = a.parse_args(argv)
    if o.command == "setup":
        return setup(o)
    if o.command == "run":
        return nd.main()
    if o.command == "join":
        return join(o)
    _as_service_user()
    k = nd.load()
    if not Path(k.seed).exists():
        print("Not set up yet: vi-mcp net setup --mode …", file=sys.stderr)
        return 2
    log = _logbook(k)
    if o.command == "id":
        print(f"{log.pub}\n{lb.pseudonym(log.pub)}")
        return 0
    if o.command == "invitation":
        if k.mode != "peerhost" or not k.address:
            print("Only a peerhost with an address issues join codes: the new server redeems the code there.", file=sys.stderr)
            return 2
        if not log.is_member(log.pub):
            print("This server is not a member itself yet.", file=sys.stderr)
            return 2
        nonce = secrets.token_urlsafe(24)
        log.create_join(nonce, o.hours * 3600)
        pin = nd.certificate_pin(Path(k.tls_cert)) if k.tls_cert else None
        print(nd.build_code(sorted(k.founders), k.address.rstrip("/"), pin, nonce, time.time() + o.hours * 3600))
        print(f"One-time, valid {o.hours:g} h. Treat it like a password: whoever has it becomes a member. On the new server:  sudo vi-mcp net join <code>", file=sys.stderr)
        return 0
    if o.command == "peers":
        for p in log.peers():
            progress = "reachable" if p["fehler"] == 0 and p["zuletzt"] else "never reached" if not p["zuletzt"] else f"{p['fehler']} errors in a row"
            print(f"{p['adresse']:45} {p['quelle']:9} {'Pin ' + p['pin'][:12] if p['pin'] else 'CA':16} {progress}")
        return 0
    if o.command in ("invite", "exclude"):
        try:
            log.attach("einladung" if o.command == "invite" else "ausschluss", {"pub": o.key_})
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 2
        print(f"{'Invited' if o.command == 'invite' else 'Excluded'}: {lb.pseudonym(o.key_)}. The network learns of it at the next sync.")
        return 0
    st = log.status()
    print(f"Mode {k.mode} · pseudonym {lb.pseudonym(log.pub)} · {'member' if log.is_member(log.pub) else 'not a member yet'}")
    print(" · ".join(f"{a_} {b}" for a_, b in st.items()))
    return 0
