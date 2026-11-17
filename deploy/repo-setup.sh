#!/bin/sh
# Adds the signed vi-mcp package repository (apt, dnf or pacman) — published as https://imoes.github.io/vi-mcp-packages/setup.sh (0.54.0):
#   curl -fsSL https://imoes.github.io/vi-mcp-packages/setup.sh | sudo sh
# Only adds the repository (key + source); it installs nothing else. Then: apt install vi-mcp / dnf install vi-mcp / pacman -Syu vi-mcp,
# later the normal updates.
set -eu
BASE=https://imoes.github.io/vi-mcp-packages
FPR=4598315414EBF86CABD322D9730B75BFAC3036B7
[ "$(id -u)" = 0 ] || { echo "run as root: curl -fsSL $BASE/setup.sh | sudo sh" >&2; exit 1; }
fetch() {  # url file
    if command -v curl >/dev/null 2>&1; then curl -fsSLo "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
    else echo "curl or wget is needed" >&2; exit 1; fi
}
if command -v apt-get >/dev/null 2>&1; then
    fetch "$BASE/vi-mcp-repo.gpg" /usr/share/keyrings/vi-mcp.gpg
    chmod 0644 /usr/share/keyrings/vi-mcp.gpg
    fetch "$BASE/vi-mcp.sources" /etc/apt/sources.list.d/vi-mcp.sources
    apt-get update -o Dir::Etc::sourcelist=sources.list.d/vi-mcp.sources -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 >/dev/null \
        || echo "note: apt-get update of the vi-mcp repository failed (network or proxy?) — the repository is added anyway" >&2
    echo "vi-mcp repository added (key $FPR). Install: sudo apt install vi-mcp — updates then come with sudo apt upgrade."
elif command -v dnf >/dev/null 2>&1; then
    fetch "$BASE/vi-mcp.repo" /etc/yum.repos.d/vi-mcp.repo
    echo "vi-mcp repository added. Install: sudo dnf install vi-mcp (dnf asks once to import the key — its fingerprint must be $FPR);"
    echo "updates then come with sudo dnf upgrade. AlmaLinux/RHEL 10 need EPEL first: sudo dnf install epel-release"
elif command -v pacman-key >/dev/null 2>&1; then  # Arch Linux, CachyOS (issue #3)
    key=$(mktemp)
    fetch "$BASE/vi-mcp-repo.asc" "$key"
    if ! { pacman-key --add "$key" && pacman-key --lsign-key "$FPR"; } >/dev/null 2>&1; then
        rm -f "$key"; echo "pacman-key could not add or sign the key $FPR (run pacman-key --init first?)" >&2; exit 1
    fi
    rm -f "$key"
    if ! grep -q '^\[vi-mcp\]' /etc/pacman.conf; then
        printf '\n[vi-mcp]\nSigLevel = Required\nServer = %s/arch\n' "$BASE" >> /etc/pacman.conf
    fi
    echo "vi-mcp repository added to /etc/pacman.conf (key $FPR, locally signed). Install: sudo pacman -Syu vi-mcp,"
    echo "then: sudo systemctl enable --now vi-mcp.service — updates then come with sudo pacman -Syu."
else
    echo "neither apt, dnf nor pacman found — download a package from https://github.com/imoes/vi-mcp/releases" >&2
    exit 1
fi
