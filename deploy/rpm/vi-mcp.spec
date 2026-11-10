%global __brp_mangle_shebangs %{nil}
%global __brp_python_bytecompile %{nil}
%global debug_package %{nil}

Name:           vi-mcp
Version:        %{vi_version}
Release:        %{vi_release}
Summary:        VI memory as an MCP server (Streamable HTTP, one process)
License:        AGPL-3.0-or-later
URL:            https://github.com/imoes/vi-mcp
BuildArch:      noarch
Requires:       python3 >= 3.11
Requires:       python3-numpy
Requires:       python3-scikit-learn
Requires:       python3-cryptography
Requires:       python3-pyyaml
Requires:       systemd
Recommends:     rb_libtorrent-python3
Requires(pre):  shadow-utils

%description
One server process with one shared memory for many AI sessions over MCP.

%install
cp -a %{vi_baum}/. %{buildroot}/

%pre
getent group vi-mcp >/dev/null || groupadd -r vi-mcp
getent passwd vi-mcp >/dev/null || useradd -r -g vi-mcp -d /var/lib/vi-mcp -M -s /sbin/nologin -c "vi-mcp" vi-mcp
getent group vi-p2p >/dev/null || groupadd -r vi-p2p
getent passwd vi-p2p >/dev/null || useradd -r -g vi-p2p -d /var/lib/vi-p2p -M -s /sbin/nologin -c "vi-mcp network service" vi-p2p
exit 0

%post
/usr/share/vi-mcp/nach-installation.sh system
if [ "$1" -eq 1 ]; then touch /var/lib/vi-mcp/.erstinstallation; fi
exit 0

%posttrans
if [ -e /var/lib/vi-mcp/.erstinstallation ]; then
    rm -f /var/lib/vi-mcp/.erstinstallation
    /usr/share/vi-mcp/nach-installation.sh menue
fi
exit 0

%preun
if [ "$1" -eq 0 ]; then
    systemctl disable --now vi-p2p.service >/dev/null 2>&1 || true
    systemctl disable --now vi-mcp.service >/dev/null 2>&1 || true
fi
exit 0

%postun
systemctl daemon-reload >/dev/null 2>&1 || true
if [ "$1" -ge 1 ]; then systemctl try-restart vi-mcp.service >/dev/null 2>&1 || true; fi
if [ "$1" -eq 0 ]; then echo "vi-mcp: data and configuration are kept: /var/lib/vi-mcp, /etc/vi-mcp, /var/lib/vi-p2p, /etc/vi-p2p"; fi
exit 0

%files
/usr/bin/vi-mcp
/usr/libexec/vi-mcp-start
/usr/lib/vi-mcp
/usr/lib/systemd/system/vi-mcp.service
/usr/lib/systemd/system/vi-p2p.service
/usr/share/doc/vi-mcp
/usr/share/vi-mcp
