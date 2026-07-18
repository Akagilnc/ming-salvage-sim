/**
 * #966 — family judge session continuity from ledger (not dead ByPass relay).
 *
 * Defect: verifyCmr packed restartFinalBarrier.judgeSessionIdByPass expecting
 * callers to pass it back, but nothing outside the process-local loop consumed
 * it across separate final-barrier rounds → every round opened a fresh amnesiac
 * judge. Ledger already records sessionId on cmr_reviewed / cmr_passed (#930).
 *
 * Acceptance:
 *   1. Next-round resume sessionId is derived from family ledger
 *      (priorFamilyJudgeVerdictRowsFromLedger / PriorJudgeVerdictRow.sessionId)
 *   2. Dead judgeSessionIdByPass production is deleted
 *   3. Two consecutive family CMR rounds: round-2 judge resumes round-1 session
 *      (grok seat is resume-capable — #955 sessionStorage)
 *   4. Fresh fallback when session truly absent stays (priorJudgeVerdicts only)
 *   5. Production runCmrWorker forwards resumeSession into Sandcastle when
 *      ctx.resumeSessionId is set and the seat is resume-capable
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import type * as sc from "@ai-hero/sandcastle";

import { cmrWorkerSpec } from "../../../src/family/dispatchFamilyWorker.js";
import {
  RealFamilyBackend,
  type CmrAuth,
} from "../../../src/family/realFamilyBackend.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import { familyJudgeResumeSessionIdFromPriorRows } from "../../../src/judgeStation.js";
import { resumeCapableForSlug } from "../../../src/modelRegistry.js";
import {
  resolveActiveModelRoute,
  smokeRouteModels,
} from "../../../src/modelRoutes.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";
import type {
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../../src/family/types.js";
import type {
  DispatchContext,
  JudgeResult,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import {
  judgeConverged,
  judgeContinue,
  sampleFinding,
} from "../../helpers/judge-fixtures.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

const FINDING = sampleFinding(
  "family open claim 966",
  "orchestrator/src/family/verifyCmr.ts:966",
);
const ROUND1_SESSION = "judge-sess-round1-966";
const GROK_SLUG = "grok-4.5";

const cleanups: string[] = [];
afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

function realRepo966(): string {
  const repo = mkDir("966-cmr-repo-");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
  execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], {
    cwd: repo,
  });
  execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
  return repo;
}

function completedJudge(output: JudgeResult, sessionId?: string): WorkerResult {
  return {
    kind: "completed",
    output,
    ...(sessionId !== undefined ? { sessionId } : {}),
  };
}

class FamilyJudgeLedgerBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: Array<{
    readonly kind: string;
    readonly session: string;
    readonly model?: string;
    readonly cmrPass?: string;
    readonly resumeSessionId?: string;
    readonly priorJudgeVerdicts?: DispatchContext["priorJudgeVerdicts"];
  }> = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: string[] = [];
  currentFamilyHead = "head-r1";

  private completenessRound = 0;
  private correctnessRound = 0;
  private coderFixRound = 0;

  constructor(
    private readonly script: {
      completeness?: (
        round: number,
        ctx: DispatchContext,
      ) => WorkerResult;
      correctness?: (
        round: number,
        ctx: DispatchContext,
      ) => WorkerResult;
      coder?: (round: number, ctx: DispatchContext) => WorkerResult;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(_req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      ...(typeof spec.model === "string" ? { model: spec.model } : {}),
      ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
      ...(ctx.resumeSessionId !== undefined
        ? { resumeSessionId: ctx.resumeSessionId }
        : {}),
      ...(ctx.priorJudgeVerdicts !== undefined
        ? { priorJudgeVerdicts: ctx.priorJudgeVerdicts }
        : {}),
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness") {
        const round = this.completenessRound++;
        if (this.script.completeness !== undefined) {
          return this.script.completeness(round, ctx);
        }
        return completedJudge(judgeConverged(), ROUND1_SESSION);
      }
      const round = this.correctnessRound++;
      if (this.script.correctness !== undefined) {
        return this.script.correctness(round, ctx);
      }
      return completedJudge(judgeConverged(), `${ROUND1_SESSION}-correctness`);
    }

    if (spec.kind === "coder") {
      const round = this.coderFixRound++;
      this.currentFamilyHead = `head-after-fix-${round + 1}`;
      if (this.script.coder !== undefined) {
        return this.script.coder(round, ctx);
      }
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }

    if (spec.kind === "ship") {
      this.prCalls.push(ctx.familyBase ?? "");
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase ?? "family/base",
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    throw new Error(`unexpected worker kind ${spec.kind}`);
  }

  /** Reset per-pass open counters so a second runVerifyCmr starts rounds at 0. */
  resetRoundCounters(): void {
    this.completenessRound = 0;
    this.correctnessRound = 0;
    this.coderFixRound = 0;
  }
}

