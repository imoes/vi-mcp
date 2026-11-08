#!/usr/bin/env bash
# Baut .deb und .rpm, schreibt SHA256SUMS, signiert sie und veröffentlicht das Release.
#   deploy/release.sh            bauen, signieren, prüfen (ohne Veröffentlichung)
#   deploy/release.sh --gh       zusätzlich als GitHub-Release v<version> veröffentlichen
# Privater Schlüssel: $VI_MCP_RELEASE_SCHLUESSEL (Standard ~/.config/vi-mcp/release-ed25519.pem), liegt nie im Repo.
set -euo pipefail
cd "$(dirname "$0")/.."
schluessel="${VI_MCP_RELEASE_SCHLUESSEL:-$HOME/.config/vi-mcp/release-ed25519.pem}"
version=$(python3 -c "import vi_mcp; print(vi_mcp.__version__)")
[ -r "$schluessel" ] || { echo "Release-Schlüssel fehlt: $schluessel" >&2; exit 2; }
# Der private Schlüssel muss zum veröffentlichten öffentlichen passen, sonst prüft niemand erfolgreich
[ "$(openssl pkey -in "$schluessel" -pubout)" = "$(cat deploy/release-schluessel.pem)" ] || { echo "Schlüssel passt nicht zu deploy/release-schluessel.pem" >&2; exit 2; }
deb=$(deploy/debian/build.sh)
rpm=$(deploy/rpm/build.sh | tail -1)
cd dist
rm -f SHA256SUMS SHA256SUMS.sig
sha256sum "$(basename "$deb")" "$(basename "$rpm")" > SHA256SUMS
openssl pkeyutl -sign -inkey "$schluessel" -rawin -in SHA256SUMS -out SHA256SUMS.sig
cd ..
deploy/pruefe-release.sh dist
if [ "${1:-}" = "--gh" ]; then
    gh release create "v$version" "$deb" "$rpm" dist/SHA256SUMS dist/SHA256SUMS.sig --title "vi-mcp $version" \
        --notes-file <(python3 - "$version" <<'PY'
import sys
v = sys.argv[1]; s = open("CHANGELOG.md").read(); i = s.index(f"## {v} "); j = s.find("\n## ", i + 1)
print(s[i:j if j > 0 else None].split("\n", 1)[1].strip())
print("\nPrüfen: `deploy/pruefe-release.sh <verzeichnis>` oder von Hand mit openssl, siehe README.")
PY
) --target main
fi
