#!/usr/bin/env bash
# Build the Flowboard desktop app for macOS.
# Output: desktop/release/Flowboard-<version>-<arch>.dmg

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Flowboard desktop build (macOS) ==="
echo "Repo: $REPO_ROOT"

# Step 1: Build frontend
echo ""
echo "[1/4] Building frontend..."
cd "$REPO_ROOT/frontend"
npm ci
npm run build
test -f dist/index.html || { echo "Frontend build failed"; exit 1; }

# Step 2: Build agent binary
echo ""
echo "[2/4] Building Python agent (PyInstaller)..."
cd "$REPO_ROOT/agent"
# Ensure a Python virtualenv exists and use it (prefer python3)
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "No python executable found (python3 or python)"
    exit 1
fi
if [ ! -d .venv ]; then
    $PY -m venv .venv
fi
. .venv/bin/activate
pip install -e . --quiet
pip install pyinstaller --quiet
# Call PyInstaller via module to ensure the venv's PyInstaller is used
python -m PyInstaller flowboard-agent.spec --clean --noconfirm
test -f dist/flowboard-agent/flowboard-agent || { echo "Agent build failed"; exit 1; }

# Step 3: Compile Electron TypeScript
echo ""
echo "[3/4] Compiling Electron TypeScript..."
cd "$REPO_ROOT/desktop"
npm ci
npm run build
test -f dist/main.js || { echo "Electron TS build failed"; exit 1; }

# Step 4: Package with electron-builder
echo ""
echo "[4/4] Packaging with electron-builder..."
npm run dist:mac

dmg=$(ls release/*.dmg 2>/dev/null | head -n1)
if [[ -z "$dmg" ]]; then
    echo "electron-builder did not produce a DMG"
    exit 1
fi

echo ""
echo "=== Build complete ==="
echo "DMG: $dmg"
echo "Size: $(du -h "$dmg" | cut -f1)"
