"""Code in the index (0.61.0): `vi-mcp index import-code <repo> --index X` puts the code of a git repository into an index.

The user (12.11.2026): "Die VI soll aber auch mit Code gefüllt werden." Runs where the repository is (a workstation, CI, the server) and
sends the pieces over MCP (vi_code_sync), so the server never needs the repository.

- What: only versioned files of the current commit (`git ls-files -s` gives each file's blob SHA, `git rev-parse HEAD` the commit). Binary
  files, files over MAX_BYTES, generated and vendored trees and lock files are skipped — counted with the reason.
- Pieces: Python by `ast` — top-level functions and classes (a class over CLASS_SPLIT lines in its methods) plus a head piece (docstring,
  imports); other text in blocks of at most BLOCK_LINES lines cut at blank lines; a small file (< WHOLE_LINES) stays whole.
- Incremental: the server knows the blob SHA of every file it holds for (index, repo); only changed files and the list of removed ones
  are sent. Removed pieces go to the long-term archive on the server — nothing disappears silently.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

MAX_BYTES = 512 * 1024
BLOCK_LINES = 120
WHOLE_LINES = 200
CLASS_SPLIT = 150
BATCH = 50
SKIP_DIRS = ("dist/", "build/", "node_modules/", "vendor/", ".venv/", "venv/", "__pycache__/", "site-packages/")
SKIP_NAMES = re.compile(r"(\.min\.[a-z]+|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|go\.sum|composer\.lock)$")
LANGS = {".py": "py", ".sh": "sh", ".bash": "sh", ".ps1": "ps1", ".js": "js", ".mjs": "js", ".ts": "ts", ".tsx": "ts", ".jsx": "js",
         ".go": "go", ".rs": "rs", ".java": "java", ".kt": "kt", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "cs",
         ".rb": "rb", ".php": "php", ".sql": "sql", ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".toml": "toml", ".ini": "ini",
         ".cfg": "ini", ".conf": "conf", ".md": "md", ".rst": "rst", ".html": "html", ".css": "css", ".j2": "jinja", ".tf": "tf",
         ".spec": "spec", ".wxs": "xml", ".xml": "xml", ".service": "systemd", ".cmd": "cmd", ".txt": "txt"}
NAMED = {"Dockerfile": "docker", "Makefile": "make", "Jenkinsfile": "groovy"}


def language(path: str) -> str | None:
    p = Path(path)
    return NAMED.get(p.name) or LANGS.get(p.suffix.lower())


# ── pieces ────────────────────────────────────────────────────────────────

def _piece(symbol: str, kind: str, lines: list[str], start: int, end: int, sig: str = "") -> dict:
    return {"symbol": symbol, "art": kind, "von": start, "bis": end, "code": "\n".join(lines[start - 1:end]), "signatur": sig[:200]}


def chunk_python(src: str) -> list[dict]:
    """Top-level functions and classes (big classes in methods) plus a head piece. Falls back to text blocks if it does not parse."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return chunk_text(src)
    lines = src.splitlines()
    out: list[dict] = []
    defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    first = min((n.lineno - len(getattr(n, "decorator_list", []) or []) for n in defs), default=len(lines) + 1)
    head_end = max(1, first - 1)
    if lines and any(x.strip() for x in lines[:head_end]):
        doc = ast.get_docstring(tree) or ""
        out.append(_piece("(module)", "module", lines, 1, min(head_end, len(lines)), doc.splitlines()[0] if doc else ""))
    for n in defs:
        start = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
        end = n.end_lineno or n.lineno
        sig = (ast.get_docstring(n) or "").splitlines()[0] if ast.get_docstring(n) else lines[n.lineno - 1].strip()
        if isinstance(n, ast.ClassDef) and end - start + 1 > CLASS_SPLIT:
            methods = [m for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            body_start = min((m.lineno for m in methods), default=end + 1)
            out.append(_piece(n.name, "class", lines, start, max(start, body_start - 1), sig))
            for m in methods:
                ms = min([m.lineno] + [d.lineno for d in m.decorator_list])
                msig = (ast.get_docstring(m) or "").splitlines()[0] if ast.get_docstring(m) else lines[m.lineno - 1].strip()
                out.append(_piece(f"{n.name}.{m.name}", "method", lines, ms, m.end_lineno or m.lineno, msig))
        else:
            out.append(_piece(n.name, "class" if isinstance(n, ast.ClassDef) else "function", lines, start, end, sig))
    return out or chunk_text(src)


def chunk_text(src: str) -> list[dict]:
    """A small file whole; otherwise blocks of at most BLOCK_LINES lines, cut at the last blank line before the limit."""
    lines = src.splitlines()
    if not lines:
        return []
    if len(lines) < WHOLE_LINES:
        return [_piece("(file)", "file", lines, 1, len(lines), next((x.strip() for x in lines if x.strip()), ""))]
    out, start = [], 1
    while start <= len(lines):
        end = min(len(lines), start + BLOCK_LINES - 1)
        if end < len(lines):
            blank = max((i for i in range(start + BLOCK_LINES // 2, end + 1) if not lines[i - 1].strip()), default=None)
            end = blank or end
        out.append(_piece(f"(lines {start}-{end})", "block", lines, start, end, next((x.strip() for x in lines[start - 1:end] if x.strip()), "")))
        start = end + 1
    return out


def chunks(path: str, src: str) -> list[dict]:
    return chunk_python(src) if path.endswith(".py") else chunk_text(src)


# ── the repository ────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=120).stdout


def collect(repo: Path) -> tuple[str, dict[str, tuple[str, str]], dict[str, str]]:
    """(commit, {path: (blob sha, language)}, {path: reason skipped}) of the versioned files."""
    commit = _git(repo, "rev-parse", "HEAD").strip()
    files, skipped = {}, {}
    for line in _git(repo, "ls-files", "-s", "-z").split("\0"):
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        mode, sha = meta.split()[0], meta.split()[1]
        if mode.startswith("16"):  # a submodule
            skipped[path] = "submodule"
            continue
        if any(f"/{d}" in f"/{path}" for d in SKIP_DIRS) or SKIP_NAMES.search(path):
            skipped[path] = "generated or vendored"
            continue
        lang = language(path)
        if lang is None:
            skipped[path] = "not a text/code file type"
            continue
        files[path] = (sha, lang)
    return commit, files, skipped


def read_text(repo: Path, path: str) -> tuple[str | None, str | None]:
    p = repo / path
    try:
        raw = p.read_bytes()
    except OSError as e:
        return None, f"unreadable: {e}"
    if len(raw) > MAX_BYTES:
        return None, f"over {MAX_BYTES // 1024} KB"
    if b"\0" in raw[:8192]:
        return None, "binary"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return raw.decode("latin-1"), None


# ── a minimal MCP client (Streamable HTTP, like the hook) ─────────────────

class Client:
    def __init__(self, url: str, token: str | None, timeout: float = 120):
        self.url, self.token, self.timeout, self.sid, self.n = url, token, timeout, None, 0

    def _post(self, body: dict) -> dict | None:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             **({"Authorization": f"Bearer {self.token}"} if self.token else {}), **({"Mcp-Session-Id": self.sid} if self.sid else {})}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=h, method="POST")
        op = urllib.request.build_opener(urllib.request.ProxyHandler({})) if "://127.0.0.1" in self.url or "://localhost" in self.url \
            else urllib.request.build_opener()
        with op.open(req, timeout=self.timeout) as r:
            self.sid = self.sid or r.headers.get("Mcp-Session-Id")
            raw = r.read()
        if not raw:
            return None
        text = raw.decode("utf-8", "replace")
        if text.lstrip().startswith("data:") or "\ndata:" in text:  # an SSE answer: the last data line
            text = [x[5:].strip() for x in text.splitlines() if x.startswith("data:")][-1]
        return json.loads(text)

    def start(self) -> None:
        self.n += 1
        self._post({"jsonrpc": "2.0", "id": self.n, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "vi-mcp-code-import", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, name: str, args: dict) -> str:
        self.n += 1
        a = self._post({"jsonrpc": "2.0", "id": self.n, "method": "tools/call", "params": {"name": name, "arguments": args}})
        if not a or "error" in a:
            raise RuntimeError(f"{name}: {(a or {}).get('error')}")
        res = a["result"]
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise RuntimeError(f"{name}: {text[:300]}")
        return text


# ── the import ────────────────────────────────────────────────────────────

def run(repo: Path, index: str, call, name: str | None = None, dry_run: bool = False) -> dict:
    """Send what changed since the server's state. `call(tool, args) -> str` (a Client's call, or the server's tools.call_tool in tests)."""
    from . import indexes
    repo = repo.resolve()
    idx = indexes.normalize(index)
    if not idx or idx == indexes.GLOBAL:
        raise ValueError("code goes into a project index, not global (--index NAME)")
    rname = re.sub(r"[^A-Za-z0-9._-]", "_", name or repo.name)[:60]
    commit, files, skipped = collect(repo)
    state = json.loads(call("vi_code_sync", {"action": "state", "index": idx, "repo": rname}) or "{}")
    known = state.get("dateien") or {}
    changed = [p for p, (sha, _l) in files.items() if known.get(p) != sha]
    removed = [p for p in known if p not in files]
    report = {"repo": rname, "index": idx, "commit": commit[:12], "dateien": len(files), "geaendert": len(changed),
              "entfernt": len(removed), "uebersprungen": len(skipped), "stuecke": 0, "gesendet_stapel": 0}
    reasons: dict[str, int] = {}
    for r in skipped.values():
        reasons[r] = reasons.get(r, 0) + 1
    batch: list[dict] = []
    pieces = 0

    def flush(rm: list[str]) -> None:
        nonlocal batch
        if (batch or rm) and not dry_run:
            call("vi_code_sync", {"action": "sync", "index": idx, "repo": rname, "commit": commit, "files": batch, "removed": rm})
            report["gesendet_stapel"] += 1
        batch = []

    for path in sorted(changed):
        src, why = read_text(repo, path)
        if src is None:
            reasons[why] = reasons.get(why, 0) + 1
            report["uebersprungen"] += 1
            continue
        cs = chunks(path, src)
        pieces += len(cs)
        batch.append({"path": path, "sha": files[path][0], "lang": files[path][1], "chunks": cs})
        if sum(len(f["chunks"]) for f in batch) >= BATCH:
            flush([])
    flush(removed)
    report["stuecke"] = pieces
    report["gruende"] = reasons
    report["trocken"] = dry_run
    return report


def main(argv: list[str]) -> int:
    import argparse
    a = argparse.ArgumentParser(prog="vi-mcp index import-code", description="put the code of a git repository into an index")
    a.add_argument("repo", type=Path)
    a.add_argument("--index", required=True, help="the project index (not global)")
    a.add_argument("--name", help="repository name (default: the directory name)")
    a.add_argument("--url", default=os.environ.get("VI_MCP_URL"), help="MCP URL of the server (default: VI_MCP_URL, else the local server)")
    a.add_argument("--token-file", default=os.environ.get("VI_MCP_TOKEN_FILE"), help="file with the instance token (default: VI_MCP_TOKEN_FILE)")
    a.add_argument("--dry-run", action="store_true", help="count what would be sent, send nothing")
    o = a.parse_args(argv)
    url = o.url
    if not url:
        from . import config
        url = f"http://127.0.0.1:{config.load().port}/mcp"
    token = Path(o.token_file).expanduser().read_text().strip() if o.token_file else None
    try:
        c = Client(url, token)
        c.start()
        r = run(o.repo, o.index, c.call, o.name, o.dry_run)
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as e:
        print(f"vi-mcp index import-code: {e}", file=sys.stderr)
        return 1
    print(json.dumps(r, indent=2, ensure_ascii=os.name == "nt"))
    return 0


# ── the server side (vi_code_sync) ────────────────────────────────────────

CODE_TAG = "art_wissen:code"


def piece_id(index: str, repo: str, path: str, symbol: str) -> str:
    import hashlib
    return "erkenntnis:code-" + hashlib.sha256(f"{index}|{repo}|{path}|{symbol}".encode()).hexdigest()[:24]


def tag_value(s: str) -> str:
    """A hashtag value: no blanks or brackets (memory.TAG)."""
    return re.sub(r"[\s()]", "_", s)[:200] or "_"


def _held(index: str, repo: str, path: str | None = None) -> list:
    from . import memory as g
    sql = ("SELECT id FROM objekt WHERE idx = ? AND modus = 'aktiv' AND id IN (SELECT objekt_id FROM tag WHERE tag = ?) "
           "AND id IN (SELECT objekt_id FROM tag WHERE tag = ?)")
    par = [index, CODE_TAG, f"repo:{tag_value(repo)}"]
    if path is not None:
        sql += " AND id IN (SELECT objekt_id FROM tag WHERE tag = ?)"
        par.append(f"datei:{tag_value(path)}")
    with g.lock:
        ids = [r[0] for r in g.db().execute(sql, par)]
    return list(g.load_many(ids).values())


def server_state(index: str, repo: str) -> dict:
    """{dateien: {path: blob sha}, commit} of what the index holds of this repository."""
    files, commit = {}, None
    held = _held(index, repo)
    for o in held:
        files[o.data.get("datei")] = o.data.get("sha")
        commit = commit or o.data.get("commit")
    return {"dateien": files, "commit": commit, "stuecke": len(held)}


def server_sync(index: str, repo: str, commit: str, files: list[dict], removed: list[str], instance: str) -> dict:
    """Upsert the pieces of the changed files (fixed id per index/repo/path/symbol), archive pieces that are gone. Visibility internal."""
    from . import anonymize, archive
    from . import memory as g
    out = {"neu": 0, "aktualisiert": 0, "archiviert": 0, "geheimnisse_ersetzt": 0}
    reason = f"removed in commit {commit[:12]}"
    for f in files:
        path, sha, lang = str(f["path"]), str(f["sha"]), str(f.get("lang") or "txt")
        keep = set()
        for c in f.get("chunks") or []:
            oid = piece_id(index, repo, path, str(c["symbol"]))
            keep.add(oid)
            code = str(c.get("code") or "")
            clean = anonymize.without_secrets(code)
            if clean != code:
                out["geheimnisse_ersetzt"] += 1
            text = f"{path}:{c['symbol']} — {c.get('signatur') or c.get('art') or ''}"[:300]
            data = {"quelle": f"{repo}@{commit[:12]}:{path}:{c.get('von')}-{c.get('bis')}", "inhalt": clean, "datei": path, "sha": sha,
                    "symbol": c["symbol"], "stueck": c.get("art"), "von": c.get("von"), "bis": c.get("bis"), "commit": commit, "repo": repo}
            tags = [CODE_TAG, f"datei:{tag_value(path)}", f"sprache:{tag_value(lang)}", f"repo:{tag_value(repo)}"]
            o = g.load(oid)
            if o is None:
                g.new_object("erkenntnis", text, tags, data, who=f"code@{instance}", reason="code import", oid=oid, instance=instance,
                             visibility="intern", index=index, link=False)
                out["neu"] += 1
            else:
                o.text, o.data, o.hashtags, o.mode, o.idx = anonymize.without_secrets(text), data, tags, "aktiv", index
                o.change(f"code@{instance}", f"updated to commit {commit[:12]}", "code import")
                g.save(o)
                out["aktualisiert"] += 1
        for o in _held(index, repo, path):
            if o.id not in keep:
                archive.store_in_archive(o, reason)
                out["archiviert"] += 1
    for path in removed:
        for o in _held(index, repo, str(path)):
            archive.store_in_archive(o, reason)
            out["archiviert"] += 1
    return out


def file_line(index: str, file_path: str) -> tuple[str | None, str | None]:
    """0.61.0: before Read/Edit/Write of a file in the project's index — which pieces it holds. (line, repo-relative path) or (None, None)."""
    from . import memory as g
    fp = str(file_path).replace("\\", "/")
    with g.lock:
        rows = g.db().execute("SELECT DISTINCT t.tag FROM tag t JOIN objekt o ON o.id = t.objekt_id WHERE o.idx = ? AND o.modus = 'aktiv' "
                              "AND t.tag LIKE 'datei:%' AND o.id IN (SELECT objekt_id FROM tag WHERE tag = ?)", (index, CODE_TAG)).fetchall()
    paths = [r[0][6:] for r in rows]
    best = max((p for p in paths if fp.endswith("/" + p) or fp == p), key=len, default=None)
    if best is None:
        return None, None
    with g.lock:
        ids = [r[0] for r in g.db().execute("SELECT o.id FROM objekt o JOIN tag t ON t.objekt_id = o.id WHERE o.idx = ? AND o.modus = 'aktiv' "
                                            "AND t.tag = ?", (index, f"datei:{best}"))]
    pieces = sorted(g.load_many(ids).values(), key=lambda o: o.data.get("von") or 0)
    names = [str(o.data.get("symbol")) for o in pieces if not str(o.data.get("symbol", "")).startswith("(")]
    commit = next((str(o.data.get("commit"))[:7] for o in pieces if o.data.get("commit")), "?")
    shown = ", ".join(names[:12]) + (f" … (+{len(names) - 12})" if len(names) > 12 else "") if names else f"{len(pieces)} piece(s)"
    return f"Code index {index}: {best} holds {shown} (commit {commit}; vi_recall datei:{best} index={index})", best
