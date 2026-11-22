"""0.71.0: the server serves its own client integration — a client that knows only the server's URL and a token installs the hooks.

Before, the hooks came only from the local package (vi-mcp setup → /usr/share/vi-mcp/hook/vi_hook.py); a client on another machine
needed the package or a checkout. An MCP server cannot install hooks or change a client's settings (MCP specification; Claude Code docs
code.claude.com/docs/en/mcp), so the vehicle is a client plugin, served here (user decision 22.11.2026, design VI insight:848cb1f6).

Routes (GET, no token — nothing served here is secret; the token never appears in a served file or a URL):
  /plugins                               plain-text index: what is served and the install commands per client
  /plugins/claude/marketplace.json       Claude Code marketplace with one plugin; its source is the archive below (url + sha256)
  /plugins/claude/vi-mcp-<version>.zip   the Claude Code plugin: .claude-plugin/plugin.json (userConfig url, token — sensitive),
                                         .mcp.json (http server, Authorization from user_config), hooks/hooks.json, hook/vi_hook.py
  /plugins/hook/vi_hook.py               the hook itself (standard library only), for Codex and Hermes

Claude Code fetches an archive source only over https and never from a loopback, link-local or cloud-metadata host
(code.claude.com/docs/en/plugins/marketplace-reference, "archive"); the marketplace.json itself may come over http. Behind the reverse
proxy set `public_url` (e.g. https://host/vi-mcp) — otherwise the URLs are derived from the request (X-Forwarded-Proto/-Host/-Prefix,
then Host). Config `plugins: false` switches the routes off (404).

The archive is built in memory and deterministically (fixed timestamps and modes): the same version and URL give the same bytes and
the same sha256, so the marketplace entry stays valid between two requests and across restarts."""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from . import __version__

ROUTE = "/plugins"
NAME = "vi-mcp"
#: the hook events, the same as vi-mcp setup --hook installs locally (setup.HOOK_EVENTS and the four without matcher)
TOOL_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")
OTHER_EVENTS = ("SessionStart", "SessionEnd", "UserPromptSubmit", "Stop")
HOOK_TIMEOUT = 5
_HOST = re.compile(r"^[A-Za-z0-9.\-]+(?::\d{1,5})?$|^\[[0-9A-Fa-f:.]+\](?::\d{1,5})?$")
_PREFIX = re.compile(r"^(/[A-Za-z0-9._\-]+)*$")
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def hook_path() -> Path:
    """The hook script this server ships: the package's copy, else the repository's (as setup._hook_script)."""
    package = Path("/usr/share/vi-mcp/hook/vi_hook.py")
    return package if package.exists() else Path(__file__).resolve().parents[1] / "hook" / "vi_hook.py"


