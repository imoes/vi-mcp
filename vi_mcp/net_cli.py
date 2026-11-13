"""vi-mcp net … — choose a mode, invitations, status. State lives in the logbook; the service runs as its own user."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from . import config, logbook as lb, net_service as nd

try:
    import pwd
except ImportError:  # Windows (0.54.0): no service user, the data folder is for SYSTEM and administrators only
    pwd = None

SERVICE_USER = "vi-p2p"
#: 0.39.0: systemd unit of the network being worked on — vi-p2p for the network standard, vi-p2p@<netz> for a further one
SERVICE = "vi-p2p"
NETWORK: str | None = None


def _root() -> bool:
    """True as root on Linux. On Windows never: there is no separate service user to switch to (0.54.0)."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _as_service_user() -> None:
    """Database and companion files must belong to the service."""
    if not _root() or pwd is None:
        return
    try:
        p = pwd.getpwnam(SERVICE_USER)
    except KeyError:
        return
    os.setgroups([])
    os.setgid(p.pw_gid)
    os.setuid(p.pw_uid)


#: 0.40.0: every network on port 443 — TLS ends at the reverse proxy, each network under its own path, the services listen on localhost
PUBLIC_PREFIX = "/vi-p2p"
FIRST_LOCAL_PORT = 8766
FIRST_SEARCH_PORT = 9766  # 0.42.0: local listener for the memory's live searches


def public_address(url: str, net: str) -> str:
    """Pure. https://HOST → https://HOST/vi-p2p/<net>. Only https on port 443 without a path: the network wiki runs over TLS on 443."""
    u = urllib.parse.urlsplit((url or "").strip())
    try:
        port = u.port
    except ValueError:
        port = -1
    if u.scheme != "https" or not u.hostname or port not in (None, 443) or u.path not in ("", "/") or u.query or u.fragment:
        raise ValueError("--public needs https://HOST (port 443, no path): every network runs over TLS on 443, each under /vi-p2p/<network>")
    return f"https://{u.hostname}{PUBLIC_PREFIX}/{net}"


