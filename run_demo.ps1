<# Run the GBI -> CPACS -> Notebook API -> CPACS demonstration.
   Creates a dedicated nTop session and a new run directory. Does not reuse
   another project's console or overwrite earlier runs.
#>
[CmdletBinding()]
param(
  [string]$Name = ('demo-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss')),
  [switch]$Resume,
  [ValidateSet(4)][double]$TipTwistDeg = 4,
  [string]$NTopExe = $env:NTOP_NOTEBOOK_EXE
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if($Name -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_-]*$'){throw 'Use a simple run name.'}
$demoRoot=$PSScriptRoot
$runDir=Join-Path $demoRoot ('runs\'+$Name)
if((Test-Path -LiteralPath $runDir) -and -not $Resume){throw 'Use a new run name to preserve previous results, or -Resume.'}
$source=Join-Path $demoRoot 'source\GBI-V38.ntop'
if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLower() -ne '44acc807b70ef83ad130c73cbe5957843fe9ff194b3391dc7fa8f805cfaae7a5'){throw 'Unexpected GBI source hash.'}
if(-not $NTopExe -and $Resume -and (Test-Path -LiteralPath (Join-Path $runDir 'session.json'))){
  $NTopExe=(Get-Content -LiteralPath (Join-Path $runDir 'session.json') -Raw | ConvertFrom-Json).exe
}
if(-not $NTopExe -or -not(Test-Path -LiteralPath $NTopExe)){throw 'Supply the Notebook API nTop build with -NTopExe or NTOP_NOTEBOOK_EXE.'}
if(-not $Resume){
  New-Item -ItemType Directory -Path $runDir | Out-Null
  Copy-Item -LiteralPath $source -Destination (Join-Path $runDir 'GBI-demo.ntop')
}
Push-Location -LiteralPath $demoRoot
try {
  if($Resume){
    $savedSession=Get-Content -LiteralPath (Join-Path $runDir 'session.json') -Raw | ConvertFrom-Json
    $taskProcess=Get-Process -Id $savedSession.pid
    if($taskProcess.StartTime.ToUniversalTime().Ticks -ne $savedSession.start_ticks){throw 'Task process identity changed.'}
  } else {
    $taskProcess=Start-Process -FilePath $NTopExe -ArgumentList ('"'+(Join-Path $runDir 'GBI-demo.ntop')+'"') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runDir 'ntop-stdout.log') -RedirectStandardError (Join-Path $runDir 'ntop-stderr.log')
  }
  $taskPid=$taskProcess.Id
  $startTicks=$taskProcess.StartTime.ToUniversalTime().Ticks
  if(-not $Resume){@{pid=$taskPid;start_ticks=$startTicks;exe=$NTopExe} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDir 'session.json')}
  Write-Output "Launched dedicated nTop PID $taskPid. Run: $runDir"
  $deadline=[DateTime]::UtcNow.AddSeconds(120)
  if(-not $Resume){do {
    Start-Sleep -Milliseconds 500
    $taskProcess=Get-Process -Id $taskPid
    if([DateTime]::UtcNow -gt $deadline){throw 'The dedicated notebook did not open within 120 seconds.'}
  } while((-not $taskProcess.MainWindowTitle.StartsWith('GBI-demo.ntop')) -or -not $taskProcess.Responding)}
  $consoleReceipt=Join-Path $runDir ('console-open-'+[DateTime]::UtcNow.Ticks+'.json')
  $expectedTitle='GBI-demo.ntop'
  if(Test-Path -LiteralPath (Join-Path $runDir 'baseline-api.json')){$expectedTitle='baseline-working.ntop'}
  if(Test-Path -LiteralPath (Join-Path $runDir 'apply-receipt.json')){$expectedTitle='changed-working.ntop'}
  if(Test-Path -LiteralPath (Join-Path $runDir 'reopen-receipt.json')){$expectedTitle='GBI-changed.ntop'}
  & (Join-Path $demoRoot 'scripts\open_python_console_shortcut.ps1') -ProcessId $taskPid -ExpectedStartTicks $startTicks -ExpectedTitlePrefix $expectedTitle -ReceiptPath $consoleReceipt
  function Invoke-DemoApi([string]$Stage,[string]$Code) {
    $p=Get-Process -Id $taskPid
    if($p.StartTime.ToUniversalTime().Ticks -ne $startTicks){throw 'Task process identity changed.'}
    $dispatch=Join-Path $runDir ('dispatch-'+$Stage+'.py')
    $marker=[System.IO.Path]::ChangeExtension($dispatch,$null)+'_done.txt'
    if(Test-Path -LiteralPath $marker){
      if((Get-Content -LiteralPath $marker -Raw).Trim() -ne 'OK'){throw "Prior API stage $Stage failed. Inspect its marker before retrying."}
      Write-Output "API $Stage already completed; retained its receipt."
      return
    }
    if(Test-Path -LiteralPath $dispatch){throw "API stage $Stage has no completion marker. Its outcome is unknown; do not resubmit."}
    & (Join-Path $demoRoot 'scripts\ntop_console_post.ps1') -ProcessId $taskPid -ScriptPath $dispatch -Command $Code -NoWait
    $until=[DateTime]::UtcNow.AddSeconds(120)
    while(-not(Test-Path -LiteralPath $marker)) {
      Start-Sleep -Milliseconds 500
      if([DateTime]::UtcNow -gt $until){throw "API stage $Stage exceeded 120 seconds. Do not resubmit; inspect the completion marker and this task's process."}
    }
    $result=Get-Content -LiteralPath $marker -Raw
    if($result.Trim() -ne 'OK'){throw $result}
    Write-Output "API $Stage completed."
  }
  $scripts=(Join-Path $demoRoot 'scripts').Replace('\','/')
  $runPy=$runDir.Replace('\','/')
  $witness=(Join-Path $demoRoot 'data\witness.json').Replace('\','/')
  Invoke-DemoApi 'prepare' "import sys, importlib; sys.path.insert(0, r'$scripts'); import repair_twist; importlib.reload(repair_twist); repair_twist.prepare(notebook, r'$runPy')"
  Invoke-DemoApi 'snapshot' "import sys; sys.path.insert(0, r'$scripts'); import api_runtime; api_runtime.snapshot(notebook, r'$runPy', r'$witness')"
  & uv run --no-sync --cache-dir (Join-Path $demoRoot '.uv-cache') python scripts/demo.py measure-baseline $runDir
  if($LASTEXITCODE -ne 0){throw 'Baseline measurement failed.'}
  & uv run --no-sync --cache-dir (Join-Path $demoRoot '.uv-cache') python scripts/demo.py prepare $runDir --tip $TipTwistDeg
  if($LASTEXITCODE -ne 0){throw 'CPACS request validation failed.'}
  Invoke-DemoApi 'apply' "api_runtime.apply(notebook, r'$runPy/apply-config.json')"
  & uv run --no-sync --cache-dir (Join-Path $demoRoot '.uv-cache') python scripts/demo.py measure-changed $runDir
  if($LASTEXITCODE -ne 0){throw 'Changed measurement failed.'}
  & uv run --no-sync --cache-dir (Join-Path $demoRoot '.uv-cache') python scripts/verify_demo.py $runDir
  if($LASTEXITCODE -ne 0){throw 'Demo verification failed.'}
  Invoke-DemoApi 'reopen' "import importlib; importlib.reload(api_runtime); api_runtime.reopen_verified(notebook, r'$runPy')"
  & uv run --no-sync --cache-dir (Join-Path $demoRoot '.uv-cache') python scripts/make_demo_report.py $runDir
  if($LASTEXITCODE -ne 0){throw 'Demo report generation failed.'}
  Write-Output "Demo verified: $runDir"
} finally { Pop-Location }
