"""Document formats for the documentation import (0.70.0): files → Markdown pages for `vi-mcp docs import`.

The user (18.11.2026): "Jetzt wird es Zeit, dass wir alle gängigen Datenformate unterstützen: PDF, doc, docx, ods, odt, etc." Until now
the import took only JSON-Lines pages that already were Markdown; every other format had to be converted by whoever ran the import.

One registry, one path (identity): FORMATS maps a file extension to its converter; the CLI turns every file into the same page dict a
JSON-Lines line carries (page_id, title, markdown, labels), so the server side (doc_import.server_sync: chunking, triggers, archive of
the old shape) is unchanged. Every file ends in exactly one class (completeness) — converted, or refused with its reason:
  unknown format · needs pypdf · needs LibreOffice · encrypted · no text (a scanned PDF without a text layer, an empty document) ·
  too large / unsafe archive · unreadable (the parser's error class)
and the report counts each class; nothing is skipped silently. A limit that cuts a table names the cut rows in the page itself.

How each family is read:
- Office Open XML (docx, xlsx, pptx) and OpenDocument (odt, ods, odp) are ZIP archives of XML: read with the standard library
  (zipfile + ElementTree — ElementTree resolves no external entities). Headings become #, lists -, tables Markdown tables, links
  [text](url); spreadsheets one table per sheet, presentations one section per slide (with speaker notes).
- PDF: pypdf (BSD; Debian/Ubuntu python3-pypdf, Fedora python3-pypdf, Arch python-pypdf), text per page under "## Page N".
- HTML, EPUB (XHTML in a ZIP), EML (e-mail, attachments named, not imported), CSV/TSV, plain text and Markdown: standard library.
- Legacy binary formats (doc, xls, ppt, rtf, …): converted by LibreOffice (`soffice --convert-to`) when it is installed, then read as
  above; without it they are refused with the package to install.
Images are not text: `vi-mcp image` stores them with a description.
"""
from __future__ import annotations

import csv
import email
import email.policy
import hashlib
import html
import io
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

#: a single file larger than this is refused (bytes)
FILE_MAX = 100 * 2**20
#: a ZIP-based document may unpack to at most this many bytes in total and hold at most this many members (zip-bomb guard)
UNZIP_MAX = 300 * 2**20
MEMBERS_MAX = 20_000
#: rows per table and cells per row that become Markdown; more is cut and named in the page
ROWS_MAX = 5_000
COLS_MAX = 200
#: a PDF whose text has fewer characters per page than this has no usable text layer (scanned) and is refused
PDF_MIN_CHARS_PER_PAGE = 20
LIBREOFFICE_TIMEOUT_S = 180


class Refused(Exception):
    """A file that is not imported, with the class and the reason (shown in the report)."""

    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


@dataclass
class Document:
    markdown: str
    title: str = ""
    fmt: str = ""
    notes: list[str] = field(default_factory=list)  # what was cut or left out, also written into the page


# ───────────────────────────────────────────────────────────────────────────────────────── helpers

def _md_escape_cell(s: str) -> str:
    return " ".join(str(s).split()).replace("|", "\\|")


