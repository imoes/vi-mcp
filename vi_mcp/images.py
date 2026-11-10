"""0.35.0: images in memory — an image with its description and its regions in the format of SAM 3 (Meta, Segment Anything with Concepts).

An image is a memory of its own kind (bild, since 0.37.0; 0.35.x: erkenntnis with medium:bild): `text` is the key statement, `content` the complete description, and the
regions say what is where — per region a concept (the noun phrase SAM 3 was prompted with, e.g. "red plug"), a box in absolute pixel
coordinates xyxy, a score 0–1 and optionally the mask as COCO run-length encoding ({"size": [h, w], "counts": ...}). That is the
output of SAM 3 per matching instance (masks, boxes, scores; arXiv 2511.16719, github.com/facebookresearch/sam3). The VI does not
segment or describe anything itself: the client delivers, the VI stores, finds and returns.

Storage: table `bild`, content-addressed by SHA-256 (the same image twice is stored once). The object carries only the reference
`data.bild` = {sha, mime, breite, hoehe, bytes} and `data.regionen`. The type is taken from the bytes (magic numbers), never from the
client's word; width and height from the header. Images stay on this server: never onto the network (p2p names the reason).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import struct

from . import memory as g

#: per image (raw bytes). Base64 in a JSON-RPC body of at most 8 MiB (server.MAX_BODY) carries about 6 MiB; 5 MiB is also the
#: largest image the Claude API accepts, so every stored image can be shown back to a model.
IMAGE_MAX = 5 * 1024 * 1024
#: all images together (raw bytes): the database is backed up as a whole, an unbounded image store would make every backup grow
TOTAL_MAX = 2 * 1024 ** 3
REGIONS_MAX = 200
CONCEPT_MAX = 80
MASK_MAX = 200_000  # characters of a COCO RLE string (or numbers of a counts list)
MIME = ("image/png", "image/jpeg", "image/gif", "image/webp")


def _table() -> None:
    with g.lock:
        g.db().execute("CREATE TABLE IF NOT EXISTS bild (sha TEXT PRIMARY KEY, mime TEXT NOT NULL, breite INTEGER NOT NULL, "
                       "hoehe INTEGER NOT NULL, bytes INTEGER NOT NULL, zeit TEXT NOT NULL, roh BLOB NOT NULL)")
        g.db().commit()


def sniff(raw: bytes) -> tuple[str, int, int]:
    """(mime, width, height) from the bytes; ValueError naming why it is not a supported image."""
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
        w, h = struct.unpack(">II", raw[16:24])
        return "image/png", w, h
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", raw[6:10])
        return "image/gif", w, h
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        chunk = raw[12:16]
        if chunk == b"VP8X":
            return "image/webp", 1 + int.from_bytes(raw[24:27], "little"), 1 + int.from_bytes(raw[27:30], "little")
        if chunk == b"VP8L" and raw[20:21] == b"\x2f":
            b = int.from_bytes(raw[21:25], "little")
            return "image/webp", 1 + (b & 0x3FFF), 1 + ((b >> 14) & 0x3FFF)
        if chunk == b"VP8 " and raw[23:26] == b"\x9d\x01\x2a":
            w, h = struct.unpack("<HH", raw[26:30])
            return "image/webp", w & 0x3FFF, h & 0x3FFF
        raise ValueError("WebP without a readable size")
    if raw[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(raw):
            if raw[i] != 0xFF:
                raise ValueError("JPEG damaged (marker expected)")
            marker = raw[i + 1]
            if marker == 0xFF:  # fill byte
                i += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", raw[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # start of frame: precision, height, width
                h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                return "image/jpeg", w, h
            i += 2 + length
        raise ValueError("JPEG without a frame header")
    raise ValueError(f"not a supported image (supported: {', '.join(m.split('/')[1] for m in MIME)}; recognised by its bytes)")


def decode(data: str) -> bytes:
    """Base64 (optionally as a data: URL) → bytes; ValueError with the reason."""
    s = (data or "").strip()
    m = re.match(r"data:[\w/+.-]+;base64,", s)
    if m:
        s = s[m.end():]
    if len(s) > IMAGE_MAX * 4 // 3 + 8:
        raise ValueError(f"image larger than {IMAGE_MAX // (1024 * 1024)} MiB")
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"image is not valid base64 ({e})") from e


def regions(raw: list | None, width: int, height: int) -> list[dict]:
    """Regions in SAM 3 form → stored form {begriff, box, score, maske?}; ValueError names the first bad region and why."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("regions must be a list")
    if len(raw) > REGIONS_MAX:
        raise ValueError(f"{len(raw)} regions, at most {REGIONS_MAX}")
    out = []
    for n, r in enumerate(raw, 1):
        where = f"region {n}"
        if not isinstance(r, dict):
            raise ValueError(f"{where}: must be an object {{concept, box, score, mask?}}")
        concept = str(r.get("concept") or r.get("begriff") or "").strip()
        if not 1 <= len(concept) <= CONCEPT_MAX:
            raise ValueError(f"{where}: concept (the noun phrase, e.g. 'red plug') must have 1–{CONCEPT_MAX} characters")
        box = r.get("box")
        if (not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)):
            raise ValueError(f"{where}: box must be [x0, y0, x1, y1] in pixels (SAM 3: absolute coordinates, xyxy)")
        x0, y0, x1, y1 = (round(float(v), 1) for v in box)
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError(f"{where}: box {box} lies outside the image {width}×{height} or is empty (x0 < x1, y0 < y1)")
        score = r.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
            raise ValueError(f"{where}: score must be a number 0–1")
        item = {"begriff": concept, "box": [x0, y0, x1, y1], "score": round(float(score), 4)}
        mask = r.get("mask", r.get("maske"))
        if mask is not None:
            if not isinstance(mask, dict) or list(mask.get("size") or []) != [height, width]:
                raise ValueError(f"{where}: mask must be COCO RLE {{size: [{height}, {width}], counts}} (size = [height, width] of the image)")
            counts = mask.get("counts")
            ok = (isinstance(counts, str) and 0 < len(counts) <= MASK_MAX) or (
                isinstance(counts, list) and 0 < len(counts) <= MASK_MAX and all(isinstance(c, int) and c >= 0 for c in counts))
            if not ok:
                raise ValueError(f"{where}: mask counts must be an RLE string or a list of non-negative integers (at most {MASK_MAX})")
            item["maske"] = {"size": [height, width], "counts": counts}
        out.append(item)
    return out


