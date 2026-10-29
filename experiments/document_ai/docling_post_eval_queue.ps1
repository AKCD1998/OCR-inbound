param([string]$Manifest, [string]$ManifestSha256, [switch]$SelfTest)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Test-NativeCompletion($Task, $Result, $Expected) {
    if ($Task.state -eq 4 -or $Task.running_instances -gt 0) { return 'WAIT' }
    if ($Task.state -ne 3 -or $Task.last_task_result -ne 0) { return 'FAIL' }
    if ($null -eq $Result) { return 'FAIL' }
    if ($Result.status -ne 'COMPLETE' -or $null -ne $Result.failure -or
        $Result.complete_full_inventory -isnot [bool] -or -not $Result.complete_full_inventory -or
        $Result.cleanup.confirmed_all_known_owned_exited -isnot [bool] -or -not $Result.cleanup.confirmed_all_known_owned_exited -or
        $Result.shared_lock_released_after_owned_closure -isnot [bool] -or -not $Result.shared_lock_released_after_owned_closure -or
        $Result.config.sha256 -ne $Expected.native_config.sha256 -or
        $Result.full_parent_plan.sha256 -ne $Expected.full_parent_plan.sha256) { return 'FAIL' }
    foreach ($key in @('actual_layout_pages', 'actual_table_stage_pages')) {
        $values = @($Result.$key)
        if ($values.Count -ne 484) { return 'FAIL' }
        for ($i=0; $i -lt 484; $i++) {
            if (($values[$i] -isnot [int] -and $values[$i] -isnot [long]) -or $values[$i] -ne ($i+1)) { return 'FAIL' }
        }
    }
    if (@($Result.fresh_layout_pages).Count -ne $Expected.expected_fresh_layout_pages -or
        @($Result.retained_layout_pages).Count -ne $Expected.expected_retained_layout_pages) { return 'FAIL' }
    $union = @(@($Result.fresh_layout_pages)+@($Result.retained_layout_pages) | Sort-Object)
    if ($union.Count -ne 484) { return 'FAIL' }
    for ($i=0; $i -lt 484; $i++) {
        if (($union[$i] -isnot [int] -and $union[$i] -isnot [long]) -or $union[$i] -ne ($i+1)) { return 'FAIL' }
    }
    if ($null -ne $Expected.PSObject.Properties['expected_retained_table_pages']) {
        if ($null -eq $Result.PSObject.Properties['fresh_table_pages'] -or
            $null -eq $Result.PSObject.Properties['retained_table_pages'] -or
            @($Result.fresh_table_pages).Count -ne $Expected.expected_fresh_table_pages -or
            @($Result.retained_table_pages).Count -ne $Expected.expected_retained_table_pages) { return 'FAIL' }
        $tableUnion = @(@($Result.fresh_table_pages)+@($Result.retained_table_pages) | Sort-Object)
        if ($tableUnion.Count -ne 484) { return 'FAIL' }
        for ($i=0; $i -lt 484; $i++) {
            if (($tableUnion[$i] -isnot [int] -and $tableUnion[$i] -isnot [long]) -or $tableUnion[$i] -ne ($i+1)) { return 'FAIL' }
        }
    }
    if (@($Result.resources).Count -ne $Expected.expected_native_stages) { return 'FAIL' }
    foreach ($resource in $Result.resources) {
        if ($resource.actual_exit_code -ne 0 -or $null -ne $resource.failure -or $null -ne $resource.stop_reason -or
            $resource.cleanup.confirmed_all_known_owned_exited -isnot [bool] -or -not $resource.cleanup.confirmed_all_known_owned_exited) { return 'FAIL' }
    }
    return 'READY'
}

function Test-PostCompletion($Result, $Score) {
    if ($null -eq $Result -or $null -eq $Result.PSObject.Properties['status'] -or $Result.status -ne 'COMPLETE') { return 'FAIL' }
    if ($null -ne $Result.failure -or $Result.endpoint_score_status -ne 'COMPLETE' -or
        -not $Result.cleanup.confirmed_all_known_owned_exited -or -not $Result.shared_lock_released_after_owned_closure -or
        @($Result.resources).Count -ne 3) { return 'FAIL' }
    $names = @($Result.resources | ForEach-Object {$_.stage})
    if (($names -join ',') -ne 'control,candidate,paired_score') { return 'FAIL' }
    foreach ($resource in $Result.resources) {
        if ($resource.actual_exit_code -ne 0 -or $null -ne $resource.failure -or $null -ne $resource.stop_reason -or
            -not $resource.child_started -or -not $resource.cleanup.confirmed_all_known_owned_exited) { return 'FAIL' }
    }
    if ($null -eq $Score -or $Score.status -ne 'COMPLETE' -or $Score.scope -ne 'FULL484_FIXED585' -or
        $Score.actual_scorer_invocations -ne 2 -or -not $Score.writer_readback_verified -or
        $Score.before_exact -ne 323 -or $Score.product_present_denominator -ne 585) { return 'FAIL' }
    return 'COMPLETE'
}

