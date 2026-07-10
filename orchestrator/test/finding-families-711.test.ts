import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { legacyDispatchWorker } from "../src/dispatchWorker.js";
import {
  FIX_FOCUS_LANDING_FILE,
  formatFixFocusMarkdown,
  priorOnlineReviewFindingsFromFamilyLedger,
  priorOnlineReviewFindingsFromLedger,
  sanitizeFindingFamilies,
} from "../src/findingFamilies.js";
import {
  parseCmrOutcome,
  parseVerifyOutcome,
} from "../src/family/realFamilyBackend.js";
import { runOnlineReviewLoopStage } from "../src/onlineReviewLoop.js";
import { verifyOutputSchema } from "../src/realBackend.js";
import { isValidVerifyResult } from "../src/reviewLoopOutcome.js";
import type {
  Backend,
  FindingFamily,
  PrReviewSnapshot,
  StepOutput,
  VerifyResult,
  WorkerLandingPayload,
} from "../src/types.js";
import { fixerWorkerSpec } from "../src/dispatchWorker.js";

const GUARD = resolve(process.cwd(), "image/bin/orchestrator-outcome-guard");

const silenceFamily = (
  members: string[],
  recurringFromRounds: number[],
  brief = "Silence must not count as green — sweep the class.",
): FindingFamily => ({
  family: "silence-not-green",
  members,
  recurringFromRounds,
  brief,
});

