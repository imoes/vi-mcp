#!/usr/bin/env bash
# Builds .deb, .rpm and the Windows .msi, writes SHA256SUMS, signs them and publishes the release.
#   deploy/release.sh            build, sign, verify (no publishing)
#   deploy/release.sh --gh       also publish as GitHub release v<version>
# Private key: $VI_MCP_RELEASE_KEY (old name VI_MCP_RELEASE_SCHLUESSEL; default ~/.config/vi-mcp/release-ed25519.pem), never in the repo.
set -euo pipefail
cd "$(dirname "$0")/.."
key="${VI_MCP_RELEASE_KEY:-${VI_MCP_RELEASE_SCHLUESSEL:-$HOME/.config/vi-mcp/release-ed25519.pem}}"
version=$(python3 -c "import vi_mcp; print(vi_mcp.__version__)")
[ -r "$key" ] || { echo "release key missing: $key" >&2; exit 2; }
# The private key must match the published public key, otherwise nobody can verify the release
[ "$(openssl pkey -in "$key" -pubout)" = "$(cat deploy/release-schluessel.pem)" ] || { echo "key does not match deploy/release-schluessel.pem" >&2; exit 2; }
if [ "${1:-}" = "--gh" ]; then
    # 0.23.0: the tag must point at the commit the packages are built from. Before, `--target main` used the remote main —
    # a release created before the push tagged an older commit (v0.22.0 pointed at 0.21.2).
    git diff --quiet HEAD || { echo "working tree has uncommitted changes — commit first" >&2; exit 2; }
    git fetch -q origin main
    [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "HEAD is not origin/main — push first, then release" >&2; exit 2; }
    ! git ls-remote --exit-code --tags origin "v$version" >/dev/null || { echo "tag v$version already exists on origin" >&2; exit 2; }
    # 0.30.1: the CHANGELOG entry must exist and carry a date (v0.30.1 was released with "unreleased" in its heading)
    grep -qE "^## $version — [0-9]{4}-[0-9]{2}-[0-9]{2}" CHANGELOG.md || { echo "CHANGELOG.md has no dated entry \"## $version — YYYY-MM-DD\"" >&2; exit 2; }
    # 0.54.0: the apt/dnf repository is signed with its own OpenPGP key — check it before anything is built or published
    GNUPGHOME="${VI_MCP_REPO_GNUPG:-$HOME/.config/vi-mcp/repo-gnupg}" gpg --list-secret-keys 2>/dev/null | grep -q '^sec' \
        || { echo "repository signing key missing (VI_MCP_REPO_GNUPG) — needed to publish to the apt/dnf repository" >&2; exit 2; }
fi
deb=$(deploy/debian/build.sh)
rpm=$(deploy/rpm/build.sh | tail -1)
msi=$(deploy/windows/build.sh | tail -1)
cd dist
rm -f SHA256SUMS SHA256SUMS.sig
sha256sum "$(basename "$deb")" "$(basename "$rpm")" "$(basename "$msi")" > SHA256SUMS
openssl pkeyutl -sign -inkey "$key" -rawin -in SHA256SUMS -out SHA256SUMS.sig
cd ..
deploy/pruefe-release.sh dist
if [ "${1:-}" = "--gh" ]; then
    gh release create "v$version" "$deb" "$rpm" "$msi" dist/SHA256SUMS dist/SHA256SUMS.sig --title "vi-mcp $version" \
        --notes-file <(python3 - "$version" <<'PY'
import sys
v = sys.argv[1]; s = open("CHANGELOG.md").read(); i = s.index(f"## {v} "); j = s.find("\n## ", i + 1)
print(s[i:j if j > 0 else None].split("\n", 1)[1].strip())
print("\nVerify: `deploy/pruefe-release.sh <directory>` or by hand with openssl, see README.")
PY
) --target "$(git rev-parse HEAD)"
    # 0.54.0: the signed apt/dnf repository on GitHub Pages — servers that added it get this version with apt/dnf upgrade
    repo_dir=$(mktemp -d); pkg_dir=$(mktemp -d)
    gh repo clone imoes/vi-mcp-packages "$repo_dir" -- -q
    cp "$deb" "$rpm" "$pkg_dir/"
    deploy/publish-repo.sh "$pkg_dir" "$repo_dir"
    (cd "$repo_dir" && git add -A && git -c user.name=imoes -c user.email=imoes@users.noreply.github.com commit -q -m "vi-mcp $version" && git push -q)
    rm -rf "$repo_dir" "$pkg_dir"
    echo "published to https://imoes.github.io/vi-mcp-packages/ (apt and dnf)"
fi
