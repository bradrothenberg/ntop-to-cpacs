<#
.SYNOPSIS
Run Python in the nTop GUI's Python Console without keyboard focus.

.DESCRIPTION
Keyboard-driven console automation types into the console with SendKeys, which
needs the interactive desktop: it fails with "could not type the launch line"
when the Windows session is locked. This variant posts WM_CHAR messages
straight to the console window's message queue, so it works with the screen
locked and never steals focus. Everything else is the same: the command is
staged in a .py file, a runner writes a marker file with OK or the
traceback, and the script waits for that marker.

.PARAMETER Command
Python to run. Multi-line is fine.

.PARAMETER TimeoutMs
How long to wait for the marker. Ignored with -NoWait.

.PARAMETER NoWait
Return as soon as the launch line has been sent and verified. Poll the
marker file yourself (its path is printed).

.PARAMETER ScriptPath
Where the command is staged. Defaults to _agent/console_cmd_<ProcessId>.py.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Command,
    [int]$TimeoutMs = 30000,
    [switch]$NoWait,
    [Parameter(Mandatory = $true)][ValidateRange(1,2147483647)][int]$ProcessId,
    [string]$ScriptPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
if (-not ('PostKeys' -as [type])) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public class PostKeys {
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
}
'@
}

# Enumerate native HWNDs first. Never query the desktop UIA root.
if (-not ('RCConsoleDiscovery' -as [type])) {
    Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class RCConsoleDiscovery {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr data);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  public static uint Owner(IntPtr h) { uint p; GetWindowThreadProcessId(h,out p); return p; }
  public static IntPtr[] OwnedWindows(uint target) {
    var windows = new List<IntPtr>();
    EnumWindows((h,p) => { if(Owner(h)==target) windows.Add(h); return true; },IntPtr.Zero);
    return windows.ToArray();
  }
}
'@
}
$consoles = @(
    foreach ($ownedHandle in [RCConsoleDiscovery]::OwnedWindows([uint32]$ProcessId)) {
        if ([RCConsoleDiscovery]::Owner($ownedHandle) -ne $ProcessId) { continue }
        try {
            $ownedElement = [System.Windows.Automation.AutomationElement]::FromHandle($ownedHandle)
            if ($ownedElement.Current.ProcessId -eq $ProcessId -and
                $ownedElement.Current.ClassName -eq 'nTopology::trb::PythonConsole') {
                $ownedElement
            }
        }
        catch [System.Windows.Automation.ElementNotAvailableException] { continue }
    }
)
if ($consoles.Count -ne 1) { throw "Expected exactly one nTop Python Console for PID $ProcessId, found $($consoles.Count)." }
$console = $consoles[0]
if ([string]::IsNullOrWhiteSpace($ScriptPath) -and $ProcessId -gt 0) {
    $ScriptPath = Join-Path (Join-Path (Split-Path -Parent $PSScriptRoot) '_agent') ("console_cmd_$ProcessId.py")
}
$hwnd = [IntPtr]$console.Current.NativeWindowHandle

$editCond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ClassNameProperty, 'nTopology::trb::CLIConsoleTextEdit')
$edit = $console.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editCond)
if ($null -eq $edit) { throw "Console window found but its text control was not." }
$textPattern = $edit.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
$before = $textPattern.DocumentRange.GetText(-1)

if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
    $repo = Split-Path -Parent $PSScriptRoot
    $agentDir = Join-Path $repo '_agent'
    if (-not (Test-Path $agentDir)) { New-Item -ItemType Directory $agentDir | Out-Null }
    $ScriptPath = Join-Path $agentDir 'console_cmd.py'
}
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($ScriptPath, $Command, $utf8)
$runnerPath = [System.IO.Path]::ChangeExtension($ScriptPath, $null) + '_run.py'
$markerPath = [System.IO.Path]::ChangeExtension($ScriptPath, $null) + '_done.txt'
$runnerPy = $runnerPath -replace '\\', '/'
$runner = @"
import traceback as _tb
_ntop_status = 'OK'
try:
    exec(compile(open(r'$ScriptPath', encoding='utf-8').read(), r'$ScriptPath', 'exec'), globals())
except BaseException:
    _ntop_status = _tb.format_exc()
open(r'$markerPath', 'w', encoding='utf-8').write(_ntop_status)
"@
[System.IO.File]::WriteAllText($runnerPath, $runner, $utf8)
if (Test-Path $markerPath) { Remove-Item $markerPath -Force }

$launch = "exec(open('$runnerPy').read())"

$lastLine = ($textPattern.DocumentRange.GetText(-1).TrimEnd() -split "`n")[-1]
if ($lastLine.Trim() -notin @('py>', '>>>')) {
    throw "Console prompt is not idle; last line is: $lastLine"
}

$WM_CHAR = 0x0102; $WM_KEYDOWN = 0x0100; $WM_KEYUP = 0x0101
foreach ($ch in $launch.ToCharArray()) {
    [void][PostKeys]::PostMessage($hwnd, $WM_CHAR, [IntPtr][int][char]$ch, [IntPtr]1)
}
Start-Sleep -Milliseconds 400
$now = $textPattern.DocumentRange.GetText(-1).TrimEnd()
if (-not $now.EndsWith($launch)) {
    throw "Launch line did not arrive intact. Prompt line is: $(($now -split "`n")[-1])"
}
[void][PostKeys]::PostMessage($hwnd, $WM_KEYDOWN, [IntPtr]0x0D, [IntPtr]0x001C0001)
[void][PostKeys]::PostMessage($hwnd, $WM_KEYUP, [IntPtr]0x0D, [IntPtr]0xC01C0001)

Write-Output "marker: $markerPath"
if ($NoWait) { return }

$deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
while ([DateTime]::UtcNow -lt $deadline) {
    Start-Sleep -Milliseconds 250
    if (Test-Path $markerPath) {
        Start-Sleep -Milliseconds 300
        $after = $textPattern.DocumentRange.GetText(-1)
        # Best effort echo of what the command printed; the buffer scrolls, so
        # on a long session this can be empty. The marker is what says it ran.
        $delta = if ($after.Length -gt $before.Length) { $after.Substring($before.Length) } else { ($after -split [regex]::Escape($launch))[-1] }
        Write-Output $delta.TrimEnd()
        $status = (Get-Content $markerPath -Raw)
        if ($status.Trim() -ne 'OK') { throw "The console command raised:`n$status" }
        return
    }
}
Write-Warning "Command did not finish within ${TimeoutMs}ms; it may still be running. Poll $markerPath."