describe("#711 findingFamilies contract", () => {
  it("sanitizeFindingFamilies drops malformed entries but keeps valid ones", () => {
    const families = sanitizeFindingFamilies([
      {
        family: "silence-not-green",
        members: ["t:1"],
        recurringFromRounds: [1, 2],
        brief: "Silence must not count as green across call sites.",
      },
      { family: "", members: ["x"], recurringFromRounds: [1], brief: "bad" },
      "not-an-object",
    ]);
    expect(families).toEqual([
      {
        family: "silence-not-green",
        members: ["t:1"],
        recurringFromRounds: [1, 2],
        brief: "Silence must not count as green across call sites.",
      },
    ]);
  });

  it("malformed top-level findingFamilies degrades to undefined (not a gate)", () => {
    expect(sanitizeFindingFamilies("oops")).toBeUndefined();
    expect(sanitizeFindingFamilies({ family: "x" })).toBeUndefined();
  });

  it("sanitizeFindingFamilies accepts snake_case wire fields (spec naming)", () => {
    const families = sanitizeFindingFamilies([
      {
        family: "silence-not-green",
        members: ["t:1"],
        recurring_from_rounds: [1, 2],
        brief: "Fix the class.",
      },
    ]);
    expect(families).toEqual([
      {
        family: "silence-not-green",
        members: ["t:1"],
        recurringFromRounds: [1, 2],
        brief: "Fix the class.",
      },
    ]);
  });

  it("verify schema accepts finding_families snake_case top-level and degrades malformed families", () => {
    const raw = {
      converged: false,
      findingDispositions: [
        {
          identityKey: "t:1",
          threadId: "thread-1",
          action: "fix" as const,
        },
      ],
      fixMarkedFindingIdentityKeys: ["t:1"],
      finding_families: [
        {
          family: "silence-not-green",
          members: ["t:1"],
          recurring_from_rounds: [1, 2],
          brief: "Fix the class, not one call site.",
        },
        { bad: true },
      ],
    };
    const shape = verifyOutputSchema.parse(raw);
    // Nested snake_case is normalized to camelCase before schema accepts it.
    expect(shape.findingFamilies).toEqual([
      {
        family: "silence-not-green",
        members: ["t:1"],
        recurringFromRounds: [1, 2],
        brief: "Fix the class, not one call site.",
      },
      { bad: true },
    ]);
    const stdout = `<verify>${JSON.stringify(raw)}</verify>`;
    const parsed = parseVerifyOutcome(stdout);
    expect(parsed).toMatchObject({
      kind: "verify",
      converged: false,
      findingFamilies: [
        {
          family: "silence-not-green",
          members: ["t:1"],
          recurringFromRounds: [1, 2],
          brief: "Fix the class, not one call site.",
        },
      ],
    });
    expect(isValidVerifyResult(parsed as VerifyResult)).toBe(true);
  });

  it("verify schema accepts camelCase findingFamilies and parseVerifyOutcome preserves sanitized families", () => {
    const raw = {
      converged: false,
      findingDispositions: [
        {
          identityKey: "t:1",
          threadId: "thread-1",
          action: "fix" as const,
        },
      ],
      fixMarkedFindingIdentityKeys: ["t:1"],
      findingFamilies: [
        {
          family: "silence-not-green",
          members: ["t:1"],
          recurringFromRounds: [1, 2],
          brief: "Fix the class, not one call site.",
        },
        { bad: true },
      ],
    };
    const shape = verifyOutputSchema.parse(raw);
    expect(shape.findingFamilies).toEqual(raw.findingFamilies);
    const stdout = `<verify>${JSON.stringify(raw)}</verify>`;
    const parsed = parseVerifyOutcome(stdout);
    expect(parsed).toMatchObject({
      kind: "verify",
      converged: false,
      findingFamilies: [
        {
          family: "silence-not-green",
          members: ["t:1"],
          recurringFromRounds: [1, 2],
          brief: "Fix the class, not one call site.",
        },
      ],
    });
    expect(isValidVerifyResult(parsed as VerifyResult)).toBe(true);
  });

  it("verify output stays valid when findingFamilies is entirely malformed (degrade, never reject verdict)", () => {
    const raw = {
      converged: false,
      findingDispositions: [
        {
          identityKey: "t:1",
          threadId: "thread-1",
          action: "fix" as const,
        },
      ],
      fixMarkedFindingIdentityKeys: ["t:1"],
      findingFamilies: "not-an-array",
    };
    verifyOutputSchema.parse(raw);
    const parsed = parseVerifyOutcome(`<verify>${JSON.stringify(raw)}</verify>`);
    expect(parsed).toMatchObject({ kind: "verify", converged: false });
    expect((parsed as VerifyResult).findingFamilies).toBeUndefined();
    expect(isValidVerifyResult(parsed as VerifyResult)).toBe(true);

    // Even if garbage remains on an object before sanitize, isValid must not fail closed.
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: false,
        findingDispositions: [
          {
            identityKey: "t:1",
            threadId: "thread-1",
            action: "fix",
          },
        ],
        fixMarkedFindingIdentityKeys: ["t:1"],
        findingFamilies: "garbage" as unknown as FindingFamily[],
      }),
    ).toBe(true);
  });

  it("CMR parse accepts finding_families snake_case without rejecting the verdict", () => {
    const raw = {
      converged: false,
      reason: "blocking findings remain",
      successfulLegs: ["gpt-5.5"],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      findings: [
        {
          severity: "medium",
          category: "correctness",
          claim_quote: "silence treated as green",
          location: "src/a.ts",
          suggested_fix: "fail closed",
          action: "fix_now",
        },
      ],
      finding_families: [
        {
          family: "silence-not-green",
          members: [
            "standards|src/a.ts|silence treated as green",
          ],
          recurring_from_rounds: [1],
          brief: "Silence must not count as green.",
        },
      ],
      evidencePaths: ["cmr/review.json"],
    };
    const parsed = parseCmrOutcome(`<cmr>${JSON.stringify(raw)}</cmr>`, [
      { slug: "gpt-5.5" },
    ]);
    expect(parsed).toMatchObject({
      kind: "verdict",
      converged: false,
      findingFamilies: [
        {
          family: "silence-not-green",
          recurringFromRounds: [1],
        },
      ],
    });
  });
});

