#!/usr/bin/env bash
# Builds .deb and .rpm, writes SHA256SUMS, signs them and publishes the release.
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
fi
deb=$(deploy/debian/build.sh)
rpm=$(deploy/rpm/build.sh | tail -1)
cd dist
rm -f SHA256SUMS SHA256SUMS.sig
sha256sum "$(basename "$deb")" "$(basename "$rpm")" > SHA256SUMS
openssl pkeyutl -sign -inkey "$key" -rawin -in SHA256SUMS -out SHA256SUMS.sig
cd ..
deploy/pruefe-release.sh dist
if [ "${1:-}" = "--gh" ]; then
    gh release create "v$version" "$deb" "$rpm" dist/SHA256SUMS dist/SHA256SUMS.sig --title "vi-mcp $version" \
        --notes-file <(python3 - "$version" <<'PY'
import sys
v = sys.argv[1]; s = open("CHANGELOG.md").read(); i = s.index(f"## {v} "); j = s.find("\n## ", i + 1)
print(s[i:j if j > 0 else None].split("\n", 1)[1].strip())
print("\nVerify: `deploy/pruefe-release.sh <directory>` or by hand with openssl, see README.")
PY
) --target "$(git rev-parse HEAD)"
fi
