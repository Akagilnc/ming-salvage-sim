/**
 * #927 — coder refuse exit: legal receipt → blind route to judge re-adjudicate.
 *
 * Seams (owner-confirmed via #919 Testing Decisions + issue #927 AC):
 * 1. runOrchestrator + fake Backend — refuse → S6 judge re-adjudicate
 *    (uphold / reverse branches); four-reason cargo; no-burn; S4-dissolved
 *    second gate still reachable
 * 2. Pure helpers — traffic keys (envelope wins), opaque cargo pass-through
 * 3. route() — S5 refuse never parks / escalates
 *
 * Out of scope: #902 re-dispatch governance, #926 advance roster, #928 signal
 * kill, #930 family CMR judge.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  LEGAL_REFUSE_REASONS,
  coderRefuseOpaqueCargo,
  coderRefuseReverifyLanding,
  coderRefuseTrafficKeys,
  isCoderRefuseReceipt,
  mintFourReasonRefuseRecord,
  type LegalRefuseReason,
} from "../../src/coderRefuseExit.js";
import { decodeCoderEnvelope } from "../../src/stationReceiptContracts.js";
import { findingIdentityKey } from "../../src/findings.js";
import { route } from "../../src/route.js";
import {
  rebuildS5ReverifySignalsFromLedger,
  runOrchestrator,
  stepSpecsForEnv,
} from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  LedgerEntry,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import {
  completedJudge,
  judgeConverged,
  judgeContinue,
  sampleFinding,
} from "../helpers/judge-fixtures.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const PROMPTS = join(ROOT, "prompts");

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-927",
  base: "main",
  path: "/resident/worktrees/issue-927",
};

const S3_SESSION = "sess-judge-s3-927";
const S2_SESSION = "sess-coder-s2-927";

// ── fake backend ────────────────────────────────────────────────────────────

class RefuseExitBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }

  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: (WorkerLandingPayload | undefined)[] = [];
  readonly resumeSessionCalls: Array<[string, string]> = [];
  private s5DispatchCount = 0;
  private judgeIdx = 0;
  private coderIdx = 0;

  constructor(
    private readonly opts: {
      /** S3 then each S6 opening. */
      readonly judgeScripts: ReadonlyArray<WorkerResult>;
      /** S2 then each S5. */
      readonly coderOutputs: ReadonlyArray<StepOutput>;
    },
  ) {}

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async runStep(): Promise<StepOutput> {
    throw new Error("runStep called directly — use dispatchWorker");
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession called directly — use dispatchWorker");
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
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async writeLedger(): Promise<void> {}

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
    this.landings.push(landing);

    if (typeof ctx.resumeSessionId === "string") {
      this.resumeSessionCalls.push([spec.id, ctx.resumeSessionId]);
    }

    if (spec.kind === "coder") {
      const scripted = this.opts.coderOutputs[this.coderIdx];
      this.coderIdx += 1;
      if (spec.id === "S5") this.s5DispatchCount += 1;
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : S2_SESSION;
      return {
        kind: "completed",
        output:
          scripted ??
          ({ kind: "coder", committed: true, commitsAdded: 1 } as StepOutput),
        sessionId,
      };
    }

    if (
      spec.kind === "verify" ||
      spec.kind === "reviewer" ||
      spec.id === "S3" ||
      spec.id === "S6"
    ) {
      const scripted = this.opts.judgeScripts[this.judgeIdx];
      this.judgeIdx += 1;
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : S3_SESSION;
      if (scripted !== undefined) {
        return {
          ...scripted,
          sessionId: scripted.sessionId ?? sessionId,
        };
      }
      return completedJudge(judgeConverged(), sessionId);
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }

  get s5Count(): number {
    return this.s5DispatchCount;
  }

  /** First S6 landing that carried refuse keys (judge re-adjudicate cargo). */
  firstS6RefuseLanding(): {
    readonly ctx: DispatchContext;
    readonly landing: WorkerLandingPayload | undefined;
  } | undefined {
    for (let i = 0; i < this.specs.length; i++) {
      if (this.specs[i]!.id !== "S6") continue;
      const ctx = this.ctxs[i]!;
      const landing = this.landings[i];
      const keys =
        landing?.refusedFindingIdentityKeys ?? ctx.refusedFindingIdentityKeys;
      if (keys !== undefined && keys.length > 0) {
        return { ctx, landing };
      }
    }
    return undefined;
  }
}

