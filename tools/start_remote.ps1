param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$camRoot = Split-Path -Parent $PSScriptRoot
$camPython = 'C:\Users\41116\AppData\Local\Programs\Python\Python312\python.exe'
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
$camArtifacts = Join-Path $camRoot 'artifacts'
[System.IO.Directory]::CreateDirectory($camArtifacts) | Out-Null
$state = (& $ts status --json | ConvertFrom-Json)
if ($state.BackendState -ne 'Running') { throw 'Please connect Tailscale first.' }
$configPath = Join-Path $camRoot 'gateway.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$wlan = Get-NetIPInterface -AddressFamily IPv4 -InterfaceAlias WLAN -ErrorAction SilentlyContinue | Select-Object -First 1
if ($wlan) { $config.interface_index = $wlan.InterfaceIndex; $config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8 }
$healthy = $false
try {
    $client = New-Object System.Net.WebClient
    $client.Proxy = $null
    $health = $client.DownloadString('http://127.0.0.1:18732/health') | ConvertFrom-Json
    $healthy = $health.gateway_ok -eq $true
} catch {} finally { if ($client) { $client.Dispose() } }
if (-not $healthy) {
    $gatewayScript = Join-Path $PSScriptRoot 'remote_gateway.py'
    $process = Start-Process -FilePath $camPython -ArgumentList @('-u',('"' + $gatewayScript + '"')) -WorkingDirectory $camRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $camArtifacts 'gateway.log') -RedirectStandardError (Join-Path $camArtifacts 'gateway.err.log') -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $camArtifacts 'gateway.pid')
}
& $ts serve --bg --http=8080 http://127.0.0.1:18732
if ($LASTEXITCODE -ne 0) { throw 'Tailscale Serve configuration failed.' }
$url = 'http://' + $state.Self.DNSName.TrimEnd('.') + ':8080/'
Write-Output $url
if ($OpenBrowser) { Start-Process $url }
