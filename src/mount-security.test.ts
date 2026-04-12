import fs from 'fs';
import os from 'os';
import path from 'path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock config before importing the module under test
vi.mock('./config.js', () => ({
  MOUNT_ALLOWLIST_PATH: '/tmp/test-mount-allowlist.json',
}));

// Suppress pino logging in tests
vi.mock('pino', () => {
  const noop = () => {};
  const logger = {
    info: noop,
    warn: noop,
    error: noop,
    debug: noop,
  };
  return { default: () => logger };
});

// Dynamic import so mocks are in place
const {
  loadMountAllowlist,
  validateMount,
  validateAdditionalMounts,
  generateAllowlistTemplate,
} = await import('./mount-security.js');

const ALLOWLIST_PATH = '/tmp/test-mount-allowlist.json';

let tmpDir: string;

function writeAllowlist(config: unknown): void {
  fs.writeFileSync(ALLOWLIST_PATH, JSON.stringify(config));
}

function resetCache(): void {
  // Force reload by re-importing (the module caches in module-level vars).
  // We use a workaround: clear the cached values via a fresh load.
  // Since the module caches, we need to reset the module registry.
  vi.resetModules();
}

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mount-sec-test-'));
  // Clean up any stale allowlist
  try {
    fs.unlinkSync(ALLOWLIST_PATH);
  } catch {}
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
  try {
    fs.unlinkSync(ALLOWLIST_PATH);
  } catch {}
});

describe('loadMountAllowlist (via validateMount)', () => {
  it('returns blocked when no allowlist file exists', async () => {
    // Re-import to get fresh module state (cache cleared)
    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: tmpDir, readonly: true },
      true,
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('No mount allowlist configured');
  });
});

describe('validateMount', () => {
  // For each test we re-import the module to reset the cache

  it('allows a valid mount under an allowed root', async () => {
    // Create a sub-directory to mount
    const subDir = path.join(tmpDir, 'myproject');
    fs.mkdirSync(subDir);

    writeAllowlist({
      allowedRoots: [
        { path: tmpDir, allowReadWrite: true, description: 'test root' },
      ],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: subDir, containerPath: 'myproject', readonly: true },
      true,
    );
    expect(result.allowed).toBe(true);
    expect(result.reason).toContain('Allowed under root');
    expect(result.realHostPath).toBe(fs.realpathSync(subDir));
    expect(result.resolvedContainerPath).toBe('myproject');
  });

  it('rejects path traversal in container path', async () => {
    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: tmpDir, containerPath: '../escape' },
      true,
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('..');
  });

  it('rejects absolute container path', async () => {
    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: tmpDir, containerPath: '/etc/passwd' },
      true,
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('Invalid container path');
  });

  it('rejects empty container path', async () => {
    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: tmpDir, containerPath: '  ' },
      true,
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('Invalid container path');
  });

  it('rejects host path that does not exist', async () => {
    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      {
        hostPath: path.join(tmpDir, 'nonexistent'),
        containerPath: 'data',
      },
      true,
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('does not exist');
  });

  it('rejects paths matching blocked patterns', async () => {
    const sshDir = path.join(tmpDir, '.ssh');
    fs.mkdirSync(sshDir);

    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: sshDir, containerPath: 'ssh' },
      true,
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('blocked pattern');
    expect(result.reason).toContain('.ssh');
  });

  it('rejects paths matching custom blocked patterns', async () => {
    const secretDir = path.join(tmpDir, 'my-token-dir');
    fs.mkdirSync(secretDir);

    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: ['token'],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: secretDir, containerPath: 'data' },
      true,
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('blocked pattern');
  });

  it('rejects paths not under any allowed root', async () => {
    // Allowed root is tmpDir, but we try to mount /tmp itself
    const otherDir = fs.mkdtempSync(path.join(os.tmpdir(), 'other-'));

    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: otherDir, containerPath: 'data' },
      true,
    );
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('not under any allowed root');

    fs.rmSync(otherDir, { recursive: true, force: true });
  });

  it('enforces nonMainReadOnly for non-main groups', async () => {
    const subDir = path.join(tmpDir, 'proj');
    fs.mkdirSync(subDir);

    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: true,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: subDir, containerPath: 'proj', readonly: false },
      false, // not main
    );
    expect(result.allowed).toBe(true);
    expect(result.effectiveReadonly).toBe(true);
  });

  it('allows read-write for main group when nonMainReadOnly is true', async () => {
    const subDir = path.join(tmpDir, 'proj');
    fs.mkdirSync(subDir);

    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: true,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: subDir, containerPath: 'proj', readonly: false },
      true, // main
    );
    expect(result.allowed).toBe(true);
    expect(result.effectiveReadonly).toBe(false);
  });

  it('forces read-only when root does not allow read-write', async () => {
    const subDir = path.join(tmpDir, 'proj');
    fs.mkdirSync(subDir);

    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: false }],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount(
      { hostPath: subDir, containerPath: 'proj', readonly: false },
      true,
    );
    expect(result.allowed).toBe(true);
    expect(result.effectiveReadonly).toBe(true);
  });

  it('defaults containerPath to basename of hostPath', async () => {
    const subDir = path.join(tmpDir, 'mydata');
    fs.mkdirSync(subDir);

    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const result = mod.validateMount({ hostPath: subDir }, true);
    expect(result.allowed).toBe(true);
    expect(result.resolvedContainerPath).toBe('mydata');
  });
});

describe('validateAdditionalMounts', () => {
  it('returns only valid mounts', async () => {
    const goodDir = path.join(tmpDir, 'good');
    fs.mkdirSync(goodDir);

    writeAllowlist({
      allowedRoots: [{ path: tmpDir, allowReadWrite: true }],
      blockedPatterns: [],
      nonMainReadOnly: false,
    });

    vi.resetModules();
    const mod = await import('./mount-security.js');
    const results = mod.validateAdditionalMounts(
      [
        { hostPath: goodDir, containerPath: 'good', readonly: true },
        {
          hostPath: path.join(tmpDir, 'nonexistent'),
          containerPath: 'bad',
          readonly: true,
        },
      ],
      'test-group',
      true,
    );
    expect(results).toHaveLength(1);
    expect(results[0].containerPath).toBe('/workspace/extra/good');
    expect(results[0].readonly).toBe(true);
  });
});

describe('generateAllowlistTemplate', () => {
  it('generates valid JSON', () => {
    const template = generateAllowlistTemplate();
    const parsed = JSON.parse(template);
    expect(parsed.allowedRoots).toBeInstanceOf(Array);
    expect(parsed.blockedPatterns).toBeInstanceOf(Array);
    expect(typeof parsed.nonMainReadOnly).toBe('boolean');
  });
});