function refuseFinding(
  claim = "overturn the ratified pin",
  location = "src/x.ts:1",
): Finding {
  return sampleFinding(claim, location);
}

function fourReasonRefuseOutput(
  finding: Finding,
  reason: LegalRefuseReason,
  evidence: string,
): StepOutput {
  const key = findingIdentityKey(finding);
  const record = mintFourReasonRefuseRecord({
    identityKey: key,
    reason,
    evidence,
    finding: finding.claim_quote,
  });
  return {
    kind: "coder",
    committed: true,
    commitsAdded: 1,
    refusedFindingIdentityKeys: [key],
    refuseRecords: [record],
  };
}

// ── pure helpers ────────────────────────────────────────────────────────────

describe("#927 pure: refuse traffic keys (envelope wins, blind to reasons)", () => {
  const key = "correctness|src/a.ts:1|claim";

  it("prefers envelope keys over refuseRecords (positive)", () => {
    expect(
      coderRefuseTrafficKeys({
        refusedFindingIdentityKeys: [key],
        refuseRecords: [
          mintFourReasonRefuseRecord({
            identityKey: "other|key|should-not-win",
            reason: "scope_creep",
            evidence: "invented AC",
          }),
        ],
      }),
    ).toEqual([key]);
  });

  it("does not drop envelope keys when refuseRecords are non-#677 cargo (regression)", () => {
    // Pre-#927: gate-only path zeroed keys when records lacked AC fields.
    const landing = coderRefuseReverifyLanding({
      refusedFindingIdentityKeys: [key],
      refuseRecords: [
        {
          identityKey: key,
          finding: "x",
          acceptanceCriterion: "y",
          conflictReason: "z",
          reason: "not_established",
          evidence: "claim mismatches code",
        },
      ],
    });
    expect(landing.refusedFindingIdentityKeys).toEqual([key]);
    expect(landing.refuseRecords?.[0]?.reason).toBe("not_established");
  });

  it("isCoderRefuseReceipt requires keys and rejects escalate dual-class (negative)", () => {
    expect(
      isCoderRefuseReceipt({
        refusedFindingIdentityKeys: [key],
      }),
    ).toBe(true);
    expect(
      isCoderRefuseReceipt({
        refusedFindingIdentityKeys: [key],
        escalate: { reason: "stuck", diagnosis: "needs owner" },
      }),
    ).toBe(false);
    expect(isCoderRefuseReceipt({ committed: false } as never)).toBe(false);
  });

  it("opaque cargo passes through without reason validation", () => {
    const invent = {
      identityKey: key,
      finding: "x",
      acceptanceCriterion: "y",
      conflictReason: "z",
      reason: "invented_reason_not_in_enum",
      evidence: "whatever",
    };
    // Runner does not validate reason tokens — judge does.
    expect(coderRefuseOpaqueCargo({ refuseRecords: [invent] })).toEqual([
      invent,
    ]);
  });

  it("mintFourReasonRefuseRecord rejects invent reasons (negative factory)", () => {
    expect(() =>
      mintFourReasonRefuseRecord({
        identityKey: key,
        reason: "hard_to_fix" as LegalRefuseReason,
        evidence: "nope",
      }),
    ).toThrow(/illegal reason/);
    expect(() =>
      mintFourReasonRefuseRecord({
        identityKey: key,
        reason: "unconstitutional",
        evidence: "   ",
      }),
    ).toThrow(/evidence/);
  });
});

