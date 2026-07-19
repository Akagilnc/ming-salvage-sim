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
  classifyBaselineFailure,
  containerBaselineVerifyCwd,
  formatBaselineHealthFailurePackage,
  NOOP_BASELINE_FIX_ATTEMPT,
  runBaselineFullTestsInWorkerContainer,
  type BaselineFullTestResult,
} from "../../../src/baselineHealthGate.js";
import { formatExecFailureOutput } from "../../../src/execFailureOutput.js";
import { FAMILY_LEDGER_FILENAME } from "../../../src/family/realFamilyBackend.js";
import { isFamilyLedgerEntryShape } from "../../../src/family/ledger.js";
import type { ResolvedModelRoute } from "../../../src/modelRoutes.js";
import {
  clearProgressBroadcastConfig,
  readProgressEvents,
} from "../../../src/progressBroadcast.js";
import { PUBLIC_FAILED_CAUSES } from "../../../src/publicResult.js";
import { SPAWNED_WORKER_ENV } from "../../../src/realBackend.js";
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
  clearProgressBroadcastConfig();
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
  async smokeModelRoute(route: ResolvedModelRoute) {
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
  it("formatExecFailureOutput keeps vitest FAIL body from stdout", () => {
    const vitestStdout =
      " FAIL  test/dispatch/grok-mid-run-auth-964.test.ts > stdin seam\n" +
      "Failed to read '/dev/stdin': os error 6\n";
    const err = Object.assign(new Error("Command failed: docker run …"), {
      status: 1,
      stdout: vitestStdout,
      stderr: "npm warn deprecated foo\n",
    });
    const output = formatExecFailureOutput(err);
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
        // Host installDeps class succeeds; only docker full is red.
        provisionDeps: async () => undefined,
      },
      (file) => {
        if (file === "git") return "";
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
    // Host worksite → agent-readable container path (not host path under /root).
    const vIdx = argv.indexOf("-v");
    expect(vIdx).toBeGreaterThan(-1);
    expect(argv[vIdx + 1]).toBe(
      "/clones/family-1006:/home/agent/baseline-worksite",
    );
    const wIdx = argv.indexOf("-w");
    expect(wIdx).toBeGreaterThan(-1);
    expect(argv[wIdx + 1]).toBe(
      "/home/agent/baseline-worksite/orchestrator",
    );
    const imageIdx = argv.indexOf("ming-orchestrator-coder:latest");
    const entrypointIdx = argv.indexOf("--entrypoint");
    expect(entrypointIdx).toBeGreaterThan(-1);
    expect(argv[entrypointIdx + 1]).toBe("bash");
    expect(entrypointIdx).toBeLessThan(imageIdx);
    expect(argv.slice(imageIdx + 1)).toEqual([
      "-lc",
      "npm ci --no-audit --no-fund && npm test",
    ]);
    // Command runs inside the container image — never host `npm test` alone.
    // familyBase checkout is host-side only (ensureBaselineWorksiteReady); no
    // second container-side git checkout on the bind mount (#1006 CR N1).
    const joined = argv.join(" ");
    expect(joined).toMatch(/npm test|npm run test/);
    expect(joined).not.toMatch(/git\b.*\bcheckout\b/);
    // Must not be a bare host-side npm invocation without docker.
    expect(argv[0]).not.toBe("npm");
  });

  it("maps host /root worksite to agent-readable container path (online Codex P1)", () => {
    const argv = buildBaselineContainerFullTestArgv({
      imageName: "ming-orchestrator-coder:latest",
      workingRepo: "/root/.sc-orchestrator/repo-iso-1006",
      familyBase: "family/1006",
      verifyCwd: "/root/.sc-orchestrator/repo-iso-1006/orchestrator",
    });
    expect(argv).toContain(
      "/root/.sc-orchestrator/repo-iso-1006:/home/agent/baseline-worksite",
    );
    const wIdx = argv.indexOf("-w");
    expect(argv[wIdx + 1]).toBe(
      "/home/agent/baseline-worksite/orchestrator",
    );
    expect(argv).toContain("--user");
    expect(argv).toContain("agent");
  });

  it("aligns worker-class env: SPAWNED_WORKER_ENV + HOME=/home/agent + user agent", () => {
    const argv = buildBaselineContainerFullTestArgv({
      imageName: "ming-orchestrator-coder:latest",
      workingRepo: "/clones/family-1006",
      familyBase: "family/1006",
      verifyCwd: "/clones/family-1006/orchestrator",
    });
    // SPAWNED_WORKER_ENV from realBackend (not hard-coded OPENCLAW_SESSION=1) +
    // sandcastle HOME default — best-effort parity, not full sc.run lifecycle.
    expect(argv).toContain("-e");
    for (const [key, value] of Object.entries(SPAWNED_WORKER_ENV)) {
      expect(argv).toContain(`${key}=${value}`);
    }
    expect(argv).toContain("HOME=/home/agent");
    expect(argv).toContain("--user");
    expect(argv).toContain("agent");
  });

  it("bind-mounts worksite paths with spaces as docker argv (no container checkout)", () => {
    const argv = buildBaselineContainerFullTestArgv({
      imageName: "ming-orchestrator-coder:latest",
      workingRepo: "/clones/family 1006",
      familyBase: "family/1006",
      verifyCwd: "/clones/family 1006/orchestrator",
    });
    const vIdx = argv.indexOf("-v");
    expect(argv[vIdx + 1]).toBe(
      "/clones/family 1006:/home/agent/baseline-worksite",
    );
    const wIdx = argv.indexOf("-w");
    expect(argv[wIdx + 1]).toBe(
      "/home/agent/baseline-worksite/orchestrator",
    );
    // Host already checked out familyBase — remote cmd is pure full suite.
    expect(argv[argv.length - 1]).toBe(
      "npm ci --no-audit --no-fund && npm test",
    );
  });

  it("maps workingRepo root and nested verifyCwd under worksite (no silent rewrite)", () => {
    expect(
      containerBaselineVerifyCwd("/root/.sc/repo", "/root/.sc/repo"),
    ).toBe("/home/agent/baseline-worksite");
    expect(
      containerBaselineVerifyCwd(
        "/root/.sc/repo",
        "/root/.sc/repo/orchestrator",
      ),
    ).toBe("/home/agent/baseline-worksite/orchestrator");
    // Lexical .. that still resolves inside hostRoot is fine.
    expect(
      containerBaselineVerifyCwd(
        "/root/.sc/repo",
        "/root/.sc/repo/orchestrator/../orchestrator",
      ),
    ).toBe("/home/agent/baseline-worksite/orchestrator");
  });

  it("rejects lexical .. escape of workingRepo (no -w outside mount)", () => {
    // Host: /root/.sc/repo/../other → /root/.sc/other (outside worksite).
    expect(() =>
      containerBaselineVerifyCwd(
        "/root/.sc/repo",
        "/root/.sc/repo/../other",
      ),
    ).toThrow(/verifyCwd.*workingRepo|escapes|outside/i);

    expect(() =>
      buildBaselineContainerFullTestArgv({
        imageName: "ming-orchestrator-coder:latest",
        workingRepo: "/root/.sc/repo",
        familyBase: "family/1006",
        verifyCwd: "/root/.sc/repo/../other",
      }),
    ).toThrow(/verifyCwd|escapes|outside/i);
  });

  it("rejects unrelated verifyCwd that cannot map under worksite (fail closed)", () => {
    expect(() =>
      containerBaselineVerifyCwd("/root/.sc/repo", "/tmp/unrelated"),
    ).toThrow(/verifyCwd.*workingRepo|escapes|outside|unrelated/i);

    expect(() =>
      buildBaselineContainerFullTestArgv({
        imageName: "ming-orchestrator-coder:latest",
        workingRepo: "/root/.sc/repo",
        familyBase: "family/1006",
        verifyCwd: "/tmp/unrelated",
      }),
    ).toThrow(/verifyCwd|escapes|outside|unrelated/i);
  });

  it("runBaselineFullTestsInWorkerContainer fails closed on escaped verifyCwd (no docker -w outside)", async () => {
    const calls: string[] = [];
    const result = await runBaselineFullTestsInWorkerContainer(
      {
        imageName: "ming-orchestrator-coder:test",
        workingRepo: "/root/.sc/repo",
        familyBase: "family/1006",
        verifyCwd: "/root/.sc/repo/../other",
        provisionDeps: async () => {
          calls.push("provision");
        },
      },
      (file) => {
        calls.push(file);
        return "";
      },
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.failureClass).toBe("infra");
    expect(result.output).toMatch(/verifyCwd|escapes|outside/i);
    // Must not spawn docker with -w outside the bind mount.
    expect(calls).not.toContain("docker");
  });
});

