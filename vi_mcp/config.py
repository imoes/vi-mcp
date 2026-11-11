"""Configuration — one file, readable by the owner only.

Path: $VI_MCP_CONFIG or ~/.config/vi-mcp/config.json. Content:
  {
    "bind": "127.0.0.1" | ["127.0.0.1", "<docker-gateway>"], "port": 8765,
    "db": "~/.local/share/vi-mcp/vi.db",
    "instanzen": {"<name>": {"token_sha256": "<hex>", "reflexe": false}},
    "ttl": {"<tool>": <seconds>},
    "origins": ["http://localhost", "http://127.0.0.1"],
    "embed": {"url": "https://host/embed/v1/embeddings", "token": "", "modell": ""},      optional (stage 3, during sleep)
    "llm":   {"url": "https://host/qwen/v1/chat/completions", "token": "", "modell": ""}  optional (stage 4, during sleep)
  }
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


#: Who comes without a token when `offen` is switched on: read, report actions, propose knowledge (quarantine). No rights.
OPEN = "offen"


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
    db: Path = Path("~/.local/share/vi-mcp/vi.db").expanduser()
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
    raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    k = Config()
    b = raw.get("bind", k.bind)
    k.bind = [b] if isinstance(b, str) else list(b)
    k.port = int(raw.get("port", k.port))
    k.db = Path(raw.get("db", str(k.db))).expanduser()
    k.ttl = {w: int(s) for w, s in (raw.get("ttl") or {}).items()}
    k.origins = list(raw.get("origins") or k.origins)
    k.embed = raw.get("embed") or None
    k.p2p = raw.get("p2p") or {}
    k.reviewer_prompt = raw.get("pruefer_prompt")
    k.archive_days = {a: int(t) for a, t in (raw.get("lager_tage") or {}).items()}
    k.llm = raw.get("llm") or None
    k.open_ = bool(raw.get("offen", False))
    k.socket = raw.get("socket") or os.environ.get("VI_MCP_SOCKET") or None
    k.local = {str(u): str(i) for u, i in (raw.get("lokal") or {}).items()}
    for n, d in (raw.get("instanzen") or {}).items():
        k.instances[n] = Instance(n, d["token_sha256"], bool(d.get("reflexe", False)), bool(d.get("freigabe", False)), bool(d.get("mensch", False)),
                                  (d.get("familie") or None))
    return k


def create_instance(name: str, reflexes: bool = False, p: Path | None = None, release: bool = False, human: bool = False) -> str:
    """Create an instance or renew its token. Returns the new token (visible only this once)."""
    if not name or not all(c.isalnum() or c in "-_." for c in name):
        raise ValueError("instance name: letters, digits, - _ .")
    if name == OPEN:
        raise ValueError(f"\"{OPEN}\" is reserved for access without a token")
    p = p or fpath()
    raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    token = secrets.token_urlsafe(32)
    raw.setdefault("instanzen", {})[name] = {"token_sha256": hashlib.sha256(token.encode()).hexdigest(), "reflexe": reflexes, "freigabe": release, "mensch": human}
    _save_raw(raw, p)
    return token


def set_port(port: int, p: Path | None = None) -> int:
    """0.27.0: set the server port in the configuration (1024–65535). Returns the previous port. The service reads it at start."""
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError("port must be a number from 1024 to 65535")
    p = p or fpath()
    raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    old = int(raw.get("port", Config().port))
    raw["port"] = port
    _save_raw(raw, p)
    return old


def set_family(name: str, family: str | None, p: Path | None = None) -> str | None:
    """0.33.0: declare (or with None remove) the model family of an instance. Returns the previous one. The service reads it at start."""
    if family is not None and (not family or not all(c.isalnum() or c in "-_." for c in family)):
        raise ValueError("family: letters, digits, - _ .")
    p = p or fpath()
    raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    inst = (raw.get("instanzen") or {}).get(name)
    if inst is None:
        raise ValueError(f"instance {name!r} unknown")
    old = inst.get("familie")
    if family:
        inst["familie"] = family
    else:
        inst.pop("familie", None)
    _save_raw(raw, p)
    return old


def set_local(user: str, instance: str | None, p: Path | None = None) -> str | None:
    """0.36.0: let a local user reach the VI over the local socket as INSTANCE (None removes it). Returns the previous instance."""
    if not user or not all(c.isalnum() or c in "-_.$@" for c in user):
        raise ValueError("local user: letters, digits, - _ . $ @")
    p = p or fpath()
    raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    if instance is not None and instance not in (raw.get("instanzen") or {}):
        raise ValueError(f"instance {instance!r} unknown — first: vi-mcp instance {instance}")
    m = raw.setdefault("lokal", {})
    old = m.get(user)
    if instance:
        m[user] = instance
    else:
        m.pop(user, None)
    _save_raw(raw, p)
    return old


def set_network(name: str, kind: str, p: Path | None = None) -> tuple[str, str | None]:
    """0.39.0: register a further network with its kind (firma or offen) and the instance its network service uses (netz-<name>).
    The memory, not the network service, decides the kind. Returns (instance, new token or None if the instance existed)."""
    import re
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", name or "") or name in ("standard", "config"):
        raise ValueError("network name: a-z, 0-9, -, 2–31 characters, not 'standard' (that is the network without a name)")
    if kind not in ("firma", "offen"):
        raise ValueError("network kind must be firma or offen")
    p = p or fpath()
    instance = f"netz-{name}"
    raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    token = None if instance in (raw.get("instanzen") or {}) else create_instance(instance, p=p)
    raw = json.loads(p.read_text(encoding="utf-8-sig"))
    nets = raw.setdefault("p2p", {}).setdefault("netze", {})
    if name in nets and nets[name].get("art") != kind:
        raise ValueError(f"network {name} is already registered as {nets[name].get('art')}; the kind is not changed afterwards "
                         "(knowledge already exchanged would otherwise change its visibility)")
    nets[name] = {"art": kind, "instanz": instance}
    _save_raw(raw, p)
    return instance, token


def set_embed(embed: dict | None, p: Path | None = None) -> None:
    """0.28.0: set or clear the embedding service ({"url": ...}); the service reads it at start."""
    p = p or fpath()
    raw = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
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
