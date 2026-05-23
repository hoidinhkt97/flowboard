import { describe, it, expect } from 'vitest';
import * as http from 'http';
import { waitForHealth } from './health-check';

function startMockServer(port: number, responder: (req: http.IncomingMessage, res: http.ServerResponse) => void): http.Server {
  const server = http.createServer(responder);
  server.listen(port, '127.0.0.1');
  return server;
}

describe('waitForHealth', () => {
  it('resolves true when health endpoint returns ok', async () => {
    const server = startMockServer(19101, (_, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true }));
    });
    try {
      const result = await waitForHealth('http://127.0.0.1:19101/api/health', { timeoutMs: 3000, intervalMs: 100 });
      expect(result).toBe(true);
    } finally {
      server.close();
    }
  });

  it('resolves false when timeout exceeded with no server', async () => {
    const result = await waitForHealth('http://127.0.0.1:19102/api/health', { timeoutMs: 500, intervalMs: 100 });
    expect(result).toBe(false);
  });

  it('keeps polling on connection refused, resolves when server becomes available', async () => {
    let server: http.Server | null = null;
    setTimeout(() => {
      server = startMockServer(19103, (_, res) => {
        res.writeHead(200);
        res.end(JSON.stringify({ ok: true }));
      });
    }, 300);

    const result = await waitForHealth('http://127.0.0.1:19103/api/health', { timeoutMs: 2000, intervalMs: 100 });
    expect(result).toBe(true);
    server?.close();
  });
});
