<#
.SYNOPSIS
  Moose Life (PC) Resolution List Fix - Windows patcher (no dependencies).

.DESCRIPTION
  Patches your own MooselifeGL.exe so the launcher lists every resolution/refresh rate your
  display supports (1440p, 4K ...) instead of stopping at the first 256 modes the graphics
  driver reports. A backup (MooselifeGL.exe.orig) is kept. Only the known Steam build is
  patched (verified by SHA-256 and by the exact bytes at every patch site); anything else is
  refused untouched. Details: README.md and docs/TECHNICAL.md in the repository.

.EXAMPLE
  .\ML-ResolutionFix.ps1                 # find the Steam install and patch it
  .\ML-ResolutionFix.ps1 -Check          # report state only
  .\ML-ResolutionFix.ps1 -Restore        # put the backup back
  .\ML-ResolutionFix.ps1 -Filter         # also apply part B (width filter, for > 256 accepted modes)
  .\ML-ResolutionFix.ps1 "C:\...\Moose Life\MooselifeGL.exe"
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Path,
    [switch]$Check,
    [switch]$Restore,
    [switch]$Filter
)
$ErrorActionPreference = 'Stop'
$Version = '1.0.0'

# ---- known builds: sha256 -> patch rows (file offset, original hex, patched hex) ---------------
# Row 0 = part A (1-byte cap fix), rows 1-2 = part B (hook + code cave; -Filter).
$Builds = @{
    'd78570b97a5761173d297598739b6201a9d2449c32ebb67d12586a98e570bd8c' = @{
        Label = 'Steam build (GL/OpenVR 1.06, 2020-08-14)'
        Rows  = @(
            @(0x9d3e6, '413bf6', '413bee'),
            @(0x9d405, '0f820f010000', 'e9e604050090'),
            @(0xed8f0, '0000000000000000000000000000000000000000000000000000000000000000', '0f8224fcfaff488b05938a0c008b00d1e8433904f70f820ffcfaffe9fbfafaff')
        )
    }
}

