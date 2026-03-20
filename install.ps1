# Maple MCP Server - Installation Script
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

$MapleRoot = "C:\Program Files\Maple 2025"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeConfig = "$env:APPDATA\Claude\claude_desktop_config.json"

Write-Host "=== Maple MCP Server Installation ===" -ForegroundColor Cyan

# 1. Check Maple installation
if (-not (Test-Path "$MapleRoot\bin.X86_64_WINDOWS\cmaple.exe")) {
    Write-Host "ERROR: Maple 2025 not found at $MapleRoot" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Maple 2025 found" -ForegroundColor Green

# 2. Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "ERROR: Python not found. Install Python 3.10+" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python found: $($python.Source)" -ForegroundColor Green

# 3. Check uv
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    & pip install uv 2>$null
}
Write-Host "[OK] uv available" -ForegroundColor Green

# 4. Install package
Write-Host "Installing maple-mcp..." -ForegroundColor Yellow
Push-Location $ProjectDir
& pip install -e . 2>$null
Pop-Location
Write-Host "[OK] maple-mcp installed" -ForegroundColor Green

# 5. Check Java Agent in launch.ini
$launchIni = "$MapleRoot\bin.X86_64_WINDOWS\launch.ini"
$agentJar = "$ProjectDir\reload-agent.jar"
$agentLine = "java_args=-javaagent:$($agentJar -replace '\\','/')"

if (Test-Path $launchIni) {
    $content = Get-Content $launchIni -Raw
    if ($content -match "javaagent.*reload-agent") {
        Write-Host "[OK] Java Agent already in launch.ini" -ForegroundColor Green
    } else {
        Write-Host "Adding Java Agent to launch.ini..." -ForegroundColor Yellow
        Add-Content $launchIni "`n$agentLine"
        Write-Host "[OK] Java Agent added (restart Maple to activate)" -ForegroundColor Green
    }
} else {
    Write-Host "WARNING: launch.ini not found at $launchIni" -ForegroundColor Yellow
}

# 6. Add to Claude Desktop config
if (Test-Path $ClaudeConfig) {
    $config = Get-Content $ClaudeConfig -Raw | ConvertFrom-Json
    if ($config.mcpServers.maple) {
        Write-Host "[OK] maple already in Claude Desktop config" -ForegroundColor Green
    } else {
        Write-Host "Adding maple to Claude Desktop config..." -ForegroundColor Yellow
        $config.mcpServers | Add-Member -NotePropertyName "maple" -NotePropertyValue @{
            command = "uv"
            args = @("--directory", $ProjectDir, "run", "maple-mcp")
        }
        $config | ConvertTo-Json -Depth 10 | Set-Content $ClaudeConfig
        Write-Host "[OK] Added to Claude Desktop (restart Claude Desktop)" -ForegroundColor Green
    }
} else {
    Write-Host "WARNING: Claude Desktop config not found. Add manually:" -ForegroundColor Yellow
    Write-Host @"
  "maple": {
    "command": "uv",
    "args": ["--directory", "$ProjectDir", "run", "maple-mcp"]
  }
"@
}

# 7. Run tests
Write-Host "`nRunning tests..." -ForegroundColor Yellow
Push-Location $ProjectDir
& pip install pytest -q 2>$null
& python -m pytest tests/ -q
Pop-Location

Write-Host "`n=== Installation Complete ===" -ForegroundColor Cyan
Write-Host "Restart Maple and Claude Desktop to use." -ForegroundColor Yellow
