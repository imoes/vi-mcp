#!/usr/bin/env python3
"""Sort the rows of every table of an MSI by its primary key, in place; --check only reports.

Why (0.59.2): Windows Installer expects the rows of a table stored in primary-key order (it searches them) and refuses to open a table
that is not: OpenView fails with "OpenView,Sql", and when that table is InstallUISequence the setup runs without any dialog ("UI Sequence
table 'InstallUISequence' is missing or empty" in the msiexec log). msitools (libmsi, used by wixl and msibuild) keeps rows in the order
they were inserted while the string ids they are sorted by change from build to build — in vi-mcp 0.58.1 to 0.59.1 exactly
InstallUISequence had one row out of order (Windows 11 test VM, 12.11.2026; 0.54.1 had one in Control, 0.57.0 none).

Only the standard library: reads the compound file (header, FAT, MiniFAT, directory), finds the table streams, reorders their rows and
writes them back into the same sectors (sorting keeps the size). Exits 1 if a table stays unsorted.
"""
from __future__ import annotations

import struct
import sys

END, FREE = 0xFFFFFFFE, 0xFFFFFFFF
_ALPHA = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._"
KEY = 0x2000      # MSITYPE_KEY: column is part of the primary key
STRING = 0x0800   # MSITYPE_STRING: stored as a 2-byte string id


def decode_name(name: str) -> str:
    """MSI stream names are packed two characters per code unit (U+3800..U+47FF), U+4840 marks a table."""
    out = []
    for ch in name:
        c = ord(ch)
        if 0x3800 <= c < 0x4800:
            c -= 0x3800
            out += [_ALPHA[c & 0x3F], _ALPHA[c >> 6]]
        elif 0x4800 <= c < 0x4840:
            out.append(_ALPHA[c - 0x4800])
        elif c == 0x4840:
            out.append("!")
        else:
            out.append(ch)
    return "".join(out)