if ($SelfTest) {
    # Pure synthetic gate tests: no Task Scheduler, locks, files, Python or models.
    $expected = [pscustomobject]@{native_config=@{sha256=('a'*64)};full_parent_plan=@{sha256=('b'*64)};expected_native_stages=16;expected_fresh_layout_pages=484;expected_retained_layout_pages=0}
    $ready = [pscustomobject]@{state=3;last_task_result=0;running_instances=0}
    $result = [pscustomobject]@{status='COMPLETE';failure=$null;complete_full_inventory=$true;
        cleanup=@{confirmed_all_known_owned_exited=$true};shared_lock_released_after_owned_closure=$true;
        config=@{sha256=('a'*64)};full_parent_plan=@{sha256=('b'*64)};
        actual_layout_pages=@(1..484);actual_table_stage_pages=@(1..484);fresh_layout_pages=@(1..484);retained_layout_pages=@();
        resources=@(1..16 | ForEach-Object {[pscustomobject]@{actual_exit_code=0;failure=$null;stop_reason=$null;cleanup=@{confirmed_all_known_owned_exited=$true}}})}
    $cases = 0
    if ((Test-NativeCompletion $ready $result $expected) -ne 'READY') { throw 'Ready gate' }; $cases++
    $running = [pscustomobject]@{state=4;last_task_result=0;running_instances=1}
    if ((Test-NativeCompletion $running $result $expected) -ne 'WAIT') { throw 'Never start before native task exits' }; $cases++
    $result.complete_full_inventory = $false
    if ((Test-NativeCompletion $ready $result $expected) -ne 'FAIL') { throw 'Partial cannot start evaluation' }; $cases++
    $result.complete_full_inventory = $true; $result.config.sha256 = ('c'*64)
    if ((Test-NativeCompletion $ready $result $expected) -ne 'FAIL') { throw 'Wrong native config' }; $cases++
    $result.config.sha256 = ('a'*64); $result.cleanup.confirmed_all_known_owned_exited = $false
    if ((Test-NativeCompletion $ready $result $expected) -ne 'FAIL') { throw 'Owned closure required' }; $cases++
    $result.cleanup.confirmed_all_known_owned_exited = $true; $result.actual_layout_pages = @(1..483)+@(483)
    if ((Test-NativeCompletion $ready $result $expected) -ne 'FAIL') { throw 'Duplicate sources refused' }; $cases++
    $result.actual_layout_pages = @(1,2.5)+@(3..484)
    if ((Test-NativeCompletion $ready $result $expected) -ne 'FAIL') { throw 'Fractional source IDs refused' }; $cases++
    $result.actual_layout_pages = @(1..484);$result.fresh_layout_pages=@(65..484);$result.retained_layout_pages=@(1..64)
    $result.resources=@($result.resources[1..15]);$expected.expected_native_stages=15;$expected.expected_fresh_layout_pages=420;$expected.expected_retained_layout_pages=64
    if ((Test-NativeCompletion $ready $result $expected) -ne 'READY') { throw 'Explicit retained64 plus15 fresh children accepted' }; $cases++
    $result.fresh_layout_pages=@(64..483)
    if ((Test-NativeCompletion $ready $result $expected) -ne 'FAIL') { throw 'Retained and fresh overlap refused' }; $cases++
    $result.fresh_layout_pages=@(65..484)
    $expected | Add-Member -NotePropertyName expected_fresh_table_pages -NotePropertyValue 420
    $expected | Add-Member -NotePropertyName expected_retained_table_pages -NotePropertyValue 64
    $expected.expected_native_stages=14;$result.resources=@($result.resources[1..14])
    $result | Add-Member -NotePropertyName fresh_table_pages -NotePropertyValue @(65..484)
    $result | Add-Member -NotePropertyName retained_table_pages -NotePropertyValue @(1..64)
    if ((Test-NativeCompletion $ready $result $expected) -ne 'READY') { throw 'Retained64 layout and tables plus14 fresh children accepted' }; $cases++
    $result.fresh_table_pages=@(64..483)
    if ((Test-NativeCompletion $ready $result $expected) -ne 'FAIL') { throw 'Retained and fresh table overlap refused' }; $cases++
    $result.fresh_table_pages=@(65..484);$result.retained_table_pages=@(1..63)+@(64.5)
    if ((Test-NativeCompletion $ready $result $expected) -ne 'FAIL') { throw 'Fractional retained table page refused' }; $cases++
    if ((Test-PostCompletion ([pscustomobject]@{valid=$true;executed=$false}) $null) -ne 'FAIL') { throw 'Preflight exit zero is not completion' }; $cases++
    $post = [pscustomobject]@{status='COMPLETE';failure=$null;endpoint_score_status='COMPLETE';cleanup=@{confirmed_all_known_owned_exited=$true};shared_lock_released_after_owned_closure=$true;
        resources=@('control','candidate','paired_score' | ForEach-Object {[pscustomobject]@{stage=$_;actual_exit_code=0;failure=$null;stop_reason=$null;child_started=$true;cleanup=@{confirmed_all_known_owned_exited=$true}}})}
    $score = [pscustomobject]@{status='COMPLETE';scope='FULL484_FIXED585';actual_scorer_invocations=2;writer_readback_verified=$true;before_exact=323;product_present_denominator=585}
    if ((Test-PostCompletion $post $score) -ne 'COMPLETE') { throw 'Actual full score result required' }; $cases++
    $score.product_present_denominator=584
    if ((Test-PostCompletion $post $score) -ne 'FAIL') { throw 'Changed metric denominator refused' }; $cases++
    [pscustomobject]@{status='PASS';synthetic_cases=$cases;Python_processes_started=0;model_calls=0} | ConvertTo-Json -Compress
    exit 0
}

