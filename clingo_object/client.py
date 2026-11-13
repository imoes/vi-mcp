"""The VI server as seen from a clingo-object program: a small MCP client over HTTP (standard library only).

Where the server is and which token to use is found the way the vi-mcp hook finds it (hook/vi_hook.py):
  1. VI_MCP_URL and VI_MCP_TOKEN_FILE in the environment,
  2. otherwise ~/.config/vi-mcp/hook.json (url, token_file), written by `vi-mcp setup`,
  3. otherwise http://127.0.0.1:8765/mcp and ~/.config/vi-mcp/token-claude if it exists.
A token is read from its file and never printed. Requests go direct first, then through the proxy of the environment (as setup does).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LOCAL = ("127.0.0.1", "localhost", "::1")


class ServerError(RuntimeError):
    """The server could not be reached, refused, or answered with an error — the message says which."""


def _config() -> tuple[str, Path | None]:
    url = os.environ.get("VI_MCP_URL")
    token_file = os.environ.get("VI_MCP_TOKEN_FILE")
    if not url:
        try:
            c = json.loads((Path.home() / ".config" / "vi-mcp" / "hook.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            c = {}
        url = c.get("url") or "http://127.0.0.1:8765/mcp"
        token_file = token_file or c.get("token_file")
    if not token_file:
        default = Path.home() / ".config" / "vi-mcp" / "token-claude"
        token_file = str(default) if default.exists() else None
    return url, (Path(token_file).expanduser() if token_file else None)


class Memory:
    """objects(filters) gives the memory objects a program reads; check/save/propose/rate send the compiled program to the server."""

    def __init__(self, url: str | None = None, token_file: str | Path | None = None, timeout: float = 60.0):
        u, t = _config()
        self.url = url or u
        self.token_file = Path(token_file).expanduser() if token_file else t
        self.timeout = timeout
        self._sid: str | None = None

    def __repr__(self):
        return f"Memory({self.url!r})"  # never the token

    def _token(self) -> str | None:
        if self.token_file is None or str(self.token_file) == os.devnull:
            return None
        try:
            return self.token_file.read_text(encoding="utf-8").strip() or None
        except OSError as e:
            raise ServerError(f"token file {self.token_file} not readable: {e}") from e

    def _open(self, req: urllib.request.Request):
        last: Exception | None = None
        local = (urllib.parse.urlsplit(self.url).hostname or "") in LOCAL
        for op in (urllib.request.build_opener(urllib.request.ProxyHandler({})), None if local else urllib.request.build_opener()):
            if op is None:
                break
            try:
                return op.open(req, timeout=self.timeout)
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last = e
        raise ServerError(f"{self.url} not reachable: {last}")

    def _post(self, body: dict, sid: str | None = None) -> tuple[int, dict, dict | None]:
        token = self._token()
        h = {**({"Authorization": f"Bearer {token}"} if token else {}), "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        if sid:
            h["Mcp-Session-Id"] = sid
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            with self._open(req) as r:
                raw = r.read()
                return r.status, {k.lower(): v for k, v in dict(r.headers).items()}, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, {}, None

    def _login(self) -> str:
        st, h, _a = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "clingo-object", "version": "1"}}})
        sid = h.get("mcp-session-id")
        if st != 200 or not sid:
            raise ServerError(f"initialize: HTTP {st}" + (" — token refused?" if st in (401, 403) else ""))
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        return sid

    def call(self, tool: str, args: dict) -> str:
        """Call a tool of the VI; on an unknown session (server restarted) log in again once."""
        for attempt in range(2):
            if self._sid is None:
                self._sid = self._login()
            st, _h, a = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": args}}, self._sid)
            if st == 404 and attempt == 0:
                self._sid = None
                continue
            if st != 200 or not a or "result" not in a:
                raise ServerError(f"{tool}: HTTP {st} {json.dumps(a)[:200] if a else ''}")
            text = a["result"]["content"][0]["text"]
            if a["result"].get("isError"):
                raise ServerError(f"{tool}: {text[:500]}")
            return text
        raise ServerError(f"{tool}: session still unknown after logging in again")

    # ── what a program needs ────────────────────────────────────────────────
    def objects(self, filters: list[str], edges: bool = True) -> dict:
        return json.loads(self.call("vi_logic", {"action": "objects", "filters": list(filters), "edges": bool(edges)}))

    def check(self, source: str) -> str:
        return self.call("vi_logic", {"action": "check", "source": source})

    def ask(self, source: str, queries: list[str]) -> str:
        return self.call("vi_logic", {"action": "ask", "source": source, "queries": list(queries)})

    def save(self, name: str, source: str, description: str = "", visibility: str | None = None) -> str:
        return self.call("vi_logic", {"action": "save", "name": name, "source": source, "description": description,
                                      **({"visibility": visibility} if visibility else {})})

    def propose(self, source: str) -> str:
        return self.call("vi_logic", {"action": "propose", "source": source})

    def rate(self, source: str, conclusion: str, correct: bool) -> str:
        return self.call("vi_logic", {"action": "rate", "source": source, "conclusion": conclusion, "correct": bool(correct)})
