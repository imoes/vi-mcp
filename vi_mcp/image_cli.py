"""0.35.0: `vi-mcp image` — put an image file with its description into memory, or fetch one back.

  vi-mcp image FILE --text "what it shows" --hashtags thema:x,host:y --source "where it comes from"
                    [--content-file F|-] [--regions F.json] [--visibility shared|internal] [--importance 0-3]
  vi-mcp image get ID OUTFILE

An AI session runs this instead of pasting megabytes of base64 into a tool call. It talks MCP to the server the clients use:
VI_MCP_URL and VI_MCP_TOKEN_FILE if set, else ~/.config/vi-mcp/hook.json, else the vi-mcp entry in ~/.claude.json (URL and token
as vi-mcp setup wrote them). --regions is a JSON list in the output format of SAM 3: [{"concept", "box": [x0, y0, x1, y1],
"score", "mask"?}] (see docs/ARCHITECTURE.md, "Images").
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _endpoint() -> tuple[str, str | None]:
    """(URL, token or None) of the server this user's clients talk to."""
    if os.environ.get("VI_MCP_URL"):
        f = os.environ.get("VI_MCP_TOKEN_FILE")
        return os.environ["VI_MCP_URL"], (Path(f).expanduser().read_text().strip() or None) if f else None
    hook = Path.home() / ".config" / "vi-mcp" / "hook.json"
    if hook.exists():
        c = json.loads(hook.read_text(encoding="utf-8"))
        f = c.get("token_file")
        return c["url"], (Path(f).read_text().strip() or None) if f else None
    claude = Path.home() / ".claude.json"
    if claude.exists():
        e = (json.loads(claude.read_text(encoding="utf-8")).get("mcpServers") or {}).get("vi-mcp")
        if e and e.get("url"):
            auth = (e.get("headers") or {}).get("Authorization") or ""
            return e["url"], auth[7:] if auth.startswith("Bearer ") else None
    raise SystemExit("no VI server known: set VI_MCP_URL (and VI_MCP_TOKEN_FILE) or run vi-mcp setup first")


def _call(tool: str, arguments: dict) -> dict:
    url, token = _endpoint()

    def post(body: dict, sid: str | None = None):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             **({"Authorization": f"Bearer {token}"} if token else {}), **({"Mcp-Session-Id": sid} if sid else {})}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode(), headers=h), timeout=120) as a:
                return a.headers.get("Mcp-Session-Id"), json.loads(a.read() or b"{}")
        except urllib.error.HTTPError as e:  # e.g. 401 wrong token, 413 body too large: name it, no traceback
            raise SystemExit(f"{url}: HTTP {e.code} — {e.read().decode(errors='replace')[:300].strip()}") from None
        except urllib.error.URLError as e:
            raise SystemExit(f"{url}: not reachable ({e.reason})") from None
    sid, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "vi-mcp-image"}}})
    _, a = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}, sid)
    if "error" in a:
        raise SystemExit(f"{tool}: {a['error'].get('message')}")
    return a["result"]


def main(argv: list[str]) -> int:
    if argv[:1] == ["get"]:
        if len(argv) != 3:
            print(__doc__, file=sys.stderr)
            return 2
        r = _call("vi_object", {"id": argv[1]})
        pics = [c for c in r["content"] if c.get("type") == "image"]
        if r.get("isError") or not pics:
            print(r["content"][0]["text"] if r["content"] else "no answer", file=sys.stderr)
            return 1
        Path(argv[2]).write_bytes(base64.b64decode(pics[0]["data"]))
        print(f"{argv[2]}: {pics[0]['mimeType']}, {len(base64.b64decode(pics[0]['data']))} bytes")
        return 0
    p = argparse.ArgumentParser(prog="vi-mcp image", description="put an image with its description into the VI memory")
    p.add_argument("file")
    p.add_argument("--text", required=True, help="what the image shows, one sentence (the hint text)")
    p.add_argument("--hashtags", required=True, help="comma separated kind:value")
    p.add_argument("--source", required=True, help="where the image comes from (command, host and time, or URL)")
    p.add_argument("--content-file", help="the complete description (file, or - for standard input)")
    p.add_argument("--regions", help="JSON file: regions in SAM 3 format [{concept, box, score, mask?}]")
    p.add_argument("--visibility", choices=("shared", "internal"))
    p.add_argument("--importance", type=int)
    a = p.parse_args(argv)
    args = {"text": a.text, "hashtags": [t.strip() for t in a.hashtags.split(",") if t.strip()], "source": a.source,
            "image": base64.b64encode(Path(a.file).read_bytes()).decode()}
    if a.content_file:
        args["content"] = sys.stdin.read() if a.content_file == "-" else Path(a.content_file).read_text(encoding="utf-8")
    if a.regions:
        args["regions"] = json.loads(Path(a.regions).read_text(encoding="utf-8"))
    if a.visibility:
        args["visibility"] = a.visibility
    if a.importance is not None:
        args["importance"] = a.importance
    r = _call("vi_learn", args)
    print(r["content"][0]["text"])
    return 1 if r.get("isError") else 0
