/**
 * #1012 — fix-findings.json docker bind-mount footgun.
 *
 * Docker auto-creates a *directory* when a host file path in `-v host:container`
 * does not exist. Later host `open()` / `writeFileSync` then throw EISDIR;
 * mechanical retry used to burn all six process-root attempts on the same
 * durable host-FS error.
 *
 * DELETE-preferring fix: ensure the host path is a regular file before
 * write/mount (clear leftover dirs; touch if missing). No content-pin tests.
 */

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { legacyDispatchWorker } from "../../src/dispatchWorker.js";
import {
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../../src/dispatchRetry.js";
import {
  ensureRegularFileForBindMount,
  isEisdirClassHostFsError,
} from "../../src/fsErrors.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

const S5_CODER: WorkerSpec = {
  id: "S5",
  kind: "coder",
  role: "coder",
  host: "codex",
  session: "fresh",
  contextRetention: "retain",
  skill: "/tdd",
  promptFile: "coder_fix.md",
  maxIter: 1,
  model: "gpt-5.6-sol",
  soul: "coder",
  toolchain: [],
};

const FINDING: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "clear the directory placeholder",
  location: "src/x.ts:1",
  suggested_fix: "ensure regular file",
  action: "fix_now",
};

function mockBackend(
  onRun: Backend["runStep"],
): Backend {
  return {
    async smokeModelRoute(route) {
      return route;
    },
    async findResumeState() {
      return undefined;
    },
    async resumeSession() {
      throw new Error("not expected");
    },
    async fetchIssueMeta() {
      throw new Error("not expected");
    },
    async prepareWorktree() {
      throw new Error("not expected");
    },
    runStep: onRun,
    async writeLedger() {},
  };
}

describe("#1012 ensureRegularFileForBindMount", () => {
  it("creates a regular file when the path is missing (docker will not get a dir placeholder)", () => {
    const dir = mkdtempSync(join(tmpdir(), "fix-findings-ensure-missing-"));
    const path = join(dir, "fix-findings.json");
    try {
      expect(existsSync(path)).toBe(false);
      ensureRegularFileForBindMount(path);
      expect(existsSync(path)).toBe(true);
      expect(statSync(path).isFile()).toBe(true);
      expect(statSync(path).isDirectory()).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("replaces a leftover directory placeholder with a regular file", () => {
    const dir = mkdtempSync(join(tmpdir(), "fix-findings-ensure-dir-"));
    const path = join(dir, "fix-findings.json");
    try {
      // Simulate docker footgun residue: path exists as a directory.
      mkdirSync(path);
      expect(statSync(path).isDirectory()).toBe(true);

      ensureRegularFileForBindMount(path);

      expect(statSync(path).isFile()).toBe(true);
      expect(statSync(path).isDirectory()).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("leaves an existing regular file untouched (no wipe of written content)", () => {
    const dir = mkdtempSync(join(tmpdir(), "fix-findings-ensure-keep-"));
    const path = join(dir, "fix-findings.json");
    try {
      writeFileSync(path, '{"keep":true}\n', "utf8");
      ensureRegularFileForBindMount(path);
      expect(readFileSync(path, "utf8")).toBe('{"keep":true}\n');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("#1012 S5 landing recovers from directory placeholder", () => {
  it("writes stateDir/fix-findings.json as a regular file even when path was a directory", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/fix",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "fix-findings-wt-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "fix-findings-ledger-"));
    const landingPath = join(stateDir, "fix-findings.json");
    // Pre-seed docker footgun residue.
    mkdirSync(landingPath);
    expect(statSync(landingPath).isDirectory()).toBe(true);

    let observedMount:
      | { readonly path: string; readonly sandboxPath: string }
      | undefined;
    const backend = mockBackend(async (_spec, _wt, options) => {
      observedMount = options?.fixFindingsLanding;
      // Host open must succeed as a file (negative: EISDIR class does not reproduce).
      const raw = readFileSync(landingPath, "utf8");
      expect(statSync(landingPath).isFile()).toBe(true);
      expect(JSON.parse(raw).blockingFindingIdentityKeys).toEqual([
        "correctness|src/x.ts:1|clear the directory placeholder",
      ]);
      return { kind: "coder", committed: true, commitsAdded: 1 };
    });

    try {
      const result = await legacyDispatchWorker(
        backend,
        S5_CODER,
        {
          worktree,
          stateDir,
          blockingFindingIdentityKeys: [
            "correctness|src/x.ts:1|clear the directory placeholder",
          ],
          blockingFindingCount: 1,
        },
        {
          fixPacketBody:
            "live: correctness|src/x.ts:1|clear the directory placeholder",
          blockingFindings: [FINDING],
        },
      );

      expect(result.kind).toBe("completed");
      expect(observedMount).toEqual({
        path: landingPath,
        sandboxPath: ".orchestrator-fix-findings.json",
      });
      expect(statSync(landingPath).isFile()).toBe(true);
      expect(statSync(landingPath).isDirectory()).toBe(false);
    } finally {
      rmSync(worktree.path, { recursive: true, force: true });
      rmSync(stateDir, { recursive: true, force: true });
    }
  });
});

describe("#1012 mechanical retry does not spin on EISDIR-class host FS errors", () => {
  it("isEisdirClassHostFsError matches Node EISDIR SystemError and message form", () => {
    const sys = Object.assign(new Error("EISDIR: illegal operation on a directory, open '/x'"), {
      code: "EISDIR",
    });
    expect(isEisdirClassHostFsError(sys)).toBe(true);
    expect(
      isEisdirClassHostFsError(
        new Error(
          "hostCliWorkerRunner: worker threw: EISDIR: illegal operation on a directory, open '/ledger/fix-findings.json'",
        ),
      ),
    ).toBe(true);
    expect(isEisdirClassHostFsError(new Error("connection dropped"))).toBe(false);
  });

  it("thrown EISDIR is non-retryable (one dispatch, rethrow — no quota burn)", async () => {
    let calls = 0;
    const err = Object.assign(
      new Error("EISDIR: illegal operation on a directory, open '/ledger/fix-findings.json'"),
      { code: "EISDIR" as const },
    );
    await expect(
      withMechanicalRetry(
        S5_CODER,
        {} as DispatchContext,
        async () => {
          calls += 1;
          throw err;
        },
      ),
    ).rejects.toBe(err);
    expect(calls).toBe(1);
  });

  it("failed result whose reason is EISDIR-class returns immediately (no six-spin)", async () => {
    let calls = 0;
    const failed: WorkerResult = {
      kind: "failed",
      reason:
        "hostCliWorkerRunner: worker threw: EISDIR: illegal operation on a directory, open '/iso/.ledger-988/fix-findings.json'",
    };
    const result = await withMechanicalRetry(
      S5_CODER,
      {} as DispatchContext,
      async () => {
        calls += 1;
        return failed;
      },
    );
    expect(result).toEqual(failed);
    expect(calls).toBe(1);
    expect(calls).toBeLessThan(MAX_DISPATCH_ATTEMPTS);
    // Exhaustion annotation must NOT be applied — we did not burn the budget.
    if (result.kind === "failed") {
      expect(result.reason).not.toMatch(/after \d+ dispatch attempts/);
    }
  });
});