describe("#927 pure: route S5 refuse → S6 (never park / escalate)", () => {
  const key = "correctness|src/x.ts:1|claim";

  it("refused with commit routes to S6", () => {
    expect(
      route({
        from: "S5",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          refusedFindingIdentityKeys: [key],
        },
      }),
    ).toEqual({ kind: "next", step: "S6" });
  });

  it("refused without commit still advances to S6 (no burn-wait)", () => {
    expect(
      route({
        from: "S5",
        output: {
          kind: "coder",
          committed: false,
          commitsAdded: 0,
          refusedFindingIdentityKeys: [key],
        },
      }),
    ).toEqual({ kind: "next", step: "S6" });
  });

  it("escalate on coder is still the global stop (orthogonal to refuse)", () => {
    expect(
      route({
        from: "S5",
        output: {
          kind: "coder",
          committed: false,
          commitsAdded: 0,
          escalate: { reason: "stuck", diagnosis: "needs owner" },
        },
      }),
    ).toEqual({ kind: "handoff", status: "escalate" });
  });
});

// ── AC: 驳回收据 → 判官复裁（改判 / 维持） ──────────────────────────────────

describe("#927 AC: refuse receipt → judge re-adjudicate (uphold / reverse)", () => {
  it("uphold branch: judge accepts refuse → converged → success (single S5)", async () => {
    const finding = refuseFinding("unconstitutional demand", "src/const.ts:1");
    const key = findingIdentityKey(finding);
    // S3 continue → S5 refuse → S6 uphold (converged: finding dead / accepted refuse).
    const backend = new RefuseExitBackend({
      judgeScripts: [
        completedJudge(judgeContinue([finding]), S3_SESSION),
        completedJudge(judgeConverged(), S3_SESSION),
      ],
      coderOutputs: [
        { kind: "coder", committed: true, commitsAdded: 1 },
        fourReasonRefuseOutput(
          finding,
          "unconstitutional",
          "finding asks to overturn accepted ADR 0132",
        ),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 927, backend });
    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual(
      expect.arrayContaining(["S5:coder", "S6:reviewer"]),
    );
    const s5 = backend.dispatched.indexOf("S5:coder");
    const s6 = backend.dispatched.indexOf("S6:reviewer");
    expect(s5).toBeGreaterThan(-1);
    expect(s6).toBeGreaterThan(s5);
    expect(backend.s5Count).toBe(1);

    const refuseLanding = backend.firstS6RefuseLanding();
    expect(refuseLanding).toBeDefined();
    expect(refuseLanding!.landing?.refusedFindingIdentityKeys).toEqual([key]);
    expect(refuseLanding!.landing?.refuseRecords?.[0]?.reason).toBe(
      "unconstitutional",
    );
    expect(refuseLanding!.landing?.refuseRecords?.[0]?.evidence).toMatch(
      /ADR 0132/,
    );
  });

  it("reverse branch: judge keeps finding live → second S5 → then converge", async () => {
    const finding = refuseFinding("still a real bug", "src/bug.ts:2");
    const key = findingIdentityKey(finding);
    const backend = new RefuseExitBackend({
      judgeScripts: [
        completedJudge(judgeContinue([finding]), S3_SESSION),
        // S6 reverse: refuse not accepted — keep live
        completedJudge(judgeContinue([finding]), S3_SESSION),
        // After second fix: converged
        completedJudge(judgeConverged(), S3_SESSION),
      ],
      coderOutputs: [
        { kind: "coder", committed: true, commitsAdded: 1 }, // S2
        fourReasonRefuseOutput(
          finding,
          "not_established",
          "coder thought claim mismatched; judge reverses",
        ), // S5#1 refuse
        { kind: "coder", committed: true, commitsAdded: 1 }, // S5#2 real fix
      ],
    });

    const result = await runOrchestrator({ issueNumber: 927, backend });
    expect(result.status).toBe("success");
    expect(backend.s5Count).toBe(2);
    // First S6 saw refuse keys
    const refuseLanding = backend.firstS6RefuseLanding();
    expect(refuseLanding?.landing?.refusedFindingIdentityKeys).toEqual([key]);
    // Sequence includes S5 → S6 → S5 → S6
    const path = backend.dispatched.filter(
      (d) => d.startsWith("S5:") || d.startsWith("S6:"),
    );
    expect(path).toEqual([
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
    ]);
  });
});

// ── AC: 驳回不再烧迭代等死（#899 morning 死法回归） ─────────────────────────

describe("#927 AC: refuse does not burn iterations (#899 morning death)", () => {
  it("S5 maxIter is 1 — refuse cannot multi-iter burn", () => {
    const specs = stepSpecsForEnv({});
    expect(specs.S5.maxIter).toBe(1);
    expect(specs.S5.maxIter).not.toBeGreaterThan(1);
  });

  it("T2 envelope status:refused is a legal single-shot receipt (not invent)", () => {
    const key = "correctness|a.ts:1|c";
    const parsed = decodeCoderEnvelope({
      station: "coderFix",
      status: "refused",
      refusedFindingIdentityKeys: [key],
      cargoPointer: "artifacts/refuse.json",
    });
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.value.status).toBe("refused");
      if (parsed.value.status === "refused") {
        expect(parsed.value.refusedFindingIdentityKeys).toEqual([key]);
      }
    }
    // Pre-#910 invent spelling has no legal envelope path
    const invent = decodeCoderEnvelope({
      station: "coderFix",
      status: "completed",
      refutedFindingIdentityKeys: [key],
    });
    expect(invent.ok).toBe(false);
  });

  it("e2e: one S5 refuse dispatch → S6; never multi-dispatch S5 for the same refuse", async () => {
    const finding = refuseFinding("burn bait", "src/burn.ts:1");
    const backend = new RefuseExitBackend({
      judgeScripts: [
        completedJudge(judgeContinue([finding]), S3_SESSION),
        completedJudge(judgeConverged(), S3_SESSION),
      ],
      coderOutputs: [
        { kind: "coder", committed: true, commitsAdded: 1 },
        // Refuse once — clean exit with legal receipt (no 5-iter burn).
        fourReasonRefuseOutput(
          finding,
          "over_defense",
          "guard fails three-question test; refuse and exit",
        ),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 927, backend });
    expect(result.status).toBe("success");
    expect(backend.s5Count).toBe(1);
    // Worker returned kind:completed with refuse traffic — not failed/retry loop.
    const s5Spec = backend.specs.find((s) => s.id === "S5");
    expect(s5Spec?.maxIter).toBe(1);
  });
});