function ConvertFrom-Hex([string]$hex) {
    $b = New-Object byte[] ($hex.Length / 2)
    for ($i = 0; $i -lt $b.Length; $i++) { $b[$i] = [Convert]::ToByte($hex.Substring(2 * $i, 2), 16) }
    return ,$b
}
function Get-Sha256([byte[]]$data) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($data)) -replace '-', '').ToLower() } finally { $sha.Dispose() }
}
function Test-Bytes([byte[]]$data, [int]$off, [byte[]]$want) {
    if ($off + $want.Length -gt $data.Length) { return $false }
    for ($i = 0; $i -lt $want.Length; $i++) { if ($data[$off + $i] -ne $want[$i]) { return $false } }
    return $true
}
function Get-RowState([byte[]]$data, $row) {
    if (Test-Bytes $data $row[0] (ConvertFrom-Hex $row[1])) { return 'orig' }
    if (Test-Bytes $data $row[0] (ConvertFrom-Hex $row[2])) { return 'patched' }
    return 'unknown'
}
function Find-Build([byte[]]$data) {
    $h = Get-Sha256 $data
    if ($Builds.ContainsKey($h)) { return $Builds[$h] }
    foreach ($b in $Builds.Values) {        # already (partly) patched files hash differently: identify by patch-site bytes
        $ok = $true
        foreach ($row in $b.Rows) { if ((Get-RowState $data $row) -eq 'unknown') { $ok = $false } }
        if ($ok) { return $b }
    }
    return $null
}
function Get-SteamLibraries {
    $roots = @()
    $isWin = ($PSVersionTable.PSVersion.Major -lt 6) -or $IsWindows
    if ($isWin) {
        foreach ($k in 'HKCU:\Software\Valve\Steam', 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam') {
            try {
                $p = Get-ItemProperty -Path $k -ErrorAction Stop
                if ($p.SteamPath) { $roots += ($p.SteamPath -replace '/', '\') }
                if ($p.InstallPath) { $roots += $p.InstallPath }
            } catch { }
        }
        $roots += 'C:\Program Files (x86)\Steam', 'C:\Program Files\Steam'
    }
    $libs = @()
    foreach ($r in $roots) {
        if (-not (Test-Path -LiteralPath $r)) { continue }
        $libs += $r
        $vdf = Join-Path $r 'steamapps\libraryfolders.vdf'
        if (Test-Path -LiteralPath $vdf) {
            foreach ($m in [regex]::Matches((Get-Content -LiteralPath $vdf -Raw), '"path"\s+"([^"]+)"')) { $libs += ($m.Groups[1].Value -replace '\\\\', '\') }
        }
    }
    return $libs | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -Unique
}
function Find-GameExes {
    $found = @()
    foreach ($lib in Get-SteamLibraries) {
        $common = Join-Path $lib 'steamapps\common'
        if (-not (Test-Path -LiteralPath $common)) { continue }
        foreach ($dir in Get-ChildItem -LiteralPath $common -Directory -Filter 'Moose Life*' -ErrorAction SilentlyContinue) {
            $found += Get-ChildItem -LiteralPath $dir.FullName -Filter 'MooselifeGL.exe' -Recurse -Depth 1 -File -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
        }
    }
    return $found
}

Write-Host "Moose Life Resolution List Fix v$Version"
$exes = $Path
if (-not $exes) { $exes = Find-GameExes }
if (-not $exes) {
    Write-Host 'MooselifeGL.exe not found automatically. Run again with:'
    Write-Host '  .\ML-ResolutionFix.ps1 "C:\Program Files (x86)\Steam\steamapps\common\Moose Life\MooselifeGL.exe"'
    exit 1
}
$rc = 0
foreach ($exe in $exes) {
    Write-Host "== $exe"
    try {
        $bak = "$exe.orig"
        if ($Restore) {
            if (-not (Test-Path -LiteralPath $bak)) { Write-Host "   no backup found ($bak). Use Steam > Verify integrity of game files."; $rc = 1; continue }
            Copy-Item -LiteralPath $bak -Destination $exe -Force
            Write-Host "   restored from $bak"; continue
        }
        $data = [System.IO.File]::ReadAllBytes($exe)
        $build = Find-Build $data
        if (-not $build) {
            Write-Host ("   unknown build (sha256 {0}) - not touching it. Please report this hash in a GitHub issue;" -f (Get-Sha256 $data))
            Write-Host "   the Python patcher (ml_resfix.py) can locate the patch sites by code signature."
            $rc = 1; continue
        }
        $full = $build.Rows
        $rows = @(, $full[0])
        if ($Filter) { $rows += , $full[1]; $rows += , $full[2] }
        $states = @(); foreach ($row in $rows) { $states += (Get-RowState $data $row) }
        $bState = @($full[1], $full[2] | ForEach-Object { Get-RowState $data $_ } | Select-Object -Unique)
        Write-Host ("   build: {0}   state: A: {1}, B(filter): {2}" -f $build.Label, $states[0], $(if ($bState.Count -eq 1) { $bState[0] } else { 'unknown' }))
        if ($Check) { continue }
        if ($states -contains 'unknown') { Write-Host "   unexpected bytes at a patch site - refusing to touch this file"; $rc = 1; continue }
        if (-not ($states -contains 'orig')) { Write-Host "   already patched - nothing to do"; continue }
        if (-not (Test-Path -LiteralPath $bak)) { Copy-Item -LiteralPath $exe -Destination $bak; Write-Host "   backup: $bak" }
        $n = 0
        for ($i = 0; $i -lt $rows.Count; $i++) {
            if ($states[$i] -ne 'orig') { continue }
            $new = ConvertFrom-Hex $rows[$i][2]
            [Array]::Copy($new, 0, $data, $rows[$i][0], $new.Length); $n += $new.Length
        }
        [System.IO.File]::WriteAllBytes($exe, $data)
        Write-Host ("   patched ({0} bytes changed). sha256: {1}" -f $n, (Get-Sha256 $data))
    } catch [System.UnauthorizedAccessException] {
        Write-Host "   access denied writing to the game folder - run this from an elevated (Administrator) prompt"; $rc = 1
    } catch {
        Write-Host "   error: $($_.Exception.Message)"; $rc = 1
    }
}
exit $rc
