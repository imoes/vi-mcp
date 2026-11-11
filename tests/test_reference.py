"""0.54.0: the documentation is complete — every tool parameter has a description (the clients show it to the model), and
docs/REFERENCE.md is what the code says (scripts/gen_reference.py): every config key, network field, environment variable and endpoint
described. A gap fails here, not with a user."""
import subprocess
import sys
from pathlib import Path

from vi_mcp import tools

ROOT = Path(__file__).resolve().parent.parent


def test_every_tool_parameter_has_a_description():
    missing = [(t["name"], p) for t in tools.TOOLS for p, spec in t["inputSchema"].get("properties", {}).items() if not spec.get("description")]
    assert missing == []


def test_shared_schema_objects_stay_bare():
    assert "description" not in tools._S and "description" not in tools._TAGS  # descriptions live on copies


def test_reference_is_complete_and_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_reference.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr


def test_every_document_is_listed_in_the_index():
    index = (ROOT / "docs" / "README.md").read_text()
    for f in sorted((ROOT / "docs").glob("*.md")):
        if f.name not in ("README.md",) and not f.name.startswith("LOKAL"):
            assert f.name in index, f.name
    for top in ("README.md", "README.de.md"):
        assert "docs/README.md" in (ROOT / top).read_text(), top