// ── AC: 四理由各一组 — 真实入口驳回穿闸达判官复裁 ───────────────────────────

describe("#927 AC: four legal reasons each reach judge re-adjudicate", () => {
  const reasonEvidence: Record<LegalRefuseReason, string> = {
    unconstitutional: "conflicts with accepted ADR 0132 tri-state",
    over_defense: "guard fails probability/severity/downstream three questions",
    not_established: "claim does not match the real source under test",
    scope_creep: "fix would invent behavior absent from the slice AC",
  };

  for (const reason of LEGAL_REFUSE_REASONS) {
    it(`${reason}: refuse from runOrchestrator lands keys+cargo on S6`, async () => {
      const finding = refuseFinding(`finding for ${reason}`, `src/${reason}.ts:1`);
      const key = findingIdentityKey(finding);
      const backend = new RefuseExitBackend({
        judgeScripts: [
          completedJudge(judgeContinue([finding]), S3_SESSION),
          completedJudge(judgeConverged(), S3_SESSION),
        ],
        coderOutputs: [
          { kind: "coder", committed: true, commitsAdded: 1 },
          fourReasonRefuseOutput(finding, reason, reasonEvidence[reason]),
        ],
      });

      const result = await runOrchestrator({ issueNumber: 927, backend });
      expect(result.status).toBe("success");
      expect(result.status).not.toBe("escalate");
      expect(result.status).not.toBe("error");

      const refuseLanding = backend.firstS6RefuseLanding();
      expect(refuseLanding).toBeDefined();
      // Traffic keys
      expect(refuseLanding!.landing?.refusedFindingIdentityKeys).toEqual([key]);
      // Opaque cargo — runner transported reason without routing on it
      expect(refuseLanding!.landing?.refuseRecords?.[0]?.reason).toBe(reason);
      expect(refuseLanding!.landing?.refuseRecords?.[0]?.evidence).toBe(
        reasonEvidence[reason],
      );
      // Topology: S5 refuse → S6 (no S4 mechanical station)
      expect(backend.dispatched.some((d) => d.startsWith("S4:"))).toBe(false);
      const s5 = backend.dispatched.indexOf("S5:coder");
      const s6 = backend.dispatched.indexOf("S6:reviewer");
      expect(s6).toBeGreaterThan(s5);
    });
  }

  it("routing is blind to reason prose (same path for all four)", () => {
    // Pure: route does not inspect refuseRecords / reason tokens.
    for (const reason of LEGAL_REFUSE_REASONS) {
      const output = fourReasonRefuseOutput(
        refuseFinding(reason, `f/${reason}.ts:1`),
        reason,
        reasonEvidence[reason],
      );
      expect(route({ from: "S5", output })).toEqual({
        kind: "next",
        step: "S6",
      });
    }
  });
});