def network_configs(directory: Path) -> dict[str, dict]:
    """network name → its config (config.json is the network standard)."""
    out = {}
    for f in sorted(Path(directory).glob("*.json")):
        try:
            raw = nd.english_file(json.loads(f.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            continue
        out["standard" if f.stem == "config" else f.stem] = raw
    return out


def _bound(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
        try:
            sk.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def free_port(used: set[int], start: int = FIRST_LOCAL_PORT) -> int:
    """The first port from start that no other network uses, that is not the embedding service's default port (8767 — before 0.51.0 a
    second network got it too) and that nothing listens on right now."""
    from . import embed_service
    p = start
    while p in used or p == embed_service.DEFAULT_PORT or _bound(p):
        p += 1
    return p


def nginx_snippet(confs: dict[str, dict]) -> str:
    """Pure. The location blocks for every network published under /vi-p2p/<name> — for the server block that listens on 443."""
    lines = ["# vi-mcp network wiki: every network on port 443, TLS ends here (vi-mcp net proxy-config)",
             "# inside the server { listen 443 ssl; … } block; then: nginx -t && systemctl reload nginx"]
    n = 0
    for name, raw in sorted(confs.items()):
        addr = str(raw.get("address") or "")
        if raw.get("mode") != "peerhost" or urllib.parse.urlsplit(addr).path != f"{PUBLIC_PREFIX}/{name}":
            continue
        n += 1
        lines += [f"location {PUBLIC_PREFIX}/{name}/ {{  # network {name} ({raw.get('kind', 'open')})",
                  f"    proxy_pass http://{raw.get('bind') if raw.get('bind') not in (None, '0.0.0.0', '::') else '127.0.0.1'}:{int(raw.get('port', FIRST_LOCAL_PORT))}/;",
                  "    proxy_set_header Host $host;",
                  "    proxy_http_version 1.1;",
                  "    client_max_body_size 2m;  # the service accepts at most 1 MiB per request",
                  "    proxy_read_timeout 120s;",
                  "}"]
    if not n:
        lines.append("# no network is published on 443 yet: vi-mcp net [--network NAME] setup --mode peerhost --public https://HOST …")
    return "\n".join(lines)


def _logbook(k: nd.NetConfig) -> lb.Logbook:
    return lb.Logbook(k.db, Path(k.seed), k.founders, schema=lb.schema_for(k.net))


def _as_service(fn) -> int:
    """Run fn with the rights of the service user. As root in a child process, otherwise directly."""
    if not _root():
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


def task_name(unit: str) -> str:
    """Pure. systemd unit → Windows scheduled task: vi-p2p@wiki → vi-p2p-wiki, vi-p2p and vi-mcp keep their names (0.54.0)."""
    return unit.replace("@", "-")


#: 0.54.0: the systemd verbs used here, as PowerShell on a scheduled task ({t} task name, {cmd} the task's command file, {net} the network)
_TASK_PS = {
    "enable": "if (-not (Get-ScheduledTask -TaskName '{t}' -ErrorAction SilentlyContinue)) {{"
              " $a = New-ScheduledTaskAction -Execute '{cmd}' -Argument '{net}' -WorkingDirectory $env:ProgramData;"
              " $p = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest;"
              " $s = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)"
              " -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -StartWhenAvailable;"
              " Register-ScheduledTask -TaskName '{t}' -Action $a -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $p -Settings $s"
              " -Description 'vi-mcp network service ({net})' | Out-Null }} else {{ Enable-ScheduledTask -TaskName '{t}' | Out-Null }}",
    "restart": "Stop-ScheduledTask -TaskName '{t}' -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1; Start-ScheduledTask -TaskName '{t}'",
    "disable": "Stop-ScheduledTask -TaskName '{t}' -ErrorAction SilentlyContinue; Disable-ScheduledTask -TaskName '{t}' | Out-Null",
    "is-active": "$x = Get-ScheduledTask -TaskName '{t}' -ErrorAction SilentlyContinue; if ($x) {{ \"$($x.State)\".ToLower() }} else {{ 'not set up' }}",
}


def _task(*command: str) -> tuple[str | None, str]:
    """Windows: the systemctl verbs on scheduled tasks. Returns (error or None, output)."""
    verb, unit = command[0], command[-1]
    t = task_name(unit)
    net = unit.split("@", 1)[1] if "@" in unit else "standard"
    cmd = Path(sys.prefix).parent / "vi-p2p.cmd"  # install dir: the venv lives in <install dir>\venv
    if verb == "enable" and not cmd.exists():
        return f"{cmd} missing (installed by the MSI)", ""
    ps = _TASK_PS[verb].format(t=t, cmd=str(cmd).replace("'", "''"), net=net)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True)
    return (None if r.returncode == 0 and not r.stderr.strip() else (r.stderr.strip() or f"exit {r.returncode}")[:200]), r.stdout.strip()


def service_state(unit: str) -> str:
    """active / inactive / … from systemd, on Windows the state of the scheduled task (running, ready, disabled); 'not checked' without either."""
    if os.environ.get("VI_MCP_KEIN_DIENST"):
        return "not checked"
    if nd.WINDOWS:
        return _task("is-active", unit)[1] or "unknown"
    if not shutil.which("systemctl"):
        return "not checked"
    return subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True).stdout.strip() or "unknown"


def _service(*command: str) -> str | None:
    if os.environ.get("VI_MCP_KEIN_DIENST"):
        return "service control switched off (VI_MCP_KEIN_DIENST)"
    if nd.WINDOWS:  # 0.54.0: scheduled tasks instead of systemd
        if command[0] == "disable" and "--now" not in command:
            command = ("disable", command[-1])
        return _task(*command)[0]
    if not shutil.which("systemctl"):
        return "systemctl missing"
    r = subprocess.run(["systemctl", *command], capture_output=True, text=True)
    return None if r.returncode == 0 else r.stderr.strip()[:200]


def _write(p: Path, raw: dict) -> None:
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    if _root():
        try:
            shutil.chown(tmp, "root", SERVICE_USER)
        except (LookupError, PermissionError):
            pass
    os.replace(tmp, p)


def wiki_start(value: str | None) -> str:
    """0.54.1: the start address of the wiki network from what a user enters (the MSI dialog, net wiki on --start): a host name
    (vi-wiki.org), https://HOST[:PORT] or a full address https://HOST/vi-p2p/wiki. None or empty: vi-wiki.org. Only https — the service
    of the wiki network allows no plain http. ValueError names the reason."""
    from . import p2p
    v = (value or "").strip()
    if not v:
        return p2p.WIKI_START
    bad = ValueError(f"wiki server: a host name or https://HOST[:PORT][/PATH], not {v!r}")
    if any(c.isspace() for c in v):
        raise bad
    u = urllib.parse.urlsplit(v if "://" in v else "https://" + v)
    try:
        u.port  # a port that is not a number raises here
    except ValueError:
        raise bad from None
    if u.scheme != "https" or not u.hostname or u.query or u.fragment or u.username or u.password:
        raise bad
    return urllib.parse.urlunsplit(("https", u.netloc.lower(), u.path.rstrip("/") or f"/vi-p2p/{p2p.WIKI_NET}", "", ""))


def _memory_config(o) -> Path | None:
    """0.62.6: the memory configuration setup writes into (instance, network entry, live-search token). One host: the memory's own file.
    Memory and network service in separate containers: the memory's config mounted into this container, given by --memory-config —
    reported from CentralStation (13.11.2026), where join wrote into a config the memory never read. None = it does not exist (refused)."""
    m = Path(getattr(o, "memory_config", None) or config.fpath())
    split = bool(getattr(o, "memory_config", None) or getattr(o, "memory_url", None))
    return m if m.exists() or not split else None  # one host: as before (created on first use); split: it must be there


def setup(o) -> int:
    p = nd.fpath()
    raw = nd.english_file(json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {})  # 0.51.0: written in English
    k_old = nd.from_file(raw)
    mem = _memory_config(o)
    if o.mode != "standalone" and mem is None:
        print(f"The memory configuration {getattr(o, 'memory_config', None) or config.fpath()} does not exist here. When the memory runs "
              "elsewhere (another container), mount its configuration and give it with --memory-config PATH, its address with "
              "--memory-url http://HOST:PORT/mcp, and where it reaches this service with --local-bind/--local-host.", file=sys.stderr)
        return 2
    if getattr(o, "memory_url", None):
        raw["mcp_url"] = o.memory_url
    if getattr(o, "local_bind", None):
        raw["local_bind"] = o.local_bind
    raw["mode"] = o.mode
    for attr, key in (("address", "address"), ("bind", "bind"), ("port", "port"), ("tls_cert", "tls_cert"), ("tls_key", "tls_key"), ("ca_file", "ca_file")):
        if getattr(o, attr) is not None:
            raw[key] = getattr(o, attr)
    if o.start:  # added to the known start addresses; replace_start (net wiki on --start, 0.54.1): the given ones only
        raw["startpeers"] = sorted(set(o.start) if getattr(o, "replace_start", False) else set(raw.get("startpeers", [])) | set(o.start))
    if o.http_allowed:
        raw["http_allowed"] = True
    if o.proxy is not None:
        raw["proxy"] = o.proxy or None
    if o.no_proxy:
        raw["no_proxy"] = sorted(set(raw.get("no_proxy", [])) | set(o.no_proxy))
    if o.torrent:
        raw["torrent"] = {**raw.get("torrent", {}), "active": True}
    if o.mode == "standalone":
        _write(p, raw)
        if reason := _service("disable", "--now", SERVICE):
            print(f"Hint: {reason}")
        print("Mode standalone: the network service does not run. The logbook is kept.")
        return 0
    if NETWORK:  # 0.39.0: own directory, key, logbook and memory instance per network
        kind = config.net_kind(getattr(o, "kind", None) or raw.get("kind"))
        if kind not in ("company", "open", "free"):
            print("A further network needs --kind free (anyone may join, no invitation, anonymised), open (anonymised, by invitation) or company "
                  "(one organisation, internal names allowed, by invitation)", file=sys.stderr)
            return 2
        if raw.get("kind") and raw["kind"] != kind:
            print(f"Network {NETWORK} is {raw['kind']}; the kind is not changed afterwards", file=sys.stderr)
            return 2
        raw.update(net=NETWORK, kind=kind)
        raw.setdefault("db", str(nd.var_dir() / NETWORK / "netz.db"))
        raw.setdefault("seed", str(nd.var_dir() / NETWORK / "schluessel"))
        raw.setdefault("mcp_token_file", str(nd.etc_dir() / f"{NETWORK}-mcp-token"))
    elif config.net_kind(getattr(o, "kind", None)) == "company":
        print("The network standard is open (anonymised); a company network gets its own name: vi-mcp net --network NAME setup --kind company …", file=sys.stderr)
        return 2
    seed = Path(raw.get("seed") or k_old.seed)
    if not seed.exists() and not _root():  # Windows, or a test as a normal user: no service user to switch to
        seed.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lb.generate_keys(seed)
    if not seed.exists():
        child_pid = os.fork()
        if child_pid == 0:
            _as_service_user()
            seed.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            lb.generate_keys(seed)
            os._exit(0)
        os.waitpid(child_pid, 0)
    # the seed belongs to the service user; root reads it only to name the pseudonym
    pub = lb.public_hex(lb.private(seed))
    if o.found:
        raw["founders"] = sorted(set(raw.get("founders", [])) | {pub})
    if o.founders:
        raw["founders"] = sorted(set(raw.get("founders", [])) | set(o.founders))
    if raw.get("kind") == "free":  # 0.45.0: no founders, no invitation — the identity proof is computed at the first start of the service
        raw.setdefault("pow_bits", lb.DEFAULT_POW_BITS)
        if not o.start and not raw.get("startpeers") and o.mode != "peerhost":
            print("A free network needs --start https://<a server of the network> (or this server is a peerhost others start from)", file=sys.stderr)
            return 2
    elif not raw.get("founders"):
        print("Founder missing: --found for a new network or --founder KEY to join", file=sys.stderr)
        return 2
    if getattr(o, "public", None):  # 0.40.0: published on 443 behind the reverse proxy
        if o.mode != "peerhost" or o.tls_self:
            print("--public is for a peerhost and replaces --tls-self: TLS ends at the reverse proxy on 443", file=sys.stderr)
            return 2
        try:
            raw["address"] = public_address(o.public, NETWORK or "standard")
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 2
        raw["bind"] = o.bind or "127.0.0.1"  # --bind: e.g. the gateway of a Docker network when nginx runs in a container
        raw.pop("tls_cert", None)
        raw.pop("tls_key", None)
        if not o.port and "port" not in raw:
            used = {int(c.get("port", FIRST_LOCAL_PORT)) for n, c in network_configs(p.parent).items() if n != (NETWORK or "standard")}
            raw["port"] = free_port(used)
        if (raw.get("torrent") or {}).get("active"):
            print("Hint: torrent uses its own port (not 443); for a network on 443 only, switch it off in " + str(p))
    if o.mode == "peerhost" and not raw.get("address"):
        print("peerhost needs --address https://name:port, otherwise nobody finds it", file=sys.stderr)
        return 2
    if o.tls_self:
        if o.mode != "peerhost":
            print("--tls-self applies to peerhost only", file=sys.stderr)
            return 2
        dir_path = nd.data_dir(nd.NetConfig(db=raw.get("db") or k_old.db, seed=raw.get("seed") or k_old.seed))
        cert, key = dir_path / "tls-cert.pem", dir_path / "tls-key.pem"
        if not cert.exists():
            _as_service(lambda: _create_certificate(raw["address"], cert, key) or 0)
        raw["tls_cert"], raw["tls_key"] = str(cert), str(key)
    token_file = Path(raw.get("mcp_token_file") or k_old.mcp_token_file)
    if not token_file.exists():
        if NETWORK:
            _instance, token = config.set_network(NETWORK, raw["kind"], p=mem)
            token = token or config.create_instance(_instance, p=mem)
        else:
            token = config.create_instance("p2p", p=mem)
        fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
        if _root():
            shutil.chown(token_file, "root", SERVICE_USER)
        if getattr(o, "memory_url", None):
            print(f"The memory reads instances at start: restart the memory (its container) — its configuration {mem} now holds the instance")
        elif reason := _service("restart", "vi-mcp"):
            print(f"Hint: vi-mcp not restarted: {reason}")
    if not raw.get("local_token_sha256"):  # 0.42.0: live search — the memory holds the token, the service its hash
        used = {int(c.get("local_port") or 0) for n, c in network_configs(p.parent).items() if n != (NETWORK or "standard")}
        raw["local_port"] = int(raw.get("local_port") or free_port(used, FIRST_SEARCH_PORT))
        local_token = secrets.token_urlsafe(32)
        raw["local_token_sha256"] = hashlib.sha256(local_token.encode()).hexdigest()
        local_host = getattr(o, "local_host", None) or "127.0.0.1"
        try:
            config.set_net_local(NETWORK or "standard", f"http://{local_host}:{raw['local_port']}", local_token, p=mem)
            print(f"Live search wired: the memory {mem} asks this service at http://{local_host}:{raw['local_port']} "
                  f"(listener bound to {raw.get('local_bind') or '127.0.0.1'})")
        except (OSError, ValueError) as ex:
            print(f"Hint: live search not wired into the memory config: {ex}")
    if "mcp_url" not in raw:  # 0.54.0: the memory's own port (an MSI with PORT=, a package with another port), not always 8765
        try:
            raw["mcp_url"] = f"http://127.0.0.1:{int(config.read_raw(mem or config.fpath()).get('port') or 8765)}/mcp"
        except (OSError, ValueError, TypeError):
            pass
    _write(p, raw)
    if reason := _service("enable", SERVICE):
        print(f"Hint: {reason}")
    if reason := _service("restart", SERVICE):
        print(f"Hint: {reason}")
    print(f"Network {raw.get('net', 'standard')} ({raw.get('kind', 'open')}) · mode {o.mode}. Key of this server: {pub}\nPseudonym: {lb.pseudonym(pub)}")
    if raw.get("kind") == "free":
        print(f"Free network: no invitation needed. The service computes its identity proof ({raw.get('pow_bits')} bits) at its first start, "
              "then finds the other servers through the start address.")
    elif not o.found and pub not in raw["founders"] and not getattr(o, "quiet", False):
        print("To join: a member runs:  vi-mcp net invite " + pub)
    return 0


def join(o) -> int:
    try:
        d = nd.read_code(o.code)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    e = argparse.Namespace(mode=o.mode, address=o.address, bind=None, port=o.port, tls_cert=None, tls_key=None, ca_file=None, found=False, founders=d["g"], start=[d["s"]],
                           memory_config=getattr(o, "memory_config", None), memory_url=getattr(o, "memory_url", None),
                           local_bind=getattr(o, "local_bind", None), local_host=getattr(o, "local_host", None),
                           http_allowed=o.http_allowed, torrent=False, tls_self=o.tls_self, proxy=o.proxy, no_proxy=o.no_proxy, quiet=True, kind=o.kind,
                           public=o.public)
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
        _service("restart", SERVICE)
    return code


def _parser() -> argparse.ArgumentParser:
    """The argument parser of `vi-mcp net` (also read by scripts/gen_reference.py for docs/REFERENCE.md)."""
    a = argparse.ArgumentParser(prog="vi-mcp net")
    a.add_argument("--network", "--netz", dest="network", help="a further network (0.39.0): config /etc/vi-p2p/NAME.json, service vi-p2p@NAME; "
                   "without it: the network standard")
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
    e.add_argument("--public", "--oeffentlich", dest="public", help="publish this network on 443: https://HOST — reachable as "
                   "https://HOST/vi-p2p/<network> through the reverse proxy (vi-mcp net proxy-config prints its configuration)")
    e.add_argument("--kind", "--art", dest="kind", type=config.net_kind, choices=("company", "open", "free"),
                   help="with --network: company = one organisation, internal names allowed, knowledge stays internal; open = anonymised, by "
                        "invitation; free = anyone may join (frei/offen/firma are still accepted)")
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
    bt.add_argument("--port", type=int)
    bt.add_argument("--public", "--oeffentlich", dest="public")
    bt.add_argument("--kind", "--art", dest="kind", type=config.net_kind, choices=("company", "open"))
    for sp in (e, bt):  # 0.62.6: memory and network service in separate containers
        sp.add_argument("--memory-config", dest="memory_config", help="the memory's configuration file to register the network in "
                        "(default: this machine's); in a container setup: the memory's config mounted here")
        sp.add_argument("--memory-url", dest="memory_url", help="where this service reaches the memory, e.g. http://vi-mcp:8765/mcp "
                        "(default: 127.0.0.1 and the memory's port)")
        sp.add_argument("--local-bind", dest="local_bind", help="address the live-search listener binds to (default 127.0.0.1)")
        sp.add_argument("--local-host", dest="local_host", help="host name the memory uses to reach that listener (default 127.0.0.1), "
                        "e.g. the network container's service name")
    wk = cmd("wiki", help="the public wiki network: on (join: free network, outgoing, start vi-wiki.org or --start) · off (stop the service) · status")
    wk.add_argument("action", choices=("on", "off", "status"), nargs="?", default="status")
    wk.add_argument("--start", default=None, help="the wiki server to start from instead of vi-wiki.org: a host name or https://HOST[:PORT][/PATH] "
                    "(no path: /vi-p2p/wiki); replaces the start address of an existing configuration (0.54.1)")
    wk.add_argument("--proxy", default=None, help="HTTP(S) proxy for the service's outgoing connections, e.g. http://proxy:3128 (0.54.0)")
    cmd("peers")
    for name, alias in (("block", "sperren"), ("unblock", "entsperren")):  # 0.45.0: local block list (public key or address)
        x = cmd(name, alias)
        x.add_argument("target", help="public key (64 hex) or address https://…")
    cmd("proxy-config", help="nginx configuration for every network published on 443 (setup --public)")
    cmd("id")
    cmd("status")
    cmd("run", "lauf")
    return a


def main(argv: list[str]) -> int:
    global SERVICE, NETWORK
    SERVICE, NETWORK = "vi-p2p", None  # per call: the network standard unless --network names another
    a = _parser()
    o = a.parse_args(argv)
    if o.network:
        import re
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", o.network) or o.network in ("standard", "config"):
            print("network name: a-z, 0-9, -, 2–31 characters; 'standard' is the network without --network", file=sys.stderr)
            return 2
        NETWORK, SERVICE = o.network, f"vi-p2p@{o.network}"
        os.environ["VI_P2P_CONFIG"] = str((nd.fpath().parent if os.environ.get("VI_P2P_CONFIG") else nd.etc_dir()) / f"{o.network}.json")
    if o.command == "wiki":  # 0.47.0
        from . import p2p
        NETWORK, SERVICE = p2p.WIKI_NET, f"vi-p2p@{p2p.WIKI_NET}"
        if not os.environ.get("VI_P2P_CONFIG"):
            os.environ["VI_P2P_CONFIG"] = str(nd.etc_dir() / f"{p2p.WIKI_NET}.json")
        p = nd.fpath()
        if o.action == "status":
            state = service_state(SERVICE)
            start = ", ".join(json.loads(p.read_text(encoding="utf-8-sig")).get("startpeers") or []) if p.exists() else p2p.WIKI_START
            print(f"wiki network ({start}): {'configured' if p.exists() else 'not set up'}; service {SERVICE}: {state}")
            return 0
        if o.action == "off":
            print(_service("disable", "--now", SERVICE) or f"{SERVICE} stopped and disabled; config and logbook are kept (vi-mcp net wiki on resumes)")
            return 0
        try:
            start = wiki_start(o.start)
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 2
        known = (json.loads(p.read_text(encoding="utf-8-sig")).get("startpeers") or []) if p.exists() else []
        if o.start is None and known:  # on again without --start: the server it was set up with, vi-wiki.org is not added
            start = known[0]
        e = argparse.Namespace(mode="peer", address=None, bind=None, port=None, tls_cert=None, tls_key=None, ca_file=None, found=False, founders=[],
                               start=[] if o.start is None and known else [start], replace_start=o.start is not None, http_allowed=False, torrent=False, tls_self=False, proxy=o.proxy,
                               no_proxy=[], quiet=True, kind="free", public=None)
        code = setup(e)
        if code == 0:
            try:  # the memory names the server in its notice to the AI (p2p.notice)
                config.set_net_start(p2p.WIKI_NET, start)
            except (OSError, ValueError) as ex:
                print(f"Hint: wiki server not recorded in the memory config: {ex}")
        return code
    if o.command == "setup":
        return setup(o)
    if o.command == "run":
        return nd.main()
    if o.command == "join":
        return join(o)
    if o.command == "proxy-config":
        print(nginx_snippet(network_configs(nd.fpath().parent)))
        return 0
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
    if o.command in ("block", "unblock"):
        t = o.target.strip().rstrip("/")
        if not (lb._HEX64.match(t) or lb._ADDRESS.match(t)):
            print("give a public key (64 hex) or an address https://…", file=sys.stderr)
            return 2
        p = nd.fpath()
        raw = nd.english_file(json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {})
        s = set(raw.get("blocked") or [])
        s = s | {t} if o.command == "block" else s - {t}
        raw["blocked"] = sorted(s)
        _write(p, raw)
        if reason := _service("restart", SERVICE):
            print(f"Hint: {reason}")
        print(f"{'Blocked' if o.command == 'block' else 'Unblocked'} on this server: {t} — other servers decide for themselves.")
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
    print(f"Network {k.net} ({k.kind}) · mode {k.mode} · pseudonym {lb.pseudonym(log.pub)} · {'member' if log.is_member(log.pub) else 'not a member yet'}")
    print(" · ".join(f"{a_} {b}" for a_, b in st.items()))
    return 0
