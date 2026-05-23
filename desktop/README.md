# Flowboard Desktop

Electron wrapper that packages Flowboard (React SPA + FastAPI agent) into a cross-platform desktop application for Windows and macOS.

## Architecture

```
Electron main process
├── Spawns flowboard-agent (PyInstaller-bundled FastAPI) on localhost:8101
├── Opens splash window during startup
├── Opens main BrowserWindow loading http://127.0.0.1:8101/app/
└── Forwards agent stdout/stderr to userData/logs/agent.log
```

The Chrome Extension dependency is preserved — users still install the extension as before for Google Flow auth.

## Data Storage

User data (SQLite DB + media) is stored at:

| OS      | Path                                                       |
|---------|------------------------------------------------------------|
| Windows | `%APPDATA%\flowboard-desktop\storage\`                     |
| macOS   | `~/Library/Application Support/flowboard-desktop/storage/` |

Logs at the same parent path under `logs/`.

## Development

Run the agent, frontend, and Electron separately:

```bash
# Terminal 1: agent
cd agent
uvicorn flowboard.main:app --reload --port 8101

# Terminal 2: frontend (build once; rebuild on UI changes)
cd frontend
npm run build   # served by agent at /app/

# Terminal 3: Electron
cd desktop
npm run dev     # sets FLOWBOARD_DEV=1, skips agent spawn
```

`FLOWBOARD_DEV=1` makes Electron skip spawning the agent binary and assume the agent is already running on port 8101.

## Production Build

### Windows

```powershell
.\scripts\build-desktop.ps1
```

Output: `desktop\release\Flowboard-Setup-<version>.exe`

### macOS

```bash
./scripts/build-desktop.sh
```

Output: `desktop/release/Flowboard-<version>-<arch>.dmg`

> PyInstaller does not cross-compile. Windows binaries must be built on Windows; macOS binaries must be built on macOS.

## Testing

```bash
cd desktop
npm test       # vitest unit tests: paths, port-finder, log-tail, health-check
```

Smoke testing the built installer is manual — see the checklist in the implementation plan tasks 15 / 16.

## Bundle Size

Approximate:
- Electron framework: ~150 MB
- PyInstaller agent (onedir): ~80-120 MB
- Frontend dist: ~5 MB
- Total installed: ~250-300 MB
- Installer size: ~100-150 MB

## Troubleshooting

**"Agent failed to start within 30s"**
- Check `userData/logs/agent.log` for Python errors
- Common cause: missing `hiddenimports` in `agent/flowboard-agent.spec`. Add the failing module and rebuild.

**Zombie agent process after quit**
- On Windows: ensure `taskkill /T` runs (process tree kill — `AgentManager.shutdown` does this)
- On POSIX: SIGTERM then SIGKILL after 5s

**Port 8101 already in use**
- The app tries 8101 → 8110 automatically. If all blocked, free one or change `startPort`/`endPort` in `main.ts`.

**Chrome Extension can't connect**
- Verify agent is running: `curl http://127.0.0.1:8101/api/health`
- Verify extension WS port is open: agent log should show "extension WS listening on 127.0.0.1:9223"

## Distribution

This build is internal use only:
- No code signing → Windows SmartScreen and macOS Gatekeeper will warn on first launch
- No auto-update mechanism
- No installer signing

For public distribution, additional work is needed: signing certs, notarization (macOS), and an auto-update channel.
