# vi-mcp for Windows — runs from the MSI after the files are copied (deferred, as SYSTEM). Also usable by hand in an elevated shell:
#   powershell -ExecutionPolicy Bypass -File install.ps1 -InstallDir "C:\Program Files\vi-mcp" [-Server 1] [-Proxy http://proxy:3128]
# Steps: find Python >= 3.11 (else download the python.org installer, check its Authenticode signature, install for all users),
# create a venv with the PyPI packages, make `vi-mcp` callable, and — with -Server 1 — set up the server as scheduled task "vi-mcp".
# Everything is logged to %ProgramData%\vi-mcp\install.log; any failure ends with exit code 1, so the MSI rolls back.
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [string]$Server = "1",
    [string]$Proxy = "",
    [string]$Port = ""   # empty: keep the port of an existing configuration, 8765 for a new one
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd("\")  # the MSI passes "[INSTALLDIR]." (a trailing \ would escape the quote)
$Data = Join-Path $env:ProgramData "vi-mcp"
New-Item -ItemType Directory -Force -Path $Data | Out-Null
$Log = Join-Path $Data "install.log"
function Log([string]$m) { "$(Get-Date -Format s) $m" | Tee-Object -FilePath $Log -Append | Out-Host }

$PythonVersion = "3.13.9"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
$Packages = @("numpy>=1.26", "scikit-learn>=1.4", "cryptography>=41", "pyyaml>=6")

try {
    Log "vi-mcp install: InstallDir=$InstallDir Server=$Server Proxy=$(if ($Proxy) { 'set' } else { 'none' })"
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
    if (-not $py) {
        Log "no Python >= 3.11 (64-bit) found — downloading $PythonUrl"
        $setup = Join-Path $env:TEMP "python-$PythonVersion-amd64.exe"
        $iwr = @{ Uri = $PythonUrl; OutFile = $setup; UseBasicParsing = $true }
        if ($Proxy) { $iwr.Proxy = $Proxy }
        Invoke-WebRequest @iwr
        $sig = Get-AuthenticodeSignature $setup
        if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") {
            throw "Python installer signature not valid ($($sig.Status), $($sig.SignerCertificate.Subject)) — not executed"
        }
        Log "signature valid ($($sig.SignerCertificate.Subject)); installing for all users"
        $p = Start-Process -FilePath $setup -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0", "Include_launcher=1" -Wait -PassThru
        Remove-Item $setup -Force -ErrorAction SilentlyContinue
        if ($p.ExitCode -ne 0) { throw "Python installer ended with exit code $($p.ExitCode)" }
        $py = Find-Python
        if (-not $py) { throw "Python was installed but is not found in the registry" }
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
    & $vpy @pipArgs @Packages 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "pip install failed ($LASTEXITCODE) — see $Log" }
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
            @{ bind = "127.0.0.1"; port = $(if ($Port) { [int]$Port } else { 8765 }); db = (Join-Path $Data "vi.db") } | ConvertTo-Json |
                Set-Content -Path $cfg -Encoding utf8
            Log "created $cfg"
        }
        [Environment]::SetEnvironmentVariable("VI_MCP_CONFIG", $cfg, "Machine")
        $env:VI_MCP_CONFIG = $cfg
        if ($Port) {
            & $vpy -I -c "import sys; from vi_mcp import config; config.set_port(int(sys.argv[1]))" $Port
            if ($LASTEXITCODE -ne 0) { throw "could not set port $Port" }
        }
        $ServerPort = [int](& $vpy -I -c "from vi_mcp import config; print(config.load().port)")
        Log "server port: $ServerPort"
        $raw = Get-Content $cfg -Raw | ConvertFrom-Json
        if (-not $raw.instanzen) {
            # the server needs at least one instance; the token is stored for administrators only
            $out = & $vpy -I -m vi_mcp instance admin
            if ($LASTEXITCODE -ne 0) { throw "vi-mcp instance admin failed" }
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
        if (-not $up) { Log "WARNING: server did not answer /gesund within 30 s — see Task Scheduler, task vi-mcp, and $Data\server.log" }
    }
    $hint = if ($Server -eq "1") { "http://127.0.0.1:$ServerPort/mcp" } else { "https://<server>/vi-mcp/mcp" }
    Log "done. Next, in a new shell: vi-mcp setup --claude --hook --url $hint --token-file <file>  (local server, elevated shell: tokens are created)"
    exit 0
} catch {
    Log "FAILED: $($_.Exception.Message)"
    exit 1
}
