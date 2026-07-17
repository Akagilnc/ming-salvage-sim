/**
 * #961 / ADR 0139 — Family Integrated Correctness incremental checkpoints.
 *
 * Seams under test (real entry):
 *   1. lastCorrectnessConvergedHeadFromLedger — durable lineage single source
 *   2. runVerifyCmr(phase:"correctness_checkpoint") — full-strength IC court
 *      (correctness only; fixed point remains familyBaseStartHead…target HEAD)
 *   3. runFamily spine — checkpoint after batch verify green; in-flight children
 *      not injected into current target; next checkpoint includes later merges;
 *      Runner does not read lastCorrectnessConvergedHead for admission/park
 */

import { describe, expect, it } from "vitest";
import {
  lastCorrectnessConvergedHeadFromLedger,
  recordCmrPassed,
} from "../../../src/family/ledger.js";
import { runFamily } from "../../../src/family/runner.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import { activeModelRoute, modelRouteFingerprint } from "../../../src/modelRoutes.js";
import { legacyCmrScriptToWorkerOutput } from "../../helpers/judge-fixtures.js";
import { legacyDispatchFamilyWorker } from "../../../src/family/dispatchFamilyWorker.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
} from "../../../src/family/types.js";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";

function currentRouteFingerprint(): string {
  return modelRouteFingerprint(activeModelRoute());
}

function makeFamilyDocReleaseRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "ic-961-doc-"));
  const git = (args: string[]) =>
    execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  git(["init"]);
  git(["config", "user.email", "t@example.com"]);
  git(["config", "user.name", "t"]);
  writeFileSync(join(dir, "VERSION"), "1.0.0\n");
  git(["add", "."]);
  git(["commit", "-m", "doc-release"]);
  return dir;
}

class ChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<undefined> {
    return undefined;
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
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

class CapableFamilyBackend implements FamilyBackend {
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
  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly prCalls: Array<{ familyBase: string }> = [];
  readonly merges: MergeRequest[] = [];
  currentFamilyHead = "head-start";
  liveHead = "head-start";

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult | Promise<IntegratedCmrResult>;
      worker?: (spec: WorkerSpec, ctx: DispatchContext) => WorkerResult | Promise<WorkerResult>;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.currentFamilyHead = `+${child.childIssue}`;
    this.liveHead = this.currentFamilyHead;
    return { familyHead: this.currentFamilyHead };
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
  async readFamilyHead(_familyBase: string): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    const result =
      (await this.script.cmr?.(req)) ?? {
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        findings: [],
      };
    return result.findings === undefined ? { ...result, findings: [] } : result;
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    if (this.script.worker !== undefined) {
      return this.script.worker(spec, ctx);
    }
    if (spec.kind === "cmr") {
      const cmr = await this.runIntegratedCmr({
        familyBase: ctx.familyBase!,
        ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
        ...(ctx.priorCmrFindingIdentityKeys !== undefined
          ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
          : {}),
      });
      return {
        kind: "completed",
        output: legacyCmrScriptToWorkerOutput(cmr),
      };
    }
    if (spec.kind === "ship") {
      const request = { familyBase: ctx.familyBase! };
      this.prCalls.push(request);
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: request.familyBase,
          pr: `pr://${request.familyBase}`,
          prHead: this.currentFamilyHead,
          status: "pr_opened",
        },
      };
    }
    return legacyDispatchFamilyWorker(this, spec, ctx);
  }
  reconcileGit() {
    return {
      liveFamilyHead: async () => this.liveHead,
      familyBaseStartHead: async () => "head-start",
      isAncestor: async () => false,
    };
  }
  workingRepo = makeFamilyDocReleaseRepo();
}

describe("#961 lastCorrectnessConvergedHeadFromLedger — durable single source", () => {
  it("returns undefined when no correctness cmr_passed row exists", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "h1",
        routeFingerprint: "fp",
      },
    ];
    expect(lastCorrectnessConvergedHeadFromLedger(entries)).toBeUndefined();
  });

  it("returns the latest correctness cmr_passed familyHeadAfter (checkpoint or final)", () => {
    const entries: FamilyLedgerEntry[] = [
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "correctness_checkpoint",
        cmrPass: "correctness",
        familyHeadAfter: "head-wave-1",
        routeFingerprint: "fp",
      },
      {
        status: "merged",
        childIssue: 2,
        familyHeadAfter: "head-wave-2",
      },
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "correctness_checkpoint",
        cmrPass: "correctness",
        familyHeadAfter: "head-wave-2",
        routeFingerprint: "fp",
      },
    ];
    expect(lastCorrectnessConvergedHeadFromLedger(entries)).toBe("head-wave-2");
  });

  it("recordCmrPassed correctness writes the durable anchor readable by the helper", async () => {
    const backend = new CapableFamilyBackend();
    await recordCmrPassed(backend, {
      cmrPass: "correctness",
      familyHeadAfter: "converged-head",
      routeFingerprint: currentRouteFingerprint(),
      phase: "correctness_checkpoint",
    });
    expect(lastCorrectnessConvergedHeadFromLedger(backend.ledger)).toBe(
      "converged-head",
    );
  });
});

