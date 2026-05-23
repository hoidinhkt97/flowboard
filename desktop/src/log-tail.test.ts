import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { readLogTail } from './log-tail';

describe('readLogTail', () => {
  let tmpFile: string;

  beforeEach(() => {
    tmpFile = path.join(os.tmpdir(), `flowboard-test-${Date.now()}-${Math.random()}.log`);
  });

  afterEach(() => {
    if (fs.existsSync(tmpFile)) fs.unlinkSync(tmpFile);
  });

  it('returns empty string if file does not exist', async () => {
    const result = await readLogTail('/nonexistent/path.log', 10);
    expect(result).toBe('');
  });

  it('returns last N lines of a multi-line file', async () => {
    const lines = Array.from({ length: 100 }, (_, i) => `line ${i + 1}`).join('\n');
    fs.writeFileSync(tmpFile, lines);

    const result = await readLogTail(tmpFile, 5);
    const resultLines = result.split('\n').filter(Boolean);
    expect(resultLines).toEqual(['line 96', 'line 97', 'line 98', 'line 99', 'line 100']);
  });

  it('returns entire file if fewer lines than requested', async () => {
    fs.writeFileSync(tmpFile, 'a\nb\nc');
    const result = await readLogTail(tmpFile, 50);
    expect(result.trim()).toBe('a\nb\nc');
  });
});
