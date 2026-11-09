"""Konfiguration — eine Datei, nur für den Eigentümer lesbar.

Pfad: $VI_MCP_CONFIG oder ~/.config/vi-mcp/config.json. Inhalt:
  {
    "bind": "127.0.0.1" | ["127.0.0.1", "<docker-gateway>"], "port": 8765,
    "db": "~/.local/share/vi-mcp/vi.db",
    "instanzen": {"<name>": {"token_sha256": "<hex>", "reflexe": false}},
    "ttl": {"<werkzeug>": <sekunden>},
    "origins": ["http://localhost", "http://127.0.0.1"],
    "embed": {"url": "https://host/embed/v1/embeddings", "token": "", "modell": ""},      optional (Stufe 3, im Schlaf)
    "llm":   {"url": "https://host/qwen/v1/chat/completions", "token": "", "modell": ""}  optional (Stufe 4, im Schlaf)
  }
Tokens stehen nur als SHA-256 in der Datei; das Token selbst wird beim Anlegen einmal ausgegeben.
Ohne Instanz startet der Server nicht (kein offener Zugang aus Versehen) — benannt, nicht still.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("~/.config/vi-mcp/config.json").expanduser()


#: Wer ohne Token kommt, wenn `offen` eingeschaltet ist: lesen, Handlungen melden, Wissen vorschlagen (Quarantäne). Keine Rechte.
OPEN = "offen"


@dataclass
class Instance:
    name: str
    token_sha256: str
    reflexes: bool = False
    release: bool = False  # darf heikle importierte Inhalte aus der Quarantäne freigeben
    human: bool = False  # darf Signale des Nutzers melden (POST /signal)


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
    #: Zugang ohne Token. Ein falsches Token bleibt trotzdem 401: Wer eins schickt, will eine bestimmte Instanz sein.
    open_: bool = False

    def instance_for(self, token: str | None) -> Instance | None:
        """Instanz zum Bearer-Token oder None. Vergleich in konstanter Zeit, über alle Instanzen."""
        if not token:
            return Instance(OPEN, "") if self.open_ else None
        h = hashlib.sha256(token.encode()).hexdigest()
        hits = None
        for i in self.instances.values():
            if hmac.compare_digest(h, i.token_sha256):
                hits = i
        return hits


def fpath() -> Path:
    return Path(os.environ.get("VI_MCP_CONFIG") or DEFAULT_PATH).expanduser()


def load(p: Path | None = None) -> Config:
    p = p or fpath()
    raw = json.loads(p.read_text()) if p.exists() else {}
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
    for n, d in (raw.get("instanzen") or {}).items():
        k.instances[n] = Instance(n, d["token_sha256"], bool(d.get("reflexe", False)), bool(d.get("freigabe", False)), bool(d.get("mensch", False)))
    return k


def create_instance(name: str, reflexes: bool = False, p: Path | None = None, release: bool = False, human: bool = False) -> str:
    """Instanz anlegen oder ihr Token erneuern. Liefert das neue Token (nur dieses eine Mal sichtbar)."""
    if not name or not all(c.isalnum() or c in "-_." for c in name):
        raise ValueError("Instanzname: Buchstaben, Ziffern, - _ .")
    if name == OPEN:
        raise ValueError(f"„{OPEN}“ ist für den Zugang ohne Token reserviert")
    p = p or fpath()
    raw = json.loads(p.read_text()) if p.exists() else {}
    token = secrets.token_urlsafe(32)
    raw.setdefault("instanzen", {})[name] = {"token_sha256": hashlib.sha256(token.encode()).hexdigest(), "reflexe": reflexes, "freigabe": release, "mensch": human}
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    old_umask_value = os.umask(0o077)
    try:
        tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    finally:
        os.umask(old_umask_value)
    # Rechte einer vorhandenen Datei übernehmen (Paket: root:vi-mcp 0640, damit der Dienst sie lesen kann);
    # eine neue Datei ist 0600 (nur der Eigentümer)
    if p.exists():
        st = os.stat(p)
        os.chmod(tmp, st.st_mode & 0o777)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
    else:
        os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    return token
