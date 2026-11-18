"""Documentation import (0.69.0): pages of an outside source (Confluence, a vendor manual, a knowledge base) into the memory — the
dedicated import access, the counterpart of code_import for documents.

Why (the user, 17.11.2026: "gibt es einen eigenen import api zugang? Das wäre doch sinnvoll. Und für die KI dokumentieren"): documents
were imported page by page through vi_learn with an agent's token — one call and one embedding per page, the old shape could only be
retired by the instance that wrote it (so a Confluence import had to run as one user's instance), the ids of old objects had to be read
from the database, pages removed at the source stayed, and an imported page carried only administrative hashtags (source, space, page),
so it appeared as a hint before an action almost never (10.11.2026: 73 of 12,994 Confluence objects ever recalled).

What the import access does:
- A right of its own: only an instance created with `vi-mcp instance NAME --import` may call vi_doc_sync (config `"import": true`);
  agents' tokens cannot mass-write or archive documentation.
- One object per page (vi-mcp ≥ 0.67 shape): the whole page as Markdown, the server chunks it for search itself (chunking.py). Only a
  page over memory.CONTENT_MAX is split into parts. The id is fixed per source and page (not per instance): any import instance updates
  the same object, unchanged pages (same content hash) are skipped.
- Hashtags at once: source_kind, knowledge_kind, page, space, area; the source's own labels (label:), its service (service:); and the
  triggers that make a page appear before matching actions — host: and topic: derived exactly as sleep step 6b does (doc_triggers),
  now at import time, so a page does not wait for several sleeps.
- Links between pages of the same source become edges ("doc link"), also when the target arrives in a later batch.
- The old shape is retired by the server: active objects of the same source and page that this import did not write (section parts,
  older imports, whoever wrote them) go to the long-term archive with a reason naming the new object (restorable); their host:, topic:,
  area:, label: and service: hashtags move to the new page object, so nothing a person or sleep added is lost.
- Pages listed as removed are archived with a reason; secrets in the content are replaced (anonymize.without_secrets) and counted.
- Vectors are not computed in the call: the on-demand catch-up (rounds of at most on_demand.VECTOR_MAX_S) and sleep step 7 add them in
  the background, not inside the import call.

The client side (`vi-mcp docs import FILE.jsonl --source S …`) reads one page per JSON line, asks the server what it holds (state), sends
changed pages in batches and, with --prune, the pages the source no longer has. Guide for people and AIs: docs/IMPORT.md.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from . import memory as g

PAGES_MAX = 50                      # pages per sync call
BATCH_CHARS_MAX = 4_000_000         # characters of Markdown per sync call
LINKS_MAX = 20                      # edges to linked pages per page (edge explosion of 09.11.2026: 2.49 M edges)
LABELS_MAX = 10
TEXT_MAX = 1000                     # tools.TEXT_MAX: the key statement
KNOWLEDGE_KINDS = ("company-docs", "external-docs", "manual")
SUPERSEDABLE = ("insight", "rule", "skill")
CARRIED_KINDS = ("host", "topic", "area", "label", "service")  # hashtag kinds of the old shape that move to the new page object
_FIXED_KINDS = {"instance", "kind", "mode", "reviewer", "origin", "publisher", "tool", "source_kind", "knowledge_kind", "page"}
_SLUG = re.compile(r"[^a-z0-9._-]+")


def slug(s: str, n: int = 60) -> str:
    return _SLUG.sub("-", str(s or "").lower()).strip("-")[:n] or "unknown"


def page_tag(page_id: str) -> str:
    """page:<id> — an id that is a plain word stays readable (Confluence numbers), any other (an URL) becomes its 12-hex sha1."""
    pid = str(page_id)
    return f"page:{pid}" if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", pid) else f"page:{hashlib.sha1(pid.encode()).hexdigest()[:12]}"


def object_id(source: str, page_id: str, part: int) -> str:
    return g.keyed_id("insight", "doc-" + hashlib.sha256(f"{source}|{page_id}|{part}".encode()).hexdigest()[:24])


def content_sha(md: str) -> str:
    return hashlib.sha256(md.encode()).hexdigest()


def parts_of(md: str) -> list[str]:
    """The page, or — over memory.CONTENT_MAX — consecutive parts cut at paragraph boundaries."""
    if len(md) <= g.CONTENT_MAX:
        return [md]
    out, cur = [], ""
    for block in md.split("\n\n"):
        while len(block) > g.CONTENT_MAX:  # a single block longer than the limit (rare): cut it hard
            if cur:
                out.append(cur)
                cur = ""
            out.append(block[:g.CONTENT_MAX])
            block = block[g.CONTENT_MAX:]
        if cur and len(cur) + 2 + len(block) > g.CONTENT_MAX:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        out.append(cur)
    return out


# ------------------------------------------------------------------------------------------------ server side

def _doc_objects(source: str, page_id: str | None = None, include_archived: bool = False) -> list[g.MemoryObject]:
    """Objects this import wrote for a source (one page or all)."""
    sql = "SELECT o.id FROM object o JOIN tag t ON t.object_id = o.id AND t.tag = ? WHERE o.data LIKE ?"
    par: list = [f"source_kind:{slug(source)}", '%"doc_import": {%']
    if not include_archived:
        sql += " AND o.mode != 'archived'"
    if page_id is not None:
        sql += " AND o.id IN (SELECT object_id FROM tag WHERE tag = ?)"
        par.append(page_tag(page_id))
    with g.lock:
        ids = [r[0] for r in g.db().execute(sql, par)]
    objs = [o for o in g.load_many(ids).values() if (o.data.get("doc_import") or {}).get("source") == source]
    return [o for o in objs if page_id is None or o.data["doc_import"].get("page_id") == str(page_id)]


def _old_shape(source: str, page_id: str, old_source_kind: str | None = None) -> list[g.MemoryObject]:
    """Active knowledge objects of the same source and page that this import did not write: the shape it replaces. old_source_kind: the
    source_kind: value an older import filed the pages under, when it differs from the source's name (e.g. two vendor manuals once
    imported together as stibodx, now the sources cue-docs and dcx-docs)."""
    with g.lock:
        ids = [r[0] for r in g.db().execute(
            "SELECT o.id FROM object o JOIN tag a ON a.object_id = o.id AND a.tag = ? JOIN tag b ON b.object_id = o.id AND b.tag = ? "
            "WHERE o.mode NOT IN ('archived', 'merged', 'refuted', 'withdrawn') AND o.data NOT LIKE ?",
            (f"source_kind:{slug(old_source_kind or source)}", page_tag(page_id), '%"doc_import": {%')).fetchall()]
    return [o for o in g.load_many(ids).values() if o.kind in SUPERSEDABLE]


def server_state(source: str) -> dict:
    """{pages: {page_id: content sha256 of the whole page}, objects, index} of what the memory holds of this source."""
    pages, n, idx = {}, 0, set()
    for o in _doc_objects(source):
        d = o.data["doc_import"]
        # 0.69.1: a page tagged by an older import version reports no hash, so the client sends it again and it is re-tagged
        pages[d["page_id"]] = d.get("page_sha256") if d.get("tagger") == TAGGER_VERSION else None
        n += 1
        idx.add(o.idx)
    return {"source": source, "pages": pages, "objects": n, "indexes": sorted(i for i in idx if i)}


#: 0.69.1: the version of how an import derives hashtags — a page imported with another version is re-tagged even if its text is the same
TAGGER_VERSION = 2


def _tags_for(source: str, kk: str, page: dict, text: str, md: str) -> tuple[list[str], dict]:
    from . import doc_triggers
    tags = [f"source_kind:{slug(source)}", f"knowledge_kind:{kk}", page_tag(page["page_id"])]
    if page.get("space"):
        tags.append(f"space:{slug(page['space'])}")
    if page.get("area"):
        tags.append(f"area:{slug(page['area'])}")
    for lab in list(page.get("labels") or [])[:LABELS_MAX]:
        if str(lab).strip():
            tags.append(f"label:{slug(lab)}")
    if page.get("service"):
        tags.append(f"service:{slug(page['service'])}")
    for t in page.get("tags") or []:
        t = str(t).strip()
        if g.TAG.match(t) and t.split(":", 1)[0] not in _FIXED_KINDS:
            tags.append(t)
    names, topics = doc_triggers.cached_vocabulary()
    # 0.69.1: topics from the TITLE only (the key statement carries the body's first 300 characters: topic:for, topic:old …);
    # hosts from title, key statement and the whole page
    hosts, tops = doc_triggers.derive(str(page.get("title") or ""), f"{text}\n{md}", names, topics)
    tags += [f"host:{h}" for h in hosts] + [f"topic:{t}" for t in tops]
    tags = [t for t in dict.fromkeys(tags) if g.TAG.match(t)]
    return tags, {"version": doc_triggers.VERSION, "host": hosts, "topic": tops, "at": "import"}


def server_sync(source: str, pages: list[dict], removed: list[str], instance: str, index: str | None = None,
                knowledge_kind: str = "company-docs", label: str | None = None, old_source_kind: str | None = None) -> dict:
    """Upsert the pages (fixed id per source/page/part), retire the old shape and leftover parts, archive removed pages, link pages."""
    from . import anonymize, archive, doc_triggers, indexes
    if not source or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,40}", source):
        raise ValueError("source: a short name, a-z 0-9 . _ - (e.g. confluence-it, cue-docs)")
    if knowledge_kind not in KNOWLEDGE_KINDS:
        raise ValueError(f"knowledge_kind must be one of {', '.join(KNOWLEDGE_KINDS)}")
    if len(pages) > PAGES_MAX:
        raise ValueError(f"at most {PAGES_MAX} pages per call ({len(pages)} given)")
    if sum(len(str(p.get("markdown") or "")) for p in pages) > BATCH_CHARS_MAX:
        raise ValueError(f"at most {BATCH_CHARS_MAX} characters of Markdown per call — send fewer pages")
    idx = indexes.normalize(index) if index else None
    if idx and idx != indexes.GLOBAL:
        indexes.describe(idx, kind="special") if not _index_exists(idx) else None
    out = {"new": 0, "updated": 0, "unchanged": 0, "parts": 0, "old_shape_archived": 0, "leftover_parts_archived": 0,
           "removed_archived": 0, "secrets_replaced": 0, "links": 0, "with_host": 0, "with_topic": 0, "rejected": []}
    who = f"import@{instance}"
    touched: list[tuple[str, g.MemoryObject]] = []
    for page in pages:
        pid = str(page.get("page_id") or "").strip()
        md = str(page.get("markdown") or "").strip()
        title = re.sub(r"\s+", " ", str(page.get("title") or "")).strip()
        if not pid or len(md) < 20:
            out["rejected"].append(f"{pid or '?'}: page_id and markdown (≥ 20 characters) are required")
            continue
        stripped, n_cred = anonymize.strip_credentials(md)  # 0.69.3: the check for documents (password columns, answers, …)
        clean = anonymize.without_secrets(stripped)
        out["secrets_replaced"] += clean != md
        sha = content_sha(md)  # of the page as the source sent it — the client compares with that; the stored content is the clean one
        held = {o.data["doc_import"].get("part", 1): o for o in _doc_objects(source, pid)}
        parts = parts_of(clean)
        if held and all(o.data["doc_import"].get("page_sha256") == sha and o.data["doc_import"].get("tagger") == TAGGER_VERSION
                        for o in held.values()) and len(held) == len(parts) \
                and all((o.idx or "global") == (idx or o.idx or "global") for o in held.values()):
            out["unchanged"] += 1
            touched += [(pid, o) for o in held.values()]
            continue
        lbl = (label or page.get("label") or source).strip()
        page_objs = []
        for i, content in enumerate(parts, 1):
            part = f" (part {i}/{len(parts)})" if len(parts) > 1 else ""
            lead = re.sub(r"\s+", " ", re.sub(r"^#+ .*$", "", content, flags=re.M)).strip()[:300]
            text = f"{lbl}: {title or pid}{part} — {lead}"[:TEXT_MAX]
            tags, trig = _tags_for(source, knowledge_kind, page, f"{title} {text}", content)
            data = {"source": f"{page.get('url') or pid} · version {page.get('version', '?')} · import {source}, {time.strftime('%d.%m.%Y')}"[:500],
                    "content": content, "derived_triggers": trig, "secrets_checked": anonymize.CREDENTIALS_VERSION,
                    "doc_import": {"source": source, "page_id": pid, "part": i, "parts": len(parts), "page_sha256": sha, "tagger": TAGGER_VERSION,
                                   "url": page.get("url"), "version": page.get("version"), "updated": page.get("updated"),
                                   "links": [str(x) for x in (page.get("links") or [])][:200]}}
            oid = object_id(source, pid, i)
            o = g.load(oid)
            if o is not None:  # 0.69.2: hashtags carried over from the old shape at the first import stay on every update
                kept = [t for t in (o.data.get("doc_import") or {}).get("carried") or [] if not (
                    t.startswith("topic:") and t[6:] in doc_triggers.STOPWORDS)]
                tags = list(dict.fromkeys(tags + kept))
                data["doc_import"]["carried"] = kept
            if o is None:
                o = g.new_object("insight", text, tags, data, who=who, reason="doc import", oid=oid, instance=instance,
                                 visibility="internal", index=idx, link=False)
                out["new"] += 1
            else:
                o.text, o.data, o.hashtags, o.mode = text, {**{k: v for k, v in o.data.items() if k in ("useful", "last_shown", "class")}, **data}, \
                    sorted(set(tags) | {t for t in o.hashtags if t.split(":", 1)[0] in ("instance", "kind")}), "active"
                if idx:
                    o.idx = idx
                o.change(who, f"updated from {source} (version {page.get('version', '?')})", "doc import")
                g.save(o)
                out["updated"] += 1
            out["parts"] += len(parts) > 1
            out["with_host"] += bool(trig["host"])
            out["with_topic"] += bool(trig["topic"])
            page_objs.append(o)
            touched.append((pid, o))
        first = page_objs[0]
        for n, o in held.items():  # parts an earlier, longer version had
            if n > len(parts) and o.mode != "archived":
                archive.store_in_archive(o, f"the page {pid} of {source} now has {len(parts)} part(s); replaced by {first.id}")
                out["leftover_parts_archived"] += 1
        olds = _old_shape(source, pid, old_source_kind)
        carried = {t for old in olds for t in old.hashtags if t.split(":", 1)[0] in CARRIED_KINDS
                   and not (t.startswith("topic:") and t[6:] in doc_triggers.STOPWORDS)}  # no filler word comes along
        carried -= {t for t in carried if t.startswith("area:") and any(x.startswith("area:") for x in first.hashtags)}
        gained = sorted(carried - set(first.hashtags))
        if gained:  # what people or sleep had added to the old shape stays with the page — recorded, so later updates keep it
            first.hashtags = sorted(set(first.hashtags) | carried)
            first.data["doc_import"]["carried"] = sorted(set(first.data["doc_import"].get("carried") or []) | set(gained))
            first.change(who, "hashtags of the old shape kept: " + " ".join(gained), "doc import")
            g.save(first)
            out["tags_carried"] = out.get("tags_carried", 0) + 1
        for old in olds:
            first.link(old.id, "Beleg (supersedes: the same page in the import shape)")
            archive.store_in_archive(old, f"superseded by {first.id}: the page {pid} of {source}, imported as one object (doc import)")
            out["old_shape_archived"] += 1
    for pid in removed or []:
        pid = str(pid)
        for o in _doc_objects(source, pid) + _old_shape(source, pid, old_source_kind):
            archive.store_in_archive(o, f"the page {pid} is no longer in {source} (doc import, {time.strftime('%d.%m.%Y')})")
            out["removed_archived"] += 1
    out["links"] = _link(source, touched)
    with g.lock:
        g.db().commit()
    return out


def _index_exists(idx: str) -> bool:
    with g.lock:
        return g.db().execute("SELECT 1 FROM vi_index WHERE name = ?", (idx,)).fetchone() is not None


def _link(source: str, touched: list[tuple[str, g.MemoryObject]]) -> int:
    """Edges for page links of the same source: from each touched page to the pages it links, and to it from pages that link it."""
    if not touched:
        return 0
    n = 0
    first_of: dict[str, str] = {}

    def first(pid: str) -> str | None:
        if pid not in first_of:
            objs = [o for o in _doc_objects(source, pid) if o.data["doc_import"].get("part") == 1]
            first_of[pid] = objs[0].id if objs else ""
        return first_of[pid] or None
    for pid, o in touched:
        if o.data["doc_import"].get("part") != 1:
            continue
        for target in (o.data["doc_import"].get("links") or [])[:LINKS_MAX]:
            t = first(target)
            if t and t != o.id:
                o.link(t, "doc link")
                n += 1
        with g.lock:  # pages already held that link to this one
            rows = g.db().execute("SELECT id FROM object WHERE data LIKE ? AND data LIKE ? AND mode != 'archived' LIMIT ?",
                                  ('%"doc_import": {%', f'%"{pid}"%', LINKS_MAX)).fetchall()
        for (oid,) in rows:
            src = g.load(oid)
            if src and src.id != o.id and pid in (src.data.get("doc_import") or {}).get("links", []) \
                    and (src.data.get("doc_import") or {}).get("source") == source:
                src.link(o.id, "doc link")
                n += 1
    return n


# ------------------------------------------------------------------------------------------------ client side

def read_pages(path: Path) -> list[dict]:
    pages = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                p = json.loads(line)
                if not isinstance(p, dict) or not p.get("page_id") or not p.get("markdown"):
                    raise ValueError(f"{path}:{n}: every line needs page_id and markdown")
                pages.append(p)
    return pages


def run(pages: list[dict], source: str, call, index: str | None = None, knowledge_kind: str = "company-docs", label: str | None = None,
        prune: bool = False, dry_run: bool = False, pause: float = 0.0, old_source_kind: str | None = None,
        keep: set[str] | None = None) -> dict:
    """The client: state, then changed pages in batches, then (with prune) the pages the source no longer has."""
    held = call("vi_doc_sync", {"action": "state", "source": source})
    have = held.get("pages") or {}
    todo = [p for p in pages if have.get(str(p["page_id"])) != content_sha(str(p["markdown"]).strip())]
    gone = sorted(set(have) - {str(p["page_id"]) for p in pages} - set(keep or ())) if prune else []
    report = {"pages": len(pages), "held_before": len(have), "to_send": len(todo), "to_remove": len(gone), "batches": 0, "totals": {}}
    if dry_run:
        return report
    batch, chars = [], 0

    def send(b, removed=()):
        r = call("vi_doc_sync", {"action": "sync", "source": source, "index": index, "knowledge_kind": knowledge_kind, "label": label,
                                 "pages": b, "removed": list(removed), **({"old_source_kind": old_source_kind} if old_source_kind else {})})
        report["batches"] += 1
        for k, v in r.items():
            if isinstance(v, int):
                report["totals"][k] = report["totals"].get(k, 0) + v
            elif isinstance(v, list) and v:
                report["totals"].setdefault(k, []).extend(v)
        if pause:
            time.sleep(pause)
    for p in todo:
        size = len(str(p["markdown"]))
        if batch and (len(batch) >= PAGES_MAX or chars + size > BATCH_CHARS_MAX):
            send(batch)
            batch, chars = [], 0
        batch.append(p)
        chars += size
    if batch:
        send(batch)
    for i in range(0, len(gone), 500):
        send([], gone[i:i + 500])
    return report


def main(argv: list[str]) -> int:
    """vi-mcp docs import PATH… --source NAME [--index X] [--kind company-docs|external-docs|manual] [--label TEXT] [--prune]
                         [--old-source-kind KIND] [--url URL --token-file F] [--pause S] [--dry-run]
    vi-mcp docs convert PATH… [--out pages.jsonl]      (local, no server: what the import would send, and what it refuses)
    vi-mcp docs formats                                (every supported format and what it needs here: pypdf, LibreOffice)
    vi-mcp docs state --source NAME [--url URL --token-file F]
    PATH: a FILE.jsonl (one page per line: {"page_id", "title", "markdown", "url", "version", "space", "area", "labels", "service",
    "links", "tags"}) or documents and directories (0.70.0: PDF, DOCX, ODT, XLSX, ODS, PPTX, ODP, HTML, EPUB, EML, CSV, text; DOC, XLS,
    PPT, RTF with LibreOffice — doc_formats.py); page_id = the path relative to the directory.
    The token must belong to an instance created with `vi-mcp instance NAME --import`. Guide: docs/IMPORT.md."""
    import argparse
    import os
    import sys
    from . import code_import
    a = argparse.ArgumentParser(prog="vi-mcp docs", description="import documentation pages (docs/IMPORT.md)")
    a.add_argument("action", choices=["import", "state", "convert", "formats"])
    a.add_argument("paths", nargs="*", help="FILE.jsonl, or documents and directories (vi-mcp docs formats)")
    a.add_argument("--source")
    a.add_argument("--out", help="convert: write the pages as JSON Lines here (default: a summary only)")
    a.add_argument("--no-recursive", action="store_true", help="directories: only their own files, not subdirectories")
    a.add_argument("--index")
    a.add_argument("--kind", default="company-docs", choices=KNOWLEDGE_KINDS)
    a.add_argument("--label")
    a.add_argument("--prune", action="store_true")
    a.add_argument("--old-source-kind", help="the source_kind: value an older import used for these pages, if it differs from --source")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--pause", type=float, default=0.0)
    a.add_argument("--url", default=os.environ.get("VI_MCP_URL"), help="MCP URL of the server (default: VI_MCP_URL, else the local server)")
    a.add_argument("--token-file", default=os.environ.get("VI_MCP_TOKEN_FILE"), help="token of an instance with the import right")
    o = a.parse_args(argv)
    if o.action == "formats":
        from . import doc_formats
        print(doc_formats.formats_table())
        return 0
    if o.action in ("import", "convert") and not o.paths:
        a.error(f"{o.action} needs FILE.jsonl or documents/directories")
    if o.action == "convert":
        pages, refused = load(o.paths, not o.no_recursive)
        if o.out:
            Path(o.out).write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pages), encoding="utf-8")
        print(json.dumps(summary(pages, refused) | ({"written": o.out} if o.out else {}), ensure_ascii=False, indent=1))
        return 0 if pages or not refused else 1
    if not o.source:
        a.error(f"{o.action} needs --source")
    url = o.url
    if not url:
        from . import config
        url = f"http://127.0.0.1:{config.load().port}/mcp"
    token = Path(o.token_file).expanduser().read_text(encoding="utf-8").strip() if o.token_file else None
    client = code_import.Client(url, token)
    try:
        client.start()
    except (OSError, RuntimeError) as e:
        print(f"vi-mcp docs: {e}", file=sys.stderr)
        return 1

    def call(name, args):
        text = client.call(name, args)
        try:
            return json.loads(text)
        except ValueError:
            raise RuntimeError(text[:300]) from None
    if o.action == "state":
        s = call("vi_doc_sync", {"action": "state", "source": o.source})
        print(json.dumps({k: (len(v) if k == "pages" else v) for k, v in s.items()}, ensure_ascii=False))
        return 0
    pages, refused = load(o.paths, not o.no_recursive)
    if refused:
        print(f"vi-mcp docs: {len(refused)} file(s) not imported:", file=sys.stderr)
        for x in refused:
            print(f"  {x['kind']}: {x['file']} — {x['reason']}", file=sys.stderr)
    if o.prune and refused:
        # a refused file is not "removed at the source": its page must not be archived by --prune (nothing disappears silently)
        print("vi-mcp docs: --prune keeps the pages of refused files", file=sys.stderr)
    r = run(pages, o.source, call, o.index, o.kind, o.label, o.prune, o.dry_run, o.pause, o.old_source_kind,
            keep={_page_id_of(x["file"], o.paths) for x in refused})
    print(json.dumps(r | summary(pages, refused), ensure_ascii=False))
    return 0


def load(paths: list[str], recursive: bool = True) -> tuple[list[dict], list[dict]]:
    """FILE.jsonl as before; documents and directories through doc_formats (0.70.0)."""
    if len(paths) == 1 and paths[0].endswith(".jsonl"):
        return read_pages(Path(paths[0])), []
    from . import doc_formats
    return doc_formats.pages_from_paths([Path(p) for p in paths], recursive)


def _page_id_of(file: str, roots: list[str]) -> str:
    for r in roots:
        rp = Path(r)
        try:
            return Path(file).relative_to(rp).as_posix() if rp.is_dir() else Path(file).name
        except ValueError:
            continue
    return Path(file).name


def summary(pages: list[dict], refused: list[dict]) -> dict:
    """What a conversion produced: pages by format, refused files by class (with the reasons in "refused")."""
    by_fmt: dict[str, int] = {}
    for p in pages:
        for lab in p.get("labels") or []:
            if str(lab).startswith("format-"):
                by_fmt[lab[7:]] = by_fmt.get(lab[7:], 0) + 1
    by_kind: dict[str, int] = {}
    for x in refused:
        by_kind[x["kind"]] = by_kind.get(x["kind"], 0) + 1
    return {"converted": len(pages), "by_format": by_fmt, "refused": len(refused), "refused_by_class": by_kind,
            "refused_files": refused}
