<#
.SYNOPSIS
    Flash ESP32-S3 firmware for Project Spotless nodes.

.DESCRIPTION
    Wrapper around PlatformIO that auto-detects pio.exe regardless of where Python
    is installed, auto-detects the COM port for the connected ESP32, and gives
    clear status output. Designed for non-technical operators on Windows.

.PARAMETER Node
    Which node to flash: 1, 2, 3, or 'all'. Required (positional).

.PARAMETER Port
    Override the auto-detected COM port (e.g. -Port COM5).

.PARAMETER WifiSsid
    Update WIFI_SSID in config.h before flashing.

.PARAMETER WifiPassword
    Update WIFI_PASSWORD in config.h before flashing.

.PARAMETER MqttBroker
    Update MQTT_BROKER (Pi static IP) in config.h before flashing.

.PARAMETER Monitor
    After a successful flash, open the serial monitor at 115200 baud.

.PARAMETER Check
    Just verify PlatformIO + COM port detection. Don't flash anything.

.PARAMETER Yes
    Skip the "Proceed?" confirmation prompt.

.EXAMPLE
    .\tools\flash_node.ps1 1
    Flash node 1 using auto-detected port and current config.h.

.EXAMPLE
    .\tools\flash_node.ps1 all
    Flash all 3 nodes interactively (prompts to swap USB cable between).

.EXAMPLE
    .\tools\flash_node.ps1 1 -WifiSsid "MyNet" -WifiPassword "secret" -MqttBroker "192.168.0.20"
    Update config.h with new WiFi + Pi IP, then flash node 1.

.EXAMPLE
    .\tools\flash_node.ps1 -Check
    Just check the toolchain - don't flash.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $false)]
    [string]$Node,

    [string]$Port,
    [string]$WifiSsid,
    [string]$WifiPassword,
    [string]$MqttBroker,
    [switch]$Monitor,
    [switch]$Check,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'

# =============================================================================
# Constants
# =============================================================================
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ValidNodes = @('1', '2', '3')

# Physical role of each node, shown in prompts so an operator with three
# physically-identical PCBs in front of them flashes the right firmware
# onto the right board.
$NodeRoles = @{
    1 = 'Container 1 (shampoo / conditioner pumps)'
    2 = 'Container 2 (disinfectant + flush)'
    3 = 'Bath line solenoid valves'
}

# =============================================================================
# UI helpers
# =============================================================================
function Write-Header {
    param([string]$Text)
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ('=' * 60) -ForegroundColor Cyan
}

function Write-Step  { param([string]$Msg) Write-Host "> $Msg" -ForegroundColor Cyan }
function Write-OK    { param([string]$Msg) Write-Host "  [OK]   $Msg" -ForegroundColor Green }
function Write-Warn  { param([string]$Msg) Write-Host "  [WARN] $Msg" -ForegroundColor Yellow }
function Write-Fail  { param([string]$Msg) Write-Host "  [FAIL] $Msg" -ForegroundColor Red }
function Write-Info  { param([string]$Msg) Write-Host "         $Msg" -ForegroundColor Gray }

# =============================================================================
# 1. Locate PlatformIO (pio.exe)
# =============================================================================
function Find-PlatformIO {
    Write-Step 'Locating PlatformIO...'

    # 1) Already on PATH?
    $cmd = Get-Command pio -ErrorAction SilentlyContinue
    if ($cmd) {
        Write-OK "Found pio on PATH: $($cmd.Source)"
        return $cmd.Source
    }

    # 2) Standard install locations (in priority order)
    $candidates = @(
        "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python*\Scripts\pio.exe",
        "$env:APPDATA\Python\Python*\Scripts\pio.exe",
        "$env:USERPROFILE\AppData\Roaming\Python\Python*\Scripts\pio.exe",
        "$env:ProgramFiles\Python*\Scripts\pio.exe"
    )

    foreach ($pattern in $candidates) {
        $foundItems = Get-Item $pattern -ErrorAction SilentlyContinue
        if ($foundItems) {
            $found = $foundItems | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            Write-OK "Found pio at: $($found.FullName)"
            # Add its dir to PATH for this session so 'pio' resolves directly
            $dir = Split-Path -Parent $found.FullName
            if ($env:Path -notlike "*$dir*") {
                $env:Path = "$dir;$env:Path"
            }
            return $found.FullName
        }
    }

    # 3) Try `python -m platformio` as last resort
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $check = & python -m platformio --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-OK "Found PlatformIO via 'python -m platformio'"
            return 'python-m-platformio'
        }
    }

    # 4) Not found - offer to install
    Write-Fail 'PlatformIO not found.'
    Write-Info 'PlatformIO is required to flash ESP32 firmware.'
    Write-Info "To install:  pip install --user platformio"
    Write-Info 'Then re-run this script.'
    return $null
}

