<#
.SYNOPSIS
Preview or refresh LAN forwarding for Docker ports in a WSL NAT distribution.
.EXAMPLE
.\scripts\share-wsl-containers.ps1 -Distro Ubuntu
.EXAMPLE
.\scripts\share-wsl-containers.ps1 -Distro Ubuntu -Apply
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$Distro,
    [switch]$Apply,
    [switch]$Remove,
    [ValidateRange(1,65535)][int[]]$Ports,
    [string]$PortList
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($PortList) {
    if ($PortList -notmatch '^\d+(,\d+)*$') { throw 'PortList must contain comma-separated TCP ports.' }
    $Ports = @($PortList.Split(',') | ForEach-Object {
        $number = [int]$_
        if ($number -lt 1 -or $number -gt 65535) { throw 'Ports must be between 1 and 65535.' }
        $number
    })
}
$rulePrefix = 'Toolbox-WSL-' + ([BitConverter]::ToString(
    [Text.Encoding]::UTF8.GetBytes($Distro))).Replace('-', '') + '-'

if ($Apply) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run PowerShell as Administrator to apply forwarding changes.'
    }
}
$managed = @(Get-NetFirewallRule -Name "$rulePrefix*" -ErrorAction SilentlyContinue)
if ($Remove) {
    foreach ($rule in $managed) {
        $port = [int]$rule.Name.Substring($rulePrefix.Length)
        Write-Host "Remove managed forwarding for TCP $port"
        if ($Apply) {
            & netsh.exe interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port
            if ($LASTEXITCODE) { throw "Failed to remove forwarding for $port" }
            $rule | Remove-NetFirewallRule
        }
    }
    if (-not $Apply) { Write-Host 'Preview only. Add -Apply to remove these rules.' }
    return
}

# Route selection avoids accidentally choosing a Docker bridge address from hostname -I.
$routeText = & wsl.exe -d $Distro -- ip -j -4 route get 192.0.2.1
if ($LASTEXITCODE) { throw 'Cannot determine the WSL address.' }
$routes = @((($routeText -join "`n") | ConvertFrom-Json))
$wslAddress = [string]$routes[0].prefsrc
$parsedAddress = $null
if (-not [Net.IPAddress]::TryParse($wslAddress, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    [Net.IPAddress]::IsLoopback($parsedAddress)) { throw 'No usable WSL IPv4 address found.' }

$ids = @(& wsl.exe -d $Distro -- docker ps -q)
if ($LASTEXITCODE) { throw 'Cannot list containers. Check Docker access in the selected WSL distribution.' }
$discovered = @()
foreach ($id in $ids) {
    if (-not $id.Trim()) { continue }
    $raw = & wsl.exe -d $Distro -- docker inspect --format '{{json .NetworkSettings.Ports}}' $id.Trim()
    if ($LASTEXITCODE) { throw "Cannot inspect container $id" }
    $bindings = ($raw -join "`n") | ConvertFrom-Json
    if ($null -eq $bindings) { continue }
    foreach ($property in $bindings.PSObject.Properties) {
        if ($property.Name -notmatch '/tcp$') { continue }
        foreach ($binding in $property.Value) {
            if ($binding.HostIp -eq '0.0.0.0' -or $binding.HostIp -eq $wslAddress) {
                $discovered += [int]$binding.HostPort
            }
        }
    }
}
$selected = @($discovered | Sort-Object -Unique | Where-Object { -not $Ports -or $_ -in $Ports })
if (-not $selected.Count) { throw 'No matching published IPv4 TCP ports. Start containers and publish their ports first.' }

# Preflight the entire selection before changing anything. Preserve unrelated proxies.
$proxyKey = $null
try {
    $proxyKey = Get-Item -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Services\PortProxy\v4tov4\tcp' -ErrorAction Stop
} catch [System.Management.Automation.ItemNotFoundException] {
    # A machine with no portproxy configuration has no registry key yet.
}
foreach ($port in $selected) {
    $name = "$rulePrefix$port"
    # RegistryKey.GetValue returns null for an absent value; the PowerShell
    # property-value cmdlet can throw even with SilentlyContinue in this case.
    $existing = if ($null -ne $proxyKey) { $proxyKey.GetValue("0.0.0.0/$port", $null) } else { $null }
    if ($existing -and $name -notin $managed.Name) {
        throw "Port $port already has an unmanaged portproxy rule. Review netsh interface portproxy show all first."
    }
}
foreach ($port in $selected) {
    $name = "$rulePrefix$port"
    Write-Host "Windows TCP $port -> ${wslAddress}:$port (firewall: LocalSubnet)"
    if ($Apply) {
        # Create the ownership marker first so an interrupted run can be retried or removed.
        if ($name -notin $managed.Name) {
            New-NetFirewallRule -Name $name -DisplayName "Toolbox WSL $Distro TCP $port" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -RemoteAddress LocalSubnet | Out-Null
        }
        & netsh.exe interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$wslAddress connectport=$port
        if ($LASTEXITCODE) { throw "Failed to forward port $port. Rerun to repair or use -Remove -Apply." }
    }
}
Write-Host 'Connect using your Windows Ethernet/Wi-Fi IPv4 address and the listed ports (ipconfig).'
Write-Host 'Rerun after WSL restarts or published ports change. Old rules remain until -Remove -Apply.'
if (-not $Apply) { Write-Host 'Preview only. Run in Administrator PowerShell with -Apply to configure access.' }
