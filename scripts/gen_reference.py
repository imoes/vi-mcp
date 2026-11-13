"""Generates docs/REFERENCE.md from the code (0.54.0) — every MCP tool with every parameter, the command line, both configuration files,
the configuration catalogue, environment variables, HTTP endpoints and modules.

  python3 scripts/gen_reference.py           write docs/REFERENCE.md
  python3 scripts/gen_reference.py --check   exit 1 if docs/REFERENCE.md is not what the code says, or something has no description

What the code cannot say by itself (what a config key means, what an environment variable does) is written in the tables below; the
check fails when the code has a key, field, variable or endpoint that is missing here — a gap shows up in the test, not with a user.
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vi_mcp import api_en, config, configure, net_cli, net_service, tools  # noqa: E402

OUT = ROOT / "docs" / "REFERENCE.md"

#: config.json — what each key means (English since 0.51.0; the German names of older files in brackets are still read)
CONFIG_KEYS = {
    "bind": ("`\"127.0.0.1\"`", "Address(es) the server listens on: one string or a list, e.g. `[\"127.0.0.1\", \"172.19.0.1\"]` for a Docker gateway."),
    "port": ("`8765`", "TCP port of the MCP server (HTTP; TLS comes from a reverse proxy). `vi-mcp port N` changes it."),
    "db": ("`~/.local/share/vi-mcp/vi.db`", "The memory: an SQLite file on a local file system, or (0.50.0) a `postgresql://` URL without password — see OPERATIONS, PostgreSQL."),
    "instances": ("—", "[`instanzen`] Who may connect: `{name: {token_sha256, reflexes, release, human, family}}` — `reflexes` [`reflexe`] may write reflexes, `release` [`freigabe`] may release sensitive imports, `human` [`mensch`] may send user signals, `family` [`familie`] the model family (independent lines). Without an instance the server does not start."),
    "ttl": ("`{}` (120 s each)", "Validity of remembered tool answers per tool in seconds (at most 3600)."),
    "origins": ("localhost", "Allowed `Origin` headers for browser clients; requests without Origin are allowed."),
    "embed": ("—", "Embedding service `{url, token, model}` [`modell`]: OpenAI-compatible `/v1/embeddings` for vectors (semantic search). `vi-mcp embed setup` sets it."),
    "rerank": ("—", "Cross-encoder `{url, token, model}` (0.57.0): OpenAI/Jina-style `/v1/rerank`; `vi_recall` orders its best 30 hybrid hits by it. Off without it — measured: MRR 0.75 → 0.82, but ~2.3 s per search instead of ~0.65 s. `vi-mcp embed setup` sets it to the own service `vi-rerank` (0.60.0) when 30 documents take ≤ 5 s."),
    "hold_back": ("0.05", "Share of the actions with hints whose hints are held back at random (0.61.0, at most 0.25; 0 = off) — `vi_stats` C and the daily measurement compare them with the rest: the causal total effect of hints."),
    "local_models": ("—", "`auto`/`off` (0.60.0): whether the packages set up the own embedding service and reranker (`vi-mcp embed auto`); configure question `local_models`."),
    "llm": ("—", "Language model `{url, token, model}` [`modell`]: OpenAI-compatible chat endpoint for sleep, scorer and reviewer."),
    "p2p": ("`{}`", "The memory side of the networks: `networks` [`netze`] `{name: {kind, instance, auto_release, local, start}}` (`start`: the server the network starts from, written by `net wiki on --start`, 0.54.1), `reflexes_from` [`reflexe_von`], `auto_release` [`auto_freigabe`], `public_domains` [`oeffentliche_domains`], `internal_names` [`interne_namen`], `local` [`lokal`] (URL and token of the standard network's local listener). Kinds: `free`, `open`, `company` [`frei`, `offen`, `firma`]."),
    "reviewer_prompt": ("—", "[`pruefer_prompt`] Path of the reviewer's system prompt for foreign content; without it imports wait for a person."),
    "archive_days": ("built in", "[`lager_tage`] Days after which unused objects move to the long-term archive, per kind, e.g. `{\"erfahrung\": 30}`."),
    "open": ("`false`", "[`offen`] Open wiki mode: requests without a token are the instance `offen` — read, report actions, propose knowledge (quarantine)."),
    "socket": ("`/run/vi-mcp/mcp.sock` (package)", "Local Unix socket for `vi-mcp stdio` (Linux); the kernel names the user. `$VI_MCP_SOCKET` overrides."),
    "local": ("`{}`", "[`lokal`] Local users allowed on the socket: `{user: instance}`. `vi-mcp local USER INSTANCE` sets it."),
    "web": ("`false`", "The read-only web page of the free and open networks under `/web` (0.46.0). `vi-mcp web on|off`."),
    "web_base": ("`/web`", "[`web_basis`] Path the browser sees behind the reverse proxy, e.g. `/vi-mcp/web`."),
    "web_internal": ("`false`", "Internal knowledge search in the browser under `/intern` (0.62.0): sign-in with a VI token, shared and internal knowledge, never private."),
    "web_internal_base": ("`/intern`", "Path of the internal search as the browser sees it, e.g. `/vi-mcp/intern`; it scopes the session cookie."),
}

#: /etc/vi-p2p/<network>.json — the network service; in brackets the German keys of files before 0.51.0
NET_FIELDS = {
    "mode": "`standalone` (off), `peer` (outgoing only, behind a firewall) or `peerhost` (also reachable). [`modus`]",
    "net": "Name of the network (`standard` for /etc/vi-p2p/config.json). [`netz`]",
    "kind": "`free` (anyone may join), `open` (by invitation, anonymised) or `company` (one organisation, internal knowledge). [`art`]",
    "db": "Logbook: SQLite file, or a `postgresql://` URL — then the schema `netz_<name>`.",
    "seed": "Private key of this server in the network (Ed25519 seed).",
    "bind": "Address the service listens on (peerhost).",
    "port": "Port the service listens on (peerhost); several networks on 443 share the reverse proxy, each on its own port.",
    "address": "Public address others reach this server at, e.g. `https://HOST/vi-p2p/<net>`. [`adresse`]",
    "tls_cert": "Own TLS certificate (peerhost without reverse proxy).",
    "tls_key": "Key of `tls_cert`.",
    "ca_file": "CA bundle for peers' certificates. [`ca_datei`]",
    "founders": "Public keys of the founders (closed networks: they invite). [`gruender`]",
    "startpeers": "Addresses to start from (a free network: one server is enough).",
    "tick_s": "Seconds between rounds — the fallback since 0.52.0 (a peer keeps a long poll open). [`takt_s`]",
    "min_round_s": "Minimum seconds between two rounds. [`min_runde_s`]",
    "neighbors": "Peers per round. [`nachbarn`]",
    "http_allowed": "Allow unencrypted HTTP to other machines (lab only). [`http_erlaubt`]",
    "believe": "Publishers whose knowledge this server imports at all (`*` = every member). [`glauben`]",
    "mcp_url": "The memory's MCP endpoint the service talks to.",
    "mcp_token_file": "Token file of the service's own memory instance (`p2p`, `netz-<name>`). [`mcp_token_datei`]",
    "torrent": "`{active, directory, port}` [`aktiv`, `verzeichnis`]: large backlogs as torrent segments (needs python3-libtorrent).",
    "proxy": "HTTPS proxy for outgoing connections (CONNECT).",
    "no_proxy": "Hosts reached without the proxy. [`kein_proxy`]",
    "local_port": "Port of the local listener (127.0.0.1) for the memory's live searches and nudges. [`lokal_port`]",
    "local_bind": "Address the local listener binds to (0.62.6; default 127.0.0.1). In a container setup the address the memory container reaches; set by `net setup|join --local-bind`.",
    "local_token_sha256": "SHA-256 of the local listener's token (the memory holds the token). [`lokal_token_sha256`]",
    "pow_bits": "Free network: proof-of-work bits of the identity entry. [`arbeit_bits`]",
    "new_quota": "Free network: entries per day for publishers without measured benefit. [`quote_neu`]",
    "blocked": "Public keys or addresses this server does not accept, relay or answer. [`sperren`]",
    "private_ok": "Free network: allow private addresses learned from others (lab). [`privat_erlaubt`]",
}

ENV_VARS = {
    "VI_MCP_CONFIG": "Path of the server configuration (default `~/.config/vi-mcp/config.json`; the package: `/etc/vi-mcp/config.json`).",
    "VI_MCP_EXPORT_KEY": "Ed25519 key that signs index files (`vi-mcp index export`, 0.62.0; default `export.key` in the network directory `/var/lib/vi-p2p`, made on the first export).",
    "VI_MCP_EXTRA_PYTHON": "Directory with Python packages that the distribution lacks — clingo for the logic layer (`vi-mcp logic install`, 0.62.0; default `/var/lib/vi-mcp/python` as root, else `~/.local/share/vi-mcp/python`), appended to the import path after the system's packages.",
    "VI_MCP_CONFIGURE_STATE": "Which configuration questions were answered (default `/etc/vi-mcp/configure.json`).",
    "VI_MCP_TOKEN_DIR": "Where `vi-mcp configure` writes the token of a new instance (default `/root`, file `vi-mcp-token-<name>`, 0600).",
    "VI_MCP_FREIGABE_TOKEN_FILE": "Token file of `vi-mcp release` (the release right).",
    "VI_MCP_FEEDBACK_NUDGE": "Claude Code hook: `0` switches off the one feedback request at the end of a session (event `Stop`, 0.59.0).",
    "VI_MCP_KEIN_DIENST": "Tests and containers: `vi-mcp net …` does not start or stop systemd services.",
    "VI_MCP_KEIN_MENUE": "Package installation without the interactive menu.",
    "VI_MCP_KEIN_WIKI": "At installation: do not join the public wiki network (same as `VI_MCP_WIKI=false`).",
    "VI_MCP_SOCKET": "Local Unix socket of the server (`vi-mcp stdio`), instead of config `socket`.",
    "VI_MCP_URL": "Client side (hook, `vi-mcp image`): URL of the VI server.",
    "VI_MCP_TOKEN": "Hermes Agent: the token referenced as `${VI_MCP_TOKEN}` in its MCP configuration (`~/.hermes/.env`).",
    "VI_MCP_TOKEN_FILE": "Client side (hook, `vi-mcp image`): file with the instance token.",
    "VI_MCP_SIGNAL_TOKEN_FILE": "Hook: token of the human instance for user signals (corrections, grades).",
    "VI_MCP_RELEASE_KEY": "Release: private Ed25519 key that signs SHA256SUMS (default `~/.config/vi-mcp/release-ed25519.pem`).",
    "VI_MCP_RELEASE_SCHLUESSEL": "Old name of `VI_MCP_RELEASE_KEY`.",
    "VI_MCP_REPO_GNUPG": "Release: GnuPG home with the OpenPGP key of the apt/dnf repository (default `~/.config/vi-mcp/repo-gnupg`).",
    "VI_P2P_CONFIG": "Path of a network service's configuration (default `/etc/vi-p2p/config.json`; `--network NAME` → `/etc/vi-p2p/NAME.json`).",
    "VI_P2P_DIR": "Directory of the network configurations (default `/etc/vi-p2p`).",
    "VI_MCP_TEST_PG": "Tests: run the whole suite against this PostgreSQL URL (every test its own schema).",
}
#: VI_MCP_<KEY> of the configuration catalogue are listed from configure.QUESTIONS, not here

ENDPOINTS = [
    ("memory server", "POST", "/mcp", "MCP over Streamable HTTP (JSON-RPC): initialize, tools/list, tools/call. Bearer token = instance."),
    ("memory server", "DELETE", "/mcp", "End the conversation (`Mcp-Session-Id`)."),
    ("memory server", "GET", "/health", "Health: `ok vi-mcp <version>`. Old name `/gesund` still answered."),
    ("memory server", "POST", "/signal", "User signals from the hook (correction, grade) — token of a human instance."),
    ("memory server", "GET", "/web", "Read-only web page of the free and open networks (config `web`)."),
    ("network service", "GET", "/netz/health", "Health and version (peers gate new entry types on it). Old name `/netz/gesund` still answered."),
    ("network service", "POST", "/netz/koepfe", "Exchange heads: the highest sequence number per publisher."),
    ("network service", "GET", "/netz/log/<pub>", "Entries of one publisher from `ab`, at most `max`."),
    ("network service", "POST", "/netz/eintraege", "Push entries (a peer behind a firewall pushes its own)."),
    ("network service", "POST", "/netz/anstoss", "Nudge: something new, run a round now."),
    ("network service", "POST", "/netz/warten", "Long poll of a peer (0.52.0): answered at once when there are entries it lacks or a relayed search."),
    ("network service", "POST", "/netz/suche", "Live search of a member; a peerhost also relays it to its waiting peers (0.52.0)."),
    ("network service", "POST", "/netz/suche/antwort", "A waiting peer's signed answer to a relayed search."),
    ("network service", "GET", "/netz/peers", "Peer exchange (free network)."),
    ("network service", "GET", "/netz/segmente/<pub>", "Torrent segments of a publisher."),
    ("network service", "POST", "/netz/beitritt", "Join with a one-time code (closed network)."),
    ("local listener (127.0.0.1)", "POST", "/lokal/suche", "The memory's live search through the service (token)."),
    ("local listener (127.0.0.1)", "POST", "/lokal/anstoss", "The memory has something new for the network (0.52.0)."),
]


def _md(s) -> str:
    return " ".join(str(s or "").split()).replace("|", "\\|")


def _tools() -> list[str]:
    german = {en: de for de, en in api_en.TOOL_ALIASES.items()} if hasattr(api_en, "TOOL_ALIASES") else {}
    pa = {en: de for de, en in api_en.PARAM_ALIASES.items()}
    out = ["## MCP tools", "", f"{len(tools.TOOLS)} tools. German names (before 0.22.0) remain valid as aliases (`vi_mcp/api_en.py`). "
           "`OPEN` = usable without a token (open wiki mode).", ""]
    for t in tools.TOOLS:
        n = t["name"]
        alias = f" · German alias `{german[n]}`" if n in german else ""
        out += [f"### `{n}`", "", _md(t["description"]) + ("" if n not in tools.OPEN_ALLOWED else " **OPEN**") + alias, ""]
        props = t["inputSchema"].get("properties", {})
        req = set(t["inputSchema"].get("required", []))
        if props:
            out += ["| Parameter | Type | Required | Meaning |", "|---|---|---|---|"]
            for p, spec in props.items():
                typ = spec.get("type", "")
                if spec.get("enum"):
                    typ += " (" + ", ".join(map(str, spec["enum"])) + ")"
                if typ == "array":
                    typ = "array of " + str((spec.get("items") or {}).get("type", "")) if spec.get("items") else typ
                desc = spec.get("description") or ""
                if p in pa:
                    desc = (desc + f" (German: `{pa[p]}`)").strip()
                out.append(f"| `{p}` | {_md(typ)} | {'yes' if p in req else ''} | {_md(desc)} |")
            out.append("")
    return out


def _cli() -> list[str]:
    import ast  # not imported: vi_mcp/__main__.py runs the command line when it is imported
    usage = (ast.get_docstring(ast.parse((ROOT / "vi_mcp" / "__main__.py").read_text(encoding="utf-8"))) or "").strip()
    out = ["## Command line", "", "`vi-mcp` (package) or `python3 -m vi_mcp`. German command names stay valid as aliases.", "", "```text", usage, "```", ""]
    out += ["### `vi-mcp net`", "", "Network service commands; `--network NAME` addresses a further network (`/etc/vi-p2p/NAME.json`, service `vi-p2p@NAME`).", ""]
    parser = net_cli._parser() if hasattr(net_cli, "_parser") else None
    if parser is None:
        return out
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        parser.print_help()
    out += ["```text", buf.getvalue().rstrip(), "```", ""]
    for action in parser._subparsers._group_actions if parser._subparsers else []:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        seen = set()
        for name, sub in action.choices.items():
            if id(sub) in seen:
                continue
            seen.add(id(sub))
            b = io.StringIO()
            with contextlib.redirect_stdout(b):
                sub.print_help()
            out += [f"#### `vi-mcp net {name}`", "", "```text", b.getvalue().rstrip(), "```", ""]
    return out


def _config() -> list[str]:
    out = ["## Server configuration (`config.json`)", "",
           "`$VI_MCP_CONFIG`, default `~/.config/vi-mcp/config.json`; the package uses `/etc/vi-mcp/config.json` (root:vi-mcp 0640). "
           "English keys since 0.51.0; the German keys of older files (in brackets) are still read and rewritten in English at the next "
           "package install (a copy of the old file stays).", "", "| Key | Default | Meaning |", "|---|---|---|"]
    out += [f"| `{k}` | {d} | {_md(m)} |" for k, (d, m) in CONFIG_KEYS.items()]
    fields = net_service.NetConfig.__dataclass_fields__
    out += ["", "## Network service configuration (`/etc/vi-p2p/<network>.json`)", "",
            "`/etc/vi-p2p/config.json` is the network `standard`; `vi-mcp net --network NAME setup …` writes `/etc/vi-p2p/NAME.json`. "
            "Keys are the field names below (English since 0.51.0; old German keys in brackets are still read).", "",
            "| Field | Default | Meaning |", "|---|---|---|"]
    for name, f in fields.items():
        default = f.default if f.default is not f.default_factory else None
        if f.default_factory is not getattr(__import__("dataclasses"), "MISSING"):
            default = f.default_factory()
        out.append(f"| `{name}` | `{default!r}` | {_md(NET_FIELDS.get(name, ''))} |")
    out += ["", "## Configuration catalogue (debconf, `vi-mcp configure`, `VI_MCP_<KEY>`)", "",
            "Asked at the first installation (Debian: debconf; RPM and everywhere: `vi-mcp configure`); unattended through the environment "
            "variable of each key.", "", "| Key | Variable | Default | Question |", "|---|---|---|---|"]
    out += [f"| `{q.key}` | `{q.env}` | `{q.default}` | {_md(q.title)} — {_md(q.text)} |" for q in configure.QUESTIONS]
    return out + [""]


def _env() -> list[str]:
    out = ["## Environment variables", "", "Besides the `VI_MCP_<KEY>` of the configuration catalogue above.", "", "| Variable | Meaning |", "|---|---|"]
    return out + [f"| `{k}` | {_md(v)} |" for k, v in sorted(ENV_VARS.items())] + [""]


def _endpoints() -> list[str]:
    out = ["## HTTP endpoints", "", "| Process | Method | Path | Meaning |", "|---|---|---|---|"]
    return out + [f"| {w} | {m} | `{p}` | {_md(d)} |" for w, m, p, d in ENDPOINTS] + [""]


def _modules() -> list[str]:
    out = ["## Modules (`vi_mcp/`)", "", "First line of each module's docstring.", "", "| Module | Purpose |", "|---|---|"]
    for p in sorted(glob.glob(str(ROOT / "vi_mcp" / "*.py"))):
        name = Path(p).stem
        if name == "__init__":
            continue
        src = Path(p).read_text(encoding="utf-8")
        m = re.match(r'\s*(?:#[^\n]*\n\s*)*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', src, re.S)
        first = (m.group(1).strip().splitlines()[0] if m and m.group(1).strip() else "")
        out.append(f"| `{name}` | {_md(first)} |")
    return out + [""]


def render() -> str:
    from vi_mcp import __version__
    head = ["# vi-mcp reference", "",
            f"Generated from the code of vi-mcp {__version__} by `scripts/gen_reference.py` — do not edit by hand; a test fails when it is out "
            "of date. Explanations: [README](../README.md) · design: [ARCHITECTURE](ARCHITECTURE.md) · operations: [OPERATIONS](OPERATIONS.md) · "
            "all documents: [docs/README](README.md).", "",
            "Contents: [MCP tools](#mcp-tools) · [Command line](#command-line) · [Server configuration](#server-configuration-configjson) · "
            "[Network service configuration](#network-service-configuration-etcvi-p2pnetworkjson) · "
            "[Configuration catalogue](#configuration-catalogue-debconf-vi-mcp-configure-vi_mcp_key) · "
            "[Environment variables](#environment-variables) · [HTTP endpoints](#http-endpoints) · [Modules](#modules-vi_mcp)", ""]
    return "\n".join(head + _tools() + _cli() + _config() + _env() + _endpoints() + _modules()).rstrip() + "\n"


def gaps() -> list[str]:
    """What the code has and the tables above do not describe."""
    out = []
    src = (ROOT / "vi_mcp" / "config.py").read_text()
    for k in sorted(set(re.findall(r'raw\.get\("([a-z_0-9]+)"', src)) | {"p2p"}):
        if k not in CONFIG_KEYS:
            out.append(f"config key {k}")
    for f in net_service.NetConfig.__dataclass_fields__:
        if f not in NET_FIELDS:
            out.append(f"network field {f}")
    code = "\n".join(Path(p).read_text(encoding="utf-8", errors="replace") for p in glob.glob(str(ROOT / "vi_mcp" / "*.py")) + glob.glob(str(ROOT / "hook" / "*.py"))
                     + glob.glob(str(ROOT / "deploy" / "*.sh")) + glob.glob(str(ROOT / "deploy" / "windows" / "*.ps1")) + glob.glob(str(ROOT / "tests" / "conftest.py")))
    catalogue = {q.env for q in configure.QUESTIONS}
    for v in sorted(set(re.findall(r"\b(VI_MCP_[A-Z_]+[A-Z]|VI_P2P_[A-Z_]+[A-Z])\b", code))):
        if v not in ENV_VARS and v not in catalogue and v not in ("VI_MCP_",):
            out.append(f"environment variable {v}")
    served = "\n".join((ROOT / "vi_mcp" / f).read_text() for f in ("server.py", "net_service.py"))
    listed = {p for _w, _m, p, _d in ENDPOINTS}
    for p in sorted(set(re.findall(r'"(/(?:netz|lokal|signal|gesund|health|mcp)[a-z/_]*)"', served))):
        if p not in listed and p not in OLD_NAMES and not any(x.startswith(p) for x in listed):
            out.append(f"endpoint {p}")
    return out


OLD_NAMES = {"/gesund", "/netz/gesund"}  # 0.59.1: still answered, described next to /health


def main(argv: list[str]) -> int:
    text = render()
    missing = gaps()
    if "--check" in argv:
        bad = []
        if missing:
            bad.append("undescribed: " + ", ".join(missing))
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            bad.append(f"{OUT.relative_to(ROOT)} is out of date — run python3 scripts/gen_reference.py")
        for b in bad:
            print(b, file=sys.stderr)
        return 1 if bad else 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)" + (f"; undescribed: {', '.join(missing)}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
