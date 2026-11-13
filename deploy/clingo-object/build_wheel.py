"""Build the wheel of the Python package clingo-object (import clingo_object) with the standard library only — no setuptools, no network.

    python3 deploy/clingo-object/build_wheel.py [OUT_DIR]      → OUT_DIR/clingo_object-<version>-py3-none-any.whl (path printed)

A pure-Python wheel is a zip with the package and a .dist-info directory (METADATA, WHEEL, RECORD with sha256 per file); PEP 427/491.
The clingo requirement comes from clingo_object.notation.CLINGO_MIN — the one place the minimum is stated.
"""
from __future__ import annotations

import base64
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import clingo_object  # noqa: E402
from clingo_object import notation  # noqa: E402

NAME, DIST = "clingo-object", "clingo_object"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # reproducible: the same sources give the same wheel


def _record_line(path: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{path},sha256={digest},{len(data)}"


def build(out_dir: Path) -> Path:
    version = clingo_object.__version__
    info = f"{DIST}-{version}.dist-info"
    metadata = "\n".join([
        "Metadata-Version: 2.1",
        f"Name: {NAME}",
        f"Version: {version}",
        "Summary: clingo as an object-oriented language over the objects of a VI memory (vi-mcp)",
        "Home-page: https://github.com/imoes/vi-mcp",
        "License: AGPL-3.0-or-later",
        "Requires-Python: >=3.11",
        f"Requires-Dist: clingo>={notation.CLINGO_MIN}",
        "", (clingo_object.__doc__ or "").strip(), ""])
    wheel = "Wheel-Version: 1.0\nGenerator: vi-mcp build_wheel.py\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    files: list[tuple[str, bytes]] = [(f"{DIST}/{p.name}", p.read_bytes()) for p in sorted((ROOT / DIST).glob("*.py"))]
    files += [(f"{info}/METADATA", metadata.encode()), (f"{info}/WHEEL", wheel.encode()),
              (f"{info}/LICENSE", (ROOT / "LICENSE").read_bytes())]
    record = "\n".join([_record_line(p, d) for p, d in files] + [f"{info}/RECORD,,"]) + "\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{DIST}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p, d in files + [(f"{info}/RECORD", record.encode())]:
            zi = zipfile.ZipInfo(p, FIXED_TIME)
            zi.external_attr = 0o644 << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, d)
    return target


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"))