def base_url(public_url: str | None, headers) -> str | None:
    """The URL a client sees in front of /plugins and /mcp, without a trailing slash. None when the request does not name a usable
    host (then nothing can be served that points back here)."""
    if public_url:
        return public_url.rstrip("/")
    proto = (headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip().lower()
    host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").split(",")[0].strip()
    prefix = (headers.get("X-Forwarded-Prefix") or "").split(",")[0].strip().rstrip("/")
    if proto not in ("http", "https") or not _HOST.match(host) or not _PREFIX.match(prefix):
        return None
    return f"{proto}://{host}{prefix}"


def claude_files(base: str) -> dict[str, bytes]:
    """The files of the Claude Code plugin. `base` only sets the default of the url option; the token is an option the user enters."""
    manifest = {
        "name": NAME, "version": __version__,
        "description": "Memory of the VI (vi-mcp): hints before every action, outcomes after it, the memory's tools over MCP.",
        "homepage": "https://github.com/imoes/vi-mcp", "license": "MIT",
        "userConfig": {
            "url": {"type": "string", "title": "vi-mcp URL", "required": True, "default": f"{base}/mcp",
                    "description": "MCP endpoint of the vi-mcp server (…/mcp)."},
            "token": {"type": "string", "title": "vi-mcp token", "required": False, "sensitive": True,
                      "description": "Bearer token of your instance (vi-mcp instance NAME on the server). Empty: an open server."},
        },
    }
    mcp = {"mcpServers": {NAME: {"type": "http", "url": "${user_config.url}",
                                 "headers": {"Authorization": "Bearer ${user_config.token}"}}}}
    command = 'python3 -I "${CLAUDE_PLUGIN_ROOT}/hook/vi_hook.py"'
    hook = {"type": "command", "command": command, "timeout": HOOK_TIMEOUT}
    hooks = {"hooks": {**{e: [{"matcher": "*", "hooks": [hook]}] for e in TOOL_EVENTS}, **{e: [{"hooks": [hook]}] for e in OTHER_EVENTS}}}
    readme = (f"# vi-mcp plugin {__version__}\n\nServed by the vi-mcp server at {base}. Hooks report every action to the memory and "
              "bring its hints; the MCP server gives the memory's tools. URL and token are plugin options (the token is kept in the "
              "client's secure credential store). Do not combine with a local `vi-mcp setup --hook`: both would report.\n")
    return {
        ".claude-plugin/plugin.json": (json.dumps(manifest, indent=2) + "\n").encode(),
        ".mcp.json": (json.dumps(mcp, indent=2) + "\n").encode(),
        "hooks/hooks.json": (json.dumps(hooks, indent=2) + "\n").encode(),
        "hook/vi_hook.py": hook_path().read_bytes(),
        "README.md": readme.encode(),
    }


def zip_bytes(files: dict[str, bytes]) -> bytes:
    """A zip with fixed timestamps and modes, entries in name order — same input, same bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, _ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((0o755 if name.endswith(".py") else 0o644) | 0o100000) << 16
            info.create_system = 3
            z.writestr(info, files[name])
    return buf.getvalue()


def archive_name() -> str:
    return f"{NAME}-{__version__}.zip"


_cache: dict[str, tuple[bytes, str]] = {}


def claude_archive(base: str) -> tuple[bytes, str]:
    """(zip bytes, sha256 hex) for this base URL; cached per base (the hook file is read once per base and version)."""
    if base not in _cache:
        data = zip_bytes(claude_files(base))
        _cache[base] = (data, hashlib.sha256(data).hexdigest())
    return _cache[base]


def marketplace(base: str) -> dict:
    _data, sha = claude_archive(base)
    return {"name": NAME, "owner": {"name": "vi-mcp server"},
            "metadata": {"description": f"Client integration served by the vi-mcp server at {base}", "version": __version__},
            "plugins": [{"name": NAME, "version": __version__,
                         "description": "Hooks and MCP connection of the VI memory (vi-mcp).",
                         "source": {"source": "archive", "url": f"{base}{ROUTE}/claude/{archive_name()}", "sha256": sha}}]}


def index(base: str) -> str:
    https = base.startswith("https://")
    return (f"vi-mcp {__version__} — client integration served by this server\n\n"
            f"Claude Code (plugin: hooks + MCP connection; URL and token are plugin options, the token is stored as a secret):\n"
            f"  claude plugin marketplace add {base}{ROUTE}/claude/marketplace.json\n"
            f"  claude plugin install {NAME}@{NAME}       (then /plugin → {NAME} → configure: token)\n"
            + ("" if https else "  NOTE: Claude Code downloads the plugin archive only over https — set public_url to the https address.\n")
            + f"\nFiles:\n  {base}{ROUTE}/claude/marketplace.json\n  {base}{ROUTE}/claude/{archive_name()}\n"
            f"  {base}{ROUTE}/hook/vi_hook.py  (standard library only)\n")


def handle(path: str, public_url: str | None, headers) -> tuple[int, str, bytes, dict]:
    """(status, content type, body, extra headers) for a GET under /plugins. Never reads the request's Authorization header."""
    p = path.split("?", 1)[0].rstrip("/") or "/"
    base = base_url(public_url, headers)
    if p == f"{ROUTE}/hook/vi_hook.py":
        data = hook_path().read_bytes()
        return 200, "text/x-python; charset=utf-8", data, {"X-Content-SHA256": hashlib.sha256(data).hexdigest()}
    if base is None:
        return 400, "text/plain; charset=utf-8", b"no usable Host header and no public_url configured\n", {}
    if p == ROUTE:
        return 200, "text/plain; charset=utf-8", index(base).encode(), {}
    if p == f"{ROUTE}/claude/marketplace.json":
        return 200, "application/json", (json.dumps(marketplace(base), indent=2) + "\n").encode(), {"Cache-Control": "no-cache"}
    if p == f"{ROUTE}/claude/{archive_name()}":
        data, sha = claude_archive(base)
        return 200, "application/zip", data, {"X-Content-SHA256": sha, "Content-Disposition": f'attachment; filename="{archive_name()}"'}
    if p.startswith(f"{ROUTE}/claude/") and p.endswith(".zip"):
        return 404, "text/plain; charset=utf-8", f"only version {__version__} is served: {archive_name()}\n".encode(), {}
    return 404, "text/plain; charset=utf-8", f"unknown path; see {ROUTE}\n".encode(), {}