class Compound:
    """Just enough of [MS-CFB] (version 3, 512-byte sectors) to read and rewrite existing streams in place."""

    def __init__(self, path: str):
        self.path = path
        self.b = bytearray(open(path, "rb").read())
        h = self.b[:512]
        if h[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError("not a compound file")
        if struct.unpack("<H", h[0x1E:0x20])[0] != 9:
            raise ValueError("only 512-byte sectors are supported")
        _nfat, self.dir_start, _, _, self.mf_start, _nmf, difat_start, ndifat = struct.unpack("<IIIIIIII", h[0x2C:0x4C])
        self.cutoff = struct.unpack("<I", h[0x38:0x3C])[0]
        difat = [x for x in struct.unpack("<109I", h[0x4C:0x200]) if x != FREE]
        s = difat_start
        for _ in range(ndifat):  # further DIFAT sectors: 127 entries and the next sector
            vals = struct.unpack("<128I", self._sector(s))
            difat += [x for x in vals[:127] if x != FREE]
            s = vals[127]
        self.fat: list[int] = []
        for s in difat:
            self.fat += struct.unpack("<128I", self._sector(s))
        self.minifat: list[int] = []
        for s in self._chain(self.mf_start):
            self.minifat += struct.unpack("<128I", self._sector(s))
        dirdata = b"".join(self._sector(s) for s in self._chain(self.dir_start))
        self.entries = []
        for i in range(len(dirdata) // 128):
            e = dirdata[i * 128:(i + 1) * 128]
            nlen, typ = struct.unpack("<H", e[64:66])[0], e[66]
            if typ == 0:
                continue
            name = e[:max(nlen - 2, 0)].decode("utf-16-le")
            start, size = struct.unpack("<II", e[116:124])
            self.entries.append((decode_name(name), typ, start, size))
        root = [x for x in self.entries if x[1] == 5][0]
        self.ministream = self._chain(root[2])

    def _sector(self, s: int) -> bytes:
        return bytes(self.b[512 + s * 512:512 + (s + 1) * 512])

    def _chain(self, start: int, table: list[int] | None = None) -> list[int]:
        table = self.fat if table is None else table
        out, s = [], start
        while s not in (END, FREE):
            if s >= len(table) or len(out) > len(table):
                raise ValueError(f"broken chain at {s}")
            out.append(s)
            s = table[s]
        return out

    def _offsets(self, start: int, size: int) -> list[tuple[int, int]]:
        """(file offset, length) pieces of a stream, in order."""
        if size >= self.cutoff:
            return [(512 + s * 512, 512) for s in self._chain(start)][: (size + 511) // 512]
        pieces = []
        for m in self._chain(start, self.minifat)[: (size + 63) // 64]:
            big = self.ministream[(m * 64) // 512]
            pieces.append((512 + big * 512 + (m * 64) % 512, 64))
        return pieces

    def read(self, name: str) -> bytes | None:
        for n, typ, start, size in self.entries:
            if n == name and typ == 2:
                return b"".join(bytes(self.b[o:o + ln]) for o, ln in self._offsets(start, size))[:size]
        return None

    def write(self, name: str, data: bytes) -> None:
        for n, typ, start, size in self.entries:
            if n == name and typ == 2:
                if len(data) != size:
                    raise ValueError(f"{name}: size changed")
                pos = 0
                for o, ln in self._offsets(start, size):
                    chunk = data[pos:pos + ln]
                    self.b[o:o + len(chunk)] = chunk
                    pos += ln
                return
        raise KeyError(name)

    def save(self) -> None:
        with open(self.path, "wb") as f:
            f.write(self.b)


def tables(cf: Compound):
    """{table: [(column number, type)]} from _Columns (Table s2, Number i2, Name s2, Type i2 — stored column by column)."""
    pool = cf.read("!_StringPool")
    if struct.unpack("<I", pool[:4])[0] & 0x80000000:
        raise ValueError("3-byte string ids are not supported")
    data, strings, off = cf.read("!_StringData"), [None], 0
    for i in range(4, len(pool), 4):
        ln = struct.unpack("<H", pool[i:i + 2])[0]
        strings.append(data[off:off + ln].decode("cp1252", "replace"))
        off += ln
    raw = cf.read("!_Columns")
    n = len(raw) // 8
    cols = [struct.unpack(f"<{n}H", raw[k * 2 * n:(k + 1) * 2 * n]) for k in range(4)]
    out: dict[str, list[tuple[int, int]]] = {}
    for r in range(n):
        out.setdefault(strings[cols[0][r]], []).append((cols[1][r] - 0x8000, cols[3][r] - 0x8000))
    return {t: sorted(c) for t, c in out.items()}


def _layout(columns):
    widths = [2 if (ty & STRING) or (ty & 0xFF) == 2 else 4 for _num, ty in columns]
    keys = [k for k, (_num, ty) in enumerate(columns) if ty & KEY]
    return widths, keys


def sort_table(raw: bytes, columns) -> tuple[bytes, int]:
    """Rows sorted by the primary key (unsigned stored values: string ids, ints with their 0x8000/0x80000000 offset); returns (data, rows moved)."""
    widths, keys = _layout(columns)
    size = sum(widths)
    n = len(raw) // size
    if not n or not keys:
        return raw, 0
    colvals, off = [], 0
    for w in widths:
        colvals.append(list(struct.unpack(f"<{n}{'H' if w == 2 else 'I'}", raw[off:off + w * n])))
        off += w * n
    order = sorted(range(n), key=lambda r: tuple(colvals[k][r] for k in keys))
    moved = sum(1 for i, r in enumerate(order) if i != r)
    if not moved:
        return raw, 0
    out = b"".join(struct.pack(f"<{n}{'H' if w == 2 else 'I'}", *[vals[r] for r in order]) for w, vals in zip(widths, colvals))
    return out + raw[off:], moved


def main(argv: list[str]) -> int:
    check = "--check" in argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__.strip().splitlines()[0])
        return 2
    rc = 0
    for path in paths:
        cf = Compound(path)
        fixed, unsorted = [], []
        for table, columns in tables(cf).items():
            raw = cf.read("!" + table)
            if not raw:
                continue
            data, moved = sort_table(raw, columns)
            if moved:
                if check:
                    unsorted.append(f"{table} ({moved} rows)")
                else:
                    cf.write("!" + table, data)
                    fixed.append(f"{table} ({moved} rows)")
        if fixed:
            cf.save()
            again = Compound(path)
            still = [t for t, c in tables(again).items() if again.read("!" + t) and sort_table(again.read("!" + t), c)[1]]
            if still:
                print(f"{path}: still unsorted after writing: {', '.join(still)}", file=sys.stderr)
                rc = 1
        if unsorted:
            print(f"{path}: not sorted by primary key: {', '.join(unsorted)}")
            rc = 1
        elif not check:
            print(f"{path}: sorted {', '.join(fixed) if fixed else 'nothing (already in order)'}")
        else:
            print(f"{path}: every table in primary-key order")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
