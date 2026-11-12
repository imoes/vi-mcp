"""Configuration — one file, readable by the owner only.

Path: $VI_MCP_CONFIG or ~/.config/vi-mcp/config.json. Content:
  {
    "bind": "127.0.0.1" | ["127.0.0.1", "<docker-gateway>"], "port": 8765,
    "db": "~/.local/share/vi-mcp/vi.db",
    "instances": {"<name>": {"token_sha256": "<hex>", "reflexes": false}},
    "ttl": {"<tool>": <seconds>},
    "origins": ["http://localhost", "http://127.0.0.1"],
    "embed": {"url": "https://host/embed/v1/embeddings", "token": "", "model": ""},      optional (stage 3, during sleep)
    "llm":   {"url": "https://host/qwen/v1/chat/completions", "token": "", "model": ""}  optional (stage 4, during sleep)
  }
Keys are English since 0.51.0; the German keys of older files (instanzen, offen, …, see normalize) are still read, and every write stores
English.
Tokens are stored only as SHA-256 in the file; the token itself is printed once on creation.
Without an instance the server does not start (no open access by accident) — named, not silent.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("~/.config/vi-mcp/config.json").expanduser()


def default_path() -> Path:
    """0.28.1: on Windows the server configuration is %ProgramData%\\vi-mcp\\config.json (where the MSI puts it). Before, only the
    machine variable VI_MCP_CONFIG pointed there, and a process started before the installation read the default and showed port 8765
    while the server ran on 8790 (Windows 11 test VM, 10.11.2026)."""
    if sys.platform == "win32":
        return Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "vi-mcp" / "config.json"
    return DEFAULT_PATH


#: Who comes without a token when `open` is switched on (the instance keeps its stored name offen): read, report actions, propose knowledge (quarantine). No rights.
OPEN = "offen"


#: 0.51.0: the configuration speaks English (decided by the user, 11.11.2026). Older files used German keys and German network kinds;
#: they are still read, every write stores English. One table per level, so the names inside a section (instances, networks, local users,
#: tools) are never translated.
TOP_KEYS = {"offen": "open", "instanzen": "instances", "pruefer_prompt": "reviewer_prompt", "lager_tage": "archive_days", "lokal": "local",
            "web_basis": "web_base"}
INSTANCE_KEYS = {"reflexe": "reflexes", "freigabe": "release", "mensch": "human", "familie": "family"}
SERVICE_KEYS = {"modell": "model"}  # llm, embed
P2P_KEYS = {"netze": "networks", "reflexe_von": "reflexes_from", "auto_freigabe": "auto_release", "oeffentliche_domains": "public_domains",
            "interne_namen": "internal_names", "lokal": "local"}
NETWORK_KEYS = {"art": "kind", "instanz": "instance", "auto_freigabe": "auto_release", "lokal": "local"}
#: network kinds: free = anyone may join, open = by invitation, anonymised, company = one organisation, internal knowledge
NET_KINDS = {"frei": "free", "offen": "open", "firma": "company"}


def net_kind(value):
    """A network kind in English; the German words of 0.39–0.50 are accepted (frei → free, offen → open, firma → company)."""
    return NET_KINDS.get(value, value)


def _rename(d: dict, table: dict, where: str, notes: list[str]) -> dict:
    out: dict = {}
    for key, value in d.items():
        new = table.get(key, key)
        if new != key:
            if new in d:  # both spellings: the English one wins, the German one is dropped — named, not silent
                notes.append(f"{where}{key} dropped ({new} is set)")
                continue
            notes.append(f"{where}{key} → {new}")
        out[new] = value
    return out


def normalize(raw: dict) -> tuple[dict, list[str]]:
    """German keys and network kinds → English. Returns the new dict and what was renamed. Pure."""
    notes: list[str] = []
    r = _rename(raw or {}, TOP_KEYS, "", notes)
    if isinstance(r.get("instances"), dict):
        r["instances"] = {n: _rename(d, INSTANCE_KEYS, f"instances.{n}.", notes) if isinstance(d, dict) else d for n, d in r["instances"].items()}
    for section in ("llm", "embed"):
        if isinstance(r.get(section), dict):
            r[section] = _rename(r[section], SERVICE_KEYS, f"{section}.", notes)
    if isinstance(r.get("p2p"), dict):
        p2p = _rename(r["p2p"], P2P_KEYS, "p2p.", notes)
        if isinstance(p2p.get("networks"), dict):
            nets = {}
            for n, d in p2p["networks"].items():
                if isinstance(d, dict):
                    d = _rename(d, NETWORK_KEYS, f"p2p.networks.{n}.", notes)
                    if d.get("kind") in NET_KINDS:
                        notes.append(f"p2p.networks.{n}.kind {d['kind']} → {NET_KINDS[d['kind']]}")
                        d["kind"] = NET_KINDS[d["kind"]]
                nets[n] = d
            p2p["networks"] = nets
        r["p2p"] = p2p
    return r, notes


def read_raw(p: Path | None = None) -> dict:
    """The configuration file as a dict with English keys (older German files are translated on the fly)."""
    p = p or fpath()
    return normalize(json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {})[0]


def migrate_file(p: Path | None = None) -> list[str]:
    """Rewrite an older configuration with English keys (package update). A copy of the old file stays next to it. Returns the renames."""
    import time
    p = p or fpath()
    if not p.exists():
        return []
    old = json.loads(p.read_text(encoding="utf-8-sig"))
    new, notes = normalize(old)
    if notes:
        backup = p.with_name(f"{p.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}-german-keys")
        backup.write_bytes(p.read_bytes())
        os.chmod(backup, os.stat(p).st_mode & 0o777)
        _save_raw(new, p)
    return notes


@dataclass
class Instance:
    name: str
    token_sha256: str
    reflexes: bool = False
    release: bool = False  # may release sensitive imported content from quarantine
    human: bool = False  # may report user signals (POST /signal)
    #: 0.33.0: model family (e.g. claude, gpt, qwen). Confirmations and refutations of one family count as ONE line — instances of the
    #: same model are not independent witnesses (Condorcet). None = undeclared: the instance counts as its own line.
    family: str | None = None


@dataclass
class Config:
    bind: list[str] = field(default_factory=lambda: ["127.0.0.1"])
    port: int = 8765
    #: SQLite file, or (0.50.0) a postgresql:// URL (str) — vi_mcp/db.py; never with a password in it (~/.pgpass, PGPASSFILE, peer auth)
    db: Path | str = Path("~/.local/share/vi-mcp/vi.db").expanduser()
    instances: dict[str, Instance] = field(default_factory=dict)
    ttl: dict[str, int] = field(default_factory=dict)
    origins: list[str] = field(default_factory=lambda: ["http://localhost", "http://127.0.0.1"])
    embed: dict | None = None
    archive_days: dict[str, int] = field(default_factory=dict)
    p2p: dict = field(default_factory=dict)
    reviewer_prompt: str | None = None
    llm: dict | None = None
    #: Access without a token. A wrong token still gets 401: whoever sends one wants to be a specific instance.
    open_: bool = False
    #: 0.36.0: local socket (Linux) for `vi-mcp stdio`: path, and local user → instance. The kernel names the user (SO_PEERCRED),
    #: so no token is needed; only users listed here get in, each as its instance (with its visibility, internal included).
    socket: str | None = None
    local: dict[str, str] = field(default_factory=dict)
    #: 0.46.0: read-only web page of the free and open networks under /web (config `web`, off by default); `web_basis` is the path the
    #: browser sees, e.g. /vi-mcp/web behind the reverse proxy
    web: bool = False
    web_base: str = "/web"

    def instance_for(self, token: str | None) -> Instance | None:
        """Instance for the bearer token, or None. Constant-time comparison across all instances."""
        if not token:
            return Instance(OPEN, "") if self.open_ else None
        h = hashlib.sha256(token.encode()).hexdigest()
        hits = None
        for i in self.instances.values():
            if hmac.compare_digest(h, i.token_sha256):
                hits = i
        return hits


def fpath() -> Path:
    return Path(os.environ.get("VI_MCP_CONFIG") or default_path()).expanduser()


def load(p: Path | None = None) -> Config:
    p = p or fpath()
    raw = read_raw(p)
    k = Config()
    b = raw.get("bind", k.bind)
    k.bind = [b] if isinstance(b, str) else list(b)
    k.port = int(raw.get("port", k.port))
    db_value = str(raw.get("db", str(k.db)))
    k.db = db_value if db_value.startswith(("postgresql://", "postgres://")) else Path(db_value).expanduser()
    k.ttl = {w: int(s) for w, s in (raw.get("ttl") or {}).items()}
    k.origins = list(raw.get("origins") or k.origins)
    k.embed = raw.get("embed") or None
    k.p2p = raw.get("p2p") or {}
    k.reviewer_prompt = raw.get("reviewer_prompt")
    k.archive_days = {a: int(t) for a, t in (raw.get("archive_days") or {}).items()}
    k.llm = raw.get("llm") or None
    k.open_ = bool(raw.get("open", False))
    k.socket = raw.get("socket") or os.environ.get("VI_MCP_SOCKET") or None
    k.local = {str(u): str(i) for u, i in (raw.get("local") or {}).items()}
    k.web = bool(raw.get("web", False))
    k.web_base = "/" + str(raw.get("web_base") or "/web").strip("/")
    for n, d in (raw.get("instances") or {}).items():
        k.instances[n] = Instance(n, d["token_sha256"], bool(d.get("reflexes", False)), bool(d.get("release", False)), bool(d.get("human", False)),
                                  (d.get("family") or None))
    return k


def create_instance(name: str, reflexes: bool = False, p: Path | None = None, release: bool = False, human: bool = False) -> str:
    """Create an instance or renew its token. Returns the new token (visible only this once)."""
    if not name or not all(c.isalnum() or c in "-_." for c in name):
        raise ValueError("instance name: letters, digits, - _ .")
    if name == OPEN:
        raise ValueError(f"\"{OPEN}\" is reserved for access without a token")
    p = p or fpath()
    raw = read_raw(p)
    token = secrets.token_urlsafe(32)
    raw.setdefault("instances", {})[name] = {"token_sha256": hashlib.sha256(token.encode()).hexdigest(), "reflexes": reflexes, "release": release, "human": human}
    _save_raw(raw, p)
    return token


def set_port(port: int, p: Path | None = None) -> int:
    """0.27.0: set the server port in the configuration (1024–65535). Returns the previous port. The service reads it at start."""
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError("port must be a number from 1024 to 65535")
    p = p or fpath()
    raw = read_raw(p)
    old = int(raw.get("port", Config().port))
    raw["port"] = port
    _save_raw(raw, p)
    return old


def set_family(name: str, family: str | None, p: Path | None = None) -> str | None:
    """0.33.0: declare (or with None remove) the model family of an instance. Returns the previous one. The service reads it at start."""
    if family is not None and (not family or not all(c.isalnum() or c in "-_." for c in family)):
        raise ValueError("family: letters, digits, - _ .")
    p = p or fpath()
    raw = read_raw(p)
    inst = (raw.get("instances") or {}).get(name)
    if inst is None:
        raise ValueError(f"instance {name!r} unknown")
    old = inst.get("family")
    if family:
        inst["family"] = family
    else:
        inst.pop("family", None)
    _save_raw(raw, p)
    return old


def set_local(user: str, instance: str | None, p: Path | None = None) -> str | None:
    """0.36.0: let a local user reach the VI over the local socket as INSTANCE (None removes it). Returns the previous instance."""
    if not user or not all(c.isalnum() or c in "-_.$@" for c in user):
        raise ValueError("local user: letters, digits, - _ . $ @")
    p = p or fpath()
    raw = read_raw(p)
    if instance is not None and instance not in (raw.get("instances") or {}):
        raise ValueError(f"instance {instance!r} unknown — first: vi-mcp instance {instance}")
    m = raw.setdefault("local", {})
    old = m.get(user)
    if instance:
        m[user] = instance
    else:
        m.pop(user, None)
    _save_raw(raw, p)
    return old


def set_network(name: str, kind: str, p: Path | None = None) -> tuple[str, str | None]:
    """0.39.0: register a further network with its kind (free, open or company) and the instance its network service uses (netz-<name>).
    The memory, not the network service, decides the kind. Returns (instance, new token or None if the instance existed)."""
    import re
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", name or "") or name in ("standard", "config"):
        raise ValueError("network name: a-z, 0-9, -, 2–31 characters, not 'standard' (that is the network without a name)")
    kind = net_kind(kind)
    if kind not in NET_KINDS.values():
        raise ValueError("network kind must be free, open or company")
    p = p or fpath()
    instance = f"netz-{name}"
    raw = read_raw(p)
    token = None if instance in (raw.get("instances") or {}) else create_instance(instance, p=p)
    raw = read_raw(p)
    nets = raw.setdefault("p2p", {}).setdefault("networks", {})
    if name in nets and nets[name].get("kind") != kind:
        raise ValueError(f"network {name} is already registered as {nets[name].get('kind')}; the kind is not changed afterwards "
                         "(knowledge already exchanged would otherwise change its visibility)")
    nets[name] = {**(nets.get(name) or {}), "kind": kind, "instance": instance}  # keeps local and start
    _save_raw(raw, p)
    return instance, token


def set_net_local(net: str, url: str, token: str, p: Path | None = None) -> None:
    """0.42.0: where the memory reaches the network service of `net` for live searches (local listener) and with which token."""
    p = p or fpath()
    raw = read_raw(p)
    p2p = raw.setdefault("p2p", {})
    if net == "standard":
        p2p["local"] = {"url": url, "token": token}
    else:
        if net not in (p2p.get("networks") or {}):
            raise ValueError(f"network {net} is not registered — first: vi-mcp net --network {net} setup --kind …")
        p2p["networks"][net]["local"] = {"url": url, "token": token}
    _save_raw(raw, p)


def set_net_start(net: str, url: str, p: Path | None = None) -> None:
    """0.54.1: the server a network starts from (net wiki on --start), so the memory names it in its notice instead of vi-wiki.org."""
    p = p or fpath()
    raw = read_raw(p)
    nets = raw.setdefault("p2p", {}).setdefault("networks", {})
    if net not in nets:
        raise ValueError(f"network {net} is not registered")
    nets[net]["start"] = url
    _save_raw(raw, p)


def set_web(on: bool, base: str | None = None, p: Path | None = None) -> None:
    """0.46.0: switch the read-only web page on or off; base = the path the browser sees (default /web)."""
    import re
    if base is not None and not re.fullmatch(r"(/[A-Za-z0-9._-]+)+", base.rstrip("/") or "/x"):
        raise ValueError("web base: a path like /web or /vi-mcp/web")
    p = p or fpath()
    raw = read_raw(p)
    raw["web"] = bool(on)
    if base is not None:
        raw["web_base"] = base.rstrip("/") or "/web"
    _save_raw(raw, p)


def set_embed(embed: dict | None, p: Path | None = None) -> None:
    """0.28.0: set or clear the embedding service ({"url": ...}); the service reads it at start."""
    p = p or fpath()
    raw = read_raw(p)
    if embed:
        raw["embed"] = embed
    else:
        raw.pop("embed", None)
    _save_raw(raw, p)


def _save_raw(raw: dict, p: Path) -> None:
    """Atomic write of the configuration; keeps owner and permissions of an existing file, a new one is 0600."""
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    old_umask_value = os.umask(0o077)
    try:
        tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    finally:
        os.umask(old_umask_value)
    # keep the permissions of an existing file (package: root:vi-mcp 0640, so the service can read it);
    # a new file is 0600 (owner only)
    if p.exists():
        st = os.stat(p)
        os.chmod(tmp, st.st_mode & 0o777)
        try:
            if hasattr(os, "chown"):  # not on Windows
                os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
    else:
        os.chmod(tmp, 0o600)
    os.replace(tmp, p)
