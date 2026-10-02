# Install the plasmon CLI binary from GitHub Releases. Windows, PowerShell 5.1 or newer.
#   In PowerShell:  irm https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.ps1 | iex
#   From cmd:       powershell -c "irm https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.ps1 | iex"
$ErrorActionPreference = "Stop"
$repo = "edumntg/plasmon"
$version = if ($env:PLASMON_VERSION) { $env:PLASMON_VERSION } else { "latest" }
$installDir = if ($env:PLASMON_INSTALL_DIR) { $env:PLASMON_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "plasmon\bin" }
$file = "plasmon-windows-x86_64.exe"
$base = if ($version -eq "latest") { "https://github.com/$repo/releases/latest/download" } else { "https://github.com/$repo/releases/download/$version" }

New-Item -ItemType Directory -Force -Path $installDir | Out-Null
$target = Join-Path $installDir "plasmon.exe"
Write-Host "downloading $file ($version)"
Invoke-WebRequest -Uri "$base/$file" -OutFile "$target.download"
Invoke-WebRequest -Uri "$base/$file.sha256" -OutFile "$target.sha256"
$expected = (Get-Content "$target.sha256").Split(" ")[0].ToLower()
$actual = (Get-FileHash "$target.download" -Algorithm SHA256).Hash.ToLower()
if ($expected -ne $actual) { Remove-Item "$target.download"; throw "checksum mismatch: expected $expected, got $actual" }
Move-Item -Force "$target.download" $target
Remove-Item "$target.sha256"
Write-Host "installed $target"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$installDir*") {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$installDir", "User")
  Write-Host "added $installDir to your PATH. Open a new terminal to use 'plasmon'."
}
& $target --version
Write-Host "next: py -m pip install `"plasmon[engine] @ git+https://github.com/$repo.git`"   (the engine: server and trainer)"
