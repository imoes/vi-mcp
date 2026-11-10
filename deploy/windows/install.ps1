# vi-mcp for Windows - runs from the MSI after the files are copied (deferred, as SYSTEM). Also usable by hand in an elevated shell:
#   powershell -ExecutionPolicy Bypass -File install.ps1 -InstallDir "C:\Program Files\vi-mcp" [-Server 1] [-Proxy http://proxy:3128]
# Steps: find Python >= 3.11 (else unpack the NuGet package of the PSF into INSTALLDIR\python, check SHA256 and Authenticode signature),
# create a venv with the PyPI packages, make `vi-mcp` callable, and - with -Server 1 - set up the server as scheduled task "vi-mcp".
# Everything is logged to %ProgramData%\vi-mcp\install.log; any failure ends with exit code 1, so the MSI rolls back.
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [string]$Server = "",  # empty: as in the previous installation, else 1
    [string]$Proxy = "",
    [string]$Port = "",  # empty: keep the port of an existing configuration, 8765 for a new one
    [string]$Embed = "0", # 1: own embedding service (llama.cpp + bge-m3) for the vectors, see `vi-mcp embed`
    # From the MSI: all options in ONE argument "server=1;port=;embed=;proxy=...". Windows PowerShell 5.1 drops empty arguments of -File
    # (-Port "" became -Port -Embed ..., the binding failed and the MSI ended with error 1722 - found in a Windows 11 test VM, 10.11.2026).
    [string]$Options = ""
)
foreach ($pair in ($Options -split ";")) {
    $k, $v = $pair -split "=", 2
    switch ($k.Trim().ToLower()) {
        "server" { if ($v) { $Server = $v } }
        "port" { $Port = "$v" }
        "embed" { if ($v) { $Embed = $v } }
        "proxy" { $Proxy = "$v" }
    }
}
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd("\")  # the MSI passes "[INSTALLDIR]." (a trailing \ would escape the quote)
$Data = Join-Path $env:ProgramData "vi-mcp"
New-Item -ItemType Directory -Force -Path $Data | Out-Null
$Log = Join-Path $Data "install.log"
# 0.34.0: server mode and proxy of the previous installation are remembered, so an update (e.g. from the setup dialog, which only asks
# for a proxy) keeps them: a client-only installation stays one, and an update behind a proxy reaches PyPI. Admins and SYSTEM only.
$Saved = Join-Path $Data "install-options.json"
$previous = $null
if (Test-Path $Saved) { try { $previous = Get-Content $Saved -Raw | ConvertFrom-Json } catch { $previous = $null } }
$fromPrevious = @()
if (-not $Server) { if ($previous -and $previous.server) { $Server = "$($previous.server)"; $fromPrevious += "server" } else { $Server = "1" } }
if (-not $Proxy -and $previous -and $previous.proxy) { $Proxy = "$($previous.proxy)"; $fromPrevious += "proxy" }
function Log([string]$m) { $line = "$(Get-Date -Format s) $m"; Add-Content -Path $Log -Value $line -Encoding UTF8; Write-Host $line }

# Runs the private Python. PowerShell 5.1 turns stderr of a native program into a terminating error under "Stop", so stderr is
# collected here and written to the log when the call fails (before 0.28.1 the reason of a failure was lost).
function Invoke-Py {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { $all = & $vpy -I @args 2>&1 } finally { $ErrorActionPreference = $old }
    $code = $LASTEXITCODE
    $err = @($all | Where-Object { $_ -is [Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
    $out = @($all | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
    if ($code -ne 0) { foreach ($l in $err) { Log "  python: $l" }; throw "python $($args -join ' ') failed (exit $code)" }
    return $out
}

# 0.34.0: runs a program, writes its stdout AND stderr to the log, and decides by its exit code only. Under "Stop" PowerShell 5.1 aborted
# at the first stderr line - pip's "WARNING: Retrying ..." ended an installation that pip itself would have completed (test VM, 10.11.2026).
function Invoke-Logged([string]$exe, [string[]]$arguments) {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { & $exe @arguments 2>&1 | ForEach-Object { Add-Content -Path $Log -Value "$_" -Encoding UTF8 } } finally { $ErrorActionPreference = $old }
    return $LASTEXITCODE
}

# Private Python from the official NuGet package of the Python Software Foundation (a zip, no installer): the python.org installer
# cannot run inside an MSI (exit 1618, "another installation is in progress" - found in a Windows 11 test VM, 10.11.2026).
$PythonVersion = "3.13.9"
$PythonUrl = "https://api.nuget.org/v3-flatcontainer/python/$PythonVersion/python.$PythonVersion.nupkg"
$PythonSha256 = "ea7541c98f77b6f344460b88db6e677573069979bcbf0ba18747cc2c125aba25"
$Packages = @("numpy>=1.26", "scikit-learn>=1.4", "cryptography>=41", "pyyaml>=6")

try {
    Log "vi-mcp install: InstallDir=$InstallDir Server=$Server Proxy=$(if ($Proxy) { 'set' } else { 'none' })$(if ($fromPrevious) { ' (from the previous installation: ' + ($fromPrevious -join ', ') + ')' })"
    if ($Proxy) {
        $env:HTTP_PROXY = $Proxy; $env:HTTPS_PROXY = $Proxy
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    function Test-Python([string]$exe) {
        if (-not $exe -or -not (Test-Path $exe)) { return $false }
        $ok = & $exe -c "import sys; print(int(sys.version_info >= (3, 11) and sys.maxsize > 2**32))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$ok".Trim() -eq "1")
    }
    function Find-Python {
        foreach ($v in "3.14", "3.13", "3.12", "3.11") {
            foreach ($root in "HKLM:\SOFTWARE\Python\PythonCore\$v\InstallPath", "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore\$v\InstallPath") {
                $p = (Get-ItemProperty -Path $root -ErrorAction SilentlyContinue).ExecutablePath
                if (Test-Python $p) { return $p }
            }
        }
        $c = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($c -and $c.Source -notlike "*WindowsApps*" -and (Test-Python $c.Source)) { return $c.Source }  # not the Store stub
        return $null
    }

    $py = Find-Python
    $private = Join-Path $InstallDir "python"
    if (-not $py -and (Test-Python (Join-Path $private "python.exe"))) { $py = Join-Path $private "python.exe" }  # from an earlier install
    if (-not $py) {
        Log "no Python >= 3.11 (64-bit) found - downloading $PythonUrl"
        $pkg = Join-Path $env:TEMP "python.$PythonVersion.zip"
        $iwr = @{ Uri = $PythonUrl; OutFile = $pkg; UseBasicParsing = $true }
        if ($Proxy) { $iwr.Proxy = $Proxy }
        Invoke-WebRequest @iwr
        $hash = (Get-FileHash -Path $pkg -Algorithm SHA256).Hash.ToLower()
        if ($hash -ne $PythonSha256) { Remove-Item $pkg -Force; throw "Python package SHA256 $hash does not match the pinned $PythonSha256 - not used" }
        $unz = Join-Path $env:TEMP "python.$PythonVersion"
        Remove-Item -Recurse -Force $unz -ErrorAction SilentlyContinue
        Expand-Archive -Path $pkg -DestinationPath $unz -Force
        Remove-Item -Recurse -Force $private -ErrorAction SilentlyContinue
        Move-Item -Path (Join-Path $unz "tools") -Destination $private
        Remove-Item -Recurse -Force $unz, $pkg -ErrorAction SilentlyContinue
        $sig = Get-AuthenticodeSignature (Join-Path $private "python.exe")
        if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") {
            Remove-Item -Recurse -Force $private
            throw "python.exe signature not valid ($($sig.Status), $($sig.SignerCertificate.Subject)) - removed"
        }
        Log "private Python $PythonVersion in $private (SHA256 and signature of the Python Software Foundation checked)"
        $py = Join-Path $private "python.exe"
        if (-not (Test-Python $py)) { throw "the private Python does not start" }
    }
    Log "Python: $py ($(& $py --version 2>&1))"

    $venv = Join-Path $InstallDir "venv"
    $vpy = Join-Path $venv "Scripts\python.exe"
    if (-not (Test-Path $vpy)) {
        Log "creating venv $venv"
        & $py -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "python -m venv failed ($LASTEXITCODE)" }
    }
    $pipArgs = @("-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--upgrade")
    if ($Proxy) { $pipArgs += @("--proxy", $Proxy) }
    Log "pip install $($Packages -join ' ')"
    $code = Invoke-Logged $vpy ($pipArgs + $Packages)
    if ($code -ne 0) { throw "pip install failed ($code) - see $Log" }
    # vi_mcp lives next to the venv: a .pth file puts the install directory on sys.path (also with python -I)
    $site = & $vpy -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
    Set-Content -Path (Join-Path $site "vi-mcp.pth") -Value $InstallDir -Encoding ascii
    & $vpy -I -c "import vi_mcp, sklearn, numpy, cryptography, yaml; print(vi_mcp.__version__)" | ForEach-Object { Log "vi_mcp $_ importable" }
    if ($LASTEXITCODE -ne 0) { throw "vi_mcp is not importable in the venv" }

    $path = [Environment]::GetEnvironmentVariable("Path", "Machine")
    if (($path -split ";") -notcontains $InstallDir) {
        [Environment]::SetEnvironmentVariable("Path", "$path;$InstallDir", "Machine")
        Log "added $InstallDir to the machine PATH"
    }

    if ($Server -eq "1") {
        # data only for SYSTEM and administrators: the database holds conversation histories, the config token hashes
        & icacls $Data /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
        $cfg = Join-Path $Data "config.json"
        if ($Port -and ($Port -notmatch '^\d+$' -or [int]$Port -lt 1024 -or [int]$Port -gt 65535)) { throw "PORT must be a number from 1024 to 65535" }
        if (-not (Test-Path $cfg)) {
            # UTF-8 without BOM: Set-Content -Encoding utf8 of PowerShell 5.1 writes a BOM, and json.loads refuses it
            # (Windows 11 test VM, 10.11.2026: "server port: 0", then "instance admin failed")
            $json = @{ bind = "127.0.0.1"; port = $(if ($Port) { [int]$Port } else { 8765 }); db = (Join-Path $Data "vi.db") } | ConvertTo-Json
            [IO.File]::WriteAllText($cfg, $json, (New-Object Text.UTF8Encoding($false)))
            Log "created $cfg"
        }
        [Environment]::SetEnvironmentVariable("VI_MCP_CONFIG", $cfg, "Machine")
        $env:VI_MCP_CONFIG = $cfg
        if ($Port) {
            Invoke-Py -c "import sys; from vi_mcp import config; config.set_port(int(sys.argv[1]))" $Port | Out-Null
        }
        $ServerPort = [int](Invoke-Py -c "from vi_mcp import config; print(config.load().port)" | Select-Object -Last 1)
        Log "server port: $ServerPort"
        $raw = Get-Content $cfg -Raw | ConvertFrom-Json
        if (-not $raw.instanzen) {
            # the server needs at least one instance; the token is stored for administrators only
            $out = Invoke-Py -m vi_mcp instance admin
            Set-Content -Path (Join-Path $Data "token-admin") -Value ($out | Select-Object -Last 1) -Encoding ascii
            Log "created instance admin (token in $Data\token-admin)"
        }
        $action = New-ScheduledTaskAction -Execute (Join-Path $InstallDir "vi-mcp-server.cmd") -WorkingDirectory $Data
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $principal = New-ScheduledTaskPrincipal -UserId "S-1-5-18" -LogonType ServiceAccount -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -StartWhenAvailable
        if (Get-ScheduledTask -TaskName "vi-mcp" -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName "vi-mcp" -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName "vi-mcp" -Confirm:$false
        }
        Register-ScheduledTask -TaskName "vi-mcp" -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
            -Description "vi-mcp memory server (MCP over HTTP, 127.0.0.1:$ServerPort)" | Out-Null
        Start-ScheduledTask -TaskName "vi-mcp"
        $up = $false
        foreach ($i in 1..30) {
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$ServerPort/gesund" -UseBasicParsing -TimeoutSec 2
                if ($r.Content -like "ok vi-mcp*") { $up = $true; Log "server: $($r.Content.Trim())"; break }
            } catch { Start-Sleep -Seconds 1 }
        }
        if (-not $up) { Log "WARNING: server did not answer /gesund within 30 s - see Task Scheduler, task vi-mcp, and $Data\server.log" }
        if ($Embed -eq "1") {
            Log "setting up the embedding service (vi-mcp embed setup; downloads llama.cpp and bge-m3, ~470 MB)"
            $code = Invoke-Logged $vpy @("-I", "-m", "vi_mcp", "embed", "setup")
            if ($code -ne 0) { Log "WARNING: vi-mcp embed setup failed - the server runs without vectors; see $Log" }
        }
    }
    $json = @{ server = $Server; proxy = $Proxy } | ConvertTo-Json
    [IO.File]::WriteAllText($Saved, $json, (New-Object Text.UTF8Encoding($false)))
    & icacls $Saved /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" | Out-Null
    $hint = if ($Server -eq "1") { "http://127.0.0.1:$ServerPort/mcp" } else { "https://<server>/vi-mcp/mcp" }
    Log "done. Next, in a new shell: vi-mcp setup --claude --hook --url $hint --token-file <file>  (local server, elevated shell: tokens are created)"
    exit 0
} catch {
    Log "FAILED: $($_.Exception.Message)"
    exit 1
}
