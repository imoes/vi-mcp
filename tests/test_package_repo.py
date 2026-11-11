"""0.54.0: the signed apt/dnf repository on GitHub Pages — the scripts that build it and the page that says how to add it."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FPR = "4598315414EBF86CABD322D9730B75BFAC3036B7"


def test_scripts_parse_and_release_publishes_after_the_github_release():
    for f in ("deploy/publish-repo.sh", "deploy/release.sh"):
        assert subprocess.run(["bash", "-n", str(ROOT / f)]).returncode == 0
    rel = (ROOT / "deploy/release.sh").read_text()
    assert rel.index("gh release create") < rel.index("deploy/publish-repo.sh") and "repository signing key missing" in rel
    pub = (ROOT / "deploy/publish-repo.sh").read_text()
    assert "--clearsign" in pub and "repomd.xml" in pub and "repo_gpgcheck=1" in pub and "Signed-By: /usr/share/keyrings/vi-mcp.gpg" in pub


def test_the_start_page_tells_how_to_add_the_repository(tmp_path):
    (tmp_path / "apt/pool/main").mkdir(parents=True)
    (tmp_path / "apt/pool/main/vi-mcp_0.54.0-1_all.deb").write_bytes(b"x")
    (tmp_path / "rpm").mkdir()
    (tmp_path / "rpm/vi-mcp-0.54.0-1.noarch.rpm").write_bytes(b"x")
    subprocess.run([sys.executable, str(ROOT / "deploy/publish-repo-page.py"), str(tmp_path), FPR], check=True)
    page = (tmp_path / "index.html").read_text()
    for needed in ("/usr/share/keyrings/vi-mcp.gpg", "/etc/apt/sources.list.d/vi-mcp.sources", "/etc/yum.repos.d/vi-mcp.repo",
                   "apt upgrade", "dnf upgrade", "4598 3154 14EB F86C", "0.54.0-1"):
        assert needed in page, needed


def test_the_published_key_and_the_documented_fingerprint_agree():
    key = (ROOT / "deploy/repo-key.asc").read_text()
    assert key.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----") and "PRIVATE" not in key
    for readme in ("README.md", "README.de.md"):
        t = (ROOT / readme).read_text()
        assert "4598 3154 14EB F86C ABD3  22D9 730B 75BF AC30 36B7" in t and "https://imoes.github.io/vi-mcp-packages/vi-mcp.repo" in t
        assert "curl -fsSL https://imoes.github.io/vi-mcp-packages/setup.sh | sudo sh" in t  # the one-liner the user asked for
    setup = (ROOT / "deploy/repo-setup.sh").read_text()
    assert subprocess.run(["sh", "-n", str(ROOT / "deploy/repo-setup.sh")]).returncode == 0
    assert "4598315414EBF86CABD322D9730B75BFAC3036B7" in setup and "apt-get" in setup and "/etc/yum.repos.d/vi-mcp.repo" in setup
