# vi-mcp for Windows - runs from the MSI before its files are removed (deferred, as SYSTEM).
# Stops and removes the scheduled task, the venv, the PATH entry and VI_MCP_CONFIG. Data and configuration in %ProgramData%\vi-mcp stay
# (like `apt remove`); delete that folder by hand to remove them as well. Never fails the uninstall: problems are only logged.
param([Parameter(Mandatory = $true)][string]$InstallDir)
$ErrorActionPreference = "Continue"
$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd("\")  # the MSI passes "[INSTALLDIR]." (a trailing \ would escape the quote)
$Data = Join-Path $env:ProgramData "vi-mcp"
New-Item -ItemType Directory -Force -Path $Data | Out-Null
$Log = Join-Path $Data "install.log"
function Log([string]$m) { Add-Content -Path $Log -Value "$(Get-Date -Format s) $m" -Encoding UTF8 }
Log "vi-mcp uninstall: InstallDir=$InstallDir"
if (Get-ScheduledTask -TaskName "vi-mcp" -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName "vi-mcp" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "vi-mcp" -Confirm:$false
    Log "scheduled task vi-mcp removed"
}
foreach ($t in @(Get-ScheduledTask -TaskName "vi-p2p*" -ErrorAction SilentlyContinue)) {  # 0.54.0: network services
    Stop-ScheduledTask -TaskName $t.TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
    Log "scheduled task $($t.TaskName) removed"
}
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -like "$InstallDir\venv\*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item -Recurse -Force (Join-Path $InstallDir "venv") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $InstallDir "python") -ErrorAction SilentlyContinue  # private Python from the NuGet package
$path = [Environment]::GetEnvironmentVariable("Path", "Machine")
$new = ($path -split ";" | Where-Object { $_ -and $_ -ne $InstallDir }) -join ";"
if ($new -ne $path) { [Environment]::SetEnvironmentVariable("Path", $new, "Machine"); Log "PATH entry removed" }
[Environment]::SetEnvironmentVariable("VI_MCP_CONFIG", $null, "Machine")
Log "done; data kept in $Data"
exit 0
