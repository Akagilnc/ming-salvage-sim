/**
 * #296 — the verify-cmr hook body driven through the REAL spine (no injected
 * `verifyCmr`), against a capable `FamilyBackend` (ADR 0022 decision 3④/⑤/⑥/4).
 *
 * `runner-verify-cmr.test.ts` (#293) proves the spine WIRING with an injected
 * fake hook. Here the spine uses the DEFAULT `runVerifyCmr` module export (#296's
 * filled body) and a `FamilyBackend` that supplies the verify/cmr/PR/abort/
 * escalate capabilities — so the three acceptance criteria are proven end-to-end
 * through the actual family loop, not just the hook in isolation:
 *
 *   1. a red WAVE verify aborts before the next wave + writes `aborted` + leaves
 *      the run observably `verify_failed` (NOT a false success);
 *   2. a NOT-converged integrated cmr at the final barrier escalates续跑 (#298) +
 *      `verify_failed`;
 *   3. all green ⇒ the family PR is OPENED (止于 PR) and the run is `success` —
 *      and the spine never merges to main (no merge-to-main call exists).
 *
 * Zero container: the single-slice child runs on a fake Backend, the family
 * verify/cmr/PR all on a scriptable fake FamilyBackend — no real codex / push.
 */

import { describe, expect, it } from "vitest";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { findingIdentityKey } from "../../../src/findings.js";
import { legacyDispatchFamilyWorker } from "../../../src/family/dispatchFamilyWorker.js";
import { recordFamilyEscalated } from "../../../src/family/ledger.js";
import { runFamily } from "../../../src/family/runner.js";
import { legacyCmrScriptToWorkerOutput } from "../../helpers/judge-fixtures.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import type {

  FamilyAbortedEvent,
  FamilyBackend,
  FamilyEpic,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  ReconcileGit,
} from "../../../src/family/types.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

/** A single-slice Backend that drives every child to S8(success). */
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

/** A family backend with the #296 verify/cmr/PR/abort/escalate capabilities. */
// ─── fakes ────────────────────────────────────────────────────────────────────

function makeFamilyDocReleaseRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "capable-family-doc-"));
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
  readonly merges: MergeRequest[] = [];
  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: Array<{ readonly familyBase: string }> = [];
  readonly workingRepo: string;
  liveHead: string | undefined;

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult;
    } = {},
    workingRepo?: string,
  ) {
    this.workingRepo = workingRepo ?? makeFamilyDocReleaseRepo();
  }

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.liveHead = `+${child.childIssue}`;
    return { familyHead: this.liveHead };
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
    if (this.liveHead === undefined) throw new Error("no live head");
    return this.liveHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    // Default green is boolean converged without open-count — fake dispatch
    // emits live kind:judge (happy 直出). findingsCount:0 stays residual unusable
    // (#919 M2/R7 never silent clean).
    const result = this.script.cmr?.(req) ?? {
      converged: true,
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
    };
    return result.findings === undefined ? { ...result, findings: [] } : result;
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
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
      const familyBase = ctx.familyBase!;
      this.prCalls.push({ familyBase });
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: familyBase,
          pr: `pr://${familyBase}`,
          ...(this.liveHead !== undefined ? { prHead: this.liveHead } : {}),
          status: "pr_opened",
        },
      };
    }
    return legacyDispatchFamilyWorker(this, spec, ctx);
  }
  resolveFamilyWorkingRepo(): string | undefined {
    return this.workingRepo;
  }
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
    await recordFamilyEscalated(this, {
      escalationKind: "decision",
      phase: "final",
      reason: esc.reason,
      familyHeadAfter: esc.familyHeadAfter,
      stopSummary: esc.stopSummary,
    });
  }
}

class StaticReconcileGit implements ReconcileGit {
  constructor(private readonly liveHead: string, private readonly startHead: string = "base0") {}
  async liveFamilyHead(): Promise<string> {
    return this.liveHead;
  }
  async familyBaseStartHead(): Promise<string> {
    return this.startHead;
  }
  async childHeadExists(): Promise<{ exists: boolean; childHead?: string }> {
    return { exists: false };
  }
  async isAncestor(a: string, b: string): Promise<boolean> {
    return a === b || a === this.startHead || b === this.liveHead;
  }
}

const TWO_WAVES: FamilyEpic = {
  issue: 291,
  children: [
    { issue: 294, blockedBy: [] },
    { issue: 296, blockedBy: [294] },
  ],
};

function epicWith(...issues: number[]): FamilyEpic {
  return { issue: 291, children: issues.map((issue) => ({ issue, blockedBy: [] })) };
}

describe("#296 spine integration — fail-safe: verify-green but a required final-barrier capability missing must NOT be success", () => {
  it("a real backend that verifies green but lacks runIntegratedCmr leaves the run cmr_failed (NOT a false success)", async () => {
    // The 承重闸 (integrated cmr, decision 3⑥) cannot run, so the run must NOT report
    // success — that would ship code the integrated cmr never reviewed. The spine
    // ignores the hook's `ran` flag and acts on `ok`, so the hook must fail-safe to
    // ok:false (verify_failed at the final phase) rather than the nothing-ran no-op.
    class VerifyOnlySpineBackend implements FamilyBackend {
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
      async mergeChildIntoFamilyBase(c: MergeRequest): Promise<{ familyHead: string }> {
        return { familyHead: `+${c.childIssue}` };
      }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

      async appendFamilyLedger(e: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(e);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
      async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
        this.verifyCalls.push(req);
        return { ok: true };
      }
      // No integrated-CMR or family worker capability (a real-but-incomplete backend).
    }
    const backend = new VerifyOnlySpineBackend();
    const result = await runFamily({
      epic: epicWith(294),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      // NO verifyCmr injection → the spine uses #296's real runVerifyCmr.
    });
    // Wave verify green + #961 IC checkpoint; missing CMR capability fails the
    // checkpoint (or final) with cmr_failed (#922), never success.
    expect(backend.verifyCalls.map((v) => v.phase)).toEqual([
      "wave",
      "correctness_checkpoint",
    ]);
    expect(result.status).toBe("failed");
    expect(result.stopSummary.reason).toBe("cmr_failed");
    expect(result.failedPhase).toBe("correctness_checkpoint");
  });
});
