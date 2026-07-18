/**
 * #1006 — baseline health gate before family fan-out.
 *
 * Admission hot-check member (with route preflight + smoke-k):
 *   - production full suite runs in the worker image (same container class)
 *   - base red → no fan-out, explicit failure package + ledger
 *   - base green → success path unchanged
 *
 * Three-question self-check (once-per-campaign cost vs N duplicate fixes):
 *   1. P(base red with env-specific defect)? Real — #969 five children hit the
 *      same /dev/stdin container red that host/CI greens hid.
 *   2. Severity? High — N parallel duplicate fixes + merger conflict tax.
 *   3. Downstream fallback? Wave S3 full gates catch it only AFTER wasted
 *      fan-out; no free downstream that prevents the waste.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  admitBaselineHealth,
  buildBaselineContainerFullTestArgv,
  formatBaselineExecFailureOutput,
  formatBaselineHealthFailurePackage,
  NOOP_BASELINE_FIX_ATTEMPT,
  runBaselineFullTestsInWorkerContainer,
  type BaselineFullTestResult,
} from "../../../src/baselineHealthGate.js";
import { FAMILY_LEDGER_FILENAME } from "../../../src/family/realFamilyBackend.js";
import { isFamilyLedgerEntryShape } from "../../../src/family/ledger.js";
import { PUBLIC_FAILED_CAUSES } from "../../../src/publicResult.js";
import { runFamilyDriver, type Sh } from "../../../src/familyDriver.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorkerSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import type {
  FamilyLedgerEntry,
  FamilyVerifyRequest,
} from "../../../src/family/types.js";
import {
  RealFamilyBackend,
  type CmrWorkerOutcome,
} from "../../../src/family/realFamilyBackend.js";
import { shipOutcomeFromResult } from "../../../src/shipOutcome.js";

const here = dirname(fileURLToPath(import.meta.url));
const familyPromptsDir = join(here, "..", "..", "..", "prompts");
const familySoulsDir = join(here, "..", "..", "..", "image", "souls");

const cleanups: string[] = [];
function track(p: string): string {
  cleanups.push(p);
  return p;
}
afterEach(() => {
  vi.unstubAllEnvs();
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}

function makeSourceRepo(): string {
  const dir = track(mkdtempSync(join(tmpdir(), "baseline-src-")));
  git(dir, "init", "-q", "-b", "main");
  git(dir, "config", "user.email", "t@t.t");
  git(dir, "config", "user.name", "t");
  git(dir, "config", "commit.gpgsign", "false");
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: dir });
  return dir;
}

function makeSh(): Sh {
  const SUB_ISSUES = JSON.stringify([
    { number: 10061, state: "OPEN", labels: [{ name: "ready-for-agent" }] },
  ]);
  return (file, args) => {
    if (file === "gh") {
      if (args[0] === "api") {
        if (String(args[1]).includes("/sub_issues")) return SUB_ISSUES;
        if (String(args[1]).includes("dependencies")) return "[]";
      }
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({
          number: Number(args[2]),
          body: "Coder-Rec: grok-4.5 → sol@med\n",
          author: { login: "Akagilnc" },
        });
      }
      throw new Error(`unexpected gh: ${args.join(" ")}`);
    }
    return execFileSync(file, args, { encoding: "utf8" }).trim();
  };
}

/** Minimal container-free child backend — fan-out counter for gate proofs. */
class TrackingChildBackend implements Backend {
  fanOutCalls = 0;
  constructor(private readonly clone: string) {}
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async resumeSession(spec: StepSpec, worktree: WorktreeHandle): Promise<StepOutput> {
    return this.runStep(spec, worktree);
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isClosed: false,
      isReadyForAgent: true,
      hasSubIssues: false,
      openBlockedBy: [],
      body: "Coder-Rec: grok-4.5 → sol@med\n",
    };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    this.fanOutCalls += 1;
    const branch = `feat/child-${issueNumber}`;
    const wtPath = join(this.clone, "..", `baseline-wt-${issueNumber}-${Date.now()}`);
    git(this.clone, "worktree", "add", "-b", branch, wtPath, base);
    track(wtPath);
    return { path: wtPath, branch, base };
  }
  async runStep(spec: StepSpec, worktree: WorktreeHandle): Promise<StepOutput> {
    this.fanOutCalls += 1;
    if (spec.role === "coder") {
      const num = Number(/child-(\d+)/.exec(worktree.branch)?.[1] ?? 0);
      writeFileSync(join(worktree.path, `child-${num}.txt`), `child ${num}`);
      git(worktree.path, "config", "user.email", "t@t.t");
      git(worktree.path, "config", "user.name", "t");
      git(worktree.path, "add", "-A");
      execFileSync("git", ["commit", "-q", "-m", `child ${num}`], {
        cwd: worktree.path,
      });
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

/** Real merge/ledger family backend with controlled verify/cmr/ship (e2e-style). */
class ControlledFamilyBackend extends RealFamilyBackend {
  protected override async runVerifyCommands(_req: FamilyVerifyRequest): Promise<void> {
    /* green */
  }
  protected override async runCmrWorker(
    _spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<CmrWorkerOutcome> {
    return {
      kind: "judge",
      status: "converged",
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      evidencePaths: ["cmr/review-summary.json"],
    };
  }
  protected override async runShipWorker(
    _spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ReturnType<typeof shipOutcomeFromResult>> {
    return {
      kind: "shipped",
      branch: ctx.familyBase!,
      status: "pr_opened",
      pr: "pr://family/1006-base",
    };
  }
}

function controlledFamilyBackend(
  clone: string,
  startHead: string,
  ledgerDir: string,
  imageName: string,
): ControlledFamilyBackend {
  return new ControlledFamilyBackend({
    workingRepo: clone,
    familyBase: "family/1006",
    ledgerDir,
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: familyPromptsDir,
    soulsDir: familySoulsDir,
    imageName,
    familyBaseStartHead: startHead,
  });
}

describe("#1006 pure baseline health gate", () => {
  it("green full → ready (no fix attempt)", async () => {
    let runs = 0;
    const admitted = await admitBaselineHealth({
      runFullTests: async () => {
        runs += 1;
        return { ok: true };
      },
    });
    expect(admitted.kind).toBe("ready");
    expect(runs).toBe(1);
  });

  it("red full → stop with failure package pointing at tests + pre-fix ticket", async () => {
    const failure: BaselineFullTestResult = {
      ok: false,
      exitCode: 1,
      output:
        "FAIL  test/dispatch/grok-mid-run-auth-964.test.ts > stdin seam\n" +
        "Failed to read '/dev/stdin': os error 6",
      failedTests: ["test/dispatch/grok-mid-run-auth-964.test.ts"],
    };
    const admitted = await admitBaselineHealth({
      runFullTests: async () => failure,
    });
    expect(admitted.kind).toBe("stop");
    if (admitted.kind !== "stop") return;
    expect(admitted.escalation.reason).toMatch(/baseline health/i);
    expect(admitted.escalation.diagnosis).toContain("grok-mid-run-auth-964");
    expect(admitted.escalation.diagnosis).toMatch(/pre-fix|前置|ticket|issue/i);
    expect(admitted.failure.output).toContain("/dev/stdin");
    expect(admitted.fixAttempts).toBe(0);
  });

  it("red → one fix attempt → recheck green → ready", async () => {
    let runs = 0;
    let fixes = 0;
    const admitted = await admitBaselineHealth({
      runFullTests: async () => {
        runs += 1;
        if (runs === 1) {
          return {
            ok: false,
            exitCode: 1,
            output: "FAIL foo.test.ts",
            failedTests: ["foo.test.ts"],
          };
        }
        return { ok: true };
      },
      tryFix: async (first) => {
        fixes += 1;
        expect(first.ok).toBe(false);
        return { attempted: true, summary: "baseline fix landed on family base" };
      },
    });
    expect(admitted.kind).toBe("ready");
    expect(runs).toBe(2);
    expect(fixes).toBe(1);
  });

  it("red → one fix attempt → still red → stop (no second fix loop)", async () => {
    let runs = 0;
    let fixes = 0;
    const admitted = await admitBaselineHealth({
      runFullTests: async () => {
        runs += 1;
        return {
          ok: false,
          exitCode: 1,
          output: `FAIL still-red-${runs}.test.ts`,
          failedTests: [`still-red-${runs}.test.ts`],
        };
      },
      tryFix: async () => {
        fixes += 1;
        return { attempted: true, summary: "tried" };
      },
    });
    expect(admitted.kind).toBe("stop");
    expect(runs).toBe(2);
    expect(fixes).toBe(1);
    if (admitted.kind === "stop") {
      expect(admitted.fixAttempts).toBe(1);
      expect(admitted.failure.output).toContain("still-red-2");
    }
  });

  it("formatBaselineHealthFailurePackage names failing tests and suggests one pre-fix ticket", () => {
    const pkg = formatBaselineHealthFailurePackage({
      ok: false,
      exitCode: 1,
      output: "FAIL a.test.ts\nFAIL b.test.ts\n",
      failedTests: ["a.test.ts", "b.test.ts"],
    });
    expect(pkg).toContain("a.test.ts");
    expect(pkg).toContain("b.test.ts");
    expect(pkg).toMatch(/single pre-fix ticket|前置修复票|file one/i);
    expect(pkg).toMatch(/family base|baseline/i);
  });

  it("red → tryFix attempted:false → stop without second full run (noop fail-closed)", async () => {
    let runs = 0;
    let fixes = 0;
    const admitted = await admitBaselineHealth({
      runFullTests: async () => {
        runs += 1;
        return {
          ok: false,
          exitCode: 1,
          output: "FAIL once.test.ts",
          failedTests: ["once.test.ts"],
        };
      },
      tryFix: async () => {
        fixes += 1;
        return { attempted: false, summary: "noop — no auto fixer this slice" };
      },
    });
    expect(admitted.kind).toBe("stop");
    expect(runs).toBe(1);
    expect(fixes).toBe(1);
    if (admitted.kind === "stop") {
      expect(admitted.fixAttempts).toBe(0);
      expect(admitted.failure.output).toContain("once.test.ts");
    }
  });

  it("NOOP_BASELINE_FIX_ATTEMPT reports attempted:false (production default 报错 path)", async () => {
    const r = await NOOP_BASELINE_FIX_ATTEMPT({
      ok: false,
      exitCode: 1,
      output: "FAIL x.test.ts",
      failedTests: ["x.test.ts"],
    });
    expect(r.attempted).toBe(false);
    expect(r.summary ?? "").toMatch(/not wired|fail-closed|报错|auto-fixer/i);
  });
});

describe("#1006 exec failure capture (message+stdout+stderr)", () => {
  it("formatBaselineExecFailureOutput keeps vitest FAIL body from stdout", () => {
    const vitestStdout =
      " FAIL  test/dispatch/grok-mid-run-auth-964.test.ts > stdin seam\n" +
      "Failed to read '/dev/stdin': os error 6\n";
    const err = Object.assign(new Error("Command failed: docker run …"), {
      status: 1,
      stdout: vitestStdout,
      stderr: "npm warn deprecated foo\n",
    });
    const output = formatBaselineExecFailureOutput(err);
    expect(output).toContain("Command failed");
    expect(output).toContain("stderr:");
    expect(output).toContain("npm warn deprecated foo");
    expect(output).toContain("stdout:");
    expect(output).toContain("grok-mid-run-auth-964");
    expect(output).toContain("/dev/stdin");
  });

  it("runBaselineFullTestsInWorkerContainer maps thrown vitest-shaped stdout into failedTests", async () => {
    const vitestStdout =
      " FAIL  test/dispatch/grok-mid-run-auth-964.test.ts > stdin seam\n" +
      "Failed to read '/dev/stdin': os error 6\n";
    const err = Object.assign(new Error("Command failed: docker run …"), {
      status: 1,
      stdout: vitestStdout,
      stderr: "",
    });
    const result = await runBaselineFullTestsInWorkerContainer(
      {
        imageName: "ming-orchestrator-coder:test",
        workingRepo: "/clones/family-1006",
        familyBase: "family/1006",
        verifyCwd: "/clones/family-1006/orchestrator",
      },
      () => {
        throw err;
      },
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.exitCode).toBe(1);
    expect(result.output).toContain("grok-mid-run-auth-964");
    expect(result.output).toContain("/dev/stdin");
    // FAIL lives on stdout — must not be dropped when only .message is read.
    expect(result.failedTests).toEqual(
      expect.arrayContaining(["test/dispatch/grok-mid-run-auth-964.test.ts"]),
    );
  });
});

describe("#1006 worker-container full-test argv (env parity)", () => {
  it("builds docker run against the worker image with repo mount + npm test (not host npm)", () => {
    const argv = buildBaselineContainerFullTestArgv({
      imageName: "ming-orchestrator-coder:latest",
      workingRepo: "/clones/family-1006",
      familyBase: "family/1006",
      verifyCwd: "/clones/family-1006/orchestrator",
    });
    expect(argv[0]).toBe("docker");
    expect(argv).toContain("run");
    expect(argv).toContain("--rm");
    expect(argv).toContain("ming-orchestrator-coder:latest");
    // Same worksite the family workers see: host clone bind-mounted at same path.
    const vIdx = argv.indexOf("-v");
    expect(vIdx).toBeGreaterThan(-1);
    expect(argv[vIdx + 1]).toBe("/clones/family-1006:/clones/family-1006");
    const wIdx = argv.indexOf("-w");
    expect(wIdx).toBeGreaterThan(-1);
    expect(argv[wIdx + 1]).toBe("/clones/family-1006/orchestrator");
    // Command runs inside the container image — never host `npm test` alone.
    const joined = argv.join(" ");
    expect(joined).toMatch(/npm test|npm run test/);
    expect(joined).toContain("family/1006");
    // Must not be a bare host-side npm invocation without docker.
    expect(argv[0]).not.toBe("npm");
  });

  it("aligns worker-class env: OPENCLAW_SESSION + HOME=/home/agent + user agent", () => {
    const argv = buildBaselineContainerFullTestArgv({
      imageName: "ming-orchestrator-coder:latest",
      workingRepo: "/clones/family-1006",
      familyBase: "family/1006",
      verifyCwd: "/clones/family-1006/orchestrator",
    });
    // SPAWNED_WORKER_ENV parity + sandcastle HOME default (no full sc.run agent).
    expect(argv).toContain("-e");
    expect(argv).toContain("OPENCLAW_SESSION=1");
    expect(argv).toContain("HOME=/home/agent");
    expect(argv).toContain("--user");
    expect(argv).toContain("agent");
  });

  it("shell-escapes paths with spaces via shared shellEscape (not a private quoter)", () => {
    const argv = buildBaselineContainerFullTestArgv({
      imageName: "ming-orchestrator-coder:latest",
      workingRepo: "/clones/family 1006",
      familyBase: "family/1006",
      verifyCwd: "/clones/family 1006/orchestrator",
    });
    const remoteCmd = argv[argv.length - 1] ?? "";
    // shellEscape quotes tokens that contain whitespace.
    expect(remoteCmd).toContain("'/clones/family 1006'");
    expect(remoteCmd).toMatch(/git -C .+ checkout --quiet/);
  });
});

describe("#1006 public cause + ledger vocabulary", () => {
  it("PUBLIC_FAILED_CAUSES includes baseline_health_failed", () => {
    expect(PUBLIC_FAILED_CAUSES).toContain("baseline_health_failed");
  });

  it("baseline_health_failed ledger row is a valid shape", () => {
    expect(
      isFamilyLedgerEntryShape({
        status: "baseline_health_failed",
        event: "baseline_health_failed",
        reason: "full suite red on family base",
        message: "FAIL foo.test.ts",
      }),
    ).toBe(true);
  });
});

describe("#1006 family admission entry (runFamilyDriver)", () => {
  it("base full red → failed, no child fan-out, ledger baseline_health_failed", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const source = makeSourceRepo();
    const ledgerDir = track(mkdtempSync(join(tmpdir(), "baseline-ledger-red-")));
    let childBackend: TrackingChildBackend | undefined;
    let fanOutBeforeGate = 0;
    let fixHookCalls = 0;

    const result = await runFamilyDriver({
      epicIssue: 1006,
      sourceRepo: source,
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/1006",
      base: "main",
      promptsDir: familyPromptsDir,
      familyPromptsDir,
      soulsDir: familySoulsDir,
      ledgerDir,
      imageName: "ming-orchestrator-coder:test",
      sh: makeSh(),
      singleSliceBackendFactory: (clone) => {
        childBackend = new TrackingChildBackend(clone);
        return childBackend;
      },
      familyBackendFactory: (clone, startHead) =>
        controlledFamilyBackend(
          clone,
          startHead,
          ledgerDir,
          "ming-orchestrator-coder:test",
        ),
      baselineFullTestRunner: async () => ({
        ok: false,
        exitCode: 1,
        output:
          "FAIL test/dispatch/grok-mid-run-auth-964.test.ts\n" +
          "Failed to read '/dev/stdin': os error 6",
        failedTests: ["test/dispatch/grok-mid-run-auth-964.test.ts"],
      }),
      // Production always wires a one-shot hook; tests may inject. Prove the
      // admission path invokes it once then fail-closes (no fan-out).
      baselineFixAttempt: async () => {
        fixHookCalls += 1;
        return { attempted: false, summary: "test noop" };
      },
    });

    expect(result.status).toBe("failed");
    if (result.status === "failed") {
      expect(result.cause).toBe("baseline_health_failed");
    }
    expect(fixHookCalls).toBe(1);
    expect(result.escalation?.diagnosis).toMatch(/grok-mid-run-auth-964|stdin/i);
    expect(result.escalation?.diagnosis).toMatch(/pre-fix|前置|ticket|issue/i);
    expect(result.stopSummary.repairHint ?? "").toMatch(/pre-fix|前置|ticket|baseline/i);
    // No fan-out: prepareWorktree / coder step never called.
    expect(childBackend?.fanOutCalls ?? fanOutBeforeGate).toBe(0);
    expect(result.children.every((c) => c.status === "skipped" || c.status === undefined)).toBe(
      true,
    );

    const ledgerPath = join(ledgerDir, FAMILY_LEDGER_FILENAME);
    const ledgerRaw = readFileSync(ledgerPath, "utf8").trim();
    expect(ledgerRaw.length).toBeGreaterThan(0);
    const rows = ledgerRaw
      .split("\n")
      .map((line) => JSON.parse(line) as FamilyLedgerEntry);
    expect(
      rows.some(
        (r) =>
          r.status === "baseline_health_failed" && r.event === "baseline_health_failed",
      ),
    ).toBe(true);
  });

  it("base full red without injected fix → production NOOP hook still fail-closes (no fan-out)", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const source = makeSourceRepo();
    const ledgerDir = track(mkdtempSync(join(tmpdir(), "baseline-ledger-noop-")));
    let childBackend: TrackingChildBackend | undefined;

    const result = await runFamilyDriver({
      epicIssue: 1006,
      sourceRepo: source,
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/1006",
      base: "main",
      promptsDir: familyPromptsDir,
      familyPromptsDir,
      soulsDir: familySoulsDir,
      ledgerDir,
      imageName: "ming-orchestrator-coder:test",
      sh: makeSh(),
      singleSliceBackendFactory: (clone) => {
        childBackend = new TrackingChildBackend(clone);
        return childBackend;
      },
      familyBackendFactory: (clone, startHead) =>
        controlledFamilyBackend(
          clone,
          startHead,
          ledgerDir,
          "ming-orchestrator-coder:test",
        ),
      baselineFullTestRunner: async () => ({
        ok: false,
        exitCode: 1,
        output: "FAIL baseline-only.test.ts\n",
        failedTests: ["baseline-only.test.ts"],
      }),
      // omit baselineFixAttempt → driver must still wire NOOP one-shot path
    });

    expect(result.status).toBe("failed");
    if (result.status === "failed") {
      expect(result.cause).toBe("baseline_health_failed");
    }
    expect(childBackend?.fanOutCalls ?? 0).toBe(0);
  });

  it("base full green → fan-out proceeds (success path not blocked)", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const source = makeSourceRepo();
    const ledgerDir = track(mkdtempSync(join(tmpdir(), "baseline-ledger-green-")));
    let childBackend: TrackingChildBackend | undefined;
    let baselineCalls = 0;

    const result = await runFamilyDriver({
      epicIssue: 1006,
      sourceRepo: source,
      repo: "Akagilnc/ming-salvage-sim",
      familyBase: "family/1006",
      base: "main",
      promptsDir: familyPromptsDir,
      familyPromptsDir,
      soulsDir: familySoulsDir,
      ledgerDir,
      imageName: "ming-orchestrator-coder:test",
      sh: makeSh(),
      singleSliceBackendFactory: (clone) => {
        childBackend = new TrackingChildBackend(clone);
        return childBackend;
      },
      familyBackendFactory: (clone, startHead) =>
        controlledFamilyBackend(
          clone,
          startHead,
          ledgerDir,
          "ming-orchestrator-coder:test",
        ),
      baselineFullTestRunner: async () => {
        baselineCalls += 1;
        return { ok: true };
      },
    });

    expect(baselineCalls).toBe(1);
    // Gate must not fail-closed as baseline_health_failed when full is green.
    if (result.status === "failed") {
      expect(result.cause).not.toBe("baseline_health_failed");
    }
    // Fan-out reached the child backend (prepareWorktree / steps) — gate did not block.
    expect(childBackend).toBeDefined();
    expect(childBackend!.fanOutCalls).toBeGreaterThan(0);
  });
});
