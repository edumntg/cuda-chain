# Join a plasmon network as a participant. Windows PowerShell.
#   .\join.ps1 http://192.168.1.20:7117 [machine-name]
param(
  [Parameter(Mandatory = $true)] [string] $Server,
  [string] $Name = $env:COMPUTERNAME
)
$ErrorActionPreference = "Stop"
$py = if ($env:PLASMON_PYTHON) { $env:PLASMON_PYTHON } else { "py" }

& $py -c "import plasmon" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "the plasmon engine is not installed. Install it with:"
  Write-Host "  $py -m pip install `"plasmon[engine] @ git+https://github.com/edumntg/plasmon.git`""
  exit 1
}

$who = & $py -m plasmon --json whoami | Out-String
if ($who -notmatch [regex]::Escape("`"server`": `"$Server`"")) {
  Write-Host "logging in to $Server (confirm the code in the browser)"
  & $py -m plasmon login --server $Server
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Write-Host "starting the trainer as $Name. Stop with Ctrl+C."
& $py -m plasmon trainer start --name $Name
