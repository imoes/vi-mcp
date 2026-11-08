#!/usr/bin/env bash
# Baut dist/vi-mcp-<version>-<rev>.noarch.rpm aus dem Arbeitsbaum. Ohne rpmbuild läuft der Bau in einem Fedora-Container.
set -euo pipefail
cd "$(dirname "$0")/../.."
version=$(python3 -c "import vi_mcp; print(vi_mcp.__version__)")
rev="${RPM_REV:-1}"
mkdir -p dist
if ! command -v rpmbuild >/dev/null; then
    docker run --rm --network host -e http_proxy -e https_proxy -e no_proxy -e RPM_REV="$rev" -e RPM_PACKAGER="${RPM_PACKAGER:-}" \
        -v "$PWD:/src:ro" -v "$PWD/dist:/dist" fedora:43 \
        bash -c 'dnf -q -y install rpm-build python3 >/dev/null && cp -a /src /tmp/q && cd /tmp/q && rm -rf dist && mkdir dist && deploy/rpm/build.sh >/dev/null && cp dist/*.rpm /dist/ && chown --reference=/dist /dist/*.rpm'
    echo "dist/vi-mcp-${version}-${rev}.noarch.rpm"
    exit 0
fi
bau=$(mktemp -d); trap 'rm -rf "$bau"' EXIT
b="$bau/baum"
install -d "$b/usr/lib/vi-mcp/vi_mcp" "$b/usr/bin" "$b/usr/libexec" "$b/usr/lib/systemd/system" "$b/usr/share/doc/vi-mcp/docs" "$b/usr/share/vi-mcp/hook"
install -m 0644 vi_mcp/*.py "$b/usr/lib/vi-mcp/vi_mcp/"
install -m 0755 deploy/rpm/vi-mcp.sh "$b/usr/bin/vi-mcp"
install -m 0755 deploy/rpm/vi-mcp-start "$b/usr/libexec/vi-mcp-start"
sed 's#^ExecStart=.*#ExecStart=/usr/libexec/vi-mcp-start#' deploy/debian/vi-mcp.service > "$b/usr/lib/systemd/system/vi-mcp.service"
chmod 0644 "$b/usr/lib/systemd/system/vi-mcp.service"
install -m 0644 README.md README.de.md AGENTS.md CHANGELOG.md "$b/usr/share/doc/vi-mcp/"
# docs/LOKAL* enthält Hostangaben und den Prüfer-Prompt und darf in kein Paket
find docs -maxdepth 1 -name "*.md" ! -name "LOKAL*" -exec install -m 0644 {} "$b/usr/share/doc/vi-mcp/docs/" \;
install -m 0755 hook/vi_hook.py "$b/usr/share/vi-mcp/hook/vi_hook.py"
install -m 0755 deploy/nach-installation.sh "$b/usr/share/vi-mcp/nach-installation.sh"
# Der Name des Bau-Rechners stünde sonst im Paket
rpmbuild -bb --quiet --define "_buildhost vi-mcp-build" --define "_topdir $bau/top" --define "vi_version $version" --define "vi_release $rev" --define "vi_baum $b" \
    ${RPM_PACKAGER:+--define "packager $RPM_PACKAGER"} deploy/rpm/vi-mcp.spec
cp "$bau"/top/RPMS/noarch/*.rpm dist/
echo "dist/vi-mcp-${version}-${rev}.noarch.rpm"
