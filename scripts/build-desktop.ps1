#!/usr/bin/env pwsh
# Build the Flowboard desktop app for Windows.
# Output: desktop\release\Flowboard-Setup-<version>.exe

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')

Write-Host "=== Flowboard desktop build (Windows) ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"

# Step 1: Build frontend
Write-Host "`n[1/4] Building frontend..." -ForegroundColor Yellow
Set-Location (Join-Path $RepoRoot 'frontend')
npm ci
npm run build
if (-not (Test-Path 'dist/index.html')) {
    throw "Frontend build failed: dist/index.html not found"
}

# Step 2: Build agent binary
Write-Host "`n[2/4] Building Python agent (PyInstaller)..." -ForegroundColor Yellow
Set-Location (Join-Path $RepoRoot 'agent')
pip install -e . --quiet
pip install pyinstaller --quiet
pyinstaller flowboard-agent.spec --clean --noconfirm
if (-not (Test-Path 'dist\flowboard-agent\flowboard-agent.exe')) {
    throw "Agent build failed: flowboard-agent.exe not found"
}

# Step 3: Compile Electron TypeScript
Write-Host "`n[3/4] Compiling Electron TypeScript..." -ForegroundColor Yellow
Set-Location (Join-Path $RepoRoot 'desktop')
npm ci
npm run build
if (-not (Test-Path 'dist\main.js')) {
    throw "Electron TS build failed: dist\main.js not found"
}

# Step 4: Package with electron-builder
Write-Host "`n[4/4] Packaging with electron-builder..." -ForegroundColor Yellow
npm run dist:win

$installer = Get-ChildItem 'release\*.exe' | Select-Object -First 1
if ($installer) {
    Write-Host "`n=== Build complete ===" -ForegroundColor Green
    Write-Host "Installer: $($installer.FullName)" -ForegroundColor Green
    Write-Host "Size: $([math]::Round($installer.Length / 1MB, 1)) MB"
} else {
    throw "electron-builder did not produce an installer"
}