describe("#1006 host deps provision before container full (installDeps class)", () => {
  it("runBaselineFullTestsInWorkerContainer provisions verifyCwd deps before docker npm test", async () => {
    const order: string[] = [];
    let provisionCwd: string | undefined;
    const result = await runBaselineFullTestsInWorkerContainer(
      {
        imageName: "ming-orchestrator-coder:test",
        workingRepo: "/clones/family-1006",
        familyBase: "family/1006",
        verifyCwd: "/clones/family-1006/orchestrator",
        depsTemplateRoot: "/src/ming",
        provisionDeps: async (cwd) => {
          provisionCwd = cwd;
          order.push("provision");
        },
      },
      (file, args) => {
        // Host checkout of family base (manifests match) or docker full.
        if (file === "git") {
          order.push("git-checkout");
          return "";
        }
        if (file === "docker") {
          order.push("docker");
          return "";
        }
        throw new Error(`unexpected sh: ${file} ${args.join(" ")}`);
      },
    );
    expect(result.ok).toBe(true);
    expect(provisionCwd).toBe("/clones/family-1006/orchestrator");
    // Provision must complete before docker so bind-mounted node_modules exist.
    expect(order.indexOf("provision")).toBeGreaterThanOrEqual(0);
    expect(order.indexOf("docker")).toBeGreaterThan(order.indexOf("provision"));
    // Host checkout before provision so package.json/lock match family base.
    expect(order.indexOf("git-checkout")).toBeGreaterThanOrEqual(0);
    expect(order.indexOf("provision")).toBeGreaterThan(order.indexOf("git-checkout"));
  });

  it("provision failure is infra red (not suite pre-fix ticket)", async () => {
    const result = await runBaselineFullTestsInWorkerContainer(
      {
        imageName: "ming-orchestrator-coder:test",
        workingRepo: "/clones/family-1006",
        familyBase: "family/1006",
        verifyCwd: "/clones/family-1006/orchestrator",
        provisionDeps: async () => {
          throw new Error("npm ci failed: network unreachable");
        },
      },
      (file) => {
        if (file === "git") return "";
        throw new Error(`docker must not run after provision failure (got ${file})`);
      },
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(classifyBaselineFailure(result)).toBe("infra");
    const pkg = formatBaselineHealthFailurePackage(result);
    expect(pkg).toMatch(/infra|infrastructure|deps|provision|npm ci/i);
    // Must not *recommend* filing a suite pre-fix ticket (negation OK).
    expect(pkg).not.toMatch(/file one (single )?pre-fix ticket|建议开前置|开前置修复票/i);
  });
});

describe("#1006 infra vs suite failure diagnosis", () => {
  it("classifies docker-missing / daemon failures as infra (no pre-fix ticket)", () => {
    const failure: Extract<BaselineFullTestResult, { ok: false }> = {
      ok: false,
      exitCode: 127,
      output:
        "Error: spawn docker ENOENT\n" +
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
    };
    expect(classifyBaselineFailure(failure)).toBe("infra");
    const pkg = formatBaselineHealthFailurePackage(failure);
    expect(pkg).toMatch(/infra|infrastructure|docker/i);
    expect(pkg).not.toMatch(/file one (single )?pre-fix ticket|建议开前置|开前置修复票/i);
    expect(pkg).toMatch(/repair|docker|re-admit|re-run|rerun/i);
  });

  it("classifies unable-to-find-image as infra (no pre-fix ticket)", () => {
    const failure: Extract<BaselineFullTestResult, { ok: false }> = {
      ok: false,
      exitCode: 125,
      output:
        "Unable to find image 'ming-orchestrator-coder:test' locally\n" +
        "docker: Error response from daemon: pull access denied for ming-orchestrator-coder, " +
        "repository does not exist or may require 'docker login'",
    };
    expect(classifyBaselineFailure(failure)).toBe("infra");
    const pkg = formatBaselineHealthFailurePackage(failure);
    expect(pkg).toMatch(/infra|infrastructure/i);
    expect(pkg).not.toMatch(/file one (single )?pre-fix ticket|建议开前置|开前置修复票/i);
  });

  it("classifies docker socket permission denied as infra (beyond Cannot connect…)", () => {
    const failure: Extract<BaselineFullTestResult, { ok: false }> = {
      ok: false,
      exitCode: 1,
      output:
        "docker: permission denied while trying to connect to the Docker daemon socket " +
        "at unix:///var/run/docker.sock: Get \"http://%2Fvar%2Frun%2Fdocker.sock/v1.24/containers/json\": " +
        "dial unix /var/run/docker.sock: connect: permission denied",
    };
    expect(classifyBaselineFailure(failure)).toBe("infra");
    const pkg = formatBaselineHealthFailurePackage(failure);
    expect(pkg).toMatch(/infra|infrastructure|docker/i);
    expect(pkg).not.toMatch(/file one (single )?pre-fix ticket|建议开前置|开前置修复票/i);
  });

  it("classifies docker exit-125 usage/config as infra when tooling-shaped", () => {
    const failure: Extract<BaselineFullTestResult, { ok: false }> = {
      ok: false,
      exitCode: 125,
      output:
        "docker: 'run' requires at least 1 argument.\n" +
        "See 'docker run --help'.\n",
    };
    expect(classifyBaselineFailure(failure)).toBe("infra");
    const pkg = formatBaselineHealthFailurePackage(failure);
    expect(pkg).toMatch(/infra|infrastructure/i);
    expect(pkg).not.toMatch(/file one (single )?pre-fix ticket|建议开前置|开前置修复票/i);
  });

  it("classifies docker exit-126 cannot-invoke as infra when docker-shaped (not suite FAIL)", () => {
    const failure: Extract<BaselineFullTestResult, { ok: false }> = {
      ok: false,
      exitCode: 126,
      output:
        "docker: Error response from daemon: failed to create task for container: " +
        "failed to create shim task: OCI runtime create failed: runc create failed: " +
        "unable to start container process: exec: \"bash\": permission denied",
    };
    expect(classifyBaselineFailure(failure)).toBe("infra");
    expect(formatBaselineHealthFailurePackage(failure)).not.toMatch(
      /file one (single )?pre-fix ticket|建议开前置|开前置修复票/i,
    );
  });

  it("does not swallow suite FAIL as infra even with docker-looking noise nearby", () => {
    const failure: Extract<BaselineFullTestResult, { ok: false }> = {
      ok: false,
      exitCode: 1,
      output:
        "docker run … npm test\n" +
        "FAIL  test/dispatch/grok-mid-run-auth-964.test.ts > stdin seam\n" +
        "Failed to read '/dev/stdin': os error 6",
      failedTests: ["test/dispatch/grok-mid-run-auth-964.test.ts"],
    };
    expect(classifyBaselineFailure(failure)).toBe("suite");
  });

  it("runBaselineFullTestsInWorkerContainer tags image-pull red as failureClass:infra", async () => {
    const err = Object.assign(
      new Error(
        "Unable to find image 'ming-orchestrator-coder:test' locally\n" +
          "docker: Error response from daemon: pull access denied for ming-orchestrator-coder",
      ),
      {
        status: 125,
        stdout: "",
        stderr:
          "Unable to find image 'ming-orchestrator-coder:test' locally\n" +
          "docker: Error response from daemon: pull access denied for ming-orchestrator-coder",
      },
    );
    const result = await runBaselineFullTestsInWorkerContainer(
      {
        imageName: "ming-orchestrator-coder:test",
        workingRepo: "/clones/family-1006",
        familyBase: "family/1006",
        verifyCwd: "/clones/family-1006/orchestrator",
        provisionDeps: async () => undefined,
      },
      (file) => {
        if (file === "git") return "";
        throw err;
      },
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.failureClass).toBe("infra");
    expect(classifyBaselineFailure(result)).toBe("infra");
    expect(formatBaselineHealthFailurePackage(result)).not.toMatch(
      /file one (single )?pre-fix ticket|建议开前置|开前置修复票/i,
    );
  });

  it("classifies suite FAIL with failedTests as suite (still suggests one pre-fix ticket)", () => {
    const failure: Extract<BaselineFullTestResult, { ok: false }> = {
      ok: false,
      exitCode: 1,
      output:
        "FAIL  test/dispatch/grok-mid-run-auth-964.test.ts > stdin seam\n" +
        "Failed to read '/dev/stdin': os error 6",
      failedTests: ["test/dispatch/grok-mid-run-auth-964.test.ts"],
    };
    expect(classifyBaselineFailure(failure)).toBe("suite");
    const pkg = formatBaselineHealthFailurePackage(failure);
    expect(pkg).toMatch(/pre-fix ticket|前置修复票|file one/i);
    expect(pkg).toContain("grok-mid-run-auth-964");
  });

  it("explicit failureClass:infra wins over suite-looking output", () => {
    const failure: Extract<BaselineFullTestResult, { ok: false }> = {
      ok: false,
      exitCode: 1,
      output: "FAIL  something.test.ts\n",
      failedTests: ["something.test.ts"],
      failureClass: "infra",
    };
    expect(classifyBaselineFailure(failure)).toBe("infra");
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
    expect(childBackend?.fanOutCalls ?? 0).toBe(0);
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

    // #1009 SP-M1: baseline_health stop dual-writes terminal failed progress.
    const progress = readProgressEvents(ledgerDir);
    expect(
      progress.some(
        (e) =>
          e.kind === "terminal" &&
          e.status === "failed" &&
          e.epic === 1006,
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

  it("infra baseline red → fail-closed without pre-fix ticket repairHint", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const source = makeSourceRepo();
    const ledgerDir = track(mkdtempSync(join(tmpdir(), "baseline-ledger-infra-")));
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
        exitCode: 127,
        output: "Error: spawn docker ENOENT",
        failureClass: "infra" as const,
      }),
    });

    expect(result.status).toBe("failed");
    if (result.status === "failed") {
      expect(result.cause).toBe("baseline_health_failed");
    }
    expect(childBackend?.fanOutCalls ?? 0).toBe(0);
    // Diagnosis may say "do NOT open a pre-fix ticket"; must not *recommend* filing one.
    expect(result.escalation?.diagnosis ?? "").not.toMatch(
      /file one (single )?pre-fix ticket|建议开前置|开前置修复票/i,
    );
    expect(result.stopSummary.repairHint ?? "").toMatch(/docker|infra|provision|deps/i);
    expect(result.stopSummary.repairHint ?? "").not.toMatch(
      /file one pre-fix ticket|file one single pre-fix/i,
    );
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

  it("#1017 C1: resident non-terminal with merged child skips baseline gate (post-merge resume)", async () => {
    // Baseline gate = fresh pre-fan-out base health only. After a child has
    // already landed on familyBase, suite red on the advanced base must not be
    // mislabeled baseline_health_failed (would skip all remaining work forever).
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const source = makeSourceRepo();
    // Real SHA so resume reconcile/is-ancestor stays on real git objects.
    const startSha = git(source, "rev-parse", "HEAD");
    const ledgerDir = track(
      mkdtempSync(join(tmpdir(), "baseline-ledger-resident-progress-")),
    );
    // Resident scene: parseable non-terminal ledger + worksite start-head.
    // Child 10061 already merged — durable child progress on family base.
    writeFileSync(
      join(ledgerDir, FAMILY_LEDGER_FILENAME),
      `${JSON.stringify({
        status: "merged",
        childIssue: 10061,
        familyHeadAfter: startSha,
      } satisfies FamilyLedgerEntry)}\n`,
      "utf8",
    );
    writeFileSync(join(ledgerDir, "family-base-start-head"), `${startSha}\n`, "utf8");

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
      singleSliceBackendFactory: (clone) => new TrackingChildBackend(clone),
      familyBackendFactory: (clone, startHead) =>
        controlledFamilyBackend(
          clone,
          startHead,
          ledgerDir,
          "ming-orchestrator-coder:test",
        ),
      // Would fail-closed on a fresh path — must not stop resume.
      baselineFullTestRunner: async () => {
        baselineCalls += 1;
        return {
          ok: false,
          exitCode: 1,
          output: "FAIL post-merge-wip.test.ts\n",
          failedTests: ["post-merge-wip.test.ts"],
        };
      },
    });

    // Gate must not run (or stop) as baseline disease on post-merge resume.
    expect(baselineCalls).toBe(0);
    if (result.status === "failed") {
      // Illegal ledger shapes fail as resume_state_invalid and would also keep
      // baselineCalls===0 / avoid baseline_health_failed — pin the real path.
      expect(result.cause).not.toBe("resume_state_invalid");
      expect(result.cause).not.toBe("baseline_health_failed");
    }
    // Ledger must not grow a baseline_health_failed row from this resume.
    const ledgerPath = join(ledgerDir, FAMILY_LEDGER_FILENAME);
    const rows = readFileSync(ledgerPath, "utf8")
      .trim()
      .split("\n")
      .filter((line) => line.length > 0)
      .map((line) => JSON.parse(line) as FamilyLedgerEntry);
    expect(
      rows.some(
        (r) =>
          r.status === "baseline_health_failed" ||
          r.event === "baseline_health_failed",
      ),
    ).toBe(false);
  });

  it("#1017 C1: resident without child progress still fail-closes baseline red", async () => {
    // Empty productive progress: resident worksite + empty-ish ledger must keep
    // fresh-style baseline fail-closed (gate is still pre-fan-out admission).
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const source = makeSourceRepo();
    const ledgerDir = track(
      mkdtempSync(join(tmpdir(), "baseline-ledger-resident-no-progress-")),
    );
    // Non-terminal ledger row that is NOT merged child progress.
    writeFileSync(
      join(ledgerDir, FAMILY_LEDGER_FILENAME),
      `${JSON.stringify({
        status: "admission_skipped",
        event: "admission_skipped",
        childIssue: 99999,
        reason: "not ready",
      })}\n`,
      "utf8",
    );
    writeFileSync(join(ledgerDir, "family-base-start-head"), "start0\n", "utf8");

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
      singleSliceBackendFactory: (clone) => new TrackingChildBackend(clone),
      familyBackendFactory: (clone, startHead) =>
        controlledFamilyBackend(
          clone,
          startHead,
          ledgerDir,
          "ming-orchestrator-coder:test",
        ),
      baselineFullTestRunner: async () => {
        baselineCalls += 1;
        return {
          ok: false,
          exitCode: 1,
          output: "FAIL still-pre-fanout.test.ts\n",
          failedTests: ["still-pre-fanout.test.ts"],
        };
      },
    });

    expect(baselineCalls).toBe(1);
    expect(result.status).toBe("failed");
    if (result.status === "failed") {
      expect(result.cause).toBe("baseline_health_failed");
    }
  });
});
