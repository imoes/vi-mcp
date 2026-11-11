#!/usr/bin/env bash
# Builds dist/vi-mcp-<version>-x64.msi from the working tree with wixl (msitools) in a Fedora container — no Windows needed.
# The MSI copies vi_mcp, the hook and the scripts to %ProgramFiles%\vi-mcp and then runs install.ps1 (Python, venv, PyPI packages,
# optionally the server as scheduled task). Public properties: SERVER=1|0 (default 1), PROXY=http://host:port (default none).
# PORT=9000 sets the server port (default: keep an existing one, 8765 for a new installation).
# EMBED=1 also sets up the own embedding service (vi-mcp embed setup). WIKI=0: do not join the public wiki network vi-wiki.org (0.54.0;
# default: join it on a new installation, as the Linux packages do).
#   msiexec /i vi-mcp-<version>-x64.msi [SERVER=0] [PORT=9000] [EMBED=1] [WIKI=0] [PROXY=http://proxy:3128] /l*v install.log
set -euo pipefail
cd "$(dirname "$0")/../.."
version=$(python3 -c "import vi_mcp; print(vi_mcp.__version__)")
out="dist/vi-mcp-${version}-x64.msi"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p dist "$work/src/vi_mcp" "$work/src/hook"
cp vi_mcp/*.py "$work/src/vi_mcp/"
cp hook/vi_hook.py "$work/src/hook/"
cp deploy/windows/install.ps1 deploy/windows/uninstall.ps1 deploy/windows/vi-mcp.cmd deploy/windows/vi-mcp-server.cmd deploy/windows/vi-p2p.cmd LICENSE "$work/src/"
python3 - "$version" "$work" <<'PY'
import sys, uuid
from pathlib import Path
version, work = sys.argv[1], Path(sys.argv[2])
src = work / "src"
NS = uuid.UUID("5b7c3f0e-2b8a-4f3c-9d4e-7a1c6e2f9b10")  # fixed: same file path → same component GUID in every version


def comp(rel: str, i: int) -> str:
    return (f'<Component Id="C{i}" Guid="{uuid.uuid5(NS, rel)}" Win64="yes">'
            f'<File Id="F{i}" Source="src/{rel}" KeyPath="yes"/></Component>')


top, mods, hooks, refs, i = [], [], [], [], 0
for p in sorted(src.rglob("*")):
    if p.is_file():
        rel = p.relative_to(src).as_posix()
        i += 1
        (mods if rel.startswith("vi_mcp/") else hooks if rel.startswith("hook/") else top).append(comp(rel, i))
        refs.append(f'<ComponentRef Id="C{i}"/>')
ps = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File"
wxs = f'''<?xml version="1.0" encoding="utf-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="vi-mcp {version}" Language="1033" Version="{version}" Manufacturer="vi-mcp (github.com/imoes/vi-mcp)"
           UpgradeCode="8f3e1c2a-6b4d-4e7f-9a1b-2c3d4e5f6a7b">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine" Description="vi-mcp — shared memory for AI sessions (MCP)"/>
    <MajorUpgrade DowngradeErrorMessage="A newer vi-mcp is already installed."/>
    <Media Id="1" Cabinet="vi.cab" EmbedCab="yes"/>
    <Property Id="PWSH" Value="powershell.exe"/>
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFiles64Folder">
        <Directory Id="INSTALLDIR" Name="vi-mcp">
          {"".join(top)}
          <Directory Id="D_VI" Name="vi_mcp">{"".join(mods)}</Directory>
          <Directory Id="D_HOOK" Name="hook">{"".join(hooks)}</Directory>
        </Directory>
      </Directory>
    </Directory>
    <Feature Id="Main" Level="1">{"".join(refs)}</Feature>
    <CustomAction Id="SetPwsh" Property="PWSH" Value="[System64Folder]WindowsPowerShell\\v1.0\\powershell.exe"/>
    <CustomAction Id="RunInstall" Property="PWSH" Execute="deferred" Impersonate="no" Return="check"
      ExeCommand='{ps} "[INSTALLDIR]install.ps1" -InstallDir "[INSTALLDIR]." -Options "server=[SERVER];port=[PORT];embed=[EMBED];wiki=[WIKI];proxy=[PROXY]"'/>
    <CustomAction Id="RunUninstall" Property="PWSH" Execute="deferred" Impersonate="no" Return="ignore"
      ExeCommand='{ps} "[INSTALLDIR]uninstall.ps1" -InstallDir "[INSTALLDIR]."'/>
    <InstallExecuteSequence>
      <Custom Action="SetPwsh" Before="InstallInitialize"/>
      <Custom Action="RunUninstall" Before="RemoveFiles">REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE</Custom>
      <Custom Action="RunInstall" After="InstallFiles">NOT REMOVE~="ALL"</Custom>
    </InstallExecuteSequence>
  </Product>
</Wix>
'''
(work / "vi-mcp.wxs").write_text(wxs)
PY
image=vi-mcp-wixl:local
if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker run --name vi-wixl-setup --network host -e http_proxy -e https_proxy -e no_proxy fedora:43 bash -c "dnf -y -q install msitools >/dev/null"
    docker commit vi-wixl-setup "$image" >/dev/null && docker rm vi-wixl-setup >/dev/null
fi
# wixl ignores Property/@Secure: without SERVER, PORT and PROXY in SecureCustomProperties an elevated install would drop them silently,
# so patch-msi.sh sets it after the build (SQL UPDATE with msibuild) and checks it
cp deploy/windows/patch-msi.sh deploy/windows/ui.sql "$work/"
docker run --rm -v "$work":/w -w /w "$image" sh -c "wixl -a x64 -o vi-mcp.msi vi-mcp.wxs 1>&2 && sh patch-msi.sh vi-mcp.msi"

cp "$work/vi-mcp.msi" "$out"
echo "$out"
