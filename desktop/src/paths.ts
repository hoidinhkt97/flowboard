import * as path from 'path';

export interface PathContext {
  platform: NodeJS.Platform;
  isPackaged: boolean;
  resourcesPath: string;
  appPath: string;
}

function pathFor(platform: NodeJS.Platform): path.PlatformPath {
  return platform === 'win32' ? path.win32 : path.posix;
}

export function resolveAgentBinaryPath(ctx: PathContext): string {
  const p = pathFor(ctx.platform);
  const ext = ctx.platform === 'win32' ? '.exe' : '';
  const binaryName = `flowboard-agent${ext}`;

  if (ctx.isPackaged) {
    return p.join(ctx.resourcesPath, 'agent', binaryName);
  }

  // Dev mode: <repo>/agent/dist/flowboard-agent/<binaryName>
  // appPath in dev = <repo>/desktop, so go up one level to repo root
  const repoRoot = p.resolve(ctx.appPath, '..');
  return p.join(repoRoot, 'agent', 'dist', 'flowboard-agent', binaryName);
}

export function getFrontendUrl(ctx: PathContext): string {
  if (ctx.isPackaged) {
    const p = pathFor(ctx.platform);
    const indexHtml = p.join(ctx.resourcesPath, 'frontend', 'index.html');
    return `file://${indexHtml}`;
  }
  return 'http://127.0.0.1:8101/app/';
}