describe("#961 runVerifyCmr correctness_checkpoint — full-strength IC only", () => {
  it("GREEN verify + correctness → ok; no completeness pass; no ship", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      }),
    });
    const result = await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/961-base",
      familyBackend: backend,
      familyHeadAfter: "target-head",
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.verifyCalls.map((v) => v.phase)).toEqual([
      "correctness_checkpoint",
    ]);
    expect(backend.cmrCalls.map((c) => c.cmrPass)).toEqual(["correctness"]);
    expect(backend.prCalls).toEqual([]);
    const passed = backend.ledger.filter((e) => e.status === "cmr_passed");
    expect(passed).toHaveLength(1);
    expect(passed[0]?.cmrPass).toBe("correctness");
    expect(passed[0]?.phase).toBe("correctness_checkpoint");
    expect(lastCorrectnessConvergedHeadFromLedger(backend.ledger)).toBe(
      backend.currentFamilyHead,
    );
  });

  it("skips re-running correctness when already converged for current HEAD+route", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      }),
    });
    backend.currentFamilyHead = "same-head";
    backend.ledger.push({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "correctness_checkpoint",
      cmrPass: "correctness",
      familyHeadAfter: "same-head",
      routeFingerprint: currentRouteFingerprint(),
    });
    const result = await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/961-base",
      familyBackend: backend,
      familyHeadAfter: "same-head",
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([]);
  });
});

describe("#961 spine — incremental IC after batch verify green", () => {
  const TWO_WAVES: FamilyEpic = {
    issue: 961,
    children: [
      { issue: 1001, blockedBy: [] },
      { issue: 1002, blockedBy: [1001] },
    ],
  };

  it("fires a correctness checkpoint after each wave verify green; final still completeness→correctness", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      }),
    });
    const result = await runFamily({
      epic: TWO_WAVES,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/961-base",
    });
    expect(result.status).toBe("completed");

    // Wave verify ×2 + checkpoint verify ×2 + final verify
    const phases = backend.verifyCalls.map((v) => v.phase);
    expect(phases.filter((p) => p === "wave")).toHaveLength(2);
    expect(phases.filter((p) => p === "correctness_checkpoint").length).toBeGreaterThanOrEqual(
      2,
    );
    expect(phases).toContain("final");

    // Checkpoint + final correctness courts; completeness only at final.
    const cmrPasses = backend.cmrCalls.map((c) => c.cmrPass);
    const correctnessCount = cmrPasses.filter((p) => p === "correctness").length;
    const completenessCount = cmrPasses.filter((p) => p === "completeness").length;
    expect(correctnessCount).toBeGreaterThanOrEqual(2);
    expect(completenessCount).toBe(1);

    // Durable lineage anchor is last correctness-green head.
    expect(lastCorrectnessConvergedHeadFromLedger(backend.ledger)).toBeDefined();
  });

  it("checkpoint target is the verify-green HEAD; later merge is only in the next checkpoint", async () => {
    const checkpointTargets: string[] = [];
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: (req) => {
        if (req.cmrPass === "correctness") {
          // Capture head at the moment correctness court opens (target).
          checkpointTargets.push(backend.currentFamilyHead);
        }
        return {
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        };
      },
    });

    await runFamily({
      epic: TWO_WAVES,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/961-base",
    });

    // First correctness after wave1 must see only +1001 (not +1002).
    expect(checkpointTargets[0]).toBe("+1001");
    // A later correctness after wave2 includes +1002.
    expect(checkpointTargets.some((h) => h === "+1002")).toBe(true);
    // First checkpoint never saw wave2 merge as its target.
    expect(checkpointTargets[0]).not.toBe("+1002");
  });

  it("Runner admission/park path never reads lastCorrectnessConvergedHead", () => {
    // Import-surface / source-text guard: must fail if Runner starts importing
    // or calling the durable IC ledger helper for admission/park. IC Action /
    // verifyCmr owns lastCorrectnessConvergedHead; Runner comments may mention
    // the field name as a negative constraint, but must not bind the helper API.
    const runnerSrc = readFileSync(
      join(import.meta.dirname, "../../../src/family/runner.ts"),
      "utf8",
    );
    expect(runnerSrc).not.toMatch(/\blastCorrectnessConvergedHeadFromLedger\b/);
  });
});
