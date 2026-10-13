<# Open the task-owned nTop Python Console with Ctrl+backtick, then verify it.
This is a foreground keyboard shortcut, not a no-focus background transport.
Use the background console bridge for subsequent Notebook API commands.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][int]$ProcessId,
    [Parameter(Mandatory=$true)][long]$ExpectedStartTicks,
    [Parameter(Mandatory=$true)][string]$ExpectedTitlePrefix,
    [Parameter(Mandatory=$true)][string]$ReceiptPath
)
$ErrorActionPreference='Stop'
$taskProcess=Get-Process -Id $ProcessId -ErrorAction Stop
if ($taskProcess.StartTime.ToUniversalTime().Ticks -ne $ExpectedStartTicks) { throw 'Task process identity changed.' }
if ($taskProcess.ProcessName -ne 'ntop') { throw 'The target process is not nTop.' }
if (Test-Path -LiteralPath $ReceiptPath) { throw 'Use a new receipt path for each test.' }
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class NTopConsoleShortcut {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h,StringBuilder s,int n);
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
  [DllImport("user32.dll")] public static extern IntPtr GetKeyboardLayout(uint thread);
  [DllImport("user32.dll",SetLastError=true)] static extern uint SendInput(uint n, INPUT[] input, int size);
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort vk,scan; public uint flags,time; public UIntPtr extra; }
  [StructLayout(LayoutKind.Explicit,Size=32)] public struct INPUTUNION { [FieldOffset(0)] public KEYBDINPUT key; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public INPUTUNION u; }
  public static uint Owner(IntPtr h) { uint p; GetWindowThreadProcessId(h,out p); return p; }
  public static string Title(IntPtr h) { var s=new StringBuilder(1024);GetWindowText(h,s,1024);return s.ToString(); }
  public static IntPtr[] MainWindows(uint pid,string prefix) {
    var a=new List<IntPtr>();EnumWindows((h,p)=>{if(Owner(h)==pid && IsWindowVisible(h) && Title(h).StartsWith(prefix,StringComparison.Ordinal))a.Add(h);return true;},IntPtr.Zero);return a.ToArray();
  }
  public static IntPtr[] Consoles(uint pid) {
    var a=new List<IntPtr>();
    EnumWindows((h,p)=>{if(Owner(h)==pid && Title(h)=="Python Console" && IsWindowVisible(h))a.Add(h);return true;},IntPtr.Zero);
    return a.ToArray();
  }
  public static uint Shortcut() {
    var a=new INPUT[4]; ushort[] keys={0x11,0xC0,0xC0,0x11};
    for(int i=0;i<4;i++){a[i].type=1;a[i].u.key.vk=keys[i];a[i].u.key.flags=i>=2?2u:0u;}
    return SendInput(4,a,Marshal.SizeOf(typeof(INPUT)));
  }
  public static void ReleaseChord() {
    var a=new INPUT[2];for(int i=0;i<2;i++){a[i].type=1;a[i].u.key.vk=(ushort)(i==0?0xC0:0x11);a[i].u.key.flags=2u;}
    SendInput(2,a,Marshal.SizeOf(typeof(INPUT)));
  }
}
'@
$mainWindows=@([NTopConsoleShortcut]::MainWindows([uint32]$ProcessId,$ExpectedTitlePrefix))
if ($mainWindows.Count -ne 1) { throw 'Expected exactly one visible main window for the task notebook.' }
$main=$mainWindows[0]
$mainTitle=[NTopConsoleShortcut]::Title($main)
$before=[NTopConsoleShortcut]::GetForegroundWindow()
$consoleBefore=@([NTopConsoleShortcut]::Consoles([uint32]$ProcessId))
if ($consoleBefore.Count -gt 1) { throw 'More than one console belongs to the target process.' }
$sent=$false
$started=[Diagnostics.Stopwatch]::StartNew()
try {
    if ($consoleBefore.Count -eq 0) {
        foreach ($key in @(0x10,0x11,0x12,0x5B,0x5C)) {
            if (([NTopConsoleShortcut]::GetAsyncKeyState($key) -band 0x8000) -ne 0) { throw 'A user modifier key is held; no shortcut was sent.' }
        }
        if ($main -eq 0) { throw 'The task has no main window.' }
        [void][NTopConsoleShortcut]::SetForegroundWindow($main)
        Start-Sleep -Milliseconds 200
        if ([NTopConsoleShortcut]::Owner([NTopConsoleShortcut]::GetForegroundWindow()) -ne $ProcessId) {
            $shell=New-Object -ComObject WScript.Shell
            [void]$shell.AppActivate($ProcessId)
            Start-Sleep -Milliseconds 200
        }
        if ([NTopConsoleShortcut]::Owner([NTopConsoleShortcut]::GetForegroundWindow()) -ne $ProcessId) { throw 'Could not focus the exact nTop process; no shortcut was sent.' }
        $delivered=[NTopConsoleShortcut]::Shortcut()
        $sent=$true
        if ($delivered -ne 4) { [NTopConsoleShortcut]::ReleaseChord();throw "Only $delivered of four key events were delivered." }
        $deadline=[DateTime]::UtcNow.AddSeconds(5)
        do {
            Start-Sleep -Milliseconds 100
            $consoleAfter=@([NTopConsoleShortcut]::Consoles([uint32]$ProcessId))
        } while ($consoleAfter.Count -eq 0 -and [DateTime]::UtcNow -lt $deadline)
        if ($consoleAfter.Count -ne 1) { throw 'Ctrl+backtick did not expose exactly one Python Console.' }
    } else { $consoleAfter=$consoleBefore }
    $result=[ordered]@{passed=$true;pid=$ProcessId;start_ticks=$ExpectedStartTicks;main_title=$mainTitle;
      shortcut='Ctrl+backtick';virtual_key='VK_OEM_3 (0xC0)';shortcut_sent=$sent;console_count_before=$consoleBefore.Count;
      console_hwnd=$consoleAfter[0].ToInt64();seconds=$started.Elapsed.TotalSeconds;foreground_before=$before.ToInt64();
      scope='Console visibility only. Require a separate successful Notebook API probe before authoring.'}
} catch {
    $result=[ordered]@{passed=$false;pid=$ProcessId;shortcut='Ctrl+backtick';shortcut_sent=$sent;error=$_.Exception.Message;seconds=$started.Elapsed.TotalSeconds}
    throw
} finally {
    if ($before -ne [IntPtr]::Zero) { [void][NTopConsoleShortcut]::SetForegroundWindow($before) }
    Start-Sleep -Milliseconds 200
    $result.foreground_after=[NTopConsoleShortcut]::GetForegroundWindow().ToInt64()
    $result.foreground_restored=($result.foreground_after -eq $before.ToInt64())
    $result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ReceiptPath -Encoding utf8
}
$result | ConvertTo-Json -Depth 4