describe("#711 outcome-guard allowlist", () => {
  it("accepts legal findingFamilies on a CMR draft", () => {
    const dir = mkdtempSync(join(tmpdir(), "outcome-guard-711-families-"));
    try {
      mkdirSync(join(dir, "cmr"), { recursive: true });
      writeFileSync(join(dir, "cmr", "review.json"), '{"ok":true}\n', "utf8");

      const outcome = {
        converged: false,
        reason: "blocking findings remain",
        successfulLegs: ["gpt-5.5"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        findings: [
          {
            severity: "medium",
            category: "correctness",
            claim_quote: "silence treated as green",
            location: "src/a.ts",
            suggested_fix: "fail closed on silence",
            action: "fix_now",
          },
        ],
        findingFamilies: [
          {
            family: "silence-not-green",
            members: ["standards|src/a.ts|silence treated as green"],
            recurringFromRounds: [1, 2],
            brief: "Silence must not count as green across sites.",
          },
        ],
        evidencePaths: ["cmr/review.json"],
      };
      const draftPath = join(dir, "draft.json");
      const sidecarPath = join(dir, "outcome.json");
      writeFileSync(draftPath, JSON.stringify(outcome), "utf8");
      writeFileSync(sidecarPath, "", "utf8");

      const stdout = execFileSync(
        GUARD,
        [
          "--role",
          "cmr",
          "--draft",
          draftPath,
          "--outcome",
          sidecarPath,
          "--evidence-root",
          dir,
          "--completion-signal",
          "CMR_STEP_COMPLETE",
        ],
        { encoding: "utf8" },
      );

      expect(JSON.parse(readFileSync(sidecarPath, "utf8"))).toEqual(outcome);
      expect(stdout).toContain("findingFamilies");
      expect(stdout).toContain("CMR_STEP_COMPLETE");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("#711 prior round findings + fix-focus forwarding", () => {
  const worktrees: string[] = [];
  afterEach(() => {
    for (const dir of worktrees.splice(0)) {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("priorOnlineReviewFindingsFromLedger collects rounds before the current one", () => {
    const ledger = [
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["t:1"],
        } satisfies VerifyResult,
      },
      { step: "S10", output: { kind: "fixer", committed: true, fixCommitSha: "abc" } },
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["t:2"],
        } satisfies VerifyResult,
      },
    ];
    expect(priorOnlineReviewFindingsFromLedger(ledger, 3)).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["t:1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["t:2"] },
    ]);
  });

  it("priorOnlineReviewFindingsFromFamilyLedger reads fix_committed markers (not S9 rows)", () => {
    const familyLedger = [
      {
        event: "online_review_fix_committed",
        onlineReviewRound: 1,
        fixMarkedFindingIdentityKeys: ["silence:r1"],
        familyHeadAfter: "sha1",
      },
      {
        event: "online_review_round_retrigger",
        onlineReviewRound: 2,
        roundTriggerHeadOid: "sha1",
      },
      {
        event: "online_review_fix_committed",
        onlineReviewRound: 2,
        fixMarkedFindingIdentityKeys: ["silence:r2"],
        familyHeadAfter: "sha2",
      },
    ];
    // Old S9-shaped extractor on family rows yields nothing:
    expect(
      priorOnlineReviewFindingsFromLedger(
        familyLedger as ReadonlyArray<{
          readonly step?: string;
          readonly output?: StepOutput;
        }>,
        3,
      ),
    ).toEqual([]);
    // Family-aware extractor recovers prior rounds:
    expect(priorOnlineReviewFindingsFromFamilyLedger(familyLedger, 3)).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["silence:r2"] },
    ]);
  });

  it("formatFixFocusMarkdown is pure data (no method instructions)", () => {
    const md = formatFixFocusMarkdown([
      silenceFamily(["t:1", "t:2"], [1, 2], "Silence must not count as green."),
    ]);
    expect(md).toContain("Recurring from rounds: 1, 2");
    expect(md).toContain("silence-not-green");
    expect(md).toContain("Silence must not count as green.");
    // Method belongs in versioned souls — runner only serializes data.
    expect(md.toLowerCase()).not.toMatch(/same-type sweep|run same-type|per family/);
  });

  it("r3 fixer dispatch writes .fix-focus.md with recurring markers (runner pure IO)", async () => {
    const worktree = mkdtempSync(join(tmpdir(), "fix-focus-711-"));
    const stateDir = mkdtempSync(join(tmpdir(), "fix-focus-state-711-"));
    worktrees.push(worktree, stateDir);
    const landingPayload: WorkerLandingPayload = {
      onlineReviewSnapshot: {
        prUrl: "https://github.com/o/r/pull/42",
        headOid: "abc",
        totalFindingCount: 1,
        quiescent: false,
        bots: {
          coderabbit: { state: "complete", findingCount: 1 },
          sourcery: { state: "complete", findingCount: 0 },
          codex: { state: "complete", findingCount: 0 },
          gemini: { state: "complete", findingCount: 0 },
        },
        droppedBots: [],
        threads: [],
        checkRuns: [],
      },
      onlineReviewRound: 3,
      fixMarkedFindingIdentityKeys: ["t:3"],
      findingFamilies: [
        silenceFamily(
          ["t:3"],
          [1, 2],
          "Same class recurred — sweep all silence-as-green sites.",
        ),
      ],
    };
    const spec = fixerWorkerSpec();
    // A defined dispatchWorker skips the offline skeleton short-circuit so the
    // legacy path reaches landing + fix-focus writes (same pattern as #600 r17).
    const legacyBackend = {
      dispatchWorker: async () => ({
        kind: "completed" as const,
        output: {
          kind: "fixer",
          committed: true,
          fixCommitSha: "deadbeef",
        },
      }),
      async runStep(): Promise<StepOutput> {
        return {
          kind: "fixer",
          committed: true,
          fixCommitSha: "deadbeef",
        };
      },
    } as unknown as Backend;
    await legacyDispatchWorker(
      legacyBackend,
      spec,
      {
        worktree: { branch: "feat/x", base: "main", path: worktree },
        stateDir,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        onlineReviewRound: 3,
      },
      landingPayload,
    );
    const fixFocusPath = join(stateDir, "fix-focus.md");
    const fixFocus = readFileSync(fixFocusPath, "utf8");
    expect(fixFocus).toContain("Recurring from rounds: 1, 2");
    expect(fixFocus).toContain("silence-not-green");
    expect(fixFocus).toContain("sweep all silence-as-green sites");
    expect(fixFocus.toLowerCase()).not.toMatch(/run same-type/);
  });
});

describe("#711 three-round reviewer→ledger→fixer path + no-briefing baseline", () => {
  const stageShip = {
    kind: "ship" as const,
    branch: "family/epic-711",
    status: "pr_opened",
    pr: "pr://family/711-stage",
    prHead: "head-1",
  };

  const baseSnapshot: PrReviewSnapshot = {
    repo: "o/r",
    prNumber: 711,
    prUrl: "pr://family/711-stage",
    headOid: "head-1",
    pollCount: 1,
    bots: {
      coderabbit: { state: "complete", findingCount: 1 },
      sourcery: { state: "complete", findingCount: 0 },
      codex: { state: "complete", findingCount: 0 },
      gemini: { state: "complete", findingCount: 0 },
    },
    threads: [
      {
        id: "thread-silence",
        bot: "coderabbit",
        path: "src/a.ts",
        line: 1,
        body: "silence treated as green",
        isResolved: false,
        comments: [],
      },
    ],
    checkRuns: [],
    totalFindingCount: 1,
    quiescent: true,
  };

  it("three-round path: r3 verify sees prior rounds; r3 fixer receives recurring families", async () => {
    const verifyLandings: WorkerLandingPayload[] = [];
    const fixerLandings: WorkerLandingPayload[] = [];
    const familyLedger: Array<{
      event: string;
      onlineReviewRound?: number;
      fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
      familyHeadAfter?: string;
    }> = [];

    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async (landing, round) => {
        verifyLandings.push(landing);
        if (round >= 4) {
          return { kind: "verify", converged: true, isRecheck: true } satisfies VerifyResult;
        }
        const key = `silence:r${round}`;
        const priorRounds = (landing.priorRoundFindings ?? []).map((p) => p.round);
        return {
          kind: "verify",
          converged: false,
          isRecheck: round > 1,
          fixMarkedFindingIdentityKeys: [key],
          findingDispositions: [
            {
              identityKey: key,
              threadId: "thread-silence",
              action: "fix",
            },
          ],
          findingFamilies: [
            silenceFamily(
              [key],
              priorRounds,
              priorRounds.length > 0
                ? "Same silence-as-green class recurred — sweep all sites."
                : "Silence must not count as green.",
            ),
          ],
        } satisfies VerifyResult;
      },
      dispatchFixer: async (landing) => {
        fixerLandings.push(landing);
        const n = fixerLandings.length;
        return {
          kind: "fixer",
          committed: true,
          fixCommitSha: `fix-sha-${n}`,
        };
      },
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify) => verify,
      resolveFixCommitSha: async (sha) => {
        const lastFixer = fixerLandings[fixerLandings.length - 1]!;
        familyLedger.push({
          event: "online_review_fix_committed",
          onlineReviewRound: lastFixer.onlineReviewRound ?? fixerLandings.length,
          fixMarkedFindingIdentityKeys: lastFixer.fixMarkedFindingIdentityKeys ?? [],
          familyHeadAfter: sha,
        });
        return sha;
      },
      retriggerAfterFix: () => {},
    }, {
      // Family resume path: when in-loop accum is empty, seed from family ledger markers.
      enrichVerifyLanding: async (landing, round) => {
        if (
          landing.priorRoundFindings !== undefined &&
          landing.priorRoundFindings.length > 0
        ) {
          return landing;
        }
        const prior = priorOnlineReviewFindingsFromFamilyLedger(familyLedger, round);
        return prior.length > 0 ? { ...landing, priorRoundFindings: prior } : landing;
      },
    });

    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 4 });
    expect(verifyLandings).toHaveLength(4);
    expect(fixerLandings).toHaveLength(3);

    // r1 verify has no prior rounds
    expect(verifyLandings[0]!.priorRoundFindings ?? []).toEqual([]);

    // r2 verify sees r1 fix-marked keys
    expect(verifyLandings[1]!.priorRoundFindings).toMatchObject([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
    ]);

    // r3 verify sees r1+r2
    expect(verifyLandings[2]!.priorRoundFindings).toMatchObject([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["silence:r2"] },
    ]);

    // r3 fixer receives families with recurring markers from r3 verify synthesis
    const r3Fixer = fixerLandings[2]!;
    expect(r3Fixer.findingFamilies).toEqual([
      silenceFamily(
        ["silence:r3"],
        [1, 2],
        "Same silence-as-green class recurred — sweep all sites.",
      ),
    ]);
    const fixFocus = formatFixFocusMarkdown(r3Fixer.findingFamilies!);
    expect(fixFocus).toContain("Recurring from rounds: 1, 2");
    expect(fixFocus).toContain("silence-not-green");

    // Family ledger received fix markers with keys (resume source)
    expect(familyLedger).toHaveLength(3);
    expect(priorOnlineReviewFindingsFromFamilyLedger(familyLedger, 3)).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["silence:r2"] },
    ]);
  });

  it("no-briefing baseline: without findingFamilies, fixer landing has no family brief", async () => {
    const fixerLandings: WorkerLandingPayload[] = [];
    let verifyCalls = 0;

    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async (_landing, round) => {
        verifyCalls += 1;
        if (round >= 2) {
          return { kind: "verify", converged: true, isRecheck: true } satisfies VerifyResult;
        }
        return {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["t:only"],
          findingDispositions: [
            {
              identityKey: "t:only",
              threadId: "thread-silence",
              action: "fix",
            },
          ],
          // deliberately no findingFamilies
        } satisfies VerifyResult;
      },
      dispatchFixer: async (landing) => {
        fixerLandings.push(landing);
        return {
          kind: "fixer",
          committed: true,
          fixCommitSha: "fix-once",
        };
      },
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });

    expect(result.ok).toBe(true);
    expect(verifyCalls).toBeGreaterThanOrEqual(2);
    expect(fixerLandings).toHaveLength(1);
    expect(fixerLandings[0]!.findingFamilies).toBeUndefined();
    expect(fixerLandings[0]!.fixMarkedFindingIdentityKeys).toEqual(["t:only"]);
  });
});
