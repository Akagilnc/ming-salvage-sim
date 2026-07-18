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

// ── pure mechanical signal ──────────────────────────────────────────────────

describe("#677 review-fix AC overturn gate — mechanical signal", () => {
  it("flags a fix that rewrites an assertion which predates this slice", () => {
    expect(
      preexistingAssertionTouched({
        baseToBefore: "",
        beforeToFix: [
          "diff --git a/orchestrator/test/gate.test.ts b/orchestrator/test/gate.test.ts",
          "@@ -8 +8 @@ describe('gate', () => {",
          "-  expect(result).toBe('blocked');",
          "+  expect(result).toBe('allowed');",
        ].join("\n"),
      }),
    ).toBe(true);
  });

  it("does not flag an assertion introduced by this slice before the review fix", () => {
    expect(
      preexistingAssertionTouched({
        baseToBefore: [
          "diff --git a/orchestrator/test/gate.test.ts b/orchestrator/test/gate.test.ts",
          "@@ -0,0 +1 @@",
          "+expect(result).toBe('blocked');",
        ].join("\n"),
        beforeToFix: [
          "diff --git a/orchestrator/test/gate.test.ts b/orchestrator/test/gate.test.ts",
          "@@ -1 +1 @@",
          "-expect(result).toBe('blocked');",
          "+expect(result).toBe('allowed');",
        ].join("\n"),
      }),
    ).toBe(false);
  });

  it("flags it.skip of a preexisting test (silent pin bypass)", () => {
    expect(
      preexistingAssertionTouched({
        baseToBefore: "",
        beforeToFix: [
          "diff --git a/orchestrator/test/gate.test.ts b/orchestrator/test/gate.test.ts",
          "@@ -3 +3 @@",
          '-  it("malformed ship stays blocked", () => {',
          '+  it.skip("malformed ship stays blocked", () => {',
        ].join("\n"),
      }),
    ).toBe(true);
  });

  it("flags removal of a custom assert helper call (assertBlocked)", () => {
    expect(
      preexistingAssertionTouched({
        baseToBefore: "",
        beforeToFix: [
          "diff --git a/orchestrator/test/gate.test.ts b/orchestrator/test/gate.test.ts",
          "@@ -10 +10 @@",
          "-  assertBlocked(result);",
          "+  // weakened",
        ].join("\n"),
      }),
    ).toBe(true);
  });

  it("flags assertion rewrites under src/*.test.ts (not only test/)", () => {
    expect(
      preexistingAssertionTouched({
        baseToBefore: "",
        beforeToFix: [
          "diff --git a/orchestrator/src/gate.test.ts b/orchestrator/src/gate.test.ts",
          "@@ -8 +8 @@",
          "-  expect(result).toBe('blocked');",
          "+  expect(result).toBe('allowed');",
        ].join("\n"),
      }),
    ).toBe(true);
  });

  it("does not treat +++ / --- headers as pin lines when the path matches isPinLine", () => {
    // Path contains `\bxit\b` so header text after stripping +/- would match
    // isPinLine if +++ / --- file headers were counted as added/removed lines.
    const path = "orchestrator/test/xit-something.test.ts";
    expect(
      preexistingAssertionTouched({
        baseToBefore: [
          `diff --git a/${path} b/${path}`,
          `--- a/${path}`,
          `+++ b/${path}`,
          "@@ -0,0 +1 @@",
          "+const touched = true;",
        ].join("\n"),
        beforeToFix: [
          `diff --git a/${path} b/${path}`,
          `--- a/${path}`,
          `+++ b/${path}`,
          "@@ -1 +1 @@",
          "-const touched = true;",
          "+const touched = false;",
        ].join("\n"),
      }),
    ).toBe(false);
  });

  it("fail-closes when git diff cannot run", () => {
    expect(() =>
      reviewFixAssertionSignal({
        worktreePath: join(tmpdir(), "no-such-worktree-677-missing"),
        sliceBase: "main",
        beforeFix: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        afterFix: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      }),
    ).toThrow(/fail-closed|git diff failed/i);
  });
});

// ── legal refuse outcome (not escalate / not park) ──────────────────────────

