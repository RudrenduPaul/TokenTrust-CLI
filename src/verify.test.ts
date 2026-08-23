import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { LiveApiCall } from './categories/tt02_cost_delta.js';
import { LIVE_API_KEY_ENV_VAR } from './categories/tt02_cost_delta.js';
import { FakeAdapter } from './test-support/fake-adapter.js';
import { ProxyExecutionError } from './adapters/types.js';
import type { ProxyAdapter, AdapterResult, ProxyName } from './adapters/types.js';
import type { Task } from './tasks/types.js';
import { resolveDefaultTasksPath, runVerify } from './verify.js';
import type { VerifyDependencies, VerifyOptions } from './verify.js';

describe('runVerify', () => {
  let repoDir: string;
  let printed: string[];

  beforeEach(() => {
    repoDir = mkdtempSync(join(tmpdir(), 'tokentrust-verify-'));
    printed = [];
  });

  afterEach(() => {
    rmSync(repoDir, { recursive: true, force: true });
  });

  function baseOptions(overrides: Partial<VerifyOptions> = {}): VerifyOptions {
    return {
      proxies: ['rtk'],
      repo: repoDir,
      tasksPath: resolveDefaultTasksPath(),
      live: false,
      confirmCost: false,
      liveMaxTasks: 5,
      format: 'terminal',
      ...overrides,
    };
  }

  function baseDeps(overrides: Partial<VerifyDependencies> = {}): VerifyDependencies {
    return {
      getAdapter: () =>
        new FakeAdapter('rtk', { baseline: () => 'token '.repeat(50), compressed: () => 'token '.repeat(20) }),
      now: () => new Date('2026-07-11T09:14:52.000Z'),
      print: (line: string) => printed.push(line),
      storePath: join(repoDir, '.tokentrust', 'report-store.json'),
      reportOutPath: join(repoDir, 'tokentrust-report-2026-07-11.json'),
      env: {},
      ...overrides,
    };
  }

  describe('cold-start: bundled default 23-task corpus with zero extra flags (E2E)', () => {
    it('produces a full report and prints the champion-tier terminal summary', async () => {
      const outcome = await runVerify(baseOptions(), baseDeps());

      expect(outcome.exitCode).toBe(0);
      expect(outcome.report?.task_corpus_size).toBe(23);
      expect(outcome.report?.records.length).toBeGreaterThan(0);
      expect(printed.some((line) => line.includes('Measuring...'))).toBe(true);
      expect(printed.some((line) => line.includes('TokenTrust v0.1'))).toBe(true);
      expect(printed.some((line) => line.includes('Report:'))).toBe(true);
    });

    // NOTE: rtk and headroom are the only two
    // ProxyName values, and headroom is unconditionally intercepted by
    // the "not yet supported" gate below before it is ever dispatched -- so
    // there is no longer a way to get two REAL, simultaneously-dispatched
    // adapters through runVerify() in v0.1 to exercise an end-to-end TT04
    // run. TT04's own aggregation/mismatch logic is still fully covered at
    // the unit level in src/categories/tt04_cross_tool_benchmark.test.ts
    // (using rtk + headroom fixtures directly, bypassing runVerify's gate).
    // This integration-level scenario becomes reachable again once a second
    // proxy is actually dispatchable (e.g. headroom's HTTP-proxy harness, or
    // a newly added proxy).
  });

  describe(
    'printProgress injection (regression -- report/terminal.ts printProgress() writes straight to ' +
      'process.stdout, bypassing the print() dependency entirely; a stdio-transport caller like the MCP ' +
      'server needs to redirect this too, not just print())',
    () => {
      it('deps.printProgress, when supplied, is called instead of the process.stdout default', async () => {
        const progressCalls: Array<{ done: number; total: number }> = [];
        const outcome = await runVerify(
          baseOptions(),
          baseDeps({ printProgress: (done, total) => progressCalls.push({ done, total }) }),
        );

        expect(outcome.exitCode).toBe(0);
        expect(progressCalls.length).toBeGreaterThan(0);
        expect(progressCalls[progressCalls.length - 1]).toEqual({ done: 23, total: 23 });
      });

      it('omitting deps.printProgress does not throw (falls back to the real terminal printProgress)', async () => {
        const outcome = await runVerify(baseOptions(), baseDeps());
        expect(outcome.exitCode).toBe(0);
      });
    },
  );

  describe('CRITICAL: missing-binary error path', () => {
    it('exits 1 and prints the locked verbatim message when the proxy is not installed, makes no report', async () => {
      const adapter = new FakeAdapter('rtk', { baseline: () => '', compressed: () => '' });
      adapter.installed = false;
      const outcome = await runVerify(baseOptions(), baseDeps({ getAdapter: () => adapter }));

      expect(outcome.exitCode).toBe(1);
      expect(outcome.report).toBeUndefined();
      expect(
        printed.some((line) =>
          line.includes('rtk not found on PATH. Install:') && line.includes('Then re-run this command.'),
        ),
      ).toBe(true);
    });
  });

  describe('CRITICAL: report-store corruption graceful degradation', () => {
    it('still produces a full report when the store file is corrupted, instead of crashing', async () => {
      const storePath = join(repoDir, '.tokentrust', 'report-store.json');
      mkdirSync(join(repoDir, '.tokentrust'), { recursive: true });
      writeFileSync(storePath, '{ not valid json', 'utf8');

      const outcome = await runVerify(baseOptions(), baseDeps({ storePath }));

      expect(outcome.exitCode).toBe(0);
      expect(outcome.report?.tt05.rtk?.degraded).toBe(true);
      expect(outcome.report?.tt05.rtk?.message).toContain('No drift comparison available');
    });
  });

  describe('CRITICAL: --live safety flag-combination matrix (E2E)', () => {
    it('no --live flag: the live API client is never invoked', async () => {
      const liveApiClient = vi.fn();
      const outcome = await runVerify(baseOptions({ live: false }), baseDeps({ liveApiClient }));
      expect(outcome.exitCode).toBe(0);
      expect(liveApiClient).not.toHaveBeenCalled();
    });

    it('--live alone (no --confirm-cost): exits 1, prints the cost estimate, makes ZERO API calls', async () => {
      const liveApiClient = vi.fn();
      const outcome = await runVerify(
        baseOptions({ live: true, confirmCost: false }),
        baseDeps({ liveApiClient, env: { [LIVE_API_KEY_ENV_VAR]: 'sk-should-not-be-used' } }),
      );

      expect(outcome.exitCode).toBe(1);
      expect(liveApiClient).not.toHaveBeenCalled();
      expect(printed.some((line) => line.includes('--confirm-cost'))).toBe(true);
    });

    it('--live --confirm-cost but task count exceeds --live-max-tasks: exits 1, makes ZERO API calls', async () => {
      const liveApiClient = vi.fn();
      // Bundled corpus has 23 tasks; cap of 5 forces the over-cap refusal path.
      const outcome = await runVerify(
        baseOptions({ live: true, confirmCost: true, liveMaxTasks: 5 }),
        baseDeps({ liveApiClient, env: { [LIVE_API_KEY_ENV_VAR]: 'sk-should-not-be-used' } }),
      );

      expect(outcome.exitCode).toBe(1);
      expect(liveApiClient).not.toHaveBeenCalled();
      expect(printed.some((line) => line.includes('exceeds --live-max-tasks'))).toBe(true);
    });

    it('--live --confirm-cost within the cap and API key present: proceeds and calls the live API client', async () => {
      const liveApiClient = vi.fn(async (taskId: string): Promise<LiveApiCall> => ({ taskId, billedInputTokens: 42 }));
      const outcome = await runVerify(
        baseOptions({ live: true, confirmCost: true, liveMaxTasks: 25 }),
        baseDeps({ liveApiClient, env: { [LIVE_API_KEY_ENV_VAR]: 'sk-real-looking-key' } }),
      );

      expect(outcome.exitCode).toBe(0);
      expect(liveApiClient).toHaveBeenCalled();
      expect(printed.some((line) => line.includes('Live mode confirmed'))).toBe(true);
    });

    it('--live --confirm-cost within cap but NO API key set: exits 1, makes ZERO API calls', async () => {
      const liveApiClient = vi.fn();
      const outcome = await runVerify(
        baseOptions({ live: true, confirmCost: true, liveMaxTasks: 25 }),
        baseDeps({ liveApiClient, env: {} }),
      );

      expect(outcome.exitCode).toBe(1);
      expect(liveApiClient).not.toHaveBeenCalled();
      expect(printed.some((line) => line.includes(LIVE_API_KEY_ENV_VAR))).toBe(true);
    });

    // NOTE: rtk and headroom are the only two
    // ProxyName values, and headroom is unconditionally gated out
    // before dispatch (see the 'headroom: v0.1 CLI-level not-yet-supported
    // gate' tests below) -- so there is no longer a pairing of two REAL,
    // simultaneously-dispatched proxies to exercise the "--live warns which
    // additional proxies are NOT live-verified" message. The test below
    // instead confirms the actual current behavior: --proxy rtk --proxy
    // headroom with --live still only ever dispatches rtk, so the
    // multi-proxy live warning never fires.
    it('--live --proxy rtk --proxy headroom: headroom is gated out before dispatch, so only rtk is ever live-verified and no multi-proxy warning fires', async () => {
      const liveApiClient = vi.fn(async (taskId: string): Promise<LiveApiCall> => ({ taskId, billedInputTokens: 42 }));
      const getAdapter = vi.fn((name: ProxyName) =>
        new FakeAdapter(name, { baseline: () => 'x'.repeat(100), compressed: () => 'x'.repeat(60) }),
      );
      const outcome = await runVerify(
        baseOptions({ proxies: ['rtk', 'headroom'], live: true, confirmCost: true, liveMaxTasks: 25 }),
        baseDeps({
          getAdapter,
          liveApiClient,
          env: { [LIVE_API_KEY_ENV_VAR]: 'sk-real-looking-key' },
        }),
      );

      expect(outcome.exitCode).toBe(0);
      expect(liveApiClient).toHaveBeenCalled();
      expect(getAdapter).not.toHaveBeenCalledWith('headroom');
      expect(printed.some((line) => line.includes('--live only verifies the first proxy'))).toBe(false);
    });
  });

  describe(
    'CRITICAL: proxy execution failure path (regression -- a failed compress invocation must never be ' +
      'reported as an implausible ~100% reduction)',
    () => {
      it('exits 1 with a readable error and produces NO report when the compress command fails', async () => {
        class FailingCompressAdapter implements ProxyAdapter {
          readonly name = 'rtk' as const;
          readonly binaryName = 'rtk';
          readonly installCommand = 'echo install';
          async isInstalled(): Promise<boolean> {
            return true;
          }
          async getVersion(): Promise<string> {
            return '2.4.1';
          }
          async run(task: Task, mode: 'compressed' | 'baseline'): Promise<AdapterResult> {
            if (mode === 'baseline') {
              return { rawOutput: 'token '.repeat(50), proxyVersion: '2.4.1', durationMs: 1 };
            }
            throw new ProxyExecutionError('rtk', 'rtk', ['compress', '--stdin'], 2, 'unrecognized argument --stdin');
          }
        }

        const outcome = await runVerify(baseOptions(), baseDeps({ getAdapter: () => new FailingCompressAdapter() }));

        expect(outcome.exitCode).toBe(1);
        expect(outcome.report).toBeUndefined();
        expect(printed.some((line) => line.startsWith('Error:') && line.includes('exited with code 2'))).toBe(true);
        // No printed line should contain a fabricated 100%-style reduction summary.
        expect(printed.some((line) => line.includes('TokenTrust v0.1'))).toBe(false);
      });
    },
  );

  describe(
    'CRITICAL: proxy execution failure surfaced from TT03 (never-worse guard also must not swallow a ' +
      'failed compress invocation)',
    () => {
      it('exits 1 with a readable error when TT03 (not TT01) is the call that hits the failing compress command', async () => {
        const tasksPath = join(repoDir, 'one-task.yml');
        writeFileSync(
          tasksPath,
          [
            'version: 1',
            'tasks:',
            '  - id: has-markers',
            '    description: "d"',
            '    fixture_repo: .',
            '    prompt: "p"',
            '    difficulty: easy',
            '    quality_markers:',
            '      - "marker"',
          ].join('\n'),
          'utf8',
        );

        let compressedCalls = 0;
        class TransientlyFailingAdapter implements ProxyAdapter {
          readonly name = 'rtk' as const;
          readonly binaryName = 'rtk';
          readonly installCommand = 'echo install';
          async isInstalled(): Promise<boolean> {
            return true;
          }
          async getVersion(): Promise<string> {
            return '2.4.1';
          }
          async run(task: Task, mode: 'compressed' | 'baseline'): Promise<AdapterResult> {
            if (mode === 'baseline') {
              return { rawOutput: 'token '.repeat(50), proxyVersion: '2.4.1', durationMs: 1 };
            }
            compressedCalls += 1;
            // First compressed call is TT01's -- let it succeed so TT01/TT02
            // complete normally. TT03's compressed call (triggered by this
            // task's quality_markers) is the one that fails.
            if (compressedCalls === 1) {
              return { rawOutput: 'token '.repeat(20), proxyVersion: '2.4.1', durationMs: 1 };
            }
            throw new ProxyExecutionError('rtk', 'rtk', ['compress', '--stdin'], 1, 'transient failure');
          }
        }

        const outcome = await runVerify(
          baseOptions({ tasksPath }),
          baseDeps({ getAdapter: () => new TransientlyFailingAdapter() }),
        );

        expect(outcome.exitCode).toBe(1);
        expect(outcome.report).toBeUndefined();
        expect(printed.some((line) => line.startsWith('Error:') && line.includes('transient failure'))).toBe(true);
      });
    },
  );

  describe('task schema errors', () => {
    it('exits 1 with a readable error when the task corpus file is invalid', async () => {
      const badPath = join(repoDir, 'bad-tasks.yml');
      writeFileSync(badPath, 'not: [valid', 'utf8');
      const outcome = await runVerify(baseOptions({ tasksPath: badPath }), baseDeps());
      expect(outcome.exitCode).toBe(1);
      expect(printed.some((line) => line.startsWith('Error:'))).toBe(true);
    });
  });

  describe('format: json', () => {
    it('prints the serialized report instead of the terminal summary', async () => {
      const outcome = await runVerify(baseOptions({ format: 'json' }), baseDeps());
      expect(outcome.exitCode).toBe(0);
      const jsonLine = printed.find((line) => line.trim().startsWith('{'));
      expect(jsonLine).toBeDefined();
      expect(() => JSON.parse(jsonLine!)).not.toThrow();
    });
  });

  describe('headroom: v0.1 CLI-level not-yet-supported gate', () => {
    it('--proxy headroom alone: exits 1 with the documented message, never constructs the headroom adapter', async () => {
      const getAdapter = vi.fn((name: ProxyName) =>
        new FakeAdapter(name, { baseline: () => '', compressed: () => '' }),
      );
      const outcome = await runVerify(baseOptions({ proxies: ['headroom'] }), baseDeps({ getAdapter }));

      expect(outcome.exitCode).toBe(1);
      expect(outcome.report).toBeUndefined();
      expect(getAdapter).not.toHaveBeenCalledWith('headroom');
      expect(printed.some((line) => line.includes('HTTP proxy server') && line.toLowerCase().includes('not yet'))).toBe(
        true,
      );
    });

    it('--proxy rtk --proxy headroom: rtk still verifies and produces a report; headroom prints its message but does not block', async () => {
      const getAdapter = vi.fn((name: ProxyName) =>
        name === 'rtk'
          ? new FakeAdapter('rtk', { baseline: () => 'token '.repeat(50), compressed: () => 'token '.repeat(20) })
          : new FakeAdapter(name, { baseline: () => '', compressed: () => '' }),
      );
      const outcome = await runVerify(baseOptions({ proxies: ['rtk', 'headroom'] }), baseDeps({ getAdapter }));

      expect(outcome.exitCode).toBe(0);
      expect(outcome.report).toBeDefined();
      expect(outcome.report?.proxies).toEqual(['rtk']);
      expect(getAdapter).not.toHaveBeenCalledWith('headroom');
      expect(printed.some((line) => line.toLowerCase().includes('not yet'))).toBe(true);
    });
  });
});