def md_table(rows: list[list[str]], notes: list[str] | None = None, what: str = "table") -> str:
    """Rows as a Markdown table, first row as header; empty trailing columns dropped; cut at ROWS_MAX / COLS_MAX (named)."""
    rows = [[_md_escape_cell(c) for c in r] for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    while width and all(len(r) < width or not r[width - 1] for r in rows):
        width -= 1
    cut_cols = width > COLS_MAX
    width = min(width, COLS_MAX)
    cut_rows = len(rows) - ROWS_MAX if len(rows) > ROWS_MAX else 0
    rows = rows[:ROWS_MAX]
    rows = [(r + [""] * width)[:width] for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    if cut_rows or cut_cols:
        msg = f"({what}: " + ", ".join(x for x in (f"{cut_rows} more rows not imported" if cut_rows else "",
                                                     f"columns after {COLS_MAX} not imported" if cut_cols else "") if x) + ")"
        out.append("")
        out.append(msg)
        if notes is not None:
            notes.append(msg)
    return "\n".join(out)


def _safe_zip(data: bytes) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise Refused("unreadable", f"not a valid ZIP-based document ({e})") from None
    infos = z.infolist()
    if len(infos) > MEMBERS_MAX:
        raise Refused("too large", f"archive has {len(infos)} members (limit {MEMBERS_MAX})")
    total = sum(i.file_size for i in infos)
    if total > UNZIP_MAX:
        raise Refused("too large", f"archive unpacks to {total // 2**20} MiB (limit {UNZIP_MAX // 2**20} MiB)")
    if any(i.flag_bits & 0x1 for i in infos):
        raise Refused("encrypted", "the document is password-protected")
    return z


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        raw = z.read(name)
    except KeyError:
        return None
    try:
        return ET.fromstring(raw)
    except ET.ParseError as e:
        raise Refused("unreadable", f"{name}: XML error ({e})") from None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean(md: str) -> str:
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


# ───────────────────────────────────────────────────────────────────────────────────────── Office Open XML

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
SS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DC = "{http://purl.org/dc/elements/1.1/}"


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Relationship id → target (absolute part name, or the URL for external targets) of a part."""
    d, f = posixpath.split(part)
    root = _xml(z, posixpath.join(d, "_rels", f + ".rels"))
    out = {}
    if root is None:
        return out
    for r in root.iter(f"{PKG_REL}Relationship"):
        t = r.get("Target", "")
        out[r.get("Id", "")] = t if r.get("TargetMode") == "External" else posixpath.normpath(posixpath.join(d, t)).lstrip("/")
    return out


def _core_title(z: zipfile.ZipFile) -> str:
    root = _xml(z, "docProps/core.xml")
    t = root.find(f"{DC}title") if root is not None else None
    return (t.text or "").strip() if t is not None else ""


HEADING_NAMES = re.compile(r"^(heading|überschrift|berschrift|titre|título|titolo|kop)\s*(\d)$", re.I)


def _docx_styles(z: zipfile.ZipFile) -> dict[str, int]:
    """style id → heading level (from the style's name "Heading N" / "Überschrift N" / title, or its outline level)."""
    out: dict[str, int] = {}
    root = _xml(z, "word/styles.xml")
    if root is None:
        return out
    for s in root.iter(f"{W}style"):
        sid = s.get(f"{W}styleId", "")
        name_el = s.find(f"{W}name")
        name = (name_el.get(f"{W}val") if name_el is not None else "") or sid
        m = HEADING_NAMES.match(name.replace(" ", "")) or HEADING_NAMES.match(name)
        lvl = None
        if m:
            lvl = int(m.group(2))
        elif name.lower() in ("title", "titel"):
            lvl = 1
        else:
            ol = s.find(f"{W}pPr/{W}outlineLvl")
            if ol is not None and (ol.get(f"{W}val") or "").isdigit() and int(ol.get(f"{W}val")) < 9:
                lvl = int(ol.get(f"{W}val")) + 1
        if lvl:
            out[sid] = min(lvl, 6)
    return out


def _docx_text(el: ET.Element, rels: dict[str, str]) -> str:
    parts = []
    for node in el:
        tag = _local(node.tag)
        if tag == "r":
            for c in node:
                ct = _local(c.tag)
                if ct == "t":
                    parts.append(c.text or "")
                elif ct == "tab":
                    parts.append("\t")
                elif ct in ("br", "cr"):
                    parts.append("\n")
        elif tag == "hyperlink":
            inner = _docx_text(node, rels)
            url = rels.get(node.get(f"{R}id", ""), "")
            parts.append(f"[{inner}]({url})" if url.startswith(("http://", "https://", "mailto:")) and inner.strip() else inner)
        elif tag in ("ins", "smartTag", "sdt", "sdtContent", "fldSimple"):
            parts.append(_docx_text(node, rels))
    return "".join(parts)


def _docx_block(el: ET.Element, styles: dict[str, int], rels: dict[str, str], notes: list[str]) -> list[str]:
    out = []
    for node in el:
        tag = _local(node.tag)
        if tag == "p":
            text = _docx_text(node, rels).strip()
            if not text:
                continue
            ppr = node.find(f"{W}pPr")
            lvl = None
            if ppr is not None:
                st = ppr.find(f"{W}pStyle")
                if st is not None:
                    lvl = styles.get(st.get(f"{W}val", ""))
                ol = ppr.find(f"{W}outlineLvl")
                if lvl is None and ol is not None and (ol.get(f"{W}val") or "").isdigit() and int(ol.get(f"{W}val")) < 9:
                    lvl = min(int(ol.get(f"{W}val")) + 1, 6)
                if lvl is None and ppr.find(f"{W}numPr") is not None:
                    ilvl = ppr.find(f"{W}numPr/{W}ilvl")
                    depth = int(ilvl.get(f"{W}val", "0")) if ilvl is not None and (ilvl.get(f"{W}val") or "0").isdigit() else 0
                    out.append("  " * depth + "- " + text)
                    continue
            if out and out[-1].lstrip().startswith("- "):
                out.append("")  # a list ends before the next block
            out.append(("#" * lvl + " " + text) if lvl else text)
            out.append("")
        elif tag == "tbl":
            rows = []
            for tr in node.iter(f"{W}tr"):
                rows.append([" ".join(_docx_text(p, rels).strip() for p in tc.iter(f"{W}p")).strip() for tc in tr.findall(f"{W}tc")])
            t = md_table(rows, notes)
            if t:
                out += ["", t, ""]  # a table never continues a list item or paragraph
        elif tag in ("sdt", "sdtContent", "customXml"):
            out += _docx_block(node, styles, rels, notes)
    return out


def docx(data: bytes) -> Document:
    z = _safe_zip(data)
    root = _xml(z, "word/document.xml")
    if root is None:
        raise Refused("unreadable", "word/document.xml missing")
    body = root.find(f"{W}body")
    notes: list[str] = []
    lines = _docx_block(body if body is not None else root, _docx_styles(z), _rels(z, "word/document.xml"), notes)
    return Document(_clean("\n".join(lines)), _core_title(z), "docx", notes)


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]*", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return max(n - 1, 0)


def xlsx(data: bytes) -> Document:
    z = _safe_zip(data)
    shared = []
    sroot = _xml(z, "xl/sharedStrings.xml")
    if sroot is not None:
        for si in sroot.findall(f"{SS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{SS}t")))
    wb = _xml(z, "xl/workbook.xml")
    if wb is None:
        raise Refused("unreadable", "xl/workbook.xml missing")
    rels = _rels(z, "xl/workbook.xml")
    notes: list[str] = []
    out = []
    for sh in wb.iter(f"{SS}sheet"):
        name = sh.get("name", "")
        if sh.get("state") in ("hidden", "veryHidden"):
            notes.append(f"(hidden sheet {name} not imported)")
            continue
        part = rels.get(sh.get(f"{R}id", ""), "")
        root = _xml(z, part)
        if root is None:
            continue
        rows: list[list[str]] = []
        for row in root.iter(f"{SS}row"):
            cells: dict[int, str] = {}
            for c in row.findall(f"{SS}c"):
                t, v = c.get("t"), c.find(f"{SS}v")
                if t == "s" and v is not None and (v.text or "").isdigit():
                    val = shared[int(v.text)] if int(v.text) < len(shared) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{SS}t"))
                elif t == "b" and v is not None:
                    val = "TRUE" if v.text == "1" else "FALSE"
                else:
                    val = (v.text or "") if v is not None else ""
                cells[_col_index(c.get("r", "A"))] = val
            if cells:
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
            if len(rows) > ROWS_MAX + 1:
                break
        t = md_table(rows, notes, f"sheet {name}")
        out += [f"## {name}", "", t or "(empty sheet)", ""]
    return Document(_clean("\n".join(out)), _core_title(z), "xlsx", notes)