describe("#677 legal refuse one finding, fix the others", () => {
  const refuseKey =
    "correctness|src/ship.ts:1|change the established assertion so the review passes";
  const otherKey =
    "correctness|src/runner.ts:10|must fix a real correctness defect";

  it("builds a legal_refuse outcome — never escalate/park", () => {
    const outcome = reviewFixDecisionGate({
      records: [
        {
          identityKey: refuseKey,
          finding: "change the established assertion so the review passes",
          acceptanceCriterion:
            "existing malformed-ship assertion remains required",
          conflictReason:
            "adopting the finding would flip a ratified AC pin; refuse and leave for re-review",
        },
      ],
    });
    expect(outcome).toEqual({
      kind: "legal_refuse",
      refusedFindingIdentityKeys: [refuseKey],
      records: [
        expect.objectContaining({
          identityKey: refuseKey,
          acceptanceCriterion: expect.stringContaining("malformed-ship"),
        }),
      ],
    });
    // Explicit: not the old escalate shape
    expect(outcome).not.toHaveProperty("escalate");
  });

  it("empty/invalid records yield no refuse outcome", () => {
    expect(reviewFixDecisionGate({ records: [] })).toBeUndefined();
    expect(
      reviewFixDecisionGate({
        records: [
          {
            identityKey: "",
            finding: "x",
            acceptanceCriterion: "y",
            conflictReason: "z",
          },
        ],
      }),
    ).toBeUndefined();
  });

  it("malformed records elements are skipped without TypeError (element shape guards)", () => {
    const valid = {
      identityKey: refuseKey,
      finding: "change the established assertion so the review passes",
      acceptanceCriterion:
        "existing malformed-ship assertion remains required",
      conflictReason:
        "adopting the finding would flip a ratified AC pin; refuse and leave for re-review",
    };
    // Pure garbage: null / undefined / non-object / wrong-typed fields → no throw, no outcome.
    expect(() =>
      reviewFixDecisionGate({
        records: [
          null,
          undefined,
          42,
          "string",
          true,
          [],
          { identityKey: 1, finding: "x", acceptanceCriterion: "y", conflictReason: "z" },
          { identityKey: "k" }, // missing required string fields
        ] as unknown as ReviewFixRefuseRecord[],
      }),
    ).not.toThrow();
    expect(
      reviewFixDecisionGate({
        records: [
          null,
          undefined,
          42,
          "string",
          true,
          [],
          { identityKey: 1, finding: "x", acceptanceCriterion: "y", conflictReason: "z" },
          { identityKey: "k" },
        ] as unknown as ReviewFixRefuseRecord[],
      }),
    ).toBeUndefined();
    // Mixed: skip malformed, keep well-shaped — fail-closed filter, not crash.
    const outcome = reviewFixDecisionGate({
      records: [
        null,
        undefined,
        valid,
        99,
        { identityKey: refuseKey }, // incomplete
      ] as unknown as ReviewFixRefuseRecord[],
    });
    expect(outcome).toEqual({
      kind: "legal_refuse",
      refusedFindingIdentityKeys: [refuseKey],
      records: [valid],
    });
  });

  it("S5 legal refuse with commit routes to S6 fresh re-review (not escalate/error)", () => {
    expect(
      route({
        from: "S5",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          refusedFindingIdentityKeys: [refuseKey],
          refuseRecords: [
            {
              identityKey: refuseKey,
              finding: "change the established assertion so the review passes",
              acceptanceCriterion:
                "existing malformed-ship assertion remains required",
              conflictReason: "would flip ratified AC pin",
            },
          ],
        },
      }),
    ).toEqual({ kind: "next", step: "S6" });
  });

  it("S5 refuse alone without commit still advances to fresh re-review", () => {
    expect(
      route({
        from: "S5",
        output: {
          kind: "coder",
          committed: false,
          commitsAdded: 0,
          refusedFindingIdentityKeys: [refuseKey],
          refuseRecords: [
            {
              identityKey: refuseKey,
              finding: "overturn AC",
              acceptanceCriterion: "keep pin",
              conflictReason: "would flip ratified assertion",
            },
          ],
        },
      }),
    ).toEqual({ kind: "next", step: "S6" });
  });

  it("end-to-end: refuse one + fix others → not abort; still dispatches fresh re-review", async () => {
    const overturn: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "change the established assertion so the review passes",
      location: "src/ship.ts:1",
      suggested_fix: "flip the test",
      action: "fix_now",
    };
    const realBug: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "must fix a real correctness defect",
      location: "src/runner.ts:10",
      suggested_fix: "fix the bug",
      action: "fix_now",
    };
    const refuseOutcome = reviewFixDecisionGate({
      records: [
        {
          identityKey: refuseKey,
          finding: overturn.claim_quote,
          acceptanceCriterion:
            "existing malformed-ship assertion remains required",
          conflictReason: "would overturn ratified AC pin",
        },
      ],
    });
    expect(refuseOutcome?.kind).toBe("legal_refuse");

    const backend = new FixLoopBackend({
      reviewerResults: [
        {
          kind: "completed",
          output: { kind: "reviewer", findings: [overturn, realBug], findingsCount: 1, fixPacketBody: "fixture residual authored body" },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer", findings: [overturn], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: refuseKey, status: "still-active" },
              { identityKey: otherKey, status: "verified-closed" },
            ],
          },
        },
        // Second fix round closes the remaining finding without overturn.
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      coderOutputs: [
        // S2 implement
        { kind: "coder", committed: true, commitsAdded: 1 },
        // S5 — refuse one, fix the other
        {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          refusedFindingIdentityKeys: refuseOutcome!.refusedFindingIdentityKeys,
          refuseRecords: refuseOutcome!.records,
        },
        // S5 round 2 — close remaining
        {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
        },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 677, backend });

    expect(result.status).not.toBe("error");
    expect(result.status).not.toBe("escalate");
    // Fresh re-review after the partial-refuse fix commit
    expect(backend.dispatched).toEqual(
      expect.arrayContaining(["S5:coder", "S6:verify"]),
    );
    const firstS6 = backend.dispatched.indexOf("S6:verify");
    expect(firstS6).toBeGreaterThan(backend.dispatched.indexOf("S5:coder"));
    // Must not park at S5 refuse
    expect(result.status).toBe("completed");
  });
});

