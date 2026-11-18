"""The start page of the package repository (index.html): how to add it on Debian/Ubuntu, Fedora/RHEL and Arch/CachyOS, the key's fingerprint, the
versions in it. Standard library only; called by publish-repo.sh."""
import html
import re
import sys
from pathlib import Path

out, fpr = Path(sys.argv[1]), sys.argv[2]
base = "https://imoes.github.io/vi-mcp-packages"
debs = sorted((out / "apt" / "pool" / "main").glob("vi-mcp_*_all.deb")) if (out / "apt").exists() else []
rpms = sorted((out / "rpm").glob("vi-mcp-*.noarch.rpm")) if (out / "rpm").exists() else []
pkgs = sorted((out / "arch").glob("vi-mcp-*-any.pkg.tar.zst")) if (out / "arch").exists() else []
key = re.sub(r"(.{4})", r"\1 ", fpr).strip()


def versions(files, pattern):
    v = [m.group(1) for f in files if (m := re.search(pattern, f.name))]
    return ", ".join(html.escape(x) for x in sorted(set(v), key=lambda s: [int(p) if p.isdigit() else p for p in re.split(r"[.-]", s)])) or "—"


# outside the f-string: a regex with a backslash inside a replacement field needs Python 3.12 (the packages promise 3.11)
apt_versions = versions(debs, r"vi-mcp_([^_]+)_all")
dnf_versions = versions(rpms, r"vi-mcp-(.+)\.noarch")
pacman_versions = versions(pkgs, r"vi-mcp-(.+)-any\.pkg")

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>vi-mcp packages</title><style>body{{font:15px/1.5 system-ui,sans-serif;max-width:52rem;margin:2rem auto;padding:0 1rem;color:#1d2330}}
pre{{background:#f3f4f7;padding:.8rem;overflow-x:auto;border-radius:6px}}code{{font-size:.92em}}h2{{margin-top:2rem}}.fp{{font-family:monospace}}</style></head><body>
<h1>vi-mcp package repository</h1>
<p>Signed apt, dnf and pacman repositories for <a href="https://github.com/imoes/vi-mcp">vi-mcp</a>, so a server gets new versions with its normal updates.
The same packages are attached to every <a href="https://github.com/imoes/vi-mcp/releases">GitHub release</a>.</p>
<p>Signing key (OpenPGP, Ed25519): <span class="fp">{key}</span> — <a href="vi-mcp-repo.asc">vi-mcp-repo.asc</a>.
Compare the fingerprint with the one in the README of the code repository before you trust it.</p>
<h2>In one line</h2>
<pre>curl -fsSL {base}/setup.sh | sudo sh</pre>
<p>Adds the repository — key and source — on apt, dnf and pacman systems, installs nothing else (<a href="setup.sh">read it first</a>). Then
<code>sudo apt install vi-mcp</code>, <code>sudo dnf install vi-mcp</code> or <code>sudo pacman -Syu vi-mcp</code>. The same by hand:</p>
<h2>Debian 12+, Ubuntu 24.04+</h2>
<pre>sudo curl -fsSLo /usr/share/keyrings/vi-mcp.gpg {base}/vi-mcp-repo.gpg
sudo curl -fsSLo /etc/apt/sources.list.d/vi-mcp.sources {base}/vi-mcp.sources
sudo apt update &amp;&amp; sudo apt install vi-mcp        # later: sudo apt upgrade</pre>
<h2>Fedora, AlmaLinux/RHEL 10 (with EPEL)</h2>
<pre>sudo curl -fsSLo /etc/yum.repos.d/vi-mcp.repo {base}/vi-mcp.repo
sudo dnf install vi-mcp                              # later: sudo dnf upgrade</pre>
<p>dnf asks once to import the key; check that its fingerprint is the one above.</p>
<h2>Arch Linux, CachyOS</h2>
<pre>curl -fsSLo /tmp/vi-mcp-repo.asc {base}/vi-mcp-repo.asc &amp;&amp; sudo pacman-key --add /tmp/vi-mcp-repo.asc
sudo pacman-key --lsign-key {fpr}
curl -fsSL {base}/vi-mcp.pacman.conf | sudo tee -a /etc/pacman.conf
sudo pacman -Syu vi-mcp                              # later: sudo pacman -Syu
sudo systemctl enable --now vi-mcp.service</pre>
<p>Packages and the database are signed (<code>SigLevel = Required</code>); the key is trusted only for what you sign locally.</p>
<h2>Versions</h2>
<p>apt: {apt_versions}<br>dnf: {dnf_versions}<br>pacman: {pacman_versions}</p>
</body></html>
"""
(out / "index.html").write_text(page, encoding="utf-8")
