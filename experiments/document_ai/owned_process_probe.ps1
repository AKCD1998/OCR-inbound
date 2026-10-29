param(
    [Parameter(Mandatory=$true)][int]$RootProcessId,
    [Parameter(Mandatory=$true)][double]$RootCreationEpoch,
    [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference='Stop'
if ($env:COMPUTERNAME -ine 'SERVER') { throw 'HQ metadata only' }
$destination=[System.IO.Path]::GetFullPath($Output)
if (-not $destination.StartsWith('D:\OCR-Experiments\document-ai-20261028\',[System.StringComparison]::OrdinalIgnoreCase)) { throw 'New isolated metadata output required' }
if (Test-Path -LiteralPath $destination) { throw 'Preserve previous snapshot' }
$all=@(Get-CimInstance -ClassName Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CreationDate,WorkingSetSize,UserModeTime,KernelModeTime)
$root=@($all | Where-Object { $_.ProcessId -eq $RootProcessId })
if ($root.Count -ne 1) { throw 'Original supervisor is absent' }
function Epoch($date) { return ([DateTimeOffset]$date.ToUniversalTime()).ToUnixTimeMilliseconds()/1000.0 }
if ([Math]::Abs((Epoch $root[0].CreationDate)-$RootCreationEpoch) -gt 0.002) { throw 'Supervisor PID creation identity differs' }
$selected=New-Object 'System.Collections.Generic.HashSet[int]'
[void]$selected.Add($RootProcessId)
do {
    $added=$false
    foreach ($item in $all) {
        if ($selected.Contains([int]$item.ParentProcessId) -and -not $selected.Contains([int]$item.ProcessId)) {
            [void]$selected.Add([int]$item.ProcessId); $added=$true
        }
    }
} while ($added)
$rows=@()
foreach ($item in $all) {
    if (-not $selected.Contains([int]$item.ProcessId)) { continue }
    $rows+=@{process_id=[int]$item.ProcessId; parent_id=[int]$item.ParentProcessId; name=$item.Name;
        creation_epoch=(Epoch $item.CreationDate); working_set_bytes=[long]$item.WorkingSetSize;
        user_cpu_seconds=([double]$item.UserModeTime/10000000.0); kernel_cpu_seconds=([double]$item.KernelModeTime/10000000.0)}
}
$result=@{contract='document-ai-owned-process-metadata.v1';observed_utc=[DateTimeOffset]::UtcNow.ToString('o');
    supervisor_creation_identity_verified=$true;processes=$rows;processes_signalled=0;
    Python_started=$false;model_calls=0;source_image_decodes=0;raw_commands_recorded=$false}
$parent=[System.IO.Path]::GetDirectoryName($destination)
[void][System.IO.Directory]::CreateDirectory($parent)
[System.IO.File]::WriteAllText($destination,($result | ConvertTo-Json -Depth 8),[System.Text.UTF8Encoding]::new($false))
