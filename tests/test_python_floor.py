"""The packages promise Python ≥ 3.11 (deb: python3 >= 3.11, rpm, Arch, pyproject). Python 3.12 (PEP 701) accepts f-strings that 3.11
refuses — the same quote inside a replacement field, a backslash in an expression part — and `ast.parse(feature_version=(3, 11))` does
not catch them. Measured 18.11.2026: vi_mcp/main_loop.py used f"…{error_tag.split(":", 1)[-1]}" since 6ddbc26 (15.11.2026, 0.67.0),
so every release from 0.67.0 to 0.70.0's first build failed to start on Debian 12 (Python 3.11) with "SyntaxError: f-string: unmatched
'('", while every test ran on 3.12/3.14. This test reads the token stream (3.12+ tokenizes f-strings into parts) and flags both forms."""
import io
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _clashes(inner: str, outer: str) -> bool:
    """3.11 refuses an inner string whose quote ends the outer f-string: the same single quote, or the same triple quote; a single "
    inside f\"\"\"…\"\"\" is fine (embed_service.py does that)."""
    return inner[:len(outer)] == outer if len(outer) == 3 else inner[0] == outer[0]


def violations(source: str) -> list[tuple[int, str]]:
    out = []
    stack = []  # (quote of the enclosing f-string, depth of {} nesting inside it)
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.FSTRING_START:
            q = tok.string.lstrip("rRbBfFuU")
            if stack and stack[-1][1] > 0 and _clashes(q, stack[-1][0]):
                out.append((tok.start[0], f"nested f-string reuses the quote {q[0]} of the enclosing one"))
            stack.append([q, 0])
        elif tok.type == tokenize.FSTRING_END:
            stack.pop()
        elif stack and tok.type == tokenize.OP and tok.string in "{}":
            stack[-1][1] += 1 if tok.string == "{" else -1
        elif stack and stack[-1][1] > 0:
            if tok.type == tokenize.STRING:
                body = tok.string.lstrip("rRbBuU")
                if _clashes(body[:3] if body[:3] in ('"""', "'''") else body[0], stack[-1][0]):
                    out.append((tok.start[0], f"string {tok.string[:20]} inside an f-string with the same quote"))
                if "\\" in tok.string:
                    out.append((tok.start[0], "backslash in an f-string expression part"))
    return out


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.11 compiles the files itself — the import of every module is the check there")
def test_the_checker_finds_both_forms():
    assert violations('x = f"{a.split(":")}"\n') and violations('x = f"{re.sub(r"\\.", "", s)}"\n')
    assert violations("x = f'{a.split(\"b\")}'\n") == [] and violations('x = f"{a!r} {b:>3}"\n') == []
    assert violations('x = f"""{" ".join(a)}"""\n') == []  # allowed in 3.11: a single quote inside a triple-quoted f-string


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.11 compiles the files itself")
def test_every_python_file_compiles_on_the_promised_floor_3_11():
    bad = []
    for f in sorted(ROOT.glob("**/*.py")):
        if any(part in (".venv", "node_modules", "dist", "build") or part.startswith(".") for part in f.relative_to(ROOT).parts[:-1]):
            continue
        for line, why in violations(f.read_text(encoding="utf-8")):
            bad.append(f"{f.relative_to(ROOT)}:{line}: {why}")
    assert not bad, "\n".join(bad)
