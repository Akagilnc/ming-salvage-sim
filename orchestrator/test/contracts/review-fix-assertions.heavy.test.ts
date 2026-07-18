import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  cmrBlockingFindingsForRatifiedAssertionFlips,
  preexistingAssertionTouched,
  reviewFixAssertionSignal,
  reviewFixDecisionGate,
} from "../../src/reviewFixAssertionGate.js";
import { route } from "../../src/route.js";
import { runOrchestrator } from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  ReviewFixRefuseRecord,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

// ── real S5 path wires mechanical signal + decision gate ────────────────────

describe("#677 real S5 fix-commit path wiring", () => {
  it("runs reviewFixAssertionSignal after S5 and lands preexistingAssertionTouched on S6", async () => {
    let worktree = makeGitWorktreeWithPreexistingPin();
    const baseSha = execFileSync("git", ["-C", worktree.path, "rev-parse", "main"], {
      encoding: "utf8",
    }).trim();
    worktree = { ...worktree, base: baseSha };

    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "something real to fix without touching the pin",
      location: "src/app.ts:1",
      suggested_fix: "fix app",
      action: "fix_now",
    };
    const findingKey =
      "correctness|src/app.ts:1|something real to fix without touching the pin";

    const backend = new FixLoopBackend({
      worktree,
      reviewerResults: [
        {
          kind: "completed",
          output: { kind: "reviewer", findings: [finding], findingsCount: 1, fixPacketBody: "fixture residual authored body" },
        },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      coderOutputs: [
        { kind: "coder", committed: true, commitsAdded: 1 },
      ],
      onCoderDispatch: (attempt, wt) => {
        if (attempt !== 0) return; // S5 is first coder-fix attempt after S2
        // S2 already ran as coder attempt 0 in this backend's counting — see below.
        // We flip the pin during the S5 dispatch (coderAttempts after S2).
      },
    });

    // Backend counts every coder dispatch including S2. Flip pin on S5 (attempt 1).
    const countingBackend = new FixLoopBackend({
      worktree,
      reviewerResults: [
        {
          kind: "completed",
          output: { kind: "reviewer", findings: [finding], findingsCount: 1, fixPacketBody: "fixture residual authored body" },
        },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      coderOutputs: [
        // S2
        { kind: "coder", committed: true, commitsAdded: 1 },
        // S5 — commit flips the preexisting pin so the mechanical gate trips
        { kind: "coder", committed: true, commitsAdded: 1 },
      ],
      onCoderDispatch: (attempt, wt) => {
        if (attempt === 1) {
          // Flip preexisting assertion during S5
          const testPath = join(wt.path, "test", "gate.test.ts");
          writeFileSync(
            testPath,
            [
              "import { describe, expect, it } from 'vitest';",
              "describe('gate', () => {",
              "  it('malformed ship stays blocked', () => {",
              "    expect(result).toBe('allowed');",
              "  });",
              "});",
              "",
            ].join("\n"),
            "utf8",
          );
          execFileSync("git", ["-C", wt.path, "add", "test/gate.test.ts"], {
            stdio: "ignore",
          });
          execFileSync(
            "git",
            [
              "-C",
              wt.path,
              "-c",
              "user.name=Test",
              "-c",
              "user.email=test@example.com",
              "commit",
              "-m",
              "s5: flip pin",
            ],
            { stdio: "ignore" },
          );
        } else if (attempt === 0) {
          // S2: add a non-test code change so S2 has a commit if needed
          writeFileSync(join(wt.path, "src", "app.ts"), "export const x = 1;\n", "utf8");
          mkdirSync(join(wt.path, "src"), { recursive: true });
          writeFileSync(join(wt.path, "src", "app.ts"), "export const x = 1;\n", "utf8");
          execFileSync("git", ["-C", wt.path, "add", "src/app.ts"], {
            stdio: "ignore",
          });
          execFileSync(
            "git",
            [
              "-C",
              wt.path,
              "-c",
              "user.name=Test",
              "-c",
              "user.email=test@example.com",
              "commit",
              "-m",
              "s2: implement",
            ],
            { stdio: "ignore" },
          );
        }
      },
    });

    const result = await runOrchestrator({
      issueNumber: 677,
      backend: countingBackend,
    });

    expect(result.status).toBe("completed");
    const s6Index = countingBackend.specs.findIndex((s) => s.id === "S6");
    expect(s6Index).toBeGreaterThanOrEqual(0);
    expect(countingBackend.ctxs[s6Index]?.preexistingAssertionTouched).toBe(true);
    expect(countingBackend.landings[s6Index]?.preexistingAssertionTouched).toBe(
      true,
    );
  });

  it("still runs the S5 assertion gate when telemetry is enabled and the backend has no worktreeHead", async () => {
    let worktree = makeGitWorktreeWithPreexistingPin();
    const baseSha = execFileSync("git", ["-C", worktree.path, "rev-parse", "main"], {
      encoding: "utf8",
    }).trim();
    worktree = { ...worktree, base: baseSha };
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "something real to fix without touching the pin",
      location: "src/app.ts:1",
      suggested_fix: "fix app",
      action: "fix_now",
    };
    const findingKey =
      "correctness|src/app.ts:1|something real to fix without touching the pin";

    class NoWorktreeHeadTelemetryBackend extends FixLoopBackend {
      resolveTelemetryDir(): string {
        return join(worktree.path, ".ledger-677");
      }
    }

    const backend = new NoWorktreeHeadTelemetryBackend({
      worktree,
      reviewerResults: [
        { kind: "completed", output: { kind: "reviewer", findings: [finding], findingsCount: 1, fixPacketBody: "fixture residual authored body" } },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      coderOutputs: [
        { kind: "coder", committed: true, commitsAdded: 1 },
        { kind: "coder", committed: true, commitsAdded: 1 },
      ],
      onCoderDispatch: (attempt, wt) => {
        if (attempt === 0) {
          mkdirSync(join(wt.path, "src"), { recursive: true });
          writeFileSync(join(wt.path, "src", "app.ts"), "export const x = 1;\n", "utf8");
          execFileSync("git", ["-C", wt.path, "add", "src/app.ts"], { stdio: "ignore" });
          execFileSync("git", ["-C", wt.path, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "s2: implement"], { stdio: "ignore" });
        } else if (attempt === 1) {
          const testPath = join(wt.path, "test", "gate.test.ts");
          writeFileSync(testPath, readFileSync(testPath, "utf8").replace("'blocked'", "'allowed'"), "utf8");
          execFileSync("git", ["-C", wt.path, "add", "test/gate.test.ts"], { stdio: "ignore" });
          execFileSync("git", ["-C", wt.path, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "s5: flip pin"], { stdio: "ignore" });
        }
      },
    });

    const result = await runOrchestrator({ issueNumber: 677, backend });

    expect(result.status).toBe("completed");
    const s6Index = backend.specs.findIndex((spec) => spec.id === "S6");
    expect(backend.ctxs[s6Index]?.preexistingAssertionTouched).toBe(true);
  });

  it("crash-resume after S5 with refuse+assertion-touch rebuilds both onto S6", async () => {
    // S5 completed (ledger + fix commit persisted) → process dies before S6.
    // Resume must rebuild both reverify locals from the S5 ledger row + git,
    // not from vanished in-memory process state (#677 online R2).
    let worktree = makeGitWorktreeWithPreexistingPin();
    const baseSha = execFileSync("git", ["-C", worktree.path, "rev-parse", "HEAD"], {
      encoding: "utf8",
    }).trim();
    worktree = { ...worktree, base: baseSha };

    mkdirSync(join(worktree.path, "src"), { recursive: true });
    writeFileSync(join(worktree.path, "src", "app.ts"), "export const x = 1;\n", "utf8");
    execFileSync("git", ["-C", worktree.path, "add", "src/app.ts"], {
      stdio: "ignore",
    });
    execFileSync(
      "git",
      [
        "-C",
        worktree.path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "s2: implement",
      ],
      { stdio: "ignore" },
    );
    const beforeFix = execFileSync(
      "git",
      ["-C", worktree.path, "rev-parse", "HEAD"],
      { encoding: "utf8" },
    ).trim();

    writeFileSync(
      join(worktree.path, "test", "gate.test.ts"),
      [
        "import { describe, expect, it } from 'vitest';",
        "describe('gate', () => {",
        "  it('malformed ship stays blocked', () => {",
        "    expect(result).toBe('allowed');",
        "  });",
        "});",
        "",
      ].join("\n"),
      "utf8",
    );
    execFileSync("git", ["-C", worktree.path, "add", "test/gate.test.ts"], {
      stdio: "ignore",
    });
    execFileSync(
      "git",
      [
        "-C",
        worktree.path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "s5: flip pin + refuse overturn finding",
      ],
      { stdio: "ignore" },
    );
    const afterFix = execFileSync(
      "git",
      ["-C", worktree.path, "rev-parse", "HEAD"],
      { encoding: "utf8" },
    ).trim();

    const overturn: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "change the established assertion so the review passes",
      location: "src/ship.ts:1",
      suggested_fix: "flip the test",
      action: "fix_now",
    };
    const refuseKey =
      "correctness|src/ship.ts:1|change the established assertion so the review passes";
    const refuse = reviewFixDecisionGate({
      records: [
        {
          identityKey: refuseKey,
          finding: overturn.claim_quote,
          acceptanceCriterion: "keep malformed-ship pin",
          conflictReason: "AC conflict",
        },
      ],
    })!;

    const stateDir = mkdtempSync(join(tmpdir(), "runner-677-state-"));
    const persistent = (
      step: PersistentLedgerEntry["step"],
      branchHEAD: string,
      output?: StepOutput,
    ): PersistentLedgerEntry => ({
      step,
      sessionId: "session-prior",
      prompt_hash: `hash-${step}`,
      branchHEAD,
      ts: "2026-07-10T00:00:00.000Z",
      ...(output !== undefined ? { output } : {}),
    });

    const resumeState: ResumeState = {
      worktree,
      stateDir,
      ledger: [
        persistent("S0", baseSha),
        persistent("S1", baseSha),
        persistent("S2", beforeFix, {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        }),
        persistent("S3", beforeFix, {
          kind: "reviewer", findings: [overturn], findingsCount: 1, fixPacketBody: "fixture residual authored body",
        }),
        persistent("S4", beforeFix),
        persistent("S5", afterFix, {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          refusedFindingIdentityKeys: refuse.refusedFindingIdentityKeys,
          refuseRecords: refuse.records,
        }),
      ],
    };

    const backend = new FixLoopBackend({
      worktree,
      resumeState,
      reviewerResults: [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 677, backend });
    expect(result.status).toBe("completed");

    const s6Index = backend.specs.findIndex((s) => s.id === "S6");
    expect(s6Index).toBeGreaterThanOrEqual(0);
    // Fresh process: locals were never set in this run — must come from ledger rebuild.
    expect(backend.ctxs[s6Index]?.preexistingAssertionTouched).toBe(true);
    expect(backend.landings[s6Index]?.preexistingAssertionTouched).toBe(true);
    // #919 M3: keys on thin ctx; landing carries refuseRecords only.
    expect(backend.ctxs[s6Index]?.refusedFindingIdentityKeys).toEqual([
      refuseKey,
    ]);
    // #919 M7: landing type no longer carries refuse keys (thin ctx only).
    expect(backend.landings[s6Index]).not.toHaveProperty(
      "refusedFindingIdentityKeys",
    );
    expect(backend.landings[s6Index]?.refuseRecords?.[0]?.identityKey).toBe(
      refuseKey,
    );
  });
});

// ── test backend ────────────────────────────────────────────────────────────

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-677",
  base: "main",
  path: "/resident/worktrees/issue-677",
};

