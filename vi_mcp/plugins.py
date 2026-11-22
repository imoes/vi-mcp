"""0.71.0: the server serves its own client integration — a client that knows only the server's URL and a token installs the hooks.

Before, the hooks came only from the local package (vi-mcp setup → /usr/share/vi-mcp/hook/vi_hook.py); a client on another machine
needed the package or a checkout. An MCP server cannot install hooks or change a client's settings (MCP specification; Claude Code docs
code.claude.com/docs/en/mcp), so the vehicle is a client plugin, served here (user decision 22.11.2026, design VI insight:848cb1f6).

Routes (GET, no token — nothing served here is secret; the token never appears in a served file or a URL):
  /plugins                               plain-text index: what is served and the install commands per client
  /plugins/claude/marketplace.json       Claude Code marketplace with one plugin; its source is the archive below (url + sha256)
  /plugins/claude/vi-mcp-<version>.zip   the Claude Code plugin: .claude-plugin/plugin.json (userConfig url, token — sensitive),
                                         .mcp.json (http server, Authorization from user_config), hooks/hooks.json, hook/vi_hook.py
  /plugins/vi-mcp-setup.pyz              installer for Codex (MCP + hook) and Hermes (MCP + prompt hook): a zipapp of the package's own
                                         vi_mcp/setup.py with the hook — the same code as `vi-mcp setup`, deterministic, sha256 in a header
  /plugins/hook/vi_hook.py               the hook itself (standard library only)

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


SETUP_NAME = "vi-mcp-setup.pyz"
#: what the installer carries: the setup of the package itself (standard library + PyYAML for Hermes), never a second implementation
SETUP_MODULES = ("__init__.py", "config.py", "setup.py")
_SETUP_MAIN = '''"""vi-mcp client setup, served by the vi-mcp server at {base} (version {version}).

It is the setup of the vi-mcp package (vi_mcp/setup.py), packed with the hook: it copies the hook to
~/.local/share/vi-mcp/hook/vi_hook.py and registers what you name — Codex (MCP + hook), Hermes (MCP + prompt hook), Claude Code
(MCP + hook, if you do not want the plugin). The token is read from a file or standard input, never from the command line.

  python3 vi-mcp-setup.pyz --codex --codex-hook --hermes --token-file -
  python3 vi-mcp-setup.pyz --status
"""
import os
import sys
import zipfile
from pathlib import Path

BASE = {base_repr}


def main() -> int:
    from vi_mcp import setup
    z = setup.target()
    dest = z.home / ".local" / "share" / "vi-mcp" / "hook" / "vi_hook.py"
    data = zipfile.ZipFile(os.path.dirname(os.path.abspath(__file__))).read("hook/vi_hook.py")
    with setup._as_user(z):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_bytes() != data:
            dest.write_bytes(data)
        dest.chmod(0o755)
    os.environ.setdefault("VI_MCP_HOOK_SCRIPT", str(dest))
    os.environ.setdefault("VI_MCP_URL", BASE + "/mcp")
    return setup.main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
'''


def setup_files(base: str) -> dict[str, bytes]:
    pkg = Path(__file__).resolve().parent
    files = {f"vi_mcp/{m}": (pkg / m).read_bytes() for m in SETUP_MODULES}
    files["hook/vi_hook.py"] = hook_path().read_bytes()
    files["__main__.py"] = _SETUP_MAIN.format(base=base, version=__version__, base_repr=repr(base)).encode()
    return files


_setup_cache: dict[str, tuple[bytes, str]] = {}


def setup_pyz(base: str) -> tuple[bytes, str]:
    """0.71.0: the installer for Codex and Hermes (and Claude Code without the plugin) — a zipapp, deterministic like the archive."""
    if base not in _setup_cache:
        data = b"#!/usr/bin/env python3\n" + zip_bytes(setup_files(base))
        _setup_cache[base] = (data, hashlib.sha256(data).hexdigest())
    return _setup_cache[base]


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
            + f"\nCodex CLI and Hermes Agent (the setup of the vi-mcp package with the hook; token from standard input, never an argument):\n"
            f"  curl -fsSO {base}{ROUTE}/{SETUP_NAME}        (sha256: {setup_pyz(base)[1]})\n"
            f"  python3 {SETUP_NAME} --codex --codex-hook --token-file -     Codex runs the hook only after you trust it: /hooks\n"
            f"  python3 {SETUP_NAME} --hermes --token-file -                  Hermes needs PyYAML (python3-yaml)\n"
            f"\nFiles:\n  {base}{ROUTE}/claude/marketplace.json\n  {base}{ROUTE}/claude/{archive_name()}\n"
            f"  {base}{ROUTE}/{SETUP_NAME}\n  {base}{ROUTE}/hook/vi_hook.py  (standard library only)\n")


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
    if p == f"{ROUTE}/{SETUP_NAME}":
        data, sha = setup_pyz(base)
        return 200, "application/octet-stream", data, {"X-Content-SHA256": sha, "Content-Disposition": f'attachment; filename="{SETUP_NAME}"'}
    if p.startswith(f"{ROUTE}/claude/") and p.endswith(".zip"):
        return 404, "text/plain; charset=utf-8", f"only version {__version__} is served: {archive_name()}\n".encode(), {}
    return 404, "text/plain; charset=utf-8", f"unknown path; see {ROUTE}\n".encode(), {}
