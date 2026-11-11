#!/usr/bin/env bash
# Builds the signed package repositories for apt (Debian/Ubuntu) and dnf (Fedora/RHEL) from release packages, so servers get vi-mcp
# with `apt upgrade` / `dnf upgrade` (0.54.0). Published on GitHub Pages: https://imoes.github.io/vi-mcp-packages/
#   deploy/publish-repo.sh <directory with vi-mcp_*.deb and vi-mcp-*.rpm> <checkout of the packages repository>
# Every version stays in the pool (an apt/dnf client may pin or downgrade). Signing key: an OpenPGP key only for the repository,
# GNUPGHOME $VI_MCP_REPO_GNUPG (default ~/.config/vi-mcp/repo-gnupg), never in a repository; its public part is published next to it.
set -euo pipefail
src=$(cd "$1" && pwd)
out=$(cd "$2" && pwd)
here=$(cd "$(dirname "$0")" && pwd)
export GNUPGHOME="${VI_MCP_REPO_GNUPG:-$HOME/.config/vi-mcp/repo-gnupg}"
fpr=$(gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '/^fpr/{print $10; exit}')
[ -n "$fpr" ] || { echo "no signing key in $GNUPGHOME" >&2; exit 2; }
shopt -s nullglob
debs=("$src"/vi-mcp_*_all.deb)
rpms=("$src"/vi-mcp-*.noarch.rpm)
[ ${#debs[@]} -gt 0 ] || [ ${#rpms[@]} -gt 0 ] || { echo "no packages in $src" >&2; exit 2; }

# ---- public key (armored and binary: apt's Signed-By takes the binary form without needing gpg on the server)
gpg --armor --export "$fpr" > "$out/vi-mcp-repo.asc"
gpg --export "$fpr" > "$out/vi-mcp-repo.gpg"

# ---- apt: pool + dists/stable/main, indices for all, amd64 and arm64 (an Architecture: all package is listed in every one)
if [ ${#debs[@]} -gt 0 ]; then
    a="$out/apt"
    mkdir -p "$a/pool/main"
    cp -n "${debs[@]}" "$a/pool/main/" 2>/dev/null || true
    for arch in all amd64 arm64; do
        d="$a/dists/stable/main/binary-$arch"
        mkdir -p "$d"
        (cd "$a" && if [ "$arch" = all ]; then dpkg-scanpackages --multiversion pool/main /dev/null; else dpkg-scanpackages --multiversion -a "$arch" pool/main /dev/null; fi) > "$d/Packages" 2>/dev/null
        gzip -9nkf "$d/Packages"
    done
    (cd "$a/dists/stable" && apt-ftparchive -o APT::FTPArchive::Release::Origin=vi-mcp -o APT::FTPArchive::Release::Label=vi-mcp \
        -o APT::FTPArchive::Release::Suite=stable -o APT::FTPArchive::Release::Codename=stable \
        -o APT::FTPArchive::Release::Architectures="all amd64 arm64" -o APT::FTPArchive::Release::Components=main \
        -o APT::FTPArchive::Release::Description="vi-mcp packages" release . > Release)
    rm -f "$a/dists/stable/InRelease" "$a/dists/stable/Release.gpg"
    gpg --batch --yes --local-user "$fpr" --clearsign -o "$a/dists/stable/InRelease" "$a/dists/stable/Release"
    gpg --batch --yes --local-user "$fpr" -abs -o "$a/dists/stable/Release.gpg" "$a/dists/stable/Release"
fi

# ---- dnf: signed packages, repodata, signed repomd.xml — in a Fedora container (rpmsign, createrepo_c)
if [ ${#rpms[@]} -gt 0 ]; then
    r="$out/rpm"
    mkdir -p "$r"
    for f in "${rpms[@]}"; do [ -e "$r/$(basename "$f")" ] || cp "$f" "$r/"; done
    keydir=$(mktemp -d)
    chmod 700 "$keydir"
    trap 'rm -rf "$keydir"' EXIT
    gpg --batch --pinentry-mode loopback --passphrase '' --armor --export-secret-keys "$fpr" > "$keydir/secret.asc"
    docker run --rm --network host -e http_proxy -e https_proxy -e no_proxy -v "$keydir:/key:ro" -v "$r:/repo" -e FPR="$fpr" fedora:43 \
        bash -c 'set -e; dnf -q -y install rpm-sign createrepo_c gnupg2 >/dev/null
                 export GNUPGHOME=/tmp/g; mkdir -m 700 $GNUPGHOME; gpg --batch --import /key/secret.asc 2>/dev/null
                 keyid=$(echo "$FPR" | tail -c 17 | tr A-F a-f)
                 for f in /repo/*.rpm; do  # sign what is not signed by this key yet (old versions keep their signature)
                     rpm -qp --qf "%{RSAHEADER:pgpsig} %{SIGPGP:pgpsig}\n" "$f" 2>/dev/null | tr A-F a-f | grep -q "$keyid" && continue
                     rpmsign --define "_gpg_name $FPR" --addsign "$f" >/dev/null; done
                 createrepo_c -q --update --general-compress-type=gz /repo  # gz: also for older dnf
                 rm -f /repo/repodata/repomd.xml.asc
                 gpg --batch --yes --local-user "$FPR" --detach-sign --armor /repo/repodata/repomd.xml
                 chown -R --reference=/repo /repo'
    rm -rf "$keydir"
    trap - EXIT
fi

# ---- the .repo file and a page that says how to use it
cat > "$out/vi-mcp.repo" <<'EOF'
[vi-mcp]
name=vi-mcp
baseurl=https://imoes.github.io/vi-mcp-packages/rpm
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=https://imoes.github.io/vi-mcp-packages/vi-mcp-repo.asc
EOF
cat > "$out/vi-mcp.sources" <<'EOF'
Types: deb
URIs: https://imoes.github.io/vi-mcp-packages/apt
Suites: stable
Components: main
Signed-By: /usr/share/keyrings/vi-mcp.gpg
EOF
cp "$here/repo-setup.sh" "$out/setup.sh"  # the one-liner: curl -fsSL …/setup.sh | sudo sh
touch "$out/.nojekyll"
python3 "$here/publish-repo-page.py" "$out" "$fpr"
echo "repository built in $out (key $fpr)"
