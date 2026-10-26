param(
    [ValidateSet('readiness','run','analyze','results','cleanup')][string]$Mode = 'readiness',
    [ValidateSet('successful_login','failed_login','process_creation','parent_child',
        'file_activity','powershell_activity','service_activity','scheduled_task',
        'registry_activity','account_activity','process_chain')][string]$Scenario = 'process_creation',
    [ValidatePattern('^[0-9a-f]{32}$')][string]$RunId
)
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'ToolboxTraining\Runs'
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
$logs = @('Security','System','Microsoft-Windows-Sysmon/Operational','Microsoft-Windows-PowerShell/Operational')
if ($Mode -eq 'readiness') {
    Write-Output "Local computer: $env:COMPUTERNAME; user: $env:USERNAME; elevated: $admin"
    foreach ($log in $logs) {
        try {
            $info = Get-WinEvent -ListLog $log
            Write-Output "$log : enabled=$($info.IsEnabled), records=$($info.RecordCount)"
        } catch { Write-Output "$log : unavailable or access denied" }
    }
    Write-Output 'Audit policy (read-only check):'
    & auditpol.exe /get /category:*
    Write-Output 'Enable the required audit policies, PowerShell script-block logging, and Sysmon rules before assessment.'
    Write-Output 'Available logs do not prove the required events are being collected. Validate each scenario first.'
    exit 0
}
if (-not $RunId) { throw 'A run ID is required.' }
$runFolder = [IO.Path]::GetFullPath((Join-Path $root $RunId))
if (-not $runFolder.StartsWith([IO.Path]::GetFullPath($root) + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Run directory is outside the exercise root.'
}
$recordPath = Join-Path $runFolder 'run.json'
$marker = 'ToolboxTraining:' + $RunId
$account = 'tb' + $RunId.Substring(0,18)
$objectName = 'ToolboxTraining_' + $RunId
$registry = 'HKCU:\Software\ToolboxTraining\' + $RunId
$adminScenarios = @('successful_login','failed_login','service_activity','scheduled_task','account_activity')
function Save-Record { $script:record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $recordPath -Encoding UTF8 }
function Invoke-LabProcess([string]$File, [string]$Arguments) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(15000)) { $process.Kill(); throw 'Lab process timed out.' }
    if ($process.ExitCode -ne 0) { throw "Lab process exited with $($process.ExitCode)" }
}
if ($Mode -eq 'run') {
    if ($Scenario -in $adminScenarios -and -not $admin) { throw 'Run the toolbox as Administrator for this scenario.' }
    if (Test-Path -LiteralPath $runFolder) { throw 'Run ID already exists.' }
    New-Item -ItemType Directory -Path $runFolder | Out-Null
    $record = [ordered]@{RunId=$RunId; Scenario=$Scenario; Host=$env:COMPUTERNAME; User=$env:USERNAME;
        StartedUtc=[DateTime]::UtcNow.ToString('o'); FinishedUtc=$null; Status='started';
        Marker=$marker; Account=$account; ObjectName=$objectName; Folder=$runFolder; Cleanup='pending'}
    Save-Record
    Write-Output "Run ID: $RunId; local scenario: $Scenario"
    try {
        switch ($Scenario) {
            'process_creation' { Invoke-LabProcess "$env:SystemRoot\System32\cmd.exe" "/d /c echo $marker" }
            'parent_child' { Invoke-LabProcess "$env:SystemRoot\System32\cmd.exe" '/d /c whoami.exe' }
            'file_activity' {
                $file = Join-Path $runFolder 'activity.txt'
                Set-Content -LiteralPath $file -Value $marker
                Add-Content -LiteralPath $file -Value 'modified'
                Remove-Item -LiteralPath $file
            }
            'powershell_activity' {
                $file = Join-Path $runFolder 'exercise.ps1'
                "Set-Content -LiteralPath (Join-Path `$PSScriptRoot 'marker.txt') -Value '$marker'" | Set-Content -LiteralPath $file
                Invoke-LabProcess "$PSHOME\powershell.exe" "-NoProfile -NonInteractive -File `"$file`""
            }
            'process_chain' {
                $file = Join-Path $runFolder 'exercise.ps1'
                "& `$env:ComSpec /d /c whoami.exe | Set-Content -LiteralPath (Join-Path `$PSScriptRoot 'marker.txt')" | Set-Content -LiteralPath $file
                Invoke-LabProcess "$PSHOME\powershell.exe" "-NoProfile -NonInteractive -File `"$file`""
            }
            'registry_activity' {
                New-Item -Path $registry -Force | Out-Null
                New-ItemProperty -Path $registry -Name 'Exercise' -Value 1 -PropertyType DWord | Out-Null
                Set-ItemProperty -Path $registry -Name 'Exercise' -Value 2
            }
            'scheduled_task' {
                $file = Join-Path $runFolder 'exercise.ps1'
                "Set-Content -LiteralPath (Join-Path `$PSScriptRoot 'marker.txt') -Value '$marker'" | Set-Content -LiteralPath $file
                $action = New-ScheduledTaskAction -Execute "$PSHOME\powershell.exe" -Argument "-NoProfile -NonInteractive -File `"$file`""
                $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive
                Register-ScheduledTask -TaskName $objectName -Action $action -Principal $principal -Description $marker | Out-Null
                Start-ScheduledTask -TaskName $objectName
                $deadline = (Get-Date).AddSeconds(15)
                while (-not (Test-Path -LiteralPath (Join-Path $runFolder 'marker.txt')) -and (Get-Date) -lt $deadline) {
                    Start-Sleep -Milliseconds 250
                }
                if (-not (Test-Path -LiteralPath (Join-Path $runFolder 'marker.txt'))) { throw 'Task registered but marker was not observed.' }
            }
            'service_activity' {
                $binary = Join-Path $runFolder 'LabService.exe'
                $escaped = (Join-Path $runFolder 'marker.txt').Replace('\','\\').Replace('"','\"')
                $source = @"
using System; using System.ServiceProcess; using System.IO;
public class LabService : ServiceBase {
 public LabService() { ServiceName = "$objectName"; }
 protected override void OnStart(string[] args) { File.WriteAllText("$escaped", "$marker"); }
 public static void Main() { ServiceBase.Run(new LabService()); }
}
"@
                Add-Type -TypeDefinition $source -ReferencedAssemblies System.ServiceProcess -OutputAssembly $binary -OutputType WindowsApplication
                New-Service -Name $objectName -BinaryPathName ('"' + $binary + '"') -Description $marker -StartupType Manual | Out-Null
                Start-Service -Name $objectName
                Stop-Service -Name $objectName
            }
            { $_ -in @('successful_login','failed_login','account_activity') } {
                $password = 'Aa1!' + [Guid]::NewGuid().ToString('N')
                New-LocalUser -Name $account -Password (ConvertTo-SecureString $password -AsPlainText -Force) -Description $marker | Out-Null
                if ($Scenario -eq 'account_activity') {
                    Disable-LocalUser -Name $account
                    Enable-LocalUser -Name $account
                } else {
                    Add-Type @'
using System; using System.Runtime.InteropServices;
public static class LabLogon {
 [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
 public static extern bool LogonUser(string user, string domain, string password, int type, int provider, out IntPtr token);
 [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
}
'@
                    $token = [IntPtr]::Zero
                    $supplied = if ($Scenario -eq 'failed_login') { 'Wrong!' + [Guid]::NewGuid() } else { $password }
                    $ok = [LabLogon]::LogonUser($account, $env:COMPUTERNAME, $supplied, 2, 0, [ref]$token)
                    $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
                    if ($token -ne [IntPtr]::Zero) { [LabLogon]::CloseHandle($token) | Out-Null }
                    if ($Scenario -eq 'successful_login' -and -not $ok) { throw "Logon failed: Windows error $errorCode" }
                    if ($Scenario -eq 'failed_login' -and ($ok -or $errorCode -ne 1326)) { throw "Expected invalid credentials; got success=$ok error=$errorCode" }
                    $record['LogonType'] = 2
                    $record['AuthenticationSucceeded'] = $ok
                    $record['AuthenticationError'] = $errorCode
                }
                $password = $null; $supplied = $null
            }
        }
        $record.Status = 'executed'
    } catch { $record.Status = 'failed'; $record['Error'] = $_.Exception.Message; throw }
    finally {
        $record.FinishedUtc = [DateTime]::UtcNow.ToString('o'); Save-Record
        Write-Output "Instructor record: $recordPath"
        Write-Output 'Execution status is separate from event collection and analyst assessment. Use Analyze Local Logs, then Clean Up.'
    }
    exit 0
}
if (-not (Test-Path -LiteralPath $recordPath)) { throw 'Run record not found.' }
$record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
if ($record.RunId -ne $RunId -or $record.Scenario -ne $Scenario -or $record.Host -ne $env:COMPUTERNAME) { throw 'Run record does not match this host/scenario.' }
if ($Mode -eq 'results') { $record | ConvertTo-Json -Depth 8; exit 0 }
if ($Mode -eq 'cleanup') {
    if ($Scenario -in $adminScenarios -and -not $admin) { throw 'Cleanup requires Administrator for this scenario.' }
    if ($Scenario -eq 'scheduled_task') {
        $task = Get-ScheduledTask -TaskName $objectName -ErrorAction SilentlyContinue
        if ($task) {
            if ($task.Description -ne $marker) { throw 'Task ownership mismatch.' }
            Stop-ScheduledTask -TaskName $objectName
            Unregister-ScheduledTask -TaskName $objectName -Confirm:$false
        }
    }
    if ($Scenario -eq 'service_activity') {
        $service = Get-CimInstance Win32_Service -Filter "Name='$objectName'"
        if ($service) {
            if ($service.Description -ne $marker) { throw 'Service ownership mismatch.' }
            Stop-Service -Name $objectName -ErrorAction Stop
            & sc.exe delete $objectName
            if ($LASTEXITCODE -ne 0) { throw 'Service removal failed.' }
        }
    }
    if ($Scenario -in @('successful_login','failed_login','account_activity')) {
        $user = Get-LocalUser -Name $account -ErrorAction SilentlyContinue
        if ($user) {
            if ($user.Description -ne $marker) { throw 'Account ownership mismatch.' }
            Remove-LocalUser -Name $account
        }
    }
    if (Test-Path -LiteralPath $registry) {
        Remove-ItemProperty -LiteralPath $registry -Name 'Exercise' -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $registry
    }
    foreach ($name in @('activity.txt','marker.txt','exercise.ps1','LabService.exe')) {
        $file = Join-Path $runFolder $name
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
    }
    $record.Cleanup = [DateTime]::UtcNow.ToString('o'); Save-Record
    Write-Output 'Exercise artifacts removed. Run records, evidence exports, and Windows event logs were preserved.'
    exit 0
}
$ids = switch ($Scenario) {
    'successful_login' { @(4624) }; 'failed_login' { @(4625) }
    'file_activity' { @(11,23,26,4663) }; 'powershell_activity' { @(4104,4688,1) }
    'service_activity' { @(4697,7045,7036,1) }; 'scheduled_task' { @(4698,4699,4702,1,4688) }
    'registry_activity' { @(12,13,14,4657) }; 'account_activity' { @(4720,4722,4725) }
    default { @(1,4688) }
}
$start = ([DateTime]::Parse($record.StartedUtc)).AddSeconds(-2)
$end = if ($record.FinishedUtc) { ([DateTime]::Parse($record.FinishedUtc)).AddSeconds(5) } else { Get-Date }
$evidence = @(); $errors = @()
foreach ($log in $logs) {
    try {
        $events = Get-WinEvent -FilterHashtable @{LogName=$log; StartTime=$start; EndTime=$end; Id=$ids} -MaxEvents 1000
        foreach ($event in $events) {
            $xml = $event.ToXml()
            $matched = $xml.Contains($RunId) -or $xml.Contains($account)
            $evidence += [pscustomobject]@{TimeUtc=$event.TimeCreated.ToUniversalTime().ToString('o');
                Log=$log; Provider=$event.ProviderName; Id=$event.Id; RecordId=$event.RecordId;
                ArtifactMatch=$matched; Message=$event.Message; Xml=$xml}
        }
        if (@($events).Count -eq 1000) { $errors += "$log : result limit reached; review the log directly for additional events" }
    } catch { $errors += "$log : $($_.Exception.Message)" }
}
$report = [ordered]@{RunId=$RunId; Scenario=$Scenario; ExecutionStatus=$record.Status;
    CandidateEvents=$evidence.Count; ArtifactMatches=@($evidence | Where-Object ArtifactMatch).Count;
    CollectionNotes=$errors; Events=$evidence}
$reportPath = Join-Path $runFolder 'evidence.json'
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Output 'Time-window candidates are not proof of correlation or an analyst score. Match account, process ancestry, paths, and timestamps.'
$evidence | Select-Object TimeUtc,Log,Id,RecordId,ArtifactMatch,Message | Format-List | Out-String -Width 180 | Write-Output
$errors | Write-Output
Write-Output "Candidates: $($evidence.Count); evidence export: $reportPath"