// ── real S5 path wires mechanical signal + decision gate ────────────────────

describe("#677 real S5 fix-commit path wiring", () => {

  it("wires reviewFixDecisionGate refuse records into the S6 landing payload", async () => {
    const overturn: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "change the established assertion so the review passes",
      location: "src/ship.ts:1",
      suggested_fix: "flip the test",
      action: "fix_now",
    };
    const realBug: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "must fix a real correctness defect",
      location: "src/runner.ts:10",
      suggested_fix: "fix the bug",
      action: "fix_now",
    };
    const refuseKey =
      "correctness|src/ship.ts:1|change the established assertion so the review passes";
    const otherKey =
      "correctness|src/runner.ts:10|must fix a real correctness defect";
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

    const backend = new FixLoopBackend({
      reviewerResults: [
        {
          kind: "completed",
          output: { kind: "reviewer", findings: [overturn, realBug], findingsCount: 1, fixPacketBody: "fixture residual authored body" },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer", findings: [overturn], findingsCount: 1, fixPacketBody: "fixture residual authored body",
            priorFindingDispositions: [
              { identityKey: refuseKey, status: "still-active" },
              { identityKey: otherKey, status: "verified-closed" },
            ],
          },
        },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      coderOutputs: [
        // S2
        { kind: "coder", committed: true, commitsAdded: 1 },
        // S5 — legal refuse via decision gate, fix the other finding
        {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          refusedFindingIdentityKeys: refuse.refusedFindingIdentityKeys,
          refuseRecords: refuse.records,
        },
        // S5 round 2
        { kind: "coder", committed: true, commitsAdded: 1 },
      ],
    });

    const result = await runOrchestrator({ issueNumber: 677, backend });
    expect(result.status).toBe("completed");
    const s6Index = backend.specs.findIndex((s) => s.id === "S6");
    expect(s6Index).toBeGreaterThanOrEqual(0);
    // #919 M3: refuse traffic keys sole on thin ctx; landing = refuseRecords only.
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

// ── CMR hard-net executable regression ──────────────────────────────────────

describe("#677 CMR ratified-assertion hard-net fixture", () => {
  it("a flipped ratified assertion with live authority becomes a blocking finding", () => {
    const findings = cmrBlockingFindingsForRatifiedAssertionFlips([
      {
        path: "orchestrator/test/ship-malformed.test.ts",
        removedAssertion: "expect(result).toBe('blocked')",
        addedAssertion: "expect(result).toBe('allowed')",
        authority:
          "AC1: existing malformed-ship assertion remains required (#598 class)",
      },
    ]);
    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({
      severity: "high",
      category: "Correctness",
      action: "fix_now",
      location: "orchestrator/test/ship-malformed.test.ts",
    });
    expect(findings[0]!.claim_quote).toMatch(/flipped ratified assertion/i);
  });

  it("does not invent a blocking finding when authority is empty (no pin)", () => {
    expect(
      cmrBlockingFindingsForRatifiedAssertionFlips([
        {
          path: "test/x.test.ts",
          removedAssertion: "expect(a).toBe(1)",
          addedAssertion: "expect(a).toBe(2)",
          authority: "   ",
        },
      ]),
    ).toEqual([]);
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
