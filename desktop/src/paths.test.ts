import { describe, it, expect } from 'vitest';
import { resolveAgentBinaryPath } from './paths';

describe('resolveAgentBinaryPath', () => {
  it('returns .exe path on Windows in packaged mode', () => {
    const result = resolveAgentBinaryPath({
      platform: 'win32',
      isPackaged: true,
      resourcesPath: 'C:\\Program Files\\Flowboard\\resources',
      appPath: 'C:\\Program Files\\Flowboard\\resources\\app',
    });
    expect(result).toBe('C:\\Program Files\\Flowboard\\resources\\agent\\flowboard-agent.exe');
  });

  it('returns binary without extension on macOS in packaged mode', () => {
    const result = resolveAgentBinaryPath({
      platform: 'darwin',
      isPackaged: true,
      resourcesPath: '/Applications/Flowboard.app/Contents/Resources',
      appPath: '/Applications/Flowboard.app/Contents/Resources/app',
    });
    expect(result).toBe('/Applications/Flowboard.app/Contents/Resources/agent/flowboard-agent');
  });

  it('returns dev path when not packaged', () => {
    const result = resolveAgentBinaryPath({
      platform: 'win32',
      isPackaged: false,
      resourcesPath: '',
      appPath: 'D:\\Workspace\\flowboard-ai\\desktop',
    });
    expect(result).toBe('D:\\Workspace\\flowboard-ai\\agent\\dist\\flowboard-agent\\flowboard-agent.exe');
  });
});
