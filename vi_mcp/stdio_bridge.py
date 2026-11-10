"""0.36.0: `vi-mcp stdio` — MCP over stdio for clients on the server host, without a token.

A client starts this process and talks JSON-RPC to it, one message per line (MCP stdio transport,
https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#stdio). Each message is passed as an HTTP request over the
local Unix socket of the running service (config `socket`, default /run/vi-mcp/mcp.sock); there the kernel names the user and config
`lokal` maps the user to an instance (`vi-mcp local USER INSTANCE`). So there stays one process that writes the memory, and nobody
handles a token.

  claude mcp add vi-mcp -- vi-mcp stdio
  codex mcp add vi-mcp -- vi-mcp stdio

stdout carries only JSON-RPC; everything else goes to stderr. If the service restarted (session unknown, 404), the bridge repeats
the client's initialize once and sends the message again — the client does not notice. A refusal (403, service not running) comes back
as a JSON-RPC error with the reason.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import sys

DEFAULT_SOCKET = "/run/vi-mcp/mcp.sock"
TIMEOUT_S = 300  # a semantic search or a sleep started by hand can take a while


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str):
        super().__init__("localhost", timeout=TIMEOUT_S)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


class Bridge:
    def __init__(self, path: str, out=None):
        self.path = path
        self.out = out or sys.stdout.buffer
        self.sid: str | None = None
        self.init: dict | None = None

    def _request(self, method: str, body: bytes | None) -> tuple[int, dict, bytes]:
        c = _UnixConnection(self.path)
        try:
            h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **({"Mcp-Session-Id": self.sid} if self.sid else {})}
            c.request(method, "/mcp", body=body, headers=h)
            r = c.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            c.close()

    def _write(self, obj) -> None:
        self.out.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode() + b"\n")
        self.out.flush()

    def _errors(self, msg, text: str) -> None:
        """A JSON-RPC error for every request (with id) in msg; notifications get nothing."""
        for m in msg if isinstance(msg, list) else [msg]:
            if isinstance(m, dict) and m.get("id") is not None and "method" in m:
                self._write({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32000, "message": text}})

    def _post(self, msg) -> tuple[int, dict, bytes]:
        return self._request("POST", json.dumps(msg).encode())

    def handle(self, line: bytes) -> None:
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"not JSON: {e}"}})
            return
        is_init = isinstance(msg, dict) and msg.get("method") == "initialize"
        if is_init:
            self.init, self.sid = msg, None
        try:
            st, h, body = self._post(msg)
            if st == 404 and not is_init and self.init is not None:  # the service restarted: open the session again, once
                self.sid = None
                st0, h0, _b = self._post(self.init)
                if st0 == 200:
                    self.sid = h0.get("mcp-session-id")
                    self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
                    print("vi-mcp stdio: session renewed after a service restart", file=sys.stderr)
                    st, h, body = self._post(msg)
        except OSError as e:
            self._errors(msg, f"vi-mcp service not reachable on {self.path} ({e.strerror or e}) — is it running on this host (0.36.0 or newer)?")
            return
        if is_init and st == 200:
            self.sid = h.get("mcp-session-id")
        if st == 200 and body:
            self._write(json.loads(body))
        elif st >= 400:
            self._errors(msg, f"vi-mcp: HTTP {st} — {body.decode(errors='replace').strip()[:500]}")

    def close(self) -> None:
        if self.sid:
            try:
                self._request("DELETE", None)  # the conversation is saved as ended, not left open until it times out
            except OSError:
                pass


def main(argv: list[str]) -> int:
    path = os.environ.get("VI_MCP_SOCKET") or DEFAULT_SOCKET
    if argv[:1] == ["--socket"] and len(argv) == 2:
        path = argv[1]
    elif argv:
        print(__doc__, file=sys.stderr)
        return 2
    b = Bridge(path)
    try:
        for line in sys.stdin.buffer:
            if line.strip():
                b.handle(line)
    except KeyboardInterrupt:
        pass
    finally:
        b.close()
    return 0