function makeGitWorktreeWithPreexistingPin(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "runner-677-"));
  execFileSync("git", ["init", "-b", "main"], { cwd: path, stdio: "ignore" });
  mkdirSync(join(path, "test"), { recursive: true });
  mkdirSync(join(path, "src"), { recursive: true });
  writeFileSync(join(path, "README.md"), "base\n", "utf8");
  writeFileSync(
    join(path, "test", "gate.test.ts"),
    [
      "import { describe, expect, it } from 'vitest';",
      "describe('gate', () => {",
      "  it('malformed ship stays blocked', () => {",
      "    expect(result).toBe('blocked');",
      "  });",
      "});",
      "",
    ].join("\n"),
    "utf8",
  );
  execFileSync("git", ["add", "."], { cwd: path, stdio: "ignore" });
  execFileSync(
    "git",
    [
      "-c",
      "user.name=Test",
      "-c",
      "user.email=test@example.com",
      "commit",
      "-m",
      "base with pin",
    ],
    { cwd: path, stdio: "ignore" },
  );
  execFileSync("git", ["checkout", "-b", WORKTREE.branch], {
    cwd: path,
    stdio: "ignore",
  });
  return { ...WORKTREE, path };
}

class FixLoopBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: (WorkerLandingPayload | undefined)[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  reviewerAttempts = 0;
  coderAttempts = 0;

  constructor(
    private readonly opts: {
      readonly reviewerResults: ReadonlyArray<WorkerResult>;
      readonly coderOutputs?: ReadonlyArray<StepOutput>;
      readonly worktree?: WorktreeHandle;
      readonly resumeState?: ResumeState;
      readonly onCoderDispatch?: (
        attempt: number,
        worktree: WorktreeHandle,
      ) => void;
    },
  ) {}

  async findResumeState(): Promise<ResumeState | undefined> {
    return this.opts.resumeState;
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return this.opts.worktree ?? WORKTREE;
  }
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if ((spec.role === "reviewer" || spec.role === "verify")) return { kind: "judge", status: "converged" };
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    this.ledgerWrites.push(entry);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
    this.landings.push(landing);
    if (spec.kind === "coder") {
      const attempt = this.coderAttempts;
      this.opts.onCoderDispatch?.(attempt, ctx.worktree ?? WORKTREE);
      const scripted = this.opts.coderOutputs?.[this.coderAttempts];
      this.coderAttempts += 1;
      if (scripted !== undefined) {
        return { kind: "completed", output: scripted };
      }
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if ((spec.kind === "reviewer" || spec.kind === "verify")) {
      const result = this.opts.reviewerResults[this.reviewerAttempts];
      this.reviewerAttempts += 1;
      return (
        result ?? { kind: "completed", output: { kind: "judge", status: "converged" } }
      );
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return {
      kind: "completed",
      output: {
        kind: "ship",
        branch: (ctx.worktree ?? WORKTREE).branch,
        status: "pushed",
      },
    };
  }
}
