import { spawn, ChildProcess } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { findAvailablePort } from './port-finder';
import { waitForHealth } from './health-check';

export interface AgentConfig {
  binaryPath: string;
  storageDir: string;
  logsDir: string;
  startPort: number;
  endPort: number;
  wsPort: number;
  frontendDist?: string; // passed as FLOWBOARD_FRONTEND_DIST when packaged
}

export interface AgentStatus {
  running: boolean;
  httpPort: number | null;
  pid: number | null;
}

export class AgentManager {
  private process: ChildProcess | null = null;
  private httpPort: number | null = null;
  private logStream: fs.WriteStream | null = null;
  private intentionalShutdown = false;
  private onCrash: (() => void) | null = null;

  async start(config: AgentConfig): Promise<{ httpPort: number }> {
    if (this.process) throw new Error('Agent already running');

    if (!fs.existsSync(config.binaryPath)) {
      throw new Error(`Agent binary not found at ${config.binaryPath}`);
    }

    fs.mkdirSync(config.storageDir, { recursive: true });
    fs.mkdirSync(config.logsDir, { recursive: true });

    const httpPort = await findAvailablePort(config.startPort, config.endPort);
    this.httpPort = httpPort;

    const logPath = path.join(config.logsDir, 'agent.log');
    this.logStream = fs.createWriteStream(logPath, { flags: 'a' });
    this.logStream.write(`\n=== Agent start ${new Date().toISOString()} (port ${httpPort}) ===\n`);

    const env: NodeJS.ProcessEnv = {
      ...process.env,
      FLOWBOARD_STORAGE: config.storageDir,
      FLOWBOARD_HTTP_PORT: String(httpPort),
      FLOWBOARD_EXT_WS_PORT: String(config.wsPort),
      FLOWBOARD_WS_HOST: '127.0.0.1',
      PYTHONUNBUFFERED: '1',
      ...(config.frontendDist ? { FLOWBOARD_FRONTEND_DIST: config.frontendDist } : {}),
    };

    this.process = spawn(config.binaryPath, [], {
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: false,
    });

    this.process.stdout?.pipe(this.logStream, { end: false });
    this.process.stderr?.pipe(this.logStream, { end: false });

    this.process.once('exit', (code, signal) => {
      this.logStream?.write(`=== Agent exit code=${code} signal=${signal} ===\n`);
      const wasIntentional = this.intentionalShutdown;
      this.process = null;
      this.httpPort = null;
      this.intentionalShutdown = false;
      if (!wasIntentional && this.onCrash) this.onCrash();
    });

    const healthy = await waitForHealth(`http://127.0.0.1:${httpPort}/api/health`, {
      timeoutMs: 30_000,
      intervalMs: 500,
    });

    if (!healthy) {
      await this.shutdown();
      throw new Error('Agent failed to become healthy within 30s');
    }

    return { httpPort };
  }

  async shutdown(): Promise<void> {
    if (!this.process) return;
    this.intentionalShutdown = true;

    const pid = this.process.pid;
    const exited = new Promise<void>((resolve) => {
      this.process?.once('exit', () => resolve());
    });

    if (process.platform === 'win32' && pid) {
      // Use taskkill /T to kill the process tree (PyInstaller bootloader spawns child)
      spawn('taskkill', ['/PID', String(pid), '/T', '/F']);
    } else {
      this.process.kill('SIGTERM');
    }

    // Wait up to 5 seconds for graceful exit, then force-kill
    const timeout = new Promise<void>((resolve) =>
      setTimeout(() => {
        this.process?.kill('SIGKILL');
        resolve();
      }, 5000)
    );

    await Promise.race([exited, timeout]);
    this.logStream?.end();
    this.logStream = null;
  }

  setCrashHandler(handler: () => void): void {
    this.onCrash = handler;
  }

  getStatus(): AgentStatus {
    return {
      running: this.process !== null,
      httpPort: this.httpPort,
      pid: this.process?.pid ?? null,
    };
  }
}