# =============================================================================
# 2. Detect connected ESP32 COM port
# =============================================================================
function Get-Esp32Port {
    Write-Step 'Detecting ESP32 COM port...'

    # Get all serial ports currently present
    $ports = @()
    try {
        $ports = [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object
    } catch {
        Write-Warn 'Could not enumerate serial ports.'
        return $null
    }

    if ($ports.Count -eq 0) {
        Write-Fail 'No COM ports detected.'
        Write-Info 'Plug the ESP32 into a USB port, wait 5 seconds, and re-run.'
        Write-Info 'If still not detected:'
        Write-Info '  - Try a different USB cable (some are charge-only)'
        Write-Info '  - Try a different USB port (preferably USB 2.0)'
        Write-Info '  - Install CP210x driver: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers'
        return $null
    }

    # Try to enrich with friendly names (helps tell ESP32 from other devices)
    $portInfo = @{}
    try {
        $devices = Get-PnpDevice -Class Ports -PresentOnly -ErrorAction SilentlyContinue
        foreach ($dev in $devices) {
            if ($dev.FriendlyName -match '\((COM\d+)\)') {
                $portInfo[$Matches[1]] = $dev.FriendlyName
            }
        }
    } catch { }

    # Filter to likely ESP32 ports (USB Serial / CP210x / CH340 / ESP32 native USB JTAG)
    $likely = @()
    foreach ($p in $ports) {
        $name = if ($portInfo.ContainsKey($p)) { $portInfo[$p] } else { $p }
        if ($name -match 'CP210|CH340|USB Serial|JTAG|ESP32|Silicon Labs') {
            $likely += [PSCustomObject]@{ Port = $p; Name = $name }
        }
    }

    if ($likely.Count -eq 1) {
        Write-OK "Detected: $($likely[0].Port)  ($($likely[0].Name))"
        return $likely[0].Port
    }

    if ($likely.Count -gt 1) {
        Write-Warn "Multiple ESP32-like devices found:"
        foreach ($x in $likely) { Write-Info "$($x.Port)  ($($x.Name))" }
        Write-Info 'Re-run with -Port COMx to pick one explicitly.'
        return $null
    }

    # No "likely" match - fall back to all ports if there's exactly one
    if ($ports.Count -eq 1) {
        $name = if ($portInfo.ContainsKey($ports[0])) { $portInfo[$ports[0]] } else { 'unknown device' }
        Write-OK "Only one COM port present: $($ports[0])  ($name)"
        return $ports[0]
    }

    Write-Warn "Multiple COM ports found, none clearly an ESP32:"
    foreach ($p in $ports) {
        $name = if ($portInfo.ContainsKey($p)) { $portInfo[$p] } else { 'unknown' }
        Write-Info "$p  ($name)"
    }
    Write-Info 'Re-run with -Port COMx to pick one explicitly.'
    return $null
}

# =============================================================================
# 3. Read + show config.h summary
# =============================================================================
function Show-NodeConfig {
    param([int]$NodeNum)

    $configPath = Join-Path $RepoRoot "esp32_node$NodeNum\include\config.h"
    if (-not (Test-Path $configPath)) {
        throw "Config file not found: $configPath"
    }

    $content = Get-Content $configPath -Raw
    $ssid     = if ($content -match '#define\s+WIFI_SSID\s+"([^"]*)"')     { $Matches[1] } else { '?' }
    $password = if ($content -match '#define\s+WIFI_PASSWORD\s+"([^"]*)"') { $Matches[1] } else { '?' }
    $broker   = if ($content -match '#define\s+MQTT_BROKER\s+"([^"]*)"')   { $Matches[1] } else { '?' }
    $nodeId   = if ($content -match '#define\s+NODE_ID\s+"([^"]*)"')       { $Matches[1] } else { '?' }

    Write-Step "Node $NodeNum config (esp32_node$NodeNum/include/config.h):"
    Write-Info "NODE_ID       = $nodeId"
    Write-Info "WIFI_SSID     = $ssid"
    Write-Info "WIFI_PASSWORD = $('*' * $password.Length)  ($($password.Length) chars)"
    Write-Info "MQTT_BROKER   = $broker"

    return @{
        Path     = $configPath
        Ssid     = $ssid
        Password = $password
        Broker   = $broker
        NodeId   = $nodeId
    }
}

# =============================================================================
# 4. Patch config.h in place (only when user supplies new values)
# =============================================================================
function Update-NodeConfig {
    param(
        [string]$Path,
        [string]$NewSsid,
        [string]$NewPassword,
        [string]$NewBroker
    )

    $changed = $false
    $content = Get-Content $Path -Raw

    if ($NewSsid) {
        $content = [regex]::Replace($content,
            '(#define\s+WIFI_SSID\s+")[^"]*(")',
            "`${1}$NewSsid`${2}")
        Write-OK "Updated WIFI_SSID -> $NewSsid"
        $changed = $true
    }
    if ($NewPassword) {
        $content = [regex]::Replace($content,
            '(#define\s+WIFI_PASSWORD\s+")[^"]*(")',
            "`${1}$NewPassword`${2}")
        Write-OK 'Updated WIFI_PASSWORD'
        $changed = $true
    }
    if ($NewBroker) {
        $content = [regex]::Replace($content,
            '(#define\s+MQTT_BROKER\s+")[^"]*(")',
            "`${1}$NewBroker`${2}")
        Write-OK "Updated MQTT_BROKER -> $NewBroker"
        $changed = $true
    }

    if ($changed) {
        # Preserve existing line endings; PowerShell defaults to system line endings
        Set-Content -Path $Path -Value $content -NoNewline
    }
}

# =============================================================================
# 5. Run pio upload
# =============================================================================
function Invoke-Flash {
    param(
        [int]$NodeNum,
        [string]$ComPort,
        [string]$PioCmd
    )

    $nodeDir = Join-Path $RepoRoot "esp32_node$NodeNum"
    Push-Location $nodeDir
    try {
        Write-Step "Building + uploading to node $NodeNum on $ComPort ..."
        Write-Info "Working directory: $nodeDir"
        Write-Info '(First flash on a clean machine: ~10-15 min toolchain download.)'
        Write-Info '(Subsequent flashes: ~30 seconds.)'
        Write-Host ''

        $args = @('run', '--target', 'upload', '--upload-port', $ComPort)
        if ($PioCmd -eq 'python-m-platformio') {
            & python -m platformio @args
        } else {
            & $PioCmd @args
        }
        $exit = $LASTEXITCODE

        Write-Host ''
        if ($exit -eq 0) {
            Write-OK "Node $NodeNum flashed successfully."
            return $true
        } else {
            Write-Fail "Node $NodeNum flash FAILED (exit $exit)."
            Write-Info 'Common fixes:'
            Write-Info '  - Hold the BOOT button on the ESP32 while the upload starts.'
            Write-Info '  - Try a different USB cable (some are charge-only).'
            Write-Info "  - Confirm port: $ComPort is the right one."
            return $false
        }
    } finally {
        Pop-Location
    }
}

# =============================================================================
# 6. Optional: open serial monitor
# =============================================================================
function Invoke-Monitor {
    param([int]$NodeNum, [string]$ComPort, [string]$PioCmd)
    $nodeDir = Join-Path $RepoRoot "esp32_node$NodeNum"
    Push-Location $nodeDir
    try {
        Write-Step "Opening serial monitor on $ComPort (Ctrl+C to exit)..."
        $args = @('device', 'monitor', '--baud', '115200', '--port', $ComPort)
        if ($PioCmd -eq 'python-m-platformio') {
            & python -m platformio @args
        } else {
            & $PioCmd @args
        }
    } finally {
        Pop-Location
    }
}

# =============================================================================
# 7. Flash one node end-to-end (config show + optional patch + flash)
# =============================================================================
function Flash-OneNode {
    param([int]$NodeNum, [string]$ChosenPort, [string]$PioCmd)

    $role = $NodeRoles[$NodeNum]
    Write-Header "Node $NodeNum  -  $role"

    $cfg = Show-NodeConfig -NodeNum $NodeNum

    if ($WifiSsid -or $WifiPassword -or $MqttBroker) {
        Write-Step 'Patching config.h with provided values...'
        Update-NodeConfig -Path $cfg.Path -NewSsid $WifiSsid -NewPassword $WifiPassword -NewBroker $MqttBroker
        # Re-display so the user sees the final values
        $cfg = Show-NodeConfig -NodeNum $NodeNum
    }

    # Resolve port (cached from outer scope, or re-detect if user is swapping cables)
    $port = $ChosenPort
    if (-not $port) {
        $port = Get-Esp32Port
        if (-not $port) { return $false }
    }

    if (-not $Yes) {
        Write-Host ''
        $confirm = Read-Host "Proceed to flash node $NodeNum on $port? (y/N)"
        if ($confirm -notmatch '^y') {
            Write-Warn "Skipped node $NodeNum"
            return $false
        }
    }

    $ok = Invoke-Flash -NodeNum $NodeNum -ComPort $port -PioCmd $PioCmd
    if ($ok -and $Monitor) {
        Invoke-Monitor -NodeNum $NodeNum -ComPort $port -PioCmd $PioCmd
    }
    return $ok
}

# =============================================================================
# Main
# =============================================================================
Write-Header 'Project Spotless - ESP32 Flash Tool'
Write-Host "  Repo root: $RepoRoot" -ForegroundColor Gray

# --- Locate pio ---
$pioCmd = Find-PlatformIO
if (-not $pioCmd) { exit 1 }

# --- Resolve which node(s) ---
if (-not $Node -and -not $Check) {
    Write-Host ''
    $Node = Read-Host 'Which node? (1, 2, 3, or all)'
}

# --- -Check just verifies the toolchain + port and exits ---
if ($Check) {
    $port = Get-Esp32Port
    Write-Host ''
    if ($port) {
        Write-OK "All good. PlatformIO + COM port ($port) ready."
        exit 0
    }
    Write-Warn 'PlatformIO OK, but no ESP32 detected. Plug one in and re-run.'
    exit 1
}

$Node = $Node.ToString().ToLower().Trim()

# --- Single node ---
if ($Node -in $ValidNodes) {
    if ($Port) {
        $present = [System.IO.Ports.SerialPort]::GetPortNames()
        if ($present -notcontains $Port) {
            Write-Fail "Port $Port not found. Present ports: $($present -join ', ')"
            exit 1
        }
        $port = $Port
    } else {
        $port = Get-Esp32Port
    }
    if (-not $port) { exit 1 }
    $ok = Flash-OneNode -NodeNum ([int]$Node) -ChosenPort $port -PioCmd $pioCmd
    exit $(if ($ok) { 0 } else { 1 })
}

# --- All nodes ---
if ($Node -eq 'all') {
    Write-Header 'Flashing all 3 nodes (sequentially)'
    Write-Info 'You will be prompted to swap the USB cable between each node.'
    Write-Info 'The COM port is always auto-redetected after each swap.'
    if ($Port) {
        Write-Warn "-Port $Port was supplied but is IGNORED in 'all' mode (each board has its own port)."
    }

    $results = @{}
    for ($i = 1; $i -le 3; $i++) {
        if ($i -gt 1) {
            Write-Host ''
            Write-Step "Disconnect node $($i-1) and connect node $i  ($($NodeRoles[$i]))"
            Read-Host 'Press Enter when ready'
            Start-Sleep -Seconds 2
        }
        # Always re-detect port between nodes (it usually changes); ignore -Port here
        $port = Get-Esp32Port
        if (-not $port) {
            Write-Fail "No port detected for node $i - skipping."
            $results[$i] = $false
            continue
        }
        $results[$i] = Flash-OneNode -NodeNum $i -ChosenPort $port -PioCmd $pioCmd
    }

    Write-Header 'Summary'
    foreach ($k in $results.Keys | Sort-Object) {
        if ($results[$k]) { Write-OK  "Node $k : flashed" }
        else              { Write-Fail "Node $k : FAILED" }
    }
    $allOk = ($results.Values | Where-Object { $_ -eq $false }).Count -eq 0
    exit $(if ($allOk) { 0 } else { 1 })
}

Write-Fail "Invalid node value: '$Node'. Use 1, 2, 3, or all."
exit 2
