"""0.61.0: code in the index — `vi-mcp index import-code` puts the versioned code of a git repository into a project index (pieces by
function/class or text block), incrementally; vi_recall finds it, a file line appears before Read/Edit, it is never a router hint."""
import json
import subprocess
import textwrap

import pytest

from vi_mcp import code_import as ci
from vi_mcp import indexes, tools
from vi_mcp import memory as g

PY = textwrap.dedent('''\
    """Sort the rows of every MSI table by its primary key."""
    import struct


    def decode_name(name):
        """MSI stream names are packed two characters per code unit."""
        return name


    class Compound:
        """Just enough of MS-CFB."""

        def read(self, name):
            return name
    ''')


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "toolbox"
    (r / "pkg").mkdir(parents=True)
    (r / "node_modules" / "x").mkdir(parents=True)
    (r / "pkg" / "msi.py").write_text(PY)
    (r / "README.md").write_text("# toolbox\n\nsorting MSI tables\n")
    (r / "logo.png").write_bytes(b"\x89PNG\0\0binary")
    (r / "node_modules" / "x" / "i.js").write_text("module.exports = 1\n")
    (r / "package-lock.json").write_text("{}\n")
    _git(r, "init", "-q")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "one")
    return r


def _call(tool, args):
    return tools.call_tool(tool, args, "a", False)


def test_pieces_of_python_and_text():
    p = ci.chunk_python(PY)
    assert [x["symbol"] for x in p] == ["(module)", "decode_name", "Compound"]
    assert p[1]["signatur"] == "MSI stream names are packed two characters per code unit." and "def decode_name" in p[1]["code"]
    big = "\n".join(f"line {i}" if i % 30 else "" for i in range(1, 400))
    blocks = ci.chunk_text(big)
    assert len(blocks) >= 3 and all(b["bis"] - b["von"] < ci.BLOCK_LINES for b in blocks) and blocks[-1]["bis"] == 399
    assert ci.chunk_text("a\nb\n")[0]["symbol"] == "(file)"


def test_import_is_incremental_internal_and_archives_what_is_gone(gd, repo):
    r = ci.run(repo, "toolbox", _call)
    assert r["dateien"] == 2 and r["geaendert"] == 2 and r["stuecke"] == 4  # msi.py: 3 pieces, README: 1
    assert r["gruende"] == {"generated or vendored": 2, "not a text/code file type": 1}  # node_modules, lock file; the png
    held = ci._held("toolbox", "toolbox")
    assert len(held) == 4 and all(o.visibility == "intern" and o.idx == "toolbox" and "art_wissen:code" in o.hashtags for o in held)
    assert not g.db().execute("SELECT 1 FROM kante WHERE a IN (%s)" % ",".join("?" * len(held)), [o.id for o in held]).fetchone()  # no links
    assert ci.run(repo, "toolbox", _call)["geaendert"] == 0  # nothing changed: nothing sent
    (repo / "pkg" / "msi.py").write_text(PY.replace("return name\n\n\nclass", "return name.upper()\n\n\nclass").replace(
        "class Compound:", "class Archive:"))
    (repo / "README.md").unlink()
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "two")
    r2 = ci.run(repo, "toolbox", _call)
    assert r2["geaendert"] == 1 and r2["entfernt"] == 1
    syms = {o.data["symbol"]: o for o in ci._held("toolbox", "toolbox")}
    assert set(syms) == {"(module)", "decode_name", "Archive"} and "name.upper()" in syms["decode_name"].data["inhalt"]
    gone = g.load(ci.piece_id("toolbox", "toolbox", "pkg/msi.py", "Compound"))
    assert gone.mode == "archiviert" and "removed in commit" in gone.data["grund"]  # nothing vanishes silently
    with pytest.raises(ValueError, match="project index"):
        ci.run(repo, "global", _call)


def test_search_and_the_file_line(gd, repo, monkeypatch):
    from vi_mcp import intuition, session
    monkeypatch.setattr(indexes, "_config", lambda: {})
    ci.run(repo, "toolbox", _call)
    own = tools.call_tool("vi_recall", {"filter": "decode_name", "project": "toolbox", "semantic": False}, "a", False)
    assert "decode_name" in own
    other = tools.call_tool("vi_recall", {"filter": "decode_name", "project": "elsewhere", "semantic": False}, "a", False)
    assert "code hit(s) from other indexes not shown" in other
    asked = tools.call_tool("vi_recall", {"filter": "art_wissen:code decode_name", "semantic": False}, "a", False)
    assert "decode_name" in asked
    s = session.begin("a", "claude-code-hook 1", "toolbox")
    with session.on_behalf(s):
        r = intuition.before("Edit", {"file_path": f"{repo}/pkg/msi.py", "old_string": "x", "new_string": "y"}, "a", False)
    line = [h for h in r["hinweise"] if h.startswith("Code index toolbox:")]
    assert line and "pkg/msi.py holds decode_name, Compound" in line[0]
    assert r["zugriff"]["code_datei"] == "pkg/msi.py" and not any(i.startswith("erkenntnis:code-") for i in r["zugriff"]["gezeigt"])


def test_code_needs_a_token_and_never_reaches_an_open_network(gd, repo, monkeypatch):
    from vi_mcp import config, p2p
    with pytest.raises(tools.Rejected, match="token"):
        tools.call_tool("vi_code_sync", {"action": "state", "index": "toolbox", "repo": "x"}, config.OPEN, False)
    ci.run(repo, "toolbox", _call)
    p2p.generate_token("a")
    out = json.dumps(p2p.outbox(), ensure_ascii=False)
    assert "decode_name" not in out