// ── AC: S4 溶解后 fixer refuse 第二道闸仍合法可达 ───────────────────────────

describe("#927 AC: S4 dissolved — fixer refuse second gate still reachable", () => {
  it("path is S3(judge) → S5(refuse) → S6(judge) with no S4 station", async () => {
    const finding = refuseFinding("second gate check", "src/gate.ts:1");
    const backend = new RefuseExitBackend({
      judgeScripts: [
        completedJudge(judgeContinue([finding]), S3_SESSION),
        completedJudge(judgeConverged(), S3_SESSION),
      ],
      coderOutputs: [
        { kind: "coder", committed: true, commitsAdded: 1 },
        fourReasonRefuseOutput(
          finding,
          "scope_creep",
          "finding invents out-of-scope behavior",
        ),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 927, backend });
    expect(result.status).toBe("success");

    // Exact agent path: no S4 between continue and fix / re-adjudicate.
    const agentPath = backend.dispatched.filter((d) =>
      /^(S[0-9]):/.test(d),
    );
    expect(agentPath).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
    ]);
    // Second gate: refuse cargo reached the judge seat
    expect(backend.firstS6RefuseLanding()?.landing?.refuseRecords).toHaveLength(
      1,
    );
  });

  it("rebuildS5ReverifySignalsFromLedger restores refuse keys + cargo", () => {
    const finding = refuseFinding("resume refuse", "src/r.ts:1");
    const key = findingIdentityKey(finding);
    const record = mintFourReasonRefuseRecord({
      identityKey: key,
      reason: "over_defense",
      evidence: "three questions fail",
    });
    const ledger: LedgerEntry[] = [
      {
        step: "S5",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          refusedFindingIdentityKeys: [key],
          refuseRecords: [record],
        },
      },
    ];
    const rebuilt = rebuildS5ReverifySignalsFromLedger(ledger, undefined);
    expect(rebuilt.refusedFindingIdentityKeys).toEqual([key]);
    expect(rebuilt.refuseRecords?.[0]?.reason).toBe("over_defense");
  });
});

// ── prompt / contract pins ──────────────────────────────────────────────────

describe("#927 contract pins: refused* vocabulary + four reasons in fix prompt", () => {
  it("coder_fix.md teaches refused envelope + four-reason cargo for judge", () => {
    const fix = readFileSync(join(PROMPTS, "coder_fix.md"), "utf8");
    expect(fix).toMatch(/status:"refused"|status.*"refused"/);
    expect(fix).toMatch(/refusedFindingIdentityKeys/);
    expect(fix).toMatch(/unconstitutional|违宪/);
    expect(fix).toMatch(/over_defense|过度防御/);
    expect(fix).toMatch(/not_established|事实不成立/);
    expect(fix).toMatch(/scope_creep|越权加戏/);
    // Never invent refuted* envelope keys
    expect(fix).not.toMatch(/refutedFindingIdentityKeys/);
  });
});
