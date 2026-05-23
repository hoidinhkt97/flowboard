import * as net from 'net';

export function isPortAvailable(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port, '127.0.0.1');
  });
}

export async function findAvailablePort(start: number, end: number): Promise<number> {
  for (let p = start; p <= end; p++) {
    if (await isPortAvailable(p)) return p;
  }
  throw new Error(`No available port in range ${start}-${end}`);
}
