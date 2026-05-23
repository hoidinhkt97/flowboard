import { describe, it, expect } from 'vitest';
import * as net from 'net';
import { findAvailablePort } from './port-finder';

function occupyPort(port: number): Promise<net.Server> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => resolve(server));
  });
}

describe('findAvailablePort', () => {
  it('returns the first port if it is free', async () => {
    const port = await findAvailablePort(18101, 18110);
    expect(port).toBe(18101);
  });

  it('skips occupied ports and returns the next free one', async () => {
    const blocker = await occupyPort(18201);
    try {
      const port = await findAvailablePort(18201, 18210);
      expect(port).toBe(18202);
    } finally {
      blocker.close();
    }
  });

  it('throws when no port is available in range', async () => {
    const b1 = await occupyPort(18301);
    const b2 = await occupyPort(18302);
    try {
      await expect(findAvailablePort(18301, 18302)).rejects.toThrow(/no available port/i);
    } finally {
      b1.close();
      b2.close();
    }
  });
});
