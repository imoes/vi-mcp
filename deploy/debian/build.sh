#!/usr/bin/env bash
# Baut dist/vi-mcp_<version>-<rev>_all.deb aus dem Arbeitsbaum. Nur dpkg-deb nötig.
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
install -m 0644 README.md CHANGELOG.md "$r/usr/share/doc/vi-mcp/"
# docs/LOKAL* enthält Hostangaben und den Prüfer-Prompt und darf in kein Paket
find docs -maxdepth 1 -name "*.md" ! -name "LOKAL*" -exec install -m 0644 {} "$r/usr/share/doc/vi-mcp/docs/" \;
install -m 0755 hook/vi_hook.py "$r/usr/share/vi-mcp/hook/vi_hook.py"
for s in postinst prerm postrm; do install -m 0755 "deploy/debian/$s" "$r/DEBIAN/$s"; done
groesse=$(du -sk "$r" | cut -f1)
# Maintainer aus DEB_MAINTAINER oder der git-Konfiguration — steht nicht fest im Repo
maintainer="${DEB_MAINTAINER:-$(git config user.name) <$(git config user.email)>}"
cat > "$r/DEBIAN/control" <<CTRL
Package: vi-mcp
Version: ${version}-${rev}
Architecture: all
Maintainer: ${maintainer}
Depends: python3 (>= 3.11), python3-sklearn, python3-cryptography, python3-numpy, adduser, systemd
Section: net
Priority: optional
Installed-Size: ${groesse}
Homepage: file:///usr/share/doc/vi-mcp/README.md
Description: VI-Gedaechtnis als MCP-Server (Streamable HTTP, ein Prozess)
 Ein Serverprozess mit einem gemeinsamen Gedaechtnis fuer viele KI-Sitzungen:
 Objekte mit Hashtags, Erfahrungen, Erkenntnisse, Regeln, Reflexe, gelernte
 Suchen; ein Gespraech je Sitzung.
CTRL
mkdir -p dist
dpkg-deb --root-owner-group --build "$r" "dist/${paket}.deb" >/dev/null
echo "dist/${paket}.deb"