def _a_paras(el: ET.Element) -> list[str]:
    paras = []
    for p in el.iter(f"{A}p"):
        text = "".join((t.text or "") if _local(t.tag) == "t" else "\n" for t in p.iter() if _local(t.tag) in ("t", "br")).strip()
        if text:
            paras.append(text)
    return paras


def pptx(data: bytes) -> Document:
    z = _safe_zip(data)
    pres = _xml(z, "ppt/presentation.xml")
    if pres is None:
        raise Refused("unreadable", "ppt/presentation.xml missing")
    rels = _rels(z, "ppt/presentation.xml")
    notes: list[str] = []
    out = []
    for n, sid in enumerate(pres.iter(f"{P}sldId"), 1):
        part = rels.get(sid.get(f"{R}id", ""), "")
        root = _xml(z, part)
        if root is None:
            continue
        title, body = "", []
        for sp in root.iter(f"{P}sp"):
            ph = sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
            paras = _a_paras(sp)
            if ph is not None and ph.get("type") in ("title", "ctrTitle") and not title:
                title = " ".join(paras)
            else:
                body += paras
        out.append(f"## Slide {n}" + (f": {title}" if title else ""))
        out.append("")
        out += [f"- {b}" for b in body]
        for tbl in root.iter(f"{A}tbl"):
            rows = [[" ".join(_a_paras(tc)) for tc in tr.findall(f"{A}tc")] for tr in tbl.findall(f"{A}tr")]
            t = md_table(rows, notes, f"table on slide {n}")
            if t:
                out += ["", t]
        srels = _rels(z, part)
        for target in srels.values():
            if "notesSlide" in target:
                nroot = _xml(z, target)
                if nroot is not None:
                    ntext = [x for sp in nroot.iter(f"{P}sp") for x in _a_paras(sp)
                             if not (sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph") is not None
                                     and sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph").get("type") in ("sldImg", "sldNum"))]
                    if ntext:
                        out += ["", "Notes: " + " ".join(ntext)]
        out.append("")
    return Document(_clean("\n".join(out)), _core_title(z), "pptx", notes)


# ───────────────────────────────────────────────────────────────────────────────────────── OpenDocument

TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
DRAW = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
XLINK = "{http://www.w3.org/1999/xlink}"
PRES = "{urn:oasis:names:tc:opendocument:xmlns:presentation:1.0}"
REPEAT_MAX = 1_000  # number-columns/rows-repeated of an empty cell can be 16,384 — never expanded beyond this


def _odf_text(el: ET.Element) -> str:
    parts = [el.text or ""]
    for c in el:
        tag = _local(c.tag)
        if tag == "s":
            parts.append(" " * min(int(c.get(f"{TEXT}c", "1") or 1), 100))
        elif tag == "tab":
            parts.append("\t")
        elif tag == "line-break":
            parts.append("\n")
        elif tag == "a":
            inner = _odf_text(c)
            url = c.get(f"{XLINK}href", "")
            parts.append(f"[{inner}]({url})" if url.startswith(("http://", "https://", "mailto:")) and inner.strip() else inner)
        elif tag in ("note", "annotation"):
            pass  # footnotes/comments: not part of the running text
        else:
            parts.append(_odf_text(c))
        parts.append(c.tail or "")
    return "".join(parts)


def _odf_table(tbl: ET.Element, notes: list[str], what: str) -> str:
    rows = []
    for tr in tbl.iter(f"{TABLE}table-row"):
        rep_rows = min(int(tr.get(f"{TABLE}number-rows-repeated", "1") or 1), REPEAT_MAX)
        row = []
        for tc in tr:
            if _local(tc.tag) not in ("table-cell", "covered-table-cell"):
                continue
            text = " ".join(_odf_text(p).strip() for p in tc if _local(p.tag) in ("p", "h"))
            rep = int(tc.get(f"{TABLE}number-columns-repeated", "1") or 1)
            row += [text] * (min(rep, REPEAT_MAX) if text else min(rep, COLS_MAX + 1))
        if any(c.strip() for c in row):
            rows += [row] * (rep_rows if rep_rows <= 10 else 1)
        if len(rows) > ROWS_MAX + 1:
            break
    return md_table(rows, notes, what)


def _odf_blocks(el: ET.Element, notes: list[str], depth: int = 0) -> list[str]:
    out = []
    for c in el:
        tag = _local(c.tag)
        if tag == "h":
            lvl = int(c.get(f"{TEXT}outline-level", "1") or 1)
            text = _odf_text(c).strip()
            if text:
                out += ["#" * min(max(lvl, 1), 6) + " " + text, ""]
        elif tag == "p":
            text = _odf_text(c).strip()
            if text:
                out += [text, ""]
        elif tag == "list":
            for item in c:
                if _local(item.tag) in ("list-item", "list-header"):
                    for sub in item:
                        st = _local(sub.tag)
                        if st in ("p", "h"):
                            text = _odf_text(sub).strip()
                            if text:
                                out.append("  " * depth + "- " + text)
                        elif st == "list":
                            out += _odf_blocks(_wrap(sub), notes, depth + 1)
            out.append("")
        elif tag == "table":
            t = _odf_table(c, notes, f"table {c.get(f'{TABLE}name', '')}".strip())
            if t:
                out += [t, ""]
        elif tag in ("section", "frame", "text-box", "g", "custom-shape", "index-body", "illustration-index", "table-of-content",
                     "alphabetical-index", "user-index"):
            out += _odf_blocks(c, notes, depth)
    return out


def _wrap(el: ET.Element) -> ET.Element:
    w = ET.Element("wrap")
    w.append(el)
    return w


def _odf_title(z: zipfile.ZipFile) -> str:
    root = _xml(z, "meta.xml")
    t = root.find(f".//{DC}title") if root is not None else None
    return (t.text or "").strip() if t is not None else ""


def odf(data: bytes) -> Document:
    z = _safe_zip(data)
    root = _xml(z, "content.xml")
    if root is None:
        raise Refused("unreadable", "content.xml missing (not an OpenDocument file)")
    body = root.find(f"{OFFICE}body")
    if body is None:
        raise Refused("unreadable", "office:body missing")
    notes: list[str] = []
    out = []
    kind = ""
    for part in body:
        kind = _local(part.tag)
        if kind == "spreadsheet":
            for tbl in part.findall(f"{TABLE}table"):
                name = tbl.get(f"{TABLE}name", "")
                t = _odf_table(tbl, notes, f"sheet {name}")
                out += [f"## {name}", "", t or "(empty sheet)", ""]
        elif kind == "presentation":
            for n, page in enumerate(part.findall(f"{DRAW}page"), 1):
                title, body_lines = "", []
                for frame in page.iter(f"{DRAW}frame"):
                    cls = frame.get(f"{PRES}class", "")
                    lines = [x for x in _odf_blocks(frame, notes) if x.strip()]
                    if cls == "title" and not title:
                        title = " ".join(lines)
                    elif cls not in ("page-number", "date-time", "footer", "header"):
                        body_lines += [x if x.lstrip().startswith(("- ", "|", "#")) else "- " + x for x in lines]
                out += [f"## Slide {n}" + (f": {title}" if title else ""), ""] + body_lines
                for nt in page.iter(f"{PRES}notes"):
                    ntext = " ".join(x for x in _odf_blocks(nt, notes) if x.strip())
                    if ntext:
                        out += ["", "Notes: " + ntext]
                out.append("")
        else:  # text (odt, ott, also odm/oth)
            out += _odf_blocks(part, notes)
    fmt = {"spreadsheet": "ods", "presentation": "odp"}.get(kind, "odt")
    return Document(_clean("\n".join(out)), _odf_title(z), fmt, notes)


# ───────────────────────────────────────────────────────────────────────────────────────── HTML, EPUB, e-mail, text

LINK_OPEN, LINK_CLOSE = "\x01", "\x02"


class _HtmlToMd(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False
        self.href: list[str] = []
        self.list_depth = 0
        self.pre = 0
        self.table: list[list[str]] | None = None
        self.cell: list[str] | None = None
        self.notes: list[str] = []

    def _emit(self, s: str):
        if self.cell is not None:
            self.cell.append(s)
        else:
            self.out.append(s)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag == "title":
            self._in_title = True
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._emit("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("p", "div", "section", "article", "blockquote"):
            self._emit("\n\n")
        elif tag == "br":
            self._emit("\n")
        elif tag in ("ul", "ol"):
            self.list_depth += 1
            self._emit("\n")
        elif tag == "li":
            self._emit("\n" + "  " * max(self.list_depth - 1, 0) + "- ")
        elif tag == "a":
            self.href.append(a.get("href") or "")
            self._emit(LINK_OPEN)
        elif tag == "pre":
            self.pre += 1
            self._emit("\n\n```\n")
        elif tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.table.append([])
        elif tag in ("td", "th") and self.table is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(self.skip - 1, 0)
            return
        if tag == "title":
            self._in_title = False
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag) or tag in ("p", "div", "section", "article", "blockquote"):
            self._emit("\n\n")
        elif tag in ("ul", "ol"):
            self.list_depth = max(self.list_depth - 1, 0)
            self._emit("\n")
        elif tag == "a" and self.href:
            url = self.href.pop()
            self._emit(LINK_CLOSE + (f"({url})" if url.startswith(("http://", "https://", "mailto:")) else ""))
        elif tag == "pre":
            self.pre = max(self.pre - 1, 0)
            self._emit("\n```\n\n")
        elif tag in ("td", "th") and self.cell is not None and self.table is not None:
            if self.table:
                self.table[-1].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "table" and self.table is not None:
            t = md_table(self.table, self.notes)
            self.table, self.cell = None, None
            self.out.append("\n\n" + t + "\n\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self.skip:
            return
        self._emit(data if self.pre else re.sub(r"\s+", " ", data))

    def markdown(self) -> str:
        md = "".join(self.out)
        # a link with a usable URL and some text becomes [text](url); one without either keeps only its text — brackets that were
        # in the text itself ("[1]") are left alone, the link markers are private characters
        md = re.sub(LINK_OPEN + r"([^" + LINK_CLOSE + r"]*)" + LINK_CLOSE + r"(\([^)\s]*\))?",
                    lambda m: f"[{m.group(1).strip()}]{m.group(2)}" if m.group(2) and m.group(1).strip() else m.group(1), md)
        return _clean(md.replace(LINK_OPEN, "").replace(LINK_CLOSE, ""))


def html_doc(data: bytes, fmt: str = "html") -> Document:
    text = _decode(data)
    p = _HtmlToMd()
    p.feed(text)
    p.close()
    return Document(p.markdown(), " ".join(p.title.split()), fmt, p.notes)


def epub(data: bytes) -> Document:
    z = _safe_zip(data)
    cont = _xml(z, "META-INF/container.xml")
    if cont is None:
        raise Refused("unreadable", "META-INF/container.xml missing (not an EPUB)")
    rf = next((e.get("full-path") for e in cont.iter() if _local(e.tag) == "rootfile"), None)
    opf = _xml(z, rf or "")
    if opf is None:
        raise Refused("unreadable", "package document (OPF) missing")
    base = posixpath.dirname(rf)
    manifest = {i.get("id"): posixpath.normpath(posixpath.join(base, i.get("href", ""))) for i in opf.iter() if _local(i.tag) == "item"}
    title = next(((e.text or "").strip() for e in opf.iter() if _local(e.tag) == "title"), "")
    parts, notes = [], []
    for ref in (e for e in opf.iter() if _local(e.tag) == "itemref"):
        name = manifest.get(ref.get("idref"))
        if not name:
            continue
        try:
            d = html_doc(z.read(name))
        except KeyError:
            notes.append(f"(chapter {name} missing in the archive)")
            continue
        parts.append(d.markdown)
        notes += d.notes
    return Document(_clean("\n\n".join(parts)), title, "epub", notes)


def eml(data: bytes) -> Document:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    head = [f"**{k}:** {msg[k]}" for k in ("From", "To", "Cc", "Date") if msg[k]]
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        content = body.get_content()
        text = html_doc(content.encode("utf-8")).markdown if body.get_content_type() == "text/html" else str(content)
    attachments = [a.get_filename() or a.get_content_type() for a in msg.iter_attachments()]
    notes = [f"(attachment not imported: {a})" for a in attachments]
    md = "\n\n".join(x for x in ["\n".join(head), _clean(text), "\n".join(notes)] if x)
    return Document(md, str(msg["Subject"] or ""), "eml", notes)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("cp1252", errors="replace")


def plain(data: bytes, fmt: str = "txt") -> Document:
    return Document(_clean(_decode(data)), "", fmt)


def delimited(data: bytes, fmt: str = "csv") -> Document:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:20_000], delimiters=",;\t|") if fmt == "csv" else csv.excel_tab
    except csv.Error:
        dialect = csv.excel
    notes: list[str] = []
    rows = list(csv.reader(io.StringIO(text), dialect))[: ROWS_MAX + 2]
    return Document(md_table(rows, notes), "", fmt, notes)


# ───────────────────────────────────────────────────────────────────────────────────────── PDF

def pdf(data: bytes) -> Document:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise Refused("needs pypdf", "PDF needs pypdf — Debian/Ubuntu: apt install python3-pypdf · Fedora: dnf install python3-pypdf · "
                      "Arch: pacman -S python-pypdf · elsewhere: pip install pypdf") from None
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:  # noqa: BLE001
                ok = 0
            if not ok:
                raise Refused("encrypted", "the PDF is password-protected")
        pages = []
        for i, page in enumerate(reader.pages, 1):
            pages.append((i, (page.extract_text() or "").strip()))
    except Refused:
        raise
    except Exception as e:  # noqa: BLE001 — a broken PDF is a named refusal, never a crash of the whole import
        raise Refused("unreadable", f"PDF: {type(e).__name__}: {str(e)[:120]}") from None
    chars = sum(len(t) for _i, t in pages)
    if not pages or chars < PDF_MIN_CHARS_PER_PAGE * len(pages):
        raise Refused("no text", f"no text layer ({chars} characters on {len(pages)} pages) — a scanned PDF needs OCR first")
    title = ""
    try:
        title = str((reader.metadata or {}).get("/Title") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    md = "\n\n".join(f"## Page {i}\n\n{t}" for i, t in pages if t)
    empty = [str(i) for i, t in pages if not t]
    notes = [f"(pages without text: {', '.join(empty)})"] if empty else []
    return Document(_clean(md + ("\n\n" + notes[0] if notes else "")), title, "pdf", notes)


# ───────────────────────────────────────────────────────────────────────────────────────── legacy formats via LibreOffice

def libreoffice() -> str | None:
    for name in ("soffice", "libreoffice", "lowriter"):
        p = shutil.which(name)
        if p:
            return p
    for p in ("/Applications/LibreOffice.app/Contents/MacOS/soffice", r"C:\Program Files\LibreOffice\program\soffice.exe"):
        if os.path.exists(p):
            return p
    return None


def via_libreoffice(data: bytes, ext: str, target: str) -> bytes:
    exe = libreoffice()
    if not exe:
        raise Refused("needs LibreOffice", f".{ext} needs LibreOffice to convert — Debian/Ubuntu: apt install libreoffice-core-nogui "
                      "(plus -writer/-calc/-impress-nogui) · Fedora: dnf install libreoffice-core · Arch: pacman -S libreoffice-fresh")
    with tempfile.TemporaryDirectory(prefix="vi-mcp-lo-") as d:
        src = Path(d) / f"in.{ext}"
        src.write_bytes(data)
        try:
            r = subprocess.run([exe, f"-env:UserInstallation=file://{Path(d).as_posix()}/profile", "--headless", "--convert-to", target,
                                "--outdir", d, str(src)], capture_output=True, timeout=LIBREOFFICE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise Refused("unreadable", f"LibreOffice did not finish within {LIBREOFFICE_TIMEOUT_S} s") from None
        out = Path(d) / f"in.{target}"
        if r.returncode != 0 or not out.exists():
            raise Refused("unreadable", f"LibreOffice could not convert .{ext} (exit {r.returncode}): "
                          f"{(r.stderr or r.stdout).decode(errors='replace').strip()[:160]}")
        return out.read_bytes()


def _legacy(target: str, reader):
    def conv(data: bytes, ext: str) -> Document:
        doc = reader(via_libreoffice(data, ext, target))
        doc.fmt = ext
        doc.notes.append(f"(converted from .{ext} by LibreOffice)")
        return doc
    return conv


# ───────────────────────────────────────────────────────────────────────────────────────── registry

#: extension → (converter(data, ext) → Document, family). One place for every format (identity).
FORMATS: dict[str, tuple] = {}
for _ext in ("docx", "docm", "dotx", "dotm"):
    FORMATS[_ext] = (lambda d, e: docx(d), "Office Open XML")
for _ext in ("xlsx", "xlsm", "xltx", "xltm"):
    FORMATS[_ext] = (lambda d, e: xlsx(d), "Office Open XML")
for _ext in ("pptx", "pptm", "potx", "ppsx"):
    FORMATS[_ext] = (lambda d, e: pptx(d), "Office Open XML")
for _ext in ("odt", "ott", "ods", "ots", "odp", "otp", "odm"):
    FORMATS[_ext] = (lambda d, e: odf(d), "OpenDocument")
FORMATS["pdf"] = (lambda d, e: pdf(d), "PDF")
for _ext in ("html", "htm", "xhtml"):
    FORMATS[_ext] = (lambda d, e: html_doc(d, e), "web")
FORMATS["epub"] = (lambda d, e: epub(d), "web")
FORMATS["eml"] = (lambda d, e: eml(d), "e-mail")
for _ext in ("txt", "text", "md", "markdown", "rst", "adoc", "log"):
    FORMATS[_ext] = (lambda d, e: plain(d, e), "text")
FORMATS["csv"] = (lambda d, e: delimited(d, "csv"), "text")
FORMATS["tsv"] = (lambda d, e: delimited(d, "tsv"), "text")
for _ext in ("doc", "dot", "rtf", "wpd", "wps", "sxw", "pages"):
    FORMATS[_ext] = (_legacy("docx", docx), "legacy (LibreOffice)")
for _ext in ("xls", "xlt", "sxc", "numbers"):
    FORMATS[_ext] = (_legacy("xlsx", xlsx), "legacy (LibreOffice)")
for _ext in ("ppt", "pot", "pps", "sxi", "key"):
    FORMATS[_ext] = (_legacy("pptx", pptx), "legacy (LibreOffice)")
#: never text: named, so the report says why (images go through `vi-mcp image`)
NOT_TEXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff", "svg", "mp3", "mp4", "wav", "mov", "zip", "gz", "7z", "exe"}


def convert(data: bytes, name: str) -> Document:
    """One file → one Document, or Refused with its class and reason."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if len(data) > FILE_MAX:
        raise Refused("too large", f"{len(data) // 2**20} MiB (limit {FILE_MAX // 2**20} MiB)")
    if ext in NOT_TEXT:
        raise Refused("unknown format", f".{ext} is no text document" + (" — images: vi-mcp image FILE" if ext in
                      ("png", "jpg", "jpeg", "gif", "webp") else ""))
    if ext not in FORMATS:
        raise Refused("unknown format", f".{ext or '(none)'} is not a supported format ({len(FORMATS)} are: vi-mcp docs formats)")
    fn, _family = FORMATS[ext]
    try:
        doc = fn(data, ext)
    except Refused:
        raise
    except (ET.ParseError, zipfile.BadZipFile, KeyError, ValueError, IndexError, UnicodeError, OSError) as e:
        raise Refused("unreadable", f"{type(e).__name__}: {str(e)[:160]}") from None
    if not doc.markdown.strip() or not re.search(r"\w", doc.markdown):
        raise Refused("no text", "the document has no text")
    doc.fmt = doc.fmt or ext
    return doc


def pages_from_paths(paths: list[Path], recursive: bool = True) -> tuple[list[dict], list[dict]]:
    """Files and directories → (pages for doc_import.run, refused [{file, kind, reason}]). page_id = the path relative to the given
    directory (a single file: its name), so a re-import of the same tree updates the same pages and --prune finds removed ones."""
    pages, refused = [], []
    for root in paths:
        root = Path(root)
        files = sorted(p for p in (root.rglob("*") if recursive else root.glob("*")) if p.is_file()) if root.is_dir() else [root]
        for f in files:
            if f.name.startswith(("~$", ".~lock")):
                continue  # office lock files
            rel = f.relative_to(root).as_posix() if root.is_dir() else f.name
            try:
                data = f.read_bytes()
                doc = convert(data, f.name)
            except Refused as e:
                refused.append({"file": str(f), "kind": e.kind, "reason": e.reason})
                continue
            except OSError as e:
                refused.append({"file": str(f), "kind": "unreadable", "reason": f"{type(e).__name__}: {e}"})
                continue
            title = doc.title or f.stem.replace("_", " ")
            md = doc.markdown if doc.markdown.lstrip().startswith("# ") else f"# {title}\n\n{doc.markdown}"
            pages.append({"page_id": rel, "title": title, "markdown": md, "labels": [f"format-{doc.fmt}"],
                          "version": hashlib.sha256(data).hexdigest()[:16], "area": str(Path(rel).parent) if "/" in rel else ""})
    return pages, refused


def formats_table() -> str:
    """For `vi-mcp docs formats`: every extension with its family and what it needs."""
    lo = libreoffice()
    try:
        import pypdf  # noqa: F401
        pdf_ok = True
    except ImportError:
        pdf_ok = False
    fam: dict[str, list[str]] = {}
    for ext, (_fn, family) in FORMATS.items():
        fam.setdefault(family, []).append(ext)
    lines = []
    for family, exts in fam.items():
        state = ("available" if pdf_ok else "needs pypdf") if family == "PDF" else \
            ("available (LibreOffice found)" if lo else "needs LibreOffice") if family.startswith("legacy") else "available"
        lines.append(f"{family:22} {state:30} {', '.join(sorted(exts))}")
    lines.append(f"{'not text':22} {'refused, named':30} {', '.join(sorted(NOT_TEXT))}")
    return "\n".join(lines)