async function grokCmrRoute() {
  const base = resolveActiveModelRoute({ ORCHESTRATOR_ROUTE: "normal" });
  return smokeRouteModels(
    {
      ...base,
      slots: {
        ...base.slots,
        cmrCompleteness: GROK_SLUG,
        cmrCorrectness: GROK_SLUG,
      },
    },
    async () => ({ cliVersion: "test-966" }),
  );
}

describe("#966 family judge session from ledger", () => {
  it.each([
    {
      name: "empty rows → undefined",
      rows: [] as ReadonlyArray<{ sessionId?: string }>,
      expected: undefined,
    },
    {
      name: "blank / empty sessionId skipped",
      rows: [{ sessionId: "" }, {}],
      expected: undefined,
    },
    {
      name: "latest non-empty wins",
      rows: [
        { sessionId: "sess-old" },
        { sessionId: "sess-mid" },
        { sessionId: "sess-latest" },
      ],
      expected: "sess-latest",
    },
    {
      name: "newest missing sessionId means fresh (do not resurrect older)",
      rows: [
        { sessionId: "sess-kept" },
        { sessionId: "" },
        {},
      ],
      expected: undefined,
    },
    {
      name: "newest blank sessionId means fresh",
      rows: [{ sessionId: "sess-old" }, { sessionId: "" }],
      expected: undefined,
    },
  ])("familyJudgeResumeSessionIdFromPriorRows: $name", ({ rows, expected }) => {
    expect(familyJudgeResumeSessionIdFromPriorRows(rows)).toBe(expected);
  });

  it("production runCmrWorker passes Sandcastle resumeSession when ctx carries resumeSessionId", async () => {
    // MUST F1: verifyCmr → ctx.resumeSessionId is necessary but not sufficient —
    // RealFamilyBackend.runCmrWorker must thread resumeSession into sc.run options
    // (same field single-slice resumeSession uses). Mock FamilyBackend only proves
    // ctx shape; this traps the real production sandbox options object.
    // Default cmr seat is codex (resume-capable); claudeToken-only auth preflight
    // is enough for that provider (unlike grok, which needs grokAuthDir).
    // K2: host session must be present (existsOnHost true) or resume is dropped.
    const spec = cmrWorkerSpec("resume", "completeness");
    expect(resumeCapableForSlug(spec.model)).toBe(true);
    const repo = realRepo966();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];
    class Backend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runCmrWorker(workerSpec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override agentForSpec(
        workerSpec: WorkerSpec,
        ctx?: Pick<DispatchContext, "billingPool">,
      ): sc.AgentProvider {
        const agent = super.agentForSpec(workerSpec, ctx);
        return {
          ...agent,
          sessionStorage: {
            ...agent.sessionStorage!,
            existsOnHost: async (_cwd: string, id: string) =>
              id === ROUND1_SESSION,
          },
        };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return {
          branch: "fb",
          stdout: "",
          commits: [],
          iterations: [{ sessionId: ROUND1_SESSION }],
          output: { station: "judge", status: "converged" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("966-cmr-resume-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(spec, {
      familyBase: "fb",
      cmrPass: "completeness",
      resumeSessionId: ROUND1_SESSION,
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBe(ROUND1_SESSION);
  });

  it("production runCmrWorker keeps fresh Sandcastle open when no resumeSessionId", async () => {
    const repo = realRepo966();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];
    class Backend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runCmrWorker(workerSpec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return {
          branch: "fb",
          stdout: "",
          commits: [],
          iterations: [{ sessionId: "fresh-sess-966" }],
          output: { station: "judge", status: "converged" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("966-cmr-fresh-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(cmrWorkerSpec("fresh", "completeness"), {
      familyBase: "fb",
      cmrPass: "completeness",
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBeUndefined();
  });

  it("ledger resumeSessionId + existsOnHost false → fresh Sandcastle open with priors (K2)", async () => {
    // #966 AC4 / correctness K2: ledger may still hold a judge sessionId after
    // the host session file is gone. Forcing resumeSession causes Sandcastle
    // "session not found" loops — host must drop resume and keep priors.
    const STALE = "judge-sess-stale-missing-on-host-966";
    const repo = realRepo966();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];
    const existsCalls: Array<[string, string]> = [];
    class Backend extends RealFamilyBackend {
      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runCmrWorker(workerSpec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override agentForSpec(
        spec: WorkerSpec,
        ctx?: Pick<DispatchContext, "billingPool">,
      ): sc.AgentProvider {
        const agent = super.agentForSpec(spec, ctx);
        const baseStorage = agent.sessionStorage;
        return {
          ...agent,
          sessionStorage: {
            ...baseStorage!,
            existsOnHost: async (cwd: string, sessionId: string) => {
              existsCalls.push([cwd, sessionId]);
              return false;
            },
          },
        };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return {
          branch: "fb",
          stdout: "",
          commits: [],
          iterations: [{ sessionId: "fresh-after-loss-966" }],
          output: { station: "judge", status: "converged" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("966-cmr-stale-session-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(cmrWorkerSpec("resume", "completeness"), {
      familyBase: "fb",
      cmrPass: "completeness",
      resumeSessionId: STALE,
      priorJudgeVerdicts: [
        {
          step: "cmr",
          status: "continue",
          sessionId: STALE,
        },
      ],
    });
    expect(existsCalls).toEqual([[repo, STALE]]);
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBeUndefined();
  });

  it("grok seat production runCmrWorker honors ledger resumeSession (true grok agent)", async () => {
    // #966 AC: "grok 席位真 resume" — not only fake backend recording + default
    // codex sandbox path. Dispatch model is grok-4.5 (resume-capable via #955),
    // production runCmrWorker → sandbox options carry resumeSession + grok agent.
    // K2: existsOnHost must affirm presence or resume is dropped for fresh open.
    const route = await grokCmrRoute();
    const spec = cmrWorkerSpec("resume", "completeness", route);
    expect(spec.model).toBe(GROK_SLUG);
    expect(resumeCapableForSlug(spec.model)).toBe(true);

    const repo = realRepo966();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];
    class Backend extends RealFamilyBackend {
      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runCmrWorker(workerSpec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        // Grok seat preflight requires grokAuthDir (providerAuth.grok).
        return {
          grokAuthDir: mkDir("966-grok-auth-"),
          providerAuth: { claude: false, grok: true, agy: false },
        };
      }
      protected override agentForSpec(
        workerSpec: WorkerSpec,
        ctx?: Pick<DispatchContext, "billingPool">,
      ): sc.AgentProvider {
        const agent = super.agentForSpec(workerSpec, ctx);
        return {
          ...agent,
          sessionStorage: {
            ...agent.sessionStorage!,
            existsOnHost: async (_cwd: string, id: string) =>
              id === ROUND1_SESSION,
          },
        };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return {
          branch: "fb",
          stdout: "",
          commits: [],
          iterations: [{ sessionId: ROUND1_SESSION }],
          output: { station: "judge", status: "converged" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("966-grok-resume-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(spec, {
      familyBase: "fb",
      cmrPass: "completeness",
      resumeSessionId: ROUND1_SESSION,
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBe(ROUND1_SESSION);
    // Production agent binding is the real grok provider (not codex sandbox default).
    expect(runs[0]!.agent?.name).toBe("grok");
    expect(typeof runs[0]!.agent?.sessionStorage?.captureToHost).toBe("function");
    expect(typeof runs[0]!.agent?.sessionStorage?.resumeIntoSandbox).toBe(
      "function",
    );
  });
});