if ($env:COMPUTERNAME.ToLowerInvariant() -ne 'server') { throw 'HQ only' }
$prefix = 'D:\OCR-Experiments\'
function Assert-ExperimentPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside HQ experiments' }
    return $full
}
function Assert-Pin($Pin) {
    $path = Assert-ExperimentPath $Pin.path
    if ($Pin.sha256 -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Pin.sha256) { throw 'Frozen bytes changed' }
    return $path
}
function Write-State([string]$Status, [string]$Detail) {
    $value = [ordered]@{contract='document-ai-post-eval-queue-status.v1';status=$Status;detail=$Detail;
        observed_at_utc=[DateTime]::UtcNow.ToString('o');Python_started=$script:PythonStarted;model_calls=0;post_proof=$script:PostProof}
    $path = Join-Path $PSScriptRoot 'QUEUE_STATE.json'; $temp = $path+'.tmp'
    [IO.File]::WriteAllText($temp, ($value | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
    # PowerShell coerces $null to an empty string for this .NET string overload.
    if (Test-Path -LiteralPath $path) { [IO.File]::Replace($temp,$path,[System.Management.Automation.Language.NullString]::Value) } else { [IO.File]::Move($temp,$path) }
}
function Test-SharedLock([string]$Path) {
    $path = Assert-ExperimentPath $Path; $stream = $null; $held = $false
    try {
        $stream = [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)
        $stream.Lock(0,1); $held = $true; return $true
    } catch [IO.IOException] {
        $code = $_.Exception.HResult -band 65535
        if ($code -notin @(32,33)) { throw }
        return $false
    } finally {
        if ($held) { $stream.Unlock(0,1) }
        if ($null -ne $stream) { $stream.Dispose() }
    }
}
$script:PythonStarted = $false
$script:PostProof = $null
try {
    $manifestPath = Assert-Pin ([pscustomobject]@{path=$Manifest;sha256=$ManifestSha256})
    $c = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($c.contract -ne 'root-HQ-docling-post-eval-queue.v1' -or $c.approved_by -ne 'root' -or
        $c.native_task_name -notmatch '^OCR_DOCAI_DOCLING_FULL484_[A-Za-z0-9_]+$' -or
        $c.maximum_wait_seconds -le 0 -or $c.maximum_wait_seconds -gt 86400) { throw 'Finite root queue required' }
    if ((Assert-Pin $c.queue_source) -ne $PSCommandPath) { throw 'Queue source differs' }
    $nativeConfig = Assert-Pin $c.native_config
    $nativeResultPath = Assert-ExperimentPath $c.native_result_path
    $end = [DateTime]::Parse($c.created_at_utc).ToUniversalTime().AddSeconds($c.maximum_wait_seconds)
    $scheduler = New-Object -ComObject Schedule.Service; $scheduler.Connect()
    Write-State 'WAITING_FOR_NATIVE_PHYSICAL_CLOSURE' 'No Python is started while waiting.'
    while ([DateTime]::UtcNow -lt $end) {
        if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'STOP_REQUEST.json')) { Write-State 'STOPPED_BY_USER' 'No post-evaluation started.'; exit 75 }
        $task = $scheduler.GetFolder('\').GetTask($c.native_task_name)
        $snapshot = [pscustomobject]@{state=[int]$task.State;last_task_result=[int]$task.LastTaskResult;running_instances=[int]$task.GetInstances(0).Count}
        if ($snapshot.state -ne 4 -and $snapshot.running_instances -eq 0) {
            $result = $null
            if (Test-Path -LiteralPath $nativeResultPath) { $result = Get-Content -LiteralPath $nativeResultPath -Raw -Encoding UTF8 | ConvertFrom-Json }
            $decision = Test-NativeCompletion $snapshot $result $c
            if ($decision -eq 'FAIL') { throw 'Native task failed, is partial, has a different config, or has not closed.' }
            if ($decision -eq 'READY' -and (Test-SharedLock $c.shared_lock_path)) {
                # The post-driver repeats source, resource, lineage and fresh process gates.
                $null = Assert-Pin $c.native_config; $python = Assert-Pin $c.python
                $worker = Assert-Pin $c.worker; $postConfig = Assert-Pin $c.post_eval_config
                $postData = Get-Content -LiteralPath $postConfig -Raw -Encoding UTF8 | ConvertFrom-Json
                $postResultPath = Join-Path (Assert-ExperimentPath $postData.preparation_root) 'RESULT.json'
                if (Test-Path -LiteralPath $postResultPath) { throw 'Preserve an existing post-evaluation attempt; do not launch twice.' }
                $receipt = [ordered]@{contract='document-ai-native-task-ready.v1';task_name=$c.native_task_name;
                    state=3;last_task_result=0;running_instances=0;observed_at_utc=[DateTime]::UtcNow.ToString('o');
                    native_result=@{path=$nativeResultPath;sha256=(Get-FileHash -LiteralPath $nativeResultPath -Algorithm SHA256).Hash.ToLowerInvariant()};native_config=$c.native_config}
                $receiptPath = Join-Path $PSScriptRoot 'NATIVE_TASK_READY.json'
                $stream = [IO.File]::Open($receiptPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
                try { $bytes=(New-Object Text.UTF8Encoding($false)).GetBytes(($receipt | ConvertTo-Json -Depth 8));$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true) } finally { $stream.Dispose() }
                $receiptSha = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
                $script:PythonStarted = $true; Write-State 'POST_EVALUATION_STARTED' 'Native task is physically closed; one bounded pure follow-up starts.'
                & $python -X utf8 -B $worker --config $postConfig --config-sha256 $c.post_eval_config.sha256 --completion-receipt $receiptPath --completion-sha256 $receiptSha --execute
                $code = $LASTEXITCODE
                if ($code -ne 0) { throw ('Post-evaluation exit '+$code) }
                $postResult = Get-Content -LiteralPath $postResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $scorePath = Assert-Pin $postResult.actual_full_score
                $fullScore = Get-Content -LiteralPath $scorePath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ((Test-PostCompletion $postResult $fullScore) -ne 'COMPLETE') { throw 'Post-evaluation returned zero without a complete fixed585 paired score.' }
                $script:PostProof = @{post_result=@{path=$postResultPath;sha256=(Get-FileHash -LiteralPath $postResultPath -Algorithm SHA256).Hash.ToLowerInvariant()};full_score=$postResult.actual_full_score}
                Write-State 'COMPLETE' 'Actual full paired score and all three owned children completed.'
                exit 0
            }
        }
        Start-Sleep -Seconds 5
    }
    throw 'Finite predecessor wait expired.'
} catch {
    Write-State 'FAILED' $_.Exception.Message
    throw
}