def store(raw: bytes) -> dict:
    """Store the bytes (once per SHA-256) → the reference {sha, mime, breite, hoehe, bytes}; ValueError if not an image or too large."""
    if not raw:
        raise ValueError("image is empty")
    if len(raw) > IMAGE_MAX:
        raise ValueError(f"image has {len(raw)} bytes, at most {IMAGE_MAX} ({IMAGE_MAX // (1024 * 1024)} MiB)")
    mime, w, h = sniff(raw)
    if not (w > 0 and h > 0):
        raise ValueError(f"image size {w}×{h} not readable")
    sha = hashlib.sha256(raw).hexdigest()
    _table()
    with g.lock:
        if not g.db().execute("SELECT 1 FROM bild WHERE sha = ?", (sha,)).fetchone():
            total = g.db().execute("SELECT COALESCE(SUM(bytes), 0) FROM bild").fetchone()[0]
            if total + len(raw) > TOTAL_MAX:
                raise ValueError(f"image store full: {total} of {TOTAL_MAX} bytes used — nothing was stored")
            g.db().execute("INSERT INTO bild (sha, mime, breite, hoehe, bytes, zeit, roh) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (sha, mime, w, h, len(raw), g.now(), raw))
            g.db().commit()
    return {"sha": sha, "mime": mime, "breite": w, "hoehe": h, "bytes": len(raw)}


def load(sha: str) -> bytes | None:
    _table()
    with g.lock:
        r = g.db().execute("SELECT roh FROM bild WHERE sha = ?", (sha or "",)).fetchone()
    return bytes(r[0]) if r else None


def stats() -> tuple[int, int]:
    """(number of stored images, raw bytes together)."""
    _table()
    with g.lock:
        n, b = g.db().execute("SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM bild").fetchone()
    return n, b


def line() -> str:
    n, b = stats()
    return f"{n} image{'' if n == 1 else 's'}, {b / 1024 ** 2:.1f} of {TOTAL_MAX // 1024 ** 3} GiB"


def concept_tags(stored_regions: list[dict]) -> list[str]:
    """zeigt:<concept> per distinct concept (lower case, blanks and brackets → "-"), so vi_recall zeigt:stecker finds the images showing it."""
    seen = []
    for r in stored_regions:
        value = re.sub(r"[\s()]+", "-", r["begriff"].strip().lower()).strip("-")  # a hashtag value has no blanks or brackets (memory.TAG)
        t = "zeigt:" + value
        if value and t not in seen:
            seen.append(t)
    return seen


def summary(o) -> str | None:
    """One line for vi_object/vi_recall: 'image png 1024×768, 213 KiB, 3 regions (plug ×2, cable)' — None without an image."""
    b = o.data.get("bild")
    if not b:
        return None
    rs = o.data.get("regionen") or []
    counts: dict[str, int] = {}
    for r in rs:
        counts[r["begriff"]] = counts.get(r["begriff"], 0) + 1
    names = ", ".join(f"{k} ×{v}" if v > 1 else k for k, v in list(counts.items())[:8])
    return (f"image {b['mime'].split('/')[1]} {b['breite']}×{b['hoehe']}, {b['bytes'] // 1024} KiB"
            + (f", {len(rs)} region{'' if len(rs) == 1 else 's'} ({names}{', …' if len(counts) > 8 else ''})" if rs else ", no regions"))
