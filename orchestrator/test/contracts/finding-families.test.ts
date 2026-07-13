import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { legacyDispatchWorker } from "../../src/dispatchWorker.js";
import { mergeResumeLedgerHistory } from "../../src/runner.js";
import {
  FIX_FOCUS_LANDING_FILE,
  formatFixFocusMarkdown,
  isFindingFamilyArray,
  mergePriorRoundFindings,
  priorCmrFindingsFromFamilyLedger,
  priorOnlineReviewFindingsFromFamilyLedger,
  priorOnlineReviewFindingsFromLedger,
  sanitizeFindingFamilies,
} from "../../src/findingFamilies.js";
import {
  parseCmrOutcome,
  parseVerifyOutcome,
} from "../../src/family/realFamilyBackend.js";
import { runOnlineReviewLoopStage } from "../../src/onlineReviewLoop.js";
import { verifyOutputSchema } from "../../src/realBackend.js";
import { isValidVerifyResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  FindingFamily,
  LedgerEntry,
  StepOutput,
  VerifyResult,
  WorkerLandingPayload,
} from "../../src/types.js";
import type { PrReviewSnapshot } from "../../src/botPolling.js";
import { fixerWorkerSpec } from "../../src/dispatchWorker.js";

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

  it("isFindingFamilyArray rejects normalized-only aliases", () => {
    expect(
      isFindingFamilyArray([
        {
          family: "silence-not-green",
          members: ["t:1"],
          recurring_from_rounds: [1],
          brief: "Fix the class.",
        },
      ]),
    ).toBe(false);
    expect(
      isFindingFamilyArray([
        {
          family: "silence-not-green",
          members: ["t:1"],
          recurringFromRounds: [1],
          brief: "Fix the class.",
        },
      ]),
    ).toBe(true);
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

  it("duplicate camelCase and snake_case family keys degrade to no briefing", () => {
    const raw = {
      converged: false,
      findingDispositions: [
        { identityKey: "t:1", threadId: "thread-1", action: "fix" as const },
      ],
      findingFamilies: [
        {
          family: "camel",
          members: ["t:1"],
          recurringFromRounds: [],
          brief: "camel",
        },
      ],
      finding_families: [
        {
          family: "snake",
          members: ["t:1"],
          recurring_from_rounds: [],
          brief: "snake",
        },
      ],
    };

    const parsed = parseVerifyOutcome(`<verify>${JSON.stringify(raw)}</verify>`);
    expect(parsed).toMatchObject({ kind: "verify", converged: false });
    expect((parsed as VerifyResult).findingFamilies).toBeUndefined();
    expect(isValidVerifyResult(parsed as VerifyResult)).toBe(true);
  });

  it("verify prompt contains only the data and output contract", () => {
    const prompt = readFileSync(resolve(process.cwd(), "prompts/verify.md"), "utf8");
    expect(prompt).not.toContain("use it to mark recurringFromRounds");
    expect(prompt).not.toContain("When `priorRoundFindings` is in the landing file");
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
      successfulLegs: ["gpt-5.6-sol"],
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
      { slug: "gpt-5.6-sol" },
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

describe("#711 prior round findings + fix-focus forwarding", () => {
  const worktrees: string[] = [];
  afterEach(() => {
    for (const dir of worktrees.splice(0)) {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("priorOnlineReviewFindingsFromLedger collects rounds before the current one", () => {
    const ledger: LedgerEntry[] = [
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

  it("keys S9 rows by round number, not array position (CI-pending timeouts do not shift rounds)", () => {
    // runner.ts parks CI-pending by persisting an S9 verify row without
    // incrementing onlineReviewRound — so a later real re-verify shares the
    // same round. Position-based slice(0, priorCount) would keep the stale
    // pending row and drop the real fix-marked findings.
    const ledger: LedgerEntry[] = [
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["t:r1"],
        } satisfies VerifyResult,
      },
      {
        step: "S10",
        output: { kind: "fixer", committed: true, fixCommitSha: "fix-1" },
      },
      // r2 CI-pending timeout: extra S9 row, same logical round, stale keys
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["stale-pending"],
        } satisfies VerifyResult,
      },
      // r2 real re-verify after resume / CI completes
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["t:r2-real"],
        } satisfies VerifyResult,
      },
    ];
    expect(priorOnlineReviewFindingsFromLedger(ledger, 3)).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["t:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["t:r2-real"] },
    ]);
  });

  it("does not let a resume-seeded ledger prefix double-count inferred rounds", () => {
    const s9Round1: LedgerEntry = {
      step: "S9",
      output: {
        kind: "verify",
        converged: false,
        fixMarkedFindingIdentityKeys: ["t:r1"],
      } satisfies VerifyResult,
    };
    const s10Round1: LedgerEntry = {
      step: "S10",
      output: { kind: "fixer", committed: true, fixCommitSha: "fix-1" },
    };
    const s9Round2: LedgerEntry = {
      step: "S9",
      output: {
        kind: "verify",
        converged: false,
        fixMarkedFindingIdentityKeys: ["t:r2"],
      } satisfies VerifyResult,
    };

    // S7 resume planning seeds these same entry objects into the in-memory
    // ledger before appending new rows. Reference de-duplication must preserve
    // the original inferred round sequence.
    expect(
      priorOnlineReviewFindingsFromLedger(
        mergeResumeLedgerHistory(
          [s9Round1, s10Round1],
          [s9Round1, s10Round1, s9Round2],
        ),
        3,
      ),
    ).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["t:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["t:r2"] },
    ]);
  });

  it("prefers non-empty fix-marked keys when a later pending row would overwrite", () => {
    const ledger: LedgerEntry[] = [
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["t:r1-real"],
        } satisfies VerifyResult,
      },
      // Same round, empty pending re-poll must not erase r1
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: [],
        } satisfies VerifyResult,
      },
      {
        step: "S10",
        output: { kind: "fixer", committed: true, fixCommitSha: "fix-1" },
      },
      {
        step: "S9",
        output: {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["t:r2"],
        } satisfies VerifyResult,
      },
    ];
    expect(priorOnlineReviewFindingsFromLedger(ledger, 3)).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["t:r1-real"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["t:r2"] },
    ]);
  });

  it("mergePriorRoundFindings unions by round (later source wins same round)", () => {
    expect(
      mergePriorRoundFindings(
        [
          { round: 1, fixMarkedFindingIdentityKeys: ["ledger:r1"] },
          { round: 2, fixMarkedFindingIdentityKeys: ["ledger:r2-stale"] },
        ],
        [{ round: 2, fixMarkedFindingIdentityKeys: ["process:r2"] }],
      ),
    ).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["ledger:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["process:r2"] },
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

  it("priorCmrFindingsFromFamilyLedger excludes other and unclassified CMR passes", () => {
    const finding = {
      severity: "medium" as const,
      category: "correctness" as const,
      claim_quote: "silence treated as green",
      location: "src/a.ts",
      suggested_fix: "fail closed",
      action: "fix_now" as const,
    };
    const ledger = [
      { event: "cmr_reviewed", cmrPass: "completeness", blockingFindingIdentityKeys: ["reviewed:complete"] },
      { output: { kind: "cmr", findings: [finding] }, cmrPass: "correctness" },
      { output: { kind: "cmr", findings: [finding] }, cmrPass: "completeness" },
      { output: { kind: "cmr", findings: [finding] } },
    ];

    expect(priorCmrFindingsFromFamilyLedger(ledger, "completeness")).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: [], blockingFindingIdentityKeys: ["reviewed:complete"] },
      { round: 2, fixMarkedFindingIdentityKeys: [], blockingFindingIdentityKeys: ["correctness|src/a.ts|silence treated as green"] },
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

  it("coder_fix prompt is pure data; same-type sweep method lives in coder soul", () => {
    const prompt = readFileSync(
      resolve(process.cwd(), "prompts/coder_fix.md"),
      "utf8",
    );
    const soul = readFileSync(
      resolve(process.cwd(), "image/souls/coder.md"),
      "utf8",
    );
    // Runner-owned prompt file must not carry workflow method (#711 R2).
    expect(prompt.toLowerCase()).not.toMatch(
      /same-type sweep|run same-type|per family/,
    );
    // Online fixer already has this in souls/fixer.md; per-slice coder-fix
    // mirrors it in the coder soul.
    expect(soul).toMatch(/same-type sweeps?\s+\*\*per family\*\*/i);
    expect(soul).toMatch(/\.fix-focus\.md/);
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

  /** Multi-site silence-as-green class — briefing must expand fix coverage. */
  const FAMILY_SITES = [
    "silence:site-a",
    "silence:site-b",
    "silence:site-c",
  ] as const;

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
        authorLogin: "coderabbit",
        threadNodeId: "thread-silence-node",
        path: "src/a.ts",
        line: 1,
        body: "silence treated as green",
        isResolved: false,
      },
    ],
    checkRuns: [],
    roundTriggerUsed: { headOid: "head-1", triggeredAt: "2026-07-10T00:00:00.000Z" },
    checkRunsEmptyMeans: "converged",
    totalFindingCount: 1,
    quiescent: true,
  };

  function mutateFixturesFromFixerLanding(
    landing: WorkerLandingPayload,
    fixtures: Map<string, boolean>,
  ): void {
    const sites = new Set(landing.fixMarkedFindingIdentityKeys ?? []);
    for (const family of landing.findingFamilies ?? []) {
      for (const member of family.members) sites.add(member);
    }
    for (const site of sites) {
      if (fixtures.has(site)) fixtures.set(site, true);
    }
  }

  function coverageFromFixtures(fixtures: Map<string, boolean>): string[] {
    return [...fixtures].filter(([, fixed]) => fixed).map(([site]) => site);
  }

  function mergeEnrichFromLedger(
    familyLedger: ReadonlyArray<{
      readonly event: string;
      readonly onlineReviewRound?: number;
      readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
    }>,
  ) {
    return async (
      landing: WorkerLandingPayload,
      round: number,
    ): Promise<WorkerLandingPayload> => {
      const fromLedger = priorOnlineReviewFindingsFromFamilyLedger(
        familyLedger,
        round,
      );
      const merged = mergePriorRoundFindings(
        fromLedger,
        landing.priorRoundFindings ?? [],
      );
      return merged.length > 0
        ? { ...landing, priorRoundFindings: merged }
        : landing;
    };
  }

  it("three-round path: r3 fixer sees recurring marker and covers all family sites", async () => {
    const verifyLandings: WorkerLandingPayload[] = [];
    const fixerLandings: WorkerLandingPayload[] = [];
    const fixerCoverage: string[][] = [];
    const fixtures = new Map(FAMILY_SITES.map((site) => [site, false]));
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
          return {
            kind: "verify",
            converged: true,
            isRecheck: true,
            fixMarkedFindingIdentityKeys:
              landing.fixMarkedFindingIdentityKeys ?? [],
          } satisfies VerifyResult;
        }
        const key = `silence:r${round}`;
        const priorRounds = (landing.priorRoundFindings ?? []).map((p) => p.round);
        // At r3 the class has recurred — synthesise multi-site family brief.
        const members =
          priorRounds.length >= 2 ? [...FAMILY_SITES] : [key];
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
              members,
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
        mutateFixturesFromFixerLanding(landing, fixtures);
        fixerCoverage.push(coverageFromFixtures(fixtures));
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
      enrichVerifyLanding: mergeEnrichFromLedger(familyLedger),
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

    // r3 fixer input must show recurring marker + multi-site family
    const r3Fixer = fixerLandings[2]!;
    expect(r3Fixer.findingFamilies).toEqual([
      silenceFamily(
        [...FAMILY_SITES],
        [1, 2],
        "Same silence-as-green class recurred — sweep all sites.",
      ),
    ]);
    const fixFocus = formatFixFocusMarkdown(r3Fixer.findingFamilies!);
    expect(fixFocus).toContain("Recurring from rounds: 1, 2");
    expect(fixFocus).toContain("silence-not-green");
    expect(fixFocus).toContain("silence:site-a");
    expect(fixFocus).toContain("silence:site-b");
    expect(fixFocus).toContain("silence:site-c");

    // Acceptance bite: briefing expands coverage to all family sites
    expect(fixerCoverage[2]).toEqual([...FAMILY_SITES]);
    expect(new Set(fixerCoverage[2]).size).toBe(FAMILY_SITES.length);

    // Family ledger received fix markers with keys (resume source)
    expect(familyLedger).toHaveLength(3);
    expect(priorOnlineReviewFindingsFromFamilyLedger(familyLedger, 3)).toEqual([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["silence:r2"] },
    ]);
  });

  it("resume mid-loop merges ledger history with in-process rounds so r3 sees r1+r2", async () => {
    // Simulate crash after r1 fix: ledger has r1 marker; process restarts at r2.
    const familyLedger: Array<{
      event: string;
      onlineReviewRound?: number;
      fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
      familyHeadAfter?: string;
    }> = [
      {
        event: "online_review_fix_committed",
        onlineReviewRound: 1,
        fixMarkedFindingIdentityKeys: ["silence:r1"],
        familyHeadAfter: "sha-r1",
      },
    ];
    const verifyLandings: WorkerLandingPayload[] = [];
    const fixerLandings: WorkerLandingPayload[] = [];

    const result = await runOnlineReviewLoopStage(
      stageShip,
      {
        poll: async () => baseSnapshot,
        dispatchVerify: async (landing, round) => {
          verifyLandings.push(landing);
          if (round >= 4) {
            return {
              kind: "verify",
              converged: true,
              isRecheck: true,
              fixMarkedFindingIdentityKeys:
                landing.fixMarkedFindingIdentityKeys ?? [],
            } satisfies VerifyResult;
          }
          const key = `silence:r${round}`;
          return {
            kind: "verify",
            converged: false,
            isRecheck: true,
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
                (landing.priorRoundFindings ?? []).map((p) => p.round),
                "Recurring class.",
              ),
            ],
          } satisfies VerifyResult;
        },
        dispatchFixer: async (landing) => {
          fixerLandings.push(landing);
          return {
            kind: "fixer",
            committed: true,
            fixCommitSha: `resume-fix-${landing.onlineReviewRound ?? "?"}`,
          };
        },
        dispatchDocRelease: async () => true,
        applySideEffects: (_landing, verify) => verify,
        resolveFixCommitSha: async (sha) => {
          const lastFixer = fixerLandings[fixerLandings.length - 1]!;
          familyLedger.push({
            event: "online_review_fix_committed",
            onlineReviewRound:
              lastFixer.onlineReviewRound ?? fixerLandings.length + 1,
            fixMarkedFindingIdentityKeys:
              lastFixer.fixMarkedFindingIdentityKeys ?? [],
            familyHeadAfter: sha,
          });
          return sha;
        },
        retriggerAfterFix: () => {},
      },
      {
        initialRound: 2,
        initialFixCommitSha: "sha-r1",
        // MERGE ledger + in-process — either/or loses pre-resume history.
        enrichVerifyLanding: mergeEnrichFromLedger(familyLedger),
      },
    );

    expect(result.ok).toBe(true);
    // Resumed at r2: r2 verify, r2 fix, r3 verify, r3 fix, r4 converged
    expect(verifyLandings.length).toBeGreaterThanOrEqual(3);

    // First verify after resume is r2 — must already see r1 from ledger
    expect(verifyLandings[0]!.onlineReviewRound).toBe(2);
    expect(verifyLandings[0]!.priorRoundFindings).toMatchObject([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
    ]);

    // r3 verify must see r1 (ledger) + r2 (this-process after r2 fix) — not only r2
    const r3Verify = verifyLandings.find((l) => l.onlineReviewRound === 3);
    expect(r3Verify).toBeDefined();
    expect(r3Verify!.priorRoundFindings).toMatchObject([
      { round: 1, fixMarkedFindingIdentityKeys: ["silence:r1"] },
      { round: 2, fixMarkedFindingIdentityKeys: ["silence:r2"] },
    ]);
  });

  it("no-briefing baseline: without findingFamilies, coverage stays single-site", async () => {
    const fixerLandings: WorkerLandingPayload[] = [];
    const fixerCoverage: string[][] = [];
    const fixtures = new Map(FAMILY_SITES.map((site) => [site, false]));
    let verifyCalls = 0;

    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async (landing, round) => {
        verifyCalls += 1;
        if (round >= 2) {
          return {
            kind: "verify",
            converged: true,
            isRecheck: true,
            fixMarkedFindingIdentityKeys:
              landing.fixMarkedFindingIdentityKeys ?? [],
          } satisfies VerifyResult;
        }
        return {
          kind: "verify",
          converged: false,
          fixMarkedFindingIdentityKeys: ["silence:site-a"],
          findingDispositions: [
            {
              identityKey: "silence:site-a",
              threadId: "thread-silence",
              action: "fix",
            },
          ],
          // deliberately no findingFamilies
        } satisfies VerifyResult;
      },
      dispatchFixer: async (landing) => {
        fixerLandings.push(landing);
        mutateFixturesFromFixerLanding(landing, fixtures);
        fixerCoverage.push(coverageFromFixtures(fixtures));
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
    expect(fixerLandings[0]!.fixMarkedFindingIdentityKeys).toEqual([
      "silence:site-a",
    ]);
    // Baseline bite: no family brief ⇒ only the single marked site, not full class
    expect(fixerCoverage[0]).toEqual(["silence:site-a"]);
    expect(fixerCoverage[0]).not.toEqual([...FAMILY_SITES]);
    expect(fixerCoverage[0]!.length).toBeLessThan(FAMILY_SITES.length);
  });
});
