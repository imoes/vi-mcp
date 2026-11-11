#!/usr/bin/env bash
# Builds dist/vi-mcp_<version>-<rev>_all.deb from the working tree. Needs only dpkg-deb.
set -euo pipefail
cd "$(dirname "$0")/../.."
version=$(python3 -c "import vi_mcp; print(vi_mcp.__version__)")
rev="${DEB_REV:-1}"
paket="vi-mcp_${version}-${rev}_all"
bau=$(mktemp -d); trap 'rm -rf "$bau"' EXIT
r="$bau/$paket"
install -d "$r/DEBIAN" "$r/usr/lib/python3/dist-packages/vi_mcp" "$r/usr/bin" "$r/lib/systemd/system" \
           "$r/usr/share/doc/vi-mcp/docs" "$r/usr/share/vi-mcp/hook"
install -m 0644 vi_mcp/*.py "$r/usr/lib/python3/dist-packages/vi_mcp/"
install -m 0755 deploy/debian/vi-mcp.sh "$r/usr/bin/vi-mcp"
install -m 0644 deploy/debian/vi-mcp.service "$r/lib/systemd/system/vi-mcp.service"
install -m 0644 deploy/vi-p2p.service "$r/lib/systemd/system/vi-p2p.service"
install -m 0644 deploy/vi-p2p@.service "$r/lib/systemd/system/vi-p2p@.service"
install -m 0644 README.md README.de.md AGENTS.md CHANGELOG.md "$r/usr/share/doc/vi-mcp/"
# docs/LOKAL* holds host details and the reviewer prompt and must never go into a package
find docs -maxdepth 1 -name "*.md" ! -name "LOKAL*" -exec install -m 0644 {} "$r/usr/share/doc/vi-mcp/docs/" \;
install -m 0755 hook/vi_hook.py "$r/usr/share/vi-mcp/hook/vi_hook.py"
install -m 0755 deploy/nach-installation.sh "$r/usr/share/vi-mcp/nach-installation.sh"
for s in postinst prerm postrm; do install -m 0755 "deploy/debian/$s" "$r/DEBIAN/$s"; done
# 0.48.0: debconf — questions and dialogs generated from vi_mcp/configure.py (one catalogue for debconf and the RPM menu)
PYTHONPATH=. python3 -m vi_mcp configure --debconf-templates > "$r/DEBIAN/templates"
PYTHONPATH=. python3 -m vi_mcp configure --debconf-config > "$r/DEBIAN/config"
chmod 0755 "$r/DEBIAN/config"
groesse=$(du -sk "$r" | cut -f1)
# Maintainer from DEB_MAINTAINER or the git config — not fixed in the repo
maintainer="${DEB_MAINTAINER:-$(git config user.name) <$(git config user.email)>}"
cat > "$r/DEBIAN/control" <<CTRL
Package: vi-mcp
Version: ${version}-${rev}
Architecture: all
Maintainer: ${maintainer}
Depends: python3 (>= 3.11), python3-sklearn, python3-cryptography, python3-numpy, python3-yaml, adduser, systemd, debconf (>= 0.5) | debconf-2.0
Recommends: python3-libtorrent
Suggests: python3-psycopg
Section: net
Priority: optional
Installed-Size: ${groesse}
Homepage: https://github.com/imoes/vi-mcp
Description: VI-Gedaechtnis als MCP-Server (Streamable HTTP, ein Prozess)
 Ein Serverprozess mit einem gemeinsamen Gedaechtnis fuer viele KI-Sitzungen:
 Objekte mit Hashtags, Erfahrungen, Erkenntnisse, Regeln, Reflexe, gelernte
 Suchen; ein Gespraech je Sitzung.
CTRL
mkdir -p dist
dpkg-deb --root-owner-group --build "$r" "dist/${paket}.deb" >/dev/null
echo "dist/${paket}.deb"
